from __future__ import annotations

import argparse
import faulthandler
import json
import os
import random
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QThread,
    QTimer,
    Qt,
    Signal,
    Slot,
)

from cooling_tower.application import (
    enable_native_crash_log,
    install_qt_message_logging,
)
from cooling_tower.diagnostics import DiagnosticJournal
from cooling_tower.gui.background_jobs import BackgroundJobManager, JobKind
from cooling_tower.gui.worker_contract import CancelableWorker
from cooling_tower.slicers.qprocess_backend import QProcessSlicerProcessRunner


SCENARIOS = (
    "hundreds_of_timer_workers",
    "deferred_delete_cleanup",
    "preview_cancel_each_phase",
    "close_during_preview",
    "parallel_job_kinds",
    "worker_exception",
    "stale_preview_replacement",
    "hanging_fake_slicer",
    "large_slicer_stdout",
    "slicer_child_process",
    "cancel_output_race",
    "parallel_qprocess_slicers",
    "close_during_qprocess_slicer",
    "shutdown_timeout",
)


class StressWorker(CancelableWorker):
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
        ignore_cancel: bool = False,
        release_event: threading.Event | None = None,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.duration_s = duration_s
        self.fail = fail
        self.timer_owner = timer_owner
        self.ignore_cancel = ignore_cancel
        self.release_event = release_event
        self.started = threading.Event()

    @Slot()
    def run(self) -> None:
        with self.diagnostic_scope():
            self.started.set()
            try:
                if self.timer_owner:
                    timer = QTimer(self)
                    timer.setInterval(1000)
                    timer.start()
                started = time.monotonic()
                while time.monotonic() - started < self.duration_s:
                    if (
                        not self.ignore_cancel
                        and self.cancellation_requested()
                    ):
                        return
                    time.sleep(0.001)
                while (
                    self.release_event is not None
                    and not self.release_event.is_set()
                ):
                    time.sleep(0.001)
                if self.fail:
                    raise RuntimeError("intentional stress worker failure")
                if not self.cancellation_requested():
                    self.succeeded.emit(self.request_id, "ok")
            except Exception as error:
                self.failed.emit(
                    self.request_id,
                    str(error),
                    traceback.format_exc(),
                )
            finally:
                self.finished.emit(self.request_id)


class FakeSlicerWorker(CancelableWorker):
    succeeded = Signal(int, object)
    failed = Signal(int, str, str)
    finished = Signal(int)

    def __init__(
        self,
        request_id: int,
        executable: Path,
        script: Path,
        mode: str,
        working_directory: Path,
        timeout_s: float,
        pid_file: Path | None = None,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.executable = executable
        self.script = script
        self.mode = mode
        self.working_directory = working_directory
        self.timeout_s = timeout_s
        self.pid_file = pid_file

    @Slot()
    def run(self) -> None:
        with self.diagnostic_scope():
            try:
                arguments = [self.script, self.mode]
                if self.pid_file is not None:
                    arguments.append(self.pid_file)
                outcome = QProcessSlicerProcessRunner(
                    output_memory_limit_bytes=256 * 1024,
                    termination_grace_ms=100,
                ).run(
                    self.executable,
                    arguments,
                    working_directory=self.working_directory,
                    timeout_s=self.timeout_s,
                    cancellation_event=self.cancellation_event,
                    diagnostics_directory=self.working_directory / "process_output",
                    adapter_id="fake_stress_slicer",
                    product_name="Fake stress slicer",
                    purpose="stress",
                )
                self.succeeded.emit(self.request_id, outcome)
            except Exception as error:
                self.failed.emit(
                    self.request_id,
                    str(error),
                    traceback.format_exc(),
                )
            finally:
                self.finished.emit(self.request_id)


def _wait_until(
    application: QCoreApplication,
    predicate,
    timeout_s: float = 10.0,
) -> None:
    deadline = time.monotonic() + timeout_s
    while not predicate() and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.001)
    application.processEvents()
    if not predicate():
        raise TimeoutError("Timed out while waiting for managed Qt jobs.")


def _drain_deferred_deletions(application: QCoreApplication) -> None:
    """Flush QThread/QObject deleteLater events before interpreter shutdown."""

    for _ in range(3):
        application.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        application.processEvents()


def _start_delay(
    manager: BackgroundJobManager,
    kind: JobKind,
    request_id: int,
    duration_s: float,
    **kwargs,
) -> str:
    return manager.start_job(
        kind=kind,
        request_id=request_id,
        worker=StressWorker(
            request_id,
            duration_s=duration_s,
            **kwargs,
        ),
        parent_operation_id=f"stress-{request_id}",
    )


