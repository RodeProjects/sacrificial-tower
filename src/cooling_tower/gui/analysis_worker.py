from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import Signal, Slot

from cooling_tower.diagnostic_events import (
    DIAGNOSTIC_EVENT_SCHEMA_VERSION,
    exception_error_code,
)
from cooling_tower.gui.worker_contract import CancelableWorker
from cooling_tower.services import AnalysisCancelled, GCodeAnalysisService


class AnalysisWorker(CancelableWorker):
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
        with self.diagnostic_scope():
            self.diagnose(
                "gcode_analysis_started",
                diagnostic_event_schema_version=(
                    DIAGNOSTIC_EVENT_SCHEMA_VERSION
                ),
                source_file_available=self.gcode_path.is_file(),
            )
            try:
                snapshot = self.analysis_service.analyze(
                    self.gcode_path,
                    progress_callback=lambda percent, status: self.progress.emit(
                        self.request_id,
                        percent,
                        status,
                    ),
                    cancellation_callback=self.cancellation_requested,
                )
            except AnalysisCancelled:
                self._diagnose_cancelled("during_analysis")
            except Exception as error:  # GUI boundary: preserve traceback in logs
                if not self.cancellation_requested():
                    self.diagnose(
                        "gcode_analysis_failed",
                        diagnostic_event_schema_version=(
                            DIAGNOSTIC_EVENT_SCHEMA_VERSION
                        ),
                        outcome="failed",
                        error_code=exception_error_code(
                            "gcode_analysis",
                            error,
                        ),
                        error_type=type(error).__name__,
                    )
                    self.failed.emit(
                        self.request_id,
                        str(error),
                        traceback.format_exc(),
                    )
                else:
                    self._diagnose_cancelled("during_analysis")
            else:
                if self.cancellation_requested():
                    self._diagnose_cancelled("after_analysis")
                else:
                    slicer = getattr(snapshot.metadata, "slicer", None)
                    self.diagnose(
                        "gcode_analysis_finished",
                        diagnostic_event_schema_version=(
                            DIAGNOSTIC_EVENT_SCHEMA_VERSION
                        ),
                        outcome="success",
                        result_code="gcode_analysis_succeeded",
                        layer_count=snapshot.layer_count,
                        file_size_bytes=snapshot.file_size_bytes,
                        metadata_value_count=len(snapshot.metadata.values),
                        typed_config_value_count=len(
                            snapshot.metadata.typed_config
                        ),
                        source_slicer_available=bool(
                            getattr(slicer, "product_name", None)
                            or getattr(slicer, "adapter_id", None)
                        ),
                        timing_confidence=getattr(
                            getattr(
                                snapshot.timing_evidence,
                                "confidence_state",
                                None,
                            ),
                            "value",
                            "unknown",
                        ),
                    )
                    self.succeeded.emit(self.request_id, snapshot)
            finally:
                self.finished.emit(self.request_id)

    def _diagnose_cancelled(self, phase: str) -> None:
        self.diagnose(
            "gcode_analysis_cancelled",
            diagnostic_event_schema_version=DIAGNOSTIC_EVENT_SCHEMA_VERSION,
            outcome="cancelled",
            result_code="gcode_analysis_cancelled",
            cancellation_phase=phase,
        )
