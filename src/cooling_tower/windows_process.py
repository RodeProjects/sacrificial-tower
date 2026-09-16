from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from threading import Lock
from typing import NamedTuple


SEM_FAILCRITICALERRORS = 0x0001
SEM_NOGPFAULTERRORBOX = 0x0002
SEM_NOOPENFILEERRORBOX = 0x8000
WINDOWS_PROCESS_ERROR_MODE_FLAGS = (
    SEM_FAILCRITICALERRORS
    | SEM_NOGPFAULTERRORBOX
    | SEM_NOOPENFILEERRORBOX
)

WER_FAULT_REPORTING_NO_UI = 0x0020
HRESULT_FROM_WIN32_ERROR_NOT_FOUND = 0x80070490
CREATE_DEFAULT_ERROR_MODE = 0x04000000

WINDOWS_ACCESS_VIOLATION = 0xC0000005
WINDOWS_ILLEGAL_INSTRUCTION = 0xC000001D
WINDOWS_INVALID_IMAGE_FORMAT = 0xC000007B
WINDOWS_DLL_NOT_FOUND = 0xC0000135
WINDOWS_DLL_INITIALIZATION_FAILED = 0xC0000142
WINDOWS_STACK_BUFFER_OVERRUN = 0xC0000409

_WINDOWS_STATUS_DESCRIPTIONS = {
    WINDOWS_ACCESS_VIOLATION: "Zugriffsverletzung",
    WINDOWS_ILLEGAL_INSTRUCTION: "ungültiger CPU-Befehl",
    WINDOWS_INVALID_IMAGE_FORMAT: "inkompatibles Programmformat",
    WINDOWS_DLL_NOT_FOUND: "benötigte DLL nicht gefunden",
    WINDOWS_DLL_INITIALIZATION_FAILED: "DLL-Initialisierung fehlgeschlagen",
    WINDOWS_STACK_BUFFER_OVERRUN: "Sicherheitsabbruch (Fast-Fail)",
}


class WindowsProcessPolicyState(NamedTuple):
    is_windows: bool
    process_error_mode: int | None
    wer_flags: int | None
    errors: tuple[str, ...]

    @property
    def active(self) -> bool:
        if not self.is_windows:
            return False
        process_mode = self.process_error_mode
        wer_flags = self.wer_flags
        return bool(
            process_mode is not None
            and process_mode & WINDOWS_PROCESS_ERROR_MODE_FLAGS
            == WINDOWS_PROCESS_ERROR_MODE_FLAGS
            and wer_flags is not None
            and wer_flags & WER_FAULT_REPORTING_NO_UI
            == WER_FAULT_REPORTING_NO_UI
        )


_POLICY_LOCK = Lock()
_POLICY_STATE: WindowsProcessPolicyState | None = None


def _load_kernel32():
    return ctypes.WinDLL("kernel32", use_last_error=True)


def _hresult_failed(value: int) -> bool:
    return ctypes.c_long(int(value)).value < 0


def _configure_process_error_mode(kernel32, errors: list[str]) -> int | None:
    try:
        kernel32.GetErrorMode.argtypes = ()
        kernel32.GetErrorMode.restype = wintypes.UINT
        kernel32.SetErrorMode.argtypes = (wintypes.UINT,)
        kernel32.SetErrorMode.restype = wintypes.UINT
        current_mode = int(kernel32.GetErrorMode())
        requested_mode = current_mode | WINDOWS_PROCESS_ERROR_MODE_FLAGS
        if requested_mode != current_mode:
            kernel32.SetErrorMode(requested_mode)
        effective_mode = int(kernel32.GetErrorMode())
        if (
            effective_mode & WINDOWS_PROCESS_ERROR_MODE_FLAGS
            != WINDOWS_PROCESS_ERROR_MODE_FLAGS
        ):
            errors.append("process_error_mode_not_applied")
        return effective_mode
    except (AttributeError, OSError, TypeError, ValueError):
        errors.append("process_error_mode_api_failed")
        return None


