import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

TOOLS=Path(__file__).resolve().parents[1]/'tools'
sys.path.insert(0,str(TOOLS))
from verify_passive_scan import verify


class FakeBoard:
    def __init__(self):
        self.hello={'status':0,'ready':True,'passiveScanSupported':True,
                    'connected':False,'connecting':False,'scanning':False,
                    'generation':0,'droppedFrames':0}
        self.events=[];self.calls=[];self.n=0
    def request(self,op,params=None):
        self.calls.append((op,params))
        if op=='scan.start':return {'status':0,'passive':True,'id':7}
        if op=='hello':return dict(self.hello)
        return {'status':0}
    def next_message(self,timeout):
        self.n+=1
        return {'type':'event','event':'advertisement','scanId':7,'generation':0,
                'addressType':0,'address':'PRIVATE_ADDRESS','advertising':[1,2,3]}


class PassiveScanTests(unittest.TestCase):
    def test_only_passive_scan_commands_and_aggregate_output(self):
        board=FakeBoard()
        with patch('verify_passive_scan.time.monotonic',side_effect=[0,0.1,0.2,2]):
            result=verify(board,1)
        self.assertEqual(board.calls,[('scan.start',{'passive':True}),('scan.stop',None),('hello',None)])
        self.assertEqual(result['advertisementFrames'],1)
        self.assertEqual(result['observedAddressIdentities'],1)
        self.assertNotIn('PRIVATE_ADDRESS',str(result))
        self.assertNotIn('advertising',result)
    def test_connected_board_is_not_touched(self):
        board=FakeBoard();board.hello['connected']=True
        with self.assertRaises(RuntimeError):verify(board,1)
        self.assertEqual(board.calls,[])
    def test_old_firmware_is_not_allowed_to_ignore_passive_flag(self):
        board=FakeBoard();del board.hello['passiveScanSupported']
        with self.assertRaises(RuntimeError):verify(board,1)
        self.assertEqual(board.calls,[])
    def test_no_advertisements_is_not_success(self):
        board=FakeBoard()
        with patch('verify_passive_scan.time.monotonic',side_effect=[0,2]):
            with self.assertRaises(RuntimeError):verify(board,1)
        self.assertIn(('scan.stop',None),board.calls)


if __name__=='__main__':unittest.main()
