from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class GenerationSettings:
    """All settings shared by command-line and graphical front ends."""

    target_layer_time_s: float = 11.0
    safety_factor: float = 1.10

    minimum_outer_radius_mm: float = 5.0
    maximum_outer_radius_mm: float = 20.0

    minimum_wall_thickness_mm: float = 0.80
    maximum_wall_thickness_mm: float = 4.20
    wall_path_width_mm: float = 0.42
    minimum_inner_radius_mm: float = 2.0

    minimum_base_radius_mm: float = 10.0
    base_height_mm: float = 4.0
    base_margin_mm: float = 2.0
    base_height_factor: float = 0.05
    automatic_base_width: bool = True
    manual_base_width_mm: float = 20.0

    minimum_radius_height_factor: float = 0.04
    maximum_radius_change_per_mm_z: float = 0.35
    maximum_expansion_angle_deg: float = 50.0
    maximum_contraction_angle_deg: float = 50.0
    maximum_wall_change_per_mm_z: float = 0.42

    local_reference_window: int = 5
    mesh_segments: int = 32

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, Any],
    ) -> "GenerationSettings":
        allowed = {field.name for field in fields(cls)}
        unknown = sorted(set(values) - allowed)
        if unknown:
            raise ValueError(
                "Unknown generation setting(s): " + ", ".join(unknown)
            )
        return cls(**dict(values))
