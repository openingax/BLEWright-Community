#!/usr/bin/env python3
"""Verify Android against the existing BLEWright workstation; never manages USB or firmware."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--scan-only', action='store_true')
    parser.add_argument('--rpc-port', type=int)
    parser.add_argument('--target-identity', type=Path, help='Fresh C6 USB identity; required when testing the general backend')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/tests/android-hardware-verification')
    args = parser.parse_args()
    port = args.rpc_port or (8766 if args.scan_only else 8876)
    args.output.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, str(ROOT / 'android/launcher/run.py'),
               '--serial', args.serial, '--package', 'space.nomoloop.blewright.host',
               '--rpc-port', str(port), '--scan-probe' if args.scan_only else '--hardware-probe']
    if args.target_identity:
        command += ['--target-identity', str(args.target_identity.resolve())]
    name = 'scan-only' if args.scan_only else 'controlled-c6'
    log = args.output / (name + '.log')
    try:
        run = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=85)
        output = run.stdout + run.stderr
        passed = run.returncode == 0 and any(line.startswith('PASS:') for line in run.stdout.splitlines())
        log.write_text(output)
        summary = dict(scenario=name, port=port, passed=passed, exitCode=run.returncode,
                       evidence=str(log), scope='Android native API probe through the BLEWright service')
        (args.output / (name + '.json')).write_text(json.dumps(summary, indent=2))
        for line in output.splitlines():
            if line.startswith(('PASS:', 'FAIL:', 'BLEWright failed:')):
                print(line)
        print(json.dumps(summary))
        return 0 if passed else 1
    except subprocess.TimeoutExpired as error:
        log.write_text(str(error))
        print('FAIL: launcher timeout; inspect ' + str(log), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
