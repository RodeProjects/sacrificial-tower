"""Atomic exports through pinned paths and an exact owned file handle."""
from contextlib import ExitStack, contextmanager
import ctypes as C
from ctypes import wintypes as W
import hashlib
import os
from pathlib import Path
import stat
import uuid

from cooling_tower.protected_io import read_locked, UnsafeWorkspaceError, OwnedWorkspace, duplicate_workspace_pin
from cooling_tower.write_policy import ensure_writable_output, ProtectedWritePathError


def _api():
    if os.name != 'nt':
        raise UnsafeWorkspaceError('Der gegen Pfadaustausch gesicherte Export benötigt Windows.')
    k = C.WinDLL('kernel32', use_last_error=True)
    k.CreateFileW.argtypes = (W.LPCWSTR, W.DWORD, W.DWORD, W.LPVOID, W.DWORD, W.DWORD, W.HANDLE)
    k.CreateFileW.restype = W.HANDLE
    k.CloseHandle.argtypes = (W.HANDLE,)
    k.SetFileInformationByHandle.argtypes = (W.HANDLE, C.c_int, W.LPVOID, W.DWORD)
    return k


@contextmanager
def _pinned_parent(parent: Path, *, ancestors=True, access=0x20):
    k, handles = _api(), []
    try:
        for path in ((*reversed(parent.parents), parent) if ancestors else (parent,)):
            before = path.lstat()
            if before.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise UnsafeWorkspaceError('Der Exportpfad enthält eine Verzeichnisverknüpfung.')
            h = duplicate_workspace_pin(path)
            if h is None:
                h = k.CreateFileW(str(path), access, 3, None, 3, 0x02200000, None)
            if h == C.c_void_p(-1).value:
                raise C.WinError(C.get_last_error())
            handles.append(h)
            after = path.lstat()
            if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino) or after.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise UnsafeWorkspaceError('Ein Exportverzeichnis wurde zwischenzeitlich ersetzt.')
        yield
    finally:
        for handle in reversed(handles):
            k.CloseHandle(handle)


class _Rename(C.Structure):
    _fields_ = [('replace', W.DWORD), ('root', W.HANDLE), ('length', W.DWORD), ('name', W.WCHAR * 1)]


def _reject_aliases(path: Path) -> None:
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ProtectedWritePathError('Der Exportpfad enthält eine Verknüpfung.')


@contextmanager
def export_parent(output_root, *, protected_files=(), protected_roots=(), pin_protected_roots_only=False):
    """Create only validated destination parents and retain all location pins."""
    requested = Path(output_root).expanduser().absolute()
    _reject_aliases(requested)
    originals = tuple(Path(path).resolve() for path in protected_files)
    roots = tuple(Path(path).resolve() for path in protected_roots)
    target = ensure_writable_output(requested, protected_files=originals, protected_roots=roots)
    with ExitStack() as pins:
        # Output ancestors are always pinned in full below. For native Windows
        # App installations, pin each concrete protected directory with actual
        # read access: their system-managed ancestors may deny traversal handles.
        # A read handle without SHARE_DELETE still prevents replacing this root.
        for path in dict.fromkeys((*roots, *(path.parent for path in originals))):
            if path.is_dir():
                pins.enter_context(_pinned_parent(path, ancestors=not pin_protected_roots_only,
                    access=1 if pin_protected_roots_only else 0x20))
        for path in originals:
            if path.is_file():
                pins.enter_context(read_locked(path))
        ancestor = target
        missing = []
        while not ancestor.is_dir():
            missing.append(ancestor)
            ancestor = ancestor.parent
        pins.enter_context(_pinned_parent(ancestor))
        for directory in reversed(missing):
            directory.mkdir(exist_ok=True)
            pins.enter_context(_pinned_parent(directory))
        yield target


@contextmanager
def export_directory(output_root, base_name: str, *, protected_files=(), protected_roots=(), pin_protected_roots_only=False):
    """Own a new, pinned export folder until all artifacts/reports are complete."""
    with export_parent(output_root, protected_files=protected_files, protected_roots=protected_roots,
                       pin_protected_roots_only=pin_protected_roots_only) as target:
        suffix = 1
        while True:
            name = base_name if suffix == 1 else f'{base_name}_{suffix}'
            try:
                work = OwnedWorkspace(parent=target, name=name)
                break
            except FileExistsError:
                suffix += 1
        try:
            yield work.path
            work.retain()
        finally:
            work.close()


def atomic_export_data(data: bytes, destination, **options) -> Path:
    """Give generated reports the same exclusive, handle-based commit boundary."""
    with OwnedWorkspace(prefix='export_report_') as work:
        source = work.child('report.txt')
        with source.open('xb') as stream:
            stream.write(data)
        return atomic_export(source, destination, expected_sha256=hashlib.sha256(data).hexdigest(), **options)


@contextmanager
def generated_file(destination, *, protected_files=(), overwrite=True):
    """Stage a generated artifact privately and publish only a complete file."""
    target = Path(destination).expanduser().absolute()
    with export_parent(target.parent, protected_files=protected_files), OwnedWorkspace(prefix='generated_') as work:
        temporary = work.child('artifact' + target.suffix)
        yield temporary
        with read_locked(temporary) as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        atomic_export(temporary, target, expected_sha256=digest,
                      protected_files=protected_files, overwrite=overwrite)


