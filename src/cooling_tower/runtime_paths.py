from __future__ import annotations

import sys
from pathlib import Path


SOURCE_PROJECT_ROOT = Path(__file__).resolve().parents[2]
IS_FROZEN = bool(getattr(sys, "frozen", False))

# PyInstaller keeps bundled resources below sys._MEIPASS, while files that
# must survive an update live next to the installed executable.
INSTALL_ROOT = (
    Path(sys.executable).resolve().parent if IS_FROZEN else SOURCE_PROJECT_ROOT
)
RESOURCE_ROOT = (
    Path(getattr(sys, "_MEIPASS")).resolve()
    if IS_FROZEN and getattr(sys, "_MEIPASS", None)
    else SOURCE_PROJECT_ROOT
)
