#!/usr/bin/env python3
"""UI regression for scan retry, connect cancellation, busy controls and timeout using mock only."""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = 'space.nomoloop.blewright.explorer'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--serial', required=True)
args = parser.parse_args()
ADB = [str(Path.home()/'Library/Android/sdk/platform-tools/adb'), '-s', args.serial]
OUT = ROOT/'dist/tests/explorer/edges'
OUT.mkdir(parents=True, exist_ok=True)

def adb(*parts):
    return subprocess.check_output([*ADB, *parts], text=True, timeout=20).strip()

def find(value, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        adb('shell', 'uiautomator', 'dump', '/sdcard/blewright-explorer-edge.xml')
        xml = adb('shell', 'cat', '/sdcard/blewright-explorer-edge.xml')
        (OUT/'latest.xml').write_text(xml)
        for node in ET.fromstring(xml).iter('node'):
            if value in node.get('content-desc', ''): return node
    raise AssertionError('Missing UI: '+value)

def tap(node):
    x1,y1,x2,y2 = map(int, re.findall(r'\d+', node.get('bounds')))
    adb('shell', 'input', 'tap', str((x1+x2)//2), str((y1+y2)//2))

def click(value):
    node = find(value)
    assert node.get('enabled') == 'true', value
    tap(node)

def run(mode):
    service = client = None
    pump_thread = None
    with (OUT/f'{mode}-service.jsonl').open('w') as service_log, (OUT/f'{mode}-client.log').open('w') as client_log:
        try:
            service = subprocess.Popen(['node', 'tests/e2e/explorer_fault_service.mjs', mode], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            first = service.stdout.readline(); service_log.write(first); service_log.flush()
            port = json.loads(first)['port']
            def pump():
                for line in service.stdout: service_log.write(line); service_log.flush()
            pump_thread = threading.Thread(target=pump, daemon=True); pump_thread.start()
            client = subprocess.Popen([sys.executable, 'android/launcher/run.py', '--serial', args.serial, '--package', PACKAGE, '--rpc-port', str(port)], cwd=ROOT, stdout=client_log, stderr=subprocess.STDOUT)
            deadline = time.monotonic()+25
            while 'RPC active' not in (OUT/f'{mode}-client.log').read_text():
                assert client.poll() is None, (OUT/f'{mode}-client.log').read_text()
                assert time.monotonic() < deadline, 'Injection timeout'
                time.sleep(.2)
            click('scan-toggle')
            if mode == 'retry':
                find('scan-status: 扫描失败')
                click('scan-toggle')
            click('connect-02:00:00:00:00:01')
            if mode == 'retry':
                click('disconnect')
                find('connection-status: 已主动断开')
                # Wait beyond the canceled connect's delayed response and verify it stays closed.
                time.sleep(6)
                find('connection-status: 已主动断开')
                click('reconnect')
                find('connection-status: 已连接 · 1 个服务')
                read = find('read'); tap(read); tap(read)  # A rapid duplicate cannot start a second GATT request.
                assert find('write').get('enabled') == 'false'
                find('characteristic-value: 42 4C 45')
                requests = [json.loads(line) for line in (OUT/f'{mode}-service.jsonl').read_text().splitlines()]
                assert sum(item.get('direction') == 'in' and item.get('method') == 'read' for item in requests) == 1
                click('disconnect'); click('tab-scan'); click('scan-toggle')
                find('scan-status: 扫描结束', timeout=22)
                print('PASS: scan error/retry, cancel pending connect, suppress late callback, reconnect, busy/duplicate action and automatic scan stop', flush=True)
            else:
                find('connection-status: 发现服务超时', timeout=20)
                assert find('reconnect').get('enabled') == 'true'
                requests = [json.loads(line) for line in (OUT/f'{mode}-service.jsonl').read_text().splitlines()]
                assert any(item.get('direction') == 'in' and item.get('method') == 'close' for item in requests)
                print('PASS: discovery timeout closes the connection and offers manual retry', flush=True)
            with (OUT/f'{mode}.png').open('wb') as image:
                subprocess.run([*ADB, 'exec-out', 'screencap', '-p'], stdout=image, check=True)
        finally:
            if client and client.poll() is None:
                client.send_signal(signal.SIGINT)
                try: client.wait(timeout=10)
                except subprocess.TimeoutExpired: client.kill(); client.wait()
            if service and service.poll() is None: service.terminate(); service.wait(timeout=5)
            if pump_thread: pump_thread.join(timeout=2)

assert adb('shell','getprop','ro.kernel.qemu') == '1'
assert adb('shell','getprop','ro.build.version.sdk') == '35'
for permission in ['android.permission.BLUETOOTH_SCAN', 'android.permission.BLUETOOTH_CONNECT']:
    adb('shell','pm','grant',PACKAGE,permission)
run('retry')
run('timeout')
