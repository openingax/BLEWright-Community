#!/usr/bin/env python3
"""Read-only workstation preflight, then launch the native explorer on its hardware RPC."""
import argparse
import json
import os
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parents[2]
CONTROL = '/var/run/blewright/control.sock'
REQUIRED = {'scan', 'connect', 'discover', 'read', 'write', 'notify'}


def read_frame(stream):
    line = stream.readline(65538)
    if not line or len(line) > 65537 or not line.endswith(b'\n'):
        raise ValueError('工作站返回了无效或过大的消息')
    result = json.loads(line)
    if not isinstance(result, dict):
        raise ValueError('工作站返回的消息不是对象')
    return result


def status(path=CONTROL):
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(3)
        connection.connect(path)
        connection.sendall(b'{"apiVersion":1,"action":"status"}\n')
        with connection.makefile('rb') as stream:
            response = read_frame(stream)
    if response.get('ok') is not True or not isinstance(response.get('result'), dict):
        raise ValueError('读取工作站状态失败：' + str(response.get('error', '无有效结果')))
    return response['result']


def endpoint(snapshot):
    if snapshot.get('apiVersion') != 1 or snapshot.get('protocolVersion') != 1:
        raise ValueError('工作站管理 API 或 BLE 协议版本不兼容')
    config = snapshot.get('config', {})
    if not config.get('serial'):
        raise ValueError('请先在 BLEWright 工作站选择并绑定 ESP32-S3')
    if not config.get('enabled') or snapshot.get('state') == 'stopped':
        raise ValueError('工作站服务已停止；请在 BLEWright 中手动启动')
    if snapshot.get('busy'):
        raise ValueError('工作站正在维护或切换配置，请稍后重试')
    if snapshot.get('state') == 'error':
        raise ValueError('工作站异常：' + str(snapshot.get('error') or '请查看工作站日志'))
    if not snapshot.get('usbConnected'):
        raise ValueError('ESP32-S3 尚未连接；软件入口已准备好，接上已绑定板卡并等待工作站就绪后重试')
    if snapshot.get('state') != 'ready':
        raise ValueError('工作站尚未就绪（' + str(snapshot.get('state')) + '），请等待固件握手完成')
    mode = config.get('mode')
    if mode == 'esp32-scan':
        raise ValueError('工作站处于只读扫描模式，不能完整测试 GATT；请在工作站选择通用 BLE 并应用设置')
    if mode not in ('esp32', 'esp32-controlled'):
        raise ValueError('正式对接仅接受工作站硬件后端，不使用 mock 替代')
    address = snapshot.get('rpcAddress', '')
    if not isinstance(address, str) or not address.startswith('127.0.0.1:'):
        raise ValueError('仅允许工作站报告的本机 RPC 地址')
    try:
        port = int(address.partition(':')[2])
        if not 1 <= port <= 65535: raise ValueError()
    except (ValueError, IndexError):
        raise ValueError('工作站 RPC 端口无效') from None
    return port, mode


def check_rpc(port, expected):
    # Hello only: no scan/connect/write, no hardware ownership acquisition.
    with socket.create_connection(('127.0.0.1', port), timeout=3) as connection:
        with connection.makefile('rb') as stream:
            hello = read_frame(stream)
    if hello.get('type') != 'hello' or hello.get('version') != 1 or not isinstance(hello.get('sessionId'), str):
        raise ValueError('RPC 握手协议不兼容')
    if hello.get('backend') != expected:
        raise ValueError('RPC 后端与工作站配置不一致，拒绝启动')
    capabilities = hello.get('capabilities', [])
    if not isinstance(capabilities, list) or not all(isinstance(item, str) for item in capabilities):
        raise ValueError('RPC 能力信息无效')
    missing = REQUIRED - set(capabilities)
    if missing:
        raise ValueError('RPC 缺少必要能力：' + ', '.join(sorted(missing)))
    return hello


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', help='adb devices 中的 API 35 模拟器序列号')
    parser.add_argument('--check', action='store_true', help='仅检查工作站，不启动或注入 App')
    args = parser.parse_args()
    if not args.check and not args.serial:
        parser.error('启动需要 --serial；只查看对接状态请使用 --check')
    try:
        snapshot = status()
        print(json.dumps({key: snapshot.get(key) for key in ('serverVersion', 'state', 'usbConnected', 'rpcAddress')}, ensure_ascii=False), flush=True)
        port, backend = endpoint(snapshot)
        hello = check_rpc(port, backend)
        print(f"工作站对接检查通过：{hello.get('serverVersion', '未知版本')} / {backend} / 127.0.0.1:{port}", flush=True)
    except (OSError, ValueError) as error:
        print('BLEExplorer：' + str(error), file=sys.stderr)
        return 2
    if args.check:
        return 0
    # The launcher rechecks the actual injection session, avoiding a stale preflight result.
    command = [sys.executable, str(ROOT/'android/launcher/run.py'), '--serial', args.serial,
               '--package', 'space.nomoloop.blewright.explorer', '--rpc-port', str(port),
               '--require-backend', backend]
    env = {**os.environ}
    sdk = Path(os.environ.get('ANDROID_SDK_ROOT', str(Path.home()/'Library/Android/sdk')))
    env['PATH'] = str(sdk/'platform-tools') + os.pathsep + env.get('PATH', '')
    os.execve(sys.executable, command, env)


if __name__ == '__main__':
    sys.exit(main())
