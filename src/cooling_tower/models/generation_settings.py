from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, Mapping
from cooling_tower.settings_defaults import GENERATION_DEFAULTS
from cooling_tower.models.layer_ranges import LayerRange, normalize_layer_ranges


_UNSET = object()
_LEGACY_HOLLOW_DEFAULTS: Mapping[str, float] = {
    "minimum_wall_thickness_mm": 0.80,
    "maximum_wall_thickness_mm": 4.20,
    "wall_path_width_mm": 0.42,
    "minimum_inner_radius_mm": 2.0,
    "maximum_wall_change_per_mm_z": 0.42,
}


@dataclass(frozen=True, slots=True, init=False)
class GenerationSettings:
    """User-facing tower-generation settings.

    Diameter is the persisted and displayed width contract.  Read-only radius
    properties remain as a calculation convenience so geometry code cannot
    accidentally expose radius values to users again.

    Private hollow-geometry values are accepted only as a transitional Python
    API for old in-process callers.  They are deliberately absent from
    :meth:`to_dict`, the GUI, CLI and persisted settings schema.
    """

    target_layer_time_s: float
    layer_time_tolerance_s: float

    minimum_outer_diameter_mm: float
    maximum_outer_diameter_mm: float
    minimum_object_tower_distance_mm: float
    simulate_full_tower_infill: bool
    simulate_tower_without_supports: bool
    simulate_source_supports: bool

    minimum_base_radius_mm: float
    _legacy_base_height_mm: float = field(repr=False, compare=False)
    base_margin_mm: float
    base_height_factor: float
    automatic_base_width: bool
    manual_base_width_mm: float

    minimum_radius_height_factor: float
    maximum_radius_change_per_mm_z: float
    maximum_expansion_angle_deg: float
    maximum_contraction_angle_deg: float

    local_reference_window: int
    # Object-bound session data; deliberately absent from global user defaults.
    excluded_layer_ranges: tuple[LayerRange, ...]

    _legacy_minimum_wall_thickness_mm: float = field(
        repr=False, compare=False
    )
    _legacy_maximum_wall_thickness_mm: float = field(
        repr=False, compare=False
    )
    _legacy_wall_path_width_mm: float = field(
        repr=False, compare=False
    )
    _legacy_minimum_inner_radius_mm: float = field(
        repr=False, compare=False
    )
    _legacy_maximum_wall_change_per_mm_z: float = field(
        repr=False, compare=False
    )

    def __init__(
        self,
        target_layer_time_s: float = GENERATION_DEFAULTS["target_layer_time_s"],
        minimum_outer_diameter_mm: float | object = _UNSET,
        maximum_outer_diameter_mm: float | object = _UNSET,
        minimum_object_tower_distance_mm: float = GENERATION_DEFAULTS["minimum_object_tower_distance_mm"],
        simulate_full_tower_infill: bool = GENERATION_DEFAULTS["simulate_full_tower_infill"],
        simulate_tower_without_supports: bool = GENERATION_DEFAULTS["simulate_tower_without_supports"],
        simulate_source_supports: bool = False,
        minimum_base_radius_mm: float = GENERATION_DEFAULTS["minimum_base_radius_mm"],
        base_margin_mm: float = GENERATION_DEFAULTS["base_margin_mm"],
        base_height_factor: float = GENERATION_DEFAULTS["base_height_factor"],
        automatic_base_width: bool = GENERATION_DEFAULTS["automatic_base_width"],
        manual_base_width_mm: float = GENERATION_DEFAULTS["manual_base_width_mm"],
        minimum_radius_height_factor: float = GENERATION_DEFAULTS["minimum_radius_height_factor"],
        maximum_radius_change_per_mm_z: float = GENERATION_DEFAULTS["maximum_radius_change_per_mm_z"],
        maximum_expansion_angle_deg: float = GENERATION_DEFAULTS["maximum_expansion_angle_deg"],
        maximum_contraction_angle_deg: float = GENERATION_DEFAULTS["maximum_contraction_angle_deg"],
        local_reference_window: int = GENERATION_DEFAULTS["local_reference_window"],
        layer_time_tolerance_s: float = GENERATION_DEFAULTS["layer_time_tolerance_s"],
        excluded_layer_ranges: tuple[LayerRange, ...] = (),
        **legacy: Any,
    ) -> None:
        legacy_base_height = legacy.pop("base_height_mm", legacy.pop("_legacy_base_height_mm", 1.0))
        object.__setattr__(self, "_legacy_base_height_mm", float(legacy_base_height))
        legacy_minimum_radius = legacy.pop("minimum_outer_radius_mm", _UNSET)
        legacy_maximum_radius = legacy.pop("maximum_outer_radius_mm", _UNSET)
        if legacy_minimum_radius is not _UNSET:
            minimum_outer_diameter_mm = 2.0 * float(legacy_minimum_radius)
        elif minimum_outer_diameter_mm is _UNSET:
            minimum_outer_diameter_mm = GENERATION_DEFAULTS["minimum_outer_diameter_mm"]
        if legacy_maximum_radius is not _UNSET:
            maximum_outer_diameter_mm = 2.0 * float(legacy_maximum_radius)
        elif maximum_outer_diameter_mm is _UNSET:
            maximum_outer_diameter_mm = GENERATION_DEFAULTS["maximum_outer_diameter_mm"]

        hollow_values: dict[str, float] = {}
        for name, default in _LEGACY_HOLLOW_DEFAULTS.items():
            carried = legacy.pop(f"_legacy_{name}", default)
            hollow_values[name] = float(legacy.pop(name, carried))
        if legacy:
            unknown = ", ".join(sorted(legacy))
            raise TypeError(f"Unknown generation setting(s): {unknown}")

        public_values = {
            "target_layer_time_s": target_layer_time_s,
            "layer_time_tolerance_s": layer_time_tolerance_s,
            "minimum_outer_diameter_mm": minimum_outer_diameter_mm,
            "maximum_outer_diameter_mm": maximum_outer_diameter_mm,
            "minimum_object_tower_distance_mm": minimum_object_tower_distance_mm,
            "simulate_full_tower_infill": simulate_full_tower_infill,
            "simulate_tower_without_supports": simulate_tower_without_supports,
            "simulate_source_supports": simulate_source_supports,
            "minimum_base_radius_mm": minimum_base_radius_mm,
            "base_margin_mm": base_margin_mm,
            "base_height_factor": base_height_factor,
            "automatic_base_width": automatic_base_width,
            "manual_base_width_mm": manual_base_width_mm,
            "minimum_radius_height_factor": minimum_radius_height_factor,
            "maximum_radius_change_per_mm_z": maximum_radius_change_per_mm_z,
            "maximum_expansion_angle_deg": maximum_expansion_angle_deg,
            "maximum_contraction_angle_deg": maximum_contraction_angle_deg,
            "local_reference_window": local_reference_window,
        }
        for name, value in public_values.items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, "excluded_layer_ranges", normalize_layer_ranges(excluded_layer_ranges))
        for name, value in hollow_values.items():
            object.__setattr__(self, f"_legacy_{name}", value)

    @property
    def minimum_outer_radius_mm(self) -> float:
        return float(self.minimum_outer_diameter_mm) / 2.0

    @property
    def maximum_outer_radius_mm(self) -> float:
        return float(self.maximum_outer_diameter_mm) / 2.0

    # Transitional read-only properties keep historical hollow-profile unit
    # tests importable while all active workflows use the solid profile.
    @property
    def base_height_mm(self) -> float:
        return self._legacy_base_height_mm

    @property
    def minimum_wall_thickness_mm(self) -> float:
        return self._legacy_minimum_wall_thickness_mm

    @property
    def maximum_wall_thickness_mm(self) -> float:
        return self._legacy_maximum_wall_thickness_mm

    @property
    def wall_path_width_mm(self) -> float:
        return self._legacy_wall_path_width_mm

    @property
    def minimum_inner_radius_mm(self) -> float:
        return self._legacy_minimum_inner_radius_mm

    @property
    def maximum_wall_change_per_mm_z(self) -> float:
        return self._legacy_maximum_wall_change_per_mm_z

    def to_dict(self, *, include_object_settings: bool = False) -> dict[str, Any]:
        return {
            item.name: getattr(self, item.name)
            for item in fields(self)
            if not item.name.startswith("_legacy_")
            and (include_object_settings or item.name not in {"excluded_layer_ranges", "simulate_source_supports"})
        }

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, Any],
    ) -> "GenerationSettings":
        public = {
            item.name
            for item in fields(cls)
            if not item.name.startswith("_legacy_")
        }
        allowed = public | {
            "base_height_mm",
            "minimum_outer_radius_mm",
            "maximum_outer_radius_mm",
            *_LEGACY_HOLLOW_DEFAULTS,
        }
        unknown = sorted(set(values) - allowed)
        if unknown:
            raise ValueError(
                "Unknown generation setting(s): " + ", ".join(unknown)
            )
        return cls(**dict(values))
