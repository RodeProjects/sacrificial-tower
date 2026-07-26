"""Compatibility imports for the Phase-2/3 module name."""

from __future__ import annotations

import sys
from pathlib import Path


_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from cooling_tower.tower.profile import *  # noqa: F401,F403,E402