def atomic_export(source: str | Path, destination: str | Path, *, expected_sha256: str,
                  protected_files=(), protected_roots=(), overwrite: bool = False,
                  cancellation_callback=None) -> Path:
    """Publish a verified copy; failure never truncates the previous export.

    Protected original handles stay open without delete sharing throughout the
    transaction, so replacing an alias/hardlink to one fails in the filesystem.
    The new file is renamed through its own handle, never a re-looked-up name.
    """
    source = Path(source).resolve(strict=True)
    def check_cancel():
        if cancellation_callback is not None and cancellation_callback():
            raise InterruptedError('Der Export wurde abgebrochen.')
    check_cancel()
    requested = Path(destination).expanduser().absolute()
    if not requested.name or any(':' in part or part.endswith(('.', ' ')) for part in requested.parts[1:]):
        raise ProtectedWritePathError('Der Exportpfad ist unter Windows mehrdeutig.')
    originals = tuple(Path(path).resolve() for path in protected_files)
    _reject_aliases(requested)
    target = ensure_writable_output(requested, protected_roots=protected_roots, protected_files=(*originals, source))
    if not target.parent.is_dir():
        raise FileNotFoundError('Der Exportordner muss bereits vorhanden sein.')
    k, handle, committed = _api(), None, False
    with ExitStack() as stack:
        stack.enter_context(_pinned_parent(target.parent))
        # Refuse aliases in the spelling supplied by the caller as well as in
        # the normalized target. Never silently redirect an export via a link.
        _reject_aliases(requested)
        original_ids = set()
        for original in originals:
            if original.is_file():
                pinned = stack.enter_context(read_locked(original))
                info = os.fstat(pinned.fileno())
                original_ids.add((info.st_dev, info.st_ino))

        def check_destination():
            if target.exists():
                info = target.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                    raise ProtectedWritePathError('Der vorhandene Export ist keine eigenständige reguläre Datei.')
                if (info.st_dev, info.st_ino) in original_ids:
                    raise ProtectedWritePathError('Eine geschützte Originaldatei darf nicht ersetzt werden.')
                if not overwrite:
                    raise FileExistsError(target)
                with read_locked(target) as current:
                    opened = os.fstat(current.fileno())
                    if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                        raise UnsafeWorkspaceError('Die vorhandene Exportdatei wurde zwischenzeitlich ersetzt.')
                    return (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns,
                            hashlib.file_digest(current, 'sha256').hexdigest())
            return None

        previous_version = check_destination()
        temporary = target.with_name('.st-export-' + uuid.uuid4().hex + '.tmp')
        handle = k.CreateFileW(str(temporary), 0xC0010000, 1, None, 1, 0x08000080, None)
        if handle == C.c_void_p(-1).value:
            raise C.WinError(C.get_last_error())
        import msvcrt
        try:
            # The CRT owns this same handle from here onward. No path-based
            # reopening or close/replace interval exists for the temporary.
            fd = msvcrt.open_osfhandle(int(handle), os.O_RDWR | os.O_BINARY)
        except BaseException:
            delete = W.BOOL(True)
            k.SetFileInformationByHandle(handle, 4, C.byref(delete), C.sizeof(delete))
            k.CloseHandle(handle)
            raise
        with os.fdopen(fd, 'w+b') as output:
            try:
                digest = hashlib.sha256()
                with read_locked(source) as incoming:
                    while block := incoming.read(1024 * 1024):
                        check_cancel()
                        output.write(block)
                        digest.update(block)
                output.flush()
                os.fsync(output.fileno())
                if digest.hexdigest() != expected_sha256:
                    raise UnsafeWorkspaceError('Die geprüfte Exportquelle wurde zwischenzeitlich verändert.')
                output.seek(0)
                if hashlib.file_digest(output, 'sha256').hexdigest() != expected_sha256:
                    raise UnsafeWorkspaceError('Der neue Export konnte nicht fehlerfrei geschrieben werden.')
                if check_destination() != previous_version:
                    raise UnsafeWorkspaceError('Die Exportdatei wurde zwischenzeitlich verändert und bleibt erhalten.')
                check_cancel()
                encoded = str(target).encode('utf-16-le')
                size = max(C.sizeof(_Rename), _Rename.name.offset + len(encoded) + 2)
                buffer = C.create_string_buffer(size)
                rename = _Rename.from_buffer(buffer)
                rename.replace, rename.length = int(overwrite), len(encoded)
                C.memmove(C.addressof(buffer) + _Rename.name.offset, encoded, len(encoded))
                if not k.SetFileInformationByHandle(handle, 3, buffer, size):
                    raise C.WinError(C.get_last_error())
                committed = True
            finally:
                if not committed:
                    delete = W.BOOL(True)
                    # Delete the exact partial file even if its path was raced.
                    if not k.SetFileInformationByHandle(handle, 4, C.byref(delete), C.sizeof(delete)):
                        raise C.WinError(C.get_last_error())
    return target
