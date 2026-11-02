"""Windows-enforced, per-invocation LPAC boundary for native slicers.

Only application-owned copies receive ACL grants. The native image is created
suspended, its token is checked, and a non-breakaway Job Object is assigned
before any slicer instruction can run. No capability grants network access.
The temporary AppContainer profile belongs exclusively to this invocation.
"""
from __future__ import annotations

from contextlib import ExitStack
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import subprocess
import uuid


class SandboxUnavailableError(RuntimeError):
    pass


class _SidAttributes(C.Structure):
    _fields_ = (("sid", W.LPVOID), ("attributes", W.DWORD))


class _TokenGroups(C.Structure):
    _fields_ = (("count", W.DWORD), ("rows", _SidAttributes * 1))


class _StartupInfo(C.Structure):
    _fields_ = (
        ("cb", W.DWORD), ("reserved", W.LPWSTR), ("desktop", W.LPWSTR),
        ("title", W.LPWSTR), ("x", W.DWORD), ("y", W.DWORD),
        ("x_size", W.DWORD), ("y_size", W.DWORD), ("x_chars", W.DWORD),
        ("y_chars", W.DWORD), ("fill", W.DWORD), ("flags", W.DWORD),
        ("show", W.WORD), ("reserved_size", W.WORD), ("reserved_bytes", W.LPVOID),
        ("stdin", W.HANDLE), ("stdout", W.HANDLE), ("stderr", W.HANDLE),
    )


class _StartupInfoEx(C.Structure):
    _fields_ = (("startup", _StartupInfo), ("attributes", W.LPVOID))


class _ProcessInfo(C.Structure):
    _fields_ = (("process", W.HANDLE), ("thread", W.HANDLE),
                ("pid", W.DWORD), ("tid", W.DWORD))


class _Capabilities(C.Structure):
    _fields_ = (("package_sid", W.LPVOID), ("capabilities", W.LPVOID),
                ("count", W.DWORD), ("reserved", W.DWORD))


class _SecurityAttributes(C.Structure):
    _fields_ = (('length', W.DWORD), ('descriptor', W.LPVOID), ('inherit', W.BOOL))


class _GenericMapping(C.Structure):
    _fields_ = (("read", W.DWORD), ("write", W.DWORD), ("execute", W.DWORD), ("all", W.DWORD))


