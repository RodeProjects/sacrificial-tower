from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


class CalibrationMode(str, Enum):
    """Output whose timing evidence is produced by a calibration run."""

    STL = "stl"
    GCODE = "gcode"


class CalibrationState(str, Enum):
    NOT_STARTED = "not_started"
    CONVERGED = "converged"
    LIMIT_REACHED = "limit_reached"
    SLICER_FAILED = "slicer_failed"
    UNSUPPORTED = "unsupported"
    INVALID_GEOMETRY = "invalid_geometry"
    CANCELLED = "cancelled"


class CalibrationFailureCode(str, Enum):
    MAXIMUM_RADIUS = "maximum_radius"
    MAXIMUM_WALL_THICKNESS = "maximum_wall_thickness"
    TRANSITION_ANGLE = "transition_angle"
    NO_BED_SPACE = "no_bed_space"
    SLICER_FAILURE = "slicer_failure"
    PROFILE_INCOMPLETE = "profile_incomplete"
    LAYER_MISMATCH = "layer_mismatch"
    UNSUPPORTED_GCODE = "unsupported_gcode"
    SLICER_TIMING_MISMATCH = "slicer_timing_mismatch"
    ITERATION_LIMIT = "iteration_limit"
    RUNTIME_LIMIT = "runtime_limit"
    STALLED = "stalled"
    GEOMETRY_INVALID = "geometry_invalid"
    FINAL_TIMING_DEFICIT = "final_timing_deficit"


