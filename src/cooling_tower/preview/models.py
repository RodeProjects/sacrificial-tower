from __future__ import annotations

import hashlib
import json
import math
import tempfile
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from cooling_tower.models import (
    BedBounds,
    CalibrationConfig,
    CalibrationMode,
    GenerationSettings,
)


PREVIEW_SCHEMA_VERSION = 1


class OutputMode(str, Enum):
    STL = "stl"
    GCODE = "gcode"


class PreviewState(str, Enum):
    EMPTY = "empty"
    BUILDING = "building"
    CURRENT = "current"
    STALE = "stale"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Point3D:
    x: float
    y: float
    z: float

    def __post_init__(self) -> None:
        if not all(math.isfinite(value) for value in (self.x, self.y, self.z)):
            raise ValueError("Vorschaukoordinaten müssen endliche Zahlen sein.")


@dataclass(frozen=True, slots=True)
class LineSegment3D:
    start: Point3D
    end: Point3D


@dataclass(frozen=True, slots=True)
class PreviewScene:
    object_segments: tuple[LineSegment3D, ...]
    tower_segments: tuple[LineSegment3D, ...]
    bed_bounds: BedBounds
    tower_center_xy_mm: tuple[float, float]
    source_segment_count: int
    displayed_segment_count: int
    tower_height_mm: float
    notes: tuple[str, ...] = ()


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class PreviewRequest:
    snapshot: Any = field(compare=False, repr=False)
    settings: GenerationSettings
    output_mode: OutputMode
    calibration_config: CalibrationConfig
    slicer_identity_key: str | None = None
    profile_fingerprint: str | None = None
    effective_profile: Any = field(default=None, compare=False, repr=False)
    adapter: Any = field(default=None, compare=False, repr=False)
    maximum_object_segments: int = 60_000

    def __post_init__(self) -> None:
        if self.maximum_object_segments < 100:
            raise ValueError("At least 100 object preview segments are required.")
        expected_mode = (
            CalibrationMode.GCODE
            if self.output_mode is OutputMode.GCODE
            else CalibrationMode.STL
        )
        if self.calibration_config.mode is not expected_mode:
            raise ValueError(
                "Ausgabemodus und Kalibrierungsmodus der Vorschau müssen übereinstimmen."
            )
        if self.output_mode is OutputMode.GCODE and (
            self.adapter is None or self.effective_profile is None
        ):
            raise ValueError(
                "Die G-Code-Vorschau benötigt einen geprüften Slicer und ein "
                "wirksames Druckprofil."
            )
        if (
            self.output_mode is OutputMode.GCODE
            and self.calibration_config.maximum_iterations == 0
        ):
            raise ValueError(
                "Die G-Code-Ausgabe benötigt mindestens einen Slicer-Durchlauf."
            )

    @property
    def source_path(self) -> Path:
        return Path(getattr(self.snapshot, "gcode_path")).resolve()

    def signature_payload(self) -> dict[str, Any]:
        source = self.source_path
        try:
            stat = source.stat()
            source_state: dict[str, Any] = {
                "path": str(source),
                "size_bytes": stat.st_size,
                "modified_ns": stat.st_mtime_ns,
            }
        except OSError:
            source_state = {
                "path": str(source),
                "size_bytes": None,
                "modified_ns": None,
            }
        return {
            "preview_schema_version": PREVIEW_SCHEMA_VERSION,
            "source": source_state,
            "analysis_file_size": getattr(
                self.snapshot, "file_size_bytes", None
            ),
            "analysis_modified_ns": getattr(
                self.snapshot, "file_modified_ns", None
            ),
            "settings": self.settings.to_dict(),
            "output_mode": self.output_mode.value,
            "slicer_identity_key": self.slicer_identity_key,
            "profile_fingerprint": self.profile_fingerprint,
            "calibration": _json_value(asdict(self.calibration_config)),
            "maximum_object_segments": self.maximum_object_segments,
        }

    def signature(self) -> str:
        payload = json.dumps(
            self.signature_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass(slots=True)
class PreviewResult:
    request_signature: str
    output_mode: OutputMode
    scene: PreviewScene
    artifact_path: Path
    source_sha256: str
    artifact_sha256: str
    calibrated: bool
    generation_kind: str
    slicer_optimized: bool = False
    calibration: Any = None
    minimum_verified_layer_time_s: float | None = None
    target_layer_time_s: float | None = None
    calibration_time_tolerance_s: float = 0.15
    calibration_profile_tolerance_mm: float = 0.03
    calibration_metadata_tolerance_s: float = 0.75
    warnings: tuple[str, ...] = ()
    _temporary_owner: tempfile.TemporaryDirectory[str] | None = field(
        default=None,
        repr=False,
    )

    def dispose(self) -> None:
        owner = self._temporary_owner
        self._temporary_owner = None
        if owner is not None:
            owner.cleanup()


@dataclass(frozen=True, slots=True)
class PreviewExportResult:
    output_mode: OutputMode
    run_directory: Path
    output_path: Path
    report_path: Path
    user_report_path: Path
    calibrated: bool
    slicer_optimized: bool
    minimum_verified_layer_time_s: float | None
    source_sha256: str
    output_sha256: str

    @property
    def technical_report_path(self) -> Path:
        """Explicit alias while keeping report_path backward compatible."""

        return self.report_path
