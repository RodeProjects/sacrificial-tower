from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication

from cooling_tower.diagnostics import DiagnosticJournal
from cooling_tower.gui.analysis_worker import AnalysisWorker
from cooling_tower.gui.background_jobs import (
    BackgroundJobManager,
    InvalidJobTransition,
    JobKind,
    JobState,
)
from cooling_tower.gui.export_worker import ExportWorker
from cooling_tower.gui.feasibility_worker import FeasibilityWorker
from cooling_tower.gui.preview_worker import PreviewWorker
from cooling_tower.gui.profile_worker import ProfileMatchingWorker
from cooling_tower.gui.slicer_worker import SlicerDiscoveryWorker
from cooling_tower.gui.update_worker import (
    UpdateCheckWorker,
    UpdateDownloadWorker,
)
from cooling_tower.gui.worker_contract import CancelableWorker


def _attribute_path(node: ast.AST) -> tuple[str, ...]:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    else:
        return ()
    return tuple(reversed(parts))


def _qthread_lifetime_violations(
    path: Path,
    source: str,
) -> list[str]:
    """Find QThread construction and lifecycle escape hatches via aliases."""

    tree = ast.parse(source)
    direct_factories: set[str] = set()
    qtcore_modules: set[str] = set()
    pyside_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "PySide6.QtCore":
                direct_factories.update(
                    alias.asname or alias.name
                    for alias in node.names
                    if alias.name == "QThread"
                )
            elif node.module == "PySide6":
                qtcore_modules.update(
                    alias.asname or alias.name
                    for alias in node.names
                    if alias.name == "QtCore"
                )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "PySide6.QtCore":
                    if alias.asname:
                        qtcore_modules.add(alias.asname)
                    else:
                        pyside_modules.add("PySide6")
                elif alias.name == "PySide6":
                    pyside_modules.add(alias.asname or "PySide6")

    def is_qthread_reference(node: ast.AST) -> bool:
        path_parts = _attribute_path(node)
        if isinstance(node, ast.Name) and node.id in direct_factories:
            return True
        return bool(
            len(path_parts) == 2
            and path_parts[0] in qtcore_modules
            and path_parts[1] == "QThread"
            or len(path_parts) == 3
            and path_parts[0] in pyside_modules
            and path_parts[1:] == ("QtCore", "QThread")
        )

    # Resolve simple local aliases such as ``ThreadFactory = QtCore.QThread``.
    aliases_changed = True
    while aliases_changed:
        aliases_changed = False
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if value is None or not is_qthread_reference(value):
                continue
            targets = (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
            for target in targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id not in direct_factories
                ):
                    direct_factories.add(target.id)
                    aliases_changed = True

    qthread_objects: set[tuple[str, ...]] = set()
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if not (
            isinstance(value, ast.Call)
            and is_qthread_reference(value.func)
        ):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        qthread_objects.update(
            target_path
            for target in targets
            if (target_path := _attribute_path(target))
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and is_qthread_reference(node.func):
            violations.append(f"{path.name}:{node.lineno}:QThread-construction")
        if isinstance(node, ast.Attribute) and node.attr in {
            "deleteLater",
            "terminate",
        }:
            owner = _attribute_path(node.value)
            owner_looks_like_thread = bool(
                owner in qthread_objects
                or any("thread" in part.casefold() for part in owner)
            )
            if node.attr == "terminate" or owner_looks_like_thread:
                violations.append(
                    f"{path.name}:{node.lineno}:QThread-{node.attr}"
                )
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in {"deleteLater", "terminate"}
        ):
            owner = _attribute_path(node.args[0])
            if node.args[1].value == "terminate" or any(
                "thread" in part.casefold() for part in owner
            ):
                violations.append(
                    f"{path.name}:{node.lineno}:QThread-getattr-"
                    f"{node.args[1].value}"
                )
    return sorted(set(violations))


