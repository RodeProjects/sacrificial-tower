"""Apply the source/test Windows process policy before test discovery starts.

Python imports ``sitecustomize`` automatically during normal interpreter
startup.  Loading the lightweight policy module directly avoids importing the
full application package or changing ``sys.path`` merely to protect test child
processes.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path


def _configure_source_windows_process_policy() -> None:
    if os.name != "nt":
        return
    policy_path = (
        Path(__file__).resolve().parent
        / "src"
        / "cooling_tower"
        / "windows_process.py"
    )
    spec = importlib.util.spec_from_file_location(
        "_cooling_tower_windows_process_bootstrap",
        policy_path,
    )
    if spec is None or spec.loader is None:
        return
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.configure_windows_process_policy()


try:
    _configure_source_windows_process_policy()
except Exception:
    # Application startup retries through cooling_tower.__init__.  The live
    # Windows integration test makes a silent bootstrap failure visible in CI.
    pass
