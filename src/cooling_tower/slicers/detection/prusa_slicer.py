from __future__ import annotations

from pathlib import Path
from typing import Iterable

from cooling_tower.slicers.base import existing_paths
from cooling_tower.slicers.detection.base import (
    ActivePresetSchema,
    SlicerDetectionModule,
)
from cooling_tower.slicers.models import ProfileKind, ProfileRecord


class PrusaSlicerDetectionModule(SlicerDetectionModule):
    """PrusaSlicer-specific installation, profile and active-preset policy."""

    def __init__(self) -> None:
        super().__init__(
            adapter_id="prusa_slicer",
            product_name="PrusaSlicer",
            implemented=True,
            active_preset_schema=ActivePresetSchema(
                config_names=("PrusaSlicer.ini",),
                section_names=("presets",),
                printer_keys=("printer", "printer_preset"),
                process_keys=("print", "process", "print_preset"),
                filament_keys=("filament", "filament_preset"),
                nozzle_keys=("nozzle_diameter",),
            ),
            executable_names=("prusa-slicer.exe", "PrusaSlicer.exe"),
            product_markers=("PrusaSlicer", "Prusa Slicer"),
            installation_directories=("Prusa3D", "PrusaSlicer"),
        )

    def profile_roots_for(
        self,
        executable: Path,
        *,
        appdata_root: Path | None,
    ) -> tuple[Path, ...]:
        """Return only active FFF user presets and system preset catalogues.

        PrusaSlicer also keeps caches, archive manifests, physical-printer
        connections and other INI/JSON data next to its profiles. Those paths
        are deliberately excluded from the selectable profile inventory.
        """

        roots: list[Path] = []
        if appdata_root is not None:
            base = appdata_root / "PrusaSlicer"
            for category in ("printer", "print", "filament"):
                roots.append(base / category)
                # Keep compatibility with installations that place user
                # presets beneath a dedicated user catalogue.
                roots.append(base / "user" / category)
            roots.append(base / "vendor")

        # The installation catalogue supplies all bundled vendors and is also
        # the fallback for a clean profile directory without downloaded
        # vendor repositories. A matching installed vendor copy is preferred
        # by filter_profile_records/parent resolution below.
        roots.append(executable.parent / "resources" / "profiles")
        return existing_paths(roots)

    def filter_profile_records(
        self,
        records: Iterable[ProfileRecord],
    ) -> tuple[ProfileRecord, ...]:
        """Keep FFF presets and select the current system copy of each ID."""

        accepted: list[ProfileRecord] = []
        for record in records:
            if record.path.suffix.casefold() != ".ini":
                continue
            if record.kind not in {
                ProfileKind.MACHINE,
                ProfileKind.PROCESS,
                ProfileKind.FILAMENT,
            }:
                continue

            metadata = dict(record.metadata)
            if _is_abstract_preset(record.name):
                metadata["instantiation"] = False
            accepted.append(
                record
                if metadata == record.metadata
                else ProfileRecord(
                    adapter_id=record.adapter_id,
                    profile_id=record.profile_id,
                    name=record.name,
                    kind=record.kind,
                    path=record.path,
                    source=record.source,
                    inherits=record.inherits,
                    metadata=metadata,
                )
            )

        # Keep vendor-specific abstract parents (for example each vendor's
        # own *common* block), while collapsing an installation copy and its
        # downloaded AppData mirror for the same vendor and section. Visible
        # duplicate IDs are likewise resolved in favor of the active catalog.
        groups: dict[tuple[object, ...], list[ProfileRecord]] = {}
        passthrough: list[ProfileRecord] = []
        for record in accepted:
            if record.source.casefold() != "system":
                passthrough.append(record)
                continue
            vendor = str(record.metadata.get("vendor", "")).casefold()
            abstract = _is_abstract_preset(record.name)
            key = (
                record.kind,
                record.name.casefold(),
                vendor if abstract else "visible",
            )
            groups.setdefault(key, []).append(record)

        selected = [
            min(items, key=_catalog_preference)
            for items in groups.values()
        ]
        return tuple((*passthrough, *selected))

    def active_config_directories(
        self,
        profile_roots: Iterable[Path],
    ) -> tuple[Path, ...]:
        directories = set(super().active_config_directories(profile_roots))
        for root in profile_roots:
            resolved = Path(root).resolve()
            if resolved.name.casefold() in {"printer", "print", "filament", "vendor"}:
                directories.add(resolved.parent)
        return tuple(directories)

    def usage_marker_paths(
        self,
        *,
        appdata_root: Path | None,
    ) -> tuple[Path, ...]:
        if appdata_root is None:
            return ()
        return (appdata_root / "PrusaSlicer" / "PrusaSlicer.ini",)


def _is_abstract_preset(name: str) -> bool:
    value = name.strip()
    return len(value) > 2 and value.startswith("*") and value.endswith("*")


def _catalog_preference(record: ProfileRecord) -> tuple[int, str]:
    origin = str(record.metadata.get("catalog_origin", ""))
    # PrusaSlicer updates its active vendor repository under AppData. It is
    # the authoritative current version when it mirrors a bundled preset.
    rank = 0 if origin == "active_vendor" else 1
    return rank, str(record.path).casefold()


MODULE = PrusaSlicerDetectionModule()
