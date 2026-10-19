"""OrcaSlicer installation, catalogue roots and active-selection policy."""
from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from cooling_tower.slicers.base import existing_paths
from cooling_tower.slicers.detection.base import ActivePresetSchema, SlicerDetectionModule
from cooling_tower.slicers.models import ProfileKind, ProfileRecord


def _is_directory(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _subdirectories(path: Path) -> tuple[Path, ...]:
    try:
        return tuple(sorted(
            (p for p in path.iterdir() if _is_directory(p)),
            key=lambda p: p.name.casefold(),
        ))
    except OSError:
        return ()


class OrcaSlicerDetectionModule(SlicerDetectionModule):
    def __init__(self) -> None:
        super().__init__(
            adapter_id="orca_slicer",
            product_name="OrcaSlicer",
            implemented=True,
            orca_derived=True,
            active_preset_schema=ActivePresetSchema(
                config_names=("OrcaSlicer.conf",),
                printer_keys=("machine", "printer", "printer_preset"),
                process_keys=("process", "print", "print_preset"),
                filament_keys=("filaments", "filament", "filament_preset"),
            ),
            executable_names=("orca-slicer.exe", "OrcaSlicer.exe"),
            product_markers=("OrcaSlicer", "Orca Slicer"),
            installation_directories=("OrcaSlicer", "Orca Slicer"),
        )

    def profile_roots_for(
        self, executable: Path, *, appdata_root: Path | None,
    ) -> tuple[Path, ...]:
        portable = executable.parent / "data_dir"
        bases = [appdata_root / "OrcaSlicer"] if appdata_root else []
        # MSIX may redirect Roaming writes into its per-user LocalCache.
        # Inspect only the exact package family belonging to this executable.
        package = next(
            (p for p in executable.parents if p.parent.name.casefold() == "windowsapps"),
            None,
        )
        local = os.environ.get("LOCALAPPDATA")
        if package is not None and local:
            parts = package.name.split("_")
            if len(parts) == 5:
                family = f"{parts[0]}_{parts[-1]}"
                bases.append(
                    Path(local) / "Packages" / family / "LocalCache"
                    / "Roaming" / "OrcaSlicer"
                )
        bases = [p for p in existing_paths(bases) if _is_directory(p)]
        if _is_directory(portable):
            bases = [portable]
        elif bases:
            def modified(base: Path) -> int:
                try:
                    return (base / "OrcaSlicer.conf").stat().st_mtime_ns
                except OSError:
                    return 0
            bases = [max(bases, key=modified)]

        bundled = executable.parent / "resources" / "profiles"
        roots: list[Path] = []
        vendors: set[str] = set()
        for base in bases:
            roots.append(base / "user")
            system = base / "system"
            active = _subdirectories(system)
            roots.extend(active)
            vendors.update(p.name for p in active)
        bundled_vendors = _subdirectories(bundled)
        if bundled_vendors:
            if vendors:
                vendors.update(("OrcaFilamentLibrary", "Custom"))
                roots.extend(bundled / vendor for vendor in sorted(vendors))
            else:
                roots.extend(bundled_vendors)
        return existing_paths(roots)

    def filter_profile_records(
        self, records: Iterable[ProfileRecord],
    ) -> tuple[ProfileRecord, ...]:
        return tuple(
            record for record in records if record.kind in {
                ProfileKind.MACHINE, ProfileKind.PROCESS, ProfileKind.FILAMENT,
            } and record.path.suffix.casefold() == ".json"
        )

    def active_config_directories(
        self, profile_roots: Iterable[Path],
    ) -> tuple[Path, ...]:
        directories = set(super().active_config_directories(profile_roots))
        for root in profile_roots:
            if root.parent.name.casefold() in {"system", "profiles"}:
                directories.add(root.parent.parent)
        return tuple(sorted(directories, key=str))

    def active_preset_payload(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        presets = payload.get("presets")
        rows = payload.get("orca_presets")
        if not isinstance(presets, Mapping):
            return payload
        # Top-level `filaments` is the installed library, never the active
        # selection. Keep this separate even when a machine snapshot is lost.
        result = {"presets": dict(presets)}
        if not isinstance(rows, list):
            return result
        machine = presets.get("machine", presets.get("printer"))
        selected = [
            row for row in rows
            if isinstance(row, Mapping) and row.get("machine") == machine
        ]
        if len(selected) != 1:
            return result
        # Orca 2.4 stores process/filament per machine, with null global
        # filaments. Never borrow the first/last row of a different machine.
        merged = dict(presets)
        for key in ("process", "filament", "filaments", "nozzle_diameter"):
            if key in selected[0]:
                merged[key] = selected[0][key]
        numbered = sorted(
            ((key, value) for key, value in selected[0].items()
             if re.fullmatch(r"filament_(?:preset_)?\d+", key)),
            key=lambda item: int(item[0].rsplit("_", 1)[1]),
        )
        if numbered:
            first = selected[0].get("filament")
            filaments = (
                [value for value in first if isinstance(value, str)]
                if isinstance(first, list) else [first] if isinstance(first, str) else []
            )
            filaments.extend(value for _, value in numbered if isinstance(value, str))
            merged["filaments"] = filaments
        elif "filament" in selected[0]:
            merged["filaments"] = selected[0]["filament"]
        result["presets"] = merged
        return result

    def usage_marker_paths(self, *, appdata_root: Path | None) -> tuple[Path, ...]:
        if appdata_root is None:
            return ()
        return (appdata_root / "OrcaSlicer" / "OrcaSlicer.conf",)


MODULE = OrcaSlicerDetectionModule()
