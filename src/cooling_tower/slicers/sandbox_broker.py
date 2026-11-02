"""Trusted, non-GUI entry point for one protected native slicer process."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys


def main(arguments: list[str] | None = None) -> int:
    args = sys.argv[1:] if arguments is None else arguments
    if len(args) != 1:
        return 125
    path = Path(args[0]).resolve(strict=True)
    if path.stat().st_size > 1024 * 1024:
        return 125
    # -I intentionally ignores PYTHONPATH and user-site packages.
    source_root = Path(__file__).resolve().parents[2]
    if not getattr(sys, "frozen", False):
        sys.path.insert(0, str(source_root))
    from cooling_tower.slicers.windows_lpac import run_lpac
    try:
        return run_lpac(json.loads(path.read_text(encoding="utf-8")))
    except Exception as error:
        # Detailed error data stays in the parent-owned local diagnostics.
        print(f"Sicherer Slicerstart fehlgeschlagen: {type(error).__name__}: {error}", file=sys.stderr)
        return 125


if __name__ == "__main__":
    os._exit(main())
