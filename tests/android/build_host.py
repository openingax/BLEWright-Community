#!/usr/bin/env python3
"""Build a standalone debug host APK. Does not install or launch anything."""
import os
from pathlib import Path
import subprocess
import zipfile
root=Path(__file__).resolve().parent
sdk=Path(os.environ.get('ANDROID_SDK_ROOT',str(Path.home()/'Library/Android/sdk')))
java=Path(os.environ.get('JAVA_HOME') or subprocess.check_output(['/usr/libexec/java_home'],text=True).strip())
bt=sdk/'build-tools/36.0.0'
out=root.parents[1]/'dist/tests/android/host';out.mkdir(parents=True,exist_ok=True)
classes=out/'classes';classes.mkdir(exist_ok=True)
jar=sdk/'platforms/android-35/android.jar'
def run(args):subprocess.run(list(map(str,args)),check=True,env={**os.environ,'JAVA_HOME':str(java)})
run([java/'bin/javac','-source','8','-target','8','-Xlint:-options','-classpath',jar,'-d',classes,*list((root/'host').rglob('*.java'))])
run([bt/'d8','--lib',jar,'--min-api','35','--output',out,*list(classes.rglob('*.class'))])
unsigned=out/'unsigned.apk'
run([bt/'aapt2','link','-I',jar,'--manifest',root/'host/AndroidManifest.xml','-o',unsigned])
with zipfile.ZipFile(unsigned,'a') as z:z.write(out/'classes.dex','classes.dex')
aligned=out/'aligned.apk';run([bt/'zipalign','-f','4',unsigned,aligned])
key=out/'debug.keystore'
if not key.exists():run([java/'bin/keytool','-genkeypair','-keystore',key,'-storepass','android','-keypass','android','-alias','androiddebugkey','-dname','CN=BLEWright Debug','-keyalg','RSA','-validity','3650'])
apk=out/'blewright-host.apk';run([bt/'apksigner','sign','--ks',key,'--ks-pass','pass:android','--out',apk,aligned])
print(apk)
