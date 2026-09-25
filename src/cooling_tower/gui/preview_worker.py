from __future__ import annotations

import traceback
import re
from threading import Event

from PySide6.QtCore import Signal, Slot

from cooling_tower.diagnostic_events import (
    DIAGNOSTIC_EVENT_SCHEMA_VERSION,
    exception_error_code,
)
from cooling_tower.gui.worker_contract import CancelableWorker
from cooling_tower.preview import PreviewCancelled, PreviewRequest, PreviewService
from cooling_tower.gui.preview_controller import PreviewBuildController


class PreviewWorker(CancelableWorker):
    progress = Signal(int, int, str)
    succeeded = Signal(int, object)
    failed = Signal(int, str, str)
    finished = Signal(int)
    joint_phase_started = Signal(int, int, int)
    joint_progress = Signal(int, object)
    joint_scene = Signal(int, object)

    def __init__(
        self,
        request_id: int,
        request: PreviewRequest,
        service: PreviewService,
        seed_preview: object | None = None,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.request = request
        self.service = service
        self.seed_preview = seed_preview
        self.accept_best_event = Event()
        self._last_joint_started = 0

    @Slot()
    def accept_current(self) -> None:
        """Stop safely and retain the best fully evaluated joint candidate."""

        self.accept_best_event.set()

    @Slot()
    def run(self) -> None:
        with self.diagnostic_scope():
            self.diagnose(
                "preview_generation_started",
                diagnostic_event_schema_version=(
                    DIAGNOSTIC_EVENT_SCHEMA_VERSION
                ),
                output_mode=self.request.output_mode.value,
                calibration_mode=self.request.calibration_config.mode.value,
                configured_iteration_count=(
                    self.request.calibration_config.maximum_iterations
                ),
                slicer_available=self.request.adapter is not None,
                effective_profile_available=(
                    self.request.effective_profile is not None
                ),
            )
            self.diagnose("preview_request_accepted")
            controller = PreviewBuildController(self.service, self)
            try:
                result = controller.execute(
                    self.request,
                    cancellation_event=self.cancellation_event,
                    accept_best_event=self.accept_best_event,
                    progress_callback=self._report_progress,
                    joint_progress_callback=self._report_joint_progress,
                    joint_scene_callback=self._report_joint_scene,
                    seed_preview=self.seed_preview,
                )
            except PreviewCancelled:
                self._diagnose_cancelled("during_generation")
                self.diagnose("preview_result_discarded", reason="cancelled")
            except Exception as error:
                if not self.cancellation_requested():
                    self.diagnose(
                        "preview_generation_failed",
                        diagnostic_event_schema_version=(
                            DIAGNOSTIC_EVENT_SCHEMA_VERSION
                        ),
                        outcome="failed",
                        error_code=exception_error_code(
                            "preview_generation",
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
                    self._diagnose_cancelled("during_generation")
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
                    calibration = getattr(result, "calibration", None)
                    failure_codes = (
                        sorted(
                            {
                                getattr(
                                    getattr(failure, "code", None),
                                    "value",
                                    "unknown",
                                )
                                for failure in getattr(
                                    calibration,
                                    "failures",
                                    (),
                                )
                            }
                        )
                        if calibration is not None
                        else []
                    )
                    self.diagnose(
                        "preview_generation_finished",
                        diagnostic_event_schema_version=(
                            DIAGNOSTIC_EVENT_SCHEMA_VERSION
                        ),
                        outcome="success",
                        result_code="preview_generation_succeeded",
                        output_mode=getattr(
                            getattr(
                                result,
                                "output_mode",
                                self.request.output_mode,
                            ),
                            "value",
                            "unknown",
                        ),
                        calibrated=bool(
                            getattr(result, "calibrated", False)
                        ),
                        generation_kind=str(
                            getattr(result, "generation_kind", "unknown")
                        ),
                        slicer_optimized=bool(
                            getattr(result, "slicer_optimized", False)
                        ),
                        displayed_segment_count=(
                            getattr(
                                getattr(result, "scene", None),
                                "displayed_segment_count",
                                None,
                            )
                        ),
                        source_segment_count=(
                            getattr(
                                getattr(result, "scene", None),
                                "source_segment_count",
                                None,
                            )
                        ),
                        warning_count=len(getattr(result, "warnings", ())),
                        calibration_state=(
                            getattr(
                                getattr(calibration, "state", None),
                                "value",
                                "unknown",
                            )
                            if calibration is not None
                            else "not_used"
                        ),
                        calibration_iteration_count=(
                            len(getattr(calibration, "iterations", ()))
                            if calibration is not None
                            else 0
                        ),
                        calibration_failure_codes=failure_codes,
                    )
                    self.diagnose("preview_result_accepted")
                    self.succeeded.emit(self.request_id, result)
                else:
                    self._diagnose_cancelled("after_generation")
                    self.diagnose("preview_result_discarded", reason="stale")
                    result.dispose()
                    self.diagnose("temporary_data_cleaned")
            finally:
                self.finished.emit(self.request_id)

    def _diagnose_cancelled(self, phase: str) -> None:
        self.diagnose(
            "preview_generation_cancelled",
            diagnostic_event_schema_version=DIAGNOSTIC_EVENT_SCHEMA_VERSION,
            outcome="cancelled",
            result_code="preview_generation_cancelled",
            cancellation_phase=phase,
        )

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
        match = re.search(
            r"Gemeinsamer Slice\s+(\d+)\s*/\s*(\d+)",
            status,
            re.IGNORECASE,
        )
        if match is not None:
            current = int(match.group(1))
            maximum = int(match.group(2))
            if current != self._last_joint_started:
                self._last_joint_started = current
                self.joint_phase_started.emit(
                    self.request_id,
                    current - 1,
                    maximum,
                )

    def _report_joint_progress(self, progress: object) -> None:
        self.joint_progress.emit(self.request_id, progress)

    def _report_joint_scene(self, scene: object) -> None:
        self.joint_scene.emit(self.request_id, scene)
