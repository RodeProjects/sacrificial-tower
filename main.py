"""Project launcher and backward-compatible CLI module."""

from __future__ import annotations

import sys
from pathlib import Path


_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from cooling_tower.cli import *  # noqa: F401,F403,E402
from cooling_tower.cli import main as _cli_main  # noqa: E402


if __name__ == "__main__":
    from multiprocessing import freeze_support

    freeze_support()
    if len(sys.argv) > 1 and sys.argv[1] == "--slicer-sandbox":
        import os
        from cooling_tower.slicers.sandbox_broker import main as run_sandbox
        os._exit(run_sandbox(sys.argv[2:]))
    if len(sys.argv) > 1:
        raise SystemExit(_cli_main())
    from cooling_tower.application import run_application

    raise SystemExit(run_application())
