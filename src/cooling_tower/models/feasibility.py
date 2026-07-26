from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FeasibilityIssue:
    """Structured explanation of a profile constraint that was not met."""

    code: str
    message: str
    affected_layer_index: int | None = None
    affected_z_mm: float | None = None
    related_setting_names: tuple[str, ...] = ()
    required_value: float | None = None
    achievable_value: float | None = None


@dataclass(frozen=True, slots=True)
class ProfileFeasibilityAssessment:
    """Output-free result of applying all geometry limits to analyzed layers."""

    tower_required: bool
    feasible: bool
    issues: tuple[FeasibilityIssue, ...] = ()
    checked_layer_count: int = 0
    support_point_count: int = 0
    mesh_ring_count: int = 0
    estimated_minimum_combined_layer_time_s: float | None = None
    estimated_maximum_shortfall_s: float | None = None
