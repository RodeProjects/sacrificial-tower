"""Independent, session-only results for each tower generation method."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from cooling_tower.preview import PreviewExportResult, PreviewResult, PreviewState
from cooling_tower.legacy_method_ids import LEGACY_POSTPROCESSOR_ID


class GenerationMode(str, Enum):
    AUTOMATIC = "automatic"
    MANUAL = "manual"
    POSTPROCESSOR = "postprocessor"

    @classmethod
    def _missing_(cls, value):
        if value == LEGACY_POSTPROCESSOR_ID:
            return cls.POSTPROCESSOR
        return None


@dataclass(slots=True)
class GenerationSession:
    preview: PreviewResult | None = None
    preview_state: PreviewState = PreviewState.EMPTY
    export_result: PreviewExportResult | None = None
    exported_preview_identity: tuple[str, str | None] | None = None
    manual_draft: Any = None
    successful_request: Any = None
    running_request: Any = None
    last_export_report: Any = None
    latest_export_directory: Path | None = None
    latest_export_root: str | None = None
    latest_export_unavailable_reason: str = "Kein Exportordner gefunden."

    def discard_preview(self) -> None:
        if self.preview is not None:
            self.preview.dispose()
            self.preview = None
        self.preview_state = PreviewState.EMPTY
        self.exported_preview_identity = None
        self.successful_request = None
