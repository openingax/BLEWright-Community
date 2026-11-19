#!/usr/bin/env python3
"""Build the standalone native API-35 explorer with the installed Android SDK."""
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parent
SDK = Path(os.environ.get('ANDROID_SDK_ROOT', str(Path.home() / 'Library/Android/sdk')))
JAVA = Path(os.environ.get('JAVA_HOME') or subprocess.check_output(['/usr/libexec/java_home'], text=True).strip())
TOOLS = SDK / 'build-tools/36.0.0'
JAR = SDK / 'platforms/android-35/android.jar'
OUT = ROOT.parents[1] / 'dist/android/explorer'
OUT.mkdir(parents=True, exist_ok=True)
CLASSES = OUT / 'classes'
if CLASSES.exists():
    shutil.rmtree(CLASSES)
CLASSES.mkdir()

def run(args):
    subprocess.run(list(map(str, args)), check=True, env={**os.environ, 'JAVA_HOME': str(JAVA)})

run([JAVA/'bin/javac', '-encoding', 'UTF-8', '-source', '8', '-target', '8', '-Xlint:-options', '-classpath', JAR, '-d', CLASSES, *sorted((ROOT/'src').rglob('*.java'))])
run([TOOLS/'d8', '--lib', JAR, '--min-api', '35', '--output', OUT, *sorted(CLASSES.rglob('*.class'))])
unsigned = OUT/'unsigned.apk'
run([TOOLS/'aapt2', 'compile', '--dir', ROOT/'res', '-o', OUT/'resources.zip'])
run([TOOLS/'aapt2', 'link', '-I', JAR, '--manifest', ROOT/'AndroidManifest.xml', '-o', unsigned, OUT/'resources.zip'])
with zipfile.ZipFile(unsigned, 'a') as archive:
    archive.write(OUT/'classes.dex', 'classes.dex')
run([TOOLS/'zipalign', '-f', '4', unsigned, OUT/'aligned.apk'])
key = OUT/'debug.keystore'
if not key.exists():
    run([JAVA/'bin/keytool', '-genkeypair', '-keystore', key, '-storepass', 'android', '-keypass', 'android', '-alias', 'androiddebugkey', '-dname', 'CN=BLEExplorer Debug', '-keyalg', 'RSA', '-validity', '3650'])
apk = OUT/'blewright-explorer.apk'
run([TOOLS/'apksigner', 'sign', '--ks', key, '--ks-pass', 'pass:android', '--out', apk, OUT/'aligned.apk'])
run([TOOLS/'apksigner', 'verify', apk])
print(apk)
