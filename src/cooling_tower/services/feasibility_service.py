from __future__ import annotations

from collections.abc import Callable

from cooling_tower.models import (
    GCodeAnalysisSnapshot,
    GenerationSettings,
    ProfileFeasibilityAssessment,
    TowerNeedAssessment,
)
from cooling_tower.services.tower_need_service import (
    assess_tower_need,
    layers_for_tower,
)
from cooling_tower.tower.solid_profile import (
    ProfileFeasibilityError,
    build_solid_tower_profile,
    validate_solid_settings,
)
from cooling_tower.tower.profile import (
    TowerProfileConfig,
    build_tower_radius_profile,
    validate_profile_config,
)


class FeasibilityCancelled(RuntimeError):
    """Raised when an obsolete live feasibility calculation is cancelled."""


def assess_profile_feasibility(
    snapshot: GCodeAnalysisSnapshot,
    settings: GenerationSettings,
    assessment: TowerNeedAssessment | None = None,
    *,
    cancellation_callback: Callable[[], bool] | None = None,
) -> ProfileFeasibilityAssessment:
    """Evaluate the Phase-10 profile without creating output directories."""
    cancelled = cancellation_callback or (lambda: False)
    if cancelled():
        raise FeasibilityCancelled()

    profile_config = TowerProfileConfig(
        target_layer_time_s=settings.target_layer_time_s,
        minimum_radius_mm=settings.minimum_outer_radius_mm,
        maximum_radius_mm=settings.maximum_outer_radius_mm,
        local_time_factor_window=settings.local_reference_window,
    )
    validate_profile_config(profile_config)
    validate_solid_settings(settings)
    current_assessment = assessment or assess_tower_need(snapshot, settings)
    if not current_assessment.tower_required:
        return ProfileFeasibilityAssessment(
            tower_required=False,
            feasible=True,
        )

    layers = layers_for_tower(snapshot, current_assessment)
    if cancelled():
        raise FeasibilityCancelled()
    radius_profile = build_tower_radius_profile(layers, profile_config)
    if cancelled():
        raise FeasibilityCancelled()
    try:
        solid_profile = build_solid_tower_profile(
            radius_profile,
            settings,
            tower_end_z_mm=current_assessment.tower_end_z_mm,
            object_height_mm=snapshot.maximum_print_z_mm,
        )
    except ProfileFeasibilityError as error:
        return ProfileFeasibilityAssessment(
            tower_required=True,
            feasible=False,
            issues=error.issues,
            checked_layer_count=len(layers),
        )
    if cancelled():
        raise FeasibilityCancelled()
    estimate_available = all(
        layer.estimated_added_time_s is not None
        for layer in solid_profile.layers
    )
    combined_layer_times = (
        tuple(
            float(layer.layer_time_s)
            + float(layer.estimated_added_time_s)
            for layer in solid_profile.layers
        )
        if estimate_available
        else ()
    )
    estimated_minimum = (
        min(combined_layer_times) if combined_layer_times else None
    )
    estimated_shortfall = (
        max(0.0, settings.target_layer_time_s - estimated_minimum)
        if estimated_minimum is not None
        else None
    )
    return ProfileFeasibilityAssessment(
        tower_required=True,
        feasible=not solid_profile.feasibility_issues,
        issues=solid_profile.feasibility_issues,
        checked_layer_count=len(solid_profile.layers),
        support_point_count=solid_profile.support_point_count,
        mesh_ring_count=len(solid_profile.points),
        estimated_minimum_combined_layer_time_s=estimated_minimum,
        estimated_maximum_shortfall_s=estimated_shortfall,
    )
