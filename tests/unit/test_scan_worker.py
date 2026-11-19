"""Tests execute the real worker loop with a fake board; no serial device is opened."""
import contextlib,importlib.util,io,json,sys,unittest
from pathlib import Path
from unittest.mock import patch
path=Path(__file__).resolve().parents[2]/'mac/backends/esp32-scan/worker.py'
spec=importlib.util.spec_from_file_location('scan_worker',path);worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)
class FakeBoard:
    instance=None
    connected=False
    def __init__(self,port):
        FakeBoard.instance=self;self.calls=[];self.events=[];self.closed=False
        self.hello={'ready':True,'connected':self.connected,'connecting':False,'scanning':False,'passiveScanSupported':True,'generation':0}
    def request(self,op,params=None,timeout=3):
        self.calls.append((op,params));return {'status':0,'id':1,'passive':True,'generation':0,'connected':False,'connecting':False,'scanning':False}
    def next_message(self,timeout):raise TimeoutError()
    def close(self):self.closed=True
class WorkerTests(unittest.TestCase):
    def test_whitelist_and_forced_passive(self):
        commands=[{'id':1,'method':'connect'},{'id':2,'method':'write'},{'id':3,'method':'scan.start','params':{'passive':False}},{'id':4,'method':'scan.stop'}]
        output=io.StringIO()
        with patch.object(worker,'Board',FakeBoard),patch.object(sys,'argv',['worker','--port','fake']),patch.object(sys,'stdin',io.StringIO(''.join(json.dumps(c)+'\n' for c in commands))),contextlib.redirect_stdout(output),contextlib.redirect_stderr(io.StringIO()):worker.main()
        self.assertEqual(FakeBoard.instance.calls,[('scan.start',{'passive':True}),('scan.stop',None),('hello',None)])
        self.assertEqual(sum(f.get('error')=='SCAN_ONLY' for f in map(json.loads,output.getvalue().splitlines())),2)
        self.assertTrue(FakeBoard.instance.closed)
    def test_existing_connection_is_not_modified(self):
        with patch.object(FakeBoard,'connected',True),patch.object(worker,'Board',FakeBoard),patch.object(sys,'argv',['worker','--port','fake']),contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError,'BOARD_ALREADY_IN_USE'):worker.main()
        self.assertEqual(FakeBoard.instance.calls,[('hello',None)])
        self.assertTrue(FakeBoard.instance.closed)
if __name__=='__main__':unittest.main()
