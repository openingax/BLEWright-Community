#!/usr/bin/env python3
"""BLEWright S3 framed serial client. Never retries a mutating request automatically."""
import argparse
import binascii
import json
import time
import secrets
import serial

MAX_PAYLOAD = 3072


def encode(message):
    payload = json.dumps(message, separators=(',', ':')).encode()
    if len(payload) > MAX_PAYLOAD:
        raise ValueError('payload too large')
    return f'@BW1 {len(payload):04X} {binascii.crc32(payload):08X} '.encode() + payload + b'\n'


def decode(line):
    if not line.startswith(b'@BW1 ') or len(line) < 20 or not line.endswith(b'\n'):
        raise ValueError('not a frame')
    length, crc = int(line[5:9], 16), int(line[10:18], 16)
    payload = line[19:-1]
    if line[9:10] != b' ' or line[18:19] != b' ' or length != len(payload) or length > MAX_PAYLOAD:
        raise ValueError('bad length')
    if binascii.crc32(payload) != crc:
        raise ValueError('bad CRC')
    return json.loads(payload)


class Board:
    def __init__(self, port):
        self.serial = serial.Serial(port=None, baudrate=115200, timeout=0.1, exclusive=True)
        self.serial.dtr = False
        self.serial.rts = False
        self.serial.port = port
        self.serial.open()
        self.sequence = secrets.randbelow(1 << 24) + 1
        self.boot_id = None
        self.generation = 0
        self.events = []
        self.buffer = bytearray()
        self.discard_line = False
        hello = self.request('hello', timeout=5)
        self.boot_id = hello['bootId']
        self.generation = hello['generation']
        self.sequence = max(self.sequence, hello.get('lastId', 0))
        self.hello = hello

    def close(self):
        self.serial.close()

    def next_message(self, timeout=1):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if b'\n' not in self.buffer:
                chunk = self.serial.read(self.serial.in_waiting or 1)
                if not chunk:
                    continue
                self.buffer.extend(chunk)
                if len(self.buffer) > MAX_PAYLOAD + 21 and b'\n' not in self.buffer:
                    self.buffer.clear()
                    self.discard_line = True
                continue
            index = self.buffer.index(b'\n')
            line = bytes(self.buffer[:index + 1])
            del self.buffer[:index + 1]
            if self.discard_line:
                self.discard_line = False
                continue
            try:
                message = decode(line)
            except (ValueError, json.JSONDecodeError):
                continue  # Boot/log noise is never accepted as protocol traffic.
            if self.boot_id and message['bootId'] != self.boot_id:
                raise RuntimeError('Board rebooted; reopen and explicitly reconnect, do not replay writes')
            self.generation = message.get('generation', self.generation)
            return message
        raise TimeoutError('No complete frame from board')

    def request(self, op, params=None, timeout=12):
        self.sequence += 1
        request = {'v': 1, 'id': self.sequence, 'op': op, 'params': params or {}}
        if self.boot_id:
            request.update(bootId=self.boot_id, generation=self.generation)
        self.serial.write(encode(request))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            message = self.next_message(max(0.1, deadline-time.monotonic()))
            if message.get('type') == 'result' and message.get('id') == self.sequence:
                return message
            self.events.append(message)
        raise TimeoutError(f'{op} timed out; outcome unknown, request is not replayed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--scan', type=float, default=0)
    args = parser.parse_args()
    board = Board(args.port)
    try:
        print(json.dumps(board.hello))
        if args.scan:
            print(json.dumps(board.request('scan.start')))
            deadline = time.monotonic() + args.scan
            while time.monotonic() < deadline:
                try:
                    print(json.dumps(board.next_message(0.5)))
                except TimeoutError:
                    pass
            print(json.dumps(board.request('scan.stop')))
    finally:
        board.close()


if __name__ == '__main__':
    main()
