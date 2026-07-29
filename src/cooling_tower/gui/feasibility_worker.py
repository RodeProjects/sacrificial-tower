from __future__ import annotations

import traceback

from PySide6.QtCore import Signal, Slot

from cooling_tower.gui.worker_contract import CancelableWorker
from cooling_tower.models import (
    GCodeAnalysisSnapshot,
    GenerationSettings,
    TowerNeedAssessment,
)
from cooling_tower.services import (
    FeasibilityCancelled,
    assess_profile_feasibility,
)


class FeasibilityWorker(CancelableWorker):
    """Cancelable worker for one debounced, output-free profile check."""

    succeeded = Signal(int, object)
    failed = Signal(int, str, str)
    finished = Signal(int)

    def __init__(
        self,
        request_id: int,
        snapshot: GCodeAnalysisSnapshot,
        settings: GenerationSettings,
        assessment: TowerNeedAssessment,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.snapshot = snapshot
        self.settings = settings
        self.assessment = assessment

    @Slot()
    def run(self) -> None:
        with self.diagnostic_scope():
            try:
                result = assess_profile_feasibility(
                    self.snapshot,
                    self.settings,
                    self.assessment,
                    cancellation_callback=self.cancellation_requested,
                )
            except FeasibilityCancelled:
                pass
            except Exception as error:
                if not self.cancellation_requested():
                    self.failed.emit(
                        self.request_id,
                        str(error),
                        traceback.format_exc(),
                    )
            else:
                if not self.cancellation_requested():
                    self.succeeded.emit(self.request_id, result)
            finally:
                self.finished.emit(self.request_id)
