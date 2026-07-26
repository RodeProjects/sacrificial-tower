from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class TowerNeedAssessment:
    """Live decision and height boundary derived from analyzed layer times."""

    tower_required: bool
    target_layer_time_s: float
    safety_factor: float

    deficit_layer_count: int
    first_deficit_layer_index: int | None
    last_deficit_layer_index: int | None
    first_deficit_z_mm: float | None
    last_deficit_z_mm: float | None

    tower_end_layer_index: int | None
    tower_end_layer_position: int | None
    tower_end_z_mm: float | None
    tower_layer_count: int

    maximum_time_deficit_s: float
    synthetic_final_layer_used: bool
    original_model_height_mm: float
    saved_tower_height_mm: float
    layer_time_deficits_s: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class NoTowerRequiredResult:
    """Successful no-output outcome when every layer already meets the target."""

    source_gcode_path: Path
    layer_count: int
    assessment: TowerNeedAssessment
    analysis_snapshot: object
    settings: object

    @property
    def reason(self) -> str:
        return (
            "Kein analysierter Layer unterschreitet die eingestellte "
            "Ziel-Layerzeit. Es wurde keine STL erzeugt."
        )
