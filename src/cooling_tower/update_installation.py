"""An acknowledged Windows Setup handoff; no Qt objects enter the launch thread.

Setup cannot replace files until BOTH a commit event and the original parent's
process exit have been observed. Cancelling a delayed CreateProcess therefore
also prevents a late installer from applying an abandoned update.
"""
from __future__ import annotations

import ctypes
import hashlib
import os
import subprocess
import threading
import time
import uuid
from ctypes import wintypes
from pathlib import Path

from cooling_tower.diagnostic_events import DIAGNOSTIC_EVENT_SCHEMA_VERSION
from cooling_tower.diagnostics import DiagnosticJournal
from cooling_tower.update import UpdateError, UpdateInfo
from cooling_tower.windows_process import windows_subprocess_creation_flags


INSTALLER_READY_TIMEOUT_S = 90.0
SHUTDOWN_TIMEOUT_S = 30.0
UPDATE_STAGES = frozenset({
    "ready", "parent_exited", "install_started", "install_completed",
    "restart_started", "restart_failed", "setup_completed", "setup_failed",
    "handoff_cancelled", "parent_exit_timeout", "handoff_invalid",
})


def record_update(journal: DiagnosticJournal | None, event: str, **details) -> None:
    if journal is not None:
        journal.record(event, diagnostic_event_schema_version=DIAGNOSTIC_EVENT_SCHEMA_VERSION,
                       **details)


class WindowsUpdateSignals:
    def __init__(self, attempt_id: str) -> None:
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateEventW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR)
        self.kernel.CreateEventW.restype = wintypes.HANDLE
        self.kernel.SetEvent.argtypes = (wintypes.HANDLE,)
        self.kernel.SetEvent.restype = wintypes.BOOL
        self.kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        self.kernel.WaitForSingleObject.restype = wintypes.DWORD
        self.kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.handles: dict[str, int] = {}
        try:
            for kind in ("ready", "commit", "cancel"):
                handle = self.kernel.CreateEventW(None, True, False, self.name(attempt_id, kind))
                if not handle:
                    raise ctypes.WinError(ctypes.get_last_error())
                self.handles[kind] = handle
                if ctypes.get_last_error() == 183:
                    raise UpdateError("Die Updateübergabe ist bereits belegt.")
        except BaseException:
            self.close()
            raise

    @staticmethod
    def name(attempt_id: str, kind: str) -> str:
        return f"Local\\SacrificialTower-Update-{attempt_id}-{kind}"

    def ready(self) -> bool:
        result = self.kernel.WaitForSingleObject(self.handles["ready"], 0)
        if result == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
        return result == 0

    def signal(self, kind: str) -> None:
        if not self.kernel.SetEvent(self.handles[kind]):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self) -> None:
        for handle in self.handles.values():
            self.kernel.CloseHandle(handle)
        self.handles.clear()


def installer_command(installer: Path, attempt_id: str, log_path: Path, status_path: Path) -> list[str]:
    return [str(installer), "/SP-", "/VERYSILENT", "/SUPPRESSMSGBOXES",
            "/NORESTART", "/CURRENTUSER", "/NOCLOSEAPPLICATIONS",
            "/NORESTARTAPPLICATIONS", "/RESTARTEXITCODE=3010", "/SACRIFICIALTOWERUPDATE",
            f"/STUPDATEHANDOFF={attempt_id}", f"/STUPDATEPARENT={os.getpid()}",
            f"/STUPDATESTATUS={status_path}", f"/LOG={log_path}"]


