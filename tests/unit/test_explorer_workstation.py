"""Hardware-free workstation integration tests: state gates, wire contract, injection guard."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch
from contextlib import redirect_stderr, redirect_stdout

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('workstation', ROOT/'android/explorer/run_workstation.py')
w = importlib.util.module_from_spec(spec); spec.loader.exec_module(w)
sys.path.insert(0, str(ROOT/'android/launcher'))
import run as launcher

READY = {'apiVersion': 1, 'protocolVersion': 1, 'state': 'ready', 'usbConnected': True,
         'busy': False, 'rpcAddress': '127.0.0.1:8876',
         'config': {'serial': 'TEST-ONLY', 'enabled': True, 'mode': 'esp32'}}


class WorkstationTests(unittest.TestCase):
    def test_supported_modes_use_reported_port(self):
        for mode in ('esp32', 'esp32-controlled'):
            state = copy.deepcopy(READY); state['config']['mode'] = mode
            state['rpcAddress'] = '127.0.0.1:32123'
            self.assertEqual(w.endpoint(state), (32123, mode))

    def test_unavailable_states_do_not_launch(self):
        cases = [({'usbConnected': False}, '尚未连接'), ({'state': 'starting'}, '握手'),
                 ({'state': 'stopped'}, '已停止'), ({'busy': True}, '维护'),
                 ({'state': 'error', 'error': '握手失败'}, '握手失败'),
                 ({'protocolVersion': 9}, '不兼容'), ({'rpcAddress': 'remote:8876'}, '本机'),
                 ({'rpcAddress': '127.0.0.1:0'}, '端口'), ({'rpcAddress': '127.0.0.1:8876:extra'}, '端口')]
        for changes, message in cases:
            with self.subTest(changes=changes):
                state = copy.deepcopy(READY); state.update(changes)
                with patch.object(sys, 'argv', ['workstation', '--serial', 'test-emulator']), \
                     patch.object(w, 'status', return_value=state), \
                     patch.object(w, 'check_rpc') as rpc, patch.object(w.os, 'execve') as execute, \
                     redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
                    self.assertEqual(w.main(), 2)
                    self.assertIn(message, err.getvalue())
                    rpc.assert_not_called(); execute.assert_not_called()

    def test_scan_only_mock_unbound_and_disabled_are_actionable(self):
        for config, message in [({'mode': 'esp32-scan'}, '只读'), ({'mode': 'mock'}, '不使用 mock'),
                                ({'serial': ''}, '绑定'), ({'enabled': False}, '已停止')]:
            state = copy.deepcopy(READY); state['config'].update(config)
            with self.assertRaisesRegex(ValueError, message): w.endpoint(state)

    def test_real_unix_wire_is_status_only(self):
        with tempfile.TemporaryDirectory(dir='/tmp') as directory:
            path = directory+'/control.sock'; seen = []
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(path); server.listen(1); server.settimeout(3)
                def serve():
                    with server.accept()[0] as client:
                        with client.makefile('rb') as stream: seen.append(json.loads(stream.readline()))
                        client.sendall((json.dumps({'ok': True, 'result': READY})+'\n').encode())
                thread = threading.Thread(target=serve); thread.start()
                self.assertEqual(w.status(path), READY); thread.join(4)
                self.assertEqual(seen, [{'apiVersion': 1, 'action': 'status'}])

    def test_rpc_hello_checks_without_sending_ble_requests(self):
        for backend, capabilities, accepted in [('esp32', list(w.REQUIRED), True),
                                                ('mock', list(w.REQUIRED), False), ('esp32', ['scan'], False)]:
            with self.subTest(backend=backend, capabilities=capabilities):
                seen = []
                with socket.socket() as server:
                    server.bind(('127.0.0.1', 0)); server.listen(1); server.settimeout(3)
                    port = server.getsockname()[1]
                    def serve():
                        with server.accept()[0] as client:
                            client.settimeout(3)
                            client.sendall((json.dumps({'type':'hello', 'version':1, 'sessionId':'test',
                                'backend':backend, 'capabilities':capabilities})+'\n').encode())
                            seen.append(client.recv(1024))
                    thread = threading.Thread(target=serve); thread.start()
                    if accepted: self.assertEqual(w.check_rpc(port, 'esp32')['backend'], 'esp32')
                    else:
                        with self.assertRaises(ValueError): w.check_rpc(port, 'esp32')
                    thread.join(4); self.assertEqual(seen, [b''])

    def test_launch_reuses_existing_adapter_with_backend_guard(self):
        with patch.object(sys, 'argv', ['workstation', '--serial', 'test-emulator']), \
             patch.object(w, 'status', return_value=READY), \
             patch.object(w, 'check_rpc', return_value={'backend':'esp32'}), \
             patch.object(w.os, 'execve') as execute, redirect_stdout(io.StringIO()):
            w.main()
            command = execute.call_args.args[1]
            self.assertIn('space.nomoloop.blewright.explorer', command)
            self.assertEqual(command[-2:], ['--require-backend', 'esp32'])

    def test_actual_session_mismatch_never_spawns_app(self):
        for info in ({'backend':'mock', 'capabilities':list(w.REQUIRED)},
                     {'backend':'esp32', 'capabilities':['scan']}, {'backend':'esp32', 'capabilities':None}):
            relay = Mock(); relay.hello = info
            device = Mock()
            with patch.object(sys, 'argv', ['run', '--serial', 'test', '--require-backend', 'esp32']), \
                 patch.dict(sys.modules, {'frida':types.SimpleNamespace(get_device=Mock(return_value=device))}), \
                 patch.object(launcher.subprocess, 'check_output', side_effect=lambda args, **kw: '1' if args[-1]=='ro.kernel.qemu' else '35'), \
                 patch.object(launcher.Path, 'is_file', return_value=True), \
                 patch.object(launcher, 'RpcRelay', return_value=relay), \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit): launcher.main()
                device.spawn.assert_not_called(); relay.close.assert_called_once()


if __name__ == '__main__': unittest.main()