class _Api:
    def __init__(self) -> None:
        if os.name != "nt":
            raise SandboxUnavailableError("Der sichere native Slicerbetrieb benötigt Windows.")
        self.kernel = C.WinDLL("kernel32", use_last_error=True)
        self.security = C.WinDLL("advapi32", use_last_error=True)
        self.user = C.WinDLL("userenv", use_last_error=True)
        self.base = C.WinDLL("kernelbase", use_last_error=True)
        self.ui = C.WinDLL("user32", use_last_error=True)
        self._bind(self.kernel, "GetCurrentProcess", (), W.HANDLE)
        self._bind(self.kernel, "GetCurrentThreadId", (), W.DWORD)
        self._bind(self.kernel, "CloseHandle", (W.HANDLE,))
        self._bind(self.kernel, "LocalFree", (W.LPVOID,), W.LPVOID)
        self._bind(self.kernel, "GetStdHandle", (W.DWORD,), W.HANDLE)
        self._bind(self.kernel, "DuplicateHandle", (W.HANDLE, W.HANDLE, W.HANDLE, C.POINTER(W.HANDLE), W.DWORD, W.BOOL, W.DWORD))
        self._bind(self.kernel, "SetHandleInformation", (W.HANDLE, W.DWORD, W.DWORD))
        self._bind(self.kernel, "CreateFileW", (W.LPCWSTR, W.DWORD, W.DWORD, W.LPVOID, W.DWORD, W.DWORD, W.HANDLE), W.HANDLE)
        self._bind(self.kernel, "GetShortPathNameW", (W.LPCWSTR, W.LPWSTR, W.DWORD), W.DWORD)
        self._bind(self.kernel, "InitializeProcThreadAttributeList", (W.LPVOID, W.DWORD, W.DWORD, C.POINTER(C.c_size_t)))
        self._bind(self.kernel, "UpdateProcThreadAttribute", (W.LPVOID, W.DWORD, C.c_size_t, W.LPVOID, C.c_size_t, W.LPVOID, W.LPVOID))
        self._bind(self.kernel, "DeleteProcThreadAttributeList", (W.LPVOID,), None)
        self._bind(self.kernel, "CreateProcessW", (W.LPCWSTR, W.LPWSTR, W.LPVOID, W.LPVOID, W.BOOL, W.DWORD, W.LPVOID, W.LPCWSTR, C.POINTER(_StartupInfoEx), C.POINTER(_ProcessInfo)))
        self._bind(self.kernel, "ResumeThread", (W.HANDLE,), W.DWORD)
        self._bind(self.kernel, "WaitForSingleObject", (W.HANDLE, W.DWORD), W.DWORD)
        self._bind(self.kernel, "GetExitCodeProcess", (W.HANDLE, C.POINTER(W.DWORD)))
        self._bind(self.kernel, "TerminateProcess", (W.HANDLE, W.UINT))
        self._bind(self.security, "OpenProcessToken", (W.HANDLE, W.DWORD, C.POINTER(W.HANDLE)))
        self._bind(self.security, "CreateRestrictedToken", (W.HANDLE, W.DWORD, W.DWORD, W.LPVOID,
            W.DWORD, W.LPVOID, W.DWORD, C.POINTER(_SidAttributes), C.POINTER(W.HANDLE)))
        self._bind(self.security, "CreateProcessAsUserW", (W.HANDLE, W.LPCWSTR, W.LPWSTR, W.LPVOID,
            W.LPVOID, W.BOOL, W.DWORD, W.LPVOID, W.LPCWSTR,
            C.POINTER(_StartupInfoEx), C.POINTER(_ProcessInfo)))
        self._bind(self.security, "DuplicateTokenEx", (W.HANDLE, W.DWORD, W.LPVOID, C.c_int, C.c_int, C.POINTER(W.HANDLE)))
        self._bind(self.security, "AccessCheck", (W.LPVOID, W.HANDLE, W.DWORD, C.POINTER(_GenericMapping), W.LPVOID, C.POINTER(W.DWORD), C.POINTER(W.DWORD), C.POINTER(W.BOOL)))
        self._bind(self.security, "GetTokenInformation", (W.HANDLE, C.c_int, W.LPVOID, W.DWORD, C.POINTER(W.DWORD)))
        self._bind(self.security, "SetTokenInformation", (W.HANDLE, C.c_int, W.LPVOID, W.DWORD))
        self._bind(self.security, "GetLengthSid", (W.LPVOID,), W.DWORD)
        self._bind(self.security, "ConvertSidToStringSidW", (W.LPVOID, C.POINTER(W.LPWSTR)))
        self._bind(self.security, "ConvertStringSidToSidW", (W.LPCWSTR, C.POINTER(W.LPVOID)))
        self._bind(self.security, "ConvertStringSecurityDescriptorToSecurityDescriptorW", (W.LPCWSTR, W.DWORD, C.POINTER(W.LPVOID), C.POINTER(W.DWORD)))
        self._bind(self.security, "GetSecurityDescriptorDacl", (W.LPVOID, C.POINTER(W.BOOL), C.POINTER(W.LPVOID), C.POINTER(W.BOOL)))
        self._bind(self.security, "GetSecurityDescriptorSacl", (W.LPVOID, C.POINTER(W.BOOL), C.POINTER(W.LPVOID), C.POINTER(W.BOOL)))
        self._bind(self.security, "SetSecurityInfo", (W.HANDLE, C.c_int, W.DWORD, W.LPVOID, W.LPVOID, W.LPVOID, W.LPVOID), W.DWORD)
        self._bind(self.security, "FreeSid", (W.LPVOID,), W.LPVOID)
        self._bind(self.user, "CreateAppContainerProfile", (W.LPCWSTR, W.LPCWSTR, W.LPCWSTR, W.LPVOID, W.DWORD, C.POINTER(W.LPVOID)), C.c_long)
        self._bind(self.user, "DeriveAppContainerSidFromAppContainerName", (W.LPCWSTR, C.POINTER(W.LPVOID)), C.c_long)
        self._bind(self.user, "DeleteAppContainerProfile", (W.LPCWSTR,), C.c_long)
        self._bind(self.base, "DeriveCapabilitySidsFromName", (W.LPCWSTR, C.POINTER(W.LPVOID), C.POINTER(W.DWORD), C.POINTER(W.LPVOID), C.POINTER(W.DWORD)))
        self._bind(self.ui, "GetProcessWindowStation", (), W.HANDLE)
        self._bind(self.ui, "GetThreadDesktop", (W.DWORD,), W.HANDLE)
        self._bind(self.ui, "SetThreadDesktop", (W.HANDLE,))
        self._bind(self.ui, "GetUserObjectInformationW", (W.HANDLE, C.c_int, W.LPVOID, W.DWORD, C.POINTER(W.DWORD)))
        self._bind(self.ui, "CreateDesktopW", (W.LPCWSTR, W.LPCWSTR, W.LPVOID, W.DWORD, W.DWORD, C.POINTER(_SecurityAttributes)), W.HANDLE)
        self._bind(self.ui, "CloseDesktop", (W.HANDLE,))
        self._bind(self.ui, "CloseWindowStation", (W.HANDLE,))

    @staticmethod
    def _bind(library, name, arguments, result=W.BOOL) -> None:
        function = getattr(library, name)
        function.argtypes = arguments
        function.restype = result

    @staticmethod
    def check(success: object, operation: str | None = None) -> None:
        if not success:
            error = C.WinError(C.get_last_error())
            if operation:
                raise SandboxUnavailableError(f'{operation} fehlgeschlagen: {error}') from error
            raise error

    def token_info(self, token, kind: int):
        size = W.DWORD()
        self.security.GetTokenInformation(token, kind, None, 0, C.byref(size))
        if not size.value or size.value > 1024 * 1024:
            raise SandboxUnavailableError(f"Windows liefert keine gültige Prozessidentität (Abfrage {kind}, Fehler {C.get_last_error()}).")
        buffer = C.create_string_buffer(size.value)
        self.check(self.security.GetTokenInformation(token, kind, buffer, size, C.byref(size)))
        return buffer

    def sid_text(self, sid) -> str:
        value = W.LPWSTR()
        self.check(self.security.ConvertSidToStringSidW(sid, C.byref(value)))
        try:
            return str(value.value)
        finally:
            self.kernel.LocalFree(C.cast(value, W.LPVOID))

    def short_path(self, path: Path) -> str:
        buffer = C.create_unicode_buffer(32768)
        count = self.kernel.GetShortPathNameW(str(path), buffer, len(buffer))
        return buffer.value if 0 < count < len(buffer) else str(path)


