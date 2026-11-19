"""System supervisor. One serial owner; management uses a local Unix socket, never TCP."""
import collections
import ctypes
import grp
import hashlib
import json
import os
from pathlib import Path
import pwd
import queue
import re
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
from serial.tools import list_ports

VERSION = '0.4.0'
ROOT = Path(__file__).resolve().parents[2]

def ports():
    return [dict(path=p.device, serial=p.serial_number or '', name=p.description)
            for p in list_ports.comports() if p.vid == 0x303A and p.pid == 0x1001]

def admin_peer(sock):
    uid, gid = ctypes.c_uint(), ctypes.c_uint()
    if ctypes.CDLL(None).getpeereid(sock.fileno(), ctypes.byref(uid), ctypes.byref(gid)) != 0:
        return False
    if uid.value == 0: return True
    user = pwd.getpwuid(uid.value)
    return grp.getgrnam('admin').gr_gid in os.getgrouplist(user.pw_name, user.pw_gid)

def validate_config(q):
    serial = q.get('serial', '')
    if not isinstance(serial, str) or not re.fullmatch(r'[A-Za-z0-9:_-]{1,128}', serial):
        raise ValueError('请选择带 USB 序列号的开发板')
    mode = q.get('mode', 'esp32')
    if mode not in ('esp32', 'esp32-scan', 'esp32-controlled'): raise ValueError('不支持的后端')
    result = dict(serial=serial, mode=mode, enabled=True)
    if mode == 'esp32-controlled':
        a = q.get('allow', {})
        if not isinstance(a, dict) or not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', str(a.get('address', ''))):
            raise ValueError('需要受控测试设备的 USB 身份文件')
        nonce = a.get('nonce')
        if isinstance(nonce, str) and re.fullmatch(r'[0-9a-fA-F]{8}', nonce): nonce = list(bytes.fromhex(nonce))
        if type(a.get('addressType')) is not int or a['addressType'] not in (0, 1) or not isinstance(nonce, list) or len(nonce) != 4 or any(type(v) is not int or not 0 <= v <= 255 for v in nonce):
            raise ValueError('受控测试设备身份无效')
        result['allow'] = dict(address=a['address'], addressType=a['addressType'], nonce=nonce)
    return result

