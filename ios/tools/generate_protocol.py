#!/usr/bin/env python3
"""Generate the distributable ObjC header from the shared protocol definition."""
import argparse,json
from pathlib import Path
root=Path(__file__).resolve().parents[2]
p=root/'ios/Sources/SimulatorBLE/BWProtocol.generated.h'
data=json.loads((root/'protocol/constants.json').read_text())
body='// Generated from protocol/constants.json. Do not edit.\n#pragma once\n'
for key,name in [('version','VERSION'),('defaultPort','PORT'),('maxFrameBytes','MAX_FRAME'),('requestTimeoutMs','TIMEOUT_MS'),('heartbeatIntervalMs','HEARTBEAT_MS')]:
 body+=f'#define BW_RPC_{name} {int(data[key])}\n'
for key,name in [('connect','CONNECT'),('discover','DISCOVER'),('session.end','END_SESSION')]:
 body+=f'#define BW_RPC_{name}_TIMEOUT_MS {int(data["requestTimeoutsMs"][key])}\n'
a=argparse.ArgumentParser();a.add_argument('--check',action='store_true');args=a.parse_args()
if args.check:
 if not p.exists() or p.read_text()!=body:raise SystemExit('Regenerate with python3 ios/tools/generate_protocol.py')
else:p.write_text(body)
