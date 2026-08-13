from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence


class TimingConfidenceState(str, Enum):
    DETAILED = "detailed"
    MOTION_AWARE = "motion_aware"
    NOMINAL_ONLY = "nominal_only"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class TimingEvidence:
    """Explicit statement of which timing influences were observed."""

    acceleration_commands_seen: bool = False
    firmware_limits_seen: bool = False
    junction_model_known: bool = False
    slicer_feature_speeds_known: bool = False
    cooling_slowdown_known: bool = False
    confidence_state: TimingConfidenceState = TimingConfidenceState.UNKNOWN

    @classmethod
    def from_flags(
        cls,
        *,
        acceleration_commands_seen: bool,
        firmware_limits_seen: bool,
        junction_model_known: bool,
        slicer_feature_speeds_known: bool,
        cooling_slowdown_known: bool,
    ) -> "TimingEvidence":
        if (
            acceleration_commands_seen
            and firmware_limits_seen
            and junction_model_known
            and slicer_feature_speeds_known
            and cooling_slowdown_known
        ):
            confidence = TimingConfidenceState.DETAILED
        elif acceleration_commands_seen:
            confidence = TimingConfidenceState.MOTION_AWARE
        else:
            confidence = TimingConfidenceState.NOMINAL_ONLY
        return cls(
            acceleration_commands_seen=acceleration_commands_seen,
            firmware_limits_seen=firmware_limits_seen,
            junction_model_known=junction_model_known,
            slicer_feature_speeds_known=slicer_feature_speeds_known,
            cooling_slowdown_known=cooling_slowdown_known,
            confidence_state=confidence,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "acceleration_commands_seen": self.acceleration_commands_seen,
            "firmware_limits_seen": self.firmware_limits_seen,
            "junction_model_known": self.junction_model_known,
            "slicer_feature_speeds_known": (
                self.slicer_feature_speeds_known
            ),
            "cooling_slowdown_known": self.cooling_slowdown_known,
            "confidence_state": self.confidence_state.value,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TimingEvidence":
        try:
            confidence = TimingConfidenceState(
                str(
                    payload.get(
                        "confidence_state",
                        TimingConfidenceState.UNKNOWN.value,
                    )
                )
            )
        except ValueError:
            confidence = TimingConfidenceState.UNKNOWN
        return cls(
            acceleration_commands_seen=bool(
                payload.get("acceleration_commands_seen", False)
            ),
            firmware_limits_seen=bool(
                payload.get("firmware_limits_seen", False)
            ),
            junction_model_known=bool(
                payload.get("junction_model_known", False)
            ),
            slicer_feature_speeds_known=bool(
                payload.get("slicer_feature_speeds_known", False)
            ),
            cooling_slowdown_known=bool(
                payload.get("cooling_slowdown_known", False)
            ),
            confidence_state=confidence,
        )


@dataclass(frozen=True, slots=True)
class LayerTimingState:
    """Keeps source, sliced and final timing evidence separate."""

    layer_index: int
    source_time_s: float
    target_time_s: float
    required_added_time_s: float
    sliced_tower_time_s: float | None = None
    final_combined_time_s: float | None = None

    def __post_init__(self) -> None:
        numeric_values = (
            self.source_time_s,
            self.target_time_s,
            self.required_added_time_s,
            self.sliced_tower_time_s,
            self.final_combined_time_s,
        )
        for value in numeric_values:
            if value is None:
                continue
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(
                    "Layer timing values must be finite and non-negative."
                )

    @property
    def best_available_combined_time_s(self) -> float:
        if self.final_combined_time_s is not None:
            return self.final_combined_time_s
        if self.sliced_tower_time_s is not None:
            return self.source_time_s + self.sliced_tower_time_s
        return self.source_time_s

    @property
    def best_evidence_kind(self) -> str:
        if self.final_combined_time_s is not None:
            return "final_combined_gcode"
        if self.sliced_tower_time_s is not None:
            return "sliced_tower"
        return "source_gcode"

    @property
    def remaining_deficit_s(self) -> float:
        return max(
            0.0,
            self.target_time_s - self.best_available_combined_time_s,
        )


@dataclass(frozen=True, slots=True)
class TimeCapacityIssue:
    """A forbidden reduction while timing evidence still shows a deficit."""

    layer_index: int
    target_time_s: float
    proven_combined_time_s: float
    previous_capacity_s: float
    current_capacity_s: float
    code: str = "time_capacity_reduced_while_deficit_remains"


def build_layer_timing_states(
    layers: Sequence[object],
    *,
    target_time_s: float,
    safety_factor: float = 1.0,
    sliced_tower_times_s: Mapping[int, float] | None = None,
    final_combined_times_s: Mapping[int, float] | None = None,
) -> tuple[LayerTimingState, ...]:
    if not math.isfinite(target_time_s) or target_time_s < 0.0:
        raise ValueError("Target layer time must be finite and non-negative.")
    if not math.isfinite(safety_factor) or safety_factor < 0.0:
        raise ValueError("Safety factor must be finite and non-negative.")
    sliced = sliced_tower_times_s or {}
    final = final_combined_times_s or {}
    states: list[LayerTimingState] = []
    for layer in layers:
        layer_index = int(getattr(layer, "index"))
        source_time = float(getattr(layer, "total_time_s"))
        states.append(
            LayerTimingState(
                layer_index=layer_index,
                source_time_s=source_time,
                target_time_s=target_time_s,
                required_added_time_s=(
                    max(0.0, target_time_s - source_time)
                    * safety_factor
                ),
                sliced_tower_time_s=sliced.get(layer_index),
                final_combined_time_s=final.get(layer_index),
            )
        )
    return tuple(states)


def validate_time_capacity_transitions(
    states: Sequence[LayerTimingState],
    capacity_by_layer_s: Mapping[int, float],
    *,
    tolerance_s: float = 1e-6,
) -> tuple[TimeCapacityIssue, ...]:
    """Reject capacity shrinkage while best evidence still misses target."""
    if tolerance_s < 0.0 or not math.isfinite(tolerance_s):
        raise ValueError("Timing tolerance must be finite and non-negative.")
    issues: list[TimeCapacityIssue] = []
    previous_capacity: float | None = None
    for state in states:
        current_capacity = capacity_by_layer_s.get(state.layer_index)
        if current_capacity is None:
            previous_capacity = None
            continue
        current_capacity = float(current_capacity)
        if not math.isfinite(current_capacity) or current_capacity < 0.0:
            raise ValueError(
                "Time capacity values must be finite and non-negative."
            )
        if (
            previous_capacity is not None
            and state.remaining_deficit_s > tolerance_s
            and current_capacity < previous_capacity - tolerance_s
        ):
            issues.append(
                TimeCapacityIssue(
                    layer_index=state.layer_index,
                    target_time_s=state.target_time_s,
                    proven_combined_time_s=(
                        state.best_available_combined_time_s
                    ),
                    previous_capacity_s=previous_capacity,
                    current_capacity_s=current_capacity,
                )
            )
        previous_capacity = current_capacity
    return tuple(issues)
