"""Read-only discovery of known slicer executables in registered Windows apps."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path, PureWindowsPath
from typing import Sequence

from cooling_tower.diagnostic_context import record_diagnostic
from cooling_tower.slicers.adapter import SlicerAdapter
from cooling_tower.slicers.models import SlicerCandidate, SlicerDiscoverySource
from cooling_tower.windows_process import windows_subprocess_creation_flags


PACKAGE_LOOKUP_TIMEOUT_S = 12.0
MAXIMUM_PACKAGE_RESPONSE_BYTES = 1024 * 1024

_PACKAGE_LOOKUP_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$executableNames = [Console]::In.ReadToEnd() | ConvertFrom-Json
$records = @(foreach ($package in @(Get-AppxPackage)) {
        if ($package.IsResourcePackage -or $package.IsFramework) { continue }
        try {
            $manifest = Get-AppxPackageManifest -Package $package.PackageFullName
            foreach ($application in @($manifest.Package.Applications.Application)) {
                if (-not $application.Executable) { continue }
                if ([IO.Path]::GetFileName([string]$application.Executable) -notin $executableNames) { continue }
                [PSCustomObject]@{
                    package_name = $package.Name
                    version = [string]$package.Version
                    install_location = $package.InstallLocation
                    executable = [string]$application.Executable
                }
            }
        } catch { continue }
})
ConvertTo-Json -InputObject @($records) -Depth 4 -Compress
"""


def _package_adapters(adapters: Sequence[SlicerAdapter]) -> dict[str, SlicerAdapter]:
    known = {}
    for adapter in adapters:
        for name in getattr(adapter, "executable_names", ()):
            known[name.casefold()] = adapter
    return known


def _package_candidates(records: object, known: dict[str, SlicerAdapter]) -> tuple[SlicerCandidate, ...]:
    if not isinstance(records, list):
        return ()
    result = []
    for record in records:
        if not isinstance(record, dict):
            continue
        package_name = record.get("package_name")
        location = record.get("install_location")
        relative_executable = record.get("executable")
        version = record.get("version")
        if not all(isinstance(value, str) and value.strip() for value in (
            package_name, location, relative_executable,
        )):
            continue
        relative = PureWindowsPath(relative_executable)
        adapter = known.get(relative.name.casefold())
        if adapter is None:
            continue
        if (
            relative.drive or relative.root or ".." in relative.parts
            or relative.name.casefold() not in {name.casefold() for name in adapter.executable_names}
        ):
            continue
        try:
            root = Path(location)
            if not root.is_absolute():
                continue
            root = root.resolve()
            executable = root.joinpath(*relative.parts).resolve()
            if not executable.is_relative_to(root) or not executable.is_file():
                continue
        except (OSError, ValueError):
            continue
        result.append(SlicerCandidate(
            executable, SlicerDiscoverySource.APP_PACKAGE,
            adapter_hint=adapter.adapter_id,
            product_hint=adapter.product_name,
            version_hint=version if isinstance(version, str) else None,
        ))
    return tuple(result)


def discover_windows_app_packages(adapters: Sequence[SlicerAdapter]) -> tuple[SlicerCandidate, ...]:
    if os.name != "nt":
        return ()
    known = _package_adapters(adapters)
    if not known:
        return ()
    try:
        completed = subprocess.run(
            ("powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
             "-Command", _PACKAGE_LOOKUP_SCRIPT),
            input=json.dumps(tuple(known)),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", shell=False,
            timeout=PACKAGE_LOOKUP_TIMEOUT_S,
            creationflags=windows_subprocess_creation_flags(
                getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ),
        )
        if completed.returncode != 0:
            raise ValueError("Package lookup did not complete successfully.")
        if len(completed.stdout.encode("utf-8")) > MAXIMUM_PACKAGE_RESPONSE_BYTES:
            raise ValueError("Package response exceeds the size limit.")
        return _package_candidates(json.loads(completed.stdout), known)
    except (OSError, subprocess.TimeoutExpired, ValueError) as error:
        record_diagnostic(
            "slicer_package_discovery_failed", outcome="failed",
            result_code="slicer_package_lookup_unavailable",
            error_type=type(error).__name__,
        )
        return ()
