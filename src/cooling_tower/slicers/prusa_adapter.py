from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from cooling_tower.models.gcode_metadata import SlicerFamily
from cooling_tower.slicers.base import (
    BaseSlicerAdapter,
    PreparedSlice,
    environment_roots,
    existing_paths,
)
from cooling_tower.slicers.errors import SlicerProcessError
from cooling_tower.slicers.models import (
    EffectiveProfile,
    ProfileCandidate,
    ProfileKind,
    ProfileRecord,
    SliceRequest,
    SliceResult,
    SlicerCandidate,
    SlicerCapability,
    SlicerDiscoverySource,
    SlicerInstallation,
    SlicerSupportLevel,
)
from cooling_tower.slicers.process import ProcessOutcome

if TYPE_CHECKING:
    from cooling_tower.slicers.prusa_profile_catalog import PrusaProfileCatalog


PRUSA_CAPABILITIES = frozenset(
    {
        SlicerCapability.PROFILE_INVENTORY,
        SlicerCapability.CLI_SLICE,
        SlicerCapability.CUSTOM_PROFILES,
        SlicerCapability.OUTPUT_DIRECTORY,
        SlicerCapability.AUTO_ARRANGE,
        SlicerCapability.GCODE_METADATA,
        SlicerCapability.PROCESS_CANCELLATION,
    }
)


