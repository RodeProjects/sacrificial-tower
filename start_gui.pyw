"""Windowed Windows entry point using the project's virtual environment."""

from __future__ import annotations

import subprocess
import sys
import traceback
from pathlib import Path


PROJECT_ROOT = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)
PROJECT_VENV = PROJECT_ROOT / ".venv"
PROJECT_PYTHONW = PROJECT_VENV / "Scripts" / "pythonw.exe"
SRC_ROOT = PROJECT_ROOT / "src"
if not getattr(sys, "frozen", False) and str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def _fallback_startup_error(details: str) -> None:
    try:
        from cooling_tower.runtime_paths import resolve_user_data_root
        from cooling_tower.write_policy import ensure_writable_output

        log_path = ensure_writable_output(
            resolve_user_data_root() / "logs" / "application_startup.log"
        )
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(details, encoding="utf-8")
        location = str(log_path.resolve())
    except Exception:
        # Last-resort diagnostics must not write into the installation when
        # resource imports or the configured application data path are broken.
        location = "nicht verfügbar"
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            0,
            "Die Anwendung konnte nicht vollständig gestartet werden.\n\n"
            f"Fehlerdetails: {location}",
            "Kühlturm-Generator – Startfehler",
            0x10,
        )
    except Exception:
        pass


def _ensure_project_venv() -> None:
    """Replace a file-association interpreter with the project's pythonw."""

    if getattr(sys, "frozen", False):
        return
    try:
        already_in_project_venv = (
            Path(sys.prefix).resolve() == PROJECT_VENV.resolve()
        )
    except OSError:
        already_in_project_venv = False
    if already_in_project_venv:
        return
    if not PROJECT_PYTHONW.is_file():
        return
    from cooling_tower.windows_process import windows_subprocess_creation_flags

    script_path = Path(__file__).resolve()
    creation_flags = windows_subprocess_creation_flags(
        getattr(subprocess, "CREATE_NO_WINDOW", 0),
        getattr(subprocess, "DETACHED_PROCESS", 0),
    )
    subprocess.Popen(
        [str(PROJECT_PYTHONW), str(script_path), *sys.argv[1:]],
        cwd=str(PROJECT_ROOT),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=creation_flags,
    )
    raise SystemExit(0)


try:
    _ensure_project_venv()
except Exception:
    _fallback_startup_error(traceback.format_exc())
    raise SystemExit(1)

try:
    from cooling_tower.application import run_application
except Exception:
    _fallback_startup_error(traceback.format_exc())
    raise SystemExit(1)

raise SystemExit(run_application())
