from __future__ import annotations

import math
from dataclasses import dataclass

from cooling_tower.models import (
    FeasibilityIssue,
    GenerationSettings,
    TowerLayerProfile,
)
from cooling_tower.tower.base_calculator import (
    MAXIMUM_BASE_WIDTH_MM,
    MINIMUM_BASE_WIDTH_MM,
    calculate_phase10_base_outer_radius,
)
from cooling_tower.tower.profile import LayerRadiusRecord, TowerRadiusProfile
from cooling_tower.tower.spline_profile import (
    adaptive_quintic_segment_samples,
    angle_to_radial_slope,
    build_asymmetric_spline_envelope,
    maximum_quintic_segment_slope,
    slope_to_angle_deg,
)
from cooling_tower.tower.wall_calculator import (
    EPSILON,
    WallPathBounds,
    calculate_required_outer_radius,
    calculate_wall_path_bounds,
    calculate_wall_path_length,
    maximum_paths_for_inner_radius,
    minimum_paths_for_required_length,
)


SPLINE_RADIAL_ERROR_MM = 0.03
SPLINE_MAXIMUM_Z_STEP_MM = 1.0
MAXIMUM_EXPANSION_ANGLE_DEG = 70.0


@dataclass(frozen=True, slots=True)
class HollowTowerPoint:
    z_mm: float
    outer_radius_mm: float
    inner_radius_mm: float
    wall_thickness_mm: float
    wall_path_count: int
    required_path_mm: float
    available_path_mm: float
    target_reached: bool
    source: str
    layer_index: int | None
    raw_outer_radius_mm: float = 0.0
    profile_region: str = "layer"


@dataclass(frozen=True, slots=True)
class HollowTowerProfile:
    settings: GenerationSettings
    points: tuple[HollowTowerPoint, ...]
    layers: tuple[TowerLayerProfile, ...]
    warnings: tuple[str, ...]
    wall_bounds: WallPathBounds
    total_height_mm: float
    base_outer_radius_mm: float
    effective_base_height_mm: float
    feasibility_issues: tuple[FeasibilityIssue, ...] = ()
    support_point_count: int = 0
    maximum_spline_error_mm: float = SPLINE_RADIAL_ERROR_MM


@dataclass(frozen=True, slots=True)
class _RawSupport:
    z_mm: float
    raw_outer_radius_mm: float
    required_path_mm: float
    source: str
    layer_index: int | None
    phase2_layer: LayerRadiusRecord | None = None


class ProfileFeasibilityError(ValueError):
    """Raised when no valid hollow profile can be represented at all."""

    def __init__(self, issue: FeasibilityIssue) -> None:
        super().__init__(issue.message)
        self.issues = (issue,)


def validate_hollow_settings(settings: GenerationSettings) -> WallPathBounds:
    if not isinstance(settings.automatic_base_width, bool):
        raise ValueError("Automatic base width must be a boolean value.")

    for name, value in settings.to_dict().items():
        if name == "automatic_base_width":
            continue
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"Generation setting {name} must be finite.")

    if settings.minimum_outer_radius_mm <= 0.0:
        raise ValueError("Minimum outer radius must be greater than zero.")
    if settings.maximum_outer_radius_mm < settings.minimum_outer_radius_mm:
        raise ValueError(
            "Maximum outer radius must be greater than or equal to minimum outer radius."
        )
    if settings.minimum_inner_radius_mm <= 0.0:
        raise ValueError("Minimum inner radius must be greater than zero.")
    if settings.base_height_mm < 0.0:
        raise ValueError("Base height must not be negative.")
    if not settings.automatic_base_width:
        if settings.manual_base_width_mm < MINIMUM_BASE_WIDTH_MM:
            raise ValueError(
                f"Manual base width must be at least {MINIMUM_BASE_WIDTH_MM:g} mm."
            )
        if settings.manual_base_width_mm > MAXIMUM_BASE_WIDTH_MM:
            raise ValueError(
                f"Manual base width must be at most {MAXIMUM_BASE_WIDTH_MM:g} mm."
            )
    if not (
        0.0
        < settings.maximum_expansion_angle_deg
        <= MAXIMUM_EXPANSION_ANGLE_DEG
    ):
        raise ValueError(
            "Maximum expansion angle must be greater than zero and at most "
            f"{MAXIMUM_EXPANSION_ANGLE_DEG:g} degrees."
        )
    angle_to_radial_slope(settings.maximum_expansion_angle_deg)
    angle_to_radial_slope(settings.maximum_contraction_angle_deg)
    if settings.maximum_wall_change_per_mm_z <= 0.0:
        raise ValueError("Maximum wall change must be greater than zero.")

    bounds = calculate_wall_path_bounds(
        settings.minimum_wall_thickness_mm,
        settings.maximum_wall_thickness_mm,
        settings.wall_path_width_mm,
    )
    minimum_feasible_outer = (
        settings.minimum_inner_radius_mm
        + bounds.effective_minimum_thickness_mm
    )
    if settings.maximum_outer_radius_mm + EPSILON < minimum_feasible_outer:
        raise ValueError(
            "Maximum outer radius cannot contain the minimum wall and minimum inner radius."
        )
    return bounds


