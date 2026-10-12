from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from run_isolated_tests import run_suite


class IsolatedTestRunnerTests(unittest.TestCase):
    def test_modules_do_not_share_process_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("test_first.py", "test_second.py"):
                (root / name).write_text(
                    "import os, unittest\n"
                    "class IsolationTest(unittest.TestCase):\n"
                    "    def test_environment(self):\n"
                    "        self.assertNotIn('SACRIFICIAL_ISOLATED_TEST_MARKER', os.environ)\n"
                    "        os.environ['SACRIFICIAL_ISOLATED_TEST_MARKER'] = 'set'\n",
                    encoding="utf-8",
                )
            self.assertEqual(run_suite(root), 0)

    def test_child_failure_and_missing_suite_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(run_suite(root), 1)
            (root / "test_failure.py").write_text(
                "import unittest\n"
                "class FailureTest(unittest.TestCase):\n"
                "    def test_failure(self): self.fail('expected failure')\n",
                encoding="utf-8",
            )
            self.assertEqual(run_suite(root), 1)

    def test_child_timeout_is_reported_as_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "test_timeout.py").write_text(
                "import time, unittest\n"
                "class TimeoutTest(unittest.TestCase):\n"
                "    def test_timeout(self): time.sleep(30)\n",
                encoding="utf-8",
            )
            self.assertEqual(run_suite(root, timeout_s=0.5), 1)
