"""Application services shared by CLI and GUI."""

from cooling_tower.services.analysis_service import (
    AnalysisCancelled,
    GCodeAnalysisService,
    GCodeChangedDuringAnalysisError,
)
from cooling_tower.services.generation_service import GenerationService
from cooling_tower.services.feasibility_service import (
    FeasibilityCancelled,
    assess_profile_feasibility,
)
from cooling_tower.services.migration_service import MigrationService
from cooling_tower.services.output_service import OutputService
from cooling_tower.services.reporting_service import (
    GenerationReport,
    build_analysis_diagnostic_report,
    build_generation_report,
    format_analysis_diagnostic_report,
    format_generation_report,
    format_no_tower_report,
)
from cooling_tower.services.tower_need_service import (
    assess_tower_need,
    layers_for_tower,
)
from cooling_tower.services.source_recognition import (
    SOURCE_SNIFF_LIMIT_BYTES,
    SourceRecognitionError,
    SourceRecognitionResult,
    recognize_source,
)
from cooling_tower.services.stl_validation import (
    StlFormat,
    StlIssueCode,
    StlValidationCancelled,
    StlValidationError,
    StlValidationIssue,
    StlValidationLimits,
    StlValidationResult,
    StlValidationService,
)
from cooling_tower.services.source_preslice import (
    PRESLICE_ADAPTER_VERSION,
    SourcePreSliceCancelled,
    SourcePreSliceError,
    SourcePreSliceResult,
    SourcePreSliceService,
    build_preslice_cache_key,
)

__all__ = [
    "AnalysisCancelled",
    "GCodeAnalysisService",
    "GCodeChangedDuringAnalysisError",
    "GenerationReport",
    "GenerationService",
    "FeasibilityCancelled",
    "MigrationService",
    "OutputService",
    "SOURCE_SNIFF_LIMIT_BYTES",
    "SourceRecognitionError",
    "SourceRecognitionResult",
    "StlFormat",
    "StlIssueCode",
    "StlValidationCancelled",
    "StlValidationError",
    "StlValidationIssue",
    "StlValidationLimits",
    "StlValidationResult",
    "StlValidationService",
    "PRESLICE_ADAPTER_VERSION",
    "SourcePreSliceCancelled",
    "SourcePreSliceError",
    "SourcePreSliceResult",
    "SourcePreSliceService",
    "build_preslice_cache_key",
    "assess_tower_need",
    "assess_profile_feasibility",
    "build_analysis_diagnostic_report",
    "build_generation_report",
    "format_analysis_diagnostic_report",
    "format_generation_report",
    "format_no_tower_report",
    "layers_for_tower",
    "recognize_source",
]
