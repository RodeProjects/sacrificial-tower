"""Angle presentation boundary; persisted geometry angles remain vertical.

The UI and CLI use slopes measured from the horizontal print bed. Existing
domain settings and saved drafts keep their vertical reference so upgrading
cannot change the geometry of an existing tower.
"""
from dataclasses import dataclass
import math

GENERATION_ANGLE_FIELDS = frozenset({
    "maximum_expansion_angle_deg", "maximum_contraction_angle_deg",
})
MANUAL_ANGLE_FIELDS = frozenset({
    "expansion_angle_deg", "contraction_angle_deg", "overhang_angle_deg",
})


def complementary_angle(value: float) -> float:
    """Convert between vertical and horizontal references without rounding."""
    return 90.0 - float(value)


def profile_binding_angle(value: float | None) -> float | None:
    """Normalize only a read profile value, without changing the slicer profile."""
    if value is None or isinstance(value, bool) or not math.isfinite(value):
        return None
    if value <= 0:
        return 30.0
    return value if value <= 89.9 and complementary_angle(value) < 90 else None


@dataclass
class ProfileAngleBinding:
    """Keep a free vertical angle while a profile supplies the effective one."""
    free_angle_deg: float = 50.0
    active: bool = False
    effective_angle_deg: float | None = None

    def resolve(self, current: float, requested: bool, threshold: float | None) -> float:
        if not self.active:
            self.free_angle_deg = min(70.0, max(1.0, current))
        threshold = profile_binding_angle(threshold)
        self.active = requested and threshold is not None
        self.effective_angle_deg = (complementary_angle(threshold) if self.active
                                    else self.free_angle_deg)
        return self.effective_angle_deg
