"""Run the complete unittest discovery in separate processes per file pattern.

Qt retains application-wide objects across GUI modules. Process isolation keeps
their lifetime bounded without deleting live test objects or bypassing failures.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import time


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


def run_suite(root: Path, *, timeout_s: float = 600) -> int:
    patterns = sorted({path.name for path in root.rglob("test*.py")})
    if not patterns:
        print(f"No test files found under {root}.", file=sys.stderr, flush=True)
        return 1
    failed = []
    total = len(patterns)
    for index, pattern in enumerate(patterns, 1):
        percent = int(100 * index / total + 0.5)
        number = f"{index} / {total}"
        print(f"Starte Test: {number} ({percent}%) - {pattern}", flush=True)
        started_at = time.monotonic()
        command = [sys.executable, "-m", "unittest", "discover", "-s", str(root),
                   "-p", pattern, "-q"]
        try:
            result = subprocess.run(command, timeout=timeout_s, check=False)
        except subprocess.TimeoutExpired:
            duration = format_test_duration(time.monotonic() - started_at)
            print(
                f"Test {number} - Stockt - Zeitüberschreitung bei {pattern} "
                f"nach {timeout_s:g} Sekunden. Testdauer: {duration}",
                file=sys.stderr,
                flush=True,
            )
            failed.append(pattern)
        else:
            duration = format_test_duration(time.monotonic() - started_at)
            if result.returncode != 0:
                print(
                    f"Test {number} - Fehler - Exit-Code {result.returncode} "
                    f"({pattern}). Testdauer: {duration}",
                    file=sys.stderr,
                    flush=True,
                )
                failed.append(pattern)
            else:
                print(
                    f"Test {number} - erfolgreich - Testdauer: {duration}",
                    flush=True,
                )
    if failed:
        print("Failed test modules: " + ", ".join(failed), file=sys.stderr, flush=True)
        return 1
    print(f"All {len(patterns)} test-file patterns passed.", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-directory", type=Path, default=Path("tests"))
    args = parser.parse_args()
    return run_suite(args.start_directory.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
