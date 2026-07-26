from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot

from cooling_tower.services import AnalysisCancelled, GCodeAnalysisService


class AnalysisWorker(QObject):
    """Cancelable background worker for one versioned G-code analysis."""

    progress = Signal(int, int, str)
    succeeded = Signal(int, object)
    failed = Signal(int, str, str)
    finished = Signal(int)

    def __init__(
        self,
        request_id: int,
        gcode_path: Path,
        analysis_service: GCodeAnalysisService,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.gcode_path = gcode_path
        self.analysis_service = analysis_service

    @Slot()
    def run(self) -> None:
        thread = QThread.currentThread()
        try:
            snapshot = self.analysis_service.analyze(
                self.gcode_path,
                progress_callback=lambda percent, status: self.progress.emit(
                    self.request_id,
                    percent,
                    status,
                ),
                cancellation_callback=thread.isInterruptionRequested,
            )
        except AnalysisCancelled:
            pass
        except Exception as error:  # GUI boundary: preserve traceback in logs
            self.failed.emit(
                self.request_id,
                str(error),
                traceback.format_exc(),
            )
        else:
            if not thread.isInterruptionRequested():
                self.succeeded.emit(self.request_id, snapshot)
        finally:
            self.finished.emit(self.request_id)
