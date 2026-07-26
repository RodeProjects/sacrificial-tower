"""Windowed Windows entry point using the project's virtual environment."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path


PROJECT_ROOT = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)
SRC_ROOT = PROJECT_ROOT / "src"
if not getattr(sys, "frozen", False) and str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def _fallback_startup_error(details: str) -> None:
    log_path = PROJECT_ROOT / "output" / "logs" / "application_startup.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(details, encoding="utf-8")
        location = str(log_path.resolve())
    except OSError:
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


try:
    from cooling_tower.application import run_application
except Exception:
    _fallback_startup_error(traceback.format_exc())
    raise SystemExit(1)

raise SystemExit(run_application())
