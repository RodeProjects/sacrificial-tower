"""Windows mutex shared with the standalone Inno uninstaller."""

from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from typing import Any
from cooling_tower.version import APP_NAME


APPLICATION_MUTEX_NAME = (
    "SacrificialTower-Standalone-D47169C5-9DE6-46AF-A8C9-72A394CD2949"
)
ERROR_ALREADY_EXISTS = 183
SW_SHOW = 5
SW_RESTORE = 9


class ApplicationAlreadyRunningError(RuntimeError):
    """Raised when this desktop session already owns the application mutex."""


def _close_windows_handle(handle: Any) -> None:
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


def acquire_application_mutex(
    mutex_name: str = APPLICATION_MUTEX_NAME,
) -> Any | None:
    """Hold a named mutex for the complete lifetime of a Windows process."""

    if os.name != "nt":
        return None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_mutex = kernel32.CreateMutexW
    create_mutex.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    create_mutex.restype = wintypes.HANDLE
    handle = create_mutex(None, False, mutex_name)
    if not handle:
        error_code = ctypes.get_last_error()
        raise OSError(
            error_code,
            "Der Anwendungs-Mutex konnte nicht erstellt werden.",
        )
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        _close_windows_handle(handle)
        raise ApplicationAlreadyRunningError(
            f"{APP_NAME} wird bereits ausgeführt."
        )
    return handle


def activate_running_application_window(
    window_title: str,
    *,
    timeout_ms: int = 1500,
) -> bool:
    """Restore and foreground the existing top-level application window."""

    if os.name != "nt":
        return False

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    find_window = user32.FindWindowW
    find_window.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
    find_window.restype = wintypes.HWND
    is_iconic = user32.IsIconic
    is_iconic.argtypes = (wintypes.HWND,)
    is_iconic.restype = wintypes.BOOL
    show_window = user32.ShowWindow
    show_window.argtypes = (wintypes.HWND, ctypes.c_int)
    show_window.restype = wintypes.BOOL
    bring_to_top = user32.BringWindowToTop
    bring_to_top.argtypes = (wintypes.HWND,)
    bring_to_top.restype = wintypes.BOOL
    set_foreground = user32.SetForegroundWindow
    set_foreground.argtypes = (wintypes.HWND,)
    set_foreground.restype = wintypes.BOOL
    flash_window = user32.FlashWindow
    flash_window.argtypes = (wintypes.HWND, wintypes.BOOL)
    flash_window.restype = wintypes.BOOL

    deadline = time.monotonic() + max(0, timeout_ms) / 1000.0
    while True:
        handle = find_window(None, window_title)
        if handle:
            show_window(handle, SW_RESTORE if is_iconic(handle) else SW_SHOW)
            brought_forward = bool(bring_to_top(handle))
            activated = bool(set_foreground(handle))
            if not activated:
                flash_window(handle, True)
            return brought_forward or activated
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


def release_application_mutex(handle: Any | None) -> None:
    """Release a mutex handle previously returned by acquire_application_mutex."""

    if handle is None or os.name != "nt":
        return
    _close_windows_handle(handle)
