"""Real published installer transition; only the dedicated authorized runner account."""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import time
from urllib.request import Request, urlopen
import winreg
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cooling_tower.update import UpdateService, parse_update_manifest
from cooling_tower.update_channel import RELEASE_REPOSITORY
from cooling_tower.version import APP_VERSION

APP_ID = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{D47169C5-9DE6-46AF-A8C9-72A394CD2949}_is1"
FLAGS = subprocess.CREATE_NO_WINDOW

def powershell(command, *, environment=None):
    return subprocess.check_output(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
        text=True, encoding="utf-8-sig", env=environment, creationflags=FLAGS, timeout=30,
    ).strip()

def installation():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APP_ID) as key:
            return (winreg.QueryValueEx(key, "DisplayVersion")[0],
                    Path(winreg.QueryValueEx(key, "InstallLocation")[0]).resolve())
    except FileNotFoundError:
        return None

def file_digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def owned_processes(executable, *, terminate=False):
    class ProcessEntry(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("usage", wintypes.DWORD),
                    ("pid", wintypes.DWORD), ("heap", ctypes.c_size_t),
                    ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
                    ("parent", wintypes.DWORD), ("priority", wintypes.LONG),
                    ("flags", wintypes.DWORD), ("name", wintypes.WCHAR * 260)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = kernel.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessEntry))
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    kernel.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    matches = []
    try:
        entry = ProcessEntry()
        entry.size = ctypes.sizeof(entry)
        present = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while present:
            if entry.name.casefold() == executable.name.casefold():
                handle = kernel.OpenProcess(0x1000 | (0x100001 if terminate else 0), False, entry.pid)
                if handle:
                    try:
                        buffer = ctypes.create_unicode_buffer(32768)
                        size = wintypes.DWORD(len(buffer))
                        if (kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size))
                                and os.path.normcase(buffer.value) == os.path.normcase(str(executable))):
                            matches.append(entry.pid)
                            if terminate and not kernel.TerminateProcess(handle, 0):
                                raise ctypes.WinError(ctypes.get_last_error())
                            if terminate and kernel.WaitForSingleObject(handle, 10000) != 0:
                                raise RuntimeError("Owned test application did not exit")
                    finally:
                        kernel.CloseHandle(handle)
            present = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    return matches

def run_installer(path, *arguments):
    subprocess.run([str(path), "/SP-", "/VERYSILENT", "/SUPPRESSMSGBOXES",
                    "/NORESTART", "/CURRENTUSER", "/NOICONS", *arguments],
                   check=True, creationflags=FLAGS, timeout=180)

