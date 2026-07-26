from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from cooling_tower.gcode.layer_detector import LayerAnalysis, LayerRecord
from cooling_tower.models.gcode_metadata import GCodeMetadata
from cooling_tower.models.timing import TimingEvidence


ANALYSIS_SCHEMA_VERSION = 1
ANALYSIS_PARSER_VERSION = 13


@dataclass(frozen=True, slots=True)
class GCodeAnalysisSnapshot:
    """Reusable, file-versioned result of one complete G-code analysis."""

    gcode_path: Path
    file_size_bytes: int
    file_modified_ns: int
    analysis: LayerAnalysis
    minimum_layer_time_s: float
    maximum_layer_time_s: float
    maximum_print_z_mm: float
    global_seconds_per_deposition_mm: float | None
    metadata: GCodeMetadata = field(default_factory=GCodeMetadata)
    timing_evidence: TimingEvidence = field(default_factory=TimingEvidence)
    content_sha256: str | None = None
    analysis_schema_version: int = ANALYSIS_SCHEMA_VERSION
    parser_version: int = ANALYSIS_PARSER_VERSION

    @property
    def layers(self) -> tuple[LayerRecord, ...]:
        return self.analysis.layers

    @property
    def layer_count(self) -> int:
        return len(self.layers)

    def matches_file(self, path: str | Path | None = None) -> bool:
        """Return whether the snapshot still identifies the same file version."""
        candidate = Path(path or self.gcode_path).expanduser()
        try:
            resolved = candidate.resolve(strict=True)
            statistics = resolved.stat()
        except (FileNotFoundError, OSError):
            return False
        return (
            resolved == self.gcode_path
            and statistics.st_size == self.file_size_bytes
            and statistics.st_mtime_ns == self.file_modified_ns
            and self.analysis_schema_version == ANALYSIS_SCHEMA_VERSION
            and self.parser_version == ANALYSIS_PARSER_VERSION
        )
