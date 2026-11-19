#!/usr/bin/env python3
"""Controlled hardware test: only the USB-derived address/type/nonce from --identity may connect."""
import argparse,json,socket,time
from pathlib import Path

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--port',type=int,default=8876);p.add_argument('--identity',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--general',action='store_true');args=p.parse_args()
 allow=json.loads(args.identity.read_text());nonce=allow['nonce'];nonce=list(bytes.fromhex(nonce)) if isinstance(nonce,str) else nonce
 sock=socket.create_connection(('127.0.0.1',args.port),timeout=3);sock.settimeout(.2);buf=bytearray();seq=0;session=None;events=[];connected=None;steps=[]
 def next_frame(deadline):
  nonlocal buf
  while time.monotonic()<deadline:
   if b'\n' in buf:
    line,_,tail=buf.partition(b'\n');buf=bytearray(tail);return json.loads(line)
   try:data=sock.recv(65536)
   except socket.timeout:continue
   if not data:raise ConnectionError('RPC closed')
   buf.extend(data)
  raise TimeoutError('RPC frame timeout')
 def request(method,params=None):
  nonlocal seq
  seq+=1;ident=seq;sock.sendall((json.dumps({'version':1,'sessionId':session,'id':ident,'method':method,'params':params or {}})+'\n').encode());deadline=time.monotonic()+15
  while True:
   f=next_frame(deadline)
   if f.get('type')=='event':events.append(f)
   if f.get('type')=='result' and f.get('id')==ident:
    if f.get('error'):raise RuntimeError(f['error']['code'])
    r=f['result']
    if r.get('status',0)!=0:raise RuntimeError(str(r))
    return r
 def wait_event(predicate):
  deadline=time.monotonic()+5
  while True:
   for i,e in enumerate(events):
    if predicate(e):return events.pop(i)
   f=next_frame(deadline)
   if f.get('type')=='event':events.append(f)
 try:
  hello=next_frame(time.monotonic()+3);assert hello['type']=='hello';session=hello['sessionId']
  if args.general:assert hello.get('backend')=='esp32' and hello.get('targetPolicy')=='any-device'
  old_id=None
  for round in range(2):
   request('scan.start',{'scanId':f'scan-{round}', **({'passive':bool(round)} if args.general else {})})
   e=wait_event(lambda e:e.get('event')=='advertisement' and e.get('device',{}).get('address','').upper()==allow['address'].upper() and e['device'].get('manufacturerData')==[255,255,*nonce])
   d=e['device'];assert d['address'].upper()==allow['address'].upper() and d.get('manufacturerData')==[255,255,*nonce]
   assert d.get('identity','').startswith(str(allow['addressType'])+':')
   request('scan.stop',{'scanId':f'scan-{round}'})
   cid=f'controlled-round-{round}';request('connect',{'connectionId':cid,'address':allow['address'],'addressType':allow['addressType']});connected=cid
   tree=request('discover',{'connectionId':cid})['services']
   service=next(s for s in tree if s['uuid'].startswith('0000FFF0'))
   characteristic=next(c for c in service['characteristics'] if c['uuid'].startswith('0000FFF1'))
   descriptor=next(d for d in characteristic['descriptors'] if d['uuid'].startswith('00002902'))
   char=characteristic['id'];desc=descriptor['id']
   assert request('mtu',{'connectionId':cid,'mtu':247})['mtu']>=23
   assert len(request('descriptor.read',{'connectionId':cid,'attributeId':desc})['value'])==2
   if old_id is not None:assert char!=old_id,'Connection generation was reused'
   old_id=char
   request('read',{'connectionId':cid,'attributeId':char}) # Real peripheral values may persist across connections.
   request('notification.set',{'connectionId':cid,'attributeId':char,'enabled':True})
   request('descriptor.write',{'connectionId':cid,'attributeId':desc,'value':[1,0]})
   value=[0x11,0x22,0x33,round]
   request('write',{'connectionId':cid,'attributeId':char,'value':value,'writeType':2})
   wait_event(lambda e:e.get('event')=='notification' and e.get('connectionId')==cid and e.get('value')==value)
   assert request('read',{'connectionId':cid,'attributeId':char})['value']==value
   value=[0x55,0x66,round]
   request('write',{'connectionId':cid,'attributeId':char,'value':value,'writeType':1})
   wait_event(lambda e:e.get('event')=='notification' and e.get('connectionId')==cid and e.get('value')==value)
   assert request('read',{'connectionId':cid,'attributeId':char})['value']==value
   assert isinstance(request('rssi',{'connectionId':cid})['rssi'],(int,float))
   request('scan.start',{'scanId':f'connected-scan-{round}','passive':True})
   assert request('read',{'connectionId':cid,'attributeId':char})['value']==value
   request('scan.stop',{'scanId':f'connected-scan-{round}'})
   request('notification.set',{'connectionId':cid,'attributeId':char,'enabled':False})
   request('descriptor.write',{'connectionId':cid,'attributeId':desc,'value':[0,0]})
   request('disconnect',{'connectionId':cid});request('close',{'connectionId':cid});connected=None
   steps.append(f'round {round+1}: USB identity matched, connect, GATT graph, MTU, descriptor read, read/write/notify, withoutResponse, RSSI, unsubscribe, disconnect')
  summary={'result':'PASS','target':'USB-verified user-owned ESP32-C6','rounds':2,'steps':steps,'otherDevicesConnected':0,'generationIDsRenewed':True}
  args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary))
 finally:
  if connected:
   try:request('disconnect',{'connectionId':connected})
   except Exception:pass
  sock.close()
if __name__=='__main__':main()
