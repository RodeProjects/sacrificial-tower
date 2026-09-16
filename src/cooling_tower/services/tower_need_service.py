from __future__ import annotations

import math

from cooling_tower.gcode.layer_detector import LayerRecord
from cooling_tower.models import (
    GCodeAnalysisSnapshot,
    GenerationSettings,
    TowerNeedAssessment,
)


TIME_EPSILON_S = 1e-6


def assess_tower_need(
    snapshot: GCodeAnalysisSnapshot,
    settings: GenerationSettings,
) -> TowerNeedAssessment:
    """Determine whether a tower is needed and where its mesh must end."""
    target = settings.target_layer_time_s
    safety_factor = settings.safety_factor
    if not math.isfinite(target) or target <= 0.0:
        raise ValueError("Target layer time must be greater than zero.")
    if not math.isfinite(safety_factor) or safety_factor < 1.0:
        raise ValueError("Safety factor must be at least 1.0.")
    if not snapshot.layers:
        raise ValueError("A tower assessment requires printable layers.")

    deficits = tuple(
        max(0.0, target - layer.total_time_s)
        for layer in snapshot.layers
    )
    deficit_positions = tuple(
        position
        for position, deficit in enumerate(deficits)
        if deficit > TIME_EPSILON_S
    )
    model_height = snapshot.layers[-1].z_mm

    if not deficit_positions:
        return TowerNeedAssessment(
            tower_required=False,
            target_layer_time_s=target,
            safety_factor=safety_factor,
            deficit_layer_count=0,
            first_deficit_layer_index=None,
            last_deficit_layer_index=None,
            first_deficit_z_mm=None,
            last_deficit_z_mm=None,
            tower_end_layer_index=None,
            tower_end_layer_position=None,
            tower_end_z_mm=None,
            tower_layer_count=0,
            maximum_time_deficit_s=0.0,
            synthetic_final_layer_used=False,
            original_model_height_mm=model_height,
            saved_tower_height_mm=model_height,
            layer_time_deficits_s=deficits,
        )

    first_position = deficit_positions[0]
    last_position = deficit_positions[-1]
    first_layer = snapshot.layers[first_position]
    last_layer = snapshot.layers[last_position]
    # One sufficient top surface alone is not a useful early termination.
    end_position = (len(snapshot.layers) - 1
                    if last_position >= len(snapshot.layers) - 2 else last_position)
    end_layer = snapshot.layers[end_position]
    end_layer_index = end_layer.index
    end_z = end_layer.z_mm
    tower_layer_count = end_position + 1

    return TowerNeedAssessment(
        tower_required=True,
        target_layer_time_s=target,
        safety_factor=safety_factor,
        deficit_layer_count=len(deficit_positions),
        first_deficit_layer_index=first_layer.index,
        last_deficit_layer_index=last_layer.index,
        first_deficit_z_mm=first_layer.z_mm,
        last_deficit_z_mm=last_layer.z_mm,
        tower_end_layer_index=end_layer_index,
        tower_end_layer_position=end_position,
        tower_end_z_mm=end_z,
        tower_layer_count=tower_layer_count,
        maximum_time_deficit_s=max(deficits),
        synthetic_final_layer_used=False,
        original_model_height_mm=model_height,
        saved_tower_height_mm=max(0.0, model_height - end_z),
        layer_time_deficits_s=deficits,
    )


def layers_for_tower(
    snapshot: GCodeAnalysisSnapshot,
    assessment: TowerNeedAssessment,
) -> tuple[LayerRecord, ...]:
    if not assessment.tower_required:
        return ()
    return snapshot.layers[: assessment.tower_layer_count]
