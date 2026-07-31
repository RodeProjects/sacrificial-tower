from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import Signal, Slot

from cooling_tower.diagnostic_events import (
    DIAGNOSTIC_EVENT_SCHEMA_VERSION,
    exception_error_code,
)
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
            self.diagnose(
                "slicer_discovery_started",
                diagnostic_event_schema_version=(
                    DIAGNOSTIC_EVENT_SCHEMA_VERSION
                ),
                manual_selection=self.manual_path is not None,
                forced_refresh=self.force,
                source_slicer_available=self.source_slicer is not None,
            )
            try:
                if self.cancellation_requested():
                    self._diagnose_cancelled("before_discovery")
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
                if self.cancellation_requested():
                    self._diagnose_cancelled("after_discovery")
                    return
                installations = tuple(
                    getattr(result, "installations", ())
                )
                verified = tuple(
                    item
                    for item in installations
                    if bool(getattr(item, "verified", False))
                )
                gui_state = getattr(
                    getattr(result, "gui_state", None),
                    "value",
                    "unknown",
                )
                self.diagnose(
                    "slicer_discovery_finished",
                    diagnostic_event_schema_version=(
                        DIAGNOSTIC_EVENT_SCHEMA_VERSION
                    ),
                    outcome="success",
                    result_code=f"slicer_{gui_state}",
                    gui_state=gui_state,
                    installation_count=len(installations),
                    verified_installation_count=len(verified),
                    slice_capable_installation_count=sum(
                        1
                        for item in verified
                        if bool(getattr(item, "can_slice", False))
                    ),
                    diagnostic_count=len(
                        getattr(result, "diagnostics", ())
                    ),
                    recommendation_available=(
                        getattr(result, "recommended", None) is not None
                    ),
                )
                self.succeeded.emit(self.request_id, result)
            except Exception as error:  # converted to a user-facing GUI state
                if not self.cancellation_requested():
                    self.diagnose(
                        "slicer_discovery_failed",
                        diagnostic_event_schema_version=(
                            DIAGNOSTIC_EVENT_SCHEMA_VERSION
                        ),
                        outcome="failed",
                        error_code=exception_error_code(
                            "slicer_discovery",
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
                    self._diagnose_cancelled("during_discovery")
            finally:
                self.finished.emit(self.request_id)

    def _diagnose_cancelled(self, phase: str) -> None:
        self.diagnose(
            "slicer_discovery_cancelled",
            diagnostic_event_schema_version=DIAGNOSTIC_EVENT_SCHEMA_VERSION,
            outcome="cancelled",
            result_code="slicer_discovery_cancelled",
            cancellation_phase=phase,
        )