def build_hollow_tower_profile(
    phase2_profile: TowerRadiusProfile,
    settings: GenerationSettings,
    *,
    tower_end_z_mm: float | None = None,
    object_height_mm: float | None = None,
) -> HollowTowerProfile:
    """Build the Phase-10 hollow profile with asymmetric C2 splines.

    Regular regions consume available layer time in this order: outer radius
    first, then wall thickness.  The stand base is the documented exception:
    its outer width is fixed by the complete G-code object height or the
    manual setting and any additional demand is handled by the wall.
    """
    bounds = validate_hollow_settings(settings)
    if not phase2_profile.layers:
        raise ValueError("A hollow profile requires at least one layer.")

    last_layer_z = phase2_profile.layers[-1].z_mm
    total_height = last_layer_z if tower_end_z_mm is None else tower_end_z_mm
    if not math.isfinite(total_height) or total_height <= 0.0:
        raise ValueError("Tower end height must be finite and greater than zero.")
    if total_height < last_layer_z - EPSILON:
        raise ValueError("Tower end height cannot be below the last included layer.")
    total_height = last_layer_z

    warnings = _initial_warnings(settings, bounds)
    issues: list[FeasibilityIssue] = []
    minimum_outer = max(
        settings.minimum_outer_radius_mm,
        settings.minimum_inner_radius_mm
        + bounds.effective_minimum_thickness_mm,
    )
    base_reference_height = (
        total_height if object_height_mm is None else object_height_mm
    )
    base_outer = calculate_phase10_base_outer_radius(
        object_height_mm=base_reference_height,
        automatic_base_width=settings.automatic_base_width,
        manual_base_width_mm=settings.manual_base_width_mm,
    )
    minimum_hollow_outer = (
        settings.minimum_inner_radius_mm
        + bounds.effective_minimum_thickness_mm
    )
    if base_outer + EPSILON < minimum_hollow_outer:
        raise ProfileFeasibilityError(
            FeasibilityIssue(
                code="BASE_WIDTH_TOO_SMALL",
                message=(
                    "Die Standfußbreite ist zu klein für Mindest-Innenradius "
                    "und Mindestwandstärke."
                ),
                affected_z_mm=0.0,
                related_setting_names=(
                    "automatic_base_width",
                    "manual_base_width_mm",
                    "minimum_inner_radius_mm",
                    "minimum_wall_thickness_mm",
                ),
                required_value=2.0 * minimum_hollow_outer,
                achievable_value=2.0 * base_outer,
            )
        )
    effective_base_height = min(settings.base_height_mm, total_height)

    supports = _build_raw_supports(
        phase2_profile=phase2_profile,
        total_height_mm=total_height,
        effective_base_height_mm=effective_base_height,
        base_outer_radius_mm=base_outer,
        minimum_outer_radius_mm=minimum_outer,
        bounds=bounds,
        settings=settings,
    )
    anchor_index = _base_anchor_index(supports, effective_base_height)
    expansion_slope = angle_to_radial_slope(
        settings.maximum_expansion_angle_deg
    )
    contraction_slope = angle_to_radial_slope(
        settings.maximum_contraction_angle_deg
    )

    outer_radii, angle_unreachable = _build_outer_envelope(
        supports=supports,
        base_anchor_index=anchor_index,
        base_outer_radius_mm=base_outer,
        maximum_expansion_slope=expansion_slope,
        maximum_contraction_slope=contraction_slope,
    )
    _append_angle_issues(
        issues=issues,
        supports=supports,
        unreachable_indices=angle_unreachable,
        outer_radii=outer_radii,
        base_anchor_index=anchor_index,
        settings=settings,
    )

    raw_wall_thicknesses = _required_wall_thicknesses(
        supports=supports,
        outer_radii=outer_radii,
        bounds=bounds,
        settings=settings,
        effective_base_height_mm=effective_base_height,
    )
    wall_envelope = build_asymmetric_spline_envelope(
        [support.z_mm for support in supports],
        raw_wall_thicknesses,
        maximum_increase_per_mm_z=settings.maximum_wall_change_per_mm_z,
        maximum_decrease_per_mm_z=settings.maximum_wall_change_per_mm_z,
    ).values

    # Once wall growth is needed, regular profile regions remain at their
    # maximum outer radius until the wall has smoothly returned to minimum.
    # Include the immediately adjacent supports as staging points.  Without
    # them, independently interpolating radius and wall between a minimum-wall
    # support and a thick-wall support would temporarily shrink/grow both at
    # once.  That makes the inner contour move while the outer contour has not
    # yet reached its maximum.  The staging points enforce the intended order
    # for every adaptively sampled mesh ring as well as for source layers:
    # outer and inner contour move together first, wall thickness second.
    ordered_outer_requirements = list(
        support.raw_outer_radius_mm for support in supports
    )
    wall_growth_indices = {
        index
        for index in range(anchor_index + 1, len(supports))
        if wall_envelope[index]
        > bounds.effective_minimum_thickness_mm + EPSILON
    }
    staged_maximum_indices = {
        neighbor
        for index in wall_growth_indices
        for neighbor in (index - 1, index, index + 1)
        if anchor_index < neighbor < len(supports)
    }
    for index in staged_maximum_indices:
        ordered_outer_requirements[index] = max(
            ordered_outer_requirements[index],
            settings.maximum_outer_radius_mm,
        )
    ordered_supports = tuple(
        _RawSupport(
            z_mm=support.z_mm,
            raw_outer_radius_mm=ordered_outer_requirements[index],
            required_path_mm=support.required_path_mm,
            source=support.source,
            layer_index=support.layer_index,
            phase2_layer=support.phase2_layer,
        )
        for index, support in enumerate(supports)
    )
    outer_radii, ordered_unreachable = _build_outer_envelope(
        supports=ordered_supports,
        base_anchor_index=anchor_index,
        base_outer_radius_mm=base_outer,
        maximum_expansion_slope=expansion_slope,
        maximum_contraction_slope=contraction_slope,
    )
    _append_angle_issues(
        issues=issues,
        supports=ordered_supports,
        unreachable_indices=ordered_unreachable,
        outer_radii=outer_radii,
        base_anchor_index=anchor_index,
        settings=settings,
    )

    raw_wall_thicknesses = _required_wall_thicknesses(
        supports=supports,
        outer_radii=outer_radii,
        bounds=bounds,
        settings=settings,
        effective_base_height_mm=effective_base_height,
    )
    requested_wall_envelope = build_asymmetric_spline_envelope(
        [support.z_mm for support in supports],
        raw_wall_thicknesses,
        maximum_increase_per_mm_z=settings.maximum_wall_change_per_mm_z,
        maximum_decrease_per_mm_z=settings.maximum_wall_change_per_mm_z,
    ).values
    wall_thicknesses = _apply_wall_capacity(
        supports=supports,
        outer_radii=outer_radii,
        requested_wall_thicknesses=requested_wall_envelope,
        bounds=bounds,
        settings=settings,
        issues=issues,
    )

    support_points, layer_results = _build_support_results(
        supports=supports,
        outer_radii=outer_radii,
        wall_thicknesses=wall_thicknesses,
        bounds=bounds,
        settings=settings,
        issues=issues,
        effective_base_height_mm=effective_base_height,
    )
    points = _sample_support_splines(
        support_points=support_points,
        settings=settings,
        bounds=bounds,
    )

    unique_issues = _unique_issues(issues)
    warnings.extend(_warnings_for_issues(unique_issues))
    return HollowTowerProfile(
        settings=settings,
        points=points,
        layers=layer_results,
        warnings=tuple(dict.fromkeys(warnings)),
        wall_bounds=bounds,
        total_height_mm=total_height,
        base_outer_radius_mm=base_outer,
        effective_base_height_mm=effective_base_height,
        feasibility_issues=unique_issues,
        support_point_count=len(support_points),
    )


