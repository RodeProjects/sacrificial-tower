"""Cancelable background preparation of source-bound drag guidance."""
import traceback
from threading import Condition

from PySide6.QtCore import Signal, Slot

from cooling_tower.gui.worker_contract import CancelableWorker
from cooling_tower.preprocessor_regions import PositionRegionMap  # canvas compatibility
from cooling_tower.preview.toolpath import PreviewCancelled


class PositionRegionWorker(CancelableWorker):
    updated = Signal(int, object)
    failed = Signal(int, str, str)
    finished = Signal(int)

    def __init__(self, request_id, context, settings, kind=None):
        super().__init__()
        self.request_id, self.context, self.settings, self.kind = request_id, context, settings, kind

    @Slot()
    def run(self):
        try:
            kinds = (self.kind,) if self.kind else ("tower", "wait")
            maps = {kind: self.context.regions.regions(kind, self.settings, event=self.cancellation_event) for kind in kinds}
            if not self.cancellation_requested():
                self.updated.emit(self.request_id, maps[self.kind] if self.kind else maps)
        except PreviewCancelled:
            pass
        except Exception as error:
            if not self.cancellation_requested():
                self.failed.emit(self.request_id, str(error), traceback.format_exc())
        finally:
            self.finished.emit(self.request_id)


class PositionDragWorker(CancelableWorker):
    """One worker per gesture; only the latest mouse coordinate needs checking."""
    checked = Signal(int, object, bool)
    failed = Signal(int, str, str)
    finished = Signal(int)

    def __init__(self, request_id, context, settings, kind):
        super().__init__()
        self.request_id, self.context, self.settings, self.kind = request_id, context, settings, kind
        self._condition, self._latest = Condition(), None

    def request(self, point):
        with self._condition:
            self._latest = point
            self._condition.notify()

    @Slot()
    def cancel(self):
        super().cancel()
        with self._condition:
            self._condition.notify()

    @Slot()
    def run(self):
        try:
            while not self.cancellation_requested():
                with self._condition:
                    self._condition.wait_for(lambda: self._latest is not None or self.cancellation_event.is_set())
                    if self.cancellation_requested():
                        break
                    point, self._latest = self._latest, None
                valid = self.context.position_valid(self.kind, point, self.settings, event=self.cancellation_event)
                if not self.cancellation_requested():
                    self.checked.emit(self.request_id, point, valid)
        except PreviewCancelled:
            pass
        except Exception as error:
            if not self.cancellation_requested():
                self.failed.emit(self.request_id, str(error), traceback.format_exc())
        finally:
            self.finished.emit(self.request_id)
