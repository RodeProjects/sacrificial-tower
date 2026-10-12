"""Run the complete unittest discovery in separate processes per file pattern.

Qt retains application-wide objects across GUI modules. Process isolation keeps
their lifetime bounded without deleting live test objects or bypassing failures.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


def run_suite(root: Path, *, timeout_s: float = 600) -> int:
    patterns = sorted({path.name for path in root.rglob("test*.py")})
    if not patterns:
        print(f"No test files found under {root}.", file=sys.stderr, flush=True)
        return 1
    failed = []
    for index, pattern in enumerate(patterns, 1):
        print(f"[{index}/{len(patterns)}] {pattern}", flush=True)
        command = [sys.executable, "-m", "unittest", "discover", "-s", str(root),
                   "-p", pattern, "-q"]
        try:
            result = subprocess.run(command, timeout=timeout_s, check=False)
        except subprocess.TimeoutExpired:
            print(f"TIMEOUT: {pattern} exceeded {timeout_s:g} seconds.",
                  file=sys.stderr, flush=True)
            failed.append(pattern)
        else:
            if result.returncode != 0:
                failed.append(pattern)
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