class Manager:
    def __init__(self, root, state, node, python, rpc_port=None):
        self.root, self.state, self.node, self.python = Path(root), Path(state), node, python
        self.rpc_port = rpc_port
        self.state.mkdir(parents=True, exist_ok=True, mode=0o755)
        self.lock = threading.RLock()
        self.commands = queue.Queue(maxsize=1)
        self.logs = collections.deque(maxlen=160)
        self.child = None
        self.child_group = None
        self.retry_at = 0
        self.device_path = None
        self.config = {'enabled': True, 'mode': 'esp32', 'serial': ''}
        config = self.state / 'config.json'
        if config.exists(): self.config = json.loads(config.read_text())
        self.status = dict(apiVersion=1, serverVersion=VERSION, protocolVersion=1, state='waiting',
                           firmware=None, busy=False, devices=[], error=None, lastSeen=None)
        self.running = True

    def log(self, message):
        with self.lock: self.logs.append(time.strftime('%H:%M:%S ') + str(message)[:600])

    def snapshot(self):
        found = ports()
        with self.lock:
            self.status['devices'] = found
            self.status['usbConnected'] = any(p['serial'] == self.config.get('serial') for p in found)
            if self.status['usbConnected']: self.status['lastSeen'] = time.time()
            return {**self.status, 'config': {k:v for k,v in self.config.items() if k != 'allow'},
                    'rpcAddress': f'127.0.0.1:{self.effective_port}', 'logs': list(self.logs)}

    def persist(self):
        p = self.state / 'config.json.tmp'
        p.write_text(json.dumps(self.config)); p.chmod(0o600)
        p.replace(self.state / 'config.json')

    def flash_port(self, serial):
        if not isinstance(serial, str) or not re.fullmatch(r'[A-Za-z0-9:_-]{1,128}', serial):
            raise ValueError('请选择要刷写的开发板')
        matching = [p for p in ports() if p['serial'] == serial]
        if len(matching) != 1:
            raise ValueError('所选刷写开发板未连接或 USB 身份不唯一，请重新选择')
        return matching[0]['path']

    def submit(self, q):
        action = q.get('action')
        if action not in ('configure', 'start', 'stop', 'restart', 'flash'): raise ValueError('未知操作')
        if action == 'configure': q = {**q, 'config': validate_config(q)}
        with self.lock:
            if self.status['busy']: raise ValueError('已有操作进行中，请稍后再试')
            if action == 'flash': self.flash_port(q.get('serial'))
            if action == 'restart' and not self.device_path: raise ValueError('所选开发板未连接')
            self.status.update(busy=True, error=None)
            self.commands.put_nowait(q)
        return {'accepted': True}

    def stop(self):
        child, group = self.child, self.child_group
        self.child = self.child_group = None
        if child is not None:
            # Node and its Python worker share this private process group.
            try: child.send_signal(signal.SIGTERM)
            except ProcessLookupError: pass
            try: child.wait(timeout=7)
            except subprocess.TimeoutExpired: pass
            try: os.killpg(group, signal.SIGKILL)
            except ProcessLookupError: pass
            child.wait(timeout=3)
        with self.lock: self.status.update(state='stopped', firmware=None)

    @property
    def effective_port(self):
        return self.rpc_port or (8766 if self.config["mode"] == "esp32-scan" else 8876)

    def environment(self):
        return {'PATH':'/usr/bin:/bin:/usr/sbin:/sbin', 'HOME':str(self.state),
                'PYTHONUNBUFFERED':'1', 'BLEWRIGHT_PYTHON': self.python,
                'BLEWRIGHT_BACKEND': self.config['mode'], 'BLEWRIGHT_SERIAL': self.device_path or '',
                'BLEWRIGHT_PORT': str(self.effective_port)}

    def start(self):
        env = self.environment()
        if self.config['mode'] == 'esp32-controlled':
            allow = self.state / 'allow.json'; allow.write_text(json.dumps(self.config['allow'])); allow.chmod(0o600)
            env['BLEWRIGHT_ALLOW_FILE'] = str(allow)
        if self.config['mode'] in ('esp32', 'esp32-controlled') and self.rpc_port is None:
            env['BLEWRIGHT_SCAN_PORT'] = '8766'
        child = subprocess.Popen([self.node, str(self.root/'mac/service/main.js')], env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        self.child, self.child_group = child, child.pid
        with self.lock: self.status.update(state='starting', firmware=None)
        threading.Thread(target=self.read_log, args=(child,), daemon=True).start()

    def read_log(self, child):
        for line in iter(child.stdout.readline, b''):
            try: event = json.loads(line)
            except (ValueError, UnicodeDecodeError): continue
            kind = event.get('event')
            with self.lock:
                if child is not self.child: continue
                if kind == 'boardReady': self.status['firmware'] = event.get('firmware')
                if kind == 'listening': self.status.update(state='ready', error=None)
                if kind in ('startupError', 'serverError', 'backendUnavailable'):
                    self.status.update(state='error', error=event.get('message', event.get('reason')))
                # Never retain advertisement values, target identities, reads or writes.
                if kind in ('boardReady','listening','startupError','serverError','backendUnavailable','sessionClosed'):
                    self.log(kind + ': ' + str(event.get('message', event.get('reason', ''))))

    def maintenance(self, action, serial=None):
        port = self.device_path
        if action == 'flash': self.flash_port(serial)
        self.stop()
        # Resolve again after releasing the worker: USB may have re-enumerated.
        if action == 'flash': port = self.flash_port(serial)
        with self.lock: self.status['state'] = 'flashing' if action == 'flash' else 'restarting'
        prefix = [self.python, '--esptool'] if getattr(sys, 'frozen', False) else [self.python, '-m', 'esptool']
        args = prefix + ['--chip', 'esp32s3', '--port', port, '--after', 'hard_reset']
        if action == 'flash':
            bundle = self.root/'firmware/release'
            manifest = json.loads((bundle/'manifest.json').read_text())
            args += ['write_flash', '--flash_mode', 'dio', '--flash_freq', '80m', '--flash_size', 'keep']
            for entry in manifest['files']:
                path = bundle / entry['file']
                if path.parent != bundle or hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
                    raise ValueError('内置固件校验失败')
                args += [entry['offset'], str(path)]
        else: args += ['run']
        self.log('开始刷写内置 S3 固件' if action == 'flash' else '开始重启 S3')
        # stdout is a bounded on-disk temporary log, not the USB stream owned by the RPC worker.
        output = self.state/'maintenance.log'
        with output.open('wb') as f:
            process = subprocess.Popen(args, stdout=f, stderr=subprocess.STDOUT, env=self.environment(), start_new_session=True)
            deadline = time.monotonic() + 120
            with output.open('r', errors='replace') as reader:
                while process.poll() is None:
                    for line in reader.readlines(): self.log(line.strip())
                    if time.monotonic() > deadline:
                        os.killpg(process.pid, signal.SIGKILL); process.wait(); raise RuntimeError('操作超时；请重新连接设备后重试')
                    time.sleep(.2)
                for line in reader.readlines(): self.log(line.strip())
            code = process.returncode
        if code: raise RuntimeError('设备操作失败；查看日志。必要时按住 BOOT 接入 USB 后重试。')
        self.log('操作完成，等待 USB 重新枚举及固件握手')
        self.retry_at = time.monotonic() + 3

    def tick(self):
        found = ports()
        matching = [p for p in found if p['serial'] == self.config.get('serial')]
        selected = matching[0]['path'] if len(matching) == 1 else None
        if selected != self.device_path:
            self.stop(); self.device_path = selected; self.retry_at = 0
            self.log('所选 USB 设备已接入' if selected else '所选 USB 设备已断开，旧会话已关闭')
        with self.lock:
            self.status['devices'] = found
            if selected: self.status['lastSeen'] = time.time()
        if self.child and self.child.poll() is not None:
            self.stop(); self.retry_at = time.monotonic() + 5
        if not self.config.get('enabled'):
            if self.child: self.stop()
            with self.lock: self.status['state'] = 'stopped'
        elif not selected:
            with self.lock: self.status.update(state='waiting', firmware=None)
        elif not self.child and time.monotonic() >= self.retry_at:
            self.start()

    def run(self):
        while self.running:
            try:
                try: q = self.commands.get(timeout=1)
                except queue.Empty: q = None
                if q:
                    try:
                        a = q['action']
                        if a == 'configure':
                            self.stop(); self.config = q['config']; self.persist(); self.retry_at = 0
                        elif a in ('start','stop'):
                            self.config['enabled'] = a == 'start'; self.persist()
                            if a == 'stop': self.stop()
                            else: self.retry_at = 0
                        else: self.maintenance(a, q.get('serial'))
                    except Exception as e:
                        # A failed flash must not repeatedly claim readiness or auto-flash.
                        self.config['enabled'] = False; self.persist()
                        with self.lock: self.status.update(state='error', error=str(e))
                        self.log(e)
                    finally:
                        with self.lock: self.status['busy'] = False
                self.tick()
            except Exception as e:
                self.log(e)
                with self.lock: self.status.update(state='error', error=str(e))
                time.sleep(1)
        self.stop()

class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(3)
        try:
            line = self.rfile.readline(16385)
            if len(line) > 16384 or not line.endswith(b'\n'): raise ValueError('请求过大')
            q = json.loads(line)
            if q.get('apiVersion') != 1: raise ValueError('管理 API 版本不兼容')
            if q.get('action') == 'status': result = self.server.manager.snapshot()
            else:
                if not admin_peer(self.connection): raise PermissionError('此操作需要管理员用户；普通用户可查看状态')
                result = self.server.manager.submit(q)
            response = dict(ok=True, result=result)
        except Exception as e: response = dict(ok=False, error=str(e))
        self.wfile.write(json.dumps(response, ensure_ascii=False).encode() + b'\n')

class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    request_queue_size = 16

def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--root', default=str(ROOT)); p.add_argument('--state', default='/Library/Application Support/BLEWright')
    p.add_argument('--socket', default='/var/run/blewright/control.sock')
    p.add_argument('--node', default='/Library/Application Support/BLEWright/runtime/node')
    p.add_argument('--python', default=sys.executable); p.add_argument('--port', type=int)
    a = p.parse_args()
    path = Path(a.socket); path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    # Lock the supervisor before removing a stale socket; two daemons cannot own a board.
    import fcntl
    lock = (path.parent/'manager.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    path.unlink(missing_ok=True)
    manager = Manager(a.root, a.state, a.node, a.python, a.port)
    server = Server(str(path), Handler); server.manager = manager; path.chmod(0o666)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    for sig in (signal.SIGTERM, signal.SIGINT): signal.signal(sig, lambda *_: setattr(manager, 'running', False))
    try: manager.run()
    finally: server.shutdown(); server.server_close(); path.unlink(missing_ok=True)

if __name__ == '__main__': main()