class LpacProfile:
    """Parent-owned identity: broker cancellation cannot leak a live profile."""

    def __init__(self) -> None:
        self.api = _Api()
        self.name = "st." + uuid.uuid4().hex
        self._sid = W.LPVOID()
        self._created = False

    def __enter__(self) -> LpacProfile:
        result = self.api.user.CreateAppContainerProfile(self.name, "Sacrificial Tower slicer",
            "Temporary isolated slicing process", None, 0, C.byref(self._sid))
        if result < 0:
            raise SandboxUnavailableError(f"Windows konnte den isolierten Slicerbereich nicht erstellen ({result & 0xffffffff:08X}).")
        self._created = True
        return self

    def close(self) -> None:
        if not self._created:
            return
        result = self.api.user.DeleteAppContainerProfile(self.name)
        if result < 0:
            raise SandboxUnavailableError(f"Der eigene isolierte Slicerbereich konnte nicht vollständig entfernt werden ({result & 0xffffffff:08X}).")
        self._created = False
        self.api.security.FreeSid(self._sid)
        self._sid = W.LPVOID()

    def __exit__(self, *_: object) -> None:
        self.close()


def _assert_plain_tree(root: Path) -> None:
    import stat
    if not root.is_dir() or root.is_symlink() or root.is_junction():
        raise SandboxUnavailableError("Der isolierte Arbeitsbereich wurde ersetzt.")
    for path in root.rglob("*"):
        info = path.lstat()
        if (info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
                or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1)):
            raise SandboxUnavailableError("Verknüpfungen im isolierten Arbeitsbereich sind nicht zulässig.")


def _grant_owned(api: _Api, root: Path, sid: str, *, writable: bool, write_sid: str | None = None,
                 integrity: str = 'LW') -> None:
    """Apply grants by a pinned directory handle, only to a verified own copy."""
    _assert_plain_tree(root)
    with ExitStack() as cleanup:
        token = W.HANDLE()
        api.check(api.security.OpenProcessToken(api.kernel.GetCurrentProcess(), 8, C.byref(token)))
        cleanup.callback(api.kernel.CloseHandle, token)
        owner_buffer = api.token_info(token, 1)
        owner = C.cast(owner_buffer, C.POINTER(_SidAttributes)).contents.sid
        rights = "0x1301bf" if writable else "0x1200a9"
        extra = f'(A;OICI;{rights};;;{write_sid})' if write_sid else ''
        sddl = f"D:P(A;OICI;FA;;;{api.sid_text(owner)})(A;OICI;{rights};;;{sid}){extra}(A;OICI;FA;;;SY)S:(ML;OICI;NW;;;{integrity})"
        descriptor = W.LPVOID()
        api.check(api.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, C.byref(descriptor), None))
        cleanup.callback(api.kernel.LocalFree, descriptor)
        present, defaulted, dacl, sacl = W.BOOL(), W.BOOL(), W.LPVOID(), W.LPVOID()
        api.check(api.security.GetSecurityDescriptorDacl(descriptor, C.byref(present), C.byref(dacl), C.byref(defaulted)))
        api.check(api.security.GetSecurityDescriptorSacl(descriptor, C.byref(present), C.byref(sacl), C.byref(defaulted)))
        # The parent already holds the non-delete-sharing ownership pin. This
        # secondary ACL handle must share its DELETE access, not request it.
        handle = api.kernel.CreateFileW(str(root), 0x000E0081, 7, None, 3, 0x02200000, None)
        if handle == C.c_void_p(-1).value:
            raise C.WinError(C.get_last_error())
        cleanup.callback(api.kernel.CloseHandle, handle)
        for flags, acl, label in ((4 | 0x80000000, dacl, None), (0x10, None, sacl)):
            error = api.security.SetSecurityInfo(handle, 1, flags, None, None, acl, label)
            if error:
                raise C.WinError(error)


