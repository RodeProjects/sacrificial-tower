from __future__ import annotations

import math
from dataclasses import replace
from typing import Mapping, Sequence

from cooling_tower.models import CalibrationConfig
from cooling_tower.tower.profile import (
    LayerRadiusRecord,
    TowerRadiusProfile,
)


def _history_radius_estimate(
    measurements: Sequence[tuple[float, float]],
    required_added_s: float,
    *,
    time_tolerance_s: float,
) -> float | None:
    """Invert trustworthy measured radius/time evidence.

    Interpolation is allowed as soon as two measurements bracket the target.
    Extrapolation requires at least three points whose area-linear model has a
    worst residual below 0.05 seconds. This keeps the shortcut substantially
    stricter than the final acceptance test while retaining the complete
    post-slice validation as the authority.
    """

    by_area: dict[float, tuple[float, float]] = {}
    for radius, observed_s in measurements:
        if (
            math.isfinite(radius)
            and radius > 0.0
            and math.isfinite(observed_s)
            and observed_s >= 0.0
        ):
            area_coordinate = radius * radius
            by_area[area_coordinate] = (area_coordinate, observed_s)
    points = tuple(sorted(by_area.values()))
    if len(points) < 2:
        return None

    brackets: list[tuple[float, tuple[float, float], tuple[float, float]]] = []
    for first_index, first in enumerate(points[:-1]):
        for second in points[first_index + 1:]:
            first_time = first[1]
            second_time = second[1]
            if (first_time - required_added_s) * (
                second_time - required_added_s
            ) <= 0.0 and abs(second_time - first_time) > 1e-9:
                brackets.append((abs(second_time - first_time), first, second))
    if brackets:
        _, first, second = min(brackets, key=lambda item: item[0])
        fraction = (required_added_s - first[1]) / (second[1] - first[1])
        estimated_area = first[0] + fraction * (second[0] - first[0])
        return math.sqrt(max(0.0, estimated_area))

    if len(points) < 3:
        return None
    mean_area = sum(item[0] for item in points) / len(points)
    mean_time = sum(item[1] for item in points) / len(points)
    area_variance = sum((item[0] - mean_area) ** 2 for item in points)
    if area_variance <= 1e-12:
        return None
    slope = sum(
        (area - mean_area) * (observed_s - mean_time)
        for area, observed_s in points
    ) / area_variance
    if slope <= 1e-12:
        return None
    intercept = mean_time - slope * mean_area
    maximum_residual = max(
        abs((intercept + slope * area) - observed_s)
        for area, observed_s in points
    )
    residual_limit = min(0.049, max(0.01, time_tolerance_s * 0.2))
    if maximum_residual > residual_limit:
        return None
    estimated_area = (required_added_s - intercept) / slope
    observed_span = points[-1][0] - points[0][0]
    if (
        estimated_area <= 0.0
        or estimated_area < points[0][0] - observed_span
        or estimated_area > points[-1][0] + observed_span
    ):
        return None
    return math.sqrt(estimated_area)


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
    measurement_history: Mapping[
        int, Sequence[tuple[float, float]]
    ] | None = None,
    combined_layer_times_s: Mapping[int, float] | None = None,
    coupled_radius_scale: float = 1.0,
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

    if not math.isfinite(coupled_radius_scale) or coupled_radius_scale <= 0.0:
        raise ValueError("coupled_radius_scale must be finite and greater than zero")
    joint_growth_guard_s = (
        min(1.0, max(config.time_tolerance_s, target_time_s * 0.05))
        if combined_layer_times_s is not None and coupled_radius_scale > 1.0
        else 0.0
    )
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
        excluded = item.layer_index in profile.config.excluded_layer_indices
        required_added = 0.0 if excluded else max(0.0, target_time_s - source_time)
        control_required_added = max(
            0.0,
            target_time_s + joint_growth_guard_s - source_time,
        )
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
        history_radius = _history_radius_estimate(
            (measurement_history or {}).get(item.layer_index, ()),
            control_required_added,
            time_tolerance_s=config.time_tolerance_s,
        )

        if required_added <= config.time_tolerance_s:
            requested_radius = minimum_radius
        elif observed_added <= 1e-9:
            requested_radius = max(
                old_radius * math.sqrt(config.maximum_path_growth_factor),
                old_radius + config.minimum_path_growth_mm / math.tau,
            )
        elif observed_added + config.time_tolerance_s < control_required_added:
            # A solid cross-section's dominant deposition time grows with its
            # area.  Limit a single iteration to the configured time-growth
            # factor to avoid an unstable jump after an empty measurement.
            radius_factor = math.sqrt(control_required_added / observed_added)
            maximum_radius_factor = math.sqrt(
                config.maximum_path_growth_factor
            )
            proportional_radius = max(
                old_radius,
                min(
                    realized_radius * radius_factor,
                    old_radius * maximum_radius_factor,
                ),
                old_radius + config.minimum_path_growth_mm / math.tau,
            )
            requested_radius = proportional_radius
            if history_radius is not None and history_radius > old_radius:
                requested_radius = min(
                    max(proportional_radius, history_radius),
                    old_radius * maximum_radius_factor,
                )
        elif observed_added > control_required_added + config.time_tolerance_s:
            # Do not turn a transition-provided radius into a new local
            # demand: if the envelope alone widened this layer, its raw request
            # may already be minimal.  Only the request that caused surplus is
            # allowed to shrink.
            ideal_realized_radius = realized_radius * math.sqrt(
                control_required_added / observed_added
            )
            if history_radius is not None and history_radius < realized_radius:
                ideal_realized_radius = history_radius
            reduction_target = min(old_radius, ideal_realized_radius)
            requested_radius = old_radius - (
                old_radius - reduction_target
            ) * config.material_reduction_factor
        else:
            requested_radius = old_radius

        # Correct every layer inside the bounded joint reserve while another
        # layer has a proven deficit. This also covers layers that were long
        # enough in the source-only slice: Bambu can re-plan cooling and make
        # one of them the next complete-plate minimum. Isolated tower slices
        # have no combined times and therefore retain the local controller.
        combined_time = (
            float(combined_layer_times_s[item.layer_index])
            if combined_layer_times_s is not None
            and item.layer_index in combined_layer_times_s
            else None
        )
        if not excluded and combined_time is not None and math.isfinite(combined_time):
            coupled_radius = old_radius * coupled_radius_scale
            if (
                coupled_radius_scale > 1.0
                and combined_time < target_time_s + joint_growth_guard_s
            ):
                requested_radius = max(requested_radius, coupled_radius)
            elif (
                coupled_radius_scale < 1.0
                and combined_time > target_time_s + config.time_tolerance_s
            ):
                requested_radius = min(requested_radius, coupled_radius)

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
                additional_path_mm=new_path,
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
