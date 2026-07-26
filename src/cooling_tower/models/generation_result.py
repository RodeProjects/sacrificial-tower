from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class GenerationResult:
    """Paths, statistics and warnings from one complete generation run."""

    run_directory: Path
    stl_path: Path
    analysis_path: Path
    profile_path: Path
    settings_path: Path
    log_path: Path

    layer_count: int
    layers_below_target: int
    maximum_outer_radius_mm: float
    maximum_wall_thickness_mm: float
    warnings: list[str] = field(default_factory=list)

    summary_path: Path | None = None
    metadata_path: Path | None = None
    analysis: Any = None
    profile: Any = None
    mesh_validation: Any = None
    source_gcode_path: Path | None = None
    settings: Any = None
    assessment: Any = None
    analysis_snapshot: Any = None
    feasibility_issues: Any = None
    gcode_path: Path | None = None
    calibration_report_path: Path | None = None
    calibration: Any = None