def _verify_token(api: _Api, process, expected_sid: str, write_sid: str) -> None:
    token = W.HANDLE()
    api.check(api.security.OpenProcessToken(process, 0xA, C.byref(token)))
    try:
        value, returned = W.DWORD(), W.DWORD()
        api.check(api.security.GetTokenInformation(token, 29, C.byref(value), C.sizeof(value), C.byref(returned)))
        if value.value != 1:
            raise SandboxUnavailableError("Windows hat den geforderten AppContainer-Schutz nicht aktiviert.")
        package_buffer = api.token_info(token, 31)
        package_sid = C.cast(package_buffer, C.POINTER(W.LPVOID)).contents.value
        if api.sid_text(package_sid) != expected_sid:
            raise SandboxUnavailableError("Der Prozess gehört nicht zum eigenen isolierten Auftrag.")
        integrity = api.token_info(token, 25)
        integrity_sid = C.cast(integrity, C.POINTER(_SidAttributes)).contents.sid
        if api.sid_text(integrity_sid) != "S-1-16-4096":
            raise SandboxUnavailableError("Der Prozess besitzt eine unerwartete Integritätsstufe.")
        restrictions = api.token_info(token, 11)
        count = C.cast(restrictions, C.POINTER(W.DWORD)).contents.value
        if count != 1 or len(restrictions) < _TokenGroups.rows.offset + C.sizeof(_SidAttributes):
            raise SandboxUnavailableError('Die eindeutige Windows-Schreibidentität fehlt.')
        row = _SidAttributes.from_buffer(restrictions, _TokenGroups.rows.offset)
        if api.sid_text(row.sid) != write_sid:
            raise SandboxUnavailableError('Der Prozess besitzt eine fremde Schreibidentität.')
        _verify_lpac_access(api, token, expected_sid, write_sid)
    finally:
        api.kernel.CloseHandle(token)


def _verify_lpac_access(api: _Api, token, package_sid: str, write_sid: str) -> None:
    """Check effective package access without touching any original resource.

    TokenIsLessPrivilegedAppContainer is not queryable through GetTokenInformation
    on all supported Windows builds. AccessCheck supplies a documented behavioral
    check: the job's own SID must grant access; ALL APPLICATION PACKAGES must not.
    Both descriptors exist only in this process's memory.
    """
    with ExitStack() as cleanup:
        impersonation = W.HANDLE()
        api.check(api.security.DuplicateTokenEx(token, 0xC, None, 2, 2, C.byref(impersonation)))
        cleanup.callback(api.kernel.CloseHandle, impersonation)
        owner_buffer = api.token_info(token, 1)
        owner = api.sid_text(C.cast(owner_buffer, C.POINTER(_SidAttributes)).contents.sid)
        mapping = _GenericMapping(0x120089, 0x120116, 0x1200A0, 0x1F01FF)
        cases = [(sids, expected, access)
                 for access in (2, 4, 0x10, 0x100, 0x10000, 0x40000, 0x80000)
                 for sids, expected in (((package_sid, write_sid), True), ((package_sid,), False),
                                       ((), False), (('S-1-15-2-1',), False),
                                       (('S-1-15-2-2',), False), (('S-1-1-0',), False),
                                       (('S-1-5-11',), False), (('S-1-5-33',), False))]
        cases += [((package_sid,), True, 1), ((package_sid,), True, 0x120089),
                  ((package_sid,), True, 0x1200A0), (('S-1-15-2-1',), False, 1),
                  (('S-1-15-2-2',), True, 0x2000000)]
        for sids, expected, access in cases:
            descriptor = W.LPVOID()
            grants = ''.join(f'(A;;FA;;;{sid})' for sid in sids)
            sddl = f"O:{owner}G:{owner}D:(A;;FA;;;{owner}){grants}"
            api.check(api.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, C.byref(descriptor), None))
            cleanup.callback(api.kernel.LocalFree, descriptor)
            privileges = C.create_string_buffer(1024)
            length, granted, allowed = W.DWORD(len(privileges)), W.DWORD(), W.BOOL()
            api.check(api.security.AccessCheck(descriptor, impersonation, access, C.byref(mapping),
                privileges, C.byref(length), C.byref(granted), C.byref(allowed)))
            if bool(allowed.value) != expected:
                raise SandboxUnavailableError(f"Die wirksame Windows-Schreibgrenze entspricht nicht dem angeforderten Schutz (Maske {access}, erwartet {expected}).")
            if access == 0x2000000 and granted.value & 0xD0116:
                raise SandboxUnavailableError('MAXIMUM_ALLOWED umgeht die Windows-Schreibbeschränkung.')


