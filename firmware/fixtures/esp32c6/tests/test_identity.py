from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from identity import IdentityPort, matches_fixture, ad_fields

class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.identity={'address':'02:00:00:00:00:01','addressType':0,'nonce':'01020304'}
        self.event={'event':'advertisement','address':'02:00:00:00:00:01','addressType':0,
                    'advertising':[7,255,255,255,1,2,3,4]}
    def test_fresh_usb_query_ignores_old_boot_and_other_request_ids(self):
        class Port:
            def write(self,data):self.written=data
        stream=IdentityPort.__new__(IdentityPort);stream.port=Port()
        reports=iter([{'nonce':'OLD'}, {'requestId':'old-request','nonce':'OLD'}, {'requestId':'a'*32,'nonce':'NEW'}])
        stream.read=lambda timeout:next(reports)
        with patch('identity.secrets.token_hex',return_value='a'*32):
            result=stream.read_fresh()
        self.assertIn(b'"op": "identity"',stream.port.written)
        self.assertEqual(result['nonce'],'NEW')
    def test_exact_usb_bound_identity(self):
        self.assertTrue(matches_fixture(self.event,self.identity))
    def test_same_name_alone_never_authorizes_connection(self):
        self.event['advertising']=[13,9,*b'BLEWright-C6']
        self.assertFalse(matches_fixture(self.event,self.identity))
    def test_wrong_address_or_address_type_or_nonce_rejected(self):
        for changed in [dict(self.event,address='02:00:00:00:00:02'),dict(self.event,addressType=1),
                        dict(self.event,advertising=[7,255,255,255,4,3,2,1])]:
            self.assertFalse(matches_fixture(changed,self.identity))
    def test_truncated_advertisement_rejected(self):
        self.event['advertising']=[7,255,255,255,1]
        self.assertFalse(matches_fixture(self.event,self.identity))
    def test_legacy_fixture_advertisement_fits_31_bytes(self):
        raw=[2,1,6,3,3,240,255,13,9,*b'BLEWright-C6',7,255,255,255,1,2,3,4]
        self.assertEqual(len(raw),29)
        self.assertEqual(len(list(ad_fields(raw))),4)

if __name__=='__main__':unittest.main()
