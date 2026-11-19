#!/usr/bin/env python3
"""Real workstation UI validation. Scan nearby advertisements; connect only to a freshly USB-verified C6."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'firmware/fixtures/esp32c6/tools'))
from identity import IdentityPort
PACKAGE='space.nomoloop.blewright.explorer'
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--serial',required=True);parser.add_argument('--c6-port',required=True)
parser.add_argument('--restore-fixture-baseline',action='store_true',help='Restore the known BLE fixture baseline after an interrupted test')
parser.add_argument('--native',action='store_true',help='Use a physical phone directly, without Frida or workstation RPC')
parser.add_argument('--output',type=Path,help='Separate evidence directory for a comparison run')
args=parser.parse_args()
ADB=[str(Path.home()/'Library/Android/sdk/platform-tools/adb'),'-s',args.serial]
OUT=args.output or ROOT/'dist/tests/explorer/live-ui';OUT.mkdir(parents=True,exist_ok=True)
observed={}

def adb(*parts):return subprocess.check_output([*ADB,*parts],text=True,timeout=20).strip()
def tree():
    for attempt in range(3):
        result=adb('shell','uiautomator','dump','/sdcard/blewright-live-ui.xml')
        if 'dumped to:' in result:
            return ET.fromstring(adb('shell','cat','/sdcard/blewright-live-ui.xml'))
    raise AssertionError('UI did not provide a fresh hierarchy')
def scroll_page(root,direction):
    view=next((n for n in root.iter('node') if n.get('class')=='android.widget.ScrollView' and n.get('package')==PACKAGE),None)
    if view is None:raise AssertionError('No app scroll area')
    x1,y1,x2,y2=map(int,re.findall(r'\d+',view.get('bounds')))
    start=int(y1+(y2-y1)*.8);end=max(int(y1+(y2-y1)*.35),start-650)
    if direction=='up':start,end=end,start
    adb('shell','input','swipe',str((x1+x2)//2),str(start),str((x1+x2)//2),str(end),'350')
def find(value,field='content-desc',timeout=15,scroll=None):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        root=tree()
        for node in root.iter('node'):
            if value in node.get(field,''):return node
        if scroll:scroll_page(root,scroll)
    raise AssertionError('Missing UI: '+value)
def tap(node):
    assert node.get('enabled')=='true',node.get('content-desc')
    x1,y1,x2,y2=map(int,re.findall(r'\d+',node.get('bounds')))
    adb('shell','input','tap',str((x1+x2)//2),str((y1+y2)//2))
def click(value,field='content-desc',scroll=None):tap(find(value,field,scroll=scroll))
def count():
    value=find('device-count:').get('content-desc')
    return list(map(int,re.findall(r'\d+',value)))
def shot(name):
    with (OUT/f'{name}.png').open('wb') as f:subprocess.run([*ADB,'exec-out','screencap','-p'],stdout=f,check=True)
def characteristic_node(action):
    deadline=time.monotonic()+25
    while time.monotonic()<deadline:
        root=tree()
        for card in root.iter('node'):
            if card.get('class')!='android.widget.LinearLayout':continue
            if not any(node.get('text')=='0000fff1-0000-1000-8000-00805f9b34fb' for node in card):continue
            for node in card:
                if '有响应写入' in node.get('text',''):observed['characteristicProperties']=node.get('text')
                if '00002902-0000-1000-8000-00805f9b34fb' in node.get('text',''):observed['cccdPresent']=True
            for node in card.iter('node'):
                if node.get('content-desc','').startswith(action):return node
        scroll_page(root,'down')
    shot('missing-fff1-action')
    raise AssertionError('FFF1 action not visible: '+action)
def char_click(action):tap(characteristic_node(action))
def current_hex():return characteristic_node('characteristic-value:').get('content-desc').split(': ',1)[1]
def enter_hex(value):
    char_click('write')
    expected=value.replace(' ','').lower()
    # Standard UI accessibility text input, identical on phone and emulator.
    # This avoids vendor IMEs consuming alphabetic ADB key events; no BLE calls are hooked.
    response=adb('shell','uiautomator','runtest','/data/local/tmp/blewright-ui-tools.jar','-s',
                 '-c','space.nomoloop.blewright.uitools.HexTextCase#testSetText','-e','text',expected)
    assert 'result=PASS' in response and 'FAILURES!!!' not in response,response
    actual=find('write-hex').get('text','').replace(' ','').lower()
    assert actual==expected,'Hex editor differs from requested bytes: '+repr(actual)
def write(value,without_response=False):
    enter_hex(value)
    if without_response:
        click('无响应写入（不确认外设接收）',field='text')
        assert find('无响应写入（不确认外设接收）',field='text').get('checked')=='true'
    click('send-write')
    deadline=time.monotonic()+8
    while time.monotonic()<deadline:
        root=tree()
        if not any(node.get('content-desc')=='write-hex' for node in root.iter('node')):return
    shot('write-dialog-not-dismissed')
    raise AssertionError('Write dialog did not submit; native UI did not leave the dialog')
def log():return adb('logcat','-d','--pid='+pid,'-s','BLEExplorer:I','*:S')

tool_jar=ROOT/'dist/tests/android/ui-tools/blewright-ui-tools.jar'
assert tool_jar.is_file(),'Build UI tools first: python3 tests/android/build_ui_tools.py'
adb('shell','rm','-f','/data/local/tmp/blewright-ui-tools.jar')
adb('push',str(tool_jar),'/data/local/tmp/blewright-ui-tools.jar')
adb('shell','chmod','444','/data/local/tmp/blewright-ui-tools.jar')
stream=IdentityPort(args.c6_port);client=None;output=(OUT/'launcher.log').open('w')
try:
    initial=stream.read_fresh();assert not initial['connected'] and initial['advertising']
    (OUT/'identity-before.json').write_text(json.dumps(initial,indent=2)+'\n')
    address=initial['address'].upper();nonce=' '.join(f'{v:02X}' for v in bytes.fromhex(initial['nonce']))
    sdk=int(adb('shell','getprop','ro.build.version.sdk'))
    model=adb('shell','getprop','ro.product.marketname') or adb('shell','getprop','ro.product.model')
    installed=adb('shell','pm','path',PACKAGE)
    apk=next(line.removeprefix('package:') for line in installed.splitlines() if line.endswith('/base.apk'))
    installed_hash=adb('shell','sha256sum',apk).split()[0]
    local_hash=hashlib.sha256((ROOT/'dist/android/explorer/blewright-explorer.apk').read_bytes()).hexdigest()
    assert installed_hash==local_hash,'Installed APK differs from the comparison artifact'
    observed.update(model=model,sdk=sdk,apkSha256=installed_hash,transport='native' if args.native else 'workstation-esp32')
    if args.native:
        assert adb('shell','getprop','ro.kernel.qemu')!='1','Native comparison requires a physical phone'
        assert sdk>=35,'Explorer APK requires API 35 or newer'
        adb('shell','input','keyevent','KEYCODE_WAKEUP')
        adb('shell','am','force-stop',PACKAGE)
        output.write(adb('shell','am','start','-W','-n',PACKAGE+'/.MainActivity')+'\n');output.flush()
    else:
        client=subprocess.Popen([sys.executable,'android/explorer/run_workstation.py','--serial',args.serial],cwd=ROOT,stdout=output,stderr=subprocess.STDOUT)
        deadline=time.monotonic()+25
        while 'RPC active' not in (OUT/'launcher.log').read_text():
            assert client.poll() is None,(OUT/'launcher.log').read_text()
            assert time.monotonic()<deadline,'Injection timeout';time.sleep(.2)
    pid=adb('shell','pidof',PACKAGE)
    click('edit-filters');click('reset-filters');click('scan-toggle')
    find('scan-status: 扫描结束',timeout=25)
    named,total=count();assert total>0 and 0<named<=total
    click('edit-filters');click('rssi-preset-70');click('apply-filters')
    strong,same_total=count();assert same_total==total and strong<=named
    shot('nearby-filtered')
    click('edit-filters');click('filter-named');click('filter-signal');click('apply-filters')
    all_count,all_total=count();assert all_count==all_total==total
    click('edit-filters');click('reset-filters')
    assert count()==[named,total]
    print(f'PASS: {observed["transport"]} scan and cached filters: total={total}, named={named}, named_RSSI_ge_minus70={strong}',flush=True)
    # The exact USB identity and current nonce must also be present in the selected advertisement.
    click('advertisement-'+address,scroll='down')
    text=find('advertisement-details').get('text','')
    assert address in text and 'FF FF '+nonce in text,'C6 advertisement does not match fresh USB identity'
    assert '0000fff0-0000-1000-8000-00805f9b34fb' in text,'Missing advertised FFF0 service'
    observed['c6RssiDbm']=int(re.search(r'(-?\d+) dBm',text).group(1))
    observed['advertisedService']='0000fff0-0000-1000-8000-00805f9b34fb'
    click('完成','text')
    click('connect-'+address,scroll='down')
    find('connection-status: 已连接',timeout=20)
    char_click('read');original=current_hex();assert original!='empty'
    observed['initialValue']=original
    observed['restoredValue']='42 4C 45' if args.restore_fixture_baseline else original
    requests_before=log().count('写入请求')
    enter_hex('GG');click('send-write');find('write-hex')
    click('android:id/button2',field='resource-id')
    assert log().count('写入请求')==requests_before,'Invalid input reached BluetoothGatt'
    observed['invalidHexRejected']=True
    print('PASS: literal hex editor input and invalid input rejection',flush=True)
    char_click('subscribe')
    assert characteristic_node('subscription-status:').get('content-desc')=='subscription-status: on'
    write('42 57 30 36')
    assert current_hex()=='42 57 30 36'
    assert '收到通知 · 0000fff1-0000-1000-8000-00805f9b34fb · 42 57 30 36' in log()
    char_click('read');assert current_hex()=='42 57 30 36'
    shot('c6-characteristic')
    char_click('subscribe')
    assert characteristic_node('subscription-status:').get('content-desc')=='subscription-status: off'
    notifications=log().count('收到通知')
    write('42 57 30 37');char_click('read');assert current_hex()=='42 57 30 37'
    assert log().count('收到通知')==notifications,'Notification arrived after unsubscribe'
    write('01 23 45 67 89 AB CD EF',without_response=True)
    char_click('read');assert current_hex()=='01 23 45 67 89 AB CD EF'
    assert log().count('收到通知')==notifications
    observed['writeModes']=['withResponse','withoutResponse-read-back-verified']
    restore_value='42 4C 45' if args.restore_fixture_baseline else original
    if restore_value!='（空）':write(restore_value);char_click('read');assert current_hex()==restore_value
    click('disconnect',scroll='up');find('connection-status: 已主动断开')
    callback_log=log()
    (OUT/'native-callbacks.log').write_text(callback_log)
    statuses=re.findall(r'(?:状态码 |status=)(\d+)',callback_log)
    assert statuses and all(int(value)==0 for value in statuses),statuses
    observed['callbackStatuses']=sorted(set(map(int,statuses)))
    observed['callbackCounts']={name:callback_log.count(name) for name in ['连接回调','服务发现成功','读取回调','写入回调','CCCD 回调','收到通知']}
    final=stream.read_fresh();assert final['nonce']==initial['nonce'] and not final['connected']
    deltas={key:final[key]-initial[key] for key in ['reads','writes','subscriptions','notifyRequests']}
    assert deltas['reads']>=3 and deltas['writes']>=2 and deltas['subscriptions']>=1 and deltas['notifyRequests']>=2,deltas
    (OUT/'identity-after.json').write_text(json.dumps(final,indent=2)+'\n')
    (OUT/'results.json').write_text(json.dumps({'result':'PASS',**observed,'backend':'android-native' if args.native else 'esp32','nearby':{'total':total,'named':named,'namedAtMinus70':strong},'target':'USB-verified C6; address and fresh nonce matched in app advertisement','otherDevicesConnected':0,'originalValueRestored':restore_value==original and original!='（空）','fixtureBaselineRestored':args.restore_fixture_baseline,'c6CounterDeltas':deltas},ensure_ascii=False,indent=2)+'\n')
    print('PASS: native explorer UI connected only USB-verified C6, read/write/read-back, notify/unsubscribe, restored original value and disconnected; counters='+json.dumps(deltas),flush=True)
finally:
    if client and client.poll() is None:
        client.send_signal(signal.SIGINT)
        try:client.wait(timeout=10)
        except subprocess.TimeoutExpired:client.kill();client.wait()
    if args.native:
        # Close only this standalone test app, leaving the phone's Bluetooth settings intact.
        adb('shell','am','force-stop',PACKAGE)
    output.close();stream.close()
    adb('shell','rm','-f','/data/local/tmp/blewright-ui-tools.jar')
