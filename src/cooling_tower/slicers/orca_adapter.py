"""Orca-specific profile resolution and isolated CLI integration."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from cooling_tower.slicers.detection.base import SlicerDetectionModule
from cooling_tower.slicers.errors import SlicerProcessError
from cooling_tower.slicers.models import (
    EffectiveProfile, ProfileCandidate, ProfileKind, ProfileRecord,
    SlicerInstallation, SliceRequest,
)
from cooling_tower.slicers.orca_family import OrcaFamilyAdapter
from cooling_tower.slicers.orca_profile_catalog import OrcaProfileCatalog
from cooling_tower.write_policy import ensure_writable_output


class OrcaSlicerAdapter(OrcaFamilyAdapter):
    adapter_id = "orca_slicer"
    detection_module_id = "orca_slicer"
    # Native projects preserve per-object settings in joint calibration/export.
    prefer_native_joint_project = True
    # Never probe an unidentified executable by starting its GUI.
    probe_arguments = ()

    @staticmethod
    def source_support_simulation_settings(profile: EffectiveProfile) -> dict[str, str]:
        from cooling_tower.slicers.orca_supports import simulated_support_settings
        return simulated_support_settings()

    def __init__(
        self, runner=None, *,
        detection_module: SlicerDetectionModule | None = None,
        profile_catalog: OrcaProfileCatalog | None = None,
    ) -> None:
        super().__init__(runner=runner, detection_module=detection_module)
        self._profile_catalog = profile_catalog or OrcaProfileCatalog()

    def discover_profiles(self, installation: SlicerInstallation) -> list[ProfileRecord]:
        records = self._profile_catalog.discover_profiles(installation)
        module = self._profile_detection_module
        return list(module.filter_profile_records(records)) if module else records

    def profile_values(self, record: ProfileRecord) -> dict[str, Any]:
        return self._profile_catalog.values(record.path)

    def filter_filament_options(
        self, installation: SlicerInstallation,
        profiles: tuple[ProfileRecord, ...],
    ) -> tuple[ProfileRecord, ...]:
        from cooling_tower.slicers.orca_filament_selection import filter_filament_options

        return filter_filament_options(installation, profiles)

    def select_profile_parents(
        self, candidates: tuple[ProfileRecord, ...], child: ProfileRecord,
    ) -> tuple[ProfileRecord, ...]:
        return self._profile_catalog.select_parents(candidates, child)

    def validate_output_directory(
        self, profile: EffectiveProfile, destination: str | Path,
    ) -> None:
        """Protect complete data roots, including Store-virtualized siblings."""
        roots = {
            profile.installation.executable_path.parent,
            *profile.installation.profile_roots,
        }
        for root in profile.installation.profile_roots:
            if root.name.casefold() == "user":
                roots.add(root.parent)
            elif root.parent.name.casefold() == "system":
                roots.add(root.parent.parent)
        ensure_writable_output(
            destination, protected_roots=roots,
            protected_files=profile.source_paths,
        )

    def resolve_profile_bundle(self, candidate: ProfileCandidate) -> EffectiveProfile:
        from cooling_tower.slicers.profile_inventory import ProfileInheritanceResolver
        from cooling_tower.slicers.profile_models import ProfileInventory

        if candidate.installation.adapter_id != self.adapter_id:
            raise SlicerProcessError("Die Profilauswahl gehört nicht zu OrcaSlicer.")
        inventory = ProfileInventory(
            installation=candidate.installation,
            records=tuple(self.discover_profiles(candidate.installation)),
            file_states=(), fingerprint_sha256="",
        )
        resolver = ProfileInheritanceResolver(inventory, self)
        values: dict[str, Any] = {}
        for record in (candidate.machine, candidate.process, *candidate.filaments):
            if record is None:
                continue
            resolved = resolver.resolve(record)
            if not resolved.valid:
                raise SlicerProcessError(
                    f"Das OrcaSlicer-Profil '{record.name}' kann nicht "
                    "vollständig verwendet werden. " + " ".join(resolved.errors)
                )
            values.update(resolved.effective_values)
        return EffectiveProfile(
            candidate.installation, candidate.machine, candidate.process,
            candidate.filaments, effective_values=values,
        )

    def build_slice_command(
        self, request: SliceRequest, model_path: Path,
        output_directory: Path, working_root: Path,
    ) -> tuple[Path, tuple[str, ...]]:
        for destination in (working_root, output_directory):
            self.validate_output_directory(request.profile, destination)
        if (
            request.profile.machine is None or request.profile.process is None
            or not request.profile.filaments
        ):
            raise SlicerProcessError(
                "Für OrcaSlicer müssen ein Maschinen-, ein Prozess- und "
                "mindestens ein Filamentprofil ausgewählt sein."
            )
        records = (request.profile.machine, request.profile.process, *request.profile.filaments)
        expected_kinds = (
            ProfileKind.MACHINE, ProfileKind.PROCESS,
            *(ProfileKind.FILAMENT for _ in request.profile.filaments),
        )
        if any(
            record.kind is not expected or record.adapter_id != self.adapter_id
            for record, expected in zip(records, expected_kinds)
        ):
            raise SlicerProcessError(
                "Die ausgewählten OrcaSlicer-Profile passen nicht zu ihren "
                "Profilrollen oder zur Slicer-Integration. "
                "Bitte die Profile erneut auswählen."
            )
        if any(not record.metadata.get("temporary") for record in records):
            from cooling_tower.calibration.slice_evaluator import build_calibration_profile
            temporary_profile, _ = build_calibration_profile(
                request.profile, working_root / "resolved_profiles"
            )
            request = replace(request, profile=temporary_profile)
        executable, arguments = super().build_slice_command(
            request, model_path, output_directory, working_root
        )
        settings = arguments[arguments.index("--load-settings") + 1].split(";")
        # Overrides are job-owned and apply after inheritance, to process
        # values only. Original profile files are never opened for writing.
        process_path = Path(settings[1])
        payload = json.loads(process_path.read_text(encoding="utf-8"))
        payload.update(request.temporary_overrides)
        process_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if (
            request.purpose == "calibration" and request.preserve_model_positions
            and model_path.suffix.casefold() == ".3mf"
        ):
            # Slice the durable joint project exactly as it will be reopened;
            # reloading role profiles can replace embedded project settings.
            retained: list[str] = []
            index = 0
            while index < len(arguments):
                if arguments[index] in {"--load-settings", "--load-filaments"}:
                    index += 2
                else:
                    retained.append(arguments[index])
                    index += 1
            arguments = tuple(retained)
        return executable, arguments
