from __future__ import annotations

import os
import subprocess
import tempfile
import time
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Sequence

from cooling_tower.diagnostic_context import record_diagnostic


@dataclass(frozen=True, slots=True)
class ProcessOutcome:
    command: tuple[str, ...]
    return_code: int | None
    stdout: str
    stderr: str
    duration_s: float
    timed_out: bool = False
    cancelled: bool = False


def isolated_slicer_environment(root: str | Path) -> dict[str, str]:
    """Redirect slicer user data, caches and temporary files to a throwaway root."""

    isolation_root = Path(root).resolve()
    roaming = isolation_root / "AppData" / "Roaming"
    local = isolation_root / "AppData" / "Local"
    home = isolation_root / "Home"
    temporary = isolation_root / "Temp"
    xdg_config = isolation_root / "xdg" / "config"
    xdg_cache = isolation_root / "xdg" / "cache"
    xdg_data = isolation_root / "xdg" / "data"
    for path in (
        roaming,
        local,
        home,
        temporary,
        xdg_config,
        xdg_cache,
        xdg_data,
    ):
        path.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update(
        {
            "APPDATA": str(roaming),
            "LOCALAPPDATA": str(local),
            "HOME": str(home),
            "USERPROFILE": str(home),
            "TEMP": str(temporary),
            "TMP": str(temporary),
            "XDG_CONFIG_HOME": str(xdg_config),
            "XDG_CACHE_HOME": str(xdg_cache),
            "XDG_DATA_HOME": str(xdg_data),
            "COOLING_TOWER_SLICER_ISOLATED": "1",
        }
    )
    return environment


class SecureSlicerProcessRunner:
    """Run a slicer without a shell and with timeout/cancellation support."""

    def run(
        self,
        executable: str | Path,
        arguments: Sequence[str | Path],
        *,
        working_directory: str | Path,
        timeout_s: float,
        cancellation_event: Event | None = None,
    ) -> ProcessOutcome:
        executable_path = Path(executable).expanduser().resolve()
        if not executable_path.is_file():
            raise FileNotFoundError(f"Slicer executable not found: {executable_path}")
        if timeout_s <= 0:
            raise ValueError("Process timeout must be greater than zero.")

        working_path = Path(working_directory).expanduser().resolve()
        working_path.mkdir(parents=True, exist_ok=True)
        command = (str(executable_path), *(str(value) for value in arguments))
        creation_flags = 0
        if os.name == "nt":
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        started = time.monotonic()
        with tempfile.TemporaryDirectory(
            prefix="cooling_tower_slicer_environment_"
        ) as isolated_root:
            record_diagnostic(
                "slicer_process_state",
                process_state="starting",
                command=command,
            )
            process = subprocess.Popen(
                command,
                cwd=str(working_path),
                env=isolated_slicer_environment(isolated_root),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                creationflags=creation_flags,
            )
            record_diagnostic(
                "slicer_process_started",
                process_state="running",
                process_id=process.pid,
                command=command,
            )
            stdout = ""
            stderr = ""
            timed_out = False
            cancelled = False
            while True:
                if cancellation_event is not None and cancellation_event.is_set():
                    cancelled = True
                    self._stop_process(process)
                    stdout, stderr = process.communicate()
                    break
                remaining = timeout_s - (time.monotonic() - started)
                if remaining <= 0:
                    timed_out = True
                    self._stop_process(process)
                    stdout, stderr = process.communicate()
                    break
                try:
                    stdout, stderr = process.communicate(timeout=min(0.1, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue

        outcome = ProcessOutcome(
            command=command,
            return_code=process.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_s=max(0.0, time.monotonic() - started),
            timed_out=timed_out,
            cancelled=cancelled,
        )
        record_diagnostic(
            "slicer_process_finished",
            process_state="not_running",
            process_id=process.pid,
            return_code=outcome.return_code,
            timed_out=outcome.timed_out,
            cancelled=outcome.cancelled,
            duration_s=outcome.duration_s,
        )
        return outcome

    @staticmethod
    def _stop_process(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        if os.name == "nt":
            _terminate_windows_process_tree(process.pid)
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                pass
            if process.poll() is not None:
                return
            try:
                subprocess.run(
                    (
                        "taskkill.exe",
                        "/PID",
                        str(process.pid),
                        "/T",
                        "/F",
                    ),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=3.0,
                    shell=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
            if process.poll() is not None:
                return
        process.terminate()
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2.0)


class _ProcessEntry32W(ctypes.Structure):
    _fields_ = (
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    )


def _windows_process_children() -> dict[int, list[int]]:
    """Snapshot parent/child relationships without matching executable names."""

    if os.name != "nt":
        return {}
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = (
        wintypes.DWORD,
        wintypes.DWORD,
    )
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(_ProcessEntry32W),
    )
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(_ProcessEntry32W),
    )
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    invalid_handle = ctypes.c_void_p(-1).value
    if snapshot == invalid_handle:
        return {}
    entry = _ProcessEntry32W()
    entry.dwSize = ctypes.sizeof(entry)
    children: dict[int, list[int]] = {}
    try:
        has_entry = bool(kernel32.Process32FirstW(snapshot, ctypes.byref(entry)))
        while has_entry:
            children.setdefault(
                int(entry.th32ParentProcessID),
                [],
            ).append(int(entry.th32ProcessID))
            has_entry = bool(
                kernel32.Process32NextW(snapshot, ctypes.byref(entry))
            )
    finally:
        kernel32.CloseHandle(snapshot)
    return children


def _terminate_windows_process_tree(root_process_id: int) -> None:
    """Terminate only one concrete PID and descendants captured beneath it."""

    if os.name != "nt":
        return
    children = _windows_process_children()
    ordered: list[int] = []

    def collect(process_id: int) -> None:
        for child_id in children.get(process_id, ()):
            collect(child_id)
        ordered.append(process_id)

    collect(int(root_process_id))
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    )
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.TerminateProcess.argtypes = (
        wintypes.HANDLE,
        wintypes.UINT,
    )
    kernel32.TerminateProcess.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
    )
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    for process_id in ordered:
        handle = kernel32.OpenProcess(
            0x0001 | 0x00100000,  # PROCESS_TERMINATE | SYNCHRONIZE
            False,
            process_id,
        )
        if not handle:
            continue
        try:
            kernel32.TerminateProcess(handle, 1)
            kernel32.WaitForSingleObject(handle, 2000)
        finally:
            kernel32.CloseHandle(handle)
