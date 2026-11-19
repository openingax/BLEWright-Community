#!/usr/bin/env python3
"""Compile a public-API probe into DEX; does not build/install an APK or start an emulator."""
from pathlib import Path
import os, subprocess
root = Path(__file__).resolve().parent
sdk = Path(os.environ.get('ANDROID_SDK_ROOT', str(Path.home() / 'Library/Android/sdk')))
java = os.environ.get('JAVA_HOME') or subprocess.check_output(['/usr/libexec/java_home'], text=True).strip()
out = root.parents[1] / 'dist/tests/android/probe'
classes = out / 'classes'
classes.mkdir(parents=True, exist_ok=True)
# Remove stale inner classes from previous versions of the probe only.
for item in classes.rglob('*.class'):
    item.unlink()
jar = sdk / 'platforms/android-35/android.jar'
subprocess.run([str(Path(java)/'bin/javac'), '-source','8','-target','8','-Xlint:-options','-classpath',str(jar),'-d',str(classes),*map(str,(root/'probe').rglob('*.java'))], check=True)
subprocess.run([str(sdk/'build-tools/36.0.0/d8'),'--lib',str(jar),'--min-api','35','--output',str(out),*map(str,classes.rglob('*.class'))],check=True,env={**os.environ,'JAVA_HOME':java})
print(out/'classes.dex')
