from __future__ import annotations

import traceback
from typing import Mapping

from PySide6.QtCore import Signal, Slot

from cooling_tower.gui.worker_contract import CancelableWorker
from cooling_tower.models import GCodeAnalysisSnapshot
from cooling_tower.slicers import (
    ProfileMatchResult,
    ProfileMatchingService,
    SlicerAdapter,
    SlicerInstallation,
)


class ProfileMatchingWorker(CancelableWorker):
    """Resolve and validate slicer profiles without blocking the GUI."""

    succeeded = Signal(int, object)
    unchanged = Signal(int)
    failed = Signal(int, str, str)
    finished = Signal(int)

    def __init__(
        self,
        request_id: int,
        service: ProfileMatchingService,
        snapshot: GCodeAnalysisSnapshot,
        installation: SlicerInstallation,
        adapter: SlicerAdapter,
        *,
        selected_profile_ids: Mapping[str, str] | None = None,
        force_inventory: bool = False,
        include_all_profiles: bool = False,
        stale_check_result: ProfileMatchResult | None = None,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.service = service
        self.snapshot = snapshot
        self.installation = installation
        self.adapter = adapter
        self.selected_profile_ids = dict(selected_profile_ids or {})
        self.force_inventory = force_inventory
        self.include_all_profiles = include_all_profiles
        self.stale_check_result = stale_check_result

    @Slot()
    def run(self) -> None:
        with self.diagnostic_scope():
            try:
                if self.cancellation_requested():
                    return
                if (
                    self.stale_check_result is not None
                    and not self.service.inventory_is_stale(self.stale_check_result)
                ):
                    if not self.cancellation_requested():
                        self.unchanged.emit(self.request_id)
                    return
                result = self.service.match(
                    self.snapshot,
                    self.installation,
                    self.adapter,
                    selected_profile_ids=self.selected_profile_ids,
                    force_inventory=(
                        self.force_inventory or self.stale_check_result is not None
                    ),
                    include_all_profiles=self.include_all_profiles,
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
