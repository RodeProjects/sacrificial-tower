from __future__ import annotations

import ctypes
import os
import tempfile
import time
import uuid
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from typing import BinaryIO, Mapping, Sequence

import shiboken6
from PySide6.QtCore import (
    QCoreApplication,
    QEventLoop,
    QObject,
    QProcess,
    QProcessEnvironment,
    QThread,
    QTimer,
    Qt,
    Signal,
    Slot,
)

from cooling_tower.diagnostic_context import record_diagnostic
from cooling_tower.slicers.process import (
    ProcessOutcome,
    ProcessRequest,
    ProcessStateCallback,
    _terminate_windows_process_tree,
    isolated_slicer_environment,
)


DEFAULT_OUTPUT_MEMORY_LIMIT_BYTES = 1024 * 1024
DEFAULT_TERMINATION_GRACE_MS = 750


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _BoundedProcessOutput:
    """Keep bounded tails in memory and archive complete oversized streams."""

    def __init__(self, limit_bytes: int, diagnostics_directory: Path | None) -> None:
        self._limit = int(limit_bytes)
        self._diagnostics_directory = diagnostics_directory
        self._tails = {"stdout": bytearray(), "stderr": bytearray()}
        self._totals = {"stdout": 0, "stderr": 0}
        self._archive: BinaryIO | None = None
        self.archive_path: Path | None = None

    def add(self, channel: str, data: bytes) -> None:
        if not data:
            return
        if channel not in self._tails:
            raise ValueError(f"Unknown process output channel: {channel}")
        if self._archive is None and self._totals[channel] + len(data) > self._limit:
            self._open_archive()
        if self._archive is not None:
            self._write_archive_chunk(channel, data)
        self._totals[channel] += len(data)
        tail = self._tails[channel]
        tail.extend(data)
        if len(tail) > self._limit:
            del tail[: len(tail) - self._limit]

    def text(self, channel: str) -> str:
        return bytes(self._tails[channel]).decode("utf-8", errors="replace")

    def truncated(self, channel: str) -> bool:
        return self._totals[channel] > self._limit

    def close(self) -> None:
        archive = self._archive
        self._archive = None
        if archive is not None:
            archive.flush()
            archive.close()

    def _open_archive(self) -> None:
        root = self._diagnostics_directory
        if root is None:
            root = Path(
                tempfile.mkdtemp(prefix="cooling_tower_slicer_diagnostics_")
            )
        root.mkdir(parents=True, exist_ok=True)
        self.archive_path = (
            root / f"slicer_process_output_{uuid.uuid4().hex}.binlog"
        ).resolve()
        self._archive = self.archive_path.open("wb")
        for channel in ("stdout", "stderr"):
            previous = bytes(self._tails[channel])
            if previous:
                self._write_archive_chunk(channel, previous)

    def _write_archive_chunk(self, channel: str, data: bytes) -> None:
        archive = self._archive
        if archive is None:
            raise RuntimeError(
                "Slicer process diagnostics archive is not open."
            )
        header = f"\n--- {channel} chunk: {len(data)} bytes ---\n".encode("ascii")
        archive.write(header)
        archive.write(data)


if os.name == "nt":
    class _IoCounters(ctypes.Structure):
        _fields_ = (
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        )


    class _JobObjectBasicLimitInformation(ctypes.Structure):
        _fields_ = (
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        )


    class _JobObjectExtendedLimitInformation(ctypes.Structure):
        _fields_ = (
            ("BasicLimitInformation", _JobObjectBasicLimitInformation),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        )


