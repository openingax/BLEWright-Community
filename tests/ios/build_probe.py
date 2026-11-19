#!/usr/bin/env python3
"""Build the standalone iOS probe; require an explicitly selected simulator."""
import argparse, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--simulator',required=True);args=p.parse_args()
 out=ROOT/'dist/ios';(out/'project').mkdir(parents=True,exist_ok=True)
 subprocess.run(['python3',str(ROOT/'ios/tools/generate_protocol.py'),'--check'],check=True)
 subprocess.run(['xcodegen','generate','--spec',str(ROOT/'tests/ios/project.yml'),'--project',str(out/'project')],check=True)
 with (out/'build.log').open('w') as log:
  r=subprocess.run(['xcodebuild','-project',str(out/'project/BLEWrightIOSProbe.xcodeproj'),'-scheme','BLEWrightIOSProbe','-configuration','Debug','-destination',f'id={args.simulator}','-derivedDataPath',str(out/'DerivedData'),'CODE_SIGNING_ALLOWED=NO','build'],stdout=log,stderr=subprocess.STDOUT)
 if r.returncode:raise SystemExit(f'Build failed: {out / "build.log"}')
 print(out/'DerivedData/Build/Products/Debug-iphonesimulator/BLEWrightIOSProbe.app')
if __name__=='__main__':main()
