"""Method-scoped managed workers for reference preparation and fixed slicing."""
import traceback
from PySide6.QtCore import Signal, Slot
from cooling_tower.gui.worker_contract import CancelableWorker
from cooling_tower.preview import PreviewCancelled


class ManualWorker(CancelableWorker):
    progress = Signal(int, int, str)
    succeeded = Signal(int, object)
    failed = Signal(int, str, str)
    finished = Signal(int)

    def __init__(self, request_id, request, service, *, reference=False):
        super().__init__()
        self.request_id, self.request, self.service, self.reference = request_id, request, service, reference

    @Slot()
    def run(self):
        with self.diagnostic_scope():
            try:
                method = self.service.prepare_reference if self.reference else self.service.prepare
                result = method(self.request, cancellation_event=self.cancellation_event,
                                progress_callback=lambda p, s: self.progress.emit(self.request_id, p, s))
            except PreviewCancelled:
                pass
            except Exception as error:
                if not self.cancellation_requested():
                    self.failed.emit(self.request_id, str(error), traceback.format_exc())
            else:
                if self.cancellation_requested():
                    if callable(getattr(result, "dispose", None)):
                        result.dispose()
                else:
                    self.succeeded.emit(self.request_id, result)
            finally:
                self.finished.emit(self.request_id)
