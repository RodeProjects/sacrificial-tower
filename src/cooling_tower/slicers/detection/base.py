from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from cooling_tower.slicers.models import ProfileRecord


@dataclass(frozen=True, slots=True)
class ActivePresetSchema:
    """Names used by one slicer to persist its last active preset bundle."""

    config_names: tuple[str, ...]
    section_names: tuple[str, ...] = ("presets", "preset")
    printer_keys: tuple[str, ...] = (
        "printer",
        "printer_preset",
        "active_machine",
    )
    process_keys: tuple[str, ...] = (
        "print",
        "process",
        "print_preset",
    )
    filament_keys: tuple[str, ...] = (
        "filament",
        "filament_preset",
    )
    nozzle_keys: tuple[str, ...] = ("nozzle_diameter",)


@dataclass(frozen=True, slots=True)
class SlicerDetectionModule:
    """Read-only detection policy owned by exactly one slicer integration."""

    adapter_id: str
    product_name: str
    implemented: bool
    orca_derived: bool = False
    active_preset_schema: ActivePresetSchema | None = None
    executable_names: tuple[str, ...] = ()
    product_markers: tuple[str, ...] = ()
    installation_directories: tuple[str, ...] = ()

    def profile_roots_for(
        self,
        executable: Path,
        *,
        appdata_root: Path | None,
    ) -> tuple[Path, ...]:
        return ()

    def filter_profile_records(
        self,
        records: Iterable[ProfileRecord],
    ) -> tuple[ProfileRecord, ...]:
        return tuple(records)

    def active_config_directories(
        self,
        profile_roots: Iterable[Path],
    ) -> tuple[Path, ...]:
        directories: set[Path] = set()
        for root in profile_roots:
            resolved = Path(root).resolve()
            directories.add(resolved)
            if resolved.name.casefold() in {"user", "profiles", "system"}:
                directories.add(resolved.parent)
        return tuple(directories)

    def usage_marker_paths(
        self,
        *,
        appdata_root: Path | None,
    ) -> tuple[Path, ...]:
        """Return exact, local files whose mtime reflects use of this slicer.

        Implementations deliberately expose a narrow allow-list.  Discovery
        only calls :meth:`Path.stat` for these paths: it neither reads their
        contents nor scans logs, projects or arbitrary user directories.
        """

        return ()

    def latest_usage_timestamp_ns(
        self,
        *,
        appdata_root: Path | None,
    ) -> int | None:
        timestamps: list[int] = []
        for path in self.usage_marker_paths(appdata_root=appdata_root):
            try:
                if path.is_file():
                    timestamps.append(path.stat().st_mtime_ns)
            except OSError:
                continue
        return max(timestamps, default=None)
