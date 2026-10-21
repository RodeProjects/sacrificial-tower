from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from run_isolated_tests import format_test_duration, run_suite


class IsolatedTestRunnerTests(unittest.TestCase):
    def test_duration_shows_only_nonzero_units(self):
        cases = (
            (0, "0 Sek"),
            (59, "59 Sek"),
            (60, "1 Min"),
            (125, "2 Min 5 Sek"),
            (3600, "1 Std"),
            (3661, "1 Std 1 Min 1 Sek"),
            (86400, "1 Tag"),
            (90061, "1 Tag 1 Std 1 Min 1 Sek"),
        )
        for seconds, expected in cases:
            with self.subTest(seconds=seconds):
                self.assertEqual(format_test_duration(seconds), expected)

    def test_reports_suite_wide_progress_and_success_duration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("test_first.py", "test_second.py", "test_third.py"):
                (root / name).write_text("", encoding="utf-8")

            output = StringIO()
            with (
                patch("run_isolated_tests.subprocess.run",
                      return_value=SimpleNamespace(returncode=0)),
                patch("run_isolated_tests.time.monotonic",
                      side_effect=[0.0, 4.9, 10.0, 70.8, 72.0, 72.9]),
                redirect_stdout(output),
            ):
                self.assertEqual(run_suite(root), 0)

        lines = output.getvalue().splitlines()
        self.assertEqual(
            lines[:6],
            [
                "Starte Test: 1 / 3 (33%) - test_first.py",
                "Test 1 / 3 - erfolgreich - Testdauer: 4 Sek",
                "Starte Test: 2 / 3 (67%) - test_second.py",
                "Test 2 / 3 - erfolgreich - Testdauer: 1 Min",
                "Starte Test: 3 / 3 (100%) - test_third.py",
                "Test 3 / 3 - erfolgreich - Testdauer: 0 Sek",
            ],
        )

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