def _configure_wer_no_ui(kernel32, errors: list[str]) -> int | None:
    try:
        kernel32.GetCurrentProcess.argtypes = ()
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.WerGetFlags.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        )
        kernel32.WerGetFlags.restype = ctypes.c_long
        kernel32.WerSetFlags.argtypes = (wintypes.DWORD,)
        kernel32.WerSetFlags.restype = ctypes.c_long

        current_flags = wintypes.DWORD()
        process_handle = kernel32.GetCurrentProcess()
        result = int(
            kernel32.WerGetFlags(
                process_handle,
                ctypes.byref(current_flags),
            )
        )
        if result & 0xFFFFFFFF == HRESULT_FROM_WIN32_ERROR_NOT_FOUND:
            current_flags.value = 0
        elif _hresult_failed(result):
            errors.append(f"wer_get_flags_failed_0x{result & 0xFFFFFFFF:08X}")
            return None
        requested_flags = int(current_flags.value) | WER_FAULT_REPORTING_NO_UI
        if requested_flags != int(current_flags.value):
            result = int(kernel32.WerSetFlags(requested_flags))
            if _hresult_failed(result):
                errors.append(f"wer_set_flags_failed_0x{result & 0xFFFFFFFF:08X}")
                return int(current_flags.value)

        effective_flags = wintypes.DWORD()
        result = int(
            kernel32.WerGetFlags(
                process_handle,
                ctypes.byref(effective_flags),
            )
        )
        if _hresult_failed(result):
            errors.append(f"wer_verify_flags_failed_0x{result & 0xFFFFFFFF:08X}")
            return requested_flags
        if not int(effective_flags.value) & WER_FAULT_REPORTING_NO_UI:
            errors.append("wer_no_ui_not_applied")
        return int(effective_flags.value)
    except (AttributeError, OSError, TypeError, ValueError):
        errors.append("wer_no_ui_api_failed")
        return None


def configure_windows_process_policy() -> WindowsProcessPolicyState:
    """Disable blocking Windows crash UI while preserving failure results.

    The process error mode is deliberately installed once and never restored.
    Child processes inherit it unless a caller explicitly requests
    ``CREATE_DEFAULT_ERROR_MODE``.  Repeated calls are cheap and retry a
    previously incomplete setup.
    """

    global _POLICY_STATE
    if os.name != "nt":
        state = WindowsProcessPolicyState(False, None, None, ())
        _POLICY_STATE = state
        return state
    cached = _POLICY_STATE
    if cached is not None and cached.active:
        return cached
    with _POLICY_LOCK:
        cached = _POLICY_STATE
        if cached is not None and cached.active:
            return cached
        errors: list[str] = []
        try:
            kernel32 = _load_kernel32()
        except (AttributeError, OSError):
            state = WindowsProcessPolicyState(
                True,
                None,
                None,
                ("kernel32_load_failed",),
            )
            _POLICY_STATE = state
            return state
        process_mode = _configure_process_error_mode(kernel32, errors)
        wer_flags = _configure_wer_no_ui(kernel32, errors)
        state = WindowsProcessPolicyState(
            True,
            process_mode,
            wer_flags,
            tuple(errors),
        )
        _POLICY_STATE = state
        return state


def windows_subprocess_creation_flags(*flags: int) -> int:
    """Combine safe Windows creation flags without breaking error inheritance."""

    combined = 0
    for value in flags:
        combined |= int(value)
    if combined & CREATE_DEFAULT_ERROR_MODE:
        raise ValueError(
            "CREATE_DEFAULT_ERROR_MODE would bypass the inherited Windows "
            "process error policy."
        )
    configure_windows_process_policy()
    return combined


def windows_process_status(return_code: int | None) -> str | None:
    """Format a failing Windows NTSTATUS without losing signed exit codes."""

    if os.name != "nt" or return_code is None:
        return None
    normalized = int(return_code) & 0xFFFFFFFF
    # Bit 28 is reserved and must be clear in an NTSTATUS. Ordinary negative
    # application exits (-1, -17, -100, ...) set it; they are not OS crashes.
    if normalized < 0x80000000 or normalized & 0x10000000:
        return None
    return f"0x{normalized:08X}"


def windows_process_status_description(return_code: int | None) -> str | None:
    status = windows_process_status(return_code)
    if status is None:
        return None
    normalized = int(return_code) & 0xFFFFFFFF
    return _WINDOWS_STATUS_DESCRIPTIONS.get(normalized)
