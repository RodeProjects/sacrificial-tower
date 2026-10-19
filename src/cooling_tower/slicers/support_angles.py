"""Read explicit support thresholds with known, horizontal angle semantics."""
import math
from collections.abc import Mapping


def profile_support_threshold(profile) -> float | None:
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
    # 0 means automatic/overlap detection, not a measured surface angle.
    # The editable geometry excludes horizontal/vertical singularities.
    return value if math.isfinite(value) and 0.1 <= value <= 89.9 else None
