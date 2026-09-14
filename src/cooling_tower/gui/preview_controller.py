from __future__ import annotations

from enum import Enum
from threading import Event
from typing import Callable

from PySide6.QtCore import QObject, QThread, Signal

from cooling_tower.diagnostic_context import record_diagnostic
from cooling_tower.preview.models import PreviewRequest, PreviewResult
from cooling_tower.preview.toolpath import PreviewCancelled
from cooling_tower.preview.service import PreviewService


class PreviewBuildState(str, Enum):
    IDLE = "idle"
    PREPARING = "preparing"
    CALIBRATION_PREPARING = "calibration_preparing"
    SLICER_RUNNING = "slicer_running"
    EVALUATING = "evaluating"
    FINALIZING = "finalizing"
    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"
    FAILED = "failed"


class PreviewBuildController(QObject):
    """Audit the preview pipeline as an explicit worker-thread state machine.

    External slicers remain asynchronous QProcess operations internally.  This
    controller does not report completion until the runner has observed final
    process termination, drained both channels and released its resources.
    """

    state_changed = Signal(object, object)

    def __init__(self, service: PreviewService, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.state = PreviewBuildState.IDLE
        self._owner_thread = QThread.currentThread()

    def execute(
        self,
        request: PreviewRequest,
        *,
        cancellation_event: Event,
        progress_callback: Callable[[int, str], None],
        seed_preview: PreviewResult | None = None,
    ) -> PreviewResult:
        self._assert_owner_thread()
        self._transition(PreviewBuildState.PREPARING)
        try:
            progress = lambda percent, status: self._on_progress(
                percent,
                status,
                progress_callback,
            )
            if seed_preview is None:
                result = self.service.prepare(
                    request,
                    cancellation_event=cancellation_event,
                    progress_callback=progress,
                )
            else:
                result = self.service.prepare(
                    request,
                    cancellation_event=cancellation_event,
                    progress_callback=progress,
                    seed_preview=seed_preview,
                )
        except PreviewCancelled:
            self._transition(PreviewBuildState.CANCELLED)
            raise
        except Exception:
            self._transition(PreviewBuildState.FAILED)
            raise
        self._transition(PreviewBuildState.SUCCEEDED)
        return result

    def _on_progress(
        self,
        percent: int,
        status: str,
        callback: Callable[[int, str], None],
    ) -> None:
        self._assert_owner_thread()
        normalized = status.casefold()
        if (
            "slicer-auftrag" in normalized
            or "gemeinsamer slice" in normalized
            or "kühlturm-slice" in normalized
        ):
            target = PreviewBuildState.SLICER_RUNNING
        elif "slicer-ergebnis" in normalized:
            target = PreviewBuildState.EVALUATING
        elif "kalibrier" in normalized and "vorbereit" in normalized:
            target = PreviewBuildState.CALIBRATION_PREPARING
        elif percent >= 90:
            target = PreviewBuildState.FINALIZING
        else:
            target = self.state
        if target is not self.state:
            self._transition(target)
        callback(percent, status)

    def _transition(self, target: PreviewBuildState) -> None:
        previous = self.state
        if target is previous:
            return
        self.state = target
        record_diagnostic(
            "preview_build_state_changed",
            previous_state=previous.value,
            new_state=target.value,
        )
        self.state_changed.emit(previous, target)

    def _assert_owner_thread(self) -> None:
        if QThread.currentThread() is not self._owner_thread:
            raise RuntimeError("PreviewBuildController crossed its owning Qt thread.")
