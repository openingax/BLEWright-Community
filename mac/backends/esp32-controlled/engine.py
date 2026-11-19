"""Event-driven S3 command dispatcher. No serial device is opened on import.
Both target identity and connection generation are checked before serial writes.
"""
import re,time
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'firmware/tools'))
from serial_client import encode

ALLOWED={'ping','scan.start','scan.stop','connect','cancel','disconnect','services','characteristics','descriptors','read','write','mtu','rssi'}
GATT={'services','characteristics','descriptors','read','write','mtu','rssi'}
def validate_allow(value):
    if not isinstance(value,dict) or not isinstance(value.get('address'),str) or not re.fullmatch(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}',value['address']) or type(value.get('addressType')) is not int or value['addressType'] not in (0,1):
        raise ValueError('EXACT_C6_ALLOW_REQUIRED')
    nonce=value.get('nonce')
    if isinstance(nonce,str) and re.fullmatch(r'[0-9A-Fa-f]{8}',nonce):nonce=list(bytes.fromhex(nonce))
    if not isinstance(nonce,list) or len(nonce)!=4 or any(type(x) is not int or not 0<=x<=255 for x in nonce):raise ValueError('EXACT_C6_NONCE_REQUIRED')
    return {'address':value['address'].upper(),'addressType':value['addressType'],'nonce':list(nonce)}
def manufacturer(data):
    if not isinstance(data,list) or any(type(x) is not int or not 0<=x<=255 for x in data):return None
    i=0
    while i<len(data):
        n=data[i]
        if n==0 or i+n>=len(data):return None
        if data[i+1]==255:return data[i+2:i+n+1]
        i+=n+1
    return None

class OpenTargetPolicy:
    def connect(self, params, now):
        address=params.get('address');kind=params.get('addressType')
        if not isinstance(address,str) or not re.fullmatch(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}',address):raise ValueError('INVALID_ADDRESS')
        if type(kind) is not int or kind not in (0,1):raise ValueError('INVALID_ADDRESS_TYPE')
        return {'address':address.upper(),'addressType':kind}
    def observe(self, event, now):pass
    def scan_options(self, params):
        passive=params.get('passive',False)
        if type(passive) is not bool:raise ValueError('INVALID_ARGUMENT')
        return {'passive':passive}

class ExactTargetPolicy(OpenTargetPolicy):
    def __init__(self,allow):self.allow=validate_allow(allow);self.proof=None
    def connect(self,params,now):
        if not isinstance(params.get('address'),str) or params['address'].upper()!=self.allow['address'] or type(params.get('addressType')) is not int or params.get('addressType')!=self.allow['addressType']:raise ValueError('TARGET_NOT_ALLOWED')
        if self.proof is None or now-self.proof>30:raise ValueError('C6_ADVERTISEMENT_PROOF_REQUIRED')
        return {'address':self.allow['address'],'addressType':self.allow['addressType']}
    def observe(self,event,now):
        if event.get('address','').upper()==self.allow['address'] and event.get('addressType')==self.allow['addressType']:
            data=manufacturer(event.get('advertising'))
            if data is not None:self.proof=now if data==[255,255,*self.allow['nonce']] else None
    def scan_options(self,params):return {'passive':True}

