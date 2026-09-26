from __future__ import annotations

import hashlib
import json
import math
import tempfile
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cooling_tower.models import (
    BedBounds,
    CalibrationConfig,
    CalibrationMode,
    GenerationSettings,
    PreparedAnalysisSource,
    SourceArtifact,
)

if TYPE_CHECKING:
    from cooling_tower.preview.source_cache import PreviewSourceData


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
    object_height_mm: float | None = None
    object_layer_count: int | None = None
    tower_layer_count: int | None = None
    tower_circle_segments: int | None = None


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
    source_artifact: SourceArtifact | None = field(
        default=None,
        compare=False,
        repr=False,
    )
    prepared_analysis_source: PreparedAnalysisSource | None = field(
        default=None,
        compare=False,
        repr=False,
    )
    prepared_source_data: PreviewSourceData | None = field(
        default=None,
        compare=False,
        repr=False,
    )
    maximum_object_segments: int = 60_000
    force_tower: bool = False

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
        if (
            self.adapter is None or self.effective_profile is None
        ):
            raise ValueError(
                "Vorschau und Export benötigen einen geprüften Slicer und "
                "ein wirksames Druckprofil."
            )
        if (
            self.calibration_config.maximum_iterations < 1
        ):
            raise ValueError(
                "Vorschau und Export benötigen mindestens einen Slicer-Durchlauf."
            )
        prepared = self.prepared_analysis_source
        artifact = self.source_artifact
        if prepared is not None:
            if prepared.analysis_gcode_path != self.source_path:
                raise ValueError(
                    "Der vorbereitete Analysekontext gehört nicht zum G-Code-Snapshot."
                )
            if artifact is not None and prepared.source_artifact != artifact:
                raise ValueError(
                    "Originalquelle und vorbereiteter Analysekontext widersprechen sich."
                )

    @property
    def source_path(self) -> Path:
        return Path(getattr(self.snapshot, "gcode_path")).resolve()

    @property
    def output_source_path(self) -> Path:
        """User-facing source used exclusively for run and artifact names."""

        if self.source_artifact is not None:
            return self.source_artifact.original_path
        return self.source_path

    def original_source_is_current(self) -> bool:
        artifact = self.source_artifact
        return artifact is None or artifact.matches_current_file(
            verify_content=True
        )

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
            "original_source": (
                {
                    "kind": self.source_artifact.source_kind.value,
                    "path": str(self.source_artifact.original_path),
                    "size_bytes": self.source_artifact.original_size,
                    "modified_ns": self.source_artifact.original_mtime_ns,
                    "sha256": self.source_artifact.original_sha256,
                }
                if self.source_artifact is not None
                else None
            ),
            "gcode_origin": (
                self.prepared_analysis_source.gcode_origin.value
                if self.prepared_analysis_source is not None
                else None
            ),
            "analysis_gcode_sha256": (
                self.prepared_analysis_source.gcode_sha256
                if self.prepared_analysis_source is not None
                else getattr(self.snapshot, "content_sha256", None)
            ),
            "analysis_file_size": getattr(
                self.snapshot, "file_size_bytes", None
            ),
            "analysis_modified_ns": getattr(
                self.snapshot, "file_modified_ns", None
            ),
            "settings": self.settings.to_dict(),
            "force_tower": self.force_tower,
            "output_mode": self.output_mode.value,
            "slicer_identity_key": self.slicer_identity_key,
            "profile_fingerprint": self.profile_fingerprint,
            "supports_simulated": bool(getattr(self.effective_profile, "supports_simulated", False)),
            "draft_shield_simulated": bool(getattr(self.effective_profile, "draft_shield_simulated", False)),
            "calibration": _json_value(asdict(self.calibration_config)),
            "maximum_object_segments": self.maximum_object_segments,
        }

    def signature(self) -> str:
        return self._signature_for_payload(self.signature_payload())

    def signature_for_joint_slice(self, enabled: bool) -> str:
        """Return the same request identity with only the joint-slice policy changed."""

        payload = self.signature_payload()
        calibration = dict(payload["calibration"])
        calibration["perform_joint_final_slice"] = bool(enabled)
        payload["calibration"] = calibration
        return self._signature_for_payload(payload)

    def refinement_seed_signature(self) -> str:
        """Identify geometry-compatible requests independent of pass budgets.

        This compatibility identity is retained for callers that resume a
        calibration from a previously measured geometry candidate.
        """

        payload = self.signature_payload()
        calibration = dict(payload["calibration"])
        for key in (
            "maximum_iterations",
            "maximum_joint_slices",
            "minimum_joint_slices",
            "completed_joint_slices_before_run",
            "perform_joint_final_slice",
        ):
            calibration.pop(key, None)
        payload["calibration"] = calibration
        return self._signature_for_payload(payload)

    @staticmethod
    def _signature_for_payload(payload: dict[str, Any]) -> str:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


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
    refinement_seed_signature: str | None = None
    project_path: Path | None = None
    project_sha256: str | None = None
    joint_sliced: bool = False
    completed_joint_slice_count: int = 0
    configured_joint_slice_count: int = 0
    slicer_optimized: bool = False
    calibration: Any = None
    minimum_verified_layer_time_s: float | None = None
    target_layer_time_s: float | None = None
    calibration_time_tolerance_s: float = 0.2
    calibration_slicer_result_tolerance_s: float = 0.25
    calibration_profile_tolerance_mm: float = 0.1
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
    project_path: Path | None = None
    emergency_fallback_used: bool = False
    primary_failure_reason: str | None = None
    target_layer_time_s: float | None = None
    calibration_time_tolerance_s: float = 0.2
    supports_simulated: bool = False
    draft_shield_simulated: bool = False
    full_tower_infill_simulated: bool = False

    @property
    def simulated_project_properties(self) -> tuple[str, ...]:
        if self.project_path is None:
            return ()
        return tuple(label for enabled, label in (
            (self.supports_simulated, "Aktivierte Stützen wurden simuliert"),
            (self.draft_shield_simulated, "Draft Shield wurde simuliert deaktiviert"),
            (self.full_tower_infill_simulated, "100%-Turmfüllung simuliert"),
        ) if enabled)

    @property
    def technical_report_path(self) -> Path:
        """Explicit alias while keeping report_path backward compatible."""

        return self.report_path
