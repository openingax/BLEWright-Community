#!/usr/bin/env python3
"""Exclusive serial owner with a hard scan-only allowlist. stdout is private IPC, not a log."""
import argparse,json,queue,sys,threading,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'firmware/tools'))
from serial_client import Board
ALLOWED={'scan.start','scan.stop','ping'}

def emit(value):print(json.dumps(value,separators=(',',':')),flush=True)
def main():
    p=argparse.ArgumentParser();p.add_argument('--port',required=True);args=p.parse_args()
    board=Board(args.port);commands=queue.Queue(maxsize=64);scanning=False;scan_id=None;counts={'hello':1}
    def request(op,params=None):
        if op not in ALLOWED:raise RuntimeError('SCAN_ONLY')
        counts[op]=counts.get(op,0)+1
        reply=board.request(op,params,timeout=3)
        if reply.get('status')!=0:raise RuntimeError('BOARD_'+str(reply.get('error',reply.get('status'))))
        return reply
    def read_commands():
        try:
            for line in sys.stdin:
                if len(line)>4096:raise ValueError('frame too large')
                commands.put(json.loads(line),timeout=1)
        except Exception:pass
        finally:commands.put(None)
    def forward(message):
        if message.get('event')=='advertisement' and scanning and message.get('scanId')==scan_id:
            emit({'type':'event','event':message})
        elif message.get('event')=='scanStopped' and scanning and message.get('scanId')==scan_id:
            emit({'type':'event','event':message})
        elif message.get('event') in ('connected','disconnected'):
            raise RuntimeError('Unexpected connection state in scan-only backend')
    try:
        h=board.hello
        if h.get('passiveScanSupported') is not True or h.get('ready') is not True:raise RuntimeError('PASSIVE_SCAN_FIRMWARE_REQUIRED')
        if h.get('connected') or h.get('connecting') or h.get('scanning'):raise RuntimeError('BOARD_ALREADY_IN_USE')
        emit({'type':'ready','firmware':h.get('firmware'),'passive':True,'connected':False})
        threading.Thread(target=read_commands,daemon=True).start();last_ping=time.monotonic()
        while True:
            try:command=commands.get_nowait()
            except queue.Empty:command='idle'
            if command is None:break
            if command!='idle':
                ident=command.get('id');op=command.get('method')
                if op not in ALLOWED:emit({'type':'result','id':ident,'error':'SCAN_ONLY'});continue
                if op=='scan.start':
                    r=request(op,{'passive':True})
                    if r.get('passive') is not True:raise RuntimeError('PASSIVE_SCAN_NOT_CONFIRMED')
                    scanning=True;scan_id=r['id']
                    emit({'type':'result','id':ident,'result':{'scanId':scan_id}})
                else:
                    r=request(op)
                    if op=='scan.stop':scanning=False;scan_id=None
                    emit({'type':'result','id':ident,'result':{}})
            while board.events:forward(board.events.pop(0))
            try:forward(board.next_message(.1))
            except TimeoutError:pass
            if time.monotonic()-last_ping>5:request('ping');last_ping=time.monotonic()
    finally:
        if scanning:
            try:request('scan.stop')
            except Exception:pass
        audit={'initialGeneration':board.hello.get('generation'),'connectedAtStart':board.hello.get('connected')}
        try:
            counts['hello']=counts.get('hello',0)+1
            final=board.request('hello',timeout=3)
            audit.update(finalGeneration=final.get('generation'),connectedAtEnd=final.get('connected'),connectingAtEnd=final.get('connecting'),scanningAtEnd=final.get('scanning'),droppedFrames=final.get('droppedFrames'))
        except Exception:
            audit['finalStateUnavailable']=True
        board.close()
        # Aggregate-only audit. Never print addresses, names or payloads to stderr.
        print(json.dumps({'event':'usbCommands','counts':counts,**audit}),file=sys.stderr,flush=True)
if __name__=='__main__':
    try:main()
    except Exception as e:
        emit({'type':'unavailable','reason':str(e)})
        raise SystemExit(1)