def _restrict_token(api: _Api, caller, sids: tuple[str, ...], cleanup: ExitStack):
    rows = []
    for sid in sids:
        pointer = W.LPVOID()
        api.check(api.security.ConvertStringSidToSidW(sid, C.byref(pointer)))
        cleanup.callback(api.kernel.LocalFree, pointer)
        rows.append(_SidAttributes(pointer, 0))
    array = (_SidAttributes * len(rows))(*rows)
    token = W.HANDLE()
    api.check(api.security.CreateRestrictedToken(caller, 0x9, 0, None, 0, None,
        len(rows), array, C.byref(token)), 'CreateRestrictedToken')
    cleanup.callback(api.kernel.CloseHandle, token)
    return token


def _private_desktop(api: _Api, security: _SecurityAttributes, startup: _StartupInfoEx,
                     cleanup: ExitStack) -> tuple[int, int]:
    station = api.ui.GetProcessWindowStation()
    api.check(station, 'GetProcessWindowStation')
    name = C.create_unicode_buffer(32768)
    returned = W.DWORD()
    api.check(api.ui.GetUserObjectInformationW(station, 2, name, C.sizeof(name), C.byref(returned)))
    inherited = W.HANDLE()
    # Read attributes, enumerate desktop names and access global atoms only.
    # No clipboard, screen, logoff, attribute-write or desktop-creation right.
    current = api.kernel.GetCurrentProcess()
    api.check(api.kernel.DuplicateHandle(current, station, current, C.byref(inherited), 0x23, True, 0))
    cleanup.callback(lambda: api.check(api.ui.CloseWindowStation(inherited), 'CloseWindowStation'))
    desktop_name = 'st.' + uuid.uuid4().hex
    desktop_security = _SecurityAttributes(C.sizeof(_SecurityAttributes), security.descriptor, True)
    old_desktop = api.ui.GetThreadDesktop(api.kernel.GetCurrentThreadId())
    api.check(old_desktop, 'GetThreadDesktop')
    desktop = api.ui.CreateDesktopW(desktop_name, None, None, 0, 0xF00FF, C.byref(desktop_security))
    api.check(desktop, 'CreateDesktopW')
    cleanup.callback(lambda: api.check(api.ui.CloseDesktop(desktop), 'CloseDesktop'))
    if api.ui.GetThreadDesktop(api.kernel.GetCurrentThreadId()) != old_desktop:
        api.check(api.ui.SetThreadDesktop(old_desktop), 'RestoreBrokerDesktop')
    startup.startup.desktop = name.value + '\\' + desktop_name
    return inherited.value, desktop


def _runtime_bootstrap_token(api: _Api, caller, write_sid: str, executable: Path,
        command_text: str, block, work: Path, startup: _StartupInfoEx,
        security: _SecurityAttributes, default_acl, cleanup: ExitStack):
    """Create a same-package startup identity without executing its template.

    Windows downgrades an unrestricted client token used by a restricted server
    to Identification. The trusted system-runtime phase therefore uses its own
    restricted token. Only the host receives it; it closes the handle and reverts
    before loading any native engine. The primary token never gains these SIDs.
    """
    from cooling_tower.slicers.qprocess_backend import _WindowsJobObject
    with ExitStack() as temporary:
        startup_token = _restrict_token(api, caller, (write_sid, 'S-1-1-0', 'S-1-5-33'), temporary)
        api.check(api.security.SetTokenInformation(startup_token, 6,
            C.byref(default_acl), C.sizeof(default_acl)), 'SetStartupDefaultDacl')
        template = _ProcessInfo()
        command = C.create_unicode_buffer(command_text)
        api.check(api.security.CreateProcessAsUserW(startup_token, str(executable), command,
            C.byref(security), C.byref(security), False,
            0x08000000 | 0x80000 | 0x400 | 4, block, str(work),
            C.byref(startup), C.byref(template)), 'CreateSuspendedRuntimeTemplate')
        temporary.callback(api.kernel.CloseHandle, template.process)
        temporary.callback(api.kernel.CloseHandle, template.thread)
        job = _WindowsJobObject()
        temporary.callback(job.close)
        try:
            if not job.assign(template.pid):
                raise SandboxUnavailableError('Der suspendierte Laufzeitbereich konnte nicht begrenzt werden.')
            token = W.HANDLE()
            api.check(api.security.OpenProcessToken(template.process, 0xE, C.byref(token)))
            temporary.callback(api.kernel.CloseHandle, token)
            result = W.HANDLE()
            api.check(api.security.DuplicateTokenEx(token, 0xC, None, 2, 2, C.byref(result)))
            cleanup.callback(api.kernel.CloseHandle, result)
            api.check(api.kernel.SetHandleInformation(result, 1, 1))
        finally:
            stopped = job.terminate()
            api.kernel.TerminateProcess(template.process, 1)
            waited = api.kernel.WaitForSingleObject(template.process, 5000)
            if waited != 0 or not stopped or not job.wait_for_empty():
                raise SandboxUnavailableError('Der suspendierte Laufzeitbereich wurde nicht nachweislich beendet.')
        return result


