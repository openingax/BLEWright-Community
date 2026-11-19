#!/usr/bin/env python3
"""Exercise only the BLEWright-HW peripheral fixture, never arbitrary nearby devices."""
import argparse
import json
import time
from serial_client import Board, encode


def name_of(data):
    data=bytes(data);offset=0
    while offset<len(data):
        length=data[offset]
        if not length or offset+length>=len(data):break
        if data[offset+1] in (8,9):return data[offset+2:offset+length+1].decode(errors='replace')
        offset+=length+1
    return None


def uuid_is(value,short):
    return value.lower().replace('0x','') in (short.lower(), '0000'+short.lower()+'-0000-1000-8000-00805f9b34fb')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--port',required=True);args=parser.parse_args()
    board=Board(args.port);connected=False;steps=[]
    def call(op,params=None):
        response=board.request(op,params)
        if response['status']!=0:raise RuntimeError(f'{op}: {response}')
        return response
    def mark(text):steps.append(text);print(json.dumps({'pass':text}),flush=True)
    try:
        assert board.hello['ready'];mark('framed hello / CRC / boot ID')
        call('scan.start');deadline=time.monotonic()+8;device=None
        while time.monotonic()<deadline:
            try:message=board.next_message(0.5)
            except TimeoutError:continue
            if message.get('event')=='advertisement' and name_of(message['advertising'])=='BLEWright-HW':device=message;break
        call('scan.stop')
        assert device is not None,'Start the dedicated BLEWright-HW Mac peripheral first'
        mark('real BLE scan finds named fixture; stop succeeds')
        call('connect',{'address':device['address'],'addressType':device['addressType']});connected=True
        mark('real BLE connection')
        board.sequence += 1
        board.serial.write(encode({'v':1,'id':board.sequence,'op':'read','params':{'handle':1},'bootId':board.boot_id,'generation':board.generation-1}))
        stale=board.next_message(2)
        assert stale.get('error')=='STALE_GENERATION',stale
        assert board.request('read',{'handle':70000}).get('error')=='INVALID_RANGE'
        mark('stale generation and invalid handle rejected before BLE execution')
        board.events.clear();call('services')
        service=next(e for e in board.events if e.get('event')=='service' and uuid_is(e['uuid'],'fff0'))
        board.events.clear();call('characteristics',{'start':service['start'],'end':service['end']})
        chars=[e for e in board.events if e.get('event')=='characteristic']
        characteristic=next(e for e in chars if uuid_is(e['uuid'],'fff1'))
        following=[e['definitionHandle']-1 for e in chars if e['definitionHandle']>characteristic['handle']]
        board.events.clear();call('descriptors',{'start':characteristic['handle'],'end':min(following,default=service['end'])})
        cccd=next(e for e in board.events if e.get('event')=='descriptor' and uuid_is(e['uuid'],'2902'))
        mark('service / characteristic / descriptor discovery with real ATT handles')
        value=[1,2,3,4]
        call('write',{'handle':characteristic['handle'],'value':value})
        assert call('read',{'handle':characteristic['handle']})['data']['value']==value
        mark('with-response write and identical readback')
        board.events.clear();call('write',{'handle':cccd['handle'],'value':[1,0]})
        value=[5,6,7,8];call('write',{'handle':characteristic['handle'],'value':value})
        deadline=time.monotonic()+3;notified=any(e.get('event')=='notification' and e.get('value')==value for e in board.events)
        while not notified and time.monotonic()<deadline:
            try:message=board.next_message(0.5)
            except TimeoutError:continue
            print(json.dumps({'received':message}),flush=True)
            notified=message.get('event')=='notification' and message.get('handle')==characteristic['handle'] and message.get('value')==value
        assert notified,f'No real radio notification received; prior events={board.events}'
        mark('CCCD subscription and real BLE notification')
        call('write',{'handle':cccd['handle'],'value':[0,0]})
        call('write',{'handle':characteristic['handle'],'value':[9,10],'withoutResponse':True})
        assert call('read',{'handle':characteristic['handle']})['data']['value']==[9,10]
        mark('unsubscribe and without-response write/read')
        call('mtu');call('rssi');mark('MTU exchange and RSSI')
        call('disconnect');connected=False;mark('disconnect completes with generation change')
        assert board.request('read',{'handle':characteristic['handle']}).get('error')=='NOT_CONNECTED'
        mark('read after disconnect rejected')
        board.serial.write(encode({'v':1,'id':board.sequence,'op':'scan.start','params':{},'bootId':board.boot_id,'generation':board.generation}))
        replay=board.next_message(2)
        assert replay.get('error')=='REPLAY',replay
        mark('duplicate mutating request rejected without replay')
        call('connect',{'address':device['address'],'addressType':device['addressType']});connected=True
        # macOS may close a newly reconnected, unused link. Establish a fresh
        # GATT subscription so this test measures host lease expiry, not that policy.
        board.events.clear();call('services')
        fresh_service=next(e for e in board.events if e.get('event')=='service' and uuid_is(e['uuid'],'fff0'))
        board.events.clear();call('characteristics',{'start':fresh_service['start'],'end':fresh_service['end']})
        fresh_char=next(e for e in board.events if e.get('event')=='characteristic' and uuid_is(e['uuid'],'fff1'))
        board.events.clear();call('descriptors',{'start':fresh_char['handle'],'end':fresh_service['end']})
        fresh_cccd=next(e for e in board.events if e.get('event')=='descriptor' and uuid_is(e['uuid'],'2902'))
        call('write',{'handle':fresh_cccd['handle'],'value':[1,0]})
        expired=False;gone=False;deadline=time.monotonic()+18
        while time.monotonic()<deadline and not (expired and gone):
            try:message=board.next_message(0.5)
            except TimeoutError:continue
            print(json.dumps({'leaseReceived':message}),flush=True)
            expired=expired or message.get('event')=='leaseExpired'
            gone=gone or message.get('event')=='disconnected'
        assert expired and gone,'Host silence did not release BLE connection'
        connected=False
        assert board.request('read',{'handle':characteristic['handle']}).get('error')=='NOT_CONNECTED'
        mark('15-second host lease expires and releases the radio connection')
        assert board.request('hello')['droppedFrames']==0
        print(json.dumps({'result':'PASS','steps':steps,'bootId':board.boot_id,'generation':board.generation}),flush=True)
    finally:
        if connected:
            try:board.request('disconnect')
            except Exception:pass
        board.close()


if __name__=='__main__':main()
