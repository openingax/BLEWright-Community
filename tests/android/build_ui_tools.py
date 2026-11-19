#!/usr/bin/env python3
"""Build a shell uiautomator test JAR; no additional APK is installed on the phone."""
import os
from pathlib import Path
import shutil
import subprocess
import zipfile
ROOT=Path(__file__).resolve().parents[2]
SDK=Path(os.environ.get('ANDROID_SDK_ROOT',str(Path.home()/'Library/Android/sdk')))
JAVA=Path(os.environ.get('JAVA_HOME') or subprocess.check_output(['/usr/libexec/java_home'],text=True).strip())
TOOLS=SDK/'build-tools/36.0.0';PLATFORM=SDK/'platforms/android-35'
LIBS=[PLATFORM/'android.jar',PLATFORM/'uiautomator.jar',PLATFORM/'optional/android.test.base.jar',PLATFORM/'optional/android.test.runner.jar']
SOURCE=ROOT/'tests/android/ui-tools';OUT=ROOT/'dist/tests/android/ui-tools';OUT.mkdir(parents=True,exist_ok=True)
classes=OUT/'classes'
if classes.exists():shutil.rmtree(classes)
classes.mkdir()
def run(args):subprocess.run(list(map(str,args)),check=True,env={**os.environ,'JAVA_HOME':str(JAVA)})
run([JAVA/'bin/javac','-encoding','UTF-8','-source','8','-target','8','-Xlint:-options','-classpath',os.pathsep.join(map(str,LIBS)),'-d',classes,*sorted(SOURCE.rglob('*.java'))])
run([TOOLS/'d8',*[arg for lib in LIBS for arg in ['--lib',lib]],'--min-api','35','--output',OUT,*sorted(classes.rglob('*.class'))])
jar=OUT/'blewright-ui-tools.jar'
with zipfile.ZipFile(jar,'w') as z:z.write(OUT/'classes.dex','classes.dex')
print(jar)