def _initial_warnings(
    settings: GenerationSettings,
    bounds: WallPathBounds,
) -> list[str]:
    warnings: list[str] = []
    if settings.minimum_wall_thickness_mm < settings.wall_path_width_mm:
        warnings.append(
            "Eingestellte Mindestwandstärke ist kleiner als eine Bahnbreite."
        )
    if (
        abs(
            bounds.effective_minimum_thickness_mm
            - settings.minimum_wall_thickness_mm
        )
        > EPSILON
    ):
        warnings.append(
            "Wandstärke wurde auf eine vollständige Anzahl von Bahnen aufgerundet."
        )
    return warnings


def _build_raw_supports(
    *,
    phase2_profile: TowerRadiusProfile,
    total_height_mm: float,
    effective_base_height_mm: float,
    base_outer_radius_mm: float,
    minimum_outer_radius_mm: float,
    bounds: WallPathBounds,
    settings: GenerationSettings,
) -> tuple[_RawSupport, ...]:
    supports = [
        _RawSupport(
            z_mm=0.0,
            raw_outer_radius_mm=base_outer_radius_mm,
            required_path_mm=0.0,
            source="base_bottom",
            layer_index=None,
        )
    ]
    for layer in phase2_profile.layers:
        solved = calculate_required_outer_radius(
            layer.safety_adjusted_path_mm,
            bounds.minimum_path_count,
            settings.wall_path_width_mm,
        )
        regular_outer = min(
            settings.maximum_outer_radius_mm,
            max(minimum_outer_radius_mm, solved),
        )
        in_base = layer.z_mm <= effective_base_height_mm + EPSILON
        supports.append(
            _RawSupport(
                z_mm=layer.z_mm,
                raw_outer_radius_mm=(
                    base_outer_radius_mm if in_base else regular_outer
                ),
                required_path_mm=layer.safety_adjusted_path_mm,
                source="layer",
                layer_index=layer.layer_index,
                phase2_layer=layer,
            )
        )

    if (
        effective_base_height_mm < total_height_mm - EPSILON
        and not any(
            abs(support.z_mm - effective_base_height_mm) <= EPSILON
            for support in supports
        )
    ):
        supports.append(
            _RawSupport(
                z_mm=effective_base_height_mm,
                raw_outer_radius_mm=base_outer_radius_mm,
                required_path_mm=0.0,
                source="base_transition",
                layer_index=None,
            )
        )

    supports.sort(key=lambda support: support.z_mm)
    for previous, current in zip(supports, supports[1:]):
        if current.z_mm <= previous.z_mm + EPSILON:
            raise ValueError("Hollow profile support heights must be strictly increasing.")
    return tuple(supports)


