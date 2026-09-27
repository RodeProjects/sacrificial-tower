from __future__ import annotations

import math


MINIMUM_BASE_WIDTH_MM = 20.0
MAXIMUM_BASE_WIDTH_MM = 100.0
BASE_WIDTH_PER_OBJECT_HEIGHT = 0.2


def calculate_phase10_base_outer_radius(
    *,
    object_height_mm: float,
    automatic_base_width: bool,
    manual_base_width_mm: float,
) -> float:
    """Return the Phase-10 stand width as an outer radius.

    In automatic mode the diameter follows 0.2 mm per millimetre of the
    analyzed G-code object's full height, bounded to 20–100 mm. A manual
    diameter must also remain in that range. The base is deliberately allowed
    to be wider than the regular maximum outer radius.
    """
    if not math.isfinite(object_height_mm) or object_height_mm <= 0.0:
        raise ValueError("Object height must be finite and greater than zero.")
    if not isinstance(automatic_base_width, bool):
        raise ValueError("Automatic base width must be a boolean value.")
    if not math.isfinite(manual_base_width_mm):
        raise ValueError("Manual base width must be finite.")
    if (
        not automatic_base_width
        and manual_base_width_mm < MINIMUM_BASE_WIDTH_MM
    ):
        raise ValueError(
            f"Manual base width must be at least {MINIMUM_BASE_WIDTH_MM:g} mm."
        )
    if (
        not automatic_base_width
        and manual_base_width_mm > MAXIMUM_BASE_WIDTH_MM
    ):
        raise ValueError(
            f"Manual base width must be at most {MAXIMUM_BASE_WIDTH_MM:g} mm."
        )

    if automatic_base_width:
        diameter_mm = min(
            MAXIMUM_BASE_WIDTH_MM,
            max(
                MINIMUM_BASE_WIDTH_MM,
                object_height_mm * BASE_WIDTH_PER_OBJECT_HEIGHT,
            ),
        )
    else:
        diameter_mm = manual_base_width_mm
    return diameter_mm / 2.0
