#!/usr/bin/env python3
"""Run filter boundary tests on the JVM against the actual app class."""
import os
from pathlib import Path
import subprocess
ROOT = Path(__file__).resolve().parents[2]
SDK = Path(os.environ.get('ANDROID_SDK_ROOT', str(Path.home()/'Library/Android/sdk')))
JAVA = Path(os.environ.get('JAVA_HOME') or subprocess.check_output(['/usr/libexec/java_home'],text=True).strip())
OUT = ROOT/'dist/tests/explorer-filter-policy'
OUT.mkdir(parents=True,exist_ok=True)
JAR = SDK/'platforms/android-35/android.jar'
source = ROOT/'android/explorer/src/space/nomoloop/blewright/explorer/ScanFilterState.java'
test = ROOT/'tests/android/explorer/space/nomoloop/blewright/explorer/FilterPolicyTest.java'
subprocess.run([str(JAVA/'bin/javac'),'-encoding','UTF-8','-classpath',str(JAR),'-d',str(OUT),str(source),str(test)],check=True)
subprocess.run([str(JAVA/'bin/java'),'-classpath',str(OUT)+os.pathsep+str(JAR),'space.nomoloop.blewright.explorer.FilterPolicyTest'],check=True)
