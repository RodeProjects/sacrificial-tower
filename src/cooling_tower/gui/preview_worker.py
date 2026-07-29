from __future__ import annotations

import traceback

from PySide6.QtCore import Signal, Slot

from cooling_tower.gui.worker_contract import CancelableWorker
from cooling_tower.preview import PreviewCancelled, PreviewRequest, PreviewService


class PreviewWorker(CancelableWorker):
    progress = Signal(int, int, str)
    succeeded = Signal(int, object)
    failed = Signal(int, str, str)
    finished = Signal(int)

    def __init__(
        self,
        request_id: int,
        request: PreviewRequest,
        service: PreviewService,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.request = request
        self.service = service

    @Slot()
    def run(self) -> None:
        with self.diagnostic_scope():
            self.diagnose("preview_request_accepted")
            try:
                result = self.service.prepare(
                    self.request,
                    cancellation_event=self.cancellation_event,
                    progress_callback=self._report_progress,
                )
            except PreviewCancelled:
                self.diagnose("preview_result_discarded", reason="cancelled")
            except Exception as error:
                if not self.cancellation_requested():
                    self.failed.emit(
                        self.request_id,
                        str(error),
                        traceback.format_exc(),
                    )
                self.diagnose(
                    "preview_result_discarded",
                    reason=(
                        "cancelled"
                        if self.cancellation_requested()
                        else "failed"
                    ),
                )
            else:
                if not self.cancellation_requested():
                    self.diagnose("preview_result_accepted")
                    self.succeeded.emit(self.request_id, result)
                else:
                    self.diagnose("preview_result_discarded", reason="stale")
                    result.dispose()
                    self.diagnose("temporary_data_cleaned")
            finally:
                self.finished.emit(self.request_id)

    def _report_progress(self, percent: int, status: str) -> None:
        normalized = status.casefold()
        if "geometrie" in normalized and (
            "erstellt" in normalized or "berechnet" in normalized
        ):
            self.diagnose("geometry_created", status=status)
        self.diagnose(
            "preview_progress",
            progress_percent=max(0, min(100, int(percent))),
            status=status,
        )
        self.progress.emit(self.request_id, percent, status)
