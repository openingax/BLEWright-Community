import importlib.util
import tempfile
import unittest
from unittest.mock import patch, Mock
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'mac/manager'))
from manager import Manager, validate_config, Server, Handler
import json
import socket
import threading

class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.m = Manager('.', self.temp.name, '/node', '/python')
    def tearDown(self): self.temp.cleanup()
    def test_configuration_rejects_paths_and_arbitrary_backend(self):
        for serial in ('/dev/cu.a', '../x', '', 'x; rm'):
            with self.assertRaises(ValueError): validate_config({'serial': serial})
        with self.assertRaises(ValueError): validate_config({'serial':'S3', 'mode':'mock'})
    def test_general_default_needs_no_target_identity(self):
        c = validate_config({'serial':'S3'})
        self.assertEqual(c['mode'], 'esp32')
        self.assertNotIn('allow', c)
        self.assertEqual(self.m.config['mode'], 'esp32')

    def test_controlled_requires_exact_identity(self):
        with self.assertRaises(ValueError): validate_config({'serial':'S3', 'mode':'esp32-controlled'})
        c = validate_config({'serial':'S3','mode':'esp32-controlled','allow':{'address':'11:22:33:44:55:66','addressType':0,'nonce':'01020304'}})
        self.assertEqual(c['allow']['nonce'], [1,2,3,4])
    def test_no_auto_selection_of_c6_or_s3(self):
        with patch('manager.ports', return_value=[{'path':'/dev/a','serial':'C6'}, {'path':'/dev/b','serial':'S3'}]), patch.object(self.m,'start') as start:
            self.m.tick(); start.assert_not_called(); self.assertEqual(self.m.status['state'],'waiting')
    def test_usb_reenumeration_matches_serial_not_path(self):
        self.m.config['serial']='S3'
        with patch('manager.ports',return_value=[{'path':'/dev/new','serial':'S3'}]), patch.object(self.m,'start') as start:
            self.m.tick(); self.assertEqual(self.m.device_path,'/dev/new'); start.assert_called_once()
    def test_unplug_closes_old_sessions(self):
        self.m.config['serial']='S3'; self.m.device_path='/dev/old'
        with patch('manager.ports',return_value=[]), patch.object(self.m,'stop') as stop:
            self.m.tick(); stop.assert_called_once(); self.assertIsNone(self.m.device_path); self.assertEqual(self.m.status['state'],'waiting')
    def test_duplicate_serial_does_not_select(self):
        self.m.config['serial']='S3'
        with patch('manager.ports', return_value=[{'path':'/a','serial':'S3'},{'path':'/b','serial':'S3'}]), patch.object(self.m,'start') as start:
            self.m.tick(); start.assert_not_called()
    def test_double_action_rejected_and_disconnect_prevents_flash(self):
        with self.assertRaises(ValueError): self.m.submit({'action':'flash'})
        self.m.submit({'action':'start'})
        with self.assertRaises(ValueError): self.m.submit({'action':'start'})
    def test_flash_requires_explicit_connected_unique_target(self):
        self.m.config['serial'] = 'OLD'; self.m.device_path = '/dev/old'
        for serial, found in [(None, []), ('NEW', []), ('NEW', [{'serial':'NEW','path':'/a'}, {'serial':'NEW','path':'/b'}])]:
            with patch('manager.ports', return_value=found), self.assertRaises(ValueError):
                self.m.submit({'action':'flash', 'serial':serial})
            self.assertFalse(self.m.status['busy'])
        with patch('manager.ports', return_value=[{'serial':'NEW','path':'/new'}]):
            self.m.submit({'action':'flash','serial':'NEW'})
            self.assertEqual(self.m.commands.get_nowait()['serial'], 'NEW')
            with self.assertRaises(ValueError): self.m.submit({'action':'flash','serial':'NEW'})

    def test_flash_resolves_selected_board_after_stopping_worker(self):
        self.m.root = Path(self.temp.name)
        bundle = self.m.root/'firmware/release'; bundle.mkdir(parents=True)
        (bundle/'manifest.json').write_text('{"files":[]}')
        self.m.config['serial'] = 'OLD'; self.m.device_path = '/dev/old'
        process = Mock(); process.poll.return_value = 0; process.returncode = 0
        with patch('manager.ports', side_effect=[[{'serial':'NEW','path':'/new'}], [{'serial':'NEW','path':'/reenumerated'}]]), patch.object(self.m,'stop'), patch('manager.subprocess.Popen', return_value=process) as spawn:
            self.m.maintenance('flash', 'NEW')
        args = spawn.call_args.args[0]
        self.assertEqual(args[args.index('--port') + 1], '/reenumerated')
        self.assertNotIn('/dev/old', args)
        self.assertEqual(self.m.config['serial'], 'OLD')

    def test_flash_unplug_during_stop_never_falls_back(self):
        self.m.device_path = '/dev/old'
        with patch('manager.ports', side_effect=[[{'serial':'NEW','path':'/new'}], []]), patch.object(self.m,'stop'), patch('manager.subprocess.Popen') as spawn:
            with self.assertRaises(ValueError): self.m.maintenance('flash', 'NEW')
            spawn.assert_not_called()

    def test_stop_persists_without_restart_on_replug(self):
        self.m.config.update(serial='S3',enabled=False)
        with patch('manager.ports',return_value=[{'path':'/a','serial':'S3'}]), patch.object(self.m,'start') as start:
            self.m.tick(); start.assert_not_called(); self.assertEqual(self.m.status['state'],'stopped')
    def test_no_root_environment_inheritance(self):
        with patch.dict('os.environ', {'NODE_OPTIONS':'--require /tmp/malicious', 'PYTHONPATH':'/tmp'}):
            self.assertNotIn('NODE_OPTIONS',self.m.environment()); self.assertNotIn('PYTHONPATH',self.m.environment())
    def test_config_survives_manager_restart(self):
        self.m.config=validate_config({'serial':'S3'}); self.m.persist()
        again=Manager('.',self.temp.name,'/node','/python')
        self.assertEqual(again.config['serial'],'S3')
    def test_readonly_snapshot_does_not_disclose_target_identity(self):
        self.m.config['allow']={'nonce':'12345678'}
        self.assertNotIn('allow',self.m.snapshot()['config'])