class _WindowsJobObject:
    """Own one concrete Windows Job Object and its assigned slicer process."""

    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9

    def __init__(self) -> None:
        self._handle: int | None = None
        self.assignment_error: str | None = None

    @property
    def assigned(self) -> bool:
        return self._handle is not None

    def assign(self, process_id: int) -> bool:
        if os.name != "nt":
            return False
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        )
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.OpenProcess.argtypes = (
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        )
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.AssignProcessToJobObject.argtypes = (
            wintypes.HANDLE,
            wintypes.HANDLE,
        )
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL

        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            self.assignment_error = f"CreateJobObjectW failed: {ctypes.get_last_error()}"
            return False
        information = _JobObjectExtendedLimitInformation()
        information.BasicLimitInformation.LimitFlags = (
            self._JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        if not kernel32.SetInformationJobObject(
            job,
            self._JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(information),
            ctypes.sizeof(information),
        ):
            error = ctypes.get_last_error()
            kernel32.CloseHandle(job)
            self.assignment_error = f"SetInformationJobObject failed: {error}"
            return False
        access = 0x0001 | 0x0100 | 0x1000 | 0x00100000
        process = kernel32.OpenProcess(access, False, int(process_id))
        if not process:
            error = ctypes.get_last_error()
            kernel32.CloseHandle(job)
            self.assignment_error = f"OpenProcess failed: {error}"
            return False
        try:
            assigned = bool(kernel32.AssignProcessToJobObject(job, process))
            if not assigned:
                self.assignment_error = (
                    f"AssignProcessToJobObject failed: {ctypes.get_last_error()}"
                )
        finally:
            kernel32.CloseHandle(process)
        if not assigned:
            kernel32.CloseHandle(job)
            return False
        self._handle = int(job)
        return True

    def terminate(self, exit_code: int = 1) -> bool:
        if os.name != "nt" or self._handle is None:
            return False
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
        kernel32.TerminateJobObject.restype = wintypes.BOOL
        return bool(kernel32.TerminateJobObject(self._handle, int(exit_code)))

    def close(self) -> None:
        handle = self._handle
        self._handle = None
        if os.name == "nt" and handle is not None:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
            kernel32.CloseHandle.restype = wintypes.BOOL
            kernel32.CloseHandle(handle)


class _QProcessController(QObject):
    """Own QProcess, timers, output and Job Object in one Qt thread."""

    completed = Signal(object)
    cancel_dispatch = Signal(str)

    def __init__(
        self,
        request: ProcessRequest,
        environment: Mapping[str, str],
        *,
        termination_grace_ms: int,
    ) -> None:
        super().__init__()
        self._owner_thread = QThread.currentThread()
        self._request = request
        self._environment = dict(environment)
        self._termination_grace_ms = max(1, int(termination_grace_ms))
        diagnostics = (
            Path(request.diagnostics_directory).expanduser().resolve()
            if request.diagnostics_directory is not None
            else None
        )
        self._output = _BoundedProcessOutput(
            request.output_memory_limit_bytes,
            diagnostics,
        )
        self._process = QProcess(self)
        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._cancel_poll_timer = QTimer(self)
        self._cancel_poll_timer.setInterval(20)
        self._termination_timer = QTimer(self)
        self._termination_timer.setSingleShot(True)
        self._windows_job = _WindowsJobObject()
        self._started_monotonic = time.monotonic()
        self._started_utc = _utc_now()
        self._process_id: int | None = None
        self._return_code: int | None = None
        self._timed_out = False
        self._cancelled = False
        self._crashed = False
        self._finished = False
        self._stop_dispatched = False
        self._process_error = ""

        self._process.setProgram(str(Path(request.executable).expanduser().resolve()))
        self._process.setArguments([str(value) for value in request.arguments])
        self._process.setWorkingDirectory(
            str(Path(request.working_directory).expanduser().resolve())
        )
        qt_environment = QProcessEnvironment()
        for key, value in self._environment.items():
            qt_environment.insert(str(key), str(value))
        self._process.setProcessEnvironment(qt_environment)
        self._process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)

        self._process.started.connect(self._on_started)
        self._process.readyReadStandardOutput.connect(self._read_stdout)
        self._process.readyReadStandardError.connect(self._read_stderr)
        self._process.errorOccurred.connect(self._on_error)
        self._process.finished.connect(self._on_finished)
        self._timeout_timer.timeout.connect(self._on_timeout)
        self._cancel_poll_timer.timeout.connect(self._poll_cancellation)
        self._termination_timer.timeout.connect(self._force_stop)
        self.cancel_dispatch.connect(
            self._begin_stop,
            Qt.ConnectionType.QueuedConnection,
        )

    @property
    def process(self) -> QProcess:
        return self._process

    def start(self) -> None:
        self._assert_owner_thread()
        command = (
            self._process.program(),
            *(str(value) for value in self._request.arguments),
        )
        self._record_state(
            "slicer_process_state",
            process_state="starting",
            command=command,
        )
        cancellation = self._request.cancellation_event
        if cancellation is not None and cancellation.is_set():
            self._cancelled = True
            self._complete()
            return
        self._timeout_timer.start(max(1, round(self._request.timeout_s * 1000)))
        if cancellation is not None:
            self._cancel_poll_timer.start()
        self._process.start()

    def dispose(self) -> None:
        """Synchronously release every owned resource in the owning Qt thread."""

        self._assert_owner_thread()
        self._timeout_timer.stop()
        self._cancel_poll_timer.stop()
        self._termination_timer.stop()
        if self._process.state() is not QProcess.ProcessState.NotRunning:
            raise RuntimeError(
                "QProcess resources cannot be disposed before final termination."
            )
        self._read_stdout()
        self._read_stderr()
        self._output.close()
        self._windows_job.close()
        self._process.close()

    @Slot()
    def _on_started(self) -> None:
        self._assert_owner_thread()
        self._process.closeWriteChannel()
        self._process_id = int(self._process.processId()) or None
        job_assigned = False
        job_error = None
        if os.name == "nt" and self._process_id is not None:
            job_assigned = self._windows_job.assign(self._process_id)
            job_error = self._windows_job.assignment_error
        self._record_state(
            "slicer_process_started",
            process_state="running",
            process_id=self._process_id,
            command=(self._process.program(), *self._process.arguments()),
            windows_job_assigned=job_assigned,
            windows_job_error=job_error,
        )

    @Slot()
    def _read_stdout(self) -> None:
        self._assert_owner_thread()
        self._output.add("stdout", bytes(self._process.readAllStandardOutput()))

    @Slot()
    def _read_stderr(self) -> None:
        self._assert_owner_thread()
        self._output.add("stderr", bytes(self._process.readAllStandardError()))

    @Slot(QProcess.ProcessError)
    def _on_error(self, error: QProcess.ProcessError) -> None:
        self._assert_owner_thread()
        self._process_error = self._process.errorString()
        self._record_state(
            "slicer_process_error",
            process_state=self._state_name(),
            process_id=self._process_id,
            process_error=int(error.value),
            error_message=self._process_error,
        )
        if error is QProcess.ProcessError.FailedToStart:
            self._output.add(
                "stderr",
                self._process_error.encode("utf-8", errors="replace"),
            )
            self._complete()

    @Slot(int, QProcess.ExitStatus)
    def _on_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        self._assert_owner_thread()
        self._return_code = int(exit_code)
        self._crashed = exit_status is QProcess.ExitStatus.CrashExit
        self._complete()

    @Slot()
    def _poll_cancellation(self) -> None:
        self._assert_owner_thread()
        cancellation = self._request.cancellation_event
        if (
            not self._stop_dispatched
            and cancellation is not None
            and cancellation.is_set()
        ):
            self._stop_dispatched = True
            self.cancel_dispatch.emit("cancelled")

    @Slot()
    def _on_timeout(self) -> None:
        self._assert_owner_thread()
        if not self._stop_dispatched and not self._finished:
            self._stop_dispatched = True
            self.cancel_dispatch.emit("timeout")

    @Slot(str)
    def _begin_stop(self, reason: str) -> None:
        self._assert_owner_thread()
        if self._finished:
            return
        if reason == "timeout":
            self._timed_out = True
        else:
            self._cancelled = True
        self._record_state(
            "slicer_process_stop_requested",
            process_state=self._state_name(),
            process_id=self._process_id,
            stop_reason=reason,
        )
        if self._process.state() is QProcess.ProcessState.NotRunning:
            self._complete()
            return
        self._process.terminate()
        self._termination_timer.start(self._termination_grace_ms)

    @Slot()
    def _force_stop(self) -> None:
        self._assert_owner_thread()
        if self._finished or self._process.state() is QProcess.ProcessState.NotRunning:
            return
        terminated_by_job = self._windows_job.terminate()
        if os.name == "nt" and not terminated_by_job and self._process_id is not None:
            _terminate_windows_process_tree(self._process_id)
        if self._process.state() is not QProcess.ProcessState.NotRunning:
            self._process.kill()
        self._record_state(
            "slicer_process_force_stopped",
            process_state=self._state_name(),
            process_id=self._process_id,
            windows_job_terminated=terminated_by_job,
        )

    def _complete(self) -> None:
        self._assert_owner_thread()
        if self._finished:
            return
        self._finished = True
        self._timeout_timer.stop()
        self._cancel_poll_timer.stop()
        self._termination_timer.stop()
        self._read_stdout()
        self._read_stderr()
        # Closing a KILL_ON_JOB_CLOSE job here prevents a slicer child from
        # surviving even when the root process exited between snapshots.
        self._windows_job.close()
        self._output.close()
        outcome = ProcessOutcome(
            command=(self._process.program(), *self._process.arguments()),
            return_code=self._return_code,
            stdout=self._output.text("stdout"),
            stderr=self._output.text("stderr"),
            duration_s=max(0.0, time.monotonic() - self._started_monotonic),
            timed_out=self._timed_out,
            cancelled=self._cancelled,
            process_id=self._process_id,
            crashed=self._crashed,
            backend="qprocess",
            stdout_truncated=self._output.truncated("stdout"),
            stderr_truncated=self._output.truncated("stderr"),
            output_diagnostic_path=self._output.archive_path,
        )
        self._record_state(
            "slicer_process_finished",
            process_state="not_running",
            process_id=self._process_id,
            return_code=outcome.return_code,
            timed_out=outcome.timed_out,
            cancelled=outcome.cancelled,
            crashed=outcome.crashed,
            duration_s=outcome.duration_s,
            stdout_truncated=outcome.stdout_truncated,
            stderr_truncated=outcome.stderr_truncated,
            output_diagnostic_path=outcome.output_diagnostic_path,
            started_utc=self._started_utc,
            finished_utc=_utc_now(),
        )
        self.completed.emit(outcome)

    def _record_state(self, event: str, **details: object) -> None:
        common = {
            "backend": "qprocess",
            "adapter": self._request.adapter_id,
            "product_name": self._request.product_name,
            "purpose": self._request.purpose,
            "calibration_round": self._request.calibration_round,
        }
        common.update(details)
        record_diagnostic(event, **common)
        callback = self._request.state_callback
        if callback is not None:
            try:
                callback(event, common)
            except Exception as error:
                # State callbacks are observers.  Letting one escape from a
                # Qt process slot can suppress completion and strand the
                # external process/event loop.
                record_diagnostic(
                    "slicer_process_state_callback_failed",
                    backend="qprocess",
                    source_event=event,
                    error_type=type(error).__name__,
                )

    def _state_name(self) -> str:
        return {
            QProcess.ProcessState.NotRunning: "not_running",
            QProcess.ProcessState.Starting: "starting",
            QProcess.ProcessState.Running: "running",
        }[self._process.state()]

    def _assert_owner_thread(self) -> None:
        if QThread.currentThread() is not self._owner_thread:
            raise RuntimeError(
                "QProcess controller, process and timers must stay in one Qt thread."
            )


