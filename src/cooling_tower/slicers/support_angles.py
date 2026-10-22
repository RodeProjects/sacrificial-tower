"""Read explicit support thresholds with known, horizontal angle semantics."""
import math
from collections.abc import Mapping


def _profile_threshold_value(profile) -> float | None:
    identifier = getattr(getattr(profile, "installation", None), "adapter_id", None)
    key = {
        "orca_slicer": "support_threshold_angle",
        "anycubic_slicer_next": "support_threshold_angle",
        "bambu_studio": "support_threshold_angle",
        "prusa_slicer": "support_material_threshold",
    }.get(identifier)
    if key is None:
        return None
    values = getattr(profile, "effective_values", {})
    if not isinstance(values, Mapping):
        return None
    value = values.get(key)
    if isinstance(value, (list, tuple)):
        value = value[0] if len(value) == 1 else None
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def profile_support_threshold(profile) -> float | None:
    """Keep automatic/overlap detection separate from explicit support angles."""
    value = _profile_threshold_value(profile)
    return value if value is not None and 0.1 <= value <= 89.9 else None


def profile_binding_threshold(profile) -> float | None:
    """Preserve nonpositive raw values so the UI can explain its 30° fallback."""
    value = _profile_threshold_value(profile)
    return value if value is not None and value <= 89.9 else None
