from __future__ import annotations

import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from functools import partial
from typing import Any

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot

from cooling_tower.diagnostics import DiagnosticJournal


class JobKind(str, Enum):
    UPDATE_CHECK = "update-check"
    UPDATE_DOWNLOAD = "update-download"
    SLICER_DISCOVERY = "slicer"
    PROFILE_MATCH = "profile"
    ANALYSIS = "analysis"
    FEASIBILITY = "feasibility"
    SLICER_PREDICTION = "prediction"
    PREVIEW = "preview"
    EXPORT = "export"


class JobState(str, Enum):
    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    WORKER_FINISHED = "worker_finished"
    THREAD_FINISHED = "thread_finished"
    RELEASED = "released"


_ALLOWED_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.CREATED: frozenset(
        {JobState.STARTING, JobState.CANCEL_REQUESTED, JobState.WORKER_FINISHED}
    ),
    JobState.STARTING: frozenset(
        {
            JobState.RUNNING,
            JobState.CANCEL_REQUESTED,
            JobState.WORKER_FINISHED,
        }
    ),
    JobState.RUNNING: frozenset(
        {JobState.CANCEL_REQUESTED, JobState.WORKER_FINISHED}
    ),
    JobState.CANCEL_REQUESTED: frozenset({JobState.WORKER_FINISHED}),
    JobState.WORKER_FINISHED: frozenset({JobState.THREAD_FINISHED}),
    JobState.THREAD_FINISHED: frozenset({JobState.RELEASED}),
    JobState.RELEASED: frozenset(),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class _ThreadIdentityProbe(QObject):
    """Capture IDs and enter run() from inside the worker event loop."""

    captured = Signal(str, object, object)

    def __init__(self, job_id: str, worker: QObject) -> None:
        super().__init__()
        self.job_id = job_id
        self.worker = worker

    @Slot()
    def capture_and_run(self) -> None:
        self.captured.emit(
            self.job_id,
            threading.get_ident(),
            threading.get_native_id(),
        )
        self.worker.run()


@dataclass(slots=True)
class BackgroundJob:
    job_id: str
    kind: str
    request_id: int | str | None
    worker: QObject | object | None
    thread: QThread | object | None
    identity_probe: QObject | None
    worker_class: str
    created_utc: str
    created_monotonic: float
    state: JobState = JobState.CREATED
    parent_operation_id: str | None = None
    started_utc: str | None = None
    started_monotonic: float | None = None
    worker_finished_utc: str | None = None
    thread_finished_utc: str | None = None
    released_utc: str | None = None
    cancel_requested: bool = False
    cancel_reason: str | None = None
    error_message: str | None = None
    error_details: str | None = None
    completion_info: str | None = None
    python_thread_id: int | None = None
    native_thread_id: int | None = None
    process_id: int | None = None

    @property
    def duration_s(self) -> float:
        return max(0.0, time.monotonic() - self.created_monotonic)


@dataclass(frozen=True, slots=True)
class ShutdownResult:
    clean: bool
    elapsed_s: float
    pending_job_ids: tuple[str, ...] = ()


class InvalidJobTransition(RuntimeError):
    pass


