from __future__ import annotations

import math
from dataclasses import dataclass, replace

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
from cooling_tower.tower.diameter_transitions import DiameterSegment, plan_diameter_transitions
from cooling_tower.tower.profile import LayerRadiusRecord, TowerRadiusProfile
from cooling_tower.tower.spline_profile import (
    angle_to_radial_slope,
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
    initial_geometry_limitations: tuple[FeasibilityIssue, ...] = ()
    support_point_count: int = 0
    maximum_spline_error_mm: float = SPLINE_RADIAL_ERROR_MM

    @property
    def printable_layer_count(self) -> int:
        return len(self.layers)


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
    if not isinstance(settings.simulate_tower_without_supports, bool):
        raise ValueError("Tower support simulation must be a boolean value.")

    for name, value in settings.to_dict().items():
        if name in {"automatic_base_width", "simulate_full_tower_infill", "simulate_tower_without_supports"}:
            continue
        if name == "maximum_contraction_angle_deg" and settings.simulate_full_tower_infill:
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
    if settings.minimum_object_tower_distance_mm < 0.0:
        raise ValueError(
            "Minimum object/tower distance must not be negative."
        )
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
    if not settings.simulate_full_tower_infill:
        angle_to_radial_slope(settings.maximum_contraction_angle_deg)


def build_solid_tower_profile(
    phase2_profile: TowerRadiusProfile,
    settings: GenerationSettings,
    *,
    tower_end_z_mm: float | None = None,
    object_height_mm: float | None = None,
) -> SolidTowerProfile:
    """Build a closed, cavity-free tower controlled only by outer diameter.

    The initial geometry input deliberately estimates only the outside perimeter.
    Real wall and infill contributions are measured by the calibration slice
    and feed the next diameter iteration back into this same builder.
    """

    validate_solid_settings(settings)
    if not phase2_profile.layers:
        raise ValueError("A solid profile requires at least one layer.")

    # The config retains original indices even when the tower ends early.
    # Also protect callers that provide a seed or a manually built profile.
    excluded = phase2_profile.config.excluded_layer_indices
    if settings.excluded_layer_ranges and not excluded:
        # Translate against profile positions; a range may extend above the tower.
        excluded = frozenset(
            layer.layer_index for position, layer in enumerate(phase2_profile.layers, 1)
            if any(start <= position <= end for start, end in settings.excluded_layer_ranges)
        )
    if excluded:
        phase2_profile = replace(phase2_profile, layers=tuple(
            replace(layer, calculated_radius_mm=settings.minimum_outer_radius_mm,
                    radius_mm=settings.minimum_outer_radius_mm, time_deficit_s=0.0,
                    additional_path_mm=0.0, safety_adjusted_path_mm=0.0)
            if layer.layer_index in excluded else layer
            for layer in phase2_profile.layers
        ))

    last_layer_z = phase2_profile.layers[-1].z_mm
    total_height = last_layer_z if tower_end_z_mm is None else tower_end_z_mm
    if not math.isfinite(total_height) or total_height <= 0.0:
        raise ValueError("Tower end height must be finite and greater than zero.")
    if total_height < last_layer_z - EPSILON:
        raise ValueError("Tower end height cannot be below the last included layer.")
    total_height = last_layer_z

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
    tiered_foot = (
        not settings.simulate_full_tower_infill
        and base_outer > 15.0 + EPSILON
        and minimum_outer <= 15.0 + EPSILON
        and len(phase2_profile.layers) >= 2
    )
    effective_base_height = phase2_profile.layers[0].z_mm
    taper_start_index = 2 if tiered_foot else 1
    taper_start_z = phase2_profile.layers[taper_start_index - 1].z_mm
    # Use the longer of six millimetres and 22 real layer intervals.
    taper_last_index = min(taper_start_index + 21, len(phase2_profile.layers) - 1)
    minimum_layer_height = max(
        0.0, phase2_profile.layers[taper_last_index].z_mm - taper_start_z,
    )
    base_taper_height = min(
        last_layer_z - taper_start_z,
        max(6.0, minimum_layer_height, 0.025 * base_reference_height),
    )
    if (settings.simulate_full_tower_infill
            and base_taper_height < last_layer_z - taper_start_z - EPSILON):
        target_z = taper_start_z + base_taper_height
        target_index = next(
            index for index in range(taper_start_index - 1, len(phase2_profile.layers))
            if phase2_profile.layers[index].z_mm >= target_z - EPSILON
        )
        raised_index = min(target_index + 5, len(phase2_profile.layers) - 1)
        base_taper_height = phase2_profile.layers[raised_index].z_mm - taper_start_z
    if calculated_base_outer > settings.maximum_outer_radius_mm + EPSILON:
        raise ProfileFeasibilityError(
            FeasibilityIssue(
                code="BASE_WIDTH_TOO_LARGE",
                message="Die Standfußbreite überschreitet den maximalen Turmdurchmesser.",
                affected_z_mm=0.0,
                related_setting_names=("maximum_outer_diameter_mm",),
                required_value=2.0 * calculated_base_outer,
                achievable_value=settings.maximum_outer_diameter_mm,
            )
        )
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
    required = [support.raw_outer_radius_mm for support in supports]
    abrupt_drops = set()
    if settings.simulate_full_tower_infill:
        for index in range(base_anchor_index + 1, len(supports)):
            previous = supports[index - 1].phase2_layer
            current = supports[index].phase2_layer
            if (previous is not None and current is not None
                    and previous.time_deficit_s > settings.layer_time_tolerance_s
                    and current.time_deficit_s <= settings.layer_time_tolerance_s
                    and current.layer_index not in excluded
                    and current.layer_time_s > previous.layer_time_s * 1.5):
                abrupt_drops.add(index)
                # A descending request before a discontinuity can come from
                # the centered timing window or calibration. Keep that trunk
                # intact until the first self-sufficient object layer.
                start = index - 1
                while (start > base_anchor_index + 1
                       and required[start - 1] >= required[start] - EPSILON):
                    start -= 1
                held_radius = max(required[start:index])
                required[start:index] = [held_radius] * (index - start)
    foot_middle_radius = 0.5 * (base_outer + 15.0)
    plan_start = 2 if tiered_foot else 0
    planned_radii, planned_unreachable, planned_segments = plan_diameter_transitions(
        tuple(support.z_mm for support in supports[plan_start:]),
        tuple(([15.0] + required[plan_start + 1:]) if tiered_foot
              else required),
        base_index=0 if tiered_foot else base_anchor_index,
        base_radius=15.0 if tiered_foot else base_outer,
        minimum_radius=minimum_outer,
        expansion_slope=angle_to_radial_slope(settings.maximum_expansion_angle_deg),
        contraction_slope=(1.0 if settings.simulate_full_tower_infill else
                           angle_to_radial_slope(settings.maximum_contraction_angle_deg)),
        allow_steps=settings.simulate_full_tower_infill,
        base_taper_height=base_taper_height,
        abrupt_drop_indices=frozenset(abrupt_drops),
        excluded_indices=frozenset(
            index - plan_start for index, support in enumerate(supports)
            if support.layer_index in excluded and index >= plan_start
        ),
    )
    if tiered_foot:
        outer_radii = (base_outer, base_outer, foot_middle_radius) + planned_radii[1:]
        unreachable = tuple(index + 2 for index in planned_unreachable)
        prefix = (
            DiameterSegment(supports[0].z_mm, supports[1].z_mm,
                            base_outer, base_outer),
            DiameterSegment(supports[1].z_mm, supports[2].z_mm,
                            base_outer, foot_middle_radius,
                            step_radius=foot_middle_radius,
                            step_source="base_tier_step"),
        )
        if planned_segments:
            first_taper_segment = replace(
                planned_segments[0], start_radius=foot_middle_radius,
                step_radius=15.0, step_source="base_tier_step",
            )
            segments = prefix + (first_taper_segment,) + planned_segments[1:]
        else:
            segments = prefix
    else:
        outer_radii, unreachable, segments = (
            planned_radii, planned_unreachable, planned_segments,
        )

    initial_geometry_limitations: list[FeasibilityIssue] = []
    _append_angle_issues(
        issues=initial_geometry_limitations,
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
        initial_geometry_limitations=initial_geometry_limitations,
        effective_base_height_mm=effective_base_height,
        segments=segments,
    )
    points = _sample_support_splines(support_points, segments)
    if tiered_foot and not planned_segments:
        points += (SolidTowerPoint(
            z_mm=taper_start_z, outer_radius_mm=15.0,
            source="base_tier_step", layer_index=None,
            raw_outer_radius_mm=15.0, profile_region="shoulder",
        ),)
    unique_limitations = _unique_issues(initial_geometry_limitations)
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
            "Der erste Geometriekandidat erreicht eine Geometriegrenze. "
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
        initial_geometry_limitations=unique_limitations,
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
    for layer in phase2_profile.layers:
        requested = max(
            settings.minimum_outer_radius_mm,
            layer.calculated_radius_mm,
        )
        regular = min(settings.maximum_outer_radius_mm, requested)
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

    supports.sort(key=lambda support: support.z_mm)
    for previous, current in zip(supports, supports[1:]):
        if current.z_mm <= previous.z_mm + EPSILON:
            raise ValueError("Solid profile support heights must be strictly increasing.")
    return tuple(supports)


def _build_support_results(
    *,
    supports: tuple[_RawSupport, ...],
    outer_radii: tuple[float, ...],
    settings: GenerationSettings,
    initial_geometry_limitations: list[FeasibilityIssue],
    effective_base_height_mm: float,
    segments: tuple[DiameterSegment, ...],
) -> tuple[tuple[SolidTowerPoint, ...], tuple[TowerLayerProfile, ...]]:
    points: list[SolidTowerPoint] = []
    layers: list[TowerLayerProfile] = []
    for index, (support, outer) in enumerate(
        zip(supports, outer_radii, strict=True)
    ):
        reached = outer + EPSILON >= support.requested_outer_radius_mm
        available_path = math.tau * outer
        if not reached and support.layer_index is not None:
            initial_geometry_limitations.append(
                FeasibilityIssue(
                    code="MAXIMUM_OUTER_DIAMETER_REACHED",
                    message=(
                        "Die benötigte Layerzeit ist beim ersten Kandidaten trotz größtem "
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
            segments, index
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
    segments: tuple[DiameterSegment, ...],
) -> tuple[SolidTowerPoint, ...]:
    sampled = [support_points[0]]
    for start, end, segment in zip(support_points, support_points[1:], segments):
        if segment.step_radius is not None:
            sampled.append(SolidTowerPoint(
                z_mm=start.z_mm,
                outer_radius_mm=segment.step_radius,
                source=segment.step_source,
                layer_index=None,
                raw_outer_radius_mm=segment.step_radius,
                profile_region="shoulder",
            ))
        for z, radius in segment.samples(
            radial_error=SPLINE_RADIAL_ERROR_MM,
            maximum_z_step=SPLINE_MAXIMUM_Z_STEP_MM,
        ):
            if abs(z - end.z_mm) <= EPSILON:
                sampled.append(end)
            else:
                sampled.append(SolidTowerPoint(
                    z_mm=z,
                    outer_radius_mm=radius,
                    source="spline_transition",
                    layer_index=None,
                    raw_outer_radius_mm=radius,
                    profile_region=_transition_region(start, end),
                ))
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
            max(
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
    segments: tuple[DiameterSegment, ...], index: int,
) -> tuple[float, float]:
    expansion = contraction = 0.0
    for position in (index - 1, index):
        if not 0 <= position < len(segments):
            continue
        segment = segments[position]
        start = segment.start_radius if segment.step_radius is None else segment.step_radius
        slope = (segment.end_radius - start) / (segment.end_z - segment.start_z)
        expansion = max(expansion, slope)
        if segment.taper is not None:
            taper = segment.taper
            derivative = 2.0 * (taper.start_radius - taper.minimum_radius) / taper.duration
            derivative *= max(0.0, 1.0 - (segment.start_z - taper.start_z) / taper.duration)
            contraction = max(contraction, derivative)
        else:
            contraction = max(contraction, -slope)
    return slope_to_angle_deg(expansion), slope_to_angle_deg(contraction)


def _profile_region(
    *,
    support: _RawSupport,
    index: int,
    outer_radii: tuple[float, ...],
    effective_base_height_mm: float,
) -> str:
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