def _write_fake_slicer(root: Path) -> Path:
    path = root / "fake_slicer.py"
    path.write_text(
        "\n".join(
            (
                "import subprocess",
                "import sys",
                "import time",
                "from pathlib import Path",
                "mode = sys.argv[1]",
                "if mode == 'large':",
                "    sys.stdout.buffer.write(b'x' * (2 * 1024 * 1024))",
                "    sys.stdout.flush()",
                "elif mode == 'hang':",
                "    time.sleep(30)",
                "elif mode == 'child':",
                "    pid_path = Path(sys.argv[2])",
                "    ready_path = pid_path.with_suffix('.ready')",
                "    child_code = \"import sys,time; from pathlib import Path; Path(sys.argv[1]).write_text('ready', encoding='ascii'); time.sleep(30)\"",
                "    child = subprocess.Popen([sys.executable, '-c', child_code, str(ready_path)])",
                "    deadline = time.monotonic() + 0.75",
                "    while not ready_path.exists() and child.poll() is None and time.monotonic() < deadline:",
                "        time.sleep(0.01)",
                "    if not ready_path.exists():",
                "        return_code = child.poll()",
                "        windows_status = f'0x{(return_code & 0xFFFFFFFF):08X}' if return_code is not None else 'not available'",
                "        raise RuntimeError(f'Child interpreter did not become ready; returncode={return_code}; windows_status={windows_status}')",
                "    pid_path.write_text(str(child.pid), encoding='ascii')",
                "    time.sleep(30)",
                "elif mode == 'cancel-output':",
                "    for index in range(10000):",
                "        print(f'line-{index}', flush=True)",
                "        time.sleep(0.002)",
                "else:",
                "    print('ok')",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _process_exists(process_id: int) -> bool:
    if process_id <= 0:
        return False
    if os.name == "nt":
        import ctypes

        process = ctypes.windll.kernel32.OpenProcess(  # type: ignore[attr-defined]
            0x100000,
            False,
            process_id,
        )
        if process:
            ctypes.windll.kernel32.CloseHandle(process)  # type: ignore[attr-defined]
            return True
        return False
    try:
        os.kill(process_id, 0)
    except OSError:
        return False
    return True


def run_scenario(
    scenario: str,
    *,
    artifact_directory: Path,
    seed: int,
) -> dict[str, object]:
    randomizer = random.Random(seed)
    application = QCoreApplication.instance() or QCoreApplication([])
    native_crash_handle = enable_native_crash_log(
        artifact_directory / "native_crash.log"
    )
    journal = DiagnosticJournal(
        artifact_directory / "diagnostics.jsonl",
        state_path=artifact_directory / "session.json",
        maximum_bytes=512 * 1024,
    )
    journal.start_session()
    manager = BackgroundJobManager(
        diagnostic_journal=journal,
        strict_transitions=True,
    )
    journal.set_active_jobs_provider(manager.diagnostic_snapshot)
    previous_handler = install_qt_message_logging(
        diagnostic_journal=journal,
        active_jobs_provider=manager.diagnostic_snapshot,
    )
    child_process_id: int | None = None
    timeout_observed = False
    parallel_slicer_outcomes: list[object] = []
    parallel_slicer_failures: list[str] = []
    try:
        if scenario == "hundreds_of_timer_workers":
            for batch_start in range(0, 300, 20):
                for request_id in range(batch_start, batch_start + 20):
                    manager.start_job(
                        kind=JobKind.STL_VALIDATION,
                        request_id=request_id,
                        worker=StressWorker(
                            request_id,
                            timer_owner=True,
                        ),
                    )
                _wait_until(
                    application,
                    lambda: not manager.has_active(),
                )
        elif scenario == "deferred_delete_cleanup":
            job_id = _start_delay(
                manager,
                JobKind.PROFILE_MATCH,
                1,
                0.02,
            )
            job = manager.job(job_id)
            if job is None or not isinstance(job.thread, QThread):
                raise RuntimeError(
                    "The stress-test job did not create the expected QThread."
                )
            cleanup_finished = threading.Event()

            def delayed_cleanup() -> None:
                time.sleep(0.08)
                cleanup_finished.set()

            job.thread.finished.connect(
                delayed_cleanup,
                Qt.ConnectionType.DirectConnection,
            )
            _wait_until(application, lambda: not manager.has_active())
            if not cleanup_finished.is_set():
                raise AssertionError("Native cleanup was not awaited.")
        elif scenario == "preview_cancel_each_phase":
            for request_id in range(1, 9):
                job_id = _start_delay(
                    manager,
                    JobKind.PREVIEW,
                    request_id,
                    0.04 + randomizer.random() * 0.02,
                )
                QTimer.singleShot(
                    request_id,
                    lambda target=job_id: manager.cancel_job(
                        target,
                        reason=f"phase-{request_id}",
                    ),
                )
                _wait_until(
                    application,
                    lambda target=job_id: manager.job(target) is None,
                )
        elif scenario == "close_during_preview":
            _start_delay(manager, JobKind.PREVIEW, 1, 0.5)
            result = manager.shutdown(2000)
            if not result.clean:
                raise AssertionError("Cooperative preview did not shut down.")
        elif scenario == "parallel_job_kinds":
            for request_id, kind in enumerate(
                (
                    JobKind.STL_VALIDATION,
                    JobKind.PROFILE_MATCH,
                    JobKind.PREVIEW,
                ),
                start=1,
            ):
                _start_delay(manager, kind, request_id, 0.03)
            _wait_until(application, lambda: not manager.has_active())
        elif scenario == "worker_exception":
            manager.start_job(
                kind=JobKind.STL_VALIDATION,
                request_id=1,
                worker=StressWorker(1, fail=True),
            )
            _wait_until(application, lambda: not manager.has_active())
        elif scenario == "stale_preview_replacement":
            for request_id in range(1, 31):
                manager.cancel_jobs(
                    JobKind.PREVIEW,
                    reason="stale_preview",
                )
                _start_delay(
                    manager,
                    JobKind.PREVIEW,
                    request_id,
                    0.005 + randomizer.random() * 0.01,
                )
                application.processEvents()
            manager.cancel_jobs(JobKind.PREVIEW, reason="final_replacement")
            _wait_until(application, lambda: not manager.has_active())
        elif scenario == "parallel_qprocess_slicers":
            script = _write_fake_slicer(artifact_directory)
            for request_id in range(1, 7):
                worker = FakeSlicerWorker(
                    request_id,
                    Path(sys.executable),
                    script,
                    "success",
                    artifact_directory / f"parallel-{request_id}",
                    5.0,
                )
                worker.succeeded.connect(
                    lambda _request_id, outcome: (
                        parallel_slicer_outcomes.append(outcome)
                    )
                )
                worker.failed.connect(
                    lambda request, message, _details: (
                        parallel_slicer_failures.append(
                            f"{request}: {message}"
                        )
                    )
                )
                manager.start_job(
                    kind=JobKind.PREVIEW,
                    request_id=request_id,
                    worker=worker,
                    parent_operation_id=f"parallel-slicer-{request_id}",
                )
            _wait_until(application, lambda: not manager.has_active(), 10.0)
            failed_outcomes = [
                outcome
                for outcome in parallel_slicer_outcomes
                if getattr(outcome, "return_code", None) != 0
                or getattr(outcome, "crashed", False)
            ]
            if (
                parallel_slicer_failures
                or len(parallel_slicer_outcomes) != 6
                or failed_outcomes
            ):
                raise AssertionError(
                    "Parallel fake slicers did not all start successfully: "
                    f"worker_failures={parallel_slicer_failures}, "
                    f"outcome_count={len(parallel_slicer_outcomes)}, "
                    f"failed_outcomes={failed_outcomes}"
                )
        elif scenario == "close_during_qprocess_slicer":
            script = _write_fake_slicer(artifact_directory)
            job_id = manager.start_job(
                kind=JobKind.PREVIEW,
                request_id=1,
                worker=FakeSlicerWorker(
                    1,
                    Path(sys.executable),
                    script,
                    "hang",
                    artifact_directory / "close-during-slicer",
                    30.0,
                ),
                parent_operation_id="close-during-qprocess-slicer",
            )
            _wait_until(
                application,
                lambda: (
                    manager.job(job_id) is not None
                    and manager.job(job_id).process_id is not None
                ),
            )
            result = manager.shutdown(2000)
            if not result.clean:
                raise AssertionError("QProcess slicer did not stop during shutdown.")
        elif scenario in {
            "hanging_fake_slicer",
            "large_slicer_stdout",
            "slicer_child_process",
            "cancel_output_race",
        }:
            script = _write_fake_slicer(artifact_directory)
            mode = {
                "hanging_fake_slicer": "hang",
                "large_slicer_stdout": "large",
                "slicer_child_process": "child",
                "cancel_output_race": "cancel-output",
            }[scenario]
            pid_file = (
                artifact_directory / "child.pid"
                if mode == "child"
                else None
            )
            job_id = manager.start_job(
                kind=JobKind.PREVIEW,
                request_id=1,
                worker=FakeSlicerWorker(
                    1,
                    Path(sys.executable),
                    script,
                    mode,
                    artifact_directory,
                    (
                        1.0
                        if mode == "child"
                        else 5.0
                        if mode == "large"
                        else 0.25
                    ),
                    pid_file,
                ),
                parent_operation_id=f"fake-slicer-{mode}",
            )
            if mode == "cancel-output":
                QTimer.singleShot(
                    50,
                    lambda: manager.cancel_job(
                        job_id,
                        reason="output_race",
                    ),
                )
            _wait_until(application, lambda: not manager.has_active(), 10.0)
            if pid_file is not None:
                ready_file = pid_file.with_suffix(".ready")
                if not pid_file.exists() or not ready_file.exists():
                    raise AssertionError(
                        "Fake slicer child interpreter never became ready: "
                        f"pid_file={pid_file.exists()}, "
                        f"ready_file={ready_file.exists()}"
                    )
                child_process_id = int(
                    pid_file.read_text(encoding="ascii").strip()
                )
                time.sleep(0.1)
                if _process_exists(child_process_id):
                    raise AssertionError(
                        f"Fake slicer child process survived: {child_process_id}"
                    )
        elif scenario == "shutdown_timeout":
            release = threading.Event()
            worker = StressWorker(
                1,
                ignore_cancel=True,
                release_event=release,
            )
            manager.start_job(
                kind=JobKind.EXPORT,
                request_id=1,
                worker=worker,
            )
            _wait_until(application, worker.started.is_set)
            first = manager.shutdown(20)
            timeout_observed = not first.clean
            if first.clean or not manager.has_active():
                raise AssertionError(
                    "Timed-out shutdown released a running job."
                )
            release.set()
            _wait_until(application, lambda: not manager.has_active())
            if not manager.shutdown(1000).clean:
                raise AssertionError("Released worker did not finish safely.")
        else:
            raise ValueError(f"Unknown stress scenario: {scenario}")

        _wait_until(application, lambda: not manager.has_active())
        if not manager.shutdown(1000).clean:
            raise AssertionError("Final stress shutdown was not clean.")
        _drain_deferred_deletions(application)
        journal.close_session()
        return {
            "scenario": scenario,
            "seed": seed,
            "complete_marker": True,
            "active_job_count": len(manager.active_jobs()),
            "timeout_observed": timeout_observed,
            "child_process_id": child_process_id,
            "orphan_child_process": (
                _process_exists(child_process_id)
                if child_process_id is not None
                else False
            ),
        }
    finally:
        from PySide6.QtCore import qInstallMessageHandler

        qInstallMessageHandler(previous_handler)
        if manager.has_active():
            for active_job in manager.active_jobs():
                release_event = getattr(
                    active_job.worker,
                    "release_event",
                    None,
                )
                if isinstance(release_event, threading.Event):
                    release_event.set()
            manager.cancel_jobs(reason="stress_finalizer")
            deadline = time.monotonic() + 5.0
            while manager.has_active() and time.monotonic() < deadline:
                application.processEvents()
                time.sleep(0.005)
            if manager.has_active():
                journal.record(
                    "stress_finalizer_timeout",
                    active_jobs=manager.diagnostic_snapshot(),
                )
                os._exit(70)
        _drain_deferred_deletions(application)
        journal.close_session()
        if native_crash_handle is not None:
            try:
                faulthandler.disable()
                native_crash_handle.write(
                    "=== stress process ended without native crash ===\n"
                )
                native_crash_handle.close()
            except (OSError, RuntimeError):
                pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=SCENARIOS, required=True)
    parser.add_argument("--artifact-directory", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=1729)
    arguments = parser.parse_args(argv)
    arguments.artifact_directory.mkdir(parents=True, exist_ok=True)
    result_path = arguments.artifact_directory / "result.json"
    try:
        result = run_scenario(
            arguments.scenario,
            artifact_directory=arguments.artifact_directory,
            seed=arguments.seed,
        )
    except Exception:
        failure = {
            "scenario": arguments.scenario,
            "seed": arguments.seed,
            "complete_marker": False,
            "traceback": traceback.format_exc(),
        }
        result_path.write_text(
            json.dumps(failure, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(
            f"Stress scenario failed: {arguments.scenario}; "
            f"reproduce with seed {arguments.seed}",
            file=sys.stderr,
        )
        traceback.print_exc()
        return 1
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
