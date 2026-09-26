"""Recognize and disable draft shields only in disposable profile copies."""

from dataclasses import dataclass, replace
from typing import Any, Mapping

from cooling_tower.slicers.models import EffectiveProfile


@dataclass(frozen=True)
class DraftShieldSource:
    role: str
    profile_name: str


def _first(value: Any) -> Any:
    return value[0] if isinstance(value, (list, tuple)) and value else value


def _positive(value: Any) -> bool:
    try:
        return float(_first(value)) > 0
    except (TypeError, ValueError):
        return False


def _enabled(value: Any) -> bool:
    return str(_first(value)).strip().casefold() in {
        "1", "true", "yes", "on", "enabled",
    }


def draft_shield_active(values: Mapping[str, Any]) -> bool:
    if _enabled(values.get("draft_shield")):
        return True
    # Bambu's tall skirt serves the same purpose; a normal one-layer skirt
    # must not prompt the user.
    return _positive(values.get("skirt_loops")) and _positive(
        _skirt_height_above_one(values.get("skirt_height"))
    )


def _skirt_height_above_one(value: Any) -> float:
    try:
        return max(0.0, float(_first(value)) - 1.0)
    except (TypeError, ValueError):
        return 0.0


def draft_shield_source(profile: EffectiveProfile, resolved_profiles=()) -> DraftShieldSource | None:
    records = (
        ("process", profile.process),
        *(("filament", record) for record in profile.filaments),
    )
    for role, record in records:
        if record is None:
            continue
        resolved = next(
            (item for item in resolved_profiles if item.record.path == record.path),
            None,
        )
        if resolved is not None and draft_shield_active(resolved.effective_values):
            return DraftShieldSource(role, record.name)
    if not draft_shield_active(profile.effective_values):
        return None
    return DraftShieldSource("process", profile.process.name if profile.process else "")


def with_simulated_draft_shield_disabled(profile: EffectiveProfile) -> EffectiveProfile:
    values = dict(profile.effective_values)
    values["skirt_loops"] = "0"
    if "draft_shield" in values or profile.installation.adapter_id == "anycubic_slicer_next":
        values["draft_shield"] = "disabled"
    return replace(
        profile,
        draft_shield_simulated=True,
        effective_values=values,
    )
