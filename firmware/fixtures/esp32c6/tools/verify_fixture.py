#!/usr/bin/env python3
"""Connect only the C6 identified by its selected USB port + BLE address/type/boot nonce."""
import argparse
import json
import sys
import time
from pathlib import Path
from identity import IdentityPort, matches_fixture

# Reuse the existing S3 wire client, never its old Mac-peripheral test program.
FIRMWARE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(FIRMWARE/'tools'))
from serial_client import Board


def uuid_is(value, short):
    return value.lower().replace('0x', '') in (short.lower(), '0000'+short.lower()+'-0000-1000-8000-00805f9b34fb')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--c6-port', required=True)
    parser.add_argument('--s3-port', required=True)
    parser.add_argument('--prepare-gate', type=Path, help='Capture a fresh wired identity, then wait for this new gate file before connecting')
    args = parser.parse_args()
    if args.c6_port == args.s3_port:
        parser.error('C6 and S3 must be different, previously identified ports')
    identity_port = IdentityPort(args.c6_port)
    board = None
    connected = False
    steps = []

    def mark(text):
        steps.append(text)
        print(json.dumps({'pass': text}), flush=True)

    def call(op, params=None):
        response = board.request(op, params)
        if response.get('status') != 0:
            raise RuntimeError(f'{op} status={response.get("status")} error={response.get("error")}')
        return response

    try:
        identity = identity_port.read_fresh()
        identity_path=Path(__file__).resolve().parents[1]/'build/identity.json'
        identity_path.parent.mkdir(parents=True,exist_ok=True)
        if identity_path.exists() and not args.prepare_gate:
            expected=json.loads(identity_path.read_text())
            if any(identity[field] != expected[field] for field in ('address','addressType','nonce')):
                raise RuntimeError('USB identity differs from prepared identity.json; no connection attempted')
        identity_path.write_text(json.dumps(identity,indent=2)+'\n')
        if args.prepare_gate:
            if args.prepare_gate.exists():
                raise RuntimeError('Gate must not exist before preparation')
            print(json.dumps({'preparedIdentity':{k:identity[k] for k in ('address','addressType','nonce')},'identityPath':str(identity_path)}),flush=True)
            deadline=time.monotonic()+90
            while not args.prepare_gate.exists():
                if time.monotonic()>deadline:
                    raise TimeoutError('Preparation gate was not released; no connection attempted')
                time.sleep(0.1)
        if not identity.get('advertising') or identity.get('connected'):
            raise RuntimeError('Selected C6 is not advertising idle; refusing to take over')
        board = Board(args.s3_port)
        if board.hello.get('connected') is not False or board.hello.get('connecting') is not False:
            raise RuntimeError('S3 is already in a connection; refusing to take over')
        if board.hello.get('passiveScanSupported') is not True:
            raise RuntimeError('S3 needs passive-scan-capable firmware')
        reply = call('scan.start', {'passive': True})
        assert reply.get('passive') is True
        deadline = time.monotonic()+8
        matched = False
        try:
            while time.monotonic() < deadline:
                try:
                    frame = board.next_message(0.5)
                except TimeoutError:
                    continue
                if frame.get('scanId') == reply['id'] and matches_fixture(frame, identity):
                    matched = True
                    break
        finally:
            call('scan.stop')
        if not matched:
            raise RuntimeError('No advertisement matching the USB C6 address/type/nonce; no connection attempted')
        mark('passive advertisement matches USB-proven C6 address, address type and boot nonce')
        # Refresh the wired identity immediately before issuing the only connect target.
        fresh = identity_port.read_fresh()
        for field in ('address', 'addressType', 'nonce'):
            if fresh[field] != identity[field]:
                raise RuntimeError('C6 identity changed during scan; no connection attempted')
        call('connect', {'address': identity['address'], 'addressType': identity['addressType']})
        connected = True
        mark('connect only to the identified ESP32-C6')
        board.events.clear(); call('services')
        service = next(e for e in board.events if e.get('event')=='service' and uuid_is(e['uuid'], 'fff0'))
        board.events.clear(); call('characteristics', {'start':service['start'], 'end':service['end']})
        chars = [e for e in board.events if e.get('event')=='characteristic']
        characteristic = next(e for e in chars if uuid_is(e['uuid'], 'fff1'))
        following = [e['definitionHandle']-1 for e in chars if e['definitionHandle']>characteristic['handle']]
        board.events.clear(); call('descriptors', {'start':characteristic['handle'], 'end':min(following, default=service['end'])})
        cccd = next(e for e in board.events if e.get('event')=='descriptor' and uuid_is(e['uuid'], '2902'))
        mark('FFF0 / FFF1 discovery and NimBLE-generated CCCD')
        initial = call('read', {'handle':characteristic['handle']})['data']['value']
        if identity['writes'] == 0:
            assert initial == [66,76,69], 'fresh boot initial value must be ASCII BLE'
        mark('read real C6 characteristic (fresh boot initial BLE checked when untouched)')
        call('write', {'handle':characteristic['handle'], 'value':[1,2,3,4]})
        assert call('read', {'handle':characteristic['handle']})['data']['value'] == [1,2,3,4]
        mark('with-response write and identical readback')
        board.events.clear(); call('write', {'handle':cccd['handle'], 'value':[1,0]})
        expected = [5,6,7,8]
        call('write', {'handle':characteristic['handle'], 'value':expected})
        notified = any(e.get('event')=='notification' and e.get('handle')==characteristic['handle'] and e.get('value')==expected for e in board.events)
        deadline = time.monotonic()+3
        while not notified and time.monotonic() < deadline:
            try:
                event = board.next_message(0.5)
            except TimeoutError:
                continue
            notified = event.get('event')=='notification' and event.get('handle')==characteristic['handle'] and event.get('value')==expected
        assert notified, 'No C6 radio notification'
        mark('CCCD subscribe and real BLE echo notification')
        call('write', {'handle':cccd['handle'], 'value':[0,0]})
        call('write', {'handle':characteristic['handle'], 'value':[9,10], 'withoutResponse':True})
        assert call('read', {'handle':characteristic['handle']})['data']['value'] == [9,10]
        mark('unsubscribe and without-response write/read')
        call('disconnect'); connected=False
        mark('disconnect completes; C6 resumes advertising')
        # Release C6 USB, then use a new passive scan to prove its captured nonce
        # still exists on air. This does not reconnect any device.
        identity_port.close()
        reply=call('scan.start',{'passive':True})
        stable=False;deadline=time.monotonic()+5
        try:
            while time.monotonic()<deadline:
                try:frame=board.next_message(0.5)
                except TimeoutError:continue
                if frame.get('scanId')==reply['id'] and matches_fixture(frame,identity):
                    stable=True;break
        finally:call('scan.stop')
        assert stable,'C6 nonce changed after USB close; do not reuse identity.json'
        mark('C6 USB released; fresh passive advertisement retains the prepared nonce')
        print(json.dumps({'result':'PASS', 'steps':steps, 'connectedTargets':1, 'target':'USB-identified ESP32-C6 only'}), flush=True)
    finally:
        if board:
            if connected:
                try: board.request('disconnect')
                except Exception: pass
            board.close()
        identity_port.close()


if __name__ == '__main__':
    main()