def _base_anchor_index(
    supports: tuple[_RawSupport, ...],
    effective_base_height_mm: float,
) -> int:
    return max(
        index
        for index, support in enumerate(supports)
        if support.z_mm <= effective_base_height_mm + EPSILON
    )


def _build_outer_envelope(
    *,
    supports: tuple[_RawSupport, ...],
    base_anchor_index: int,
    base_outer_radius_mm: float,
    maximum_expansion_slope: float,
    maximum_contraction_slope: float,
) -> tuple[tuple[float, ...], tuple[int, ...]]:
    prefix = tuple(base_outer_radius_mm for _ in range(base_anchor_index))
    tail = supports[base_anchor_index:]
    result = build_asymmetric_spline_envelope(
        [support.z_mm for support in tail],
        [support.raw_outer_radius_mm for support in tail],
        maximum_increase_per_mm_z=maximum_expansion_slope,
        maximum_decrease_per_mm_z=maximum_contraction_slope,
        fixed_start_value=base_outer_radius_mm,
    )
    return (
        prefix + result.values,
        tuple(base_anchor_index + index for index in result.unreachable_positions),
    )


def _required_wall_thicknesses(
    *,
    supports: tuple[_RawSupport, ...],
    outer_radii: tuple[float, ...],
    bounds: WallPathBounds,
    settings: GenerationSettings,
    effective_base_height_mm: float,
) -> tuple[float, ...]:
    values: list[float] = []
    for support, outer in zip(supports, outer_radii, strict=True):
        if (
            support.z_mm > effective_base_height_mm + EPSILON
            and outer < settings.maximum_outer_radius_mm - EPSILON
        ):
            values.append(bounds.effective_minimum_thickness_mm)
            continue
        capacity = min(
            bounds.maximum_path_count,
            maximum_paths_for_inner_radius(
                outer,
                settings.minimum_inner_radius_mm,
                settings.wall_path_width_mm,
            ),
        )
        count, _ = minimum_paths_for_required_length(
            outer,
            support.required_path_mm,
            bounds.minimum_path_count,
            max(bounds.minimum_path_count, capacity),
            settings.wall_path_width_mm,
        )
        values.append(count * settings.wall_path_width_mm)
    return tuple(values)


