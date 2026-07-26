from __future__ import annotations

import math
from dataclasses import replace
from typing import Mapping, Sequence

from cooling_tower.models import CalibrationConfig
from cooling_tower.tower.profile import (
    LayerRadiusRecord,
    TowerRadiusProfile,
)
from cooling_tower.tower.wall_calculator import calculate_required_outer_radius


def _layer_by_index(layers: Sequence[object]) -> dict[int, object]:
    return {int(getattr(layer, "index")): layer for layer in layers}


def adjust_radius_profile(
    profile: TowerRadiusProfile,
    source_layers: Sequence[object],
    calibrated_added_times_s: Mapping[int, float],
    *,
    target_time_s: float,
    minimum_wall_path_count: int,
    wall_path_width_mm: float,
    config: CalibrationConfig,
) -> tuple[TowerRadiusProfile, float]:
    """Update per-layer path demand without violating capacity ordering.

    A layer with a remaining deficit can only retain or increase its demand.
    Surplus layers may shed a bounded fraction.  The hollow profile builder
    then reapplies radius-first, wall-second, spline and angle invariants.
    """

    source_by_index = _layer_by_index(source_layers)
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
        old_path = max(0.0, item.safety_adjusted_path_mm)

        if required_added > config.time_tolerance_s:
            if observed_added <= 1e-9:
                growth = config.maximum_path_growth_factor
                new_path = max(
                    old_path * growth,
                    old_path + config.minimum_path_growth_mm,
                )
            elif observed_added + config.time_tolerance_s < required_added:
                ratio = min(
                    config.maximum_path_growth_factor,
                    required_added / observed_added,
                )
                new_path = max(
                    old_path * ratio,
                    old_path + config.minimum_path_growth_mm,
                )
            else:
                new_path = old_path
        else:
            new_path = 0.0

        if observed_added > required_added + config.time_tolerance_s and old_path > 0.0:
            ideal = old_path * required_added / observed_added
            reduction = (old_path - ideal) * config.material_reduction_factor
            new_path = min(new_path, max(0.0, old_path - reduction))

        # Never shrink a still-insufficient layer.  This directly prevents
        # the premature necking observed in the 15-second reference case.
        remaining = required_added - observed_added
        if remaining > config.time_tolerance_s:
            new_path = max(old_path, new_path)

        radius = calculate_required_outer_radius(
            new_path,
            minimum_wall_path_count,
            wall_path_width_mm,
        )
        radius = min(
            profile.config.maximum_radius_mm,
            max(profile.config.minimum_radius_mm, radius),
        )
        maximum_radius_change = max(
            maximum_radius_change, abs(radius - item.radius_mm)
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
                    if math.isclose(radius, profile.config.maximum_radius_mm)
                    else "minimum"
                    if math.isclose(radius, profile.config.minimum_radius_mm)
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
