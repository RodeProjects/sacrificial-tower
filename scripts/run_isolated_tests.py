"""Run unittest discovery in isolated processes and report suite-wide progress."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

COUNT_MARKER = "__SUITE_CASE_COUNT__="


def format_test_duration(seconds: float) -> str:
    whole_seconds = max(0, int(seconds))
    days, remainder = divmod(whole_seconds, 24 * 60 * 60)
    hours, remainder = divmod(remainder, 60 * 60)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days} {'Tag' if days == 1 else 'Tage'}")
    if hours:
        parts.append(f"{hours} Std")
    if minutes:
        parts.append(f"{minutes} Min")
    if seconds or not parts:
        parts.append(f"{seconds} Sek")
    return " ".join(parts)


def _discover(root: Path, pattern: str) -> unittest.TestSuite:
    loader = unittest.TestLoader()
    suite = loader.discover(str(root), pattern=pattern)
    if loader.errors:
        raise RuntimeError("\n".join(loader.errors))
    return suite


def _write_progress(
    message: str,
    *,
    is_error: bool = False,
    progress_path: str | None = None,
    use_environment_path: bool = True,
) -> None:
    print(message, file=sys.stderr if is_error else sys.stdout, flush=True)
    if progress_path is None and use_environment_path:
        progress_path = os.environ.get("SACRIFICIAL_TEST_PROGRESS_FILE")
    if progress_path:
        try:
            with Path(progress_path).open("a", encoding="utf-8", newline="\n") as progress_file:
                progress_file.write(message + "\n")
        except OSError as error:
            print(f"Could not write test progress file: {error}", file=sys.stderr, flush=True)


class ProgressTestResult(unittest.TextTestResult):
    def __init__(
        self,
        *args,
        completed_before: int,
        total: int,
        progress_path,
        planned_cases: list[unittest.TestCase],
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.completed_before = completed_before
        self.total = total
        self.progress_path = progress_path
        self.planned_cases = planned_cases
        self.completed = 0
        self.started_at: dict[int, tuple[int, float]] = {}
        self.outcomes: dict[int, tuple[str, str]] = {}
        self.completed_case_ids: set[int] = set()

    def startTest(self, test):
        number = self.completed_before + self.completed + 1
        percent = int(100 * number / self.total + 0.5)
        self.started_at[id(test)] = (number, time.monotonic())
        _write_progress(
            f"Starte Test: {number} / {self.total} ({percent}%) - {test.id()}",
            progress_path=self.progress_path,
            use_environment_path=False,
        )
        super().startTest(test)

    @staticmethod
    def _exception_summary(error) -> str:
        error_type, error_value, _ = error
        summary = str(error_value).splitlines()[0] if str(error_value) else error_type.__name__
        return summary[:240]

    def addSuccess(self, test):
        self.outcomes[id(test)] = ("erfolgreich", "")
        super().addSuccess(test)

    def addFailure(self, test, err):
        self.outcomes[id(test)] = ("Fehler", self._exception_summary(err))
        super().addFailure(test, err)

    def addError(self, test, err):
        detail = self._exception_summary(err)
        if id(test) in self.started_at:
            self.outcomes[id(test)] = ("Fehler", detail)
        elif not self._report_fixture_cases(test, "Fehler", detail):
            _write_progress(
                f"Testfixture {test} - Fehler - {detail}",
                is_error=True,
                progress_path=self.progress_path,
                use_environment_path=False,
            )
        super().addError(test, err)

    def addSkip(self, test, reason):
        if id(test) in self.started_at:
            self.outcomes[id(test)] = ("übersprungen", reason[:240])
        else:
            self._report_fixture_cases(test, "übersprungen", reason[:240])
        super().addSkip(test, reason)

    def addExpectedFailure(self, test, err):
        self.outcomes[id(test)] = ("erwartet fehlgeschlagen", self._exception_summary(err))
        super().addExpectedFailure(test, err)

    def addUnexpectedSuccess(self, test):
        self.outcomes[id(test)] = ("Fehler", "unerwarteter Erfolg")
        super().addUnexpectedSuccess(test)

    def stopTest(self, test):
        number, started_at = self.started_at.pop(id(test))
        self.completed += 1
        self.completed_case_ids.add(id(test))
        status, detail = self.outcomes.pop(id(test), ("Fehler", "Test ohne Ergebnis beendet"))
        duration = format_test_duration(time.monotonic() - started_at)
        message = f"Test {number} / {self.total} - {status} - Testdauer: {duration}"
        if detail:
            message += f" - {detail}"
        _write_progress(
            message,
            is_error=status == "Fehler",
            progress_path=self.progress_path,
            use_environment_path=False,
        )
        super().stopTest(test)

    def _report_fixture_cases(self, fixture, status: str, detail: str) -> bool:
        description = str(fixture)
        class_prefix = "setUpClass ("
        module_prefix = "setUpModule ("
        cases = []
        if description.startswith(class_prefix) and description.endswith(")"):
            class_name = description[len(class_prefix):-1]
            cases = [
                case
                for case in self.planned_cases
                if f"{case.__class__.__module__}.{case.__class__.__qualname__}" == class_name
            ]
        elif description.startswith(module_prefix) and description.endswith(")"):
            module_name = description[len(module_prefix):-1]
            cases = [
                case for case in self.planned_cases if case.__class__.__module__ == module_name
            ]
        else:
            return False

        for case in cases:
            case_id = id(case)
            if case_id in self.completed_case_ids:
                continue
            number = self.completed_before + self.completed + 1
            percent = int(100 * number / self.total + 0.5)
            _write_progress(
                f"Starte Test: {number} / {self.total} ({percent}%) - {case.id()}",
                progress_path=self.progress_path,
                use_environment_path=False,
            )
            self.completed += 1
            self.completed_case_ids.add(case_id)
            message = f"Test {number} / {self.total} - {status} - Testdauer: 0 Sek"
            if detail:
                message += f" - {detail}"
            _write_progress(
                message,
                is_error=status == "Fehler",
                progress_path=self.progress_path,
                use_environment_path=False,
            )
        return bool(cases)


class ProgressTestRunner(unittest.TextTestRunner):
    def __init__(
        self,
        *args,
        completed_before: int,
        total: int,
        progress_path,
        planned_cases: list[unittest.TestCase],
        **kwargs,
    ):
        self.completed_before = completed_before
        self.total = total
        self.progress_path = progress_path
        self.planned_cases = planned_cases
        super().__init__(*args, **kwargs)

    def _makeResult(self):
        return ProgressTestResult(
            self.stream,
            self.descriptions,
            self.verbosity,
            completed_before=self.completed_before,
            total=self.total,
            progress_path=self.progress_path,
            planned_cases=self.planned_cases,
        )


def count_pattern(root: Path, pattern: str) -> int:
    return _discover(root, pattern).countTestCases()


def _collect_test_cases(suite: unittest.TestSuite) -> list[unittest.TestCase]:
    cases = []
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            cases.extend(_collect_test_cases(test))
        elif isinstance(test, unittest.TestCase):
            cases.append(test)
    return cases


def plan_suite(root: Path, patterns: list[str], *, timeout_s: float = 600):
    counts: dict[str, int] = {}
    for pattern in patterns:
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--start-directory",
            str(root),
            "--count-pattern",
            pattern,
        ]
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            return None, (
                f"Testfallzahl für {pattern} - Stockt - Ermittlung nach "
                f"{timeout_s:g} Sekunden abgebrochen."
            )
        marker = next(
            (line for line in result.stdout.splitlines() if line.startswith(COUNT_MARKER)),
            None,
        )
        if result.returncode != 0 or marker is None:
            details = [
                line.strip()
                for line in (result.stderr or result.stdout).splitlines()
                if line.strip()
            ]
            detail = details[-1][:240] if details else f"Exit-Code {result.returncode}"
            return None, f"Testfallzahl für {pattern} - Fehler - {detail}"
        counts[pattern] = int(marker[len(COUNT_MARKER):])
    return counts, None


def run_pattern(
    root: Path,
    pattern: str,
    *,
    expected_count: int,
    completed_before: int,
    total: int,
) -> int:
    progress_path = os.environ.pop("SACRIFICIAL_TEST_PROGRESS_FILE", None)
    try:
        suite = _discover(root, pattern)
    except Exception as error:
        detail = str(error).splitlines()[-1][:240] if str(error) else type(error).__name__
        _write_progress(
            f"Testdateimuster {pattern} - Fehler - Discovery fehlgeschlagen: {detail}",
            is_error=True,
            progress_path=progress_path,
            use_environment_path=False,
        )
        return 1
    actual_count = suite.countTestCases()
    if actual_count != expected_count:
        _write_progress(
            f"Testdateimuster {pattern} - Fehler - Testfallzahl änderte sich: "
            f"geplant {expected_count}, gefunden {actual_count}.",
            is_error=True,
            progress_path=progress_path,
            use_environment_path=False,
        )
        return 1
    planned_cases = _collect_test_cases(suite)
    if len(planned_cases) != expected_count:
        _write_progress(
            f"Testdateimuster {pattern} - Fehler - Geplante TestCase-Fälle "
            f"({len(planned_cases)}) stimmen nicht mit der Discovery-Zahl "
            f"({expected_count}) überein.",
            is_error=True,
            progress_path=progress_path,
            use_environment_path=False,
        )
        return 1
    result = ProgressTestRunner(
        verbosity=0,
        completed_before=completed_before,
        total=total,
        progress_path=progress_path,
        planned_cases=planned_cases,
    ).run(suite)
    return 0 if result.wasSuccessful() and result.completed == expected_count else 1


def run_suite(root: Path, *, timeout_s: float = 600) -> int:
    started_at = time.monotonic()
    patterns = sorted({path.name for path in root.rglob("test*.py")})
    if not patterns:
        print(f"No test files found under {root}.", file=sys.stderr, flush=True)
        return 1

    progress_path = os.environ.get("SACRIFICIAL_TEST_PROGRESS_FILE")
    if progress_path:
        try:
            Path(progress_path).parent.mkdir(parents=True, exist_ok=True)
            Path(progress_path).write_text("", encoding="utf-8")
        except OSError as error:
            print(f"Could not initialize test progress file: {error}", file=sys.stderr, flush=True)

    counts, planning_error = plan_suite(root, patterns, timeout_s=timeout_s)
    if planning_error:
        _write_progress(planning_error, is_error=True)
        return 1
    assert counts is not None

    total = sum(counts.values())
    if total <= 0:
        _write_progress("Keine ausführbaren unittest-Testfälle gefunden.", is_error=True)
        return 1
    _write_progress(f"Geplante Einzeltests: {total} aus {len(patterns)} Testdateimustern.")

    completed = 0
    failed_patterns = []
    for pattern in patterns:
        expected_count = counts[pattern]
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--start-directory",
            str(root),
            "--run-pattern",
            pattern,
            "--expected-count",
            str(expected_count),
            "--completed-before",
            str(completed),
            "--total-tests",
            str(total),
        ]
        try:
            result = subprocess.run(command, timeout=timeout_s, check=False)
        except subprocess.TimeoutExpired:
            _write_progress(
                f"Testdateimuster {pattern} - Stockt - Zeitüberschreitung nach "
                f"{timeout_s:g} Sekunden.",
                is_error=True,
            )
            failed_patterns.append(pattern)
        else:
            if result.returncode != 0:
                failed_patterns.append(pattern)
        completed += expected_count

    duration = format_test_duration(time.monotonic() - started_at)
    if failed_patterns:
        _write_progress(
            f"Tests fehlgeschlagen: {', '.join(failed_patterns)}. "
            f"Gesamtdauer: {duration}",
            is_error=True,
        )
        return 1
    _write_progress(
        f"Alle {total} Einzeltests aus {len(patterns)} Testdateimustern erfolgreich. "
        f"Gesamtdauer: {duration}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-directory", type=Path, default=Path("tests"))
    parser.add_argument("--count-pattern")
    parser.add_argument("--run-pattern")
    parser.add_argument("--expected-count", type=int)
    parser.add_argument("--completed-before", type=int, default=0)
    parser.add_argument("--total-tests", type=int)
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    root = args.start_directory.resolve()

    if args.count_pattern is not None:
        try:
            count = count_pattern(root, args.count_pattern)
        except Exception as error:
            detail = str(error).splitlines()[-1] if str(error) else type(error).__name__
            print(
                f"Discovery failed for {args.count_pattern}: {detail}",
                file=sys.stderr,
                flush=True,
            )
            return 2
        print(f"{COUNT_MARKER}{count}", flush=True)
        return 0
    if args.run_pattern is not None:
        if args.expected_count is None or args.total_tests is None:
            parser.error("--run-pattern requires --expected-count and --total-tests")
        return run_pattern(
            root,
            args.run_pattern,
            expected_count=args.expected_count,
            completed_before=args.completed_before,
            total=args.total_tests,
        )
    if args.plan_only:
        patterns = sorted({path.name for path in root.rglob("test*.py")})
        if not patterns:
            print(f"No test files found under {root}.", file=sys.stderr, flush=True)
            return 1
        counts, planning_error = plan_suite(root, patterns)
        if planning_error:
            print(planning_error, file=sys.stderr, flush=True)
            return 1
        assert counts is not None
        total = sum(counts.values())
        print(f"Geplante Einzeltests: {total} aus {len(patterns)} Testdateimustern.")
        return 0 if total else 1
    return run_suite(root)


if __name__ == "__main__":
    raise SystemExit(main())
