from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import Signal, Slot

from cooling_tower.gui.worker_contract import CancelableWorker
from cooling_tower.preview import (
    PreviewCancelled,
    PreviewExportService,
    PreviewRequest,
    PreviewResult,
    PreviewService,
)
from cooling_tower.preview.controller import PreviewBuildController


class ExportWorker(CancelableWorker):
    progress = Signal(int, int, str)
    succeeded = Signal(int, object)
    failed = Signal(int, str, str)
    finished = Signal(int)

    def __init__(
        self,
        request_id: int,
        preview: PreviewResult | None,
        request: PreviewRequest,
        output_root: Path,
        export_service: PreviewExportService,
        preview_service: PreviewService,
        seed_preview: PreviewResult | None = None,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.preview = preview
        self.request = request
        self.output_root = output_root
        self.export_service = export_service
        self.preview_service = preview_service
        self.seed_preview = seed_preview

    @Slot()
    def run(self) -> None:
        with self.diagnostic_scope():
            generated_preview: PreviewResult | None = None
            try:
                preview = self.preview
                if preview is None:
                    controller = PreviewBuildController(self.preview_service, self)
                    generated_preview = controller.execute(
                        self.request,
                        cancellation_event=self.cancellation_event,
                        progress_callback=lambda percent, status: self.progress.emit(
                            self.request_id, percent, status
                        ),
                        seed_preview=self.seed_preview,
                    )
                    preview = generated_preview
                else:
                    self.progress.emit(
                        self.request_id,
                        75,
                        "Aktuelle Vorschau wird für den Export übernommen …",
                    )
                if self.cancellation_requested():
                    raise PreviewCancelled()
                self.progress.emit(
                    self.request_id,
                    95,
                    "STL-Datei und Berichte werden gespeichert …",
                )
                result = self.export_service.export(
                    preview,
                    self.request,
                    self.output_root,
                )
            except PreviewCancelled:
                pass
            except Exception as error:
                if not self.cancellation_requested():
                    self.failed.emit(
                        self.request_id,
                        str(error),
                        traceback.format_exc(),
                    )
            else:
                self.succeeded.emit(self.request_id, result)
            finally:
                if generated_preview is not None:
                    generated_preview.dispose()
                    self.diagnose("temporary_data_cleaned")
                self.finished.emit(self.request_id)