@dataclass(frozen=True, slots=True)
class CalibrationConfig:
    """Bounded controls for the iterative slicer feedback loop."""

    mode: CalibrationMode = CalibrationMode.STL
    maximum_iterations: int = 5
    maximum_runtime_s: float = 600.0
    time_tolerance_s: float = 0.15
    slicer_metadata_tolerance_s: float = 0.75
    profile_change_tolerance_mm: float = 0.03
    maximum_path_growth_factor: float = 2.0
    minimum_path_growth_mm: float = 0.5
    material_reduction_factor: float = 0.35
    repeated_result_limit: int = 2
    object_clearance_mm: float = 5.0
    bed_edge_clearance_mm: float = 3.0
    travel_speed_mm_s: float = 150.0
    retraction_length_mm: float = 0.8
    retraction_speed_mm_s: float = 35.0
    timeout_per_slice_s: float = 300.0

    def __post_init__(self) -> None:
        if not 0 <= self.maximum_iterations <= 10:
            raise ValueError(
                "maximum_iterations muss zwischen null und zehn liegen"
            )
        if self.repeated_result_limit < 1:
            raise ValueError("repeated_result_limit must be at least one")
        for name in (
            "maximum_runtime_s",
            "time_tolerance_s",
            "slicer_metadata_tolerance_s",
            "profile_change_tolerance_mm",
            "maximum_path_growth_factor",
            "minimum_path_growth_mm",
            "material_reduction_factor",
            "object_clearance_mm",
            "bed_edge_clearance_mm",
            "travel_speed_mm_s",
            "retraction_length_mm",
            "retraction_speed_mm_s",
            "timeout_per_slice_s",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        if self.maximum_runtime_s <= 0.0 or self.timeout_per_slice_s <= 0.0:
            raise ValueError("runtime and slice timeouts must be greater than zero")
        if self.maximum_path_growth_factor < 1.0:
            raise ValueError("maximum_path_growth_factor must be at least one")
        if not 0.0 <= self.material_reduction_factor <= 1.0:
            raise ValueError("material_reduction_factor must be between zero and one")


@dataclass(frozen=True, slots=True)
class BedBounds:
    minimum_x_mm: float
    maximum_x_mm: float
    minimum_y_mm: float
    maximum_y_mm: float

    def __post_init__(self) -> None:
        values = (
            self.minimum_x_mm,
            self.maximum_x_mm,
            self.minimum_y_mm,
            self.maximum_y_mm,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Bed bounds must be finite")
        if self.maximum_x_mm <= self.minimum_x_mm:
            raise ValueError("Bed X bounds are empty")
        if self.maximum_y_mm <= self.minimum_y_mm:
            raise ValueError("Bed Y bounds are empty")


@dataclass(frozen=True, slots=True)
class OccupiedBounds:
    minimum_x_mm: float
    maximum_x_mm: float
    minimum_y_mm: float
    maximum_y_mm: float

    def expanded(self, margin_mm: float) -> "OccupiedBounds":
        return OccupiedBounds(
            self.minimum_x_mm - margin_mm,
            self.maximum_x_mm + margin_mm,
            self.minimum_y_mm - margin_mm,
            self.maximum_y_mm + margin_mm,
        )


@dataclass(frozen=True, slots=True)
class TowerPlacement:
    center_x_mm: float
    center_y_mm: float
    radius_mm: float
    bed_bounds: BedBounds
    clearance_mm: float


@dataclass(frozen=True, slots=True)
class LayerSliceTiming:
    layer_index: int
    z_mm: float
    deposition_time_s: float
    internal_travel_time_s: float
    retraction_time_s: float
    approach_time_s: float
    return_time_s: float
    total_added_time_s: float
    slicer_reported_time_s: float | None = None
    timing_difference_s: float | None = None


@dataclass(frozen=True, slots=True)
class SliceEvaluation:
    gcode_path: Path
    layer_timings: tuple[LayerSliceTiming, ...]
    metadata_source: str
    maximum_metadata_difference_s: float | None
    diagnostics: tuple[str, ...] = ()

    @property
    def added_time_by_layer(self) -> dict[int, float]:
        return {
            item.layer_index: item.total_added_time_s
            for item in self.layer_timings
        }


@dataclass(frozen=True, slots=True)
class CalibrationFailure:
    code: CalibrationFailureCode
    message: str
    layer_index: int | None = None
    related_setting_names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CalibrationIteration:
    number: int
    candidate_signature: str
    maximum_remaining_deficit_s: float
    deficient_layer_count: int
    total_remaining_deficit_s: float
    maximum_profile_change_mm: float
    elapsed_s: float
    evaluation: SliceEvaluation
    final_combined_gcode_path: Path | None = None


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    state: CalibrationState
    mode: CalibrationMode
    iterations: tuple[CalibrationIteration, ...]
    profile: Any | None
    stl_path: Path | None
    gcode_path: Path | None
    placement: TowerPlacement | None
    failures: tuple[CalibrationFailure, ...] = ()
    warnings: tuple[str, ...] = ()
    report_path: Path | None = None
    source_sha256: str | None = None
    output_sha256: str | None = None
    configured_iteration_count: int = 0
    best_iteration_number: int | None = None
    improved_over_analytical: bool = False

    @property
    def success(self) -> bool:
        return self.state is CalibrationState.CONVERGED

    @property
    def best_iteration(self) -> CalibrationIteration | None:
        if self.best_iteration_number is None:
            return None
        return next(
            (
                item
                for item in self.iterations
                if item.number == self.best_iteration_number
            ),
            None,
        )

    @property
    def has_slicer_evaluated_output(self) -> bool:
        output = self.gcode_path if self.mode is CalibrationMode.GCODE else self.stl_path
        return self.best_iteration is not None and output is not None

    @property
    def has_usable_improvement(self) -> bool:
        return self.has_slicer_evaluated_output and (
            self.success or self.improved_over_analytical
        )

    @property
    def minimum_proven_layer_time_s(self) -> float | None:
        if not self.iterations:
            return None
        iteration = self.best_iteration
        if iteration is None:
            return None
        values = [
            timing.total_added_time_s
            for timing in iteration.evaluation.layer_timings
        ]
        return min(values) if values else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "mode": self.mode.value,
            "success": self.success,
            "configured_iteration_count": self.configured_iteration_count,
            "completed_iteration_count": len(self.iterations),
            "best_iteration_number": self.best_iteration_number,
            "improved_over_analytical": self.improved_over_analytical,
            "has_slicer_evaluated_output": self.has_slicer_evaluated_output,
            "has_usable_improvement": self.has_usable_improvement,
            "iterations": [
                {
                    "number": item.number,
                    "candidate_signature": item.candidate_signature,
                    "maximum_remaining_deficit_s": item.maximum_remaining_deficit_s,
                    "deficient_layer_count": item.deficient_layer_count,
                    "total_remaining_deficit_s": item.total_remaining_deficit_s,
                    "maximum_profile_change_mm": item.maximum_profile_change_mm,
                    "elapsed_s": item.elapsed_s,
                    "final_combined_gcode_path": (
                        str(item.final_combined_gcode_path)
                        if item.final_combined_gcode_path else None
                    ),
                    "layer_timings": [
                        {
                            field: getattr(timing, field)
                            for field in timing.__dataclass_fields__
                        }
                        for timing in item.evaluation.layer_timings
                    ],
                    "diagnostics": list(item.evaluation.diagnostics),
                }
                for item in self.iterations
            ],
            "stl_path": str(self.stl_path) if self.stl_path else None,
            "gcode_path": str(self.gcode_path) if self.gcode_path else None,
            "placement": (
                {
                    "center_x_mm": self.placement.center_x_mm,
                    "center_y_mm": self.placement.center_y_mm,
                    "radius_mm": self.placement.radius_mm,
                    "clearance_mm": self.placement.clearance_mm,
                }
                if self.placement else None
            ),
            "failures": [
                {
                    "code": item.code.value,
                    "message": item.message,
                    "layer_index": item.layer_index,
                    "related_setting_names": list(item.related_setting_names),
                }
                for item in self.failures
            ],
            "warnings": list(self.warnings),
            "source_sha256": self.source_sha256,
            "output_sha256": self.output_sha256,
        }


def calibration_config_from_mapping(
    values: Mapping[str, Any],
) -> CalibrationConfig:
    payload = dict(values)
    if "mode" in payload and not isinstance(payload["mode"], CalibrationMode):
        payload["mode"] = CalibrationMode(str(payload["mode"]))
    return CalibrationConfig(**payload)
