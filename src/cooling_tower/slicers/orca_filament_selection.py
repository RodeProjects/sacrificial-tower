"""Read Orca's enabled system filaments independently of its active material."""
from __future__ import annotations

from cooling_tower.slicers.active_presets import (
    _candidate_config_paths,
    _load_json_with_checksum_footer,
    _safe_modified_ns,
)
from cooling_tower.slicers.models import ProfileRecord, SlicerInstallation


_MAXIMUM_CONFIG_BYTES = 2 * 1024 * 1024


def enabled_system_filaments(
    installation: SlicerInstallation,
) -> frozenset[str] | None:
    """Return exact names; None means the optional selection is unavailable.

    Use the same installation-scoped configuration locations as active preset
    detection, including portable and Store data. Never borrow an older
    selection when the newest configuration is damaged or no longer has one.
    """
    try:
        paths = _candidate_config_paths(installation)
        if not paths:
            return None
        path = max(paths, key=lambda p: (_safe_modified_ns(p), str(p).casefold()))
        if path.stat().st_size > _MAXIMUM_CONFIG_BYTES:
            return None
        with path.open("rb") as stream:
            raw = stream.read(_MAXIMUM_CONFIG_BYTES + 1)
        if len(raw) > _MAXIMUM_CONFIG_BYTES:
            return None
        payload = _load_json_with_checksum_footer(raw.decode("utf-8-sig"))
    except (OSError, ValueError, RecursionError):
        return None
    if not isinstance(payload, dict):
        return None
    names = payload.get("filaments")
    if not isinstance(names, list) or any(
        not isinstance(name, str) or not name.strip() for name in names
    ):
        return None
    return frozenset(name.strip().casefold() for name in names)


def filter_filament_options(
    installation: SlicerInstallation,
    profiles: tuple[ProfileRecord, ...],
) -> tuple[ProfileRecord, ...]:
    """Restrict visibility only; keep every profile available for inheritance.

    An explicitly empty selection falls back to all system materials, as does
    a missing/unreadable optional selection. A nonempty selection with no
    matching compatible profile must never be mistaken for an empty selection.
    User presets are independent of the system-material selection.
    """
    enabled = enabled_system_filaments(installation)
    if not enabled:
        return profiles
    return tuple(
        profile for profile in profiles
        if profile.source.casefold() != "system"
        or profile.name.casefold() in enabled
        or profile.profile_id.casefold() in enabled
    )
