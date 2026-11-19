"""Regression: cleanup errors must preserve the original setup failure.
Run: .venv/bin/python android/launcher/test_run_cleanup.py
No emulator, Frida server or BLE backend is accessed by this test.
"""
import contextlib
import io
import sys
import types
import unittest
from unittest.mock import Mock, patch

import run


class CleanupTests(unittest.TestCase):
    def test_original_failure_survives_both_cleanup_errors(self):
        session = Mock()
        session.create_script.side_effect = ValueError('original script setup failure')
        session.detach.side_effect = RuntimeError('detach cleanup failure')
        device = Mock()
        device.spawn.return_value = 1234
        device.attach.return_value = session
        device.kill.side_effect = RuntimeError('kill cleanup failure')
        # Intentionally no Error attribute, matching the installed Frida API.
        frida = types.SimpleNamespace(get_device=Mock(return_value=device))
        relay = Mock()
        relay.hello = {'sessionId': 'synthetic-session'}
        diagnostics = io.StringIO()

        def adb_result(args, **kwargs):
            return '1' if args[-1] == 'ro.kernel.qemu' else '35'

        with patch.dict(sys.modules, {'frida': frida}), \
                patch.object(sys, 'argv', ['run.py', '--serial', 'synthetic-emulator', '--package', 'space.nomoloop.blewright.host']), \
                patch.object(run.subprocess, 'check_output', side_effect=adb_result), \
                patch.object(run.Path, 'is_file', return_value=True), \
                patch.object(run.Path, 'read_text', return_value=''), \
                patch.object(run, 'RpcRelay', return_value=relay), \
                contextlib.redirect_stderr(diagnostics):
            with self.assertRaisesRegex(ValueError, 'original script setup failure'):
                run.main()

        device.kill.assert_called_once_with(1234)
        session.detach.assert_called_once()
        relay.close.assert_called_once()
        self.assertIn('kill cleanup failure', diagnostics.getvalue())
        self.assertIn('detach cleanup failure', diagnostics.getvalue())


if __name__ == '__main__':
    unittest.main()
