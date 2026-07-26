from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

from cooling_tower.models import CalibrationConfig


@dataclass(frozen=True, slots=True)
class ConvergenceAssessment:
    converged: bool
    remaining_deficits_s: Mapping[int, float]
    maximum_remaining_deficit_s: float
    deficient_layer_count: int
    total_remaining_deficit_s: float
    profile_stable: bool


def evaluate_convergence(
    source_layers: Sequence[object],
    added_times_s: Mapping[int, float],
    *,
    target_time_s: float,
    maximum_profile_change_mm: float,
    config: CalibrationConfig,
) -> ConvergenceAssessment:
    """Apply the Phase-16 time and profile convergence criteria."""

    deficits: dict[int, float] = {}
    for layer in source_layers:
        index = int(getattr(layer, "index"))
        source = float(getattr(layer, "total_time_s"))
        added = max(0.0, float(added_times_s.get(index, 0.0)))
        deficits[index] = max(0.0, target_time_s - source - added)
    maximum = max(deficits.values(), default=0.0)
    count = sum(value > config.time_tolerance_s for value in deficits.values())
    total = sum(
        value for value in deficits.values() if value > config.time_tolerance_s
    )
    stable = (
        math.isfinite(maximum_profile_change_mm)
        and maximum_profile_change_mm <= config.profile_change_tolerance_mm
    )
    # A sufficient first candidate is a valid result even though no previous
    # profile exists against which stability could be measured.
    converged = count == 0 and (
        stable or not math.isfinite(maximum_profile_change_mm)
    )
    return ConvergenceAssessment(
        converged=converged,
        remaining_deficits_s=deficits,
        maximum_remaining_deficit_s=maximum,
        deficient_layer_count=count,
        total_remaining_deficit_s=total,
        profile_stable=stable,
    )
