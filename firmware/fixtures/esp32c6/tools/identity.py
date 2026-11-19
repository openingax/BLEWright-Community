"""Read the explicitly selected C6's read-only USB identity endpoint."""
import json
import re
import secrets
import time
import termios
import serial


class IdentityPort:
    def __init__(self, port):
        self.port = serial.Serial(port=None, baudrate=115200, timeout=0.1, exclusive=True)
        self.port.dtr = False
        self.port.rts = False
        self.port.port = port
        self.port.open()
        # Avoid a close-triggered modem hangup/reset. Opening this USB device may
        # still reboot it, so capture identity after opening and retain the port
        # through verification; never reuse a pre-open nonce.
        attrs = termios.tcgetattr(self.port.fileno())
        attrs[2] &= ~termios.HUPCL
        termios.tcsetattr(self.port.fileno(), termios.TCSANOW, attrs)
        self.buffer = bytearray()

    def read(self, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if b'\n' not in self.buffer:
                chunk = self.port.read(self.port.in_waiting or 1)
                self.buffer.extend(chunk)
                if len(self.buffer) > 8192:
                    self.buffer.clear()
                continue
            end = self.buffer.index(b'\n')
            line = bytes(self.buffer[:end])
            del self.buffer[:end+1]
            try:
                value = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            if value.get('type') != 'fixtureIdentity' or value.get('chip') != 'ESP32-C6':
                continue
            if value.get('name') != 'BLEWright-C6' or value.get('manufacturerId') != 65535:
                raise RuntimeError('Unexpected fixture identity')
            if not re.fullmatch(r'[0-9A-Fa-f]{8}', value.get('nonce', '')):
                raise RuntimeError('Invalid USB nonce')
            if not re.fullmatch(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}', value.get('address', '')):
                raise RuntimeError('Invalid USB BLE address')
            if value.get('addressType') not in (0, 1):
                raise RuntimeError('Unsupported address type')
            return value
        raise TimeoutError('No valid ESP32-C6 identity received from selected USB port')

    def read_fresh(self, timeout=8):
        # Do not trust unsolicited announcements or buffered identities. Only a
        # response to this newly generated read-only request can prove freshness.
        request_id=secrets.token_hex(16)
        self.port.write((json.dumps({'op':'identity','requestId':request_id})+'\n').encode())
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            value=self.read(timeout=max(0.1,deadline-time.monotonic()))
            if value.get('requestId')==request_id:
                return value
        raise TimeoutError('No identity response matching the fresh USB request ID')

    def close(self):
        self.port.close()


def ad_fields(raw):
    data = bytes(raw)
    offset = 0
    while offset < len(data):
        length = data[offset]
        if length == 0:
            return
        if offset + length >= len(data):
            raise ValueError('Malformed advertisement')
        yield data[offset+1], data[offset+2:offset+length+1]
        offset += length + 1


def matches_fixture(event, identity):
    if event.get('event') != 'advertisement':
        return False
    if event.get('address', '').upper() != identity['address'].upper():
        return False
    if event.get('addressType') != identity['addressType']:
        return False
    expected = b'\xff\xff' + bytes.fromhex(identity['nonce'])
    try:
        return any(kind == 0xff and value == expected for kind, value in ad_fields(event.get('advertising', [])))
    except (ValueError, TypeError):
        return False


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--c6-port', required=True)
    args = parser.parse_args()
    stream = IdentityPort(args.c6_port)
    try:
        print(json.dumps(stream.read_fresh()))
    finally:
        stream.close()