def _apply_wall_capacity(
    *,
    supports: tuple[_RawSupport, ...],
    outer_radii: tuple[float, ...],
    requested_wall_thicknesses: tuple[float, ...],
    bounds: WallPathBounds,
    settings: GenerationSettings,
    issues: list[FeasibilityIssue],
) -> tuple[float, ...]:
    actual: list[float] = []
    for support, outer, requested in zip(
        supports, outer_radii, requested_wall_thicknesses, strict=True
    ):
        inner_capacity = outer - settings.minimum_inner_radius_mm
        maximum = min(bounds.effective_maximum_thickness_mm, inner_capacity)
        thickness = min(requested, maximum)
        thickness = max(bounds.effective_minimum_thickness_mm, thickness)
        actual.append(thickness)
        if requested > maximum + EPSILON:
            issues.append(
                FeasibilityIssue(
                    code="MINIMUM_INNER_RADIUS_REACHED",
                    message=(
                        "Die geglättete Wandstärke würde den eingestellten "
                        "Mindest-Innenradius unterschreiten."
                    ),
                    affected_layer_index=support.layer_index,
                    affected_z_mm=support.z_mm,
                    related_setting_names=(
                        "minimum_inner_radius_mm",
                        "maximum_wall_change_per_mm_z",
                    ),
                    required_value=requested,
                    achievable_value=maximum,
                )
            )
    return tuple(actual)