class UpdateInstallationAttempt:
    """Pollable state whose lifetime is independent of the GUI and QThreads.

    The daemon is intentional: a security product can indefinitely suspend an OS
    process creation call. No GUI objects are referenced, and Setup's gate stays
    closed unless the GUI explicitly commits a safe shutdown.
    """

    def __init__(self, installer: Path, info: UpdateInfo, log_root: Path, *,
                 journal: DiagnosticJournal | None = None,
                 ready_timeout_s: float = INSTALLER_READY_TIMEOUT_S,
                 signals_factory=WindowsUpdateSignals, popen=None) -> None:
        self.installer = installer
        self.info = info
        self.attempt_id = uuid.uuid4().hex
        self.log_root = log_root
        self.log_path = log_root / f"update-{self.attempt_id}.log"
        self.status_path = log_root / f"update-{self.attempt_id}.status"
        self.journal = journal
        self.ready_timeout_s = ready_timeout_s
        self._signals_factory = signals_factory
        self._popen = popen or subprocess.Popen
        self._lock = threading.RLock()
        self._cancelled = threading.Event()
        self._committed = threading.Event()
        self._signals = None
        self._process = None
        self.state = "starting"
        self.error = ""
        self.started = time.monotonic()
        self._thread = threading.Thread(target=self._run, name="UpdateInstallerLaunch", daemon=True)

    def start(self) -> UpdateInstallationAttempt:
        self._record("update_installer_launch_requested", outcome="starting")
        self._thread.start()
        return self

    def _record(self, event: str, **details) -> None:
        record_update(self.journal, event, target_version=self.info.version,
                      attempt_id=self.attempt_id, elapsed_s=round(time.monotonic() - self.started, 3),
                      installer_log_path=self.log_path, **details)

    def poll(self) -> tuple[str, str]:
        with self._lock:
            if self.state == "starting" and time.monotonic() - self.started >= self.ready_timeout_s:
                self._fail("update_installer_ready_timeout",
                           "Das Setup hat seine Startbereitschaft nicht rechtzeitig bestätigt. "
                           "Möglicherweise wartet ein Virenscanner oder Windows auf eine Entscheidung. "
                           "Das Update wurde nicht freigegeben; das Programm bleibt geöffnet.")
            return self.state, self.error

    def _fail(self, event: str, message: str, **details) -> None:
        with self._lock:
            if self.state in {"failed", "cancelled", "committed"}:
                return
            self.state, self.error = "failed", message
            self._cancelled.set()
            if self._signals is not None:
                try:
                    self._signals.signal("cancel")
                except OSError:
                    pass  # Absence of commit still prevents file replacement.
        self._record(event, outcome="failed", **details)

    def cancel(self) -> None:
        with self._lock:
            if self.state in {"cancelled", "committed"}:
                return
            self._cancelled.set()
            if self._signals is not None:
                try:
                    self._signals.signal("cancel")
                except OSError as error:
                    self._record("update_handoff_signal_failed", outcome="failed",
                                 error_type=type(error).__name__, winerror=getattr(error, "winerror", None))
            if self.state != "failed":
                self.state = "cancelled"
                self._record("update_handoff_cancelled", outcome="cancelled")

    def commit(self) -> None:
        with self._lock:
            if self.state != "ready" or self._cancelled.is_set() or self._signals is None:
                raise UpdateError("Die Updateübergabe ist nicht mehr bereit.")
            code = self._process.poll()
            if code is not None:
                raise UpdateError(f"Das Setup wurde vor der Übergabe beendet (Code {code}).")
            self._signals.signal("commit")
            self.state = "committed"
            self._record("update_handoff_committed", outcome="success")
            self._committed.set()

    def _run(self) -> None:
        try:
            self.log_root.mkdir(parents=True, exist_ok=True)
            # Fail before launching if detailed diagnostics cannot be created.
            with self.log_path.open("xb"):
                pass
            digest = hashlib.sha256()
            size = 0
            with self.installer.open("rb") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    if self._cancelled.is_set():
                        return
                    size += len(block)
                    digest.update(block)
            if size != self.info.size_bytes or digest.hexdigest() != self.info.sha256:
                self._fail("update_installer_integrity_failed", "Der geladene Installer wurde "
                           "nach dem Download verändert. Das Update wurde nicht gestartet.")
                return
            with self._lock:
                if self._cancelled.is_set():
                    return
                self._signals = self._signals_factory(self.attempt_id)
            self._record("update_installer_integrity_verified", outcome="success", file_size_bytes=size)
            process = self._popen(
                installer_command(self.installer, self.attempt_id, self.log_path, self.status_path),
                cwd=self.installer.parent, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, close_fds=True,
                creationflags=windows_subprocess_creation_flags(
                    getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                    getattr(subprocess, "DETACHED_PROCESS", 0)))
            with self._lock:
                self._process = process
            self._record("update_installer_process_created", external_process_id=process.pid, outcome="running")
            while not self._committed.is_set():
                if self._cancelled.wait(0.05):
                    return
                code = process.poll()
                if code is not None:
                    self._fail("update_installer_exited_early",
                               f"Das Setup wurde vor der Installation beendet (Code {code}). "
                               "Bitte die Windows-/Virenscanner-Meldung und das Setup-Protokoll prüfen.",
                               return_code=code)
                    return
                with self._lock:
                    ready = self.state == "starting" and self._signals.ready()
                if ready:
                    # File/diagnostic I/O must never hold the GUI polling lock.
                    if not self._status_acknowledged():
                        self._fail("update_installer_ack_inconsistent",
                                   "Die Startmeldung des Setups konnte im eigenen "
                                   "Update-Protokoll nicht bestätigt werden. Die Installation "
                                   "wurde nicht freigegeben.")
                        return
                    self._record("update_installer_ready", outcome="success")
                    with self._lock:
                        if self.state == "starting" and not self._cancelled.is_set():
                            self.state = "ready"
                self.poll()
        except Exception as error:
            self._fail("update_installer_launch_failed",
                       "Das Setup konnte nicht sicher gestartet werden. "
                       "Das Programm bleibt geöffnet. Bitte das Update-Protokoll prüfen.",
                       error_type=type(error).__name__, winerror=getattr(error, "winerror", None),
                       errno=getattr(error, "errno", None), error_message=str(error))
        finally:
            with self._lock:
                if self._signals is not None:
                    self._signals.close()
                    self._signals = None

    def _status_acknowledged(self) -> bool:
        try:
            if self.status_path.resolve().parent != self.log_root.resolve():
                return False
            with self.status_path.open("rb") as handle:
                payload = handle.read(16 * 1024 + 1)
            if len(payload) > 16 * 1024:
                return False
            lines = payload.decode("utf-8-sig").splitlines()
            return ("protocol=1" in lines and f"attempt={self.attempt_id}" in lines
                    and f"version={self.info.version}" in lines and "stage=ready" in lines)
        except (OSError, UnicodeError):
            return False


