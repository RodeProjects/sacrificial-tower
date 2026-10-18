"""Bounded, disposable processes for discovery and profile operations.

Only internal Python objects cross this private transport. Slicer files are
never unpickled; they are parsed by the unchanged adapters in the child.
"""
from __future__ import annotations

import multiprocessing
import os
import pickle
import tempfile
import time
from pathlib import Path
from threading import Event
from typing import Callable

from cooling_tower.diagnostic_context import diagnostic_scope, record_diagnostic
from cooling_tower.slicers.errors import SlicerProcessCancelled, SlicerProcessError
from cooling_tower.slicers.support import slicer_failure_message

DISCOVERY_TIMEOUT_S = 30.0
CATALOG_TIMEOUT_S = 60.0
MATCHING_TIMEOUT_S = 300.0
MAXIMUM_RESPONSE_BYTES = 128 * 1024 * 1024


def _child_entry(target, payload, destination, ready):
    from cooling_tower.windows_process import configure_windows_process_policy

    configure_windows_process_policy()
    # On Windows the parent first assigns us to a kill-on-close Job Object.
    # No adapter or external slicer runs before the process tree is owned.
    if not ready.wait(10):
        return
    workspace = Path(destination).parent / "workspace"
    workspace.mkdir()
    os.environ["TEMP"] = os.environ["TMP"] = str(workspace)
    tempfile.tempdir = str(workspace)
    events = []
    def capture(event, **details):
        if len(events) < 512:
            events.append((event, details))
    try:
        with diagnostic_scope(capture):
            result = target(payload)
        response = (True, result, events)
    except Exception as error:
        from cooling_tower.diagnostic_events import exception_error_code

        capture(
            "slicer_operation_failed", outcome="failed",
            error_type=type(error).__name__,
            error_code=exception_error_code("slicer_operation", error),
        )
        response = (False, slicer_failure_message(error), events)
    with open(destination, "wb") as output:
        pickle.dump(response, output, protocol=pickle.HIGHEST_PROTOCOL)


def run_bounded_operation(
    target: Callable,
    payload: object,
    *,
    timeout_s: float,
    cancellation_event: Event,
) -> object:
    if cancellation_event.is_set():
        raise SlicerProcessCancelled("Slicer-Verarbeitung wurde abgebrochen.")
    if timeout_s <= 0:
        raise ValueError("Operation timeout must be positive.")
    context = multiprocessing.get_context("spawn")
    from cooling_tower.slicers.qprocess_backend import _WindowsJobObject

    with tempfile.TemporaryDirectory(prefix="cooling_tower_operation_") as temporary:
        response_path = Path(temporary) / "response.bin"
        ready = context.Event()
        process = context.Process(
            target=_child_entry, args=(target, payload, response_path, ready), daemon=True,
        )
        owned_tree = _WindowsJobObject()
        started = time.monotonic()
        try:
            process.start()
            record_diagnostic("slicer_operation_process_started", external_process_id=process.pid)
            if os.name == "nt" and not owned_tree.assign(process.pid):
                raise SlicerProcessError(
                    "Die Slicer-Verarbeitung konnte nicht sicher gestartet werden. "
                    "Bitte erneut versuchen."
                )
            ready.set()
            while process.is_alive():
                if cancellation_event.wait(0.05):
                    raise SlicerProcessCancelled("Slicer-Verarbeitung wurde abgebrochen.")
                if time.monotonic() - started >= timeout_s:
                    raise TimeoutError(
                        "Die Slicer-Verarbeitung hat das Zeitlimit überschritten."
                    )
            process.join(0)
            if cancellation_event.is_set():
                raise SlicerProcessCancelled("Slicer-Verarbeitung wurde abgebrochen.")
            if process.exitcode != 0 or not response_path.is_file():
                raise SlicerProcessError(
                    "Die Slicer-Verarbeitung wurde unerwartet beendet. "
                    "Bitte erneut versuchen oder einen anderen unterstützten "
                    "Slicer auswählen."
                )
            if response_path.stat().st_size > MAXIMUM_RESPONSE_BYTES:
                raise SlicerProcessError(
                    "Die erkannten Slicer- oder Profildaten sind zu umfangreich "
                    "und konnten nicht sicher übernommen werden."
                )
            # The file belongs to this invocation, is written by our child,
            # and is read only after that child has completely exited.
            with response_path.open("rb") as source:
                success, result, events = pickle.load(source)
            for event, details in events:
                record_diagnostic(event, **details)
            if not success:
                raise SlicerProcessError(result)
            return result
        finally:
            # Closing the job also kills any slicer descendants. QThreads are
            # never terminated and never outlive a blocked adapter operation.
            owned_tree.close()
            if process.pid is not None:
                if process.is_alive():
                    process.terminate()
                process.join(1.0)
                if process.is_alive():
                    process.kill()
                    process.join(1.0)
                process.close()


def execute_slicer_operation(payload):
    """Recreate only standard application services, with their real adapters."""
    from cooling_tower.slicers import (
        ProfileInventoryService, ProfileMappingStore, ProfileMatchingService,
        SlicerDiscoveryService, SlicerPreferenceStore,
    )
    from cooling_tower.slicers.profile_probe import SlicerProfileProbeValidator

    operation, config, args, kwargs = payload
    if operation in {"discover_installations", "add_manual_installation"}:
        service = SlicerDiscoveryService(
            preference_store=SlicerPreferenceStore(config["preferences"]),
        )
        service._installations = config.get("installations")
        service._diagnostics = config.get("diagnostics", ())
        return getattr(service, operation)(*args, **kwargs)
    if operation not in {"catalog", "match", "inventory_is_stale"}:
        raise ValueError("Unknown isolated slicer operation.")
    service = ProfileMatchingService(
        inventory_service=ProfileInventoryService(config["inventory"]),
        mapping_store=ProfileMappingStore(config["mappings"]),
        validator=SlicerProfileProbeValidator(),
    )
    installation = args[-1] if operation != "inventory_is_stale" else args[0].execution_slicer
    from cooling_tower.write_policy import register_slicer_roots

    register_slicer_roots((installation.executable_path.parent, *installation.profile_roots))
    adapter = SlicerDiscoveryService().adapter_for(installation)
    if operation == "inventory_is_stale":
        result = args[0]
        inventory = service.inventory_service.load(adapter, installation)
        if inventory.fingerprint_sha256 != result.inventory_fingerprint:
            return True
        return service.inventory_is_stale(result)
    return getattr(service, operation)(*args, adapter, **kwargs)


def isolated_slicer_call(operation, config, args, kwargs, cancellation_event):
    timeout = (
        DISCOVERY_TIMEOUT_S if operation in {"discover_installations", "add_manual_installation"}
        else MATCHING_TIMEOUT_S if operation == "match" else CATALOG_TIMEOUT_S
    )
    return run_bounded_operation(
        execute_slicer_operation, (operation, config, args, kwargs),
        timeout_s=timeout, cancellation_event=cancellation_event,
    )