def _build_support_results(
    *,
    supports: tuple[_RawSupport, ...],
    outer_radii: tuple[float, ...],
    wall_thicknesses: tuple[float, ...],
    bounds: WallPathBounds,
    settings: GenerationSettings,
    issues: list[FeasibilityIssue],
    effective_base_height_mm: float,
) -> tuple[tuple[HollowTowerPoint, ...], tuple[TowerLayerProfile, ...]]:
    points: list[HollowTowerPoint] = []
    layer_results: list[TowerLayerProfile] = []
    z_values = tuple(support.z_mm for support in supports)

    for index, (support, outer, wall) in enumerate(
        zip(supports, outer_radii, wall_thicknesses, strict=True)
    ):
        capacity = min(
            bounds.maximum_path_count,
            maximum_paths_for_inner_radius(
                outer,
                settings.minimum_inner_radius_mm,
                settings.wall_path_width_mm,
            ),
        )
        fitted_count = math.floor(
            (wall + EPSILON) / settings.wall_path_width_mm
        )
        count = max(bounds.minimum_path_count, min(capacity, fitted_count))
        effective_wall = max(wall, count * settings.wall_path_width_mm)
        effective_wall = min(
            effective_wall,
            outer - settings.minimum_inner_radius_mm,
        )
        inner = outer - effective_wall
        available = calculate_wall_path_length(
            outer, count, settings.wall_path_width_mm
        )
        reached = available + EPSILON >= support.required_path_mm
        expansion_angle, contraction_angle = _support_angles(
            z_values, outer_radii, index
        )
        region = _profile_region(
            support=support,
            index=index,
            outer_radii=outer_radii,
            wall_thickness_mm=effective_wall,
            minimum_wall_thickness_mm=bounds.effective_minimum_thickness_mm,
            effective_base_height_mm=effective_base_height_mm,
        )
        point = HollowTowerPoint(
            z_mm=support.z_mm,
            outer_radius_mm=outer,
            inner_radius_mm=inner,
            wall_thickness_mm=effective_wall,
            wall_path_count=count,
            required_path_mm=support.required_path_mm,
            available_path_mm=available,
            target_reached=reached,
            source=support.source,
            layer_index=support.layer_index,
            raw_outer_radius_mm=support.raw_outer_radius_mm,
            profile_region=region,
        )
        points.append(point)

        if support.layer_index is not None:
            phase2 = support.phase2_layer
            if phase2 is None:
                raise RuntimeError("Layer support lost its Phase-2 source data.")
            estimated_added = (
                None
                if phase2.seconds_per_deposition_mm is None
                else available * phase2.seconds_per_deposition_mm
            )
            layer_results.append(
                TowerLayerProfile(
                    index=support.layer_index,
                    z=support.z_mm,
                    required_path_mm=support.required_path_mm,
                    available_path_mm=available,
                    outer_radius_mm=outer,
                    inner_radius_mm=inner,
                    wall_thickness_mm=effective_wall,
                    wall_path_count=count,
                    target_reached=reached,
                    layer_time_s=phase2.layer_time_s,
                    time_deficit_s=phase2.time_deficit_s,
                    raw_outer_radius_mm=support.raw_outer_radius_mm,
                    expansion_angle_deg=expansion_angle,
                    contraction_angle_deg=contraction_angle,
                    estimated_added_time_s=estimated_added,
                    profile_region=region,
                )
            )
            if not reached:
                _append_capacity_issues(
                    issues=issues,
                    support=support,
                    outer_radius_mm=outer,
                    wall_path_count=count,
                    available_path_mm=available,
                    bounds=bounds,
                    settings=settings,
                )
    return tuple(points), tuple(layer_results)


def _sample_support_splines(
    *,
    support_points: tuple[HollowTowerPoint, ...],
    settings: GenerationSettings,
    bounds: WallPathBounds,
) -> tuple[HollowTowerPoint, ...]:
    sampled: list[HollowTowerPoint] = [support_points[0]]
    for start, end in zip(support_points, support_points[1:]):
        samples = adaptive_quintic_segment_samples(
            start_z_mm=start.z_mm,
            end_z_mm=end.z_mm,
            start_outer_radius_mm=start.outer_radius_mm,
            end_outer_radius_mm=end.outer_radius_mm,
            start_wall_thickness_mm=start.wall_thickness_mm,
            end_wall_thickness_mm=end.wall_thickness_mm,
            maximum_radial_error_mm=SPLINE_RADIAL_ERROR_MM,
            maximum_z_step_mm=SPLINE_MAXIMUM_Z_STEP_MM,
        )
        for sample in samples:
            if sample.t >= 1.0 - EPSILON:
                sampled.append(end)
                continue
            capacity = min(
                bounds.maximum_path_count,
                maximum_paths_for_inner_radius(
                    sample.outer_radius_mm,
                    settings.minimum_inner_radius_mm,
                    settings.wall_path_width_mm,
                ),
            )
            count = max(
                bounds.minimum_path_count,
                min(
                    capacity,
                    math.floor(
                        (sample.wall_thickness_mm + EPSILON)
                        / settings.wall_path_width_mm
                    ),
                ),
            )
            available = calculate_wall_path_length(
                sample.outer_radius_mm,
                count,
                settings.wall_path_width_mm,
            )
            sampled.append(
                HollowTowerPoint(
                    z_mm=sample.z_mm,
                    outer_radius_mm=sample.outer_radius_mm,
                    inner_radius_mm=(
                        sample.outer_radius_mm - sample.wall_thickness_mm
                    ),
                    wall_thickness_mm=sample.wall_thickness_mm,
                    wall_path_count=count,
                    required_path_mm=0.0,
                    available_path_mm=available,
                    target_reached=True,
                    source="spline_transition",
                    layer_index=None,
                    raw_outer_radius_mm=sample.outer_radius_mm,
                    profile_region=_transition_region(start, end),
                )
            )
    return tuple(sampled)


