from __future__ import annotations

from pathlib import Path
from typing import Iterable

from cooling_tower.slicers.base import existing_paths
from cooling_tower.slicers.detection.base import (
    ActivePresetSchema,
    SlicerDetectionModule,
)
from cooling_tower.slicers.models import ProfileKind, ProfileRecord


_DECLARED_TYPES = {
    ProfileKind.MACHINE: {"machine", "machine_model", "printer"},
    ProfileKind.PROCESS: {"process", "print", "quality"},
    ProfileKind.FILAMENT: {"filament", "material"},
}


class BambuStudioDetectionModule(SlicerDetectionModule):
    """Bambu-specific catalogue roots, profile policy and active keys."""

    def __init__(self) -> None:
        super().__init__(
            adapter_id="bambu_studio",
            product_name="Bambu Studio",
            implemented=True,
            orca_derived=True,
            active_preset_schema=ActivePresetSchema(
                config_names=("BambuStudio.conf",),
                printer_keys=("machine", "printer", "printer_preset"),
                process_keys=("process", "print", "print_preset"),
                filament_keys=("filaments", "filament", "filament_preset"),
            ),
            executable_names=("bambu-studio.exe", "BambuStudio.exe"),
            product_markers=("BambuStudio", "Bambu Studio"),
            installation_directories=("Bambu Studio", "BambuStudio"),
        )

    def profile_roots_for(
        self,
        executable: Path,
        *,
        appdata_root: Path | None,
    ) -> tuple[Path, ...]:
        # Bambu ships third-party vendor catalogues next to BBL.  Reading the
        # parent directory makes an unrelated alphabetically-first printer
        # (for example Anker M5) look like the active Bambu machine.
        bundled_bbl = executable.parent / "resources" / "profiles" / "BBL"
        roots: list[Path] = []
        if appdata_root is not None:
            base = appdata_root / "BambuStudio"
            active_system_bbl = base / "system" / "BBL"
            roots.extend(
                (
                    base / "user",
                    active_system_bbl,
                    base / "profiles" / "BBL",
                )
            )
            # Bambu's local system catalogue is the version its GUI actually
            # presents. Avoid scanning the bundled mirror as well; duplicate
            # thousands of presets add latency and can create stale ambiguity.
            if not active_system_bbl.is_dir():
                roots.append(bundled_bbl)
        else:
            roots.append(bundled_bbl)
        return existing_paths(roots)

    def filter_profile_records(
        self,
        records: Iterable[ProfileRecord],
    ) -> tuple[ProfileRecord, ...]:
        accepted: list[ProfileRecord] = []
        for record in records:
            if record.path.suffix.casefold() != ".json":
                continue
            allowed_types = _DECLARED_TYPES.get(record.kind)
            if allowed_types is None:
                continue
            declared_type = str(record.metadata.get("type", "")).casefold()
            if declared_type in allowed_types:
                accepted.append(record)
                continue
            if record.source.casefold() == "user" and not declared_type:
                # GUI-created Bambu presets inherit their type from the
                # containing catalogue and commonly omit the JSON `type`.
                accepted.append(record)
                continue
            instantiation = str(
                record.metadata.get("instantiation", "")
            ).casefold()
            if not declared_type and instantiation in {"0", "false", "no", "off"}:
                # Hidden Bambu template fragments can be inheritance parents.
                accepted.append(record)
        return tuple(accepted)

    def active_config_directories(
        self,
        profile_roots: Iterable[Path],
    ) -> tuple[Path, ...]:
        directories = set(super().active_config_directories(profile_roots))
        for root in profile_roots:
            resolved = Path(root).resolve()
            if (
                resolved.name.casefold() == "bbl"
                and resolved.parent.name.casefold() in {"system", "profiles"}
            ):
                directories.add(resolved.parent.parent)
        return tuple(directories)

    def usage_marker_paths(
        self,
        *,
        appdata_root: Path | None,
    ) -> tuple[Path, ...]:
        if appdata_root is None:
            return ()
        return (appdata_root / "BambuStudio" / "BambuStudio.conf",)


MODULE = BambuStudioDetectionModule()