class ManagedTestWorker(CancelableWorker):
    succeeded = Signal(int, object)
    failed = Signal(int, str, str)
    finished = Signal(int)

    def __init__(
        self,
        request_id: int,
        *,
        duration_s: float = 0.0,
        fail: bool = False,
        timer_owner: bool = False,
        release_event: threading.Event | None = None,
        ignore_cancel: bool = False,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.duration_s = duration_s
        self.fail = fail
        self.timer_owner = timer_owner
        self.release_event = release_event
        self.ignore_cancel = ignore_cancel
        self.started = threading.Event()

    @Slot()
    def run(self) -> None:
        self.started.set()
        try:
            if self.timer_owner:
                timer = QTimer(self)
                timer.start(500)
            deadline = time.monotonic() + self.duration_s
            while time.monotonic() < deadline:
                if not self.ignore_cancel and self.cancellation_requested():
                    return
                time.sleep(0.001)
            while (
                self.release_event is not None
                and not self.release_event.is_set()
            ):
                time.sleep(0.001)
            if self.fail:
                raise RuntimeError("expected worker failure")
            if not self.cancellation_requested():
                self.succeeded.emit(self.request_id, "ok")
        except Exception as error:
            self.failed.emit(self.request_id, str(error), "test traceback")
        finally:
            self.finished.emit(self.request_id)


class BackgroundJobManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.journal = DiagnosticJournal(
            self.root / "jobs.jsonl",
            state_path=self.root / "session.json",
        )
        self.journal.start_session()
        self.manager = BackgroundJobManager(
            diagnostic_journal=self.journal,
            strict_transitions=True,
        )

    def tearDown(self) -> None:
        if self.manager.has_active():
            self.manager.cancel_jobs(reason="test_teardown")
            self.manager.shutdown(2000)
        self.app.processEvents()
        self.journal.close_session()
        self.temporary.cleanup()

    def wait_until(self, predicate, timeout_s: float = 5.0) -> None:
        deadline = time.monotonic() + timeout_s
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.001)
        self.app.processEvents()
        self.assertTrue(predicate(), "Timed out waiting for managed jobs")

    def start_worker(
        self,
        request_id: int,
        *,
        kind: JobKind = JobKind.ANALYSIS,
        **kwargs,
    ) -> tuple[str, ManagedTestWorker]:
        worker = ManagedTestWorker(request_id, **kwargs)
        job_id = self.manager.start_job(
            kind=kind,
            request_id=request_id,
            worker=worker,
            parent_operation_id=f"operation-{request_id}",
        )
        return job_id, worker

    def test_immediate_and_timer_workers_release_after_native_end(self) -> None:
        released = []
        self.manager.job_released.connect(released.append)
        for request_id in range(1, 51):
            self.start_worker(request_id, timer_owner=True)
        self.wait_until(lambda: not self.manager.has_active())
        self.assertEqual(len(released), 50)
        self.assertTrue(
            all(job.state is JobState.RELEASED for job in released)
        )
        self.assertTrue(
            all(job.worker is None and job.thread is None for job in released)
        )

    def test_native_cleanup_is_awaited_before_release(self) -> None:
        job_id, worker = self.start_worker(1, duration_s=0.03)
        job = self.manager.job(job_id)
        self.assertIsNotNone(job)
        cleanup_finished = threading.Event()

        def delayed_cleanup() -> None:
            time.sleep(0.08)
            cleanup_finished.set()

        job.thread.finished.connect(  # type: ignore[union-attr]
            delayed_cleanup,
            Qt.ConnectionType.DirectConnection,
        )
        self.wait_until(lambda: self.manager.job(job_id) is None)
        self.assertTrue(cleanup_finished.is_set())
        self.assertTrue(worker.started.is_set())

    def test_exception_is_diagnosed_and_does_not_leak_job(self) -> None:
        failures = []
        self.manager.job_failed.connect(failures.append)
        self.start_worker(1, fail=True)
        self.wait_until(lambda: not self.manager.has_active())
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].completion_info, "failed")
        content = (self.root / "jobs.jsonl").read_text(encoding="utf-8")
        self.assertIn("job_worker_failed", content)
        self.assertIn("expected worker failure", content)
        self.assertIn('"error_code": "analysis_worker_failed"', content)

    def test_cancel_before_and_after_start_is_idempotent(self) -> None:
        first_id, _first = self.start_worker(1, duration_s=0.2)
        self.assertTrue(self.manager.cancel_job(first_id))
        self.assertTrue(self.manager.cancel_job(first_id))
        second_id, second = self.start_worker(2, duration_s=0.2)
        self.wait_until(second.started.is_set)
        self.assertTrue(self.manager.cancel_job(second_id))
        self.wait_until(lambda: not self.manager.has_active())
        content = (self.root / "jobs.jsonl").read_text(encoding="utf-8")
        self.assertIn("job_cancel_repeated", content)

    def test_cancel_just_before_normal_completion_is_safe(self) -> None:
        job_id, worker = self.start_worker(1, duration_s=0.04)
        self.wait_until(worker.started.is_set)
        time.sleep(0.03)
        self.manager.cancel_job(job_id, reason="finish_race")
        self.wait_until(lambda: self.manager.job(job_id) is None)
        self.assertFalse(self.manager.has_active())

    def test_shutdown_cancels_running_jobs_and_preserves_timed_out_job(self) -> None:
        self.start_worker(1, duration_s=0.3)
        clean = self.manager.shutdown(2000)
        self.assertTrue(clean.clean)
        self.assertFalse(self.manager.has_active())

        release = threading.Event()
        _job_id, worker = self.start_worker(
            2,
            release_event=release,
            ignore_cancel=True,
        )
        self.wait_until(worker.started.is_set)
        timed_out = self.manager.shutdown(10)
        self.assertFalse(timed_out.clean)
        self.assertTrue(self.manager.has_active())
        release.set()
        self.wait_until(lambda: not self.manager.has_active())

    def test_stale_signals_are_ignored_and_multiple_kinds_can_run(self) -> None:
        first_id, _worker = self.start_worker(1)
        for request_id, kind in enumerate(
            (
                JobKind.PROFILE_MATCH,
                JobKind.PREVIEW,
                JobKind.FEASIBILITY,
            ),
            start=2,
        ):
            self.start_worker(request_id, kind=kind, duration_s=0.02)
        self.wait_until(lambda: not self.manager.has_active())
        self.manager._worker_finished_received.emit(first_id)
        self.app.processEvents()
        content = (self.root / "jobs.jsonl").read_text(encoding="utf-8")
        self.assertIn("stale_worker_finished_signal", content)

    def test_invalid_transition_is_reported_immediately_in_development(self) -> None:
        job_id, _worker = self.start_worker(1, duration_s=0.2)
        job = self.manager.job(job_id)
        self.assertIsNotNone(job)
        with self.assertRaises(InvalidJobTransition):
            self.manager._transition(job, JobState.RELEASED)
        self.manager.cancel_job(job_id)
        self.wait_until(lambda: self.manager.job(job_id) is None)
        self.assertIn(
            "invalid_job_transition",
            (self.root / "jobs.jsonl").read_text(encoding="utf-8"),
        )


