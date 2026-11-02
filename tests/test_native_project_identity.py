from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from cooling_tower.native_project.session import _engine_identity


class NativeEngineIdentityTests(unittest.TestCase):
    def test_results_bind_to_launcher_engine_and_own_host_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable, library, host = (root/name for name in ('engine.exe','AnycubicSlicer.dll','host.exe'))
            for path, data in ((executable,b'launcher'),(library,b'engine'),(host,b'host')):
                path.write_bytes(data)
            installation = SimpleNamespace(executable_path=executable, adapter_id='anycubic_slicer_next')
            with patch('cooling_tower.native_project.session.native_host_path',return_value=host):
                expected = _engine_identity(installation)
                for path in (executable,library,host):
                    with self.subTest(component=path.name):
                        original = path.read_bytes()
                        path.write_bytes(original+b'changed')
                        self.assertNotEqual(_engine_identity(installation),expected)
                        path.write_bytes(original)
                        self.assertEqual(_engine_identity(installation),expected)
                host.unlink()
                self.assertNotEqual(_engine_identity(installation),expected)


if __name__ == '__main__':
    unittest.main()