class ControlledEngine:
    def __init__(self,board,allow,emit,now=time.monotonic,policy=None):
        self.policy=policy or ExactTargetPolicy(allow);self.board=board;self.emit=emit;self.now=now
        h=board.hello
        if h.get('ready') is not True or h.get('passiveScanSupported') is not True:raise RuntimeError('FIRMWARE_NOT_READY')
        if h.get('connected') or h.get('connecting') or h.get('scanning'):raise RuntimeError('BOARD_ALREADY_IN_USE')
        self.generation=h['generation'];self.pending={};self.proof=None;self.owned=False;self.connecting=False;self.scanning=False;self.scan_id=None;self.counts={'hello':1};self.closing=False;self.initial_drops=h.get('droppedFrames',0)
    def error(self,ident,code):
        if ident is not None:self.emit({'type':'result','id':ident,'error':code})
    def reply(self,ident,result):
        if ident is not None:self.emit({'type':'result','id':ident,'result':result})
    def command(self,q):
        ident=q.get('id');op=q.get('method');params=q.get('params') or {}
        if op not in ALLOWED:return self.error(ident,'UNSUPPORTED')
        if not isinstance(params,dict):return self.error(ident,'INVALID_ARGUMENT')
        if op=='connect':
            try:params=self.policy.connect(params,self.now())
            except ValueError as error:return self.error(ident,str(error))
            if self.owned or self.connecting:return self.error(ident,'BUSY')
            self.connecting=True;self.scanning=False
        elif op=='scan.start':
            if self.connecting or self.scanning:return self.error(ident,'BUSY')
            try:params=self.policy.scan_options(params)
            except ValueError as error:return self.error(ident,str(error))
        elif op=='cancel':
            if not self.connecting:return self.reply(ident,{'status':0,'generation':self.generation})
            params={}
        elif op=='disconnect':
            if not self.owned:return self.reply(ident,{'status':0,'generation':self.generation})
            if params.get('generation')!=self.generation:return self.error(ident,'STALE_GENERATION')
            params={}
        elif op in GATT:
            if not self.owned:return self.error(ident,'NOT_CONNECTED')
            if params.get('generation')!=self.generation:return self.error(ident,'STALE_GENERATION')
            if any(p['op'] in GATT for p in self.pending.values()):return self.error(ident,'BUSY')
            params={k:v for k,v in params.items() if k in ('start','end','handle','value','withoutResponse')}
        elif op in ('scan.stop','ping'):params={}
        self._send(ident,op,params)
    def _send(self,ident,op,params):
        self.board.sequence+=1;wire_id=self.board.sequence
        self.pending[wire_id]={'id':ident,'op':op,'generation':self.generation,'events':[],'params':params,'deadline':self.now()+(11 if op=='connect' else 5)}
        self.counts[op]=self.counts.get(op,0)+1
        self.board.serial.write(encode({'v':1,'id':wire_id,'op':op,'bootId':self.board.boot_id,'generation':self.generation,'params':params}))
    def on_message(self,m):
        if m.get('bootId')!=self.board.boot_id:raise RuntimeError('BOARD_REBOOTED')
        if m.get('type')=='result':
            p=self.pending.pop(m.get('id'),None)
            if not p:return
            op=p['op'];status=m.get('status')
            if op=='hello' and m.get('droppedFrames',0)>self.initial_drops:raise RuntimeError('DROPPED_FRAMES_OUTCOME_UNKNOWN')
            if op=='connect':
                self.connecting=False;self.owned=status==0
                if self.owned:self.generation=m['generation']
            elif op in GATT and (p['generation']!=self.generation or m.get('generation')!=self.generation):
                return self.error(p['id'],'STALE_GENERATION')
            if op=='scan.start' and status==0:
                if m.get('passive') is not p['params']['passive']:raise RuntimeError('SCAN_MODE_NOT_CONFIRMED')
                self.scanning=True;self.scan_id=m['id']
            if op=='scan.stop' and status==0:self.scanning=False;self.scan_id=None
            result={k:v for k,v in m.items() if k not in ('id','v','bootId','type')}
            result['events']=p['events']
            if op=='scan.start':result['scanId']=m['id']
            self.reply(p['id'],result)
            return
        if m.get('type')!='event':return
        event=m.get('event')
        if event=='advertisement':
            if not self.scanning or m.get('scanId')!=self.scan_id:return
            self.policy.observe(m,self.now())
            self.emit({'type':'event','event':m})
        elif event=='scanStopped':
            if self.scanning and m.get('scanId')==self.scan_id:
                self.scanning=False;self.emit({'type':'event','event':m})
        elif event=='disconnected':
            was_owned=self.owned;self.owned=False;self.generation=m['generation']
            for wire_id,p in list(self.pending.items()):
                if p['op'] in GATT:self.pending.pop(wire_id);self.error(p['id'],'DISCONNECTED')
            if was_owned:self.emit({'type':'event','event':m})
        elif event in ('service','characteristic','descriptor'):
            p=self.pending.get(m.get('id'))
            if p and self.owned and m.get('generation')==self.generation:p['events'].append(m)
        elif event=='notification':
            if self.owned and m.get('generation')==self.generation:self.emit({'type':'event','event':m})
    def health(self):self._send(None,'hello',{})
    def tick(self):
        if any(p['deadline']<self.now() for p in self.pending.values()):raise TimeoutError('BOARD_OPERATION_TIMEOUT_OUTCOME_UNKNOWN')
    def cleanup(self):
        # Mutations here can only affect the one connection this engine authorized.
        self.closing=True
        if self.scanning:self.command({'id':None,'method':'scan.stop'})
        if self.connecting:self.command({'id':None,'method':'cancel'})
        deadline=self.now()+3
        while self.now()<deadline:
            if self.scanning and not any(p['op']=='scan.stop' for p in self.pending.values()):self.command({'id':None,'method':'scan.stop'})
            if self.owned and not any(p['op']=='disconnect' for p in self.pending.values()):self.command({'id':None,'method':'disconnect','params':{'generation':self.generation}})
            if not self.pending and not self.owned and not self.connecting:break
            try:self.on_message(self.board.next_message(.1))
            except TimeoutError:continue