def run_lpac(spec: dict) -> int:
    """Trusted broker entry. Inputs have already been copied by the parent."""
    from cooling_tower.slicers.process import isolated_slicer_environment
    from cooling_tower.slicers.qprocess_backend import _WindowsJobObject

    api = _Api()
    root = Path(spec["root"]).resolve(strict=True)
    root_info = root.stat()
    if [root_info.st_dev, root_info.st_ino] != spec["identity"]:
        raise SandboxUnavailableError("Der isolierte Auftrag wurde zwischenzeitlich ersetzt.")
    work = root / "w"
    runtime = root / "s"
    environment_root = root / "e"
    _assert_plain_tree(root)
    redirected = isolated_slicer_environment(environment_root)
    # Do not pass account tokens, signing settings or arbitrary PATH additions
    # into an external parser. Its binaries and profiles are self-contained.
    environment = {key: value for key, value in redirected.items() if key in {
        "SystemRoot", "SYSTEMROOT", "WINDIR", "COMSPEC", "OS", "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE", "APPDATA", "LOCALAPPDATA", "HOME", "USERPROFILE",
        "TEMP", "TMP", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME",
        "COOLING_TOWER_SLICER_ISOLATED",
    }}
    environment["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    if spec.get("software_renderer"):
        cache = environment_root / "mesa-cache"
        cache.mkdir(exist_ok=True)
        environment.update(GALLIUM_DRIVER="llvmpipe", LIBGL_ALWAYS_SOFTWARE="1", MESA_SHADER_CACHE_DIR=str(cache))
    # Native slicers append their own backup hierarchy and an AppContainer
    # suffix. Short, existing paths keep those names below legacy MAX_PATH.
    for key, name in (("APPDATA", "r"), ("LOCALAPPDATA", "l"), ("HOME", "h"),
                      ("USERPROFILE", "h"), ("TEMP", "t"), ("TMP", "t")):
        path = environment_root / name
        path.mkdir(exist_ok=True)
        environment[key] = api.short_path(path)
    arguments = [str(value) for value in spec["arguments"]]
    executable = Path(spec["executable"])
    if not executable.is_file() or (runtime.exists() and not executable.resolve().is_relative_to(runtime.resolve())):
        raise SandboxUnavailableError("Die native Programmkopie ist ungültig.")
    profile_name = str(spec["profile_name"])
    import re
    if re.fullmatch(r"st\.[0-9a-f]{32}", profile_name) is None:
        raise SandboxUnavailableError("Die isolierte Prozessidentität ist ungültig.")
    package_sid = W.LPVOID()
    result = api.user.DeriveAppContainerSidFromAppContainerName(profile_name, C.byref(package_sid))
    if result < 0:
        raise SandboxUnavailableError(f"Windows konnte den isolierten Slicerbereich nicht erstellen ({result & 0xffffffff:08X}).")

    try:
        with ExitStack() as cleanup:
            cleanup.callback(api.security.FreeSid, package_sid)
            sid = api.sid_text(package_sid)
            # Package/capability SIDs cannot be restricting SIDs in
            # CreateRestrictedToken. Use a fresh, unregistered ordinary SID;
            # no outside resource can pre-grant this unpredictable identity.
            entropy = uuid.uuid4().bytes
            write_sid_text = 'S-1-5-21-' + '-'.join(str(int.from_bytes(entropy[i:i + 4], 'little')) for i in range(0, 16, 4))
            # Some native launchers canonicalize every path component. Grant
            # read/execute on our own staging ancestor, never on its originals.
            _grant_owned(api, root, sid, writable=False, integrity='S-1-16-4096')
            _grant_owned(api, work, sid, writable=True, write_sid=write_sid_text, integrity='S-1-16-4096')
            _grant_owned(api, environment_root, sid, writable=True, write_sid=write_sid_text, integrity='S-1-16-4096')
            if runtime.exists():
                _grant_owned(api, runtime, sid, writable=False, integrity='S-1-16-4096')
            capability_rows = []
            # These two platform capabilities are needed to load native GUI
            # runtimes even for CLI slicing. Neither is a network capability.
            for name in ("registryRead", "lpacAppExperience"):
                groups, values, group_count, value_count = W.LPVOID(), W.LPVOID(), W.DWORD(), W.DWORD()
                api.check(api.base.DeriveCapabilitySidsFromName(name, C.byref(groups), C.byref(group_count), C.byref(values), C.byref(value_count)))
                for pointer, count in ((groups, group_count), (values, value_count)):
                    cleanup.callback(api.kernel.LocalFree, pointer)
                    rows = C.cast(pointer, C.POINTER(W.LPVOID))
                    for index in range(count.value):
                        cleanup.callback(api.kernel.LocalFree, rows[index])
                rows = C.cast(values, C.POINTER(W.LPVOID))
                capability_rows.extend(_SidAttributes(rows[index], 4) for index in range(value_count.value))
            cap_array = (_SidAttributes * len(capability_rows))(*capability_rows)
            capabilities = _Capabilities(package_sid, C.cast(cap_array, W.LPVOID), len(capability_rows), 0)
            size = C.c_size_t()
            api.kernel.InitializeProcThreadAttributeList(None, 3, 0, C.byref(size))
            attributes = C.create_string_buffer(size.value)
            api.check(api.kernel.InitializeProcThreadAttributeList(attributes, 3, 0, C.byref(size)))
            cleanup.callback(api.kernel.DeleteProcThreadAttributeList, attributes)
            opt_out = W.DWORD(1)
            api.check(api.kernel.UpdateProcThreadAttribute(attributes, 0, 0x20009, C.byref(capabilities), C.sizeof(capabilities), None, None))
            api.check(api.kernel.UpdateProcThreadAttribute(attributes, 0, 0x2000F, C.byref(opt_out), C.sizeof(opt_out), None, None))
            inherited = []
            for standard in (-10, -11, -12):
                original = api.kernel.GetStdHandle(standard & 0xffffffff)
                if not original or original == C.c_void_p(-1).value:
                    raise SandboxUnavailableError("Der Slicer besitzt keinen sicheren Ein-/Ausgabekanal.")
                handle = W.HANDLE()
                api.check(api.kernel.DuplicateHandle(api.kernel.GetCurrentProcess(), original,
                    api.kernel.GetCurrentProcess(), C.byref(handle), 0, True, 2))
                cleanup.callback(api.kernel.CloseHandle, handle)
                inherited.append(handle.value)
            startup = _StartupInfoEx()
            startup.startup.cb = C.sizeof(startup)
            startup.startup.flags = 0x100 | 1  # explicit handles, hidden window
            startup.startup.stdin, startup.startup.stdout, startup.startup.stderr = inherited
            startup.attributes = C.cast(attributes, W.LPVOID)
            block = C.create_unicode_buffer("\0".join(f"{key}={value}" for key, value in sorted(environment.items(), key=lambda p: p[0].casefold())) + "\0\0")
            if spec.get("console_probe"):
                # CMD uses its own command grammar rather than C argv quoting.
                # This branch is exclusively for the neutral OS-boundary tests.
                permitted = Path(os.environ["SystemRoot"]) / "System32" / "cmd.exe"
                if executable.resolve() != permitted.resolve() or arguments[:3] != ["/d", "/v:off", "/c"] or len(arguments) != 4:
                    raise SandboxUnavailableError("Der native Konsolentest ist ungültig.")
                command_text = subprocess.list2cmdline([str(executable), "/d", "/v:off", "/s", "/c"]) + ' "' + arguments[-1] + '"'
            else:
                command_text = subprocess.list2cmdline([str(executable), *arguments])
            command = C.create_unicode_buffer(command_text)
            process = _ProcessInfo()
            # LPAC still permits writes to low-integrity resources explicitly
            # granted to ALL RESTRICTED APPLICATION PACKAGES. An additional
            # write-restricted token requires our per-job SID for every write.
            # It is a restricted version of the caller's primary token, so no
            # separate user credentials or administrator operation is needed.
            caller = W.HANDLE()
            api.check(api.security.OpenProcessToken(api.kernel.GetCurrentProcess(), 0x8B, C.byref(caller)), 'OpenProcessToken')
            cleanup.callback(api.kernel.CloseHandle, caller)
            restricted = _restrict_token(api, caller, (write_sid_text,), cleanup)
            low_sid = W.LPVOID()
            api.check(api.security.ConvertStringSidToSidW('S-1-16-4096', C.byref(low_sid)))
            cleanup.callback(api.kernel.LocalFree, low_sid)
            label = C.create_string_buffer(C.sizeof(_SidAttributes) + api.security.GetLengthSid(low_sid))
            mandatory = _SidAttributes.from_buffer(label)
            mandatory.sid, mandatory.attributes = C.addressof(label) + C.sizeof(_SidAttributes), 0x20
            C.memmove(mandatory.sid, low_sid, api.security.GetLengthSid(low_sid))
            api.check(api.security.SetTokenInformation(restricted, 25, label, len(label)), 'SetTokenIntegrityLevel')
            # New process/thread and unnamed runtime objects must themselves be
            # accessible to the restricted identity. This descriptor is used
            # only for newly created job objects, never an existing resource.
            owner_buffer = api.token_info(caller, 1)
            owner = api.sid_text(C.cast(owner_buffer, C.POINTER(_SidAttributes)).contents.sid)
            descriptor = W.LPVOID()
            sddl = f'O:{owner}G:{owner}D:P(A;;GA;;;{owner})(A;;GA;;;SY)(A;;GA;;;{sid})(A;;GA;;;{write_sid_text})S:(ML;;NW;;;S-1-16-4096)'
            api.check(api.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, C.byref(descriptor), None))
            cleanup.callback(api.kernel.LocalFree, descriptor)
            present, defaulted, default_acl = W.BOOL(), W.BOOL(), W.LPVOID()
            api.check(api.security.GetSecurityDescriptorDacl(descriptor, C.byref(present), C.byref(default_acl), C.byref(defaulted)))
            api.check(api.security.SetTokenInformation(restricted, 6, C.byref(default_acl), C.sizeof(default_acl)), 'SetTokenDefaultDacl')
            object_security = _SecurityAttributes(C.sizeof(_SecurityAttributes), descriptor, False)
            native_host = spec.get('native_host') is True
            if native_host:
                if spec.get('console_probe') or executable.name != 'st-slicer-host.exe':
                    raise SandboxUnavailableError('Der vertrauenswürdige Laufzeiteinstieg ist ungültig.')
                inherited.extend(_private_desktop(api, object_security, startup, cleanup))
                bootstrap = _runtime_bootstrap_token(api, caller, write_sid_text, executable,
                    command_text, block, work, startup, object_security, default_acl, cleanup)
                inherited.append(bootstrap.value)
                command = C.create_unicode_buffer(subprocess.list2cmdline(
                    [str(executable), str(bootstrap.value), *arguments]))
            elif not spec.get('console_probe'):
                raise SandboxUnavailableError('Der sichere native Laufzeiteinstieg fehlt.')
            handles = (W.HANDLE * len(inherited))(*inherited)
            api.check(api.kernel.UpdateProcThreadAttribute(attributes, 0, 0x20002,
                handles, C.sizeof(handles), None, None))
            api.check(api.security.CreateProcessAsUserW(restricted, str(executable), command,
                C.byref(object_security), C.byref(object_security), True,
                0x08000000 | 0x80000 | 0x400 | 4, block, str(work), C.byref(startup), C.byref(process)), 'CreateProcessAsUserW')
            cleanup.callback(api.kernel.CloseHandle, process.process)
            cleanup.callback(api.kernel.CloseHandle, process.thread)
            job = _WindowsJobObject()
            cleanup.callback(job.close)
            try:
                # Enforce the expected Low label on the still-suspended child.
                child_token = W.HANDLE()
                api.check(api.security.OpenProcessToken(process.process, 0x88, C.byref(child_token)), 'OpenChildToken')
                cleanup.callback(api.kernel.CloseHandle, child_token)
                api.check(api.security.SetTokenInformation(child_token, 25, label, len(label)), 'SetChildIntegrityLevel')
                _verify_token(api, process.process, sid, write_sid_text)
                if not job.assign(process.pid):
                    raise SandboxUnavailableError("Windows konnte den Slicer-Prozessbaum nicht sicher begrenzen.")
                state = {"pid": process.pid, "tid": process.tid, "lpac": True,
                    "job_assigned": True, "bootstrap_template_stopped": native_host}
                (root / "native-state.json").write_text(json.dumps(state), encoding="utf-8")
                if api.kernel.ResumeThread(process.thread) == 0xffffffff:
                    raise C.WinError(C.get_last_error())
                timeout_ms = max(1, min(int(float(spec["timeout_s"]) * 1000), 0xfffffffe))
                if api.kernel.WaitForSingleObject(process.process, timeout_ms) != 0:
                    state['timed_out'] = True
                    job.terminate()
                    api.kernel.WaitForSingleObject(process.process, 5000)
                    return 124
                code = W.DWORD()
                api.check(api.kernel.GetExitCodeProcess(process.process, C.byref(code)))
                state['exit_code'] = C.c_int32(code.value).value
                return C.c_int32(code.value).value
            finally:
                # Includes native children left behind after a successful exit.
                terminated = job.terminate()
                api.kernel.TerminateProcess(process.process, 1)
                api.kernel.WaitForSingleObject(process.process, 5000)
                if 'state' in locals():
                    state['job_stopped'] = terminated and job.wait_for_empty()
                    (root / "native-state.json").write_text(json.dumps(state), encoding="utf-8")
                    if not state['job_stopped']:
                        raise SandboxUnavailableError('Der vollständige native Prozessbaum wurde nicht nachweislich beendet.')
    finally:
        (root / "broker-stopped.json").write_text(json.dumps({"stopped": True}), encoding="utf-8")
