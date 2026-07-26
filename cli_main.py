"""Convenient launcher for command-line generation."""

from __future__ import annotations

import sys
from pathlib import Path


SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cooling_tower.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
