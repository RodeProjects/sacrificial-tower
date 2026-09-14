"""Bounded, process-wide document locks without third-party dependencies."""
from __future__ import annotations

import hashlib
import os
import time
from contextlib import contextmanager
from pathlib import Path
from threading import RLock, local


_thread_state = local()
_registry_lock = RLock()
_locks: dict[str, RLock] = {}


@contextmanager
def document_lock(path: str | Path, *, timeout_s: float = 10.0):
    """Serialize cooperating writers by canonical path, including first creation.

    Windows uses a named kernel mutex: no sidecar in a potentially protected
    directory, no stale lock after a crash. POSIX uses an advisory sidecar flock.
    External editors do not participate; callers still compare original bytes.
    """
    target = Path(path).expanduser().resolve()
    key = os.path.normcase(str(target))
    with _registry_lock:
        local = _locks.setdefault(key, RLock())
    if not local.acquire(timeout=timeout_s):
        raise TimeoutError("Das Einstellungsdokument wird bereits bearbeitet.")
    held = getattr(_thread_state, "held", set())
    if key in held:
        try:
            yield
        finally:
            local.release()
        return
    _thread_state.held = held
    handle = None
    descriptor = None
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
            kernel.CreateMutexW.restype = wintypes.HANDLE
            kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
            kernel.WaitForSingleObject.restype = wintypes.DWORD
            kernel.ReleaseMutex.argtypes = (wintypes.HANDLE,)
            kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
            name = "Local\\SacrificialTower.Document." + hashlib.sha256(key.encode()).hexdigest()
            handle = kernel.CreateMutexW(None, False, name)
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())
            status = kernel.WaitForSingleObject(handle, max(1, int(timeout_s * 1000)))
            if status not in (0, 0x80):  # acquired or abandoned by a crashed writer
                kernel.CloseHandle(handle)
                handle = None
                raise TimeoutError("Das Einstellungsdokument ist durch einen anderen Prozess gesperrt.")
        else:
            import fcntl
            import tempfile
            directory = Path(tempfile.gettempdir()) / f"sacrificial-tower-locks-{os.getuid()}"
            directory.mkdir(mode=0o700, exist_ok=True)
            descriptor = os.open(directory / hashlib.sha256(key.encode()).hexdigest(), os.O_CREAT | os.O_RDWR, 0o600)
            deadline = time.monotonic() + timeout_s
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Das Einstellungsdokument ist gesperrt.")
                    time.sleep(0.02)
        held.add(key)
        yield
    finally:
        held.discard(key)
        if handle is not None:
            kernel.ReleaseMutex(handle)
            kernel.CloseHandle(handle)
        if descriptor is not None:
            os.close(descriptor)
        local.release()
