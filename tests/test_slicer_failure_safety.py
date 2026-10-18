from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from cooling_tower.diagnostics import DiagnosticJournal
from cooling_tower.gui.background_jobs import JobKind
from cooling_tower.gui.main_window import MainWindow
from cooling_tower.gui.profile_worker import ProfileCatalogWorker, ProfileMatchingWorker
from cooling_tower.gui.slicer_worker import SlicerDiscoveryWorker
from cooling_tower.slicers import (
    CuraAdapter, EffectiveProfile, ProfileCatalog, ProfileInventoryService,
    ProfileKind, ProfileRecord, SliceRequest, SlicerCapability,
    SlicerDiscoveryResult, SlicerDiscoveryService, SlicerDiscoverySource,
    SlicerGuiState, SlicerInstallation, SlicerPreferenceStore, SlicerSupportLevel,
)
from cooling_tower.slicers.errors import SlicerIntegrationUnavailableError
from cooling_tower.slicers.support import (
    detected_installation, require_profile_support, slicer_failure_message,
)
from cooling_tower.slicers.operation_process import run_bounded_operation, execute_slicer_operation
from cooling_tower.gui.worker_contract import CancelableWorker
from PySide6.QtCore import Signal, Slot
from slicer_operation_fixtures import (
    return_value, raise_empty_error, crash_process, hang_process, hang_with_descendant,
)
from gui_lifecycle import dispose_test_widget


def installation(root: Path, adapter_id: str = "test") -> SlicerInstallation:
    product_names = {
        "prusa_slicer": "PrusaSlicer",
        "orca_slicer": "OrcaSlicer",
    }
    return SlicerInstallation(
        adapter_id=adapter_id,
        product_name=product_names.get(adapter_id, adapter_id),
        version="2.9.6",
        executable_path=root / f"{adapter_id}.exe",
        verified=True,
        capabilities=frozenset({SlicerCapability.CLI_SLICE, SlicerCapability.PROFILE_INVENTORY}),
        discovery_source=SlicerDiscoverySource.KNOWN_PATH,
        support_level=SlicerSupportLevel.FULL,
        profile_roots=(root / "profiles",),
    )


def discovery_result(*installations: SlicerInstallation) -> SlicerDiscoveryResult:
    return SlicerDiscoveryResult(
        installations=installations,
        recommended_key=installations[0].identity_key,
        gui_state=SlicerGuiState.AVAILABLE,
        message="Slicer erkannt",
    )


class SlicerSupportBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_all_registered_placeholders_are_closed_despite_legacy_full_flags(self):
        for adapter_id in ("cura", "orca_slicer", "creality_print"):
            with self.subTest(adapter_id=adapter_id):
                item = installation(self.root, adapter_id)
                self.assertFalse(item.can_slice)
                self.assertIn("nur erkannt", item.display_name)
                normalized = detected_installation(item)
                self.assertEqual(normalized.support_level, SlicerSupportLevel.DETECTION_ONLY)
                self.assertFalse(normalized.capabilities)
                with self.assertRaises(SlicerIntegrationUnavailableError):
                    require_profile_support(item)

    def test_implemented_integrations_and_custom_adapters_keep_their_contract(self):
        for adapter_id in (
            "anycubic_slicer_next",
            "bambu_studio",
            "prusa_slicer",
            "custom",
        ):
            with self.subTest(adapter_id=adapter_id):
                item = installation(self.root, adapter_id)
                self.assertIs(detected_installation(item), item)
                self.assertTrue(item.can_slice)
                require_profile_support(item)

    def test_unverified_and_detection_only_installations_are_rejected(self):
        item = installation(self.root)
        for invalid in (
            replace(item, verified=False),
            replace(item, support_level=SlicerSupportLevel.DETECTION_ONLY),
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(SlicerIntegrationUnavailableError):
                    require_profile_support(invalid)

    def test_unsupported_and_mismatched_inventory_never_scans_reads_or_caches(self):
        service = ProfileInventoryService(self.root / "cache.json")
        adapter = Mock(adapter_id="test")
        for item in (installation(self.root, "orca_slicer"), installation(self.root, "other")):
            with self.subTest(adapter_id=item.adapter_id), patch.object(service, "snapshot_file_states") as scan:
                with self.assertRaises(SlicerIntegrationUnavailableError):
                    service.load(adapter, item, force=True)
                scan.assert_not_called()
                adapter.discover_profiles.assert_not_called()
        self.assertFalse(service.cache_path.exists())

    def test_direct_slice_is_rejected_before_copying_or_starting_processes(self):
        item = installation(self.root, "cura")
        adapter = CuraAdapter(runner=Mock())
        request = SliceRequest(
            model_path=self.root / "missing.stl",
            output_directory=self.root / "output",
            profile=EffectiveProfile(item, None, None, ()),
        )
        with patch("cooling_tower.slicers.base.tempfile.mkdtemp") as temporary:
            with self.assertRaises(SlicerIntegrationUnavailableError):
                adapter.slice_model(request)
            temporary.assert_not_called()
            adapter.runner.run.assert_not_called()
        self.assertFalse(request.output_directory.exists())

    def test_saved_unsupported_choice_does_not_outrank_working_installation(self):
        unsupported = installation(self.root, "orca_slicer")
        working = installation(self.root, "anycubic_slicer_next")
        store = SlicerPreferenceStore(self.root / "preferences.json")
        store.set_last_selected(unsupported.identity_key)
        service = SlicerDiscoveryService(preference_store=store)
        result = service._build_result((unsupported, working), None, ())
        self.assertEqual(result.recommended_key, working.identity_key)

    def test_missing_registered_adapter_is_reported_as_unavailable(self):
        service = SlicerDiscoveryService(adapters=(Mock(adapter_id="other"),))
        with self.assertRaises(SlicerIntegrationUnavailableError):
            service.adapter_for(installation(self.root, "orca_slicer"))

    def test_unknown_empty_and_private_errors_have_actionable_generic_feedback(self):
        for error in (RuntimeError(), NotImplementedError(), KeyError("private profile"), ValueError("<private>")):
            message = slicer_failure_message(error)
            self.assertIn("unerwarteten Fehler", message)
            self.assertNotIn("private", message)
        self.assertIn("zugegriffen", slicer_failure_message(PermissionError()))
        self.assertIn("nicht gefunden", slicer_failure_message(FileNotFoundError()))
        self.assertIn("Zeitlimit", slicer_failure_message(TimeoutError()))


class SlicerFailureWorkerTests(unittest.TestCase):
    def _capture(self, worker):
        failed, succeeded, finished = [], [], []
        worker.failed.connect(lambda *args: failed.append(args))
        worker.succeeded.connect(lambda *args: succeeded.append(args))
        worker.finished.connect(finished.append)
        worker.run()
        self.assertEqual(finished, [worker.request_id])
        return failed, succeeded

    def test_catalog_and_matching_workers_reject_unsupported_before_service_call(self):
        item = installation(PROJECT_ROOT, "orca_slicer")
        service = Mock()
        for worker in (
            ProfileCatalogWorker(1, service, item, object()),
            ProfileMatchingWorker(2, service, object(), item, object()),
        ):
            with self.subTest(worker=type(worker).__name__):
                failed, succeeded = self._capture(worker)
                self.assertEqual(len(failed), 1)
                self.assertIn("noch nicht", failed[0][1])
                self.assertFalse(succeeded)
        service.catalog.assert_not_called()
        service.match.assert_not_called()

    def test_empty_exceptions_and_absent_results_fail_and_always_finish(self):
        item = installation(PROJECT_ROOT)
        for error in (RuntimeError(), NotImplementedError(), None):
            service = Mock()
            if error is None:
                service.catalog.return_value = None
                service.match.return_value = None
                service.discover_installations.return_value = None
            else:
                service.catalog.side_effect = error
                service.match.side_effect = error
                service.discover_installations.side_effect = error
            for worker in (
                ProfileCatalogWorker(1, service, item, object()),
                ProfileMatchingWorker(2, service, object(), item, object()),
                SlicerDiscoveryWorker(3, service, None),
            ):
                with self.subTest(error=error, worker=type(worker).__name__):
                    failed, succeeded = self._capture(worker)
                    self.assertEqual(len(failed), 1)
                    self.assertTrue(failed[0][1].strip())
                    self.assertFalse(succeeded)

    def test_cancelled_workers_finish_without_obsolete_error(self):
        service = Mock()
        item = installation(PROJECT_ROOT, "prusa_slicer")
        for worker in (
            ProfileCatalogWorker(1, service, item, object()),
            ProfileMatchingWorker(2, service, object(), item, object()),
            SlicerDiscoveryWorker(3, service, None),
        ):
            with self.subTest(worker=type(worker).__name__):
                worker.cancel()
                self.assertEqual(self._capture(worker), ([], []))


class _SlicerGuiFixture:
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.working = installation(self.root)
        self.unsupported = installation(self.root, "orca_slicer")
        records = []
        for kind in (ProfileKind.MACHINE, ProfileKind.PROCESS, ProfileKind.FILAMENT):
            path = self.root / f"{kind.value}.json"
            path.write_text("{}", encoding="utf-8")
            records.append(ProfileRecord("test", kind.value, kind.value, kind, path, "user"))
        self.catalog = ProfileCatalog(self.working, "test-inventory", (records[0],), (records[1],), (records[2],))
        self.profiles = Mock()
        self.profiles.catalog.return_value = self.catalog
        self.service = SimpleNamespace(
            adapter_for=Mock(return_value=object()),
            remember_selection=Mock(),
            discover_installations=Mock(return_value=discovery_result(self.working, self.unsupported)),
        )

    def window(self, *, startup=False):
        window = MainWindow(
            user_settings_path=self.root / "user.json",
            slicer_service=self.service,
            profile_service=self.profiles,
            enable_update_check=False,
            enable_startup_slicer_discovery=startup,
            diagnostic_journal=DiagnosticJournal(self.root / "events.jsonl"),
        )
        self.addCleanup(dispose_test_widget, window)
        return window

    def wait_for(self, condition, timeout_s=5):
        deadline = time.monotonic() + timeout_s
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertTrue(condition(), "GUI-Zustand wurde nicht rechtzeitig erreicht")

    def idle(self, window):
        self.wait_for(lambda: not window.background_job_manager.active_jobs())

    def start(self):
        window = self.window()
        window.start_slicer_discovery()
        self.wait_for(lambda: window.profile_catalog is not None)
        self.idle(window)
        return window

    def assert_failed(self, window):
        self.assertTrue(window.profile_status_label.text().strip())
        self.assertEqual(window.profile_status_label.property("state"), "error")
        self.assertFalse(window.profile_status_label.isHidden())
        self.assertFalse(window._profile_confirmation_busy)
        self.assertFalse(window.profile_confirm_button.isEnabled())
        self.assertIsNone(window.profile_catalog)
        self.assertIsNone(window.profile_catalog_confirmation)
        self.assertIsNone(window.profile_match_result)
        self.assertIsNone(window.confirmed_profile_context)
        for combo in (window.machine_profile_combo, window.filament_profile_combo, window.process_profile_combo):
            self.assertEqual(combo.count(), 0)
            self.assertFalse(combo.isEnabled())


class SlicerFailureGuiTests(_SlicerGuiFixture, unittest.TestCase):
    def test_startup_with_only_saved_unsupported_slicer_closes_without_profile_work(self):
        self.service.discover_installations.return_value = discovery_result(self.unsupported)
        window = self.window(startup=True)
        self.wait_for(lambda: window.profile_status_label.property("state") == "error")
        self.idle(window)
        self.assert_failed(window)
        self.assertIn("OrcaSlicer", window.profile_status_label.text())
        self.assertIn("nur erkannt", window.slicer_combo.currentText())
        self.profiles.catalog.assert_not_called()
        self.service.adapter_for.assert_not_called()
        before = time.monotonic()
        self.assertTrue(window.close())
        self.assertLess(time.monotonic() - before, 1)

    def test_switching_to_unsupported_clears_authorization_and_allows_recovery(self):
        window = self.start()
        window.confirmed_profile_context = object()
        window.profile_status_label.setProperty("inputBlocker", True)
        calls_before = self.profiles.catalog.call_count
        window.slicer_combo.setCurrentIndex(window.slicer_combo.findData(self.unsupported.identity_key))
        self.assert_failed(window)
        self.assertIsNone(window._pending_profile_match)
        self.assertEqual(self.profiles.catalog.call_count, calls_before)
        self.assertTrue(window.slicer_refresh_button.isEnabled())
        self.assertTrue(window.slicer_manual_button.isEnabled())
        window.slicer_combo.setCurrentIndex(window.slicer_combo.findData(self.working.identity_key))
        self.wait_for(lambda: window.profile_catalog is not None)
        self.idle(window)
        self.assertEqual(window.profile_status_label.text(), "")

    def test_unknown_adapter_error_and_failed_preference_do_not_block_recovery(self):
        window = self.start()
        self.service.adapter_for.side_effect = NotImplementedError()
        window.start_profile_catalog_loading()
        self.assert_failed(window)
        self.assertIn("unerwarteten Fehler", window.profile_status_label.text())
        self.service.adapter_for.side_effect = None
        self.service.remember_selection.side_effect = PermissionError()
        window._on_slicer_selection_changed(0)
        self.wait_for(lambda: window.profile_catalog is not None)
        self.idle(window)
        self.assertEqual(window.profile_status_label.text(), "")

    def test_worker_failure_revokes_previously_loaded_catalog_and_unlocks_controls(self):
        window = self.start()
        self.profiles.catalog.side_effect = RuntimeError()
        window.start_profile_catalog_loading(force_inventory=True)
        self.wait_for(lambda: window.profile_status_label.property("state") == "error")
        self.idle(window)
        self.assert_failed(window)
        self.assertTrue(window.slicer_refresh_button.isEnabled())

    def test_malformed_queued_results_and_render_errors_have_visible_fallback(self):
        for callback in ("_on_slicer_discovery_succeeded", "_on_profile_catalog_succeeded", "_on_profile_matching_succeeded"):
            with self.subTest(callback=callback):
                window = self.start()
                request_id = window._slicer_request_id if "discovery" in callback else window._profile_request_id
                getattr(window, callback)(request_id, None)
                self.assert_failed(window)
        window = self.start()
        with patch.object(window, "_populate_profile_combos", side_effect=ValueError("private")):
            window._on_profile_catalog_succeeded(window._profile_request_id, self.catalog)
        self.assert_failed(window)
        self.assertNotIn("private", window.profile_status_label.text())

    def test_worker_start_failure_has_no_infinite_busy_state(self):
        window = self.start()
        with patch.object(window.background_job_manager, "start_job", side_effect=RuntimeError()):
            window.start_profile_catalog_loading()
        self.assert_failed(window)
        self.assertTrue(window.slicer_refresh_button.isEnabled())

    def test_missing_profile_role_ends_loading_with_error_instead_of_success(self):
        window = self.start()
        window._on_profile_catalog_succeeded(
            window._profile_request_id, replace(self.catalog, filament_options=()),
        )
        self.assertFalse(window.profile_catalog.complete)
        self.assertIn("Filamentprofile", window.profile_status_label.text())
        self.assertEqual(window.profile_status_label.property("state"), "error")
        self.assertEqual(window.slicer_progress_status_label.property("state"), "error")
        self.assertFalse(window._profile_confirmation_busy)
        self.assertFalse(window.profile_confirm_button.isEnabled())

    def test_obsolete_success_and_failure_cannot_replace_unsupported_notice(self):
        window = self.start()
        old_request = window._profile_request_id
        window.slicer_combo.setCurrentIndex(window.slicer_combo.findData(self.unsupported.identity_key))
        message = window.profile_status_label.text()
        window._on_profile_catalog_succeeded(old_request, self.catalog)
        window._on_profile_catalog_failed(old_request, "old error", "")
        window._on_profile_matching_failed(old_request, "old error", "")
        self.assertEqual(window.profile_status_label.text(), message)
        self.assert_failed(window)

    def test_switch_during_active_worker_ignores_late_result_and_remains_responsive(self):
        window = self.start()
        entered, release = threading.Event(), threading.Event()
        def delayed_catalog(*args, **kwargs):
            entered.set()
            if not release.wait(3):
                raise TimeoutError()
            return self.catalog
        self.profiles.catalog.side_effect = delayed_catalog
        window.start_profile_catalog_loading()
        self.wait_for(entered.is_set)
        try:
            window.slicer_combo.setCurrentIndex(window.slicer_combo.findData(self.unsupported.identity_key))
            self.assert_failed(window)
            heartbeat = []
            QTimer.singleShot(0, lambda: heartbeat.append(True))
            self.wait_for(lambda: bool(heartbeat))
        finally:
            release.set()
        self.idle(window)
        self.assert_failed(window)
        self.assertTrue(window.slicer_refresh_button.isEnabled())

    def test_repeated_unsupported_selection_never_starts_work_or_prevents_close(self):
        window = self.start()
        for _ in range(20):
            window.slicer_combo.setCurrentIndex(window.slicer_combo.findData(self.unsupported.identity_key))
            self.assert_failed(window)
            window.slicer_combo.setCurrentIndex(window.slicer_combo.findData(self.working.identity_key))
            self.wait_for(lambda: window.profile_catalog is not None)
            self.idle(window)
        self.assertTrue(window.close())


class BoundedSlicerProcessTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_results_cross_process_boundary_without_modification(self):
        payload = {"text": "äöü", "data": tuple(range(1000)), "path": self.root}
        self.assertEqual(run_bounded_operation(
            return_value, payload, timeout_s=10, cancellation_event=threading.Event(),
        ), payload)

    def test_bambu_catalog_is_identical_across_process_boundary(self):
        from test_bambu_studio_detection import BambuStudioDetectionTests
        from cooling_tower.slicers import ProfileMatchingService

        fixture = BambuStudioDetectionTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        fixture.create_realistic_catalog()
        adapter, item = fixture.adapter_and_installation()
        expected = ProfileMatchingService().catalog(item, adapter, include_all_profiles=True)
        original = {path: path.read_bytes() for root in item.profile_roots for path in root.rglob("*") if path.is_file()}
        actual = run_bounded_operation(
            execute_slicer_operation,
            ("catalog", {"inventory": self.root / "inventory.json", "mappings": self.root / "mappings.json"},
             (item,), {"include_all_profiles": True}),
            timeout_s=15, cancellation_event=threading.Event(),
        )
        self.assertTrue(actual.complete)
        self.assertEqual(actual, expected)
        self.assertEqual(original, {path: path.read_bytes() for root in item.profile_roots for path in root.rglob("*") if path.is_file()})

    def test_missing_profiles_match_and_stale_check_return_valid_results(self):
        from cooling_tower.models import SourceArtifact
        from cooling_tower.slicers import ProfileMatchingContext

        item = installation(self.root, "bambu_studio")
        source = SourceArtifact.capture(PROJECT_ROOT / "tests/fixtures/stl/test_model_manifold.stl")
        config = {"inventory": self.root / "inventory.json", "mappings": self.root / "mappings.json"}
        result = run_bounded_operation(
            execute_slicer_operation,
            ("match", config, (ProfileMatchingContext.from_stl(source), item), {}),
            timeout_s=15, cancellation_event=threading.Event(),
        )
        self.assertFalse(result.can_use_stl_mode)
        self.assertIsNone(result.selected)
        self.assertTrue(result.message.strip())
        stale = run_bounded_operation(
            execute_slicer_operation, ("inventory_is_stale", config, (result,), {}),
            timeout_s=15, cancellation_event=threading.Event(),
        )
        self.assertFalse(stale)

    def test_empty_exception_and_abrupt_crash_return_understandable_errors(self):
        for target in (raise_empty_error, crash_process):
            with self.subTest(target=target.__name__), self.assertRaises(Exception) as raised:
                run_bounded_operation(target, None, timeout_s=10, cancellation_event=threading.Event())
            self.assertIn("Slicer-Verarbeitung", str(raised.exception))
            self.assertNotIn("17", str(raised.exception))

    def test_nonreturning_operation_is_terminated_by_deadline(self):
        marker = self.root / "started.txt"
        before = time.monotonic()
        with self.assertRaises(TimeoutError):
            run_bounded_operation(hang_process, marker, timeout_s=2, cancellation_event=threading.Event())
        self.assertTrue(marker.is_file(), "Child did not reach the simulated hang")
        self.assertLess(time.monotonic() - before, 5)

    def test_cancel_does_not_wait_for_adapter_to_cooperate(self):
        cancelled = threading.Event()
        timer = threading.Timer(1.5, cancelled.set)
        timer.start()
        self.addCleanup(timer.cancel)
        before = time.monotonic()
        with self.assertRaises(Exception) as raised:
            run_bounded_operation(hang_process, None, timeout_s=60, cancellation_event=cancelled)
        self.assertIn("abgebrochen", str(raised.exception))
        self.assertLess(time.monotonic() - before, 5)

    @unittest.skipUnless(os.name == "nt", "Windows Job Object")
    def test_timeout_also_terminates_only_owned_descendants(self):
        import ctypes
        from ctypes import wintypes

        marker = self.root / "descendant.txt"
        with self.assertRaises(TimeoutError):
            run_bounded_operation(hang_with_descendant, marker, timeout_s=2, cancellation_event=threading.Event())
        self.assertTrue(marker.is_file())
        pid = int(marker.read_text(encoding="ascii"))
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        handle = kernel32.OpenProcess(0x1000 | 0x00100000, False, pid)
        if handle:
            kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
            kernel32.WaitForSingleObject.restype = wintypes.DWORD
            kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
            try:
                self.assertEqual(kernel32.WaitForSingleObject(handle, 3000), 0)
            finally:
                kernel32.CloseHandle(handle)


class HangingIsolatedWorker(CancelableWorker):
    succeeded = Signal(int, object)
    failed = Signal(int, str, str)
    finished = Signal(int)

    def __init__(self, marker):
        super().__init__()
        self.request_id = 987
        self.marker = marker

    @Slot()
    def run(self):
        try:
            run_bounded_operation(hang_process, self.marker, timeout_s=60, cancellation_event=self.cancellation_event)
        except Exception:
            pass
        finally:
            self.finished.emit(self.request_id)


class SlicerStepIsolationTests(_SlicerGuiFixture, unittest.TestCase):
    def test_slicer_error_cannot_change_successful_file_transfer_feedback(self):
        window = self.window()
        window._isolate_slicer_operations = True
        self.assertTrue(window.drop_zone.set_file(PROJECT_ROOT / "tests/fixtures/stl/test_model_manifold.stl"))
        self.wait_for(lambda: window.stl_validation_result is not None, timeout_s=30)
        self.assertTrue(window.stl_validation_result.valid)
        source_message = window.source_progress_status_label.text()
        source_state = window.source_group.state()
        window._on_slicer_discovery_failed(window._slicer_request_id, "", "")
        self.assertEqual(window.preparation_tabs.currentIndex(), 0)
        self.assertEqual(window.source_progress_status_label.text(), source_message)
        self.assertEqual(window.source_group.state(), source_state)
        self.assertTrue(window._source_step_is_complete())
        self.assertTrue(window.preparation_next_button.isEnabled())

    def test_step_one_defers_profiles_and_shows_no_slicer_error(self):
        window = self.window()
        window._isolate_slicer_operations = True
        self.service.discover_installations.return_value = discovery_result(self.unsupported)
        window.start_slicer_discovery()
        self.wait_for(lambda: window.slicer_discovery_result is not None)
        self.idle(window)
        self.assertEqual(window.preparation_tabs.currentIndex(), 0)
        self.profiles.catalog.assert_not_called()
        self.assertIsNotNone(window._deferred_profile_catalog_request)
        self.assertNotEqual(window.profile_status_label.property("state"), "error")
        # Open step 2 directly through the test's navigation guard; source
        # validation is tested separately below and in the existing suite.
        window.preparation_tabs.set_step_guard(lambda _index: True)
        with patch.object(window, "_source_step_is_complete", return_value=True), patch.object(window, "_update_preparation_requirements"):
            window.preparation_tabs.setCurrentIndex(1)
            window._ensure_slicer_profiles_on_first_step_entry()
        self.assert_failed(window)

    def test_hung_slicer_process_does_not_block_file_transfer_or_close(self):
        window = self.window()
        marker = self.root / "hung-worker.txt"
        worker = HangingIsolatedWorker(marker)
        window.background_job_manager.start_job(kind=JobKind.SLICER_DISCOVERY, worker=worker)
        self.wait_for(marker.is_file)
        source = PROJECT_ROOT / "tests/fixtures/stl/test_model_manifold.stl"
        self.assertTrue(window.drop_zone.set_file(source))
        self.wait_for(lambda: window.stl_validation_result is not None, timeout_s=30)
        self.assertTrue(window.stl_validation_result.valid)
        self.assertTrue(window._source_step_is_complete())
        self.assertTrue(window.preparation_next_button.isEnabled())
        heartbeat = []
        QTimer.singleShot(0, lambda: heartbeat.append(True))
        self.wait_for(lambda: bool(heartbeat))
        before = time.monotonic()
        self.assertTrue(window.close())
        self.assertLess(time.monotonic() - before, 3)
        self.assertFalse(window.background_job_manager.active_jobs())


if __name__ == "__main__":
    unittest.main()
