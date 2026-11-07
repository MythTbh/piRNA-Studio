"""Cancellation must stop native tool children, not only the Python worker."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from .store import terminate_process_tree


class ProcessTests(unittest.TestCase):
    def test_cancel_stops_child_work(self):
        with tempfile.TemporaryDirectory(prefix='piRNA cancel ') as tmp:
            folder = Path(tmp)
            child = folder / 'child.py'
            child.write_text(
                'from pathlib import Path\nimport sys,time\n'
                'p=Path(sys.argv[1])\n'
                'while True:\n p.write_text(str(time.monotonic()))\n time.sleep(0.1)\n'
            )
            heartbeat = folder / 'heartbeat'
            command = [sys.executable, '-c',
                'import subprocess,sys; subprocess.Popen(sys.argv[1:]).wait()',
                sys.executable, str(child), str(heartbeat)]
            process = subprocess.Popen(command, start_new_session=os.name != 'nt',
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0)
            try:
                for _ in range(100):
                    if heartbeat.exists() and heartbeat.stat().st_size:
                        break
                    time.sleep(0.05)
                self.assertTrue(heartbeat.exists(), 'Child did not start')
                terminate_process_tree(process)
                process.wait(timeout=15)
                time.sleep(0.2)
                last_write = heartbeat.stat().st_mtime_ns
                time.sleep(0.5)
                self.assertEqual(last_write, heartbeat.stat().st_mtime_ns, 'Child continues after cancellation')
            finally:
                if process.poll() is None:
                    terminate_process_tree(process)
                    process.wait(timeout=15)


if __name__ == '__main__':
    unittest.main()
