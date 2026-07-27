from __future__ import annotations

import os
import re
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


def resolve_user_data_root(
    environment: dict[str, str] | None = None,
    *,
    instance_id: str | None = None,
) -> Path:
    """Return a writable, instance-separated application data root."""

    values = os.environ if environment is None else environment
    explicit = values.get("COOLING_TOWER_USER_DATA_ROOT", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    selected_instance = (
        values.get("COOLING_TOWER_INSTANCE_ID", "").strip()
        or (instance_id or "").strip()
        or ("standalone" if IS_FROZEN else "development")
    )
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", selected_instance):
        raise ValueError(
            "Die Sacrificial-Tower-Instanz-ID enthält unzulässige Zeichen."
        )
    local_app_data = values.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        base = Path(local_app_data).expanduser()
    else:
        base = Path.home() / ".local" / "share"
    return (
        base
        / "RodeProjects"
        / "SacrificialTower"
        / selected_instance
    ).resolve()


USER_DATA_ROOT = resolve_user_data_root()
USER_CONFIG_ROOT = USER_DATA_ROOT / "config"
USER_LOG_ROOT = USER_DATA_ROOT / "logs"
USER_OUTPUT_ROOT = USER_DATA_ROOT / "output"
