from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TowerLayerProfile:
    """Final hollow tower geometry and timing result for one layer."""

    index: int
    z: float
    required_path_mm: float
    available_path_mm: float
    outer_radius_mm: float
    inner_radius_mm: float
    wall_thickness_mm: float
    wall_path_count: int
    target_reached: bool
    layer_time_s: float = 0.0
    time_deficit_s: float = 0.0
    raw_outer_radius_mm: float = 0.0
    expansion_angle_deg: float = 0.0
    contraction_angle_deg: float = 0.0
    estimated_added_time_s: float | None = None
    profile_region: str = "layer"

    @property
    def effective_wall_thickness_mm(self) -> float:
        return self.wall_thickness_mm
