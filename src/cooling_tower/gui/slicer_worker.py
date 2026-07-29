from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import Signal, Slot

from cooling_tower.gui.worker_contract import CancelableWorker
from cooling_tower.models.gcode_metadata import SlicerIdentity
from cooling_tower.slicers.service import SlicerDiscoveryService


class SlicerDiscoveryWorker(CancelableWorker):
    succeeded = Signal(int, object)
    failed = Signal(int, str, str)
    finished = Signal(int)

    def __init__(
        self,
        request_id: int,
        service: SlicerDiscoveryService,
        source_slicer: SlicerIdentity | None,
        *,
        force: bool = False,
        manual_path: Path | None = None,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.service = service
        self.source_slicer = source_slicer
        self.force = force
        self.manual_path = manual_path

    @Slot()
    def run(self) -> None:
        with self.diagnostic_scope():
            try:
                if self.cancellation_requested():
                    return
                if self.manual_path is not None:
                    result = self.service.add_manual_installation(
                        self.manual_path,
                        self.source_slicer,
                    )
                else:
                    result = self.service.discover_installations(
                        self.source_slicer,
                        force=self.force,
                    )
                if not self.cancellation_requested():
                    self.succeeded.emit(self.request_id, result)
            except Exception as error:  # converted to a user-facing GUI state
                if not self.cancellation_requested():
                    self.failed.emit(
                        self.request_id,
                        str(error),
                        traceback.format_exc(),
                    )
            finally:
                self.finished.emit(self.request_id)
