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
)


class ExportWorker(CancelableWorker):
    progress = Signal(int, int, str)
    succeeded = Signal(int, object)
    failed = Signal(int, str, str)
    finished = Signal(int)

    def __init__(
        self,
        request_id: int,
        preview: PreviewResult,
        request: PreviewRequest,
        output_root: Path,
        export_service: PreviewExportService,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.preview = preview
        self.request = request
        self.output_root = output_root
        self.export_service = export_service

    @Slot()
    def run(self) -> None:
        with self.diagnostic_scope():
            try:
                if self.cancellation_requested():
                    raise PreviewCancelled()
                self.progress.emit(
                    self.request_id,
                    50,
                    "Aktuelle Generierung wird ohne erneute Slicer-Läufe übernommen …",
                )
                self.progress.emit(
                    self.request_id,
                    95,
                    "STL-Datei und Berichte werden gespeichert …",
                )
                result = self.export_service.export(
                    self.preview,
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
                self.finished.emit(self.request_id)
