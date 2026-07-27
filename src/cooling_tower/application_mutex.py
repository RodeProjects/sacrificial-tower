"""Windows mutex shared with the standalone Inno uninstaller."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import Any


APPLICATION_MUTEX_NAME = (
    "SacrificialTower-Standalone-D47169C5-9DE6-46AF-A8C9-72A394CD2949"
)


def acquire_application_mutex() -> Any | None:
    """Hold a named mutex for the complete lifetime of a Windows process."""

    if os.name != "nt":
        return None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_mutex = kernel32.CreateMutexW
    create_mutex.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    create_mutex.restype = wintypes.HANDLE
    handle = create_mutex(None, False, APPLICATION_MUTEX_NAME)
    if not handle:
        error_code = ctypes.get_last_error()
        raise OSError(
            error_code,
            "Der Anwendungs-Mutex konnte nicht erstellt werden.",
        )
    return handle


def release_application_mutex(handle: Any | None) -> None:
    """Release a mutex handle previously returned by acquire_application_mutex."""

    if handle is None or os.name != "nt":
        return
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL
    if not close_handle(handle):
        error_code = ctypes.get_last_error()
        raise OSError(
            error_code,
            "Der Anwendungs-Mutex konnte nicht freigegeben werden.",
        )
