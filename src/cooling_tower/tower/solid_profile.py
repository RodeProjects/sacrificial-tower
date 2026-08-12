from __future__ import annotations

import math
from dataclasses import dataclass

from cooling_tower.models import (
    FeasibilityIssue,
    GenerationSettings,
    TowerLayerProfile,
)
from cooling_tower.tower.base_calculator import (
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


EPSILON = 1e-9
SPLINE_RADIAL_ERROR_MM = 0.03
SPLINE_MAXIMUM_Z_STEP_MM = 1.0
MAXIMUM_EXPANSION_ANGLE_DEG = 70.0


@dataclass(frozen=True, slots=True)
class SolidTowerPoint:
    z_mm: float
    outer_radius_mm: float
    source: str
    layer_index: int | None
    raw_outer_radius_mm: float = 0.0
    profile_region: str = "layer"

    @property
    def radius_mm(self) -> float:
        """Mesh-generator compatibility without exposing radius in the UI."""

        return self.outer_radius_mm

    @property
    def outer_diameter_mm(self) -> float:
        return 2.0 * self.outer_radius_mm


@dataclass(frozen=True, slots=True)
class SolidTowerProfile:
    settings: GenerationSettings
    points: tuple[SolidTowerPoint, ...]
    layers: tuple[TowerLayerProfile, ...]
    warnings: tuple[str, ...]
    total_height_mm: float
    base_outer_radius_mm: float
    effective_base_height_mm: float
    feasibility_issues: tuple[FeasibilityIssue, ...] = ()
    analytical_limitations: tuple[FeasibilityIssue, ...] = ()
    support_point_count: int = 0
    maximum_spline_error_mm: float = SPLINE_RADIAL_ERROR_MM


@dataclass(frozen=True, slots=True)
class _RawSupport:
    z_mm: float
    raw_outer_radius_mm: float
    requested_outer_radius_mm: float
    required_path_mm: float
    source: str
    layer_index: int | None
    phase2_layer: LayerRadiusRecord | None = None


class ProfileFeasibilityError(ValueError):
    """Raised when no valid solid profile can be represented at all."""

    def __init__(self, issue: FeasibilityIssue) -> None:
        super().__init__(issue.message)
        self.issues = (issue,)


def validate_solid_settings(settings: GenerationSettings) -> None:
    if not isinstance(settings.automatic_base_width, bool):
        raise ValueError("Automatic base width must be a boolean value.")
    if not isinstance(settings.simulate_full_tower_infill, bool):
        raise ValueError("Full tower infill simulation must be a boolean value.")

    for name, value in settings.to_dict().items():
        if name in {"automatic_base_width", "simulate_full_tower_infill"}:
            continue
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"Generation setting {name} must be finite.")

    if settings.minimum_outer_diameter_mm <= 0.0:
        raise ValueError("Minimum outer diameter must be greater than zero.")
    if (
        settings.maximum_outer_diameter_mm
        < settings.minimum_outer_diameter_mm
    ):
        raise ValueError(
            "Maximum outer diameter must be greater than or equal to "
            "minimum outer diameter."
        )
    if settings.base_height_mm < 0.0:
        raise ValueError("Base height must not be negative.")
    if settings.manual_base_width_mm < MINIMUM_BASE_WIDTH_MM:
        raise ValueError(
            f"Manual base width must be at least {MINIMUM_BASE_WIDTH_MM:g} mm."
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


def build_solid_tower_profile(
    phase2_profile: TowerRadiusProfile,
    settings: GenerationSettings,
    *,
    tower_end_z_mm: float | None = None,
    object_height_mm: float | None = None,
) -> SolidTowerProfile:
    """Build a closed, cavity-free tower controlled only by outer diameter.

    The analytical input deliberately estimates only the outside perimeter.
    Real wall and infill contributions are measured by the calibration slice
    and feed the next diameter iteration back into this same builder.
    """

    validate_solid_settings(settings)
    if not phase2_profile.layers:
        raise ValueError("A solid profile requires at least one layer.")

    last_layer_z = phase2_profile.layers[-1].z_mm
    total_height = last_layer_z if tower_end_z_mm is None else tower_end_z_mm
    if not math.isfinite(total_height) or total_height <= 0.0:
        raise ValueError("Tower end height must be finite and greater than zero.")
    if total_height < last_layer_z - EPSILON:
        raise ValueError("Tower end height cannot be below the last included layer.")

    base_reference_height = (
        total_height if object_height_mm is None else object_height_mm
    )
    calculated_base_outer = calculate_phase10_base_outer_radius(
        object_height_mm=base_reference_height,
        automatic_base_width=settings.automatic_base_width,
        manual_base_width_mm=settings.manual_base_width_mm,
    )
    minimum_outer = settings.minimum_outer_radius_mm
    if (
        not settings.automatic_base_width
        and calculated_base_outer + EPSILON < minimum_outer
    ):
        raise ProfileFeasibilityError(
            FeasibilityIssue(
                code="BASE_WIDTH_TOO_SMALL",
                message=(
                    "Die manuelle Standfußbreite unterschreitet den "
                    "eingestellten kleinsten Außendurchmesser."
                ),
                affected_z_mm=0.0,
                related_setting_names=(
                    "manual_base_width_mm",
                    "minimum_outer_diameter_mm",
                ),
                required_value=settings.minimum_outer_diameter_mm,
                achievable_value=settings.manual_base_width_mm,
            )
        )
    base_outer = max(calculated_base_outer, minimum_outer)
    effective_base_height = min(settings.base_height_mm, total_height)
    supports = _build_raw_supports(
        phase2_profile=phase2_profile,
        total_height_mm=total_height,
        effective_base_height_mm=effective_base_height,
        base_outer_radius_mm=base_outer,
        settings=settings,
    )
    base_anchor_index = max(
        index
        for index, support in enumerate(supports)
        if support.z_mm <= effective_base_height + EPSILON
    )
    outer_radii, unreachable = _build_outer_envelope(
        supports=supports,
        base_anchor_index=base_anchor_index,
        base_outer_radius_mm=base_outer,
        maximum_expansion_slope=angle_to_radial_slope(
            settings.maximum_expansion_angle_deg
        ),
        maximum_contraction_slope=angle_to_radial_slope(
            settings.maximum_contraction_angle_deg
        ),
    )

    analytical_limitations: list[FeasibilityIssue] = []
    _append_angle_issues(
        issues=analytical_limitations,
        supports=supports,
        unreachable_indices=unreachable,
        outer_radii=outer_radii,
        base_anchor_index=base_anchor_index,
        settings=settings,
    )
    support_points, layer_results = _build_support_results(
        supports=supports,
        outer_radii=outer_radii,
        settings=settings,
        analytical_limitations=analytical_limitations,
        effective_base_height_mm=effective_base_height,
    )
    points = _sample_support_splines(support_points)
    unique_limitations = _unique_issues(analytical_limitations)
    warnings = [
        "Der Kühlturm wird als geschlossener Vollkörper ohne Hohlraum erzeugt.",
        (
            "Die Testslices simulieren 100 % Turmfüllung; beim späteren "
            "Slicen der STL muss für den Kühlturm ebenfalls 100 % Fülldichte "
            "eingestellt werden."
            if settings.simulate_full_tower_infill
            else "Die tatsächlich gedruckte Turmfüllung folgt der globalen "
            "Fülldichte und dem Füllmuster des ausgewählten Prozessprofils."
        ),
    ]
    if unique_limitations:
        warnings.append(
            "Die analytische Umfangsschätzung erreicht eine Geometriegrenze. "
            "Der Testslice entscheidet anhand der tatsächlichen Wände und "
            "Füllung, ob die Ziel-Layerzeit dennoch erreicht wird."
        )
    return SolidTowerProfile(
        settings=settings,
        points=points,
        layers=layer_results,
        warnings=tuple(dict.fromkeys(warnings)),
        total_height_mm=total_height,
        base_outer_radius_mm=base_outer,
        effective_base_height_mm=effective_base_height,
        feasibility_issues=(),
        analytical_limitations=unique_limitations,
        support_point_count=len(support_points),
    )


def _build_raw_supports(
    *,
    phase2_profile: TowerRadiusProfile,
    total_height_mm: float,
    effective_base_height_mm: float,
    base_outer_radius_mm: float,
    settings: GenerationSettings,
) -> tuple[_RawSupport, ...]:
    supports = [
        _RawSupport(
            z_mm=0.0,
            raw_outer_radius_mm=base_outer_radius_mm,
            requested_outer_radius_mm=base_outer_radius_mm,
            required_path_mm=0.0,
            source="base_bottom",
            layer_index=None,
        )
    ]
    regular_by_layer: dict[int, tuple[float, float]] = {}
    for layer in phase2_profile.layers:
        requested = max(
            settings.minimum_outer_radius_mm,
            layer.calculated_radius_mm,
        )
        regular = min(settings.maximum_outer_radius_mm, requested)
        regular_by_layer[layer.layer_index] = (regular, requested)
        in_base = layer.z_mm <= effective_base_height_mm + EPSILON
        supports.append(
            _RawSupport(
                z_mm=layer.z_mm,
                raw_outer_radius_mm=(
                    base_outer_radius_mm if in_base else regular
                ),
                requested_outer_radius_mm=(
                    min(base_outer_radius_mm, requested) if in_base else requested
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
                requested_outer_radius_mm=base_outer_radius_mm,
                required_path_mm=0.0,
                source="base_transition",
                layer_index=None,
            )
        )

    last_layer = phase2_profile.layers[-1]
    if total_height_mm > last_layer.z_mm + EPSILON:
        regular, requested = regular_by_layer[last_layer.layer_index]
        in_base = total_height_mm <= effective_base_height_mm + EPSILON
        supports.append(
            _RawSupport(
                z_mm=total_height_mm,
                raw_outer_radius_mm=(base_outer_radius_mm if in_base else regular),
                requested_outer_radius_mm=(
                    min(base_outer_radius_mm, requested) if in_base else requested
                ),
                required_path_mm=last_layer.safety_adjusted_path_mm,
                source="synthetic_final_layer",
                layer_index=None,
                phase2_layer=last_layer,
            )
        )

    supports.sort(key=lambda support: support.z_mm)
    for previous, current in zip(supports, supports[1:]):
        if current.z_mm <= previous.z_mm + EPSILON:
            raise ValueError("Solid profile support heights must be strictly increasing.")
    return tuple(supports)


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


def _build_support_results(
    *,
    supports: tuple[_RawSupport, ...],
    outer_radii: tuple[float, ...],
    settings: GenerationSettings,
    analytical_limitations: list[FeasibilityIssue],
    effective_base_height_mm: float,
) -> tuple[tuple[SolidTowerPoint, ...], tuple[TowerLayerProfile, ...]]:
    z_values = tuple(support.z_mm for support in supports)
    points: list[SolidTowerPoint] = []
    layers: list[TowerLayerProfile] = []
    for index, (support, outer) in enumerate(
        zip(supports, outer_radii, strict=True)
    ):
        reached = outer + EPSILON >= support.requested_outer_radius_mm
        available_path = math.tau * outer
        if not reached and support.layer_index is not None:
            analytical_limitations.append(
                FeasibilityIssue(
                    code="MAXIMUM_OUTER_DIAMETER_REACHED",
                    message=(
                        "Die analytisch benötigte Layerzeit ist trotz größtem "
                        "Außendurchmesser noch nicht erreichbar. Der Testslice "
                        "prüft zusätzlich die Zeitwirkung der Füllung."
                    ),
                    affected_layer_index=support.layer_index,
                    affected_z_mm=support.z_mm,
                    related_setting_names=("maximum_outer_diameter_mm",),
                    required_value=2.0 * support.requested_outer_radius_mm,
                    achievable_value=settings.maximum_outer_diameter_mm,
                )
            )
        expansion, contraction = _support_angles(
            z_values, outer_radii, index
        )
        region = _profile_region(
            support=support,
            index=index,
            outer_radii=outer_radii,
            effective_base_height_mm=effective_base_height_mm,
        )
        points.append(
            SolidTowerPoint(
                z_mm=support.z_mm,
                outer_radius_mm=outer,
                source=support.source,
                layer_index=support.layer_index,
                raw_outer_radius_mm=support.raw_outer_radius_mm,
                profile_region=region,
            )
        )
        if support.layer_index is None:
            continue
        phase2 = support.phase2_layer
        if phase2 is None:
            raise RuntimeError("Layer support lost its source data.")
        estimated = (
            available_path * phase2.seconds_per_deposition_mm
            if phase2.seconds_per_deposition_mm is not None
            else None
        )
        layers.append(
            TowerLayerProfile(
                index=support.layer_index,
                z=support.z_mm,
                required_path_mm=support.required_path_mm,
                available_path_mm=available_path,
                outer_radius_mm=outer,
                inner_radius_mm=0.0,
                wall_thickness_mm=outer,
                wall_path_count=0,
                target_reached=reached,
                layer_time_s=phase2.layer_time_s,
                time_deficit_s=phase2.time_deficit_s,
                raw_outer_radius_mm=support.raw_outer_radius_mm,
                expansion_angle_deg=expansion,
                contraction_angle_deg=contraction,
                estimated_added_time_s=estimated,
                profile_region=region,
            )
        )
    return tuple(points), tuple(layers)


def _sample_support_splines(
    support_points: tuple[SolidTowerPoint, ...],
) -> tuple[SolidTowerPoint, ...]:
    sampled: list[SolidTowerPoint] = [support_points[0]]
    for start, end in zip(support_points, support_points[1:]):
        for sample in adaptive_quintic_segment_samples(
            start_z_mm=start.z_mm,
            end_z_mm=end.z_mm,
            start_outer_radius_mm=start.outer_radius_mm,
            end_outer_radius_mm=end.outer_radius_mm,
            start_wall_thickness_mm=0.0,
            end_wall_thickness_mm=0.0,
            maximum_radial_error_mm=SPLINE_RADIAL_ERROR_MM,
            maximum_z_step_mm=SPLINE_MAXIMUM_Z_STEP_MM,
        ):
            if sample.t >= 1.0 - EPSILON:
                sampled.append(end)
            else:
                sampled.append(
                    SolidTowerPoint(
                        z_mm=sample.z_mm,
                        outer_radius_mm=sample.outer_radius_mm,
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
        previous = max(base_anchor_index, index - 1)
        delta_z = support.z_mm - supports[previous].z_mm
        required_angle = 90.0 if delta_z <= EPSILON else slope_to_angle_deg(
            1.875
            * max(
                0.0,
                support.raw_outer_radius_mm - outer_radii[previous],
            )
            / delta_z
        )
        issues.append(
            FeasibilityIssue(
                code="EXPANSION_ANGLE_TOO_SMALL",
                message=(
                    "Der eingestellte Aufweitungswinkel ist zu flach, um den "
                    "benötigten Außendurchmesser rechtzeitig zu erreichen."
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


def _support_angles(
    z_values: tuple[float, ...],
    outer_values: tuple[float, ...],
    index: int,
) -> tuple[float, float]:
    expansion = 0.0
    contraction = 0.0
    for left_index, right_index in ((index - 1, index), (index, index + 1)):
        if left_index < 0 or right_index >= len(outer_values):
            continue
        start = outer_values[left_index]
        end = outer_values[right_index]
        angle = slope_to_angle_deg(
            maximum_quintic_segment_slope(
                start,
                end,
                z_values[right_index] - z_values[left_index],
            )
        )
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
    effective_base_height_mm: float,
) -> str:
    if support.source == "synthetic_final_layer":
        return "final_cap"
    if support.z_mm <= effective_base_height_mm + EPSILON:
        return "base"
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
    if support.required_path_mm > EPSILON:
        return "time_peak"
    return "minimum_trunk"


def _transition_region(start: SolidTowerPoint, end: SolidTowerPoint) -> str:
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
        unique[
            (issue.code, issue.affected_layer_index, issue.affected_z_mm)
        ] = issue
    return tuple(unique.values())
