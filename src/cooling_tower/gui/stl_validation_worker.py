from __future__ import annotations

from pathlib import Path
import traceback

from PySide6.QtCore import Signal, Slot

from cooling_tower.gui.worker_contract import CancelableWorker
from cooling_tower.services import StlValidationCancelled, StlValidationService


class StlValidationWorker(CancelableWorker):
    """Cancelable background worker for strict validation of one STL."""

    progress = Signal(int, int, str)
    succeeded = Signal(int, object)
    failed = Signal(int, str, str)
    finished = Signal(int)

    def __init__(
        self,
        request_id: int,
        stl_path: Path,
        service: StlValidationService,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.stl_path = stl_path
        self.service = service

    @Slot()
    def run(self) -> None:
        with self.diagnostic_scope():
            self.diagnose("stl_validation_started", source_file_available=True)
            try:
                result = self.service.validate(
                    self.stl_path,
                    progress_callback=lambda percent, status: self.progress.emit(
                        self.request_id, percent, status
                    ),
                    cancellation_callback=self.cancellation_requested,
                )
            except StlValidationCancelled:
                self.diagnose(
                    "stl_validation_cancelled",
                    outcome="cancelled",
                )
            except Exception as error:
                if not self.cancellation_requested():
                    self.diagnose(
                        "stl_validation_failed",
                        outcome="failed",
                        error_type=type(error).__name__,
                    )
                    self.failed.emit(
                        self.request_id,
                        str(error),
                        traceback.format_exc(),
                    )
            else:
                if not self.cancellation_requested():
                    self.diagnose(
                        "stl_validation_finished",
                        outcome="valid" if result.valid else "invalid",
                        face_count=result.face_count,
                        component_count=result.component_count,
                        issue_count=len(result.issues),
                    )
                    self.succeeded.emit(self.request_id, result)
            finally:
                self.finished.emit(self.request_id)
