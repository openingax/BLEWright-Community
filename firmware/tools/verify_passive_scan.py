#!/usr/bin/env python3
"""Listen for BLE advertisements only; print counts, never device identities or payloads.
No connect, cancel, disconnect, GATT or subscription command exists in this tool.
"""
import argparse
import json
import time
from serial_client import Board

ALLOWED_COMMANDS = frozenset(('hello', 'ping', 'scan.start', 'scan.stop'))


def verify(board, seconds=10):
    identities = set()
    frames = 0
    scan_id = None
    initial = board.hello

    def request(op, params=None):
        if op not in ALLOWED_COMMANDS:
            raise AssertionError('Command outside scan-only allowlist')
        response = board.request(op, params)
        if response.get('status') != 0:
            raise RuntimeError(f'{op} failed with status {response.get("status")}')
        return response

    def check_idle(hello):
        if hello.get('ready') is not True or hello.get('passiveScanSupported') is not True:
            raise RuntimeError('Board is not ready or firmware lacks passive scan support')
        if hello.get('connected') is not False or hello.get('connecting') is not False:
            raise RuntimeError('Board already has a connection or connection attempt; refusing scan')

    def observe(message):
        nonlocal frames
        if message.get('generation') != initial.get('generation'):
            raise RuntimeError('Connection generation changed during passive-only verification')
        if message.get('event') == 'advertisement' and message.get('scanId') == scan_id:
            frames += 1
            identities.add((message.get('addressType'), message.get('address')))
        elif message.get('event') not in (None, 'scanStopped', 'advertisement'):
            raise RuntimeError('Unexpected non-scan event during passive-only verification')

    check_idle(initial)
    if initial.get('scanning') is not False:
        raise RuntimeError('Another scan is already active; refusing to take it over')
    started = False
    try:
        reply = request('scan.start', {'passive': True})
        scan_id = reply['id']
        started = True
        if reply.get('passive') is not True:
            raise RuntimeError('Firmware did not confirm passive scanning')
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            for message in board.events:
                observe(message)
            board.events.clear()
            try:
                observe(board.next_message(min(0.5, deadline-time.monotonic())))
            except TimeoutError:
                continue
    finally:
        if started:
            request('scan.stop')
    for message in board.events:
        observe(message)
    board.events.clear()
    final = request('hello')
    check_idle(final)
    if final.get('scanning') is not False or final.get('generation') != initial.get('generation'):
        raise RuntimeError('Scan did not stop cleanly or connection generation changed')
    dropped = final.get('droppedFrames', 0) - initial.get('droppedFrames', 0)
    if dropped:
        raise RuntimeError(f'Firmware reported {dropped} dropped transport frames')
    if frames == 0:
        raise RuntimeError('No radio advertisements observed')
    return {'result': 'PASS', 'mode': 'passive', 'seconds': seconds,
            'advertisementFrames': frames, 'observedAddressIdentities': len(identities),
            'connectedBefore': False, 'connectedAfter': False,
            'connectionGenerationUnchanged': True, 'droppedFrames': dropped}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--seconds', type=float, default=10)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 10:
        parser.error('Use 1..10 seconds; firmware scan duration is bounded to 10 seconds')
    board = Board(args.port)
    try:
        print(json.dumps(verify(board, args.seconds), ensure_ascii=False))
    finally:
        board.close()


if __name__ == '__main__':
    main()