class BackgroundJobManager(QObject):
    """Single GUI-thread owner for all worker and QThread lifetimes."""

    job_started = Signal(object)
    state_changed = Signal(str, object, object)
    job_failed = Signal(object)
    job_released = Signal(object)
    shutdown_timed_out = Signal(object)

    _worker_finished_received = Signal(str)
    _thread_finished_received = Signal(str)
    _worker_failed_received = Signal(str, str, str)
    _worker_succeeded_received = Signal(str)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        diagnostic_journal: DiagnosticJournal | None = None,
        strict_transitions: bool | None = None,
    ) -> None:
        super().__init__(parent)
        self.diagnostic_journal = diagnostic_journal
        self.strict_transitions = (
            not bool(getattr(sys, "frozen", False))
            if strict_transitions is None
            else bool(strict_transitions)
        )
        self._jobs: dict[str, BackgroundJob] = {}
        self._job_keys: dict[tuple[str, int | str], str] = {}
        self._lock = threading.RLock()
        self._diagnostic_snapshot: tuple[dict[str, object], ...] = ()
        queued = Qt.ConnectionType.QueuedConnection
        self._worker_finished_received.connect(
            self._on_worker_finished,
            queued,
        )
        self._thread_finished_received.connect(
            self._on_thread_finished,
            queued,
        )
        self._worker_failed_received.connect(
            self._on_worker_failed,
            queued,
        )
        self._worker_succeeded_received.connect(
            self._on_worker_succeeded,
            queued,
        )

    def start_job(
        self,
        *,
        kind: JobKind | str,
        worker: QObject,
        request_id: int | str | None = None,
        parent_operation_id: str | None = None,
        job_id: str | None = None,
    ) -> str:
        self._assert_manager_thread()
        normalized_kind = self._normalize_kind(kind)
        run = getattr(worker, "run", None)
        finished = getattr(worker, "finished", None)
        cancel = getattr(worker, "cancel", None)
        if not callable(run) or finished is None:
            raise TypeError("Background workers require run() and finished.")
        if not callable(cancel):
            raise TypeError(
                "Managed background workers require an idempotent cancel()."
            )
        if request_id is None:
            request_id = getattr(worker, "request_id", None)
        target_job_id = job_id or str(uuid.uuid4())
        key = (
            (normalized_kind, request_id)
            if request_id is not None
            else None
        )
        with self._lock:
            if target_job_id in self._jobs:
                raise ValueError(f"Background job already exists: {target_job_id}")
            if key is not None and key in self._job_keys:
                raise ValueError(
                    "Background request already exists: "
                    f"{normalized_kind}/{request_id}"
                )
            thread = QThread(self)
            thread.setObjectName(f"background-job-{target_job_id}")
            identity_probe = _ThreadIdentityProbe(target_job_id, worker)
            job = BackgroundJob(
                job_id=target_job_id,
                kind=normalized_kind,
                request_id=request_id,
                worker=worker,
                thread=thread,
                identity_probe=identity_probe,
                worker_class=type(worker).__name__,
                created_utc=_utc_now(),
                created_monotonic=time.monotonic(),
                parent_operation_id=parent_operation_id,
            )
            self._jobs[target_job_id] = job
            if key is not None:
                self._job_keys[key] = target_job_id
            self._refresh_snapshot_locked()

        callback_setter = getattr(worker, "set_diagnostic_callback", None)
        if callable(callback_setter):
            callback_setter(
                partial(self._record_worker_diagnostic, target_job_id)
            )
        worker.moveToThread(thread)
        identity_probe.moveToThread(thread)
        identity_probe.captured.connect(
            self._on_thread_execution_started,
            Qt.ConnectionType.QueuedConnection,
        )
        thread.started.connect(
            identity_probe.capture_and_run,
            Qt.ConnectionType.QueuedConnection,
        )
        finished.connect(
            thread.quit,
            Qt.ConnectionType.DirectConnection,
        )
        finished.connect(
            lambda _request_id, target=target_job_id: (
                self._worker_finished_received.emit(target)
            )
        )
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(identity_probe.deleteLater)
        thread.finished.connect(
            lambda target=target_job_id: self._thread_finished_received.emit(
                target
            ),
            Qt.ConnectionType.DirectConnection,
        )
        thread.finished.connect(thread.deleteLater)
        failed = getattr(worker, "failed", None)
        if failed is not None:
            failed.connect(
                lambda _request_id, message, details, target=target_job_id: (
                    self._worker_failed_received.emit(
                        target,
                        str(message),
                        str(details),
                    )
                )
            )
        succeeded = getattr(worker, "succeeded", None)
        if succeeded is not None:
            succeeded.connect(
                lambda _request_id, _result, target=target_job_id: (
                    self._worker_succeeded_received.emit(target)
                )
            )

        self._transition(job, JobState.STARTING)
        self.job_started.emit(job)
        self._record_job_event(job, "job_started")
        thread.start()
        return target_job_id

    def cancel_job(
        self,
        job_id: str,
        *,
        reason: str = "user_request",
    ) -> bool:
        with self._lock:
            job = self._jobs.get(str(job_id))
        if job is None or job.state is JobState.RELEASED:
            return False
        if job.cancel_requested:
            self._record_job_event(
                job,
                "job_cancel_repeated",
                cancel_reason=job.cancel_reason,
            )
            return True
        if job.state in {
            JobState.WORKER_FINISHED,
            JobState.THREAD_FINISHED,
        }:
            return False
        job.cancel_requested = True
        job.cancel_reason = str(reason)
        self._transition(job, JobState.CANCEL_REQUESTED)
        worker = job.worker
        thread = job.thread
        try:
            cancel = getattr(worker, "cancel", None)
            if callable(cancel):
                cancel()
        except Exception as error:
            self._record_job_event(
                job,
                "job_cancel_callback_failed",
                error_message=str(error),
            )
        if isinstance(thread, QThread):
            thread.requestInterruption()
        self._record_job_event(
            job,
            "job_cancel_requested",
            cancel_reason=job.cancel_reason,
        )
        return True

    def cancel_jobs(
        self,
        kind: JobKind | str | None = None,
        *,
        reason: str = "user_request",
    ) -> tuple[str, ...]:
        jobs = self.active_jobs(kind)
        cancelled = tuple(
            job.job_id
            for job in jobs
            if self.cancel_job(job.job_id, reason=reason)
        )
        return cancelled

    def active_jobs(
        self,
        kind: JobKind | str | None = None,
    ) -> tuple[BackgroundJob, ...]:
        normalized_kind = (
            self._normalize_kind(kind) if kind is not None else None
        )
        with self._lock:
            return tuple(
                job
                for job in self._jobs.values()
                if job.state is not JobState.RELEASED
                and (normalized_kind is None or job.kind == normalized_kind)
            )

    def has_active(self, kind: JobKind | str | None = None) -> bool:
        return bool(self.active_jobs(kind))

    def job(self, job_id: str) -> BackgroundJob | None:
        with self._lock:
            return self._jobs.get(str(job_id))

    def job_for_request(
        self,
        kind: JobKind | str,
        request_id: int | str,
    ) -> BackgroundJob | None:
        normalized_kind = self._normalize_kind(kind)
        with self._lock:
            job_id = self._job_keys.get((normalized_kind, request_id))
            return self._jobs.get(job_id) if job_id is not None else None

    def diagnostic_snapshot(self) -> tuple[dict[str, object], ...]:
        with self._lock:
            return tuple(dict(item) for item in self._diagnostic_snapshot)

    def shutdown(self, timeout_ms: int = 5000) -> ShutdownResult:
        self._assert_manager_thread()
        started = time.monotonic()
        timeout_s = max(0, int(timeout_ms)) / 1000.0
        pending: list[str] = []
        for job in self.active_jobs():
            self.cancel_job(job.job_id, reason="application_shutdown")

        for job in self.active_jobs():
            thread = job.thread
            if not isinstance(thread, QThread):
                self._finish_stopped_job(job)
                continue
            remaining_s = timeout_s - (time.monotonic() - started)
            if remaining_s <= 0 or (
                thread.isRunning()
                and not thread.wait(max(1, round(remaining_s * 1000)))
            ):
                pending.append(job.job_id)
                continue
            self._finish_stopped_job(job)

        result = ShutdownResult(
            clean=not pending,
            elapsed_s=max(0.0, time.monotonic() - started),
            pending_job_ids=tuple(pending),
        )
        if pending:
            self._record_manager_event(
                "job_shutdown_timeout",
                timeout_ms=timeout_ms,
                pending_job_ids=pending,
            )
            self.shutdown_timed_out.emit(result)
        else:
            self._record_manager_event(
                "job_shutdown_finished",
                elapsed_s=result.elapsed_s,
            )
        return result

    @Slot(str, object, object)
    def _on_thread_execution_started(
        self,
        job_id: str,
        python_thread_id: object,
        native_thread_id: object,
    ) -> None:
        job = self.job(job_id)
        if job is None:
            self._record_manager_event(
                "stale_thread_started_signal",
                job_id=job_id,
            )
            return
        job.python_thread_id = int(python_thread_id)
        job.native_thread_id = int(native_thread_id)
        job.started_utc = _utc_now()
        job.started_monotonic = time.monotonic()
        if job.state is JobState.STARTING:
            self._transition(job, JobState.RUNNING)
        self._record_job_event(job, "job_thread_started")

    @Slot(str)
    def _on_worker_finished(self, job_id: str) -> None:
        job = self.job(job_id)
        if job is None:
            self._record_manager_event(
                "stale_worker_finished_signal",
                job_id=job_id,
            )
            return
        if job.state in {
            JobState.STARTING,
            JobState.RUNNING,
            JobState.CANCEL_REQUESTED,
            JobState.CREATED,
        }:
            job.worker_finished_utc = _utc_now()
            if job.completion_info is None:
                job.completion_info = (
                    "cancelled" if job.cancel_requested else "finished"
                )
            self._transition(job, JobState.WORKER_FINISHED)
            self._record_job_event(job, "job_worker_finished")

    @Slot(str)
    def _on_thread_finished(self, job_id: str) -> None:
        job = self.job(job_id)
        if job is None:
            self._record_manager_event(
                "stale_thread_finished_signal",
                job_id=job_id,
            )
            return
        self._finish_stopped_job(job)

    @Slot(str, str, str)
    def _on_worker_failed(
        self,
        job_id: str,
        message: str,
        details: str,
    ) -> None:
        job = self.job(job_id)
        if job is None:
            self._record_manager_event(
                "stale_worker_failed_signal",
                job_id=job_id,
            )
            return
        job.error_message = message
        job.error_details = details
        job.completion_info = "failed"
        self._record_job_event(
            job,
            "job_worker_failed",
            error_message=message,
            error_details=details,
        )
        self.job_failed.emit(job)

    @Slot(str)
    def _on_worker_succeeded(self, job_id: str) -> None:
        job = self.job(job_id)
        if job is None:
            self._record_manager_event(
                "stale_worker_succeeded_signal",
                job_id=job_id,
            )
            return
        job.completion_info = "succeeded"
        self._record_job_event(job, "job_worker_succeeded")

    def _finish_stopped_job(self, job: BackgroundJob) -> None:
        thread = job.thread
        if isinstance(thread, QThread):
            if thread is not QThread.currentThread():
                # isRunning() can already be false while direct slots of
                # QThread.finished still perform native cleanup.  wait() is
                # the authoritative boundary after which references may go.
                if not thread.wait():
                    return
        if job.state in {
            JobState.CREATED,
            JobState.STARTING,
            JobState.RUNNING,
            JobState.CANCEL_REQUESTED,
        }:
            job.worker_finished_utc = job.worker_finished_utc or _utc_now()
            job.completion_info = job.completion_info or (
                "cancelled" if job.cancel_requested else "finished"
            )
            self._transition(job, JobState.WORKER_FINISHED)
        if job.state is JobState.WORKER_FINISHED:
            job.thread_finished_utc = _utc_now()
            self._transition(job, JobState.THREAD_FINISHED)
        if job.state is not JobState.THREAD_FINISHED:
            return

        request_key = (
            (job.kind, job.request_id)
            if job.request_id is not None
            else None
        )
        job.worker = None
        job.thread = None
        job.identity_probe = None
        job.released_utc = _utc_now()
        self._transition(job, JobState.RELEASED)
        with self._lock:
            self._jobs.pop(job.job_id, None)
            if (
                request_key is not None
                and self._job_keys.get(request_key) == job.job_id
            ):
                self._job_keys.pop(request_key, None)
            self._refresh_snapshot_locked()
        self._record_job_event(job, "job_released")
        self.job_released.emit(job)

    def _transition(self, job: BackgroundJob, target: JobState) -> None:
        previous = job.state
        if target is previous:
            return
        if target not in _ALLOWED_TRANSITIONS[previous]:
            message = (
                f"Invalid background job transition for {job.job_id}: "
                f"{previous.value} -> {target.value}"
            )
            self._record_job_event(
                job,
                "invalid_job_transition",
                previous_state=previous.value,
                new_state=target.value,
                error_message=message,
            )
            if self.strict_transitions:
                raise InvalidJobTransition(message)
            return
        job.state = target
        with self._lock:
            self._refresh_snapshot_locked()
        self._record_job_event(
            job,
            "job_state_changed",
            previous_state=previous.value,
            new_state=target.value,
        )
        self.state_changed.emit(job.job_id, previous, target)

    def _record_worker_diagnostic(
        self,
        job_id: str,
        event: str,
        **details: Any,
    ) -> None:
        job = self.job(job_id)
        if job is None:
            self._record_manager_event(
                "stale_job_diagnostic",
                job_id=job_id,
                source_event=event,
            )
            return
        self._record_job_event(job, event, **details)

    def _record_job_event(
        self,
        job: BackgroundJob,
        event: str,
        **details: Any,
    ) -> None:
        journal = self.diagnostic_journal
        if journal is None:
            return
        payload = {
            "job_id": job.job_id,
            "job_kind": job.kind,
            "parent_operation_id": job.parent_operation_id,
            "request_id": job.request_id,
            "job_state": job.state.value,
            "worker_class": job.worker_class,
            "python_thread_id": job.python_thread_id,
            "native_thread_id": job.native_thread_id,
            "cancel_requested": job.cancel_requested,
            "cancel_reason": job.cancel_reason,
            "duration_s": round(job.duration_s, 6),
            "external_process_id": job.process_id,
        }
        payload.update(details)
        journal.record(event, **payload)

    def _record_manager_event(self, event: str, **details: Any) -> None:
        if self.diagnostic_journal is not None:
            self.diagnostic_journal.record(event, **details)

    def _refresh_snapshot_locked(self) -> None:
        self._diagnostic_snapshot = tuple(
            {
                "job_id": job.job_id,
                "job_kind": job.kind,
                "request_id": job.request_id,
                "parent_operation_id": job.parent_operation_id,
                "state": job.state.value,
                "worker_class": job.worker_class,
                "cancel_requested": job.cancel_requested,
                "duration_s": round(job.duration_s, 6),
                "python_thread_id": job.python_thread_id,
                "native_thread_id": job.native_thread_id,
                "external_process_id": job.process_id,
            }
            for job in self._jobs.values()
            if job.state is not JobState.RELEASED
        )

    def _assert_manager_thread(self) -> None:
        if QThread.currentThread() is not self.thread():
            raise RuntimeError(
                "BackgroundJobManager must be controlled from its GUI thread."
            )

    @staticmethod
    def _normalize_kind(kind: JobKind | str) -> str:
        return kind.value if isinstance(kind, JobKind) else str(kind)
