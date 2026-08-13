"""Shared application data models."""

from cooling_tower.models.analysis import GCodeAnalysisSnapshot
from cooling_tower.models.analysis_report import (
    ANALYSIS_REPORT_SCHEMA_VERSION,
    AnalysisDiagnosticReport,
    UnsupportedAnalysisReportSchemaError,
)
from cooling_tower.models.feasibility import (
    FeasibilityIssue,
    ProfileFeasibilityAssessment,
)
from cooling_tower.models.generation_result import GenerationResult
from cooling_tower.models.generation_settings import GenerationSettings
from cooling_tower.models.gcode_metadata import (
    ConfigValueItem,
    GCodeMetadata,
    MetadataSourceKind,
    MetadataValue,
    ProfileFingerprint,
    SlicerDetectionConfidence,
    SlicerFamily,
    SlicerIdentity,
    TypedConfigValue,
    UnsupportedMetadataSchemaError,
    build_profile_fingerprint,
)
from cooling_tower.models.layer import LayerData
from cooling_tower.models.source import (
    GCodeOrigin,
    PreSliceProvenance,
    PreparedAnalysisSource,
    SourceArtifact,
    SourceChangedError,
    SourceKind,
)
from cooling_tower.models.timing import (
    LayerTimingState,
    TimeCapacityIssue,
    TimingConfidenceState,
    TimingEvidence,
    build_layer_timing_states,
    validate_time_capacity_transitions,
)
from cooling_tower.models.tower_need import (
    NoTowerRequiredResult,
    TowerNeedAssessment,
)
from cooling_tower.models.tower_profile import TowerLayerProfile
from cooling_tower.models.calibration import (
    BedBounds,
    BedGeometry,
    CalibrationConfig,
    CalibrationFailure,
    CalibrationFailureCode,
    CalibrationIteration,
    CalibrationMode,
    CalibrationResult,
    CalibrationState,
    LayerSliceTiming,
    OccupiedBounds,
    SliceEvaluation,
    TowerPlacement,
    calibration_config_from_mapping,
)

__all__ = [
    "GCodeAnalysisSnapshot",
    "ANALYSIS_REPORT_SCHEMA_VERSION",
    "AnalysisDiagnosticReport",
    "UnsupportedAnalysisReportSchemaError",
    "FeasibilityIssue",
    "ProfileFeasibilityAssessment",
    "GenerationResult",
    "GenerationSettings",
    "ConfigValueItem",
    "GCodeMetadata",
    "MetadataSourceKind",
    "MetadataValue",
    "ProfileFingerprint",
    "SlicerDetectionConfidence",
    "SlicerFamily",
    "SlicerIdentity",
    "TypedConfigValue",
    "UnsupportedMetadataSchemaError",
    "build_profile_fingerprint",
    "LayerData",
    "GCodeOrigin",
    "PreSliceProvenance",
    "PreparedAnalysisSource",
    "SourceArtifact",
    "SourceChangedError",
    "SourceKind",
    "LayerTimingState",
    "TimeCapacityIssue",
    "TimingConfidenceState",
    "TimingEvidence",
    "build_layer_timing_states",
    "validate_time_capacity_transitions",
    "NoTowerRequiredResult",
    "TowerNeedAssessment",
    "TowerLayerProfile",
    "BedBounds",
    "BedGeometry",
    "CalibrationConfig",
    "CalibrationFailure",
    "CalibrationFailureCode",
    "CalibrationIteration",
    "CalibrationMode",
    "CalibrationResult",
    "CalibrationState",
    "LayerSliceTiming",
    "OccupiedBounds",
    "SliceEvaluation",
    "TowerPlacement",
    "calibration_config_from_mapping",
]
