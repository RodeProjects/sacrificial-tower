from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Iterable, Protocol, Sequence

from cooling_tower.slicers.adapter import SlicerAdapter
from cooling_tower.slicers.models import (
    SlicerCandidate,
    SlicerDiscoverySource,
)
from cooling_tower.windows_process import windows_subprocess_creation_flags
from cooling_tower.slicers.windows_app_packages import discover_windows_app_packages


class CandidateDiscovery(Protocol):
    def discover(
        self,
        adapters: Sequence[SlicerAdapter],
    ) -> tuple[SlicerCandidate, ...]: ...


def deduplicate_candidates(
    candidates: Iterable[SlicerCandidate],
) -> tuple[SlicerCandidate, ...]:
    """Return candidates in discovery order with duplicate paths removed."""

    result: list[SlicerCandidate] = []
    seen: set[tuple[str, str | None]] = set()
    for candidate in candidates:
        key = (
            str(candidate.executable_path.expanduser().resolve()).casefold(),
            candidate.adapter_hint,
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return tuple(result)


def _clean_registry_path(value: object) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().strip('"')
    text = re.sub(r",-?\d+$", "", text).strip().strip('"')
    match = re.match(r'^"([^"]+\.exe)"', value.strip(), re.IGNORECASE)
    if match:
        text = match.group(1)
    elif ".exe" in text.casefold():
        end = text.casefold().find(".exe") + 4
        text = text[:end].strip().strip('"')
    return Path(os.path.expandvars(text)).expanduser()


class WindowsSlicerDiscovery:
    """Bounded Windows discovery: registry, app packages, paths and shortcuts."""

    def discover(
        self,
        adapters: Sequence[SlicerAdapter],
    ) -> tuple[SlicerCandidate, ...]:
        candidates: list[SlicerCandidate] = []
        candidates.extend(self._registry_uninstall_candidates(adapters))
        candidates.extend(self._app_paths_candidates(adapters))
        candidates.extend(discover_windows_app_packages(adapters))
        for adapter in adapters:
            # Windows exposes compatibility junctions and protected folders
            # below otherwise readable application roots.  A denied folder
            # belonging to one adapter must not discard candidates already
            # found for every other slicer.
            try:
                candidates.extend(adapter.known_candidates())
            except OSError:
                continue
        candidates.extend(self._start_menu_candidates(adapters))
        return deduplicate_candidates(candidates)

    def _registry_uninstall_candidates(
        self,
        adapters: Sequence[SlicerAdapter],
    ) -> tuple[SlicerCandidate, ...]:
        if os.name != "nt":
            return ()
        try:
            import winreg
        except ImportError:
            return ()

        locations = (
            (
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                SlicerDiscoverySource.REGISTRY_SYSTEM,
                winreg.KEY_WOW64_64KEY,
            ),
            (
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                SlicerDiscoverySource.REGISTRY_SYSTEM,
                winreg.KEY_WOW64_32KEY,
            ),
            (
                winreg.HKEY_CURRENT_USER,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                SlicerDiscoverySource.REGISTRY_USER,
                0,
            ),
        )
        result: list[SlicerCandidate] = []
        for hive, key_path, source, view in locations:
            try:
                root = winreg.OpenKey(hive, key_path, 0, winreg.KEY_READ | view)
            except OSError:
                continue
            try:
                index = 0
                while True:
                    try:
                        name = winreg.EnumKey(root, index)
                    except OSError:
                        break
                    index += 1
                    try:
                        entry = winreg.OpenKey(root, name)
                    except OSError:
                        continue
                    try:
                        display = self._query(entry, "DisplayName")
                        version = self._query(entry, "DisplayVersion")
                        icon = self._query(entry, "DisplayIcon")
                        location = self._query(entry, "InstallLocation")
                    finally:
                        winreg.CloseKey(entry)
                    matched = self._matching_adapters(adapters, display)
                    for adapter in matched:
                        paths: list[Path] = []
                        icon_path = _clean_registry_path(icon)
                        if icon_path is not None:
                            paths.append(icon_path)
                        location_path = _clean_registry_path(location)
                        if location_path is not None:
                            paths.extend(
                                location_path / executable
                                for executable in adapter.executable_names
                            )
                        for path in paths:
                            if path.is_file():
                                result.append(
                                    SlicerCandidate(
                                        path,
                                        source,
                                        adapter_hint=adapter.adapter_id,
                                        product_hint=(
                                            str(display) if display else None
                                        ),
                                        version_hint=(
                                            str(version) if version else None
                                        ),
                                    )
                                )
            finally:
                winreg.CloseKey(root)
        return tuple(result)

    def _app_paths_candidates(
        self,
        adapters: Sequence[SlicerAdapter],
    ) -> tuple[SlicerCandidate, ...]:
        if os.name != "nt":
            return ()
        try:
            import winreg
        except ImportError:
            return ()
        roots = (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER)
        result: list[SlicerCandidate] = []
        for adapter in adapters:
            for executable in adapter.executable_names:
                key_path = (
                    "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\"
                    + executable
                )
                for hive in roots:
                    key = None
                    try:
                        key = winreg.OpenKey(hive, key_path)
                        value, _ = winreg.QueryValueEx(key, None)
                    except OSError:
                        continue
                    finally:
                        try:
                            if key is None:
                                continue
                            winreg.CloseKey(key)
                        except OSError:
                            pass
                    path = _clean_registry_path(value)
                    if path is not None and path.is_file():
                        result.append(
                            SlicerCandidate(
                                path,
                                SlicerDiscoverySource.APP_PATHS,
                                adapter_hint=adapter.adapter_id,
                            )
                        )
        return tuple(result)

    @staticmethod
    def _query(key, name: str):
        try:
            import winreg

            return winreg.QueryValueEx(key, name)[0]
        except OSError:
            return None

    @staticmethod
    def _matching_adapters(
        adapters: Sequence[SlicerAdapter],
        display_name: object,
    ) -> tuple[SlicerAdapter, ...]:
        if not isinstance(display_name, str):
            return ()
        folded = display_name.casefold()
        return tuple(
            adapter
            for adapter in adapters
            if adapter.product_name.casefold() in folded
            or adapter.adapter_id.replace("_", " ") in folded
            or any(
                Path(name).stem.casefold() in folded
                for name in adapter.executable_names
            )
        )

    def _start_menu_candidates(
        self,
        adapters: Sequence[SlicerAdapter],
    ) -> tuple[SlicerCandidate, ...]:
        if os.name != "nt":
            return ()
        roots = tuple(
            Path(value)
            for value in (
                os.environ.get("PROGRAMDATA"),
                os.environ.get("APPDATA"),
            )
            if value
        )
        result: list[SlicerCandidate] = []
        for root in roots:
            start_menu = root / "Microsoft" / "Windows" / "Start Menu" / "Programs"
            if not start_menu.is_dir():
                continue
            try:
                shortcuts = tuple(start_menu.rglob("*.lnk"))
            except OSError:
                continue
            for shortcut in shortcuts:
                matched = self._matching_adapters(adapters, shortcut.stem)
                if not matched:
                    continue
                target = self._resolve_shortcut(shortcut)
                if target is None or not target.is_file():
                    continue
                for adapter in matched:
                    result.append(
                        SlicerCandidate(
                            target,
                            SlicerDiscoverySource.START_MENU,
                            adapter_hint=adapter.adapter_id,
                            product_hint=shortcut.stem,
                        )
                    )
        return tuple(result)

    @staticmethod
    def _resolve_shortcut(shortcut: Path) -> Path | None:
        script = (
            "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($args[0]);"
            "[Console]::Out.Write($s.TargetPath)"
        )
        creation_flags = windows_subprocess_creation_flags(
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
        try:
            completed = subprocess.run(
                (
                    "powershell.exe",
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    script,
                    str(shortcut),
                ),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=3.0,
                shell=False,
                creationflags=creation_flags,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        value = completed.stdout.strip()
        return Path(value).expanduser() if value else None


class StaticCandidateDiscovery:
    """Small deterministic source used by tests and embedded deployments."""

    def __init__(self, candidates: Iterable[SlicerCandidate]) -> None:
        self.candidates = tuple(candidates)

    def discover(
        self,
        adapters: Sequence[SlicerAdapter],
    ) -> tuple[SlicerCandidate, ...]:
        return self.candidates
