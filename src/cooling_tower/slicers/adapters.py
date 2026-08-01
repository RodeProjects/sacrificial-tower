from __future__ import annotations

import configparser
import json
import os
from pathlib import Path

from cooling_tower.models.gcode_metadata import SlicerFamily
from cooling_tower.slicers.base import (
    BaseSlicerAdapter,
    classify_profile_source,
    environment_roots,
    existing_paths,
)
from cooling_tower.slicers.errors import SlicerProcessError
from cooling_tower.slicers.models import (
    SliceRequest,
    EffectiveProfile,
    ProfileCandidate,
    ProfileKind,
    ProfileRecord,
    SlicerCandidate,
    SlicerCapability,
    SlicerDiscoverySource,
    SlicerInstallation,
    SlicerSupportLevel,
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
        arguments.extend(
            (
                "--arrange",
                "1",
                "--ensure-on-bed",
                "--slice",
                "0",
                "--outputdir",
                str(output_directory),
                str(model_path),
            )
        )
        return profile.installation.executable_path, tuple(arguments)

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


class AnycubicSlicerNextAdapter(OrcaFamilyAdapter):
    adapter_id = "anycubic_slicer_next"
    product_name = "Anycubic Slicer Next"
    executable_names = ("AnycubicSlicerNext.exe",)
    product_markers = ("AnycubicSlicerNext", "Anycubic Slicer Next")
    installation_directories = ("AnycubicSlicerNext",)
    user_directories = ("AnycubicSlicerNext",)
    vendor_profile_directory = "Anycubic"


class OrcaSlicerAdapter(OrcaFamilyAdapter):
    adapter_id = "orca_slicer"
    product_name = "OrcaSlicer"
    executable_names = ("orca-slicer.exe", "OrcaSlicer.exe")
    product_markers = ("OrcaSlicer", "Orca Slicer")
    installation_directories = ("OrcaSlicer", "Orca Slicer")
    user_directories = ("OrcaSlicer",)


class BambuStudioAdapter(OrcaFamilyAdapter):
    adapter_id = "bambu_studio"
    product_name = "Bambu Studio"
    executable_names = ("bambu-studio.exe", "BambuStudio.exe")
    product_markers = ("BambuStudio", "Bambu Studio")
    installation_directories = ("Bambu Studio", "BambuStudio")
    user_directories = ("BambuStudio",)


class PrusaSlicerAdapter(BaseSlicerAdapter):
    adapter_id = "prusa_slicer"
    product_name = "PrusaSlicer"
    family = SlicerFamily.PRUSA_SLIC3R
    support_level = SlicerSupportLevel.FULL
    executable_names = ("prusa-slicer.exe", "PrusaSlicer.exe")
    product_markers = ("PrusaSlicer", "Prusa Slicer")
    capabilities = FULL_CAPABILITIES

    def known_candidates(self) -> tuple[SlicerCandidate, ...]:
        result: list[SlicerCandidate] = []
        for root in environment_roots():
            for directory in ("Prusa3D", "PrusaSlicer", "PrusaSlicer 2.9.0"):
                for executable in self.executable_names:
                    paths = (root / directory / executable, root / directory / "PrusaSlicer" / executable)
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
        roots = [executable.parent / "resources" / "profiles"]
        appdata = os.environ.get("APPDATA")
        if appdata:
            roots.extend(
                (
                    Path(appdata) / "PrusaSlicer",
                    Path(appdata) / "PrusaSlicer-alpha",
                    Path(appdata) / "PrusaSlicer-beta",
                )
            )
        return existing_paths(roots)

    def discover_profiles(
        self,
        installation: SlicerInstallation,
    ) -> list[ProfileRecord]:
        records = [
            record
            for record in super().discover_profiles(installation)
            if record.path.suffix.casefold() != ".ini"
        ]
        seen: set[tuple[Path, str]] = set()
        for root in installation.profile_roots:
            if not root.is_dir():
                continue
            for path in root.rglob("*.ini"):
                parser = configparser.ConfigParser(
                    interpolation=None,
                    strict=False,
                )
                parser.optionxform = str
                try:
                    parser.read(path, encoding="utf-8-sig")
                except (OSError, UnicodeError, configparser.Error):
                    continue
                if not parser.sections():
                    continue
                for section in parser.sections():
                    folded = section.casefold()
                    if folded.startswith("printer:"):
                        kind = ProfileKind.MACHINE
                    elif folded.startswith("print:"):
                        kind = ProfileKind.PROCESS
                    elif folded.startswith("filament:"):
                        kind = ProfileKind.FILAMENT
                    else:
                        continue
                    name = section.split(":", 1)[1].strip()
                    key = (path.resolve(), section)
                    if key in seen:
                        continue
                    seen.add(key)
                    inherits = tuple(
                        value.strip()
                        for value in parser.get(
                            section,
                            "inherits",
                            fallback="",
                        ).split(";")
                        if value.strip()
                    )
                    source = classify_profile_source(installation, path)
                    records.append(
                        ProfileRecord(
                            adapter_id=self.adapter_id,
                            profile_id=name,
                            name=name,
                            kind=kind,
                            path=path,
                            source=source,
                            inherits=inherits,
                            metadata={"section": section},
                        )
                    )
        return sorted(
            records,
            key=lambda item: (item.kind.value, item.name.casefold(), str(item.path)),
        )

    def resolve_profile_bundle(
        self,
        candidate: ProfileCandidate,
    ) -> EffectiveProfile:
        inventory = self.discover_profiles(candidate.installation)
        index = {
            (record.kind, record.name.casefold()): record
            for record in inventory
        }
        effective: dict[str, object] = {}
        visited: set[tuple[Path, str]] = set()

        def merge(record: ProfileRecord) -> None:
            section = str(record.metadata.get("section", ""))
            key = (record.path, section)
            if key in visited:
                return
            visited.add(key)
            for parent_name in record.inherits:
                parent = index.get((record.kind, parent_name.casefold()))
                if parent is not None:
                    merge(parent)
            parser = configparser.ConfigParser(
                interpolation=None,
                strict=False,
            )
            parser.optionxform = str
            try:
                parser.read(record.path, encoding="utf-8-sig")
                if section and parser.has_section(section):
                    effective.update(dict(parser.items(section)))
            except (OSError, UnicodeError, configparser.Error):
                return

        for record in (
            *((candidate.machine,) if candidate.machine is not None else ()),
            *((candidate.process,) if candidate.process is not None else ()),
            *candidate.filaments,
            *candidate.definitions,
        ):
            merge(record)
        return EffectiveProfile(
            installation=candidate.installation,
            machine=candidate.machine,
            process=candidate.process,
            filaments=candidate.filaments,
            definitions=candidate.definitions,
            effective_values=effective,
        )

    def profile_values(self, record: ProfileRecord) -> dict[str, object]:
        section = str(record.metadata.get("section", ""))
        if not section:
            return super().profile_values(record)
        parser = configparser.ConfigParser(
            interpolation=None,
            strict=False,
        )
        parser.optionxform = str
        try:
            parser.read(record.path, encoding="utf-8-sig")
            if parser.has_section(section):
                return dict(parser.items(section))
        except (OSError, UnicodeError, configparser.Error):
            pass
        return {}

    def build_slice_command(
        self,
        request: SliceRequest,
        model_path: Path,
        output_directory: Path,
        working_root: Path,
    ) -> tuple[Path, tuple[str, ...]]:
        temporary_config = working_root / "phase14_effective_profile.ini"
        lines: list[str] = []
        for key, value in sorted(request.profile.effective_values.items()):
            if isinstance(value, bool):
                rendered = "1" if value else "0"
            elif isinstance(value, (list, tuple)):
                rendered = ",".join(str(item) for item in value)
            elif isinstance(value, (str, int, float)):
                rendered = str(value)
            else:
                continue
            lines.append(f"{key} = {rendered}")
        temporary_config.write_text("\n".join(lines) + "\n", encoding="utf-8")
        output_path = output_directory / f"{model_path.stem}.gcode"
        return request.profile.installation.executable_path, (
            "--load",
            str(temporary_config),
            "--output",
            str(output_path),
            str(model_path),
        )


class CuraAdapter(BaseSlicerAdapter):
    adapter_id = "cura"
    product_name = "UltiMaker Cura"
    family = SlicerFamily.CURA
    support_level = SlicerSupportLevel.FULL
    executable_names = ("UltiMaker-Cura.exe", "Cura.exe")
    product_markers = ("UltiMaker Cura", "Ultimaker Cura", "CuraEngine")
    probe_arguments = ()

    def known_candidates(self) -> tuple[SlicerCandidate, ...]:
        result: list[SlicerCandidate] = []
        for root in environment_roots():
            if not root.is_dir():
                continue
            for directory in root.glob("*Cura*"):
                for executable in self.executable_names:
                    path = directory / executable
                    if path.is_file():
                        result.append(
                            SlicerCandidate(
                                path,
                                SlicerDiscoverySource.KNOWN_PATH,
                                adapter_hint=self.adapter_id,
                            )
                        )
        return tuple(result)

    def engine_path_for(self, executable: Path) -> Path | None:
        candidates = (
            executable.parent / "CuraEngine.exe",
            executable.parent / "bin" / "CuraEngine.exe",
        )
        engine = next((path.resolve() for path in candidates if path.is_file()), None)
        if engine is None:
            return None
        outcome = self.runner.run(
            engine,
            ("--version",),
            working_directory=engine.parent,
            timeout_s=3.0,
        )
        text = f"{outcome.stdout}\n{outcome.stderr}".casefold()
        if (
            outcome.timed_out
            or outcome.cancelled
            or outcome.return_code != 0
            or "curaengine" not in text
        ):
            return None
        return engine

    def capabilities_for(
        self,
        engine_path: Path | None,
    ) -> frozenset[SlicerCapability]:
        values = {
            SlicerCapability.PROFILE_INVENTORY,
            SlicerCapability.CUSTOM_PROFILES,
        }
        if engine_path is not None:
            values.update(
                {
                    SlicerCapability.CLI_SLICE,
                    SlicerCapability.OUTPUT_DIRECTORY,
                    SlicerCapability.PROCESS_CANCELLATION,
                }
            )
        return frozenset(values)

    def profile_roots_for(self, executable: Path) -> tuple[Path, ...]:
        roots = [executable.parent / "share" / "cura" / "resources"]
        appdata = os.environ.get("APPDATA")
        if appdata:
            roots.append(Path(appdata) / "cura")
        return existing_paths(roots)

    def build_slice_command(
        self,
        request: SliceRequest,
        model_path: Path,
        output_directory: Path,
        working_root: Path,
    ) -> tuple[Path, tuple[str, ...]]:
        engine = request.profile.installation.engine_path
        if engine is None or not engine.is_file():
            raise SlicerProcessError("CuraEngine wurde nicht gefunden.")
        definitions = request.profile.definitions
        if not definitions:
            raise SlicerProcessError(
                "Für CuraEngine fehlt eine vollständige Maschinendefinition."
            )
        output_path = output_directory / f"{model_path.stem}.gcode"
        arguments: list[str] = ["slice"]
        for definition in definitions:
            arguments.extend(("-j", str(definition.path)))
        for key, value in sorted(request.profile.effective_values.items()):
            if isinstance(value, (bool, int, float, str)):
                arguments.extend(("-s", f"{key}={value}"))
        arguments.extend(("-l", str(model_path), "-o", str(output_path)))
        return engine, tuple(arguments)


class DetectionOnlyAdapter(BaseSlicerAdapter):
    support_level = SlicerSupportLevel.DETECTION_ONLY
    probe_arguments = ()
    capabilities = frozenset()

    def known_candidates(self) -> tuple[SlicerCandidate, ...]:
        result: list[SlicerCandidate] = []
        names = {
            self.product_name.casefold().replace(" ", ""),
            self.adapter_id.casefold().replace("_", ""),
        }
        for root in environment_roots():
            if not root.is_dir():
                continue
            try:
                directories = tuple(root.iterdir())
            except OSError:
                continue
            for directory in directories:
                if not directory.is_dir():
                    continue
                folded = directory.name.casefold().replace(" ", "")
                if not any(name in folded for name in names):
                    continue
                for executable in self.executable_names:
                    path = directory / executable
                    if path.is_file():
                        result.append(
                            SlicerCandidate(
                                path,
                                SlicerDiscoverySource.KNOWN_PATH,
                                adapter_hint=self.adapter_id,
                            )
                        )
        return tuple(result)

    def slice_model(self, request: SliceRequest):
        raise SlicerProcessError(
            f"{self.product_name} wird erkannt, ist aber noch nicht vollständig integriert."
        )


class IdeaMakerAdapter(DetectionOnlyAdapter):
    adapter_id = "ideamaker"
    product_name = "ideaMaker"
    family = SlicerFamily.IDEAMAKER
    executable_names = ("ideaMaker.exe",)
    product_markers = ("ideaMaker", "Raise3D")


class Simplify3DAdapter(DetectionOnlyAdapter):
    adapter_id = "simplify3d"
    product_name = "Simplify3D"
    family = SlicerFamily.SIMPLIFY3D
    executable_names = ("Simplify3D.exe",)
    product_markers = ("Simplify3D",)


def default_adapters():
    return (
        AnycubicSlicerNextAdapter(),
        OrcaSlicerAdapter(),
        BambuStudioAdapter(),
        PrusaSlicerAdapter(),
        CuraAdapter(),
        IdeaMakerAdapter(),
        Simplify3DAdapter(),
    )