def _append_angle_issues(
    *,
    issues: list[FeasibilityIssue],
    supports: tuple[_RawSupport, ...],
    unreachable_indices: tuple[int, ...],
    outer_radii: tuple[float, ...],
    base_anchor_index: int,
    settings: GenerationSettings,
) -> None:
    for index in unreachable_indices:
        support = supports[index]
        required_angle = _required_expansion_angle(
            supports=supports,
            index=index,
            outer_radii=outer_radii,
            base_anchor_index=base_anchor_index,
        )
        issues.append(
            FeasibilityIssue(
                code="EXPANSION_ANGLE_TOO_SMALL",
                message=(
                    "Der eingestellte Zunahmewinkel ist zu flach, um den "
                    "benötigten Außenradius rechtzeitig zu erreichen."
                ),
                affected_layer_index=support.layer_index,
                affected_z_mm=support.z_mm,
                related_setting_names=(
                    "maximum_expansion_angle_deg",
                    "automatic_base_width",
                    "manual_base_width_mm",
                ),
                required_value=required_angle,
                achievable_value=settings.maximum_expansion_angle_deg,
            )
        )
        if (
            not settings.automatic_base_width
            and support.raw_outer_radius_mm > outer_radii[base_anchor_index] + EPSILON
        ):
            issues.append(
                FeasibilityIssue(
                    code="BASE_WIDTH_TOO_SMALL",
                    message=(
                        "Die manuelle Standfußbreite bietet mit dem "
                        "eingestellten Aufweitungswinkel nicht genug "
                        "Übergangshöhe."
                    ),
                    affected_layer_index=support.layer_index,
                    affected_z_mm=support.z_mm,
                    related_setting_names=(
                        "manual_base_width_mm",
                        "maximum_expansion_angle_deg",
                    ),
                    required_value=2.0 * support.raw_outer_radius_mm,
                    achievable_value=2.0 * outer_radii[base_anchor_index],
                )
            )


def _required_expansion_angle(
    *,
    supports: tuple[_RawSupport, ...],
    index: int,
    outer_radii: tuple[float, ...],
    base_anchor_index: int,
) -> float:
    previous = max(base_anchor_index, index - 1)
    delta_z = supports[index].z_mm - supports[previous].z_mm
    if delta_z <= EPSILON:
        return 90.0
    delta_radius = max(
        0.0,
        supports[index].raw_outer_radius_mm - outer_radii[previous],
    )
    return slope_to_angle_deg(1.875 * delta_radius / delta_z)


def _append_capacity_issues(
    *,
    issues: list[FeasibilityIssue],
    support: _RawSupport,
    outer_radius_mm: float,
    wall_path_count: int,
    available_path_mm: float,
    bounds: WallPathBounds,
    settings: GenerationSettings,
) -> None:
    common = dict(
        affected_layer_index=support.layer_index,
        affected_z_mm=support.z_mm,
        required_value=support.required_path_mm,
        achievable_value=available_path_mm,
    )
    if outer_radius_mm >= settings.maximum_outer_radius_mm - EPSILON:
        issues.append(
            FeasibilityIssue(
                code="MAXIMUM_OUTER_RADIUS_REACHED",
                message=(
                    "Die benötigte Layertime ist trotz maximaler Außenbreite "
                    "noch nicht erreichbar."
                ),
                related_setting_names=("maximum_outer_radius_mm",),
                **common,
            )
        )
    if wall_path_count >= bounds.maximum_path_count:
        issues.append(
            FeasibilityIssue(
                code="MAXIMUM_WALL_THICKNESS_REACHED",
                message=(
                    "Die benötigte Layertime ist trotz maximaler Wandstärke "
                    "noch nicht erreichbar."
                ),
                related_setting_names=("maximum_wall_thickness_mm",),
                **common,
            )
        )
    if wall_path_count >= maximum_paths_for_inner_radius(
        outer_radius_mm,
        settings.minimum_inner_radius_mm,
        settings.wall_path_width_mm,
    ):
        issues.append(
            FeasibilityIssue(
                code="MINIMUM_INNER_RADIUS_REACHED",
                message=(
                    "Mehr Wandbahnen würden den Mindest-Innenradius "
                    "unterschreiten."
                ),
                related_setting_names=("minimum_inner_radius_mm",),
                **common,
            )
        )


