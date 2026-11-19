import ctypes
import importlib.util
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('serial_client', ROOT/'tools/serial_client.py')
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)

class WireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out=ROOT/'build/libwire.dylib'
        out.parent.mkdir(parents=True,exist_ok=True)
        subprocess.run(['clang','-shared','-fPIC','-Wall','-Wextra','-Werror',str(ROOT/'main/wire.c'),'-o',str(out)],check=True)
        cls.lib=ctypes.CDLL(str(out))
        cls.lib.bw_frame.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_char_p,ctypes.c_size_t]
        cls.lib.bw_unframe.argtypes=[ctypes.c_char_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_char_p),ctypes.POINTER(ctypes.c_size_t)]
    def valid_c(self,line):
        p=ctypes.c_char_p();n=ctypes.c_size_t()
        return self.lib.bw_unframe(line,len(line),ctypes.byref(p),ctypes.byref(n))
    def test_python_to_c(self):
        frame=client.encode({'v':1,'id':1,'op':'hello'})
        self.assertEqual(self.valid_c(frame),0)
    def test_c_to_python(self):
        payload=b'{"value":[0,127,255],"name":"BLEWright"}'
        out=ctypes.create_string_buffer(4096)
        n=self.lib.bw_frame(out,len(out),payload,len(payload))
        self.assertGreater(n,0)
        self.assertEqual(client.decode(out.raw[:n]),{'value':[0,127,255],'name':'BLEWright'})
    def test_crc_rejects_corruption(self):
        frame=client.encode({'v':1,'id':1,'op':'hello'})
        broken=frame.replace(b'hello',b'jello')
        self.assertNotEqual(self.valid_c(broken),0)
        with self.assertRaises(ValueError):client.decode(broken)
    def test_truncation_noise_and_length(self):
        frame=client.encode({'x':1})
        for bad in [frame[:-1],b'boot log\n',frame[:5]+b'FFFF'+frame[9:],frame+b'junk\n']:
            self.assertNotEqual(self.valid_c(bad),0)
            with self.assertRaises(ValueError):client.decode(bad)
    def test_fragmented_input_preserved_and_bad_frame_skipped(self):
        valid=client.encode({'v':1,'bootId':'test','generation':3,'type':'event'})
        stream=b'boot noise\n'+valid.replace(b'test',b'fail')+valid
        chunks=[stream[i:i+7] for i in range(0,len(stream),7)]
        class Port:
            @property
            def in_waiting(self):return len(chunks[0]) if chunks else 0
            def read(self,n):return chunks.pop(0) if chunks else b''
        board=client.Board.__new__(client.Board)
        board.serial=Port();board.buffer=bytearray();board.discard_line=False;board.boot_id='test';board.generation=0
        self.assertEqual(board.next_message(1)['generation'],3)
    def test_limit(self):
        out=ctypes.create_string_buffer(4096)
        self.assertEqual(self.lib.bw_frame(out,len(out),b'x'*3073,3073),-1)
        with self.assertRaises(ValueError):client.encode({'x':'y'*3073})

if __name__=='__main__':unittest.main()