class ControlBoundaryTests(unittest.TestCase):
    def test_unprivileged_peer_can_observe_but_cannot_mutate(self):
        with tempfile.TemporaryDirectory() as directory, patch('manager.admin_peer', return_value=False), patch('manager.ports', return_value=[]):
            manager = Manager('.', directory, '/node', '/python')
            path = str(Path(directory)/'control.sock')
            server = Server(path, Handler); server.manager = manager
            thread = threading.Thread(target=server.serve_forever); thread.start()
            def req(q):
                with socket.socket(socket.AF_UNIX) as client:
                    client.connect(path); client.sendall((json.dumps(q)+'\n').encode())
                    return json.loads(client.makefile('rb').readline())
            try:
                self.assertTrue(req({'apiVersion':1,'action':'status'})['ok'])
                self.assertFalse(req({'apiVersion':1,'action':'start'})['ok'])
                self.assertTrue(manager.commands.empty())
                self.assertFalse(req({'apiVersion':2,'action':'status'})['ok'])
            finally:
                server.shutdown(); server.server_close(); thread.join()
    def test_existing_client_ports_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = Manager('.', directory, '/node', '/python')
            self.assertEqual(manager.effective_port, 8876)
            manager.config['mode'] = 'esp32-scan'
            self.assertEqual(manager.effective_port, 8766)
            manager.config['mode'] = 'esp32-controlled'
            self.assertEqual(manager.effective_port, 8876)
            manager.rpc_port = 18765
            self.assertEqual(manager.effective_port, 18765)

if __name__ == '__main__': unittest.main()