def _support_angles(
    z_values: tuple[float, ...],
    outer_values: tuple[float, ...],
    index: int,
) -> tuple[float, float]:
    expansion = 0.0
    contraction = 0.0
    for left_index, right_index in (
        (index - 1, index),
        (index, index + 1),
    ):
        if left_index < 0 or right_index >= len(outer_values):
            continue
        start = outer_values[left_index]
        end = outer_values[right_index]
        slope = maximum_quintic_segment_slope(
            start,
            end,
            z_values[right_index] - z_values[left_index],
        )
        angle = slope_to_angle_deg(slope)
        if end > start + EPSILON:
            expansion = max(expansion, angle)
        elif start > end + EPSILON:
            contraction = max(contraction, angle)
    return expansion, contraction


def _profile_region(
    *,
    support: _RawSupport,
    index: int,
    outer_radii: tuple[float, ...],
    wall_thickness_mm: float,
    minimum_wall_thickness_mm: float,
    effective_base_height_mm: float,
) -> str:
    if support.z_mm <= effective_base_height_mm + EPSILON:
        return "base"
    if wall_thickness_mm > minimum_wall_thickness_mm + EPSILON:
        return "wall_thickening"
    previous = outer_radii[index - 1] if index else outer_radii[index]
    following = (
        outer_radii[index + 1]
        if index + 1 < len(outer_radii)
        else outer_radii[index]
    )
    if outer_radii[index] > previous + EPSILON or following > outer_radii[index] + EPSILON:
        return "expansion"
    if outer_radii[index] < previous - EPSILON or following < outer_radii[index] - EPSILON:
        return "contraction"
    if (
        support.required_path_mm > EPSILON
        and outer_radii[index] >= previous - EPSILON
        and outer_radii[index] >= following - EPSILON
    ):
        return "time_peak"
    return "minimum_trunk"


def _transition_region(
    start: HollowTowerPoint,
    end: HollowTowerPoint,
) -> str:
    if end.wall_thickness_mm > start.wall_thickness_mm + EPSILON:
        return "wall_expansion"
    if end.wall_thickness_mm < start.wall_thickness_mm - EPSILON:
        return "wall_contraction"
    if end.outer_radius_mm > start.outer_radius_mm + EPSILON:
        return "expansion"
    if end.outer_radius_mm < start.outer_radius_mm - EPSILON:
        return "contraction"
    return start.profile_region


def _unique_issues(
    issues: list[FeasibilityIssue],
) -> tuple[FeasibilityIssue, ...]:
    unique: dict[tuple[str, int | None, float | None], FeasibilityIssue] = {}
    for issue in issues:
        key = (issue.code, issue.affected_layer_index, issue.affected_z_mm)
        unique.setdefault(key, issue)
    return tuple(unique.values())


def _warnings_for_issues(
    issues: tuple[FeasibilityIssue, ...],
) -> tuple[str, ...]:
    counts: dict[str, int] = {}
    messages: dict[str, str] = {}
    for issue in issues:
        counts[issue.code] = counts.get(issue.code, 0) + 1
        messages[issue.code] = issue.message
    return tuple(
        f"{message} ({counts[code]} Profilpunkt(e))"
        for code, message in messages.items()
    )
