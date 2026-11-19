"""Exercise launchd's asynchronous unload without touching real services."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class UpgradeTests(unittest.TestCase):
    def run_unload(self, remaining):
        source = (ROOT / 'mac/packaging/scripts/preinstall').read_text()
        function = source[source.index('unload_service()'):source.index('\nunload_service system/')]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            counter = root / 'remaining'
            counter.write_text(str(remaining))
            fake = root / 'launchctl'
            fake.write_text(f'''#!/bin/sh
if [ "$1" = bootout ]; then exit 0; fi
n=$(cat '{counter}')
if [ "$n" -le 0 ]; then exit 1; fi
echo $((n - 1)) > '{counter}'
exit 0
''')
            fake.chmod(0o755)
            function = function.replace('/bin/launchctl', str(fake)).replace('/bin/sleep 1', ':')
            result = subprocess.run(['/bin/sh'], input='set -eu\n' + function + '\nunload_service system/test\necho safe-to-replace\n', text=True, capture_output=True)
            return result, int(counter.read_text())

    def test_waits_until_launchd_removes_old_service(self):
        result, remaining = self.run_unload(3)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(remaining, 0)
        self.assertIn('safe-to-replace', result.stdout)

    def test_timeout_stops_upgrade_before_replacement(self):
        result, remaining = self.run_unload(100)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('safe-to-replace', result.stdout)
        self.assertIn('等待旧服务退出超时', result.stderr)
        self.assertEqual(remaining, 55)


if __name__ == '__main__':
    unittest.main()
