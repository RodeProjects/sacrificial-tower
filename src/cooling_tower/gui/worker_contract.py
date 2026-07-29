from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from threading import Event
from typing import Any

from PySide6.QtCore import QObject, QThread, Slot

from cooling_tower.diagnostic_context import diagnostic_scope


class CancelableWorker(QObject):
    """Common, idempotent cancellation contract for managed GUI workers."""

    def __init__(self) -> None:
        super().__init__()
        self.cancellation_event = Event()
        self._diagnostic_callback: Callable[..., None] | None = None

    @Slot()
    def cancel(self) -> None:
        """Request cancellation; repeated calls are deliberately harmless."""

        self.cancellation_event.set()

    def cancellation_requested(self) -> bool:
        return bool(
            self.cancellation_event.is_set()
            or QThread.currentThread().isInterruptionRequested()
        )

    def set_diagnostic_callback(
        self,
        callback: Callable[..., None] | None,
    ) -> None:
        self._diagnostic_callback = callback

    def diagnostic_scope(self) -> AbstractContextManager[None]:
        return diagnostic_scope(self._diagnostic_callback)

    def diagnose(self, event: str, **details: Any) -> None:
        callback = self._diagnostic_callback
        if callback is not None:
            callback(event, **details)
