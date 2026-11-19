"""Controlled transport tests use an in-memory board, never a serial port."""
import importlib.util,json,sys,unittest
from pathlib import Path
path=Path(__file__).resolve().parents[2]/'mac/backends/esp32-controlled/engine.py'
spec=importlib.util.spec_from_file_location('controlled_engine',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
from serial_client import decode
ALLOW={'address':'00:00:00:00:00:01','addressType':0,'nonce':'01020304'}
class Serial:
    def __init__(self):self.frames=[]
    def write(self,data):self.frames.append(decode(data))
class Board:
    def __init__(self):
        self.hello={'ready':True,'connected':False,'connecting':False,'scanning':False,'passiveScanSupported':True,'generation':0,'droppedFrames':0}
        self.sequence=1;self.boot_id='test';self.serial=Serial()
class Tests(unittest.TestCase):
    def setUp(self):
        self.board=Board();self.output=[];self.time=0
        self.engine=module.ControlledEngine(self.board,ALLOW,self.output.append,now=lambda:self.time)
    def result(self,status=0,**extra):
        frame=self.board.serial.frames[-1]
        self.engine.on_message({'type':'result','bootId':'test','generation':self.engine.generation,'id':frame['id'],'status':status,**extra})
    def advertisement(self,nonce=[1,2,3,4],address=ALLOW['address']):
        self.engine.on_message({'type':'event','bootId':'test','event':'advertisement','scanId':self.engine.scan_id,'generation':self.engine.generation,'address':address,'addressType':0,'advertising':[7,255,255,255,*nonce]})
    def prove(self):
        self.engine.command({'id':1,'method':'scan.start','params':{'passive':False}})
        self.assertEqual(self.board.serial.frames[-1]['params'],{'passive':True})
        self.result(passive=True);self.advertisement()
    def connect(self):
        self.prove();self.engine.command({'id':2,'method':'connect','params':{'address':ALLOW['address'],'addressType':0}});self.result(generation=1,mtu=23)
    def test_missing_or_invalid_configuration_and_existing_connection_fail_closed(self):
        with self.assertRaises(ValueError):module.validate_allow(None)
        with self.assertRaises(ValueError):module.validate_allow({**ALLOW,'nonce':'*'})
        self.board.hello['connected']=True
        with self.assertRaisesRegex(RuntimeError,'BOARD_ALREADY_IN_USE'):module.ControlledEngine(self.board,ALLOW,self.output.append)
        self.assertEqual(self.board.serial.frames,[])
    def test_wrong_address_nonce_or_stale_proof_never_reaches_serial_connect(self):
        self.prove();base=len(self.board.serial.frames)
        self.engine.command({'id':2,'method':'connect','params':{'address':'00:00:00:00:00:02','addressType':0}})
        self.advertisement(nonce=[9,9,9,9]);self.engine.command({'id':3,'method':'connect','params':{'address':ALLOW['address'],'addressType':0}})
        self.advertisement();self.time=31;self.engine.command({'id':4,'method':'connect','params':{'address':ALLOW['address'],'addressType':0}})
        self.assertEqual(len(self.board.serial.frames),base)
        self.assertEqual([x['error'] for x in self.output if 'error' in x],['TARGET_NOT_ALLOWED','C6_ADVERTISEMENT_PROOF_REQUIRED','C6_ADVERTISEMENT_PROOF_REQUIRED'])
    def test_cancel_is_sent_while_connect_result_is_pending(self):
        self.prove();self.engine.command({'id':2,'method':'connect','params':{'address':ALLOW['address'],'addressType':0}})
        connect_id=self.board.serial.frames[-1]['id']
        self.engine.command({'id':3,'method':'cancel'})
        self.assertEqual(self.board.serial.frames[-1]['op'],'cancel');self.result()
        self.engine.on_message({'type':'result','bootId':'test','generation':0,'id':connect_id,'status':13})
        self.assertFalse(self.engine.owned);self.assertFalse(self.engine.connecting)
        self.assertEqual([x['id'] for x in self.output if x.get('type')=='result'][-2:],[3,2])
    def test_generations_and_discovery_events_preserved(self):
        self.connect();before=len(self.board.serial.frames)
        self.engine.command({'id':3,'method':'read','params':{'generation':0,'handle':3}})
        self.assertEqual(len(self.board.serial.frames),before);self.assertEqual(self.output[-1]['error'],'STALE_GENERATION')
        self.engine.command({'id':4,'method':'services','params':{'generation':1}})
        wire=self.board.serial.frames[-1]
        self.engine.on_message({'type':'event','bootId':'test','generation':1,'id':wire['id'],'event':'service','uuid':'0xfff0','start':1,'end':9})
        self.result();self.assertEqual(self.output[-1]['result']['events'][0]['start'],1)
    def test_remote_disconnect_invalidates_pending_gatt(self):
        self.connect();self.engine.command({'id':3,'method':'read','params':{'generation':1,'handle':3}})
        self.engine.on_message({'type':'event','bootId':'test','generation':2,'event':'disconnected','reason':531})
        self.assertFalse(self.engine.owned);self.assertEqual(self.output[-2]['error'],'DISCONNECTED')
        self.engine.command({'id':4,'method':'write','params':{'generation':2,'handle':3,'value':[1]}})
        self.assertEqual(self.output[-1]['error'],'NOT_CONNECTED')
    def test_health_reports_dropped_frames_as_unknown_outcome(self):
        self.engine.health()
        with self.assertRaisesRegex(RuntimeError,'DROPPED_FRAMES'):self.result(droppedFrames=1)
    def test_scan_while_connected_preserves_connection_generation(self):
        self.connect()
        self.engine.command({'id':5,'method':'scan.start','params':{'passive':True}})
        self.result(passive=True)
        self.assertTrue(self.engine.owned)
        self.engine.command({'id':6,'method':'rssi','params':{'generation':1}})
        self.assertEqual(self.board.serial.frames[-1]['op'],'rssi')

class GeneralTests(Tests):
    def setUp(self):
        self.board=Board();self.output=[];self.time=0
        self.engine=module.ControlledEngine(self.board,None,self.output.append,now=lambda:self.time,policy=module.OpenTargetPolicy())
    def prove(self):
        self.engine.command({'id':1,'method':'scan.start','params':{'passive':True}})
        self.assertEqual(self.board.serial.frames[-1]['params'],{'passive':True})
        self.result(passive=True);self.advertisement()
    def test_wrong_address_nonce_or_stale_proof_never_reaches_serial_connect(self):
        # General service accepts any valid selected target, with no fixture proof.
        self.engine.command({'id':1,'method':'connect','params':{'address':'AA:BB:CC:DD:EE:FF','addressType':1}})
        self.assertEqual(self.board.serial.frames[-1]['params'],{'address':'AA:BB:CC:DD:EE:FF','addressType':1})
    def test_active_and_passive_scan_confirmation(self):
        self.engine.command({'id':1,'method':'scan.start','params':{}})
        self.assertEqual(self.board.serial.frames[-1]['params'],{'passive':False})
        self.result(passive=False)
        self.engine.command({'id':2,'method':'scan.stop'});self.result()
        self.engine.command({'id':3,'method':'scan.start','params':{'passive':True}})
        with self.assertRaisesRegex(RuntimeError,'SCAN_MODE_NOT_CONFIRMED'):self.result(passive=False)
    def test_invalid_target_never_reaches_usb(self):
        for params in [{'address':'*','addressType':0},{'address':ALLOW['address']},{'address':ALLOW['address'],'addressType':True}]:
            self.engine.command({'id':1,'method':'connect','params':params})
        self.assertEqual(self.board.serial.frames,[])
if __name__=='__main__':unittest.main()
