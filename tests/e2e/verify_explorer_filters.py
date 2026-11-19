#!/usr/bin/env python3
"""Black-box UI filtering regression using synthetic advertisements and the native BLE adapter."""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[2]
PACKAGE='space.nomoloop.blewright.explorer'
parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--serial',required=True);args=parser.parse_args()
ADB=[str(Path.home()/'Library/Android/sdk/platform-tools/adb'),'-s',args.serial]
OUT=ROOT/'dist/tests/explorer/filters';OUT.mkdir(parents=True,exist_ok=True)
results=[]

def adb(*parts): return subprocess.check_output([*ADB,*parts],text=True,timeout=20).strip()
def nodes():
    adb('shell','uiautomator','dump','/sdcard/blewright-filter-test.xml')
    xml=adb('shell','cat','/sdcard/blewright-filter-test.xml');(OUT/'latest.xml').write_text(xml)
    return list(ET.fromstring(xml).iter('node'))
def find(value,field='content-desc',timeout=15):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        for node in nodes():
            if value in node.get(field,''):return node
    raise AssertionError('Missing UI: '+value)
def tap(node):
    x1,y1,x2,y2=map(int,re.findall(r'\d+',node.get('bounds')))
    adb('shell','input','tap',str((x1+x2)//2),str((y1+y2)//2))
def click(value,field='content-desc'):
    node=find(value,field);assert node.get('enabled')=='true',value;tap(node)
def shot(name):
    with (OUT/f'{name}.png').open('wb') as image:subprocess.run([*ADB,'exec-out','screencap','-p'],stdout=image,check=True)
def check_count(shown,total=6):find(f'device-count: {shown}/{total}')
def passed(message):results.append(message);print('PASS: '+message,flush=True)
def stop(child):
    if child and child.poll() is None:
        child.send_signal(signal.SIGINT)
        try:child.wait(timeout=10)
        except subprocess.TimeoutExpired:child.kill();child.wait()
def launch(port,index):
    log=(OUT/f'client-{index}.log').open('w')
    child=subprocess.Popen([sys.executable,'android/launcher/run.py','--serial',args.serial,'--package',PACKAGE,'--rpc-port',str(port)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    deadline=time.monotonic()+25
    while 'RPC active' not in (OUT/f'client-{index}.log').read_text():
        if child.poll() is not None:raise AssertionError((OUT/f'client-{index}.log').read_text())
        if time.monotonic()>deadline:stop(child);raise AssertionError('Injection timeout')
        time.sleep(.1)
    return child,log

service=client=None;client_log=None;reader=None
service_log=(OUT/'service.jsonl').open('w')
try:
    assert adb('shell','getprop','ro.kernel.qemu')=='1'
    assert adb('shell','getprop','ro.build.version.sdk')=='35'
    for permission in ['android.permission.BLUETOOTH_SCAN','android.permission.BLUETOOTH_CONNECT']:adb('shell','pm','grant',PACKAGE,permission)
    service=subprocess.Popen(['node','tests/e2e/explorer_filter_service.mjs'],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    first=service.stdout.readline();service_log.write(first);service_log.flush();port=json.loads(first)['port']
    def record():
        for line in service.stdout:service_log.write(line);service_log.flush()
    reader=threading.Thread(target=record,daemon=True);reader.start()
    client,client_log=launch(port,1)
    click('edit-filters');click('reset-filters')
    find('filter-summary: 隐藏无名称 · 信号不限')
    click('scan-toggle');check_count(4)
    passed('default hides missing and whitespace-only names; retains weak and unknown RSSI without a signal filter')
    click('edit-filters');click('rssi-preset-70')
    find('信号下限 ≥ -70 dBm','text');shot('filter-dialog')
    click('apply-filters');check_count(2)
    find('connect-02:00:00:00:00:01');find('connect-02:00:00:00:00:02')
    shot('filtered-list')
    passed('inclusive -70 dBm threshold, updated RSSI and name condition combine correctly; unknown RSSI excluded')
    find('scan-status: 扫描结束')
    click('advertisement-02:00:00:00:00:01')
    details=find('advertisement-details').get('text','')
    assert '0000180f-0000-1000-8000-00805f9b34fb' in details and 'FF FF 01 02 03 04' in details,details
    shot('advertisement')
    click('完成','text')
    click('edit-filters');click('filter-named');click('apply-filters');check_count(4)
    passed('disabling name filter restores strong unnamed devices without restarting scanning')
    click('edit-filters')
    slider=find('filter-rssi-slider')
    x1,y1,x2,y2=map(int,re.findall(r'\d+',slider.get('bounds')))
    adb('shell','input','swipe',str((x1+x2)//2),str((y1+y2)//2),str(x2-2),str((y1+y2)//2),'600')
    find('信号下限 ≥ -30 dBm','text');click('apply-filters');check_count(0)
    find('没有符合条件的设备','text');shot('filter-empty')
    click('show-all-devices');check_count(6)
    passed('slider reaches the configured bound; empty state can restore all cached devices')
    click('edit-filters');click('rssi-preset-70');click('apply-filters');check_count(4)
    # A canceled draft must not change the active filters.
    click('edit-filters');click('rssi-preset-55');click('取消','text')
    find('filter-summary: 显示全部名称 · ≥ -70 dBm');check_count(4)
    passed('cancel leaves applied filters unchanged')
    stop(client);client_log.close();client_log=None
    client,client_log=launch(port,2)
    find('filter-summary: 显示全部名称 · ≥ -70 dBm')
    click('scan-toggle');check_count(4)
    passed('filters persist across a new app process and apply to newly received broadcasts')
    click('edit-filters');click('reset-filters');check_count(4)
    find('filter-summary: 隐藏无名称 · 信号不限')
    entries=[json.loads(line) for line in (OUT/'service.jsonl').read_text().splitlines()]
    methods=[item.get('method') for item in entries if item.get('direction')=='in']
    assert methods.count('scan.start')==2,methods
    assert not set(methods)&{'connect','discover','read','write','notification.set','descriptor.write'},methods
    passed('reset restores defaults; filter edits never restart scanning or initiate GATT operations')
    (OUT/'results.json').write_text(json.dumps({'passed':results,'backend':'mock-advertisement-fixture','hardware':False},ensure_ascii=False,indent=2)+'\n')
finally:
    stop(client)
    if client_log:client_log.close()
    if service and service.poll() is None:service.terminate();service.wait(timeout=5)
    if reader:reader.join(timeout=2)
    service_log.close()
