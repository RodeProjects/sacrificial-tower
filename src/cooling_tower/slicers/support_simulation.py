"""Explicit, request-scoped support activation without changing source presets."""
from dataclasses import replace

from cooling_tower.slicers.models import EffectiveProfile, SliceResult


SUPPORT_KEYS = {
    "anycubic_slicer_next": "enable_support",
    "orca_slicer": "enable_support",
    "bambu_studio": "enable_support",
    "prusa_slicer": "support_material",
    "cura": "support_enable",
}


def with_simulated_supports(profile: EffectiveProfile) -> EffectiveProfile:
    key = SUPPORT_KEYS[profile.installation.adapter_id]
    return replace(profile, supports_simulated=True,
                   effective_values={**profile.effective_values, key: "1"})


def can_offer_support_simulation(result: SliceResult, profile: EffectiveProfile) -> bool:
    key = SUPPORT_KEYS.get(profile.installation.adapter_id)
    if not key or profile.supports_simulated or result.success or (
        result.cancelled or result.timed_out or result.crashed
    ):
        return False
    value = profile.effective_values.get(key, False)
    if isinstance(value, (list, tuple)):
        value = value[0] if value else False
    if str(value).strip().casefold() in {"1", "true", "yes"}:
        return False
    output = f"{result.stdout}\n{result.stderr}".casefold()
    # Anycubic conceals its collected slicing exceptions behind "Errors".
    # This code is only an offer to retry, not a diagnosis of an empty layer.
    generic_geometry_error = (
        profile.installation.adapter_id == "anycubic_slicer_next"
        and result.return_code is not None
        and result.return_code & 0xFFFFFFFF == 0xFFFFFF9C
    )
    return generic_geometry_error or any(marker in output for marker in (
        "empty initial layer", "empty first layer", "enable supports",
        "no extrusions on the first layer",
    ))
