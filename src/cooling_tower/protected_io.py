"""Owned workspaces and consistent read-only input snapshots.

Source files are never opened for mutation. On Windows the capture handle denies
concurrent writes and replacement until the verified copy has been completed.
Neither source attributes nor source ACLs are changed.
"""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
import stat
import tempfile
import weakref
from threading import RLock
from typing import BinaryIO, Iterator

from cooling_tower.write_policy import ensure_writable_output


_leases_lock = RLock()
_leases: dict[Path, "OwnedWorkspace"] = {}


def require_owned_workspace(path: str | Path) -> "OwnedWorkspace":
    resolved = Path(path).resolve()
    with _leases_lock:
        lease = _leases.get(resolved)
        if lease is None:
            raise UnsafeWorkspaceError("Der Slicer benötigt einen nachweislich eigenen Arbeitsbereich.")
        lease.assert_owned()
        return lease


def duplicate_workspace_pin(path: Path) -> int | None:
    """Retain an existing root pin without incompatible additional file opens."""
    if os.name != 'nt':
        return None
    with _leases_lock:
        lease = _leases.get(path)
        if lease is None or lease._closed or not lease._pins:
            return None
        lease.assert_owned()
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.DuplicateHandle.argtypes = (wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE,
                                           ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD,
                                           wintypes.BOOL, wintypes.DWORD)
        handle = wintypes.HANDLE()
        process = kernel.GetCurrentProcess()
        if not kernel.DuplicateHandle(process, lease._pins[-1], process, ctypes.byref(handle), 0, False, 2):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(handle.value)


class UnsafeWorkspaceError(ValueError):
    """An owned path has been replaced or contains an unsafe link."""


class InputChangedError(RuntimeError):
    """A source could not be captured as a consistent snapshot."""


def _identity(value: os.stat_result) -> tuple[int, int]:
    return value.st_dev, value.st_ino


