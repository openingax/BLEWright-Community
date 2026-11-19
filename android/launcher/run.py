#!/usr/bin/env python3
"""Connect the Mac RPC service and inject the Android BLE adapter into one API-35 process."""
import argparse
import json
import re
from pathlib import Path
import subprocess
import sys
import threading
import time
from rpc_relay import RpcRelay, PROTOCOL

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True, help='adb/frida emulator ID, e.g. emulator-5554')
    parser.add_argument('--package', default='space.nomoloop.blewright.explorer')
    parser.add_argument('--require-backend', choices=['esp32', 'esp32-controlled'], help='Require the actual injection session to use the selected hardware backend')
    parser.add_argument('--probe', action='store_true', help='Load public-API DEX probe and exit with PASS/FAIL')
    parser.add_argument('--rpc-port', type=int, default=PROTOCOL['defaultPort'], help='Mac loopback BLEWright RPC port')
    parser.add_argument('--fault-probe', action='store_true', help='Wait for service shutdown and verify native disconnect/scan failure')
    parser.add_argument('--hardware-probe', action='store_true', help='Verify the exact allowlisted C6 through an existing BLEWright service')
    parser.add_argument('--scan-probe', action='store_true', help='Verify read-only hardware scanning without GATT operations')
    parser.add_argument('--target-identity', type=Path, help='Fresh C6 USB identity for hardware tests against the general service; never configures server policy')
    args = parser.parse_args()
    if sum((args.hardware_probe, args.fault_probe, args.scan_probe)) > 1:
        parser.error('Select only one probe scenario')
    args.probe = args.probe or args.fault_probe or args.hardware_probe or args.scan_probe
    target = None
    if args.target_identity:
        if not args.hardware_probe:
            parser.error('--target-identity is only for --hardware-probe')
        target = json.loads(args.target_identity.read_text())
        if not re.fullmatch(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}', str(target.get('address', ''))) or not re.fullmatch(r'[0-9A-Fa-f]{8}', str(target.get('nonce', ''))):
            parser.error('Hardware test requires the C6 USB address and nonce')

    def adb(*items):
        return subprocess.check_output(['adb', '-s', args.serial, *items], text=True).strip()

    if adb('shell', 'getprop', 'ro.kernel.qemu') != '1':
        parser.error('Only emulators are allowed; refusing a physical device')
    if adb('shell', 'getprop', 'ro.build.version.sdk') != '35':
        parser.error('This prototype requires Android 15 / API 35')
    agent = ROOT / 'dist/android/agent.js'
    if not agent.is_file():
        parser.error('Build the agent first: npm ci && npm run build')
    if args.probe:
        dex = ROOT / 'dist/tests/android/probe/classes.dex'
        if not dex.is_file():
            parser.error('Compile the probe first: npm run build:probe')
        remote = '/data/local/tmp/blewright-probe.dex'
        adb('push', str(dex), remote)
        adb('shell', 'chmod', '444', remote)

    import frida
    device = frida.get_device(args.serial, timeout=5)
    relay = RpcRelay(args.rpc_port)
    info = relay.hello
    print(json.dumps({'event': 'blewrightService', 'port': args.rpc_port,
                      **{key: info.get(key) for key in ('serverVersion', 'backend', 'capabilities')} }), flush=True)
    if args.require_backend:
        required = {'scan', 'connect', 'discover', 'read', 'write', 'notify'}
        capabilities = info.get('capabilities', [])
        valid_capabilities = isinstance(capabilities, list) and all(isinstance(item, str) for item in capabilities)
        if info.get('backend') != args.require_backend or not valid_capabilities or not required.issubset(capabilities):
            relay.close()
            parser.error('Workstation backend changed or lacks required BLE capabilities; refusing injection')
    controlled = info.get('backend') == 'esp32-controlled' and info.get('targetPolicy') == 'exact-allowlist'
    general = info.get('backend') == 'esp32' and info.get('targetPolicy') == 'any-device'
    if args.hardware_probe and not (controlled or (general and target)):
        relay.close()
        parser.error('Hardware probe requires BLEWright esp32-controlled with exact-allowlist, or esp32 with --target-identity')
    if args.scan_probe and info.get('backend') != 'esp32-scan':
        relay.close()
        parser.error('Scan probe requires BLEWright esp32-scan')
    ready, failed = threading.Event(), threading.Event()

    def message(msg, data):
        payload = msg.get('payload', {})
        if isinstance(payload, dict) and payload.get('event') == 'rpcRequest':
            relay.send(payload['request'])
            return
        print(json.dumps(msg, ensure_ascii=False), flush=True)
        if payload.get('event') == 'rpcUnavailable':
            relay.close()
        if payload.get('event') == 'ready':
            ready.set()
        if msg.get('type') == 'error' or payload.get('event') in ('installError', 'callbackError'):
            failed.set()
            ready.set()

    pid, session = None, None
    try:
        pid = device.spawn([args.package])
        session = device.attach(pid)
        script = session.create_script("globalThis.BLEWRIGHT_SESSION = " + json.dumps(relay.hello["sessionId"]) + ";\n" + agent.read_text())
        script.on('message', message)
        script.load()
        relay.start(script)
        device.resume(pid)
        if not ready.wait(20) or failed.is_set():
            raise RuntimeError('Hook installation failed or timed out; inspect installError above')
        if args.probe:
            deadline = time.monotonic() + 10
            while not script.exports_sync.application_ready():
                if time.monotonic() >= deadline:
                    raise RuntimeError('Application context did not become ready')
                time.sleep(0.05)
            kind = "c6" if args.hardware_probe else "scan" if args.scan_probe else "loss" if args.fault_probe else "normal"
            print(script.exports_sync.probe(remote, kind, target), flush=True)
            deadline = time.monotonic() + (60 if args.hardware_probe else 20)
            checkpoint_printed = False
            while time.monotonic() < deadline and not failed.is_set():
                result = script.exports_sync.probe_result()
                if result == 'CONNECTED_WAITING_FOR_SERVICE_LOSS' and not checkpoint_printed:
                    print(result, flush=True)
                    checkpoint_printed = True
                if result.startswith(('PASS:', 'FAIL:')):
                    print(result, flush=True)
                    return 0 if result.startswith('PASS:') else 1
                time.sleep(0.2)
            raise RuntimeError('Native probe timed out or callback failed')
        print('RPC active in this process only. Ctrl-C stops this launched process.', flush=True)
        while not failed.wait(1):
            pass
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        relay.close()
        # Stop the process launched by this tool; do not leave cached mock objects alive
        # after removing the hooks. No persistent system Bluetooth settings are changed.
        if pid is not None:
            try:
                device.kill(pid)
            except Exception as cleanup_error:
                # Frida exposes concrete exception classes, not frida.Error. Cleanup
                # must never replace the original spawn/attach/probe failure.
                print(f'BLEWright cleanup: {cleanup_error}', file=sys.stderr)
        if session is not None:
            try:
                session.detach()
            except Exception as cleanup_error:
                # Frida exposes concrete exception classes, not frida.Error. Cleanup
                # must never replace the original spawn/attach/probe failure.
                print(f'BLEWright cleanup: {cleanup_error}', file=sys.stderr)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        print(f'BLEWright failed: {error}', file=sys.stderr)
        sys.exit(1)
