#!/usr/bin/env python3
"""Run the installed explorer against an isolated mock backend, with no hardware access."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--serial', required=True, help='Running API-35 emulator ID from adb devices')
args = parser.parse_args()
service = client = None
try:
    service = subprocess.Popen(['node', 'mac/service/main.js'], cwd=ROOT,
        env={**os.environ, 'BLEWRIGHT_BACKEND': 'mock', 'BLEWRIGHT_PORT': '0'},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    first = service.stdout.readline()
    ready = json.loads(first)
    if ready.get('event') != 'listening':
        raise RuntimeError(first)
    print(f"BLEExplorer mock · localhost:{ready['port']} · 不访问 ESP32", flush=True)
    def drain():
        for line in service.stdout:
            if 'error' in line.lower():
                print(line, end='', flush=True)
    threading.Thread(target=drain, daemon=True).start()
    client = subprocess.Popen([sys.executable, 'android/launcher/run.py', '--serial', args.serial,
        '--package', 'space.nomoloop.blewright.explorer', '--rpc-port', str(ready['port'])], cwd=ROOT)
    code = client.wait()
except KeyboardInterrupt:
    code = 0
finally:
    if client and client.poll() is None:
        client.send_signal(signal.SIGINT)
        try: client.wait(timeout=10)
        except subprocess.TimeoutExpired: client.kill(); client.wait()
    if service and service.poll() is None:
        service.terminate()
        try: service.wait(timeout=5)
        except subprocess.TimeoutExpired: service.kill(); service.wait()
sys.exit(code)