def json_api(path, context):
    with urlopen(Request("https://api.github.com/" + path,
                         headers={"User-Agent": "SacrificialTower-Update-Acceptance"}),
                 context=context, timeout=60) as response:
        return json.load(response)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--expected-user-sid", required=True)
    parser.add_argument("--development-release", action="store_true")
    args = parser.parse_args()
    if not __debug__:
        raise RuntimeError("Acceptance assertions must be enabled")
    sid = powershell("[Security.Principal.WindowsIdentity]::GetCurrent().User.Value")
    if (sid != args.expected_user_sid or ctypes.windll.shell32.IsUserAnAdmin()
            or os.environ.get("GITHUB_ACTIONS") != "true"
            or not os.environ.get("RODE_RUNNER_ROOT")):
        raise RuntimeError("Only the dedicated nonadministrative official runner may install these test versions")
    if args.version != APP_VERSION:
        raise RuntimeError("Acceptance version differs from approved source")
    current = tuple(map(int, APP_VERSION.split(".")))
    if current[2] < 1:
        raise RuntimeError("No previous patch version")
    previous = f"{current[0]}.{current[1]}.{current[2]-1}"
    work = args.work_root.resolve()
    temporary = Path(os.environ["RUNNER_TEMP"]).resolve()
    if (work.parent != temporary or not work.name.startswith("tower-published-update-")
            or work.exists() or installation() is not None):
        raise RuntimeError("Fresh job directory and no existing installation required")
    work.mkdir()
    install = work / "installed"
    service = UpdateService(temporary_root=work, timeout_s=60)
    source_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    old_source = None
    for version in (previous, APP_VERSION):
        release = json_api(f"repos/{RELEASE_REPOSITORY}/releases/tags/v{version}", service._ssl_context)
        if release["draft"] or release["prerelease"] or not release["immutable"]:
            raise AssertionError("Published immutable development release required")
        if args.development_release:
            assert "Entwicklungsversion" in release["name"] and "Entwicklungsversion" in release["body"]
        reference = json_api(f"repos/{RELEASE_REPOSITORY}/git/ref/tags/v{version}", service._ssl_context)["object"]
        if reference["type"] == "tag":
            reference = json_api(f"repos/{RELEASE_REPOSITORY}/git/tags/{reference['sha']}", service._ssl_context)["object"]
        if reference["type"] != "commit":
            raise AssertionError("Source tag does not identify a commit")
        if not re.fullmatch(r"[0-9a-f]{40}", reference["sha"]):
            raise AssertionError("Invalid immutable source identity")
        if version == APP_VERSION:
            assert reference["sha"] == source_sha
        else:
            old_source = reference["sha"]
            subprocess.run(["git", "merge-base", "--is-ancestor", old_source, source_sha], check=True)
    old_manifest = f"https://github.com/{RELEASE_REPOSITORY}/releases/download/v{previous}/latest.json"
    with service._opener(service._request(old_manifest, "application/json"), timeout=60) as response:
        old_info = parse_update_manifest(response.read())
    assert old_info.version == previous
    if args.development_release:
        assert "Entwicklungsversion" in old_info.release_notes
    old_installer = service.download_installer(old_info)
    archive = work / "old-source.zip"
    subprocess.run(["git", "archive", "--format=zip", f"--output={archive}", old_source], check=True)
    old_root = work / "released-source"
    with zipfile.ZipFile(archive) as bundle:
        for entry in bundle.infolist():
            name = PurePosixPath(entry.filename)
            if name.is_absolute() or ".." in name.parts or ":" in entry.filename or stat.S_ISLNK(entry.external_attr >> 16):
                raise AssertionError("Unsafe source archive member")
        bundle.extractall(old_root)
    # This task does not change native program code. Use the exact native build
    # already produced for the approved checkout with the released old Python UI.
    native_difference = subprocess.check_output(["git", "diff", "--name-only", old_source, source_sha, "--", "*.cpp", "*.h", "*.hpp", "*.c", "*.pyx", "setup_native.py"], text=True)
    if native_difference:
        raise AssertionError("Native code changed; the previous release needs its own native build")
    for native in (ROOT / "src/cooling_tower").glob("*.pyd"):
        shutil.copy2(native, old_root / "src/cooling_tower" / native.name)
    environment = dict(os.environ, QT_QPA_PLATFORM="offscreen", COOLING_TOWER_DISABLE_SLICER_DISCOVERY="1",
                       COOLING_TOWER_USER_DATA_ROOT=str(work / "userdata"))
    owned = False
    try:
        owned = True
        run_installer(old_installer, f"/DIR={install}")
        assert installation() == (previous, install.resolve())
        before = file_digest(install / "SacrificialTower.exe")
        subprocess.run([sys.executable, str(ROOT / "scripts/published_update_gui_parent.py"),
                        "--source", str(old_root), "--work", str(work),
                        "--previous-version", previous, "--version", APP_VERSION],
                       env=environment, check=True, creationflags=FLAGS, timeout=240)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if installation() == (APP_VERSION, install.resolve()):
                statuses = list((work / "userdata/logs/updates").glob("*.status"))
                if statuses and "stage=setup_completed" in statuses[-1].read_text():
                    break
            time.sleep(0.5)
        else:
            raise AssertionError("Actual published installer did not finish the version transition")
        status = statuses[-1].read_text()
        assert status.index("stage=parent_exited") < status.index("stage=install_started")
        assert "stage=restart_started" in status
        assert (work / "userdata/update-data-canary.txt").read_text() == "preserve this test data"
        after = file_digest(install / "SacrificialTower.exe")
        assert after != before, "Installed application bytes did not change"
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            pids = owned_processes(install / "SacrificialTower.exe")
            if pids:
                break
            time.sleep(0.5)
        assert pids, "Updated frozen application did not restart"
        time.sleep(3)
        assert set(pids) & set(owned_processes(install / "SacrificialTower.exe")), "Updated application exited immediately"
        journal = work / "userdata/logs/background_jobs.jsonl"
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            records = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()] if journal.exists() else []
            if any(record.get("program_version") == APP_VERSION for record in records):
                break
            time.sleep(0.5)
        else:
            raise AssertionError("Frozen application did not report the expected program version")
        report = json.loads((work / "gui-result.json").read_text())
        report.update(source_sha=source_sha, previous_source_sha=old_source,
                      installed_versions=[previous, APP_VERSION], native_handoff_completed=True,
                      frozen_application_restarted=True, user_data_preserved=True)
        (work / "acceptance.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report), flush=True)
    finally:
        if owned and installation() and installation()[1] == install.resolve():
            # Only processes whose exact executable belongs to this fresh test
            # installation may be stopped. Regular developer installations differ
            # by Windows SID and are inaccessible to this runner account.
            owned_processes(install / "SacrificialTower.exe", terminate=True)
            uninstallers = list(install.glob("unins*.exe"))
            if len(uninstallers) != 1:
                raise AssertionError("Owned test uninstaller missing")
            run_installer(uninstallers[0])
            assert installation() is None, "Test installation was not removed"
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