class PrusaSlicerAdapter(BaseSlicerAdapter):
    adapter_id = "prusa_slicer"
    product_name = "PrusaSlicer"
    family = SlicerFamily.PRUSA_SLIC3R
    support_level = SlicerSupportLevel.FULL
    executable_names = ("prusa-slicer.exe", "PrusaSlicer.exe")
    product_markers = ("PrusaSlicer", "Prusa Slicer")
    capabilities = PRUSA_CAPABILITIES

    def __init__(
        self,
        runner=None,
        *,
        profile_catalog: PrusaProfileCatalog | None = None,
    ) -> None:
        super().__init__(runner=runner)
        if profile_catalog is None:
            from cooling_tower.slicers.prusa_profile_catalog import (
                PrusaProfileCatalog,
            )

            profile_catalog = PrusaProfileCatalog()
        self._profile_catalog = profile_catalog

    def known_candidates(self) -> tuple[SlicerCandidate, ...]:
        result: list[SlicerCandidate] = []
        for root in environment_roots():
            for directory in ("Prusa3D", "PrusaSlicer", "PrusaSlicer 2.9.0"):
                for executable in self.executable_names:
                    paths = (
                        root / directory / executable,
                        root / directory / "PrusaSlicer" / executable,
                    )
                    for path in paths:
                        if path.is_file():
                            result.append(
                                SlicerCandidate(
                                    path,
                                    SlicerDiscoverySource.KNOWN_PATH,
                                    adapter_hint=self.adapter_id,
                                )
                            )
        return tuple(result)

    def profile_roots_for(self, executable: Path) -> tuple[Path, ...]:
        from cooling_tower.slicers.detection.registry import detection_module_for

        appdata = os.environ.get("APPDATA")
        module = detection_module_for(self.adapter_id)
        if module is None:
            return existing_paths(
                (executable.parent / "resources" / "profiles",)
            )
        return module.profile_roots_for(
            executable,
            appdata_root=Path(appdata) if appdata else None,
        )
    def discover_profiles(
        self,
        installation: SlicerInstallation,
    ) -> list[ProfileRecord]:
        from cooling_tower.slicers.detection.registry import detection_module_for

        records = self._profile_catalog.discover_profiles(installation)
        module = detection_module_for(self.adapter_id)
        if module is None:
            return list(records)
        return list(module.filter_profile_records(records))

    def resolve_profile_bundle(
        self,
        candidate: ProfileCandidate,
    ) -> EffectiveProfile:
        from cooling_tower.slicers.profile_inventory import (
            ProfileInheritanceResolver,
        )
        from cooling_tower.slicers.profile_models import ProfileInventory

        inventory = ProfileInventory(
            installation=candidate.installation,
            records=tuple(self.discover_profiles(candidate.installation)),
            file_states=(),
            fingerprint_sha256="",
        )
        resolver = ProfileInheritanceResolver(inventory, self)
        effective: dict[str, object] = {}
        notes: list[str] = []
        machine = candidate.machine
        for record in (
            *((candidate.machine,) if candidate.machine is not None else ()),
            *((candidate.process,) if candidate.process is not None else ()),
            *candidate.filaments,
            *candidate.definitions,
        ):
            resolved = resolver.resolve(record)
            if not resolved.valid:
                details = " ".join(resolved.errors)
                raise SlicerProcessError(
                    f"Das PrusaSlicer-Profil '{record.name}' konnte nicht "
                    "vollständig aufgelöst werden. "
                    + details
                )
            effective.update(resolved.effective_values)
            if record.kind is ProfileKind.MACHINE and len(resolved.chain) > 1:
                notes.append(
                    f"Maschinenprofil '{record.name}' mit "
                    f"{len(resolved.chain) - 1} geerbten Basisprofil(en) geladen."
                )
        return EffectiveProfile(
            installation=candidate.installation,
            machine=machine,
            process=candidate.process,
            filaments=candidate.filaments,
            definitions=candidate.definitions,
            effective_values=effective,
            resolution_notes=tuple(notes),
        )

    def profile_values(self, record: ProfileRecord) -> dict[str, object]:
        return self._profile_catalog.profile_values(record)

    def select_profile_parents(
        self,
        candidates: tuple[ProfileRecord, ...],
        child: ProfileRecord,
    ) -> tuple[ProfileRecord, ...]:
        return self._profile_catalog.select_parent_records(candidates, child)

    def build_slice_command(
        self,
        request: SliceRequest,
        model_path: Path,
        output_directory: Path,
        working_root: Path,
    ) -> tuple[Path, tuple[str, ...]]:
        if (
            request.profile.machine is None
            or request.profile.process is None
            or not request.profile.filaments
        ):
            raise SlicerProcessError(
                "Für PrusaSlicer werden ein Maschinen-, Prozess- und "
                "mindestens ein Filamentprofil benötigt."
            )
        temporary_config = working_root / "phase14_effective_profile.ini"
        lines: list[str] = []
        effective_values = {
            str(key): value
            for key, value in request.profile.effective_values.items()
            if str(key).casefold() != "binary_gcode"
        }
        effective_values.update(
            {
                str(key): value
                for key, value in request.temporary_overrides.items()
                if str(key).casefold() != "binary_gcode"
            }
        )
        # PrusaSlicer may inherit ``binary_gcode = 1`` from the selected
        # printer preset or from its application-wide defaults.  Every
        # downstream analysis and both generation modes consume ordinary
        # textual G-code, so the disposable CLI configuration must make the
        # required transport format explicit.  This affects only the
        # temporary file below and never changes a slicer-owned preset.
        effective_values["binary_gcode"] = False
        for key, value in sorted(effective_values.items()):
            if key.casefold() in {
                "inherits",
                "instantiation",
                "compatible_printers",
                "compatible_printers_condition",
                "printer_settings_id",
                "print_settings_id",
                "filament_settings_id",
                "setting_id",
                "setting_version",
            }:
                continue
            if isinstance(value, bool):
                rendered = "1" if value else "0"
            elif isinstance(value, (list, tuple)):
                rendered = ",".join(str(item) for item in value)
            elif isinstance(value, (str, int, float)):
                rendered = str(value).replace("\r\n", "\\n").replace(
                    "\n", "\\n"
                ).replace("\r", "\\r")
            else:
                continue
            lines.append(f"{key} = {rendered}")
        temporary_config.write_text("\n".join(lines) + "\n", encoding="utf-8")
        output_path = output_directory / f"{model_path.stem}.gcode"
        return request.profile.installation.executable_path, (
            "--load",
            str(temporary_config),
            "--export-gcode",
            "--output",
            str(output_path),
            str(model_path),
        )

    def finalize_slice(
        self,
        prepared: PreparedSlice,
        outcome: ProcessOutcome,
    ) -> SliceResult:
        """Reject binary Prusa output before a text-G-code consumer sees it."""

        result = super().finalize_slice(prepared, outcome)
        if not result.success or result.gcode_path is None:
            return result
        try:
            with result.gcode_path.open("rb") as handle:
                signature = handle.read(4)
        except OSError:
            return replace(
                result,
                success=False,
                gcode_path=None,
                failure_reason=(
                    "Der von PrusaSlicer erzeugte G-Code konnte nicht gelesen "
                    "und deshalb nicht sicher geprüft werden."
                ),
            )
        if signature != b"GCDE":
            return result
        return replace(
            result,
            success=False,
            gcode_path=None,
            failure_reason=(
                "PrusaSlicer hat unerwartet binären G-Code erzeugt. Bitte den "
                "Vorgang erneut starten; die Anwendung fordert für Analyse "
                "und Generierung automatisch textuellen G-Code an."
            ),
        )
