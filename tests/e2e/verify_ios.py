#!/usr/bin/env python3
"""Verify CoreBluetooth calls against independent Mac RPC sessions on a booted iOS simulator."""
import argparse,json,os,re,signal,socket,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
BUNDLE='space.nomoloop.blewright.iosprobe'
def sim(*args,check=True,env=None):
 return subprocess.run(['xcrun','simctl',*args],capture_output=True,text=True,check=check,env=env)
def case(udid,out,name,mode='normal',fault=None,unavailable=False):
 service=None;stopped=False;port=None
 service_log=(out/f'{name}-service.jsonl').open('w')
 reserved=None
 try:
  if unavailable:
   reserved=socket.socket();reserved.bind(('127.0.0.1',0));port=reserved.getsockname()[1]
  else:
   service=subprocess.Popen(['node','mac/service/main.js'],cwd=ROOT,env={**os.environ,'BLEWRIGHT_PORT':'0','BLEWRIGHT_BACKEND':'mock'},stdout=service_log,stderr=subprocess.STDOUT)
   deadline=time.monotonic()+5
   while time.monotonic()<deadline:
    lines=(out/f'{name}-service.jsonl').read_text().splitlines()
    if lines:
     hello=json.loads(lines[0]);assert hello['event']=='listening';port=hello['port'];break
    if service.poll() is not None:raise RuntimeError('Mac service failed to start')
    time.sleep(.05)
   if port is None:raise TimeoutError('Mac service startup')
  sim('terminate',udid,BUNDLE,check=False)
  data=Path(sim('get_app_container',udid,BUNDLE,'data').stdout.strip())
  result=data/'Documents/probe-result.txt';result.unlink(missing_ok=True)
  env={**os.environ,'SIMCTL_CHILD_BLEWRIGHT_ENABLE':'1','SIMCTL_CHILD_BLEWRIGHT_PORT':str(port),'SIMCTL_CHILD_BLEWRIGHT_PROBE_MODE':mode}
  launch=sim('launch',f'--stdout={out/name}.stdout.log',f'--stderr={out/name}.stderr.log','--terminate-running-process',udid,BUNDLE,env=env)
  (out/f'{name}-launch.log').write_text(launch.stdout+launch.stderr)
  deadline=time.monotonic()+22;injected=False
  while time.monotonic()<deadline:
   text=result.read_text() if result.exists() else ''
   if fault and not injected and text=='CONNECTED_WAITING_FOR_SERVICE_LOSS':
    injected=True
    if fault=='stop':service.send_signal(signal.SIGSTOP);stopped=True
    else:service.terminate()
   if text.startswith(('PASS:','FAIL:')):
    (out/f'{name}-result.txt').write_text(text+'\n');print(f'{name}: {text}',flush=True)
    if not text.startswith('PASS:'):raise RuntimeError(text)
    if fault and not injected:raise RuntimeError('fault not injected')
    # Keep process alive briefly: a successful callback must not hide a release-time crash.
    time.sleep(.3)
    match=re.search(r": (\d+)",launch.stdout)
    if not match:raise RuntimeError("Missing simulator process ID")
    os.kill(int(match.group(1)),0)
    return
   time.sleep(.08)
  raise TimeoutError(f'{name}: no PASS result; see {out}')
 finally:
  sim('terminate',udid,BUNDLE,check=False)
  if reserved:reserved.close()
  if service:
   if stopped:service.send_signal(signal.SIGCONT)
   if service.poll() is None:service.terminate()
   service.wait(timeout=5)
  service_log.close()
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--simulator',required=True);p.add_argument('--output',type=Path,default=ROOT/'dist/tests/ios-results');args=p.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
 devices=json.loads(sim('list','devices','available','--json').stdout)['devices']
 assert any(d['udid']==args.simulator and d['state']=='Booted' for group in devices.values() for d in group),'Choose a booted simulator UDID'
 app=ROOT/'dist/ios/DerivedData/Build/Products/Debug-iphonesimulator/BLEWrightIOSProbe.app'
 assert app.is_dir(),'Run npm run build:ios -- --simulator <UDID> first'
 sim('install',args.simulator,str(app))
 case(args.simulator,out,'ios-normal')
 entries=[json.loads(line) for line in (out/'ios-normal-service.jsonl').read_text().splitlines()]
 methods={e.get('method') for e in entries if e.get('direction')=='in'}
 assert {'scan.start','scan.stop','connect','mtu','discover','read','write','notification.set','descriptor.write','disconnect','close'}<=methods
 assert any(e.get('event')=='notification' and e.get('value')==[5,6,7] for e in entries),'No server-origin withoutResponse notification'
 assert any(e.get('result',{}).get('status')==13 for e in entries),'Oversize write did not reach backend'
 case(args.simulator,out,'ios-disconnect',mode='loss',fault='terminate')
 case(args.simulator,out,'ios-timeout',mode='loss',fault='stop')
 case(args.simulator,out,'ios-unavailable',mode='unavailable',unavailable=True)
if __name__=='__main__':main()