def recover_update_outcomes(log_root: Path, journal: DiagnosticJournal | None, current_version: str) -> list[str]:
    """Read bounded fixed-format stage markers, never parse raw Setup messages.

    No outcome is inferred to be an antivirus detection. A killed installer may
    only leave the last confirmed stage, which is reported as such.
    """
    if not log_root.is_dir():
        return []
    summaries = []
    candidates = []
    for path in log_root.glob("update-*.status"):
        try:
            candidates.append((path.stat().st_mtime, path))
        except OSError:
            continue
    for _, path in sorted(candidates)[-1:]:
        if path.is_symlink() or path.resolve().parent != log_root.resolve():
            continue
        try:
            if path.stat().st_size > 16 * 1024:
                continue
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except (OSError, UnicodeError):
            continue
        if "protocol=1" not in lines:
            continue
        version = next((line[8:] for line in lines if line.startswith("version=")), "")
        from cooling_tower.update import version_key
        try:
            version_key(version)
        except ValueError:
            continue
        stages = [line[6:] for line in lines if line.startswith("stage=") and line[6:] in UPDATE_STAGES]
        if not stages:
            continue
        stage = stages[-1]
        for confirmed_stage in stages[-20:]:
            record_update(journal, "update_previous_outcome", target_version=version,
                          update_stage=confirmed_stage, installed_version_matches=current_version == version)
        if current_version == version and "setup_completed" in stages:
            record_update(journal, "update_target_started", target_version=version,
                          outcome="success")
        summaries.append(stage)
    return summaries
