from __future__ import annotations

import traceback
from threading import Event

from PySide6.QtCore import QObject, Signal, Slot

from cooling_tower.preview import PreviewCancelled, PreviewRequest, PreviewService


class PreviewWorker(QObject):
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
        self.cancellation_event = Event()

    def cancel(self) -> None:
        self.cancellation_event.set()

    @Slot()
    def run(self) -> None:
        try:
            result = self.service.prepare(
                self.request,
                cancellation_event=self.cancellation_event,
                progress_callback=lambda percent, status: self.progress.emit(
                    self.request_id, percent, status
                ),
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
            if not self.cancellation_event.is_set():
                self.succeeded.emit(self.request_id, result)
            else:
                result.dispose()
        finally:
            self.finished.emit(self.request_id)
