#!/usr/bin/env python3
"""Run native emulator probes against dedicated Mac RPC server processes.
Requires an already booted API-35 emulator, Frida Server and installed debug host.
"""
import argparse
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'dist/tests/results'


def pump(stream, messages, path):
    with path.open('w') as file:
        for line in stream:
            file.write(line)
            file.flush()
            messages.put(line)
    messages.put(None)


def run_case(serial, name, fault=None):
    service_queue, client_queue = queue.Queue(), queue.Queue()
    service = subprocess.Popen(['node', 'mac/service/main.js'], cwd=ROOT,
                               env={**os.environ, 'BLEWRIGHT_PORT': '0', 'BLEWRIGHT_BACKEND': 'mock'},
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    service_thread = threading.Thread(target=pump, args=(service.stdout, service_queue, OUT / f'{name}-service.jsonl'), daemon=True)
    service_thread.start()
    client = None
    stopped = False
    try:
        first = service_queue.get(timeout=5)
        ready = json.loads(first)
        assert ready['event'] == 'listening', first
        port = ready['port']
        command = [sys.executable, str(ROOT / 'android/launcher/run.py'), '--serial', serial,
                   '--package', 'space.nomoloop.blewright.host', '--rpc-port', str(port),
                   '--fault-probe' if fault else '--probe']
        client = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        client_thread = threading.Thread(target=pump, args=(client.stdout, client_queue, OUT / f'{name}-client.log'), daemon=True)
        client_thread.start()
        deadline = time.monotonic() + 40
        passed = False
        injected = False
        while time.monotonic() < deadline:
            line = client_queue.get(timeout=max(0.1, deadline - time.monotonic()))
            if line is None:
                break
            if fault and not injected and 'CONNECTED_WAITING_FOR_SERVICE_LOSS' in line:
                injected = True
                if fault == 'stop':
                    service.send_signal(signal.SIGSTOP)
                    stopped = True
                else:
                    service.terminate()
            if line.startswith('PASS:'):
                passed = True
                print(f'{name}: {line.strip()}', flush=True)
            if 'FAIL:' in line or 'BLEWright failed:' in line:
                print(line.strip(), flush=True)
        code = client.wait(timeout=5)
        client_thread.join(timeout=2)
        if not passed or code != 0 or (fault and not injected):
            raise RuntimeError(f'{name} failed; see {OUT}/{name}-client.log')
        return port
    finally:
        if client and client.poll() is None:
            client.kill()
            client.wait(timeout=5)
        if stopped:
            service.send_signal(signal.SIGCONT)
        if service.poll() is None:
            service.terminate()
        service.wait(timeout=5)
        service_thread.join(timeout=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--output', type=Path, help='Optional evidence output directory; defaults to dist/tests/results')
    args = parser.parse_args()
    global OUT
    if args.output:
        OUT = args.output.resolve()
    OUT.mkdir(parents=True, exist_ok=True)
    run_case(args.serial, 'rpc-normal')
    entries = [json.loads(line) for line in (OUT / 'rpc-normal-service.jsonl').read_text().splitlines()]
    methods = {e.get('method') for e in entries if e.get('direction') == 'in'}
    required = {'scan.start', 'scan.stop', 'connect', 'discover', 'read', 'write', 'notification.set', 'descriptor.write', 'disconnect', 'close'}
    assert required <= methods, f'Missing server operations: {required - methods}'
    assert any(e.get('event') == 'notification' and e.get('value') == [1, 2, 3, 4] for e in entries), 'No server-origin notification'
    run_case(args.serial, 'rpc-disconnect', 'terminate')
    port = run_case(args.serial, 'rpc-timeout', 'stop')
    # No listener now: the launcher must fail, never use its old in-process fixture.
    absent = subprocess.run([sys.executable, str(ROOT/'android/launcher/run.py'), '--serial', args.serial,
                             '--package', 'space.nomoloop.blewright.host', '--probe', '--rpc-port', str(port)],
                            cwd=ROOT, capture_output=True, text=True, timeout=15)
    (OUT/'rpc-unavailable-client.log').write_text(absent.stdout+absent.stderr)
    assert absent.returncode != 0 and 'Connection refused' in absent.stderr, 'Missing-service startup did not fail as expected'
    print('rpc-unavailable: PASS: service absence fails startup; no local fallback', flush=True)


if __name__ == '__main__':
    main()
