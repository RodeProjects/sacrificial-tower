from __future__ import annotations

import math
from dataclasses import replace
from typing import Mapping, Sequence

from cooling_tower.models import CalibrationConfig
from cooling_tower.tower.profile import (
    LayerRadiusRecord,
    TowerRadiusProfile,
)


def _layer_by_index(layers: Sequence[object]) -> dict[int, object]:
    return {int(getattr(layer, "index")): layer for layer in layers}


def adjust_radius_profile(
    profile: TowerRadiusProfile,
    source_layers: Sequence[object],
    calibrated_added_times_s: Mapping[int, float],
    *,
    target_time_s: float,
    realized_outer_radii_mm: Mapping[int, float] | None = None,
    minimum_wall_path_count: int | None = None,
    wall_path_width_mm: float | None = None,
    config: CalibrationConfig,
) -> tuple[TowerRadiusProfile, float]:
    """Update raw radius demand from the geometry that was actually sliced.

    Spline and angle constraints can make the realized radius substantially
    larger than the raw per-layer request.  The measured time must therefore
    be inverted against that realized solid cross-section, not against the
    old circumference request.  Since 100-percent infill is dominated by
    cross-sectional area, radius changes use the square root of the measured
    time ratio.  The solid profile builder subsequently reapplies all diameter
    and transition invariants.
    """

    source_by_index = _layer_by_index(source_layers)
    realized_by_index = realized_outer_radii_mm or {}
    adjusted: list[LayerRadiusRecord] = []
    maximum_radius_change = 0.0
    for item in profile.layers:
        source = source_by_index.get(item.layer_index)
        if source is None:
            adjusted.append(item)
            continue
        source_time = float(getattr(source, "total_time_s"))
        observed_added = max(
            0.0, float(calibrated_added_times_s.get(item.layer_index, 0.0))
        )
        required_added = max(0.0, target_time_s - source_time)
        minimum_radius = profile.config.minimum_radius_mm
        maximum_radius = profile.config.maximum_radius_mm
        old_radius = min(
            maximum_radius,
            max(minimum_radius, float(item.radius_mm)),
        )
        realized_radius = min(
            maximum_radius,
            max(
                minimum_radius,
                float(realized_by_index.get(item.layer_index, old_radius)),
            ),
        )

        if required_added <= config.time_tolerance_s:
            requested_radius = minimum_radius
        elif observed_added <= 1e-9:
            requested_radius = max(
                old_radius * math.sqrt(config.maximum_path_growth_factor),
                old_radius + config.minimum_path_growth_mm / math.tau,
            )
        elif observed_added + config.time_tolerance_s < required_added:
            # A solid cross-section's dominant deposition time grows with its
            # area.  Limit a single iteration to the configured time-growth
            # factor to avoid an unstable jump after an empty measurement.
            radius_factor = math.sqrt(required_added / observed_added)
            maximum_radius_factor = math.sqrt(
                config.maximum_path_growth_factor
            )
            requested_radius = max(
                old_radius,
                min(
                    realized_radius * radius_factor,
                    old_radius * maximum_radius_factor,
                ),
                old_radius + config.minimum_path_growth_mm / math.tau,
            )
        elif observed_added > required_added + config.time_tolerance_s:
            # Do not turn a transition-provided radius into a new local
            # demand: if the envelope alone widened this layer, its raw request
            # may already be minimal.  Only the request that caused surplus is
            # allowed to shrink.
            ideal_realized_radius = realized_radius * math.sqrt(
                required_added / observed_added
            )
            reduction_target = min(old_radius, ideal_realized_radius)
            requested_radius = old_radius - (
                old_radius - reduction_target
            ) * config.material_reduction_factor
        else:
            requested_radius = old_radius

        radius = min(
            maximum_radius,
            max(minimum_radius, requested_radius),
        )
        if required_added > config.time_tolerance_s:
            new_path = math.tau * radius
        else:
            new_path = 0.0

        maximum_radius_change = max(
            maximum_radius_change, abs(radius - old_radius)
        )
        factor = item.seconds_per_deposition_mm
        estimated_added = new_path * factor if factor is not None else None
        adjusted.append(
            replace(
                item,
                time_deficit_s=required_added,
                additional_path_mm=(
                    new_path / profile.config.safety_factor
                    if profile.config.safety_factor > 0.0 else new_path
                ),
                safety_adjusted_path_mm=new_path,
                calculated_radius_mm=radius,
                radius_mm=radius,
                radius_limit=(
                    "maximum"
                    if math.isclose(radius, maximum_radius)
                    else "minimum"
                    if math.isclose(radius, minimum_radius)
                    else "none"
                ),
                estimated_added_time_s=estimated_added,
                estimated_combined_layer_time_s=(
                    source_time + estimated_added
                    if estimated_added is not None else None
                ),
            )
        )
    return (
        TowerRadiusProfile(
            config=profile.config,
            global_seconds_per_deposition_mm=(
                profile.global_seconds_per_deposition_mm
            ),
            layers=tuple(adjusted),
        ),
        maximum_radius_change,
    )
