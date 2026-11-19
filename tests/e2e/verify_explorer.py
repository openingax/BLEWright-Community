#!/usr/bin/env python3
"""Exercise the installed explorer UI against a dedicated mock service. No USB/BLE hardware access.
Requires an already running API-35 emulator and Frida Server. Only the explorer's
permissions/process are changed. Stops its own processes.
"""
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
OUT = ROOT / 'dist/tests/explorer'
OUT.mkdir(parents=True, exist_ok=True)
ADB = [str(Path.home()/'Library/Android/sdk/platform-tools/adb'), '-s', args.serial]


def adb(*args):
    return subprocess.check_output([*ADB, *args], text=True, timeout=20).strip()


def dump():
    adb('shell', 'uiautomator', 'dump', '/sdcard/blewright-explorer.xml')
    xml = adb('shell', 'cat', '/sdcard/blewright-explorer.xml')
    (OUT/'latest.xml').write_text(xml)
    return list(ET.fromstring(xml).iter('node'))


def find(value, field='content-desc', timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for node in dump():
            if value in node.get(field, ''):
                return node
    raise AssertionError(f'UI element absent: {field}={value}')


def click(value, field='content-desc'):
    node = find(value, field)
    assert node.get('enabled') == 'true', f'Disabled: {value}'
    x1, y1, x2, y2 = map(int, re.findall(r'\d+', node.get('bounds')))
    adb('shell', 'input', 'tap', str((x1+x2)//2), str((y1+y2)//2))


def shot(name):
    with (OUT/f'{name}.png').open('wb') as file:
        subprocess.run([*ADB, 'exec-out', 'screencap', '-p'], stdout=file, check=True)


def passed(message):
    print('PASS: ' + message, flush=True)
    results.append(message)


def launch(port):
    log = (OUT/'launcher.log').open('w')
    child = subprocess.Popen([sys.executable, 'android/launcher/run.py', '--serial', args.serial,
                              '--package', PACKAGE, '--rpc-port', str(port)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        if 'RPC active in this process only' in (OUT/'launcher.log').read_text():
            return child, log
        if child.poll() is not None:
            raise RuntimeError((OUT/'launcher.log').read_text())
        time.sleep(.2)
    child.terminate()
    raise RuntimeError('Injection timeout')


def device_log():
    return adb('logcat', '-d', '--pid='+pid, '-s', 'BLEExplorer:I', '*:S')


def expect_log(text):
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        if text in device_log():
            return
        time.sleep(.15)
    raise AssertionError('Missing callback: '+text)


def write(value):
    click('write')
    click('write-hex')
    adb('shell', 'input', 'text', value)
    click('send-write')


results = []
service = client = None
client_log = None
service_file = (OUT/'service.jsonl').open('w')
try:
    assert adb('shell', 'getprop', 'ro.kernel.qemu') == '1'
    assert adb('shell', 'getprop', 'ro.build.version.sdk') == '35'
    # Reset only the standalone explorer's permission decisions for reproducible UI testing.
    adb('shell', 'am', 'force-stop', PACKAGE)
    for permission in ['android.permission.BLUETOOTH_SCAN', 'android.permission.BLUETOOTH_CONNECT']:
        adb('shell', 'pm', 'revoke', PACKAGE, permission)
        adb('shell', 'pm', 'clear-permission-flags', PACKAGE, permission, 'user-set', 'user-fixed')
    service = subprocess.Popen(['node', 'mac/service/main.js'], cwd=ROOT,
        env={**os.environ, 'BLEWRIGHT_BACKEND': 'mock', 'BLEWRIGHT_PORT': '0'},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    first = service.stdout.readline()
    service_file.write(first); service_file.flush()
    port = json.loads(first)['port']
    def record_service():
        for line in service.stdout:
            service_file.write(line); service_file.flush()
    threading.Thread(target=record_service, daemon=True).start()
    client, client_log = launch(port)
    pid = adb('shell', 'pidof', PACKAGE)
    assert find('scan-toggle').get('enabled') == 'false'
    click('grant-permissions')
    click('permission_deny_button', 'resource-id')
    find('adapter-status: 需要附近设备权限')
    assert find('scan-toggle').get('enabled') == 'false'
    click('grant-permissions')
    click('permission_allow_button', 'resource-id')
    find('adapter-status: 蓝牙可用')
    passed('permission denied, then granted through the system dialog')
    click('scan-toggle')
    find('connect-02:00:00:00:00:01')
    shot('scan')
    click('scan-toggle')
    find('scan-status: 扫描已手动停止')
    click('scan-toggle')
    find('connect-02:00:00:00:00:01')
    passed('scan, stop, restart and real native ScanResult display')
    click('connect-02:00:00:00:00:01')
    find('connection-status: 已连接 · 1 个服务')
    click('read')
    find('characteristic-value: 42 4C 45')
    passed('connect, service/characteristic/descriptor discovery and native read callback')
    click('write')
    click('write-hex'); adb('shell', 'input', 'text', 'GG')
    click('send-write')
    find('write-hex')  # Invalid hex keeps the dialog open and must not reach RPC.
    assert '写入请求' not in device_log()
    click('取消', 'text')
    write('0102FF')
    expect_log('写入回调 · 状态码 0')
    click('read')
    find('characteristic-value: 01 02 FF')
    passed('invalid input rejected; write and read-back match')
    click('subscribe')
    find('subscription-status: on')
    write('414243')
    expect_log('收到通知 · 0000fff1-0000-1000-8000-00805f9b34fb · 41 42 43')
    find('characteristic-value: 41 42 43')
    shot('detail')
    click('subscribe')
    find('subscription-status: off')
    notifications = device_log().count('收到通知')
    write('444546')
    click('read')
    find('characteristic-value: 44 45 46')
    assert device_log().count('收到通知') == notifications
    passed('CCCD subscribe, server-origin notification and unsubscribe suppresses notifications')
    write('00' * 21)
    expect_log('写入回调 · 状态码 13')
    click('read'); find('characteristic-value: 44 45 46')
    passed('oversize GATT write reports failure without changing the value; next read succeeds')
    click('tab-logs'); find('operation-log'); shot('logs')
    click('tab-detail'); click('disconnect')
    find('connection-status: 已主动断开')
    click('reconnect'); find('connection-status: 已连接 · 1 个服务')
    click('read'); find('characteristic-value: 42 4C 45')
    passed('disconnect and reconnect use a new connection with fresh service/value state')
    adb('shell', 'input', 'keyevent', 'KEYCODE_HOME')
    expect_log('已断开：离开页面')
    adb('shell', 'am', 'start', '--activity-single-top', '-n', PACKAGE+'/.MainActivity')
    find('connection-status: 已断开：离开页面')
    click('reconnect'); find('connection-status: 已连接 · 1 个服务')
    passed('leaving the app closes the connection; returning allows reconnect')
    service.terminate(); service.wait(timeout=5)
    find('adapter-status: 蓝牙不可用')
    find('connection-status: 已断开')
    shot('service-lost')
    click('tab-scan')
    assert find('scan-toggle').get('enabled') == 'false'
    passed('mock service loss disconnects the app and disables scanning')
    (OUT/'native-callbacks.log').write_text(device_log())
    (OUT/'results.json').write_text(json.dumps({'passed': results, 'backend': 'mock', 'serial': args.serial, 'hardware': False}, ensure_ascii=False, indent=2))
finally:
    if client and client.poll() is None:
        client.send_signal(signal.SIGINT)
        try: client.wait(timeout=10)
        except subprocess.TimeoutExpired: client.kill(); client.wait()
    if service and service.poll() is None:
        service.terminate(); service.wait(timeout=5)
    if client_log: client_log.close()
    service_file.close()
