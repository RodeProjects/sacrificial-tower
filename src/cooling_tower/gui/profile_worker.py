from __future__ import annotations

import inspect
import traceback
from typing import Mapping

from PySide6.QtCore import Signal, Slot

from cooling_tower.diagnostic_events import (
    DIAGNOSTIC_EVENT_SCHEMA_VERSION,
    exception_error_code,
)
from cooling_tower.gui.worker_contract import CancelableWorker
from cooling_tower.models import GCodeAnalysisSnapshot
from cooling_tower.slicers import (
    ProfileCatalog,
    ProfileMatchingContext,
    ProfileMatchResult,
    ProfileMatchingService,
    ProfileSelectionReference,
    SlicerAdapter,
    SlicerInstallation,
)


class ProfileCatalogWorker(CancelableWorker):
    """Inventory selectable profiles before a source file exists."""

    succeeded = Signal(int, object)
    failed = Signal(int, str, str)
    finished = Signal(int)

    def __init__(
        self,
        request_id: int,
        service: ProfileMatchingService,
        installation: SlicerInstallation,
        adapter: SlicerAdapter,
        *,
        force_inventory: bool = False,
        selected_machine: str | ProfileSelectionReference | None = None,
        selected_profile_ids: Mapping[
            str, str | ProfileSelectionReference
        ] | None = None,
        include_all_profiles: bool = False,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.service = service
        self.installation = installation
        self.adapter = adapter
        self.force_inventory = force_inventory
        self.selected_machine = selected_machine
        self.selected_profile_ids = dict(selected_profile_ids or {})
        self.include_all_profiles = include_all_profiles

    @Slot()
    def run(self) -> None:
        with self.diagnostic_scope():
            self.diagnose(
                "profile_catalog_started",
                diagnostic_event_schema_version=DIAGNOSTIC_EVENT_SCHEMA_VERSION,
                forced_inventory=self.force_inventory,
            )
            try:
                if self.cancellation_requested():
                    return
                catalog_method = self.service.catalog
                parameters = inspect.signature(catalog_method).parameters
                optional_filter_arguments = {}
                if "selected_machine" in parameters:
                    optional_filter_arguments["selected_machine"] = (
                        self.selected_machine
                    )
                if "selected_profile_ids" in parameters:
                    optional_filter_arguments["selected_profile_ids"] = (
                        self.selected_profile_ids
                    )
                if "include_all_profiles" in parameters:
                    optional_filter_arguments["include_all_profiles"] = (
                        self.include_all_profiles
                    )
                catalog: ProfileCatalog = catalog_method(
                    self.installation,
                    self.adapter,
                    force_inventory=self.force_inventory,
                    **optional_filter_arguments,
                )
                if self.cancellation_requested():
                    return
                self.diagnose(
                    "profile_catalog_finished",
                    diagnostic_event_schema_version=DIAGNOSTIC_EVENT_SCHEMA_VERSION,
                    outcome="success",
                    machine_profile_count=len(catalog.machine_options),
                    process_profile_count=len(catalog.process_options),
                    filament_profile_count=len(catalog.filament_options),
                    rejected_profile_count=catalog.rejected_profile_count,
                    catalog_complete=catalog.complete,
                )
                self.succeeded.emit(self.request_id, catalog)
            except Exception as error:
                if not self.cancellation_requested():
                    self.diagnose(
                        "profile_catalog_failed",
                        diagnostic_event_schema_version=(
                            DIAGNOSTIC_EVENT_SCHEMA_VERSION
                        ),
                        outcome="failed",
                        error_code=exception_error_code(
                            "profile_catalog",
                            error,
                        ),
                        error_type=type(error).__name__,
                    )
                    self.failed.emit(
                        self.request_id,
                        str(error),
                        traceback.format_exc(),
                    )
            finally:
                self.finished.emit(self.request_id)


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
        source: GCodeAnalysisSnapshot | ProfileMatchingContext,
        installation: SlicerInstallation,
        adapter: SlicerAdapter,
        *,
        selected_profile_ids: Mapping[
            str, str | ProfileSelectionReference
        ] | None = None,
        force_inventory: bool = False,
        include_all_profiles: bool = False,
        stale_check_result: ProfileMatchResult | None = None,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.service = service
        self.source = source
        self.snapshot = (
            source.gcode_snapshot
            if isinstance(source, ProfileMatchingContext)
            else source
        )
        self.installation = installation
        self.adapter = adapter
        self.selected_profile_ids = dict(selected_profile_ids or {})
        self.force_inventory = force_inventory
        self.include_all_profiles = include_all_profiles
        self.stale_check_result = stale_check_result

    @Slot()
    def run(self) -> None:
        with self.diagnostic_scope():
            self.diagnose(
                "profile_matching_started",
                diagnostic_event_schema_version=(
                    DIAGNOSTIC_EVENT_SCHEMA_VERSION
                ),
                selected_profile_role_count=len(self.selected_profile_ids),
                forced_inventory=self.force_inventory,
                include_all_profiles=self.include_all_profiles,
                source_kind=(
                    self.source.source_kind.value
                    if isinstance(self.source, ProfileMatchingContext)
                    else "gcode"
                ),
                stale_check=self.stale_check_result is not None,
            )
            try:
                if self.cancellation_requested():
                    self._diagnose_cancelled("before_matching")
                    return
                if (
                    self.stale_check_result is not None
                    and not self.service.inventory_is_stale(self.stale_check_result)
                ):
                    if not self.cancellation_requested():
                        self.diagnose(
                            "profile_matching_finished",
                            diagnostic_event_schema_version=(
                                DIAGNOSTIC_EVENT_SCHEMA_VERSION
                            ),
                            outcome="success",
                            result_code="profile_inventory_unchanged",
                            profile_state=getattr(
                                getattr(
                                    self.stale_check_result,
                                    "state",
                                    None,
                                ),
                                "value",
                                "unknown",
                            ),
                        )
                        self.unchanged.emit(self.request_id)
                    else:
                        self._diagnose_cancelled("during_stale_check")
                    return
                result = self.service.match(
                    self.source,
                    self.installation,
                    self.adapter,
                    selected_profile_ids=self.selected_profile_ids,
                    force_inventory=(
                        self.force_inventory or self.stale_check_result is not None
                    ),
                    include_all_profiles=self.include_all_profiles,
                )
                if self.cancellation_requested():
                    self._diagnose_cancelled("after_matching")
                    return
                selected = getattr(result, "selected", None)
                candidates = tuple(getattr(result, "candidates", ()))
                machine_options = tuple(
                    getattr(result, "machine_options", ())
                )
                process_options = tuple(
                    getattr(result, "process_options", ())
                )
                filament_options = tuple(
                    getattr(result, "filament_options", ())
                )
                profile_state = getattr(
                    getattr(result, "state", None),
                    "value",
                    "unknown",
                )
                exclusion_codes = sorted(
                    {
                        getattr(
                            getattr(exclusion, "code", None),
                            "value",
                            "unknown",
                        )
                        for candidate in candidates
                        for exclusion in getattr(candidate, "exclusions", ())
                    }
                )
                self.diagnose(
                    "profile_matching_finished",
                    diagnostic_event_schema_version=(
                        DIAGNOSTIC_EVENT_SCHEMA_VERSION
                    ),
                    outcome="success",
                    result_code=f"profile_{profile_state}",
                    profile_state=profile_state,
                    candidate_count=len(candidates),
                    machine_profile_count=len(machine_options),
                    process_profile_count=len(process_options),
                    filament_profile_count=len(filament_options),
                    machine_profile_status=self._profile_status(
                        getattr(selected, "machine", None),
                        machine_options,
                    ),
                    process_profile_status=self._profile_status(
                        getattr(selected, "process", None),
                        process_options,
                    ),
                    filament_profile_status=self._profile_status(
                        getattr(selected, "filament", None),
                        filament_options,
                    ),
                    profile_exclusion_codes=exclusion_codes,
                    exclusion_count=sum(
                        len(getattr(candidate, "exclusions", ()))
                        for candidate in candidates
                    ),
                    selection_available=selected is not None,
                    selected_profile_validation_state=(
                        getattr(
                            getattr(selected, "validation_state", None),
                            "value",
                            "unknown",
                        )
                        if selected is not None
                        else "not_selected"
                    ),
                    selected_profile_reconstructed=bool(
                        selected is not None
                        and getattr(selected, "reconstructed", False)
                    ),
                    selected_profile_cross_slicer=bool(
                        selected is not None
                        and getattr(selected, "cross_slicer", False)
                    ),
                    requires_confirmation=bool(
                        getattr(result, "requires_confirmation", False)
                    ),
                    user_confirmed=bool(
                        getattr(result, "user_confirmed", False)
                    ),
                    can_use_stl_mode=bool(
                        getattr(result, "can_use_stl_mode", False)
                    ),
                    can_use_gcode_mode=bool(
                        getattr(result, "can_use_gcode_mode", False)
                    ),
                    profiles_filtered=bool(
                        getattr(result, "profiles_filtered", False)
                    ),
                )
                self.succeeded.emit(self.request_id, result)
            except Exception as error:  # converted to a user-facing GUI state
                if not self.cancellation_requested():
                    self.diagnose(
                        "profile_matching_failed",
                        diagnostic_event_schema_version=(
                            DIAGNOSTIC_EVENT_SCHEMA_VERSION
                        ),
                        outcome="failed",
                        error_code=exception_error_code(
                            "profile_matching",
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
                    self._diagnose_cancelled("during_matching")
            finally:
                self.finished.emit(self.request_id)

    @staticmethod
    def _profile_status(selected: object | None, options: object) -> str:
        if selected is not None:
            return "selected"
        return "available" if bool(options) else "unavailable"

    def _diagnose_cancelled(self, phase: str) -> None:
        self.diagnose(
            "profile_matching_cancelled",
            diagnostic_event_schema_version=DIAGNOSTIC_EVENT_SCHEMA_VERSION,
            outcome="cancelled",
            result_code="profile_matching_cancelled",
            cancellation_phase=phase,
        )