class QProcessSlicerProcessRunner:
    """Event-driven slicer runner with no Python pipe-reader threads."""

    backend_name = "qprocess"

    def __init__(
        self,
        *,
        output_memory_limit_bytes: int = DEFAULT_OUTPUT_MEMORY_LIMIT_BYTES,
        termination_grace_ms: int = DEFAULT_TERMINATION_GRACE_MS,
    ) -> None:
        if output_memory_limit_bytes <= 0:
            raise ValueError("Process output memory limit must be greater than zero.")
        self.output_memory_limit_bytes = int(output_memory_limit_bytes)
        self.termination_grace_ms = max(1, int(termination_grace_ms))

    def run(
        self,
        executable: str | Path,
        arguments: Sequence[str | Path],
        *,
        working_directory: str | Path,
        timeout_s: float,
        cancellation_event: Event | None = None,
        diagnostics_directory: str | Path | None = None,
        adapter_id: str | None = None,
        product_name: str | None = None,
        purpose: str | None = None,
        calibration_round: int | None = None,
        environment: Mapping[str, str] | None = None,
        state_callback: ProcessStateCallback | None = None,
    ) -> ProcessOutcome:
        return self.run_request(
            ProcessRequest(
                executable=executable,
                arguments=tuple(arguments),
                working_directory=working_directory,
                timeout_s=timeout_s,
                cancellation_event=cancellation_event,
                environment=environment,
                diagnostics_directory=diagnostics_directory,
                output_memory_limit_bytes=self.output_memory_limit_bytes,
                adapter_id=adapter_id,
                product_name=product_name,
                purpose=purpose,
                calibration_round=calibration_round,
                state_callback=state_callback,
            )
        )

    def run_request(self, request: ProcessRequest) -> ProcessOutcome:
        executable = Path(request.executable).expanduser().resolve()
        if not executable.is_file():
            raise FileNotFoundError(f"Slicer executable not found: {executable}")
        working_directory = Path(request.working_directory).expanduser().resolve()
        working_directory.mkdir(parents=True, exist_ok=True)
        application = QCoreApplication.instance()
        if application is None:
            application = QCoreApplication([])
        result: list[ProcessOutcome] = []
        with tempfile.TemporaryDirectory(
            prefix="cooling_tower_slicer_environment_"
        ) as isolated_root:
            environment = isolated_slicer_environment(isolated_root)
            if request.environment is not None:
                environment.update(
                    {str(key): str(value) for key, value in request.environment.items()}
                )
                isolated = isolated_slicer_environment(isolated_root)
                for key in (
                    "APPDATA",
                    "LOCALAPPDATA",
                    "HOME",
                    "USERPROFILE",
                    "TEMP",
                    "TMP",
                    "XDG_CONFIG_HOME",
                    "XDG_CACHE_HOME",
                    "XDG_DATA_HOME",
                    "COOLING_TOWER_SLICER_ISOLATED",
                ):
                    environment[key] = isolated[key]
            normalized = ProcessRequest(
                executable=executable,
                arguments=request.arguments,
                working_directory=working_directory,
                timeout_s=request.timeout_s,
                cancellation_event=request.cancellation_event,
                environment=request.environment,
                diagnostics_directory=request.diagnostics_directory,
                output_memory_limit_bytes=request.output_memory_limit_bytes,
                adapter_id=request.adapter_id,
                product_name=request.product_name,
                purpose=request.purpose,
                calibration_round=request.calibration_round,
                state_callback=request.state_callback,
            )
            controller = _QProcessController(
                normalized,
                environment,
                termination_grace_ms=self.termination_grace_ms,
            )
            loop = QEventLoop()

            def accept(outcome: ProcessOutcome) -> None:
                result.append(outcome)
                loop.quit()

            controller.completed.connect(accept, Qt.ConnectionType.DirectConnection)
            controller.start()
            if not result:
                loop.exec()
            controller.dispose()
            shiboken6.delete(controller)
        if not result:
            raise RuntimeError("QProcess completed without a ProcessOutcome.")
        return result[0]
