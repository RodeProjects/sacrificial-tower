"""On-demand Phase-17 preview and signature-bound export services."""

from cooling_tower.preview.export_service import (
    PreviewExportService,
    StalePreviewError,
)
from cooling_tower.preview.models import (
    LineSegment3D,
    OutputMode,
    Point3D,
    PreviewExportResult,
    PreviewRequest,
    PreviewResult,
    PreviewScene,
    PreviewState,
)
from cooling_tower.preview.service import PreviewBuildError, PreviewService
from cooling_tower.preview.source_cache import (
    PREVIEW_SOURCE_CACHE_SCHEMA_VERSION,
    PreviewSourceCacheKey,
    PreviewSourceData,
    PreviewSourceDataCache,
)
from cooling_tower.preview.toolpath import (
    DepositionToolpathAnalysis,
    PreviewCancelled,
    analyze_deposition_toolpaths,
    extract_deposition_toolpaths,
)

__all__ = [
    "DepositionToolpathAnalysis",
    "LineSegment3D",
    "OutputMode",
    "Point3D",
    "PreviewBuildError",
    "PreviewBuildController",
    "PreviewBuildState",
    "PreviewCancelled",
    "PreviewExportResult",
    "PreviewExportService",
    "PreviewRequest",
    "PreviewResult",
    "PreviewScene",
    "PreviewService",
    "PreviewSourceCacheKey",
    "PreviewSourceData",
    "PreviewSourceDataCache",
    "PreviewState",
    "PREVIEW_SOURCE_CACHE_SCHEMA_VERSION",
    "StalePreviewError",
    "analyze_deposition_toolpaths",
    "extract_deposition_toolpaths",
]


def __getattr__(name: str):
    # Preserve the public API without importing Qt for headless preview services.
    if name in {"PreviewBuildController", "PreviewBuildState"}:
        from cooling_tower.gui import preview_controller
        return getattr(preview_controller, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