class DiagnosticJournalTests(unittest.TestCase):
    def test_unclean_session_is_detected_reported_and_discarded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = DiagnosticJournal(
                root / "jobs.jsonl",
                state_path=root / "session.json",
            )
            first.start_session()
            first.record(
                "intentional_failure",
                source_path=root / "private" / "model.gcode",
                private_key="must-not-appear",
            )

            second = DiagnosticJournal(
                root / "jobs.jsonl",
                state_path=root / "session.json",
            )
            previous = second.start_session()
            self.assertIsNotNone(previous)
            entries = [
                json.loads(line)
                for line in (root / "jobs.jsonl").read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
            current_start = next(
                entry
                for entry in reversed(entries)
                if entry["event"] == "session_started"
            )
            self.assertTrue(
                current_start["previous_session_ended_unexpectedly"]
            )
            report = second.build_previous_crash_report()
            self.assertIn("intentional_failure", report)
            self.assertNotIn("must-not-appear", report)
            self.assertNotIn(str(root / "private"), report)
            second.discard_previous_crash_report()
            self.assertIsNone(second.previous_unexpected_session)
            second.close_session()
            state = json.loads(
                (root / "session.json").read_text(encoding="utf-8")
            )
            self.assertTrue(state["clean_shutdown"])

    def test_rotation_and_critical_qt_snapshot_are_thread_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            journal = DiagnosticJournal(
                root / "jobs.jsonl",
                maximum_bytes=64 * 1024,
                backup_count=2,
            )
            journal.start_session()
            journal.set_active_jobs_provider(
                lambda: ({"job_id": "one", "state": "running"},)
            )
            for index in range(80):
                journal.record("bulk", index=index, text="x" * 2048)
            journal.record_qt_message(
                message_type="qt-warning",
                message="QThread: Destroyed while thread is still running",
                critical=True,
            )
            journal.close_session()
            self.assertTrue((root / "jobs.jsonl.1").exists())
            combined = "\n".join(
                path.read_text(encoding="utf-8")
                for path in root.glob("jobs.jsonl*")
            )
            self.assertIn('"priority": "critical"', combined)
            self.assertIn('"job_id": "one"', combined)


class BackgroundArchitectureTests(unittest.TestCase):
    def test_qthread_lifetime_operations_are_manager_only(self) -> None:
        gui_root = SRC_ROOT / "cooling_tower" / "gui"
        manager_path = gui_root / "background_jobs.py"
        violations: list[str] = []
        for path in gui_root.rglob("*.py"):
            if path == manager_path:
                continue
            source = path.read_text(encoding="utf-8")
            violations.extend(_qthread_lifetime_violations(path, source))
        self.assertEqual(violations, [])

    def test_qthread_architecture_guard_detects_aliases_and_escape_hatches(
        self,
    ) -> None:
        unsafe_sources = (
            "from PySide6.QtCore import QThread as WorkerThread\nWorkerThread()",
            "from PySide6 import QtCore as QC\nQC.QThread()",
            "import PySide6.QtCore as QC\nQC.QThread()",
            "import PySide6\nPySide6.QtCore.QThread()",
            (
                "from PySide6.QtCore import QThread\n"
                "ThreadFactory = QThread\nthread = ThreadFactory()\n"
                "cleanup = thread.deleteLater"
            ),
            "def cleanup(worker_thread):\n    worker_thread.deleteLater()",
            "def stop(anything):\n    anything.terminate()",
            "def stop(thread):\n    getattr(thread, 'terminate')()",
        )
        for index, source in enumerate(unsafe_sources):
            with self.subTest(index=index):
                self.assertTrue(
                    _qthread_lifetime_violations(Path("unsafe.py"), source)
                )

        safe_source = (
            "from PySide6.QtCore import QThread\n"
            "current = QThread.currentThread()\n"
            "current.requestInterruption()"
        )
        self.assertEqual(
            _qthread_lifetime_violations(Path("safe.py"), safe_source),
            [],
        )

    def test_main_window_has_no_manual_job_dictionaries(self) -> None:
        path = SRC_ROOT / "cooling_tower" / "gui" / "main_window.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        violations = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if not isinstance(value, ast.Dict):
                continue
            targets = (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
            for target in targets:
                if (
                    isinstance(target, ast.Attribute)
                    and target.attr.endswith("_jobs")
                ):
                    violations.append((target.attr, node.lineno))
        self.assertEqual(violations, [])
        self.assertNotIn("legacy_view", source)
        self.assertNotIn("BackgroundJobView", source)

    def test_productive_code_has_no_legacy_background_job_api(self) -> None:
        source_root = SRC_ROOT / "cooling_tower"
        forbidden = (
            "legacy_view",
            "BackgroundJobView",
            "start_background_job",
            "adopt_external_job",
            "release_external_thread",
        )
        violations = []
        for path in source_root.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            for symbol in forbidden:
                if symbol in source:
                    violations.append(f"{path.relative_to(source_root)}:{symbol}")
        self.assertEqual(violations, [])

    def test_every_productive_worker_has_cancel_and_one_finished_signal(self) -> None:
        workers = (
            AnalysisWorker,
            FeasibilityWorker,
            ProfileMatchingWorker,
            SlicerDiscoveryWorker,
            PreviewWorker,
            ExportWorker,
            UpdateCheckWorker,
            UpdateDownloadWorker,
        )
        for worker in workers:
            with self.subTest(worker=worker.__name__):
                self.assertTrue(issubclass(worker, CancelableWorker))
                self.assertTrue(callable(getattr(worker, "cancel", None)))
                self.assertIn("finished", worker.__dict__)

    def test_documented_invariants_cover_all_thread_rules(self) -> None:
        architecture = (PROJECT_ROOT / "docs" / "architecture.md").read_text(
            encoding="utf-8"
        )
        for required in (
            "genau einen Besitzer",
            "nativen Threadende",
            "zugehörigen Thread erzeugt und zerstört",
            "mehrfach gefahrlos",
            "terminate()",
            "GUI-Thread",
        ):
            self.assertIn(required, architecture)


if __name__ == "__main__":
    unittest.main()
