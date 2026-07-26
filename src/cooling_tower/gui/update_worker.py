from __future__ import annotations

import traceback
from threading import Event

from PySide6.QtCore import QObject, Signal, Slot

from cooling_tower.update import UpdateCancelled, UpdateService


class UpdateCheckWorker(QObject):
    succeeded = Signal(int, object)
    failed = Signal(int, str, str)
    finished = Signal(int)

    def __init__(
        self,
        request_id: int,
        current_version: str,
        update_service: UpdateService,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.current_version = current_version
        self.update_service = update_service

    @Slot()
    def run(self) -> None:
        try:
            result = self.update_service.check_for_update(self.current_version)
        except Exception as error:
            self.failed.emit(self.request_id, str(error), traceback.format_exc())
        else:
            self.succeeded.emit(self.request_id, result)
        finally:
            self.finished.emit(self.request_id)


class UpdateDownloadWorker(QObject):
    progress = Signal(int, int)
    succeeded = Signal(int, object)
    failed = Signal(int, str, str)
    finished = Signal(int)

    def __init__(
        self,
        request_id: int,
        update_info,
        update_service: UpdateService,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.update_info = update_info
        self.update_service = update_service
        self.cancellation_event = Event()

    def cancel(self) -> None:
        self.cancellation_event.set()

    @Slot()
    def run(self) -> None:
        try:
            installer = self.update_service.download_installer(
                self.update_info,
                progress_callback=lambda percent: self.progress.emit(
                    self.request_id, percent
                ),
                cancellation_event=self.cancellation_event,
            )
        except UpdateCancelled:
            pass
        except Exception as error:
            self.failed.emit(self.request_id, str(error), traceback.format_exc())
        else:
            self.succeeded.emit(self.request_id, installer)
        finally:
            self.finished.emit(self.request_id)
