#!/usr/bin/env python3
"""Controlled C6 worker. Exact USB-derived allow config is required before opening S3."""
import argparse,json,queue,sys,threading,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'firmware/tools'))
from serial_client import Board
from engine import ControlledEngine,validate_allow,OpenTargetPolicy

def emit(value):print(json.dumps(value,separators=(',',':')),flush=True)
def main():
    p=argparse.ArgumentParser();p.add_argument('--port',required=True)
    policy=p.add_mutually_exclusive_group(required=True)
    policy.add_argument('--allow-json');policy.add_argument('--general',action='store_true');args=p.parse_args()
    allow=None if args.general else validate_allow(json.loads(args.allow_json))
    board=Board(args.port);engine=None;commands=queue.Queue(maxsize=64)
    def reader():
        try:
            for line in sys.stdin:
                if len(line)>8192:raise ValueError('COMMAND_TOO_LARGE')
                commands.put(json.loads(line),timeout=1)
        finally:commands.put(None)
    try:
        engine=ControlledEngine(board,allow,emit,policy=OpenTargetPolicy() if args.general else None)
        emit({'type':'ready','firmware':board.hello.get('firmware'),'controlled':not args.general,'connected':False})
        threading.Thread(target=reader,daemon=True).start();last_ping=time.monotonic()
        while True:
            try:q=commands.get_nowait()
            except queue.Empty:q='idle'
            if q is None:break
            if q!='idle':engine.command(q)
            while board.events:engine.on_message(board.events.pop(0))
            try:engine.on_message(board.next_message(.05))
            except TimeoutError:pass
            engine.tick()
            if time.monotonic()-last_ping>5:engine.health();last_ping=time.monotonic()
    finally:
        if engine:
            try:engine.cleanup()
            except Exception:pass
            print(json.dumps({'event':'usbCommands','mode':'general' if args.general else 'controlled-c6','counts':engine.counts,'connectedAtEnd':engine.owned,'generation':engine.generation}),file=sys.stderr,flush=True)
        board.close()
if __name__=='__main__':
    try:main()
    except Exception as error:
        emit({'type':'unavailable','reason':str(error)})
        raise SystemExit(1)
