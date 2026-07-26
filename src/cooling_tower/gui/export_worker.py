from __future__ import annotations

import traceback
from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, Signal, Slot

from cooling_tower.preview import (
    PreviewCancelled,
    PreviewExportService,
    PreviewRequest,
    PreviewResult,
    PreviewService,
)


class ExportWorker(QObject):
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
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.preview = preview
        self.request = request
        self.output_root = output_root
        self.export_service = export_service
        self.preview_service = preview_service
        self.cancellation_event = Event()

    def cancel(self) -> None:
        self.cancellation_event.set()

    @Slot()
    def run(self) -> None:
        generated_preview: PreviewResult | None = None
        try:
            preview = self.preview
            if preview is None:
                generated_preview = self.preview_service.prepare(
                    self.request,
                    cancellation_event=self.cancellation_event,
                    progress_callback=lambda percent, status: self.progress.emit(
                        self.request_id, percent, status
                    ),
                )
                preview = generated_preview
            else:
                self.progress.emit(
                    self.request_id,
                    75,
                    "Aktuelle Vorschau wird für den Export übernommen …",
                )
            if self.cancellation_event.is_set():
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
            self.finished.emit(self.request_id)
