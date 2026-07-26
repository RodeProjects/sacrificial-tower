from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from cooling_tower.models.gcode_metadata import GCodeMetadata
from cooling_tower.models.timing import TimingEvidence


ANALYSIS_REPORT_SCHEMA_VERSION = 1


class UnsupportedAnalysisReportSchemaError(ValueError):
    """Raised for reports written by an unsupported newer application."""


@dataclass(frozen=True, slots=True)
class AnalysisDiagnosticReport:
    """Versioned, source-labelled technical analysis report."""

    source_gcode: Path
    layer_count: int
    minimum_layer_time_s: float
    maximum_layer_time_s: float
    maximum_print_z_mm: float
    metadata: GCodeMetadata = field(default_factory=GCodeMetadata)
    timing_evidence: TimingEvidence = field(default_factory=TimingEvidence)
    local_installation_verified: bool = False
    exact_profile_verified: bool = False
    schema_version: int = ANALYSIS_REPORT_SCHEMA_VERSION

    @classmethod
    def from_snapshot(
        cls,
        snapshot: object,
        *,
        local_installation_verified: bool = False,
        exact_profile_verified: bool = False,
    ) -> "AnalysisDiagnosticReport":
        return cls(
            source_gcode=Path(getattr(snapshot, "gcode_path")),
            layer_count=int(getattr(snapshot, "layer_count")),
            minimum_layer_time_s=float(
                getattr(snapshot, "minimum_layer_time_s")
            ),
            maximum_layer_time_s=float(
                getattr(snapshot, "maximum_layer_time_s")
            ),
            maximum_print_z_mm=float(
                getattr(snapshot, "maximum_print_z_mm")
            ),
            metadata=getattr(snapshot, "metadata", GCodeMetadata()),
            timing_evidence=getattr(
                snapshot,
                "timing_evidence",
                TimingEvidence(),
            ),
            local_installation_verified=local_installation_verified,
            exact_profile_verified=exact_profile_verified,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_report_schema_version": self.schema_version,
            "source_gcode": str(self.source_gcode),
            "layer_count": self.layer_count,
            "minimum_layer_time_s": self.minimum_layer_time_s,
            "maximum_layer_time_s": self.maximum_layer_time_s,
            "maximum_print_z_mm": self.maximum_print_z_mm,
            "metadata": self.metadata.to_dict(),
            "timing_evidence": self.timing_evidence.to_dict(),
            "verification": {
                "local_installation_verified": (
                    self.local_installation_verified
                ),
                "exact_profile_verified": self.exact_profile_verified,
            },
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "AnalysisDiagnosticReport":
        version = int(payload.get("analysis_report_schema_version", 0))
        if version > ANALYSIS_REPORT_SCHEMA_VERSION:
            raise UnsupportedAnalysisReportSchemaError(
                "Unsupported analysis report schema version "
                f"{version}; maximum supported version is "
                f"{ANALYSIS_REPORT_SCHEMA_VERSION}."
            )
        if version == 0:
            return cls._from_legacy_dict(payload)
        raw_metadata = payload.get("metadata", {})
        metadata = (
            GCodeMetadata.from_dict(raw_metadata)
            if isinstance(raw_metadata, Mapping)
            else GCodeMetadata()
        )
        raw_timing = payload.get("timing_evidence", {})
        timing = (
            TimingEvidence.from_dict(raw_timing)
            if isinstance(raw_timing, Mapping)
            else TimingEvidence()
        )
        verification = payload.get("verification", {})
        if not isinstance(verification, Mapping):
            verification = {}
        return cls(
            source_gcode=Path(str(payload.get("source_gcode", ""))),
            layer_count=int(payload.get("layer_count", 0)),
            minimum_layer_time_s=float(
                payload.get("minimum_layer_time_s", 0.0)
            ),
            maximum_layer_time_s=float(
                payload.get("maximum_layer_time_s", 0.0)
            ),
            maximum_print_z_mm=float(
                payload.get("maximum_print_z_mm", 0.0)
            ),
            metadata=metadata,
            timing_evidence=timing,
            local_installation_verified=bool(
                verification.get("local_installation_verified", False)
            ),
            exact_profile_verified=bool(
                verification.get("exact_profile_verified", False)
            ),
        )

    @classmethod
    def _from_legacy_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "AnalysisDiagnosticReport":
        metadata_payload: dict[str, Any] = {}
        legacy_metadata = payload.get("metadata")
        if isinstance(legacy_metadata, Mapping):
            metadata_payload.update(legacy_metadata)
        for key in (
            "generator_name",
            "generator_version",
            "printer_model",
            "printer_settings_id",
            "print_settings_id",
            "filament_settings_id",
            "configuration",
        ):
            if key in payload and key not in metadata_payload:
                metadata_payload[key] = payload[key]
        return cls(
            source_gcode=Path(str(payload.get("source_gcode", ""))),
            layer_count=int(payload.get("layer_count", 0)),
            minimum_layer_time_s=float(
                payload.get("minimum_layer_time_s", 0.0)
            ),
            maximum_layer_time_s=float(
                payload.get("maximum_layer_time_s", 0.0)
            ),
            maximum_print_z_mm=float(
                payload.get("maximum_print_z_mm", 0.0)
            ),
            metadata=GCodeMetadata.from_dict(metadata_payload),
            timing_evidence=TimingEvidence(),
        )
