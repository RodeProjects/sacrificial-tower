from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import sys
import tempfile
import unittest
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
                (root / name).write_text(
                    "import unittest\n"
                    "class Sample(unittest.TestCase):\n"
                    "    def test_ok(self): pass\n",
                    encoding="utf-8",
                )
            progress_path = root / "progress.log"

            output = StringIO()
            with (
                patch.dict("os.environ", {"SACRIFICIAL_TEST_PROGRESS_FILE": str(progress_path)}),
                redirect_stdout(output),
            ):
                self.assertEqual(run_suite(root), 0)
            progress_contents = progress_path.read_text(encoding="utf-8")

        lines = progress_contents.splitlines()
        self.assertEqual(
            lines[:-1],
            [
                "Geplante Einzeltests: 3 aus 3 Testdateimustern.",
                "Starte Test: 1 / 3 (33%) - test_first.Sample.test_ok",
                "Test 1 / 3 - erfolgreich - Testdauer: 0 Sek",
                "Starte Test: 2 / 3 (67%) - test_second.Sample.test_ok",
                "Test 2 / 3 - erfolgreich - Testdauer: 0 Sek",
                "Starte Test: 3 / 3 (100%) - test_third.Sample.test_ok",
                "Test 3 / 3 - erfolgreich - Testdauer: 0 Sek",
            ],
        )
        self.assertRegex(
            lines[-1],
            r"^Alle 3 Einzeltests aus 3 Testdateimustern erfolgreich\. Gesamtdauer: .+$",
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

    def test_case_count_is_exact_for_multiple_test_methods(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "test_many.py").write_text(
                "import unittest\n"
                "class Sample(unittest.TestCase):\n"
                "    def test_one(self): pass\n"
                "    def test_two(self): pass\n"
                "    def test_three(self): pass\n",
                encoding="utf-8",
            )
            self.assertEqual(run_suite(root), 0)

    def test_nested_runner_does_not_pollute_outer_progress_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outer = root / "outer"
            nested = root / "nested"
            outer.mkdir()
            nested.mkdir()
            (nested / "test_inner.py").write_text(
                "import unittest\n"
                "class InnerTest(unittest.TestCase):\n"
                "    def test_inner(self): pass\n",
                encoding="utf-8",
            )
            (outer / "test_outer.py").write_text(
                "from pathlib import Path\n"
                "import unittest\n"
                "from run_isolated_tests import run_suite\n"
                "class OuterTest(unittest.TestCase):\n"
                "    def test_nested(self):\n"
                f"        self.assertEqual(run_suite(Path({str(nested)!r})), 0)\n",
                encoding="utf-8",
            )
            progress_path = root / "progress.log"
            with patch.dict(
                "os.environ", {"SACRIFICIAL_TEST_PROGRESS_FILE": str(progress_path)}
            ):
                self.assertEqual(run_suite(outer), 0)

            progress_lines = progress_path.read_text(encoding="utf-8").splitlines()

        start_lines = [line for line in progress_lines if line.startswith("Starte Test:")]
        done_lines = [line for line in progress_lines if line.startswith("Test ")]
        self.assertEqual(
            start_lines,
            ["Starte Test: 1 / 1 (100%) - test_outer.OuterTest.test_nested"],
        )
        self.assertEqual(
            done_lines,
            ["Test 1 / 1 - erfolgreich - Testdauer: 0 Sek"],
        )
