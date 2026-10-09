"""Independent, session-only results for each tower generation method."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from cooling_tower.preview import PreviewExportResult, PreviewResult, PreviewState


class GenerationMode(str, Enum):
    AUTOMATIC = "automatic"
    MANUAL = "manual"


@dataclass(slots=True)
class GenerationSession:
    preview: PreviewResult | None = None
    preview_state: PreviewState = PreviewState.EMPTY
    export_result: PreviewExportResult | None = None
    exported_preview_identity: tuple[str, str | None] | None = None

    def discard_preview(self) -> None:
        if self.preview is not None:
            self.preview.dispose()
            self.preview = None
        self.preview_state = PreviewState.EMPTY
        self.exported_preview_identity = None
