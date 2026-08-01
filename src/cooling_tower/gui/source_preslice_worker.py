from __future__ import annotations

import traceback

from PySide6.QtCore import Signal, Slot

from cooling_tower.gui.worker_contract import CancelableWorker
from cooling_tower.services import (
    SourcePreSliceCancelled,
    SourcePreSliceService,
)
from cooling_tower.slicers import (
    ProfileConfirmation,
    ProfileMatchResult,
    SlicerAdapter,
)
from cooling_tower.services import StlValidationResult


class SourcePreSliceWorker(CancelableWorker):
    """Run the confirmed STL pre-slice without blocking the GUI thread."""

    progress = Signal(int, int, str, bool)
    succeeded = Signal(int, object)
    failed = Signal(int, str, str)
    cancelled = Signal(int)
    finished = Signal(int)

    def __init__(
        self,
        request_id: int,
        service: SourcePreSliceService,
        stl_validation: StlValidationResult,
        profile_match: ProfileMatchResult,
        confirmation: ProfileConfirmation,
        adapter: SlicerAdapter,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.service = service
        self.stl_validation = stl_validation
        self.profile_match = profile_match
        self.confirmation = confirmation
        self.adapter = adapter

    @Slot()
    def run(self) -> None:
        with self.diagnostic_scope():
            self.diagnose(
                "source_preslice_started",
                source_kind="stl",
                slicer_adapter=self.adapter.adapter_id,
            )
            try:
                result = self.service.run(
                    stl_validation=self.stl_validation,
                    profile_match=self.profile_match,
                    confirmation=self.confirmation,
                    adapter=self.adapter,
                    cancellation_event=self.cancellation_event,
                    progress_callback=lambda percent, status, busy: (
                        self.progress.emit(
                            self.request_id,
                            percent,
                            status,
                            busy,
                        )
                    ),
                )
            except SourcePreSliceCancelled:
                self.diagnose(
                    "source_preslice_cancelled",
                    outcome="cancelled",
                )
                self.cancelled.emit(self.request_id)
            except Exception as error:
                if not self.cancellation_requested():
                    self.diagnose(
                        "source_preslice_failed",
                        outcome="failed",
                        error_type=type(error).__name__,
                    )
                    self.failed.emit(
                        self.request_id,
                        str(error),
                        "\n\n".join(
                            item
                            for item in (
                                getattr(error, "technical_details", None),
                                traceback.format_exc(),
                            )
                            if item
                        ),
                    )
            else:
                if self.cancellation_requested():
                    result.cleanup()
                    self.diagnose(
                        "source_preslice_cancelled",
                        outcome="cancelled",
                    )
                    self.cancelled.emit(self.request_id)
                else:
                    self.diagnose(
                        "source_preslice_finished",
                        outcome="success",
                        layer_count=result.analysis_snapshot.layer_count,
                        metadata_verified=result.metadata_verified,
                        cache_hit=result.cache_hit,
                    )
                    self.succeeded.emit(self.request_id, result)
            finally:
                self.finished.emit(self.request_id)
