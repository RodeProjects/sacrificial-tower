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

OBJECT_SUPPORT_ADAPTERS = frozenset({"anycubic_slicer_next", "orca_slicer", "bambu_studio", "prusa_slicer"})


def simulated_support_settings(profile: EffectiveProfile) -> dict[str, str]:
    """Use each integration's policy without modifying any source preset."""
    identifier = profile.installation.adapter_id
    if identifier == "orca_slicer":
        from cooling_tower.slicers.orca_supports import simulated_support_settings as settings
        return settings()
    if identifier == "prusa_slicer":
        from cooling_tower.slicers.prusa_supports import simulated_support_settings as settings
        return settings(profile.installation.version)
    return {SUPPORT_KEYS[identifier]: "1"}


def global_supports_disabled(profile: EffectiveProfile) -> bool:
    """Offer object support simulation only for a recognized disabled value."""
    key = SUPPORT_KEYS.get(getattr(getattr(profile, "installation", None), "adapter_id", None))
    if key is None:
        return False
    value = getattr(profile, "effective_values", {}).get(key)
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    return value is not None and str(value).strip().casefold() in {"0", "false", "no"}


def global_supports_enabled(profile: EffectiveProfile) -> bool:
    key = SUPPORT_KEYS.get(profile.installation.adapter_id)
    value = profile.effective_values.get(key)
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    return profile.supports_simulated or str(value).strip().casefold() in {"1", "true", "yes"}


def with_simulated_supports(profile: EffectiveProfile) -> EffectiveProfile:
    return replace(profile, supports_simulated=True,
                   effective_values={**profile.effective_values, **simulated_support_settings(profile)})


def tower_support_warning_angle(profile: EffectiveProfile) -> float | None:
    """Return the tower's vertical angle at the Orca-family support threshold.

    ``support_threshold_angle`` is measured from the horizontal surface,
    whereas tower expansion is measured from the vertical axis. A zero
    threshold switches the slicer to overlap-based detection.
    """
    key = SUPPORT_KEYS.get(profile.installation.adapter_id)
    if key is None:
        return None
    enabled = profile.effective_values.get(key, "0")
    if isinstance(enabled, (list, tuple)):
        enabled = enabled[0] if enabled else "0"
    if str(enabled).strip().casefold() not in {"1", "true", "yes"}:
        return None
    from cooling_tower.slicers.support_angles import profile_support_threshold
    threshold = profile_support_threshold(profile)
    return 90.0 - threshold if threshold is not None else None


def can_offer_support_simulation(result: SliceResult, profile: EffectiveProfile) -> bool:
    key = SUPPORT_KEYS.get(profile.installation.adapter_id)
    if not key or not global_supports_disabled(profile) or profile.supports_simulated or result.success or (
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
    from cooling_tower.gcode.empty_layers import reports_empty_layers
    return generic_geometry_error or reports_empty_layers(output) or any(marker in output for marker in (
        "empty initial layer", "empty first layer", "enable supports",
        "no extrusions on the first layer",
    ))