def _is_reparse(value: os.stat_result) -> bool:
    return stat.S_ISLNK(value.st_mode) or bool(
        getattr(value, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


@contextmanager
def read_locked(path: str | Path) -> Iterator[BinaryIO]:
    """Open a regular source without write/delete sharing on Windows."""
    source = Path(path)
    if os.name != "nt":
        with source.open("rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("Die Quelle ist keine reguläre Datei.")
            yield stream
        return
    import msvcrt

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    )
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.CreateFileW(str(source), 0x80000000, 1, None, 3, 0x08000000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        fd = msvcrt.open_osfhandle(int(handle), os.O_RDONLY | os.O_BINARY)
    except BaseException:
        kernel.CloseHandle(handle)
        raise
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("Die Quelle ist keine reguläre Datei.")
        yield stream


@dataclass(frozen=True, slots=True)
class InputSnapshot:
    """Content identity of one source and its independently owned copy."""

    original_path: Path
    path: Path
    sha256: str
    size: int
    mtime_ns: int
    file_identity: tuple[int, int]

    def original_is_unchanged(self) -> bool:
        try:
            with read_locked(self.original_path) as stream:
                info = os.fstat(stream.fileno())
                return (
                    _identity(info) == self.file_identity
                    and info.st_size == self.size
                    and info.st_mtime_ns == self.mtime_ns
                    and hashlib.file_digest(stream, "sha256").hexdigest() == self.sha256
                )
        except OSError:
            return False

    def verify(self) -> None:
        with read_locked(self.path) as stream:
            info = os.fstat(stream.fileno())
            if info.st_size != self.size or hashlib.file_digest(stream, "sha256").hexdigest() != self.sha256:
                raise InputChangedError("Die temporäre Eingangskopie wurde verändert.")


class OwnedWorkspace:
    """A newly created workspace whose ancestors stay pinned during I/O.

    Native processes must receive a *derived* workspace, never the workspace
    retaining InputSnapshot files. The Windows process boundary grants access
    only to its own staging tree. This class does not claim to sandbox a process.
    """

    def __init__(self, *, parent: str | Path | None = None, prefix: str = "tower_job_",
                 name: str | None = None) -> None:
        base = ensure_writable_output(parent or tempfile.gettempdir())
        if os.name == 'nt':
            # Pin the destination before creating any child, not only after
            # mkdtemp: a replaced parent must never redirect the first write.
            from cooling_tower.export_io import export_parent
            guard = export_parent(base)
        else:
            guard = nullcontext(base)
        with guard:
            base.mkdir(parents=True, exist_ok=True)
            self.base_path = base
            if name is None:
                self.path = Path(tempfile.mkdtemp(prefix=prefix, dir=base)).resolve()
            else:
                if not name or Path(name).name != name or any(char in name for char in '\\/:') or name.endswith(('.', ' ')):
                    raise UnsafeWorkspaceError('Ungültiger Name für den eigenen Ausgabebereich.')
                self.path = base / name
                self.path.mkdir()  # exclusive: never adopt an existing directory
            self._identity = _identity(self.path.stat())
            self._pins: list[int] = []
            self._closed = False
            try:
                self._pin_ancestors()
            except BaseException as error:
                self._release_pins()
                try:
                    self.path.rmdir()
                except OSError as cleanup_error:
                    error.add_note(f'Der neu angelegte Arbeitsordner konnte nicht entfernt werden: {cleanup_error}')
                raise
            with _leases_lock:
                _leases[self.path] = self

    def _pin_ancestors(self) -> None:
        if os.name != "nt":
            return
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = (
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
        )
        kernel.CreateFileW.restype = wintypes.HANDLE
        # No FILE_SHARE_DELETE: an ancestor cannot be replaced by a junction
        # between validation and a path-based operation beneath this lease.
        for ancestor in (*reversed(self.path.parents), self.path):
            # Keep DELETE on our exact root handle so cleanup can mark that
            # directory for deletion without releasing its anti-replacement pin.
            # FILE_TRAVERSE counts as executable/read access for sharing checks
            # without requiring permission to list a system temporary parent.
            access = 0x10081 if ancestor == self.path else 0x20
            handle = duplicate_workspace_pin(ancestor) if ancestor != self.path else None
            if handle is None:
                handle = kernel.CreateFileW(str(ancestor), access, 3, None, 3, 0x02200000, None)
            if handle == ctypes.c_void_p(-1).value:
                error = ctypes.WinError(ctypes.get_last_error())
                error.filename = str(ancestor)
                raise error
            self._pins.append(int(handle))
        self.assert_owned()

    def _release_pins(self) -> None:
        with _leases_lock:
            if not self._pins:
                return
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
            for handle in reversed(self._pins):
                kernel.CloseHandle(handle)
            self._pins.clear()

    def child(self, relative: str | Path) -> Path:
        self.assert_owned()
        part = Path(relative)
        if part.is_absolute() or part.drive or ".." in part.parts or not part.parts:
            raise UnsafeWorkspaceError("Ungültiger relativer Arbeitspfad.")
        if any(":" in value or value.endswith((".", " ")) for value in part.parts):
            raise UnsafeWorkspaceError("Mehrdeutiger Windows-Arbeitspfad.")
        result = self.path / part
        for candidate in (result, *result.parents):
            if candidate == self.path:
                break
            try:
                value = candidate.lstat()
            except FileNotFoundError:
                continue
            if _is_reparse(value) or (stat.S_ISREG(value.st_mode) and value.st_nlink != 1):
                raise UnsafeWorkspaceError("Verknüpfungen sind im Arbeitsbereich nicht zulässig.")
        if not result.resolve().is_relative_to(self.path):
            raise UnsafeWorkspaceError("Der Arbeitspfad verlässt den eigenen Bereich.")
        return result

    def assert_owned(self) -> None:
        if self._closed:
            raise UnsafeWorkspaceError("Der Arbeitsbereich ist bereits geschlossen.")
        if self.path == self.base_path or not self.path.is_relative_to(self.base_path):
            raise UnsafeWorkspaceError("Der Arbeitsbereich verlässt seinen Erstellungsordner.")
        try:
            value = self.path.lstat()
        except OSError as error:
            raise UnsafeWorkspaceError("Der Arbeitsbereich ist nicht mehr vorhanden.") from error
        if _is_reparse(value) or _identity(value) != self._identity:
            raise UnsafeWorkspaceError("Der Arbeitsbereich wurde extern ersetzt.")

    def capture(self, source: str | Path, *, name: str | Path | None = None) -> InputSnapshot:
        original = Path(source).expanduser().resolve(strict=True)
        destination = self.child(name or ("source" + original.suffix.casefold()))
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with read_locked(original) as stream, destination.open("xb") as output:
                before = os.fstat(stream.fileno())
                digest = hashlib.sha256()
                while block := stream.read(1024 * 1024):
                    digest.update(block)
                    output.write(block)
                output.flush()
                os.fsync(output.fileno())
                after = os.fstat(stream.fileno())
                if (_identity(before), before.st_size, before.st_mtime_ns) != (
                    _identity(after), after.st_size, after.st_mtime_ns,
                ):
                    raise InputChangedError("Die Quelle wurde während des Imports verändert.")
            snapshot = InputSnapshot(original, destination, digest.hexdigest(),
                                     after.st_size, after.st_mtime_ns, _identity(after))
            snapshot.verify()
            return snapshot
        except BaseException:
            # Never remove a pre-existing destination on exclusive-open failure.
            # The workspace lease owns cleanup of any newly created partial copy.
            raise

    def close(self) -> None:
        if self._closed:
            return
        try:
            self.assert_owned()
        except BaseException:
            self._release_pins()
            raise
        if os.name == "nt":
            # Stop all native children first. Retain the root/ancestor pins while
            # removing owned children; never traverse a junction or symlink.
            for child in self.path.iterdir():
                info = child.lstat()
                if _is_reparse(info):
                    if child.is_junction():
                        child.rmdir()
                    else:
                        child.unlink()
                elif stat.S_ISDIR(info.st_mode):
                    shutil.rmtree(child)
                else:
                    child.unlink()
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.SetFileInformationByHandle.argtypes = (
                wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
            )
            kernel.SetFileInformationByHandle.restype = wintypes.BOOL
            delete = wintypes.BOOL(True)
            if not kernel.SetFileInformationByHandle(self._pins[-1], 4, ctypes.byref(delete), ctypes.sizeof(delete)):
                raise ctypes.WinError(ctypes.get_last_error())
            self._release_pins()  # closes the exact, now delete-pending root
        else:
            shutil.rmtree(self.path)
        self._closed = True
        with _leases_lock:
            _leases.pop(self.path, None)

    def retain(self) -> Path:
        """Transfer a completed output to the user and revoke its scratch lease."""
        self.assert_owned()
        self._release_pins()
        self._closed = True
        with _leases_lock:
            _leases.pop(self.path, None)
        return self.path

    def __enter__(self) -> OwnedWorkspace:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class OwnedTemporaryDirectory:
    """Pinned scratch storage with TemporaryDirectory's owner lifetime."""

    def __init__(self, *, prefix: str, parent=None):
        workspace = OwnedWorkspace(prefix=prefix, parent=parent)
        self.name = str(workspace.path)
        self._cleanup = weakref.finalize(self, workspace.close)

    def cleanup(self):
        self._cleanup()
