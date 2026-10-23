"""Shared, behavior-preserving Orca-family CLI transport and project export."""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import replace
from pathlib import Path

from cooling_tower.models.gcode_metadata import SlicerFamily
from cooling_tower.slicers.base import BaseSlicerAdapter, environment_roots, existing_paths
from cooling_tower.slicers.errors import SlicerProcessError
from cooling_tower.slicers.detection.base import SlicerDetectionModule
from cooling_tower.slicers.detection.registry import detection_module_for
from cooling_tower.slicers.models import (
    SliceRequest, ProfileKind, ProfileRecord, SlicerCandidate,
    SlicerCapability, SlicerDiscoverySource, SlicerInstallation, SlicerSupportLevel,
)


FULL_CAPABILITIES = frozenset(
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


class OrcaFamilyAdapter(BaseSlicerAdapter):
    family = SlicerFamily.ORCA_BAMBU_ANYCUBIC
    support_level = SlicerSupportLevel.FULL
    capabilities = FULL_CAPABILITIES
    vendor_profile_directory: str | None = None
    installation_directories: tuple[str, ...] = ()
    user_directories: tuple[str, ...] = ()
    detection_module_id: str | None = None

    def __init__(
        self,
        runner=None,
        *,
        detection_module: SlicerDetectionModule | None = None,
    ) -> None:
        super().__init__(runner=runner)
        module = detection_module or detection_module_for(
            self.detection_module_id or "",
            implemented_only=True,
        )
        if module is not None:
            if not module.implemented:
                raise ValueError("A placeholder detection module cannot be used.")
            if module.adapter_id != self.adapter_id:
                raise ValueError(
                    "The detection module belongs to a different slicer adapter."
                )
            self.product_name = module.product_name
            self.executable_names = module.executable_names
            self.product_markers = module.product_markers
            self.installation_directories = module.installation_directories
        self._profile_detection_module = module

    def known_candidates(self) -> tuple[SlicerCandidate, ...]:
        candidates: list[SlicerCandidate] = []
        for root in environment_roots():
            for directory in self.installation_directories:
                for executable in self.executable_names:
                    path = root / directory / executable
                    if path.is_file():
                        candidates.append(
                            SlicerCandidate(
                                path,
                                SlicerDiscoverySource.KNOWN_PATH,
                                adapter_hint=self.adapter_id,
                            )
                        )
        return tuple(candidates)

    def profile_roots_for(self, executable: Path) -> tuple[Path, ...]:
        module = self._profile_detection_module
        if module is not None:
            appdata = os.environ.get("APPDATA")
            return module.profile_roots_for(
                executable,
                appdata_root=Path(appdata) if appdata else None,
            )

        roots: list[Path] = []
        resource_profiles = executable.parent / "resources" / "profiles"
        if self.vendor_profile_directory:
            roots.append(resource_profiles / self.vendor_profile_directory)
        roots.append(resource_profiles)
        appdata = os.environ.get("APPDATA")
        if appdata:
            for directory in self.user_directories:
                base = Path(appdata) / directory
                # Orca-family applications keep the presets visible in their
                # selectors in the active ``user`` and ``system`` catalogues.
                # Never recurse over the complete application data root here:
                # it also contains profile backups, OTA payloads, logs and
                # crash data.  Treating those historical mirrors as current
                # presets created duplicates, false user origins and broken
                # inheritance chains.
                roots.extend(
                    (
                        base / "user",
                        base / "system",
                        base / "profiles",
                    )
                )
        return existing_paths(roots)

    def discover_profiles(
        self,
        installation: SlicerInstallation,
    ) -> list[ProfileRecord]:
        records = super().discover_profiles(installation)
        module = self._profile_detection_module
        if module is None:
            return records
        return list(module.filter_profile_records(records))

    def build_slice_command(
        self,
        request: SliceRequest,
        model_path: Path,
        output_directory: Path,
        working_root: Path,
    ) -> tuple[Path, tuple[str, ...]]:
        profile = request.profile
        records = (
            *((profile.machine,) if profile.machine is not None else ()),
            *((profile.process,) if profile.process is not None else ()),
            *profile.filaments,
        )
        if request.purpose == "calibration" and any(
            not record.metadata.get("temporary") for record in records
        ):
            raise SlicerProcessError(
                "Sicherheitsabbruch: Fuer Kalibrierung duerfen dem Slicer nur "
                "temporaere Profilkopien uebergeben werden."
            )
        settings_records = tuple(
            record
            for record in (profile.machine, profile.process)
            if record is not None
        )
        if len(settings_records) != 2:
            raise SlicerProcessError(
                "Für das CLI-Slicing fehlt ein vollständiges Maschinen-/Prozessprofil."
            )
        isolated_data = working_root / "slicer_data"
        isolated_data.mkdir(parents=True, exist_ok=True)
        cli_profiles = working_root / "effective_profiles"
        cli_profiles.mkdir(parents=True, exist_ok=True)
        settings = tuple(
            self._materialize_cli_profile(record, cli_profiles, index)
            for index, record in enumerate(settings_records)
        )
        filaments = tuple(
            self._materialize_cli_profile(record, cli_profiles, index)
            for index, record in enumerate(profile.filaments)
        )
        arguments: list[str] = [
            "--datadir",
            str(isolated_data),
            "--load-settings",
            ";".join(str(path) for path in settings),
        ]
        if filaments:
            arguments.extend(
                (
                    "--load-filaments",
                    ";".join(str(path) for path in filaments),
                )
            )
        if request.use_cli_assemble_list:
            if request.purpose != "calibration" or not request.preserve_model_positions:
                raise SlicerProcessError(
                    "Eine feste CLI-Objektliste ist nur für den gemeinsamen "
                    "Kalibrierungsslice zulässig."
                )
            arguments.extend(("--load-assemble-list", str(model_path)))
        elif not request.preserve_model_positions:
            arguments.extend(("--arrange", "1", "--ensure-on-bed"))
        arguments.extend(
            (
                "--slice",
                "0",
                "--outputdir",
                str(output_directory),
            )
        )
        if not request.use_cli_assemble_list:
            arguments.append(str(model_path))
        return profile.installation.executable_path, tuple(arguments)

    def create_joint_project(
        self,
        request: SliceRequest,
        source_model_path: Path,
        tower_model_path: Path,
        destination: Path,
        *,
        occupied: object,
        placement: object,
        tower_full_infill: bool,
        tower_supports_disabled: bool = False,
        source_supports_enabled: bool = False,
    ) -> object:
        """Let the CLI create native metadata, then lock app-chosen positions."""

        from cooling_tower.calibration.joint_project import (
            JointProjectError,
            finalize_slicer_project,
        )

        project_request = replace(
            request,
            model_path=Path(source_model_path).resolve(),
            preserve_model_positions=False,
            placement_xy_mm=None,
        )
        prepared = self.prepare_slice(project_request)
        try:
            copied_tower = prepared.input_directory / Path(tower_model_path).name
            shutil.copy2(Path(tower_model_path).resolve(), copied_tower)
            arguments = list(prepared.arguments)
            try:
                option_index = arguments.index("--arrange")
            except ValueError as error:
                raise JointProjectError(
                    "Der Slicer-Aufruf enthält keine sichere Projektanordnung."
                ) from error
            native_project = prepared.working_root / "native_project.3mf"
            # A native 3MF contains the actual source and tower meshes, not
            # merely reusable metadata. Reusing round one's project for a
            # later radius candidate silently retained the old tower geometry:
            # Anycubic then re-sliced the same first candidate, while Bambu's
            # direct calibration input used the new STL but exported the old
            # one. Always regenerate the native container for the exact pair
            # of model files. The optional path remains a latest-copy artifact,
            # never an input cache.
            native_template = request.native_project_template_path
            export_arguments = (
                *arguments[:option_index],
                "--arrange",
                "1",
                "--ensure-on-bed",
                "--export-3mf",
                str(native_project),
                str(prepared.copied_model),
                str(copied_tower),
            )
            outcome = self.runner.run(
                prepared.executable,
                export_arguments,
                working_directory=prepared.working_root,
                timeout_s=request.timeout_s,
                cancellation_event=request.cancellation_event,
            )
            if outcome.cancelled or outcome.timed_out or outcome.crashed or outcome.return_code != 0 or not native_project.is_file():
                self._write_failure_diagnostic(
                    request, outcome, "Die native gemeinsame Projekterstellung ist fehlgeschlagen oder wurde abgebrochen.",
                    working_root=prepared.working_root,
                )
                details = (outcome.stderr or outcome.stdout).strip()
                if len(details) > 1000:
                    details = details[-1000:]
                raise JointProjectError(
                    "Der Slicer hat das gemeinsame 3MF nicht akzeptiert."
                    + (f" Slicer-Ausgabe: {details}" if details else "")
                )
            if native_template is not None:
                native_template.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(native_project, native_template)
            return finalize_slicer_project(
                native_project,
                prepared.copied_model,
                copied_tower,
                destination,
                occupied=occupied,
                placement=placement,
                tower_full_infill=tower_full_infill,
                tower_supports_disabled=tower_supports_disabled,
                source_supports_enabled=source_supports_enabled,
                **({"source_support_settings": self.source_support_simulation_settings(request.profile)}
                   if source_supports_enabled and callable(getattr(self, "source_support_simulation_settings", None))
                   else {}),
            )
        finally:
            self.cleanup_prepared_slice(prepared)

    @staticmethod
    def _materialize_cli_profile(
        record: ProfileRecord,
        destination_root: Path,
        index: int,
    ) -> Path:
        """Create a typed, read-only-source profile copy for Orca-family CLIs.

        GUI-created user presets commonly omit ``type`` because their parent
        catalogue supplies it. The standalone CLI rejects those same files
        with ``unknown config type``. Supplying a typed copy in the isolated
        working directory mirrors the GUI catalogue context without changing
        any slicer-owned file.
        """

        if record.kind not in {
            ProfileKind.MACHINE,
            ProfileKind.PROCESS,
            ProfileKind.FILAMENT,
        }:
            raise SlicerProcessError(
                f"Profil '{record.name}' besitzt keinen CLI-fähigen Typ."
            )
        try:
            payload = json.loads(record.path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise SlicerProcessError(
                f"Profil '{record.name}' konnte nicht sicher für den CLI-Lauf "
                "vorbereitet werden."
            ) from error
        if not isinstance(payload, dict):
            raise SlicerProcessError(
                f"Profil '{record.name}' besitzt kein gültiges JSON-Objekt."
            )
        declared_type = str(payload.get("type", "")).strip().casefold()
        if declared_type and declared_type != record.kind.value:
            raise SlicerProcessError(
                f"Profil '{record.name}' meldet den widersprüchlichen Typ "
                f"'{declared_type}'."
            )
        payload["type"] = record.kind.value
        destination = destination_root / f"{record.kind.value}_{index}.json"
        destination.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return destination.resolve()
