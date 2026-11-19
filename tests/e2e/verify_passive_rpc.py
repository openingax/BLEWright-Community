#!/usr/bin/env python3
"""Observe scan-only RPC advertisements. Never sends connect or GATT commands; saves aggregates only."""
import argparse,collections,json,socket,time
from pathlib import Path

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--port',type=int,default=8766);p.add_argument('--seconds',type=float,default=12);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 if not 1<=a.seconds<=30:raise SystemExit('Use a bounded 1–30 second scan')
 sock=socket.create_connection(('127.0.0.1',a.port),timeout=3);sock.settimeout(.25);buffer=bytearray();session=None;seq=0;commands=[];frames=0;ids=set();named=set();services=set();manufacturer=set();rssis=[];stopped=False;late=0
 def receive(deadline):
  nonlocal buffer
  while time.monotonic()<deadline:
   if b'\n' in buffer:
    line,_,rest=buffer.partition(b'\n');buffer=bytearray(rest);return json.loads(line)
   try:part=sock.recv(65536)
   except socket.timeout:continue
   if not part:raise ConnectionError('RPC disconnected')
   buffer.extend(part)
  return None
 def send(method):
  nonlocal seq
  assert method in ('scan.start','scan.stop','ping')
  seq+=1;commands.append(method);sock.sendall((json.dumps({'version':1,'sessionId':session,'id':seq,'method':method,'params':{'scanId':'passive-observation'}})+'\n').encode());return seq
 try:
  hello=receive(time.monotonic()+3);assert hello and hello['type']=='hello';session=hello['sessionId'];send('scan.start')
  end=time.monotonic()+a.seconds
  while time.monotonic()<end:
   f=receive(end)
   if not f:continue
   if f.get('error'):raise RuntimeError(f['error']['code'])
   if f.get('event')!='advertisement':continue
   d=f['device'];identity=d.get('identity',d['address']);frames+=1;ids.add(identity);rssis.append(d['rssi'])
   if d.get('name'):named.add(identity)
   if d.get('serviceUUIDs'):services.add(identity)
   if d.get('manufacturerData'):manufacturer.add(identity)
  stop_id=send('scan.stop');end=time.monotonic()+4
  while time.monotonic()<end:
   f=receive(end)
   if f and f.get('type')=='result' and f.get('id')==stop_id:
    assert not f.get('error');stopped=True;break
  assert stopped,'Stop was not acknowledged'
  end=time.monotonic()+.5
  while time.monotonic()<end:
   f=receive(end)
   if f and f.get('event')=='advertisement':late+=1
  summary={'scanSeconds':a.seconds,'advertisementEvents':frames,'temporaryIdentities':len(ids),'namedIdentities':len(named),'serviceUUIDIdentities':len(services),'manufacturerIdentities':len(manufacturer),'rssiRange':[min(rssis),max(rssis)] if rssis else [],'eventsAfterStop':late,'commands':commands,'connectCommands':0}
  assert frames>0 and late==0,summary
  a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary))
 finally:
  if session and not stopped:
   try:send('scan.stop')
   except Exception:pass
  sock.close()
if __name__=='__main__':main()
