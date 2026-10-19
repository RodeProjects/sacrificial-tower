from __future__ import annotations

import faulthandler
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from cooling_tower.application import enable_native_crash_log
from cooling_tower.gui.background_jobs import JobKind
from cooling_tower.gui.main_window import MainWindow
from cooling_tower.gui.worker_contract import CancelableWorker
from cooling_tower.models import SlicerFamily, SourceArtifact, SourceKind
from cooling_tower.slicers import (
    SlicerCapability,
    SlicerDiscoveryResult,
    SlicerDiscoverySource,
    SlicerGuiState,
    SlicerInstallation,
    SlicerSupportLevel,
)
from gui_lifecycle import dispose_test_widget


class StaticSlicerService:
    def __init__(self) -> None:
        self.adapter = object()

    def adapter_for(self, _installation):
        return self.adapter

    def remember_selection(self, _identity_key) -> None:
        pass


class StableProfileService:
    def __init__(self, delay_s: float = 0.0) -> None:
        self.delay_s = delay_s
        self.calls = 0
        self.active = 0
        self.maximum_active = 0
        self.started = threading.Event()
        self._lock = threading.Lock()

    def inventory_is_stale(self, _result) -> bool:
        with self._lock:
            self.calls += 1
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
            self.started.set()
        try:
            if self.delay_s:
                time.sleep(self.delay_s)
            return False
        finally:
            with self._lock:
                self.active -= 1


class SlowFailingProfileService:
    def __init__(self, delay_s: float = 0.05) -> None:
        self.delay_s = delay_s
        self.started = threading.Event()
        self.active = False
        self._lock = threading.Lock()

    def match(self, *_args, **_kwargs):
        with self._lock:
            self.active = True
            self.started.set()
        try:
            time.sleep(self.delay_s)
            raise RuntimeError("controlled profile test failure")
        finally:
            with self._lock:
                self.active = False


class RepeatedSlicerService(StaticSlicerService):
    def __init__(
        self,
        result: SlicerDiscoveryResult,
        *,
        profile_service: SlowFailingProfileService | None = None,
        delay_s: float = 0.002,
    ) -> None:
        super().__init__()
        self.result = result
        self.profile_service = profile_service
        self.delay_s = delay_s
        self.calls = 0
        self.overlapped_profile_work = False

    def discover_installations(self, _source_slicer=None, *, force=False):
        self.calls += 1
        if self.profile_service is not None and self.profile_service.active:
            self.overlapped_profile_work = True
        if self.delay_s:
            time.sleep(self.delay_s)
        return self.result


class TimerOwningWorker(CancelableWorker):
    """Worker exposing the native-timer cleanup race from the real crash."""

    finished = Signal(int)

    def __init__(self, request_id: int) -> None:
        super().__init__()
        self.request_id = request_id
        self.timers: tuple[QTimer, QTimer] | None = None

    @Slot()
    def run(self) -> None:
        first = QTimer(self)
        second = QTimer(self)
        first.start(1000)
        second.start(1000)
        self.timers = (first, second)
        self.finished.emit(self.request_id)


class ControlledTimerOwningWorker(TimerOwningWorker):
    """Timer worker whose completion can be released by the GUI test."""

    def __init__(self, request_id: int) -> None:
        super().__init__(request_id)
        self.started = threading.Event()
        self.release = threading.Event()
        self.release_timer: QTimer | None = None

    @Slot()
    def run(self) -> None:
        first = QTimer(self)
        second = QTimer(self)
        first.start(1000)
        second.start(1000)
        self.timers = (first, second)
        self.release_timer = QTimer(self)
        self.release_timer.timeout.connect(self._finish_if_released)
        self.release_timer.start(1)
        self.started.set()

    @Slot()
    def _finish_if_released(self) -> None:
        if not self.release.is_set():
            return
        assert self.release_timer is not None
        self.release_timer.stop()
        self.finished.emit(self.request_id)


class GuiCrashStabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.app.processEvents()

    def make_window(
        self,
        profile_service: StableProfileService,
    ) -> MainWindow:
        installation = SlicerInstallation(
            adapter_id="stability-test",
            product_name="Stability Test Slicer",
            version="1.0",
            executable_path=self.root / "slicer.exe",
            verified=True,
            capabilities=frozenset({SlicerCapability.CLI_SLICE}),
            discovery_source=SlicerDiscoverySource.MANUAL,
            family=SlicerFamily.OTHER,
            support_level=SlicerSupportLevel.FULL,
        )
        discovery = SlicerDiscoveryResult(
            installations=(installation,),
            recommended_key=installation.identity_key,
            gui_state=SlicerGuiState.AVAILABLE,
            message="Test-Slicer verfügbar",
        )
        window = MainWindow(
            user_settings_path=self.root / "user_settings.json",
            slicer_service=StaticSlicerService(),
            profile_service=profile_service,
        )
        self.addCleanup(dispose_test_widget, window)
        window.analysis_snapshot = object()
        window.profile_match_result = object()
        stl_path = self.root / "stability.stl"
        stl_path.write_text("solid stability\nendsolid stability\n", encoding="utf-8")
        window.current_source_path = stl_path.resolve()
        window.current_source_kind = SourceKind.STL
        window.source_artifact = SourceArtifact.capture(stl_path)
        window.stl_validation_result = SimpleNamespace(valid=True)
        window.slicer_discovery_result = discovery
        window._populating_slicer_combo = True
        window.slicer_combo.addItem(
            installation.display_name,
            installation.identity_key,
        )
        window._populating_slicer_combo = False
        return window

    def wait_until(self, predicate, timeout_s: float = 5.0) -> None:
        deadline = time.monotonic() + timeout_s
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.001)
        self.app.processEvents()
        self.assertTrue(predicate(), "Timed out waiting for Qt background work")

    def test_pending_window_layout_callbacks_stop_at_native_deletion(self) -> None:
        window = MainWindow(
            user_settings_path=self.root / "deleted_window_settings.json",
            enable_update_check=False,
            enable_startup_slicer_discovery=False,
        )
        self.addCleanup(dispose_test_widget, window)
        window.show()
        window.resize(1100, 900)
        window._on_settings_scroll_range_changed(0, 1)
        self.assertTrue(window.close())
        window.deleteLater()
        self.app.sendPostedEvents(window, QEvent.Type.DeferredDelete)
        self.assertFalse(isValid(window))
        with patch("sys.excepthook") as unhandled_error:
            self.app.processEvents()
            QTest.qWait(400)
        unhandled_error.assert_not_called()

    def test_worker_reference_is_retained_until_qthread_finished(self) -> None:
        window = self.make_window(StableProfileService())
        worker = ControlledTimerOwningWorker(41)
        job_id = window.background_job_manager.start_job(
            kind=JobKind.STL_VALIDATION,
            request_id=41,
            worker=worker,
        )
        self.wait_until(worker.started.is_set)
        job = window.background_job_manager.job(job_id)
        self.assertIsNotNone(job)
        thread = job.thread
        self.assertIsInstance(thread, QThread)
        self.assertTrue(thread.isRunning())
        thread_finished = threading.Event()
        thread.finished.connect(
            thread_finished.set,
            Qt.ConnectionType.DirectConnection,
        )

        worker.release.set()
        self.wait_until(
            lambda: window.background_job_manager.job(job_id) is None
        )
        self.assertTrue(thread_finished.is_set())
        window.close()

    def test_timer_owning_workers_are_deleted_in_their_own_thread(self) -> None:
        window = self.make_window(StableProfileService())

        for request_id in range(1, 101):
            worker = TimerOwningWorker(request_id)
            window.background_job_manager.start_job(
                kind=JobKind.STL_VALIDATION,
                request_id=request_id,
                worker=worker,
            )
            self.wait_until(
                lambda: window.background_job_manager.job_for_request(
                    JobKind.STL_VALIDATION,
                    request_id,
                )
                is None
            )

        self.assertFalse(
            window.background_job_manager.has_active(JobKind.STL_VALIDATION)
        )
        window.close()

    def test_job_is_retained_until_native_thread_cleanup_finishes(self) -> None:
        window = self.make_window(StableProfileService())
        worker = ControlledTimerOwningWorker(42)
        job_id = window.background_job_manager.start_job(
            kind=JobKind.STL_VALIDATION,
            request_id=42,
            worker=worker,
        )
        job = window.background_job_manager.job(job_id)
        self.assertIsNotNone(job)
        thread = job.thread
        self.assertIsInstance(thread, QThread)
        self.wait_until(worker.started.is_set)

        cleanup_started = threading.Event()
        cleanup_finished = threading.Event()

        def slow_native_cleanup() -> None:
            cleanup_started.set()
            time.sleep(0.1)
            cleanup_finished.set()

        thread.finished.connect(
            slow_native_cleanup,
            Qt.ConnectionType.DirectConnection,
        )
        worker.release.set()
        self.wait_until(cleanup_started.is_set)

        self.wait_until(
            lambda: window.background_job_manager.job(job_id) is None
        )
        self.assertTrue(cleanup_finished.is_set())
        window.close()

    def test_profile_checks_are_serialized_and_latest_request_runs(self) -> None:
        service = StableProfileService(delay_s=0.05)
        window = self.make_window(service)

        window._check_profile_inventory_changes()
        self.assertTrue(service.started.wait(1.0))
        window.start_profile_matching(stale_check_only=True)

        self.assertEqual(
            len(
                window.background_job_manager.active_jobs(
                    JobKind.PROFILE_MATCH
                )
            ),
            1,
        )
        self.assertIsNotNone(window._pending_profile_match)
        self.wait_until(
            lambda: service.calls == 2
            and not window.background_job_manager.has_active(
                JobKind.PROFILE_MATCH
            )
            and window._pending_profile_match is None,
        )
        self.assertEqual(service.maximum_active, 1)
        window.close()

    def test_many_idle_profile_checks_leave_no_native_threads_behind(self) -> None:
        service = StableProfileService()
        window = self.make_window(service)

        for expected_calls in range(1, 101):
            window._check_profile_inventory_changes()
            self.wait_until(
                lambda: service.calls >= expected_calls
                and not window.background_job_manager.has_active(
                    JobKind.PROFILE_MATCH
                )
            )

        self.assertEqual(service.calls, 100)
        self.assertEqual(service.maximum_active, 1)
        self.assertFalse(
            window.background_job_manager.has_active(JobKind.PROFILE_MATCH)
        )
        window.close()

    def test_repeated_slicer_detection_waits_for_native_thread_shutdown(self) -> None:
        window = self.make_window(StableProfileService())
        window.analysis_snapshot = None
        service = RepeatedSlicerService(window.slicer_discovery_result)
        window.slicer_service = service

        for expected_calls in range(1, 31):
            window.start_slicer_discovery(force=True)
            self.wait_until(
                lambda: service.calls >= expected_calls
                and not window.background_job_manager.has_active(
                    JobKind.SLICER_DISCOVERY
                )
                and window.slicer_refresh_button.isEnabled(),
            )

        self.assertEqual(service.calls, 30)
        self.assertIsNone(window._pending_slicer_discovery)
        self.assertFalse(
            window.background_job_manager.has_active(JobKind.SLICER_DISCOVERY)
        )
        window.close()

    def test_slicer_detection_and_profile_matching_never_share_adapter_work(self) -> None:
        profile_service = SlowFailingProfileService(delay_s=0.08)
        window = self.make_window(profile_service)
        self.assertFalse(window._source_support_recovery_available())
        slicer_service = RepeatedSlicerService(
            window.slicer_discovery_result,
            profile_service=profile_service,
        )
        window.slicer_service = slicer_service

        window.start_profile_matching()
        self.assertTrue(profile_service.started.wait(1.0))
        window.start_slicer_discovery(force=True)
        self.assertEqual(slicer_service.calls, 0)
        self.assertIsNotNone(window._pending_slicer_discovery)
        self.assertFalse(window.slicer_refresh_button.isEnabled())

        # The queued discovery must not trigger another profile pass afterward.
        window.analysis_snapshot = None
        self.wait_until(
            lambda: slicer_service.calls == 1
            and not window.background_job_manager.has_active(
                JobKind.PROFILE_MATCH
            )
            and not window.background_job_manager.has_active(
                JobKind.SLICER_DISCOVERY
            )
            and window._pending_slicer_discovery is None
            and window.slicer_refresh_button.isEnabled(),
        )
        self.assertFalse(slicer_service.overlapped_profile_work)
        window.close()

    def test_native_crash_diagnostics_can_write_python_thread_stacks(self) -> None:
        if faulthandler.is_enabled():
            self.skipTest("faulthandler is already owned by the test runner")
        path = self.root / "native_crash.log"
        handle = enable_native_crash_log(path)
        self.assertIsNotNone(handle)
        try:
            faulthandler.dump_traceback(file=handle, all_threads=True)
        finally:
            faulthandler.disable()
            handle.close()
        content = path.read_text(encoding="utf-8")
        self.assertIn("application session started", content)
        self.assertIn("test_native_crash_diagnostics", content)


if __name__ == "__main__":
    unittest.main()
