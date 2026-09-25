from __future__ import annotations

import ctypes
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from cooling_tower.write_policy import ensure_writable_output
from typing import Any, Iterable, Mapping, Sequence

from cooling_tower.diagnostic_context import record_diagnostic
from cooling_tower.models.gcode_metadata import SlicerFamily
from cooling_tower.slicers.errors import (
    SlicerProcessError,
    SlicerVerificationTimeoutError,
    UnsupportedSlicerExecutableError,
)
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
from cooling_tower.slicers.process import (
    ProcessOutcome,
    SlicerProcessRunner,
    create_slicer_process_runner,
)
from cooling_tower.windows_process import (
    WINDOWS_DLL_INITIALIZATION_FAILED,
    windows_process_status,
    windows_process_status_description,
)


_VERSION_PATTERN = re.compile(r"(?<!\d)(\d+(?:\.\d+){1,4})(?!\d)")

_SLICER_RETURN_CODE_EXPLANATIONS = {
    -100: (
        "Der Slicer konnte mit dieser Modell-/Profilkombination keinen "
        "G-Code erzeugen. Prüfe insbesondere, ob die erste Schicht eine "
        "druckbare Auflagefläche hat und ob Stützen erforderlich sind. "
        "Auch eine geschlossene (manifold) STL kann auf einer zu dünnen "
        "Spitze stehen."
    ),
    -50: (
        "Der Slicer hat die Modellgeometrie abgelehnt und konnte daraus "
        "keinen zuverlässig verarbeitbaren G-Code erzeugen."
    ),
    -61: (
        "Im wirksamen Filamentprofil ist für den gewählten Druckbett-Typ "
        "keine verwendbare Betttemperatur hinterlegt. Bitte Filamentprofil "
        "und Druckbett-Typ prüfen oder eine passende Profilkombination wählen."
    ),
    -17: (
        "Das ausgewählte Prozessprofil ist mit dem Maschinenprofil nicht "
        "kompatibel."
    ),
    -2: (
        "Der Slicer konnte mindestens eine übergebene Modell- oder "
        "Profildatei nicht laden oder nicht mit der gewählten Konfiguration "
        "verarbeiten."
    ),
    -1: "Der Slicer konnte den übergebenen Auftrag nicht verarbeiten.",
    1: "Der Slicer konnte den übergebenen Auftrag nicht verarbeiten.",
    2: (
        "Die installierte Slicer-Version hat mindestens eine für den Auftrag "
        "benötigte Kommandozeilenoption nicht akzeptiert."
    ),
}


def _slicer_output_failure_explanation(outcome: ProcessOutcome) -> str | None:
    """Extract a stable user cause while keeping raw output diagnostic-only."""

    output = f"{outcome.stderr}\n{outcome.stdout}".casefold()
    if not output.strip():
        return None
    if "no valid nozzle found" in output:
        return (
            "Bambu Studio konnte dem gemeinsamen Projekt keine gültige "
            "Düse zuordnen."
        )
    if "process not compatible with printer" in output or (
        "not compatible" in output
        and "process" in output
        and "printer" in output
    ):
        return (
            "Das ausgewählte Prozessprofil ist mit dem Maschinenprofil nicht "
            "kompatibel."
        )
    if "unknown config type" in output:
        return (
            "Mindestens ein ausgewähltes Profil besitzt keinen vom Slicer "
            "erkennbaren Profiltyp."
        )
    if any(
        marker in output
        for marker in (
            "invalid config",
            "invalid preset",
            "failed to load config",
            "cannot load config",
            "incompatible preset",
        )
    ):
        return (
            "Mindestens ein ausgewähltes Profil ist ungültig, unvollständig "
            "oder mit den übrigen Profilen nicht kompatibel."
        )
    if any(
        marker in output
        for marker in (
            "nothing to be sliced",
            "nothing to slice",
            "no object is fully inside",
            "no printable object",
        )
    ):
        return (
            "Der Slicer konnte kein druckbares Modell vollständig auf dem "
            "Druckbett platzieren."
        )
    if ("mesh" in output or "stl" in output or "geometry" in output) and any(
        marker in output
        for marker in (
            "invalid",
            "corrupt",
            "not manifold",
            "non-manifold",
            "self-intersect",
            "empty",
        )
    ):
        return (
            "Der Slicer hat die Modellgeometrie als ungültig oder nicht "
            "verarbeitbar abgelehnt."
        )
    if "out of memory" in output or "bad allocation" in output:
        return (
            "Der Slicer hatte nicht genügend Arbeitsspeicher, um das Modell "
            "zu verarbeiten."
        )
    if "permission denied" in output or "access denied" in output:
        return (
            "Der Slicer konnte auf eine benötigte Eingabe- oder Ausgabedatei "
            "nicht zugreifen."
        )
    if any(
        marker in output
        for marker in (
            "no such file",
            "file not found",
            "cannot open",
            "failed to open",
        )
    ):
        return (
            "Der Slicer konnte mindestens eine benötigte Modell- oder "
            "Profildatei nicht öffnen."
        )
    if any(
        marker in output
        for marker in (
            "unknown option",
            "unrecognized option",
            "invalid option",
        )
    ):
        return (
            "Die installierte Slicer-Version unterstützt mindestens eine für "
            "den Auftrag benötigte Kommandozeilenoption nicht."
        )
    if any(
        marker in output
        for marker in ("unhandled exception", "assertion failed", "fatal error")
    ):
        return (
            "Der Slicer hat die Verarbeitung wegen eines internen Fehlers "
            "abgebrochen."
        )
    return None


@dataclass(frozen=True, slots=True)
class PreparedSlice:
    """Prepared, transport-neutral slice job whose paths remain owned here."""

    request: SliceRequest
    working_root: Path
    input_directory: Path
    output_directory: Path
    copied_model: Path
    executable: Path
    arguments: tuple[str, ...]

    @property
    def command(self) -> tuple[str, ...]:
        return (str(self.executable), *self.arguments)


def read_windows_version_information(path: Path) -> dict[str, str]:
    """Read PE string resources without launching the executable."""

    if os.name != "nt" or not path.is_file():
        return {}
    try:
        version = ctypes.windll.version
        size = version.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return {}
        buffer = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(str(path), 0, size, buffer):
            return {}

        translations_pointer = ctypes.c_void_p()
        translations_length = ctypes.c_uint()
        translations: list[tuple[int, int]] = []
        if version.VerQueryValueW(
            buffer,
            "\\VarFileInfo\\Translation",
            ctypes.byref(translations_pointer),
            ctypes.byref(translations_length),
        ):
            count = translations_length.value // 4
            values = ctypes.cast(
                translations_pointer,
                ctypes.POINTER(ctypes.c_ushort),
            )
            translations = [
                (values[index * 2], values[index * 2 + 1])
                for index in range(count)
            ]
        if not translations:
            translations = [(0x0409, 0x04B0), (0x0409, 0x04E4)]

        result: dict[str, str] = {}
        for key in ("ProductName", "FileDescription", "FileVersion", "ProductVersion"):
            for language, codepage in translations:
                pointer = ctypes.c_void_p()
                length = ctypes.c_uint()
                query = (
                    f"\\StringFileInfo\\{language:04x}{codepage:04x}\\{key}"
                )
                if not version.VerQueryValueW(
                    buffer,
                    query,
                    ctypes.byref(pointer),
                    ctypes.byref(length),
                ):
                    continue
                value = ctypes.wstring_at(pointer, max(0, length.value - 1)).strip()
                if value:
                    result[key] = value
                    break
        return result
    except (AttributeError, OSError, ValueError):
        return {}


def _profile_kind_from_path(path: Path) -> ProfileKind:
    parts = {part.casefold() for part in path.parts}
    if "machine" in parts or "printer" in parts:
        return ProfileKind.MACHINE
    if "process" in parts or "print" in parts:
        return ProfileKind.PROCESS
    if "filament" in parts or "material" in parts:
        return ProfileKind.FILAMENT
    if "quality" in parts or "quality_changes" in parts:
        return ProfileKind.QUALITY
    if "definitions" in parts or "definition_changes" in parts:
        return ProfileKind.DEFINITION
    return ProfileKind.UNKNOWN


def _normalise_inherits(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(";") if item.strip())
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


def classify_profile_source(
    installation: SlicerInstallation,
    path: Path,
    declared_source: str = "",
) -> str:
    """Classify preset ownership conservatively from its actual location."""

    resolved = path.resolve()
    executable_root = installation.executable_path.parent.resolve()
    if executable_root == resolved or executable_root in resolved.parents:
        return "system"

    ordered_parts = tuple(part.casefold() for part in resolved.parts)
    parts = set(ordered_parts)
    if parts.intersection({"system", "resources", "vendor"}):
        return "system"
    # Anycubic Slicer Next may mirror bundled presets below ``user/default``,
    # but it can also store genuine anonymous/local user presets there.  Its
    # small sidecar distinguishes a catalogue mirror by a base id without any
    # user, sync or setting identity.  Keep the exception both adapter- and
    # metadata-scoped; the directory name alone is not sufficient evidence.
    if (
        installation.adapter_id == "anycubic_slicer_next"
        and any(
            ordered_parts[index : index + 2] == ("user", "default")
            for index in range(max(0, len(ordered_parts) - 1))
        )
        and _is_anycubic_catalogue_mirror(path)
    ):
        return "system"
    if "project" in parts or declared_source == "project":
        return "project"
    if "session" in parts or declared_source == "session":
        return "session"
    if "user" in parts or "quality_changes" in parts:
        return "user"
    appdata = os.environ.get("APPDATA")
    if appdata:
        appdata_root = Path(appdata).expanduser().resolve()
        if (
            appdata_root in resolved.parents
            and (
                declared_source == "user"
                or resolved.parent.name.casefold()
                in {"printer", "print", "filament"}
            )
        ):
            return "user"
    return "system"


def _is_anycubic_catalogue_mirror(path: Path) -> bool:
    sidecar = path.with_suffix(".info")
    try:
        if not sidecar.is_file() or sidecar.stat().st_size > 16 * 1024:
            return False
        text = sidecar.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return False
    values: dict[str, str] = {}
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key.strip().casefold()] = value.strip()
    return bool(values.get("base_id")) and not any(
        values.get(key)
        for key in ("sync_info", "user_id", "setting_id")
    )


class BaseSlicerAdapter:
    adapter_id = "base"
    product_name = "Unknown slicer"
    family = SlicerFamily.UNKNOWN
    support_level = SlicerSupportLevel.DETECTION_ONLY
    executable_names: tuple[str, ...] = ()
    product_markers: tuple[str, ...] = ()
    probe_arguments: tuple[str, ...] = ("--help",)
    probe_timeout_s = 5.0
    capabilities: frozenset[SlicerCapability] = frozenset()

    def __init__(self, runner: SlicerProcessRunner | None = None) -> None:
        self.runner = runner or create_slicer_process_runner(self.adapter_id)

    def known_candidates(self) -> tuple[SlicerCandidate, ...]:
        return ()

    def matches_candidate(self, candidate: SlicerCandidate) -> bool:
        if candidate.adapter_hint == self.adapter_id:
            return True
        filename = candidate.executable_path.name.casefold()
        if filename in {name.casefold() for name in self.executable_names}:
            return True
        hint = (candidate.product_hint or "").casefold()
        return any(marker.casefold() in hint for marker in self.product_markers)

    def verify_installation(
        self,
        candidate: SlicerCandidate | Path,
    ) -> SlicerInstallation:
        if isinstance(candidate, Path):
            candidate = SlicerCandidate(
                candidate,
                SlicerDiscoverySource.MANUAL,
                adapter_hint=self.adapter_id,
            )
        path = candidate.executable_path.expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Slicer executable not found: {path}")

        file_information = read_windows_version_information(path)
        product_evidence = " ".join(
            (
                file_information.get("ProductName", ""),
                file_information.get("FileDescription", ""),
            )
        ).strip()
        version = (
            candidate.version_hint
            or file_information.get("ProductVersion")
            or file_information.get("FileVersion")
        )
        product_verified = self._contains_product_marker(product_evidence)

        # Starting a GUI-subsystem slicer with ``--help`` can create one or
        # more visible native windows even when CREATE_NO_WINDOW is used; that
        # flag only suppresses console windows.  Automatic discovery already
        # has bounded registry/path/shortcut evidence, so validate it without
        # executing the slicer.  An explicitly selected manual file may still
        # use the process probe when its Windows version resource is missing.
        automatic_candidate = (
            candidate.discovery_source is not SlicerDiscoverySource.MANUAL
        )
        filename_matches = path.name.casefold() in {
            name.casefold() for name in self.executable_names
        }
        hint_matches = (
            candidate.adapter_hint == self.adapter_id
            and candidate.discovery_source
            in {
                SlicerDiscoverySource.KNOWN_PATH,
                SlicerDiscoverySource.APP_PATHS,
                SlicerDiscoverySource.START_MENU,
            }
        )
        product_hint_matches = self._contains_product_marker(
            candidate.product_hint or ""
        )
        if automatic_candidate and (
            filename_matches or hint_matches or product_hint_matches
        ):
            product_verified = True

        probe_outcome: ProcessOutcome | None = None
        if (
            not product_verified
            and not automatic_candidate
            and self.probe_arguments
        ):
            probe_outcome = self.runner.run(
                path,
                self.probe_arguments,
                working_directory=path.parent,
                timeout_s=self.probe_timeout_s,
            )
            if probe_outcome.timed_out:
                raise SlicerVerificationTimeoutError(
                    f"Versionsprüfung für {path.name} hat das Zeitlimit überschritten."
                )
            probe_text = f"{probe_outcome.stdout}\n{probe_outcome.stderr}"
            product_verified = self._contains_product_marker(probe_text)
            if version is None:
                version = self._extract_version(probe_text)

        if not product_verified:
            raise UnsupportedSlicerExecutableError(
                f"Die Datei {path.name} konnte nicht als {self.product_name} "
                "bestätigt werden."
            )

        roots = self.profile_roots_for(path)
        engine = self.engine_path_for(path)
        capabilities = self.capabilities_for(engine)
        return SlicerInstallation(
            adapter_id=self.adapter_id,
            product_name=self.product_name,
            version=self._normalise_version(version),
            executable_path=path,
            verified=True,
            capabilities=capabilities,
            discovery_source=candidate.discovery_source,
            family=self.family,
            support_level=self.support_level,
            profile_roots=roots,
            engine_path=engine,
        )

    def _contains_product_marker(self, value: str) -> bool:
        folded = value.casefold()
        return any(marker.casefold() in folded for marker in self.product_markers)

    @staticmethod
    def _extract_version(value: str) -> str | None:
        match = _VERSION_PATTERN.search(value)
        return match.group(1) if match else None

    @staticmethod
    def _normalise_version(value: str | None) -> str | None:
        if not value:
            return None
        match = _VERSION_PATTERN.search(value)
        return match.group(1) if match else value.strip() or None

    def profile_roots_for(self, executable: Path) -> tuple[Path, ...]:
        return ()

    def engine_path_for(self, executable: Path) -> Path | None:
        return executable

    def capabilities_for(
        self,
        engine_path: Path | None,
    ) -> frozenset[SlicerCapability]:
        return self.capabilities

    def discover_profiles(
        self,
        installation: SlicerInstallation,
    ) -> list[ProfileRecord]:
        records: list[ProfileRecord] = []
        seen: set[Path] = set()
        for root in installation.profile_roots:
            if not root.is_dir():
                continue
            for pattern in ("*.json", "*.ini", "*.cfg"):
                for path in root.rglob(pattern):
                    resolved = path.resolve()
                    if resolved in seen or not resolved.is_file():
                        continue
                    seen.add(resolved)
                    record = self._read_profile_record(installation, resolved)
                    if record is not None:
                        records.append(record)
        return sorted(
            records,
            key=lambda item: (item.kind.value, item.name.casefold(), str(item.path)),
        )

    def _read_profile_record(
        self,
        installation: SlicerInstallation,
        path: Path,
    ) -> ProfileRecord | None:
        payload: Mapping[str, Any] = {}
        if path.suffix.casefold() == ".json":
            try:
                loaded = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                return None
            if isinstance(loaded, Mapping):
                payload = loaded
        name = str(payload.get("name") or payload.get("id") or path.stem)
        profile_id = str(payload.get("id") or name)
        # Orca/Bambu/Anycubic JSON profiles use ``inherits`` for their
        # parent chain.  ``from`` describes the profile origin (for example
        # ``system`` or ``user``) and must never be interpreted as a parent
        # profile name.
        inherits = _normalise_inherits(payload.get("inherits", ()))
        declared_source = str(payload.get("from", "")).strip().casefold()
        source = classify_profile_source(
            installation,
            path,
            declared_source,
        )
        return ProfileRecord(
            adapter_id=self.adapter_id,
            profile_id=profile_id,
            name=name,
            kind=_profile_kind_from_path(path),
            path=path,
            source=source,
            inherits=inherits,
            metadata={
                key: payload[key]
                for key in (
                    "type",
                    "from",
                    "version",
                    "instantiation",
                    "setting_version",
                    "setting_id",
                    "printer_settings_id",
                    "print_settings_id",
                    "filament_settings_id",
                    "printer_model",
                    "printer_variant",
                    "printer_technology",
                    "nozzle_diameter",
                    "gcode_flavor",
                    "compatible_printers",
                    "compatible_printers_condition",
                    "printable_area",
                    "printable_height",
                    "extruder_count",
                    "minimum_slicer_version",
                    "maximum_slicer_version",
                )
                if key in payload
            },
        )
    def profile_values(self, record: ProfileRecord) -> dict[str, object]:
        return self._load_profile_values(record.path)

    def resolve_profile_bundle(
        self,
        candidate: ProfileCandidate,
    ) -> EffectiveProfile:
        if candidate.installation.adapter_id != self.adapter_id:
            raise ValueError("Profile candidate belongs to a different adapter.")
        inventory = self.discover_profiles(candidate.installation)
        index: dict[tuple[ProfileKind, str], ProfileRecord] = {}
        for record in inventory:
            index[(record.kind, record.profile_id.casefold())] = record
            index[(record.kind, record.name.casefold())] = record

        effective: dict[str, Any] = {}
        notes: list[str] = []
        machine = candidate.machine
        if machine is not None:
            chain = self._profile_chain(machine, index)
            for record in chain:
                effective.update(self._load_profile_values(record.path))
            if len(chain) > 1:
                machine = chain[0]
                notes.append(
                    "Abgeleitetes Maschinenprofil wurde auf das vollständige "
                    f"Basisprofil '{machine.name}' zurückgeführt."
                )
        for record in (
            *((candidate.process,) if candidate.process is not None else ()),
            *candidate.filaments,
            *candidate.definitions,
        ):
            for item in self._profile_chain(record, index):
                effective.update(self._load_profile_values(item.path))

        return EffectiveProfile(
            installation=candidate.installation,
            machine=machine,
            process=candidate.process,
            filaments=candidate.filaments,
            definitions=candidate.definitions,
            effective_values=effective,
            resolution_notes=tuple(notes),
        )

    @staticmethod
    def _profile_chain(
        record: ProfileRecord,
        index: Mapping[tuple[ProfileKind, str], ProfileRecord],
    ) -> tuple[ProfileRecord, ...]:
        chain: list[ProfileRecord] = []
        visited: set[Path] = set()

        def add(item: ProfileRecord) -> None:
            if item.path in visited:
                return
            visited.add(item.path)
            for parent_name in item.inherits:
                parent = index.get((item.kind, parent_name.casefold()))
                if parent is not None:
                    add(parent)
            chain.append(item)

        add(record)
        return tuple(chain)

    @staticmethod
    def _load_profile_values(path: Path) -> dict[str, Any]:
        if path.suffix.casefold() != ".json":
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, Mapping):
            return {}
        values = payload.get("setting", payload)
        return dict(values) if isinstance(values, Mapping) else {}

    def slice_model(self, request: SliceRequest) -> SliceResult:
        prepared = self.prepare_slice(request)
        try:
            outcome = self.execute_prepared_slice(prepared)
            return self.finalize_slice(prepared, outcome)
        finally:
            self.cleanup_prepared_slice(prepared)

    def prepare_slice(self, request: SliceRequest) -> PreparedSlice:
        """Copy inputs and build a command without starting an external process."""

        ensure_writable_output(request.output_directory, protected_roots=(request.profile.installation.executable_path.parent, *request.profile.installation.profile_roots))
        if request.diagnostics_root is not None:
            ensure_writable_output(request.diagnostics_root, protected_roots=(request.profile.installation.executable_path.parent, *request.profile.installation.profile_roots))
        if not request.model_path.is_file():
            raise FileNotFoundError(f"Model file not found: {request.model_path}")
        if request.profile.installation.adapter_id != self.adapter_id:
            raise ValueError("Slice request belongs to a different adapter.")
        if not request.profile.installation.can_slice:
            raise SlicerProcessError(
                f"{request.profile.installation.product_name} ist nur für die "
                "Erkennung verfügbar und kann nicht automatisiert slicen."
            )

        working_root = Path(tempfile.mkdtemp(prefix="cooling_tower_slicer_"))
        work_input = working_root / "input"
        work_output = working_root / "output"
        work_input.mkdir()
        work_output.mkdir()
        copied_model = work_input / request.model_path.name
        try:
            shutil.copy2(request.model_path, copied_model)
            # ``TEMP`` may use an 8.3 alias on Windows runners (for example
            # ``RUNNER~1``).  Resolve the copied input before constructing the
            # command so the arguments and the PreparedSlice contract expose
            # the same canonical path.
            copied_model = copied_model.resolve()
            executable, arguments = self.build_slice_command(
                request,
                copied_model,
                work_output,
                working_root,
            )
            prepared = PreparedSlice(
                request=request,
                working_root=working_root.resolve(),
                input_directory=work_input.resolve(),
                output_directory=work_output.resolve(),
                copied_model=copied_model.resolve(),
                executable=Path(executable).expanduser().resolve(),
                arguments=tuple(str(item) for item in arguments),
            )
            record_diagnostic(
                "slice_job_prepared",
                adapter=self.adapter_id,
                product_name=self.product_name,
                purpose=request.purpose,
                calibration_round=request.calibration_round,
                command=prepared.command,
            )
            return prepared
        except Exception:
            shutil.rmtree(working_root, ignore_errors=True)
            raise

    def execute_prepared_slice(
        self,
        prepared: PreparedSlice,
        *,
        runner: SlicerProcessRunner | None = None,
    ) -> ProcessOutcome:
        """Run only the transport portion of a prepared slice job."""

        request = prepared.request
        kwargs: dict[str, object] = {
            "working_directory": prepared.working_root,
            "timeout_s": request.timeout_s,
            "cancellation_event": request.cancellation_event,
        }
        selected_runner = runner or self.runner
        if getattr(selected_runner, "backend_name", None) in {"legacy", "qprocess"}:
            kwargs.update(
                {
                    "diagnostics_directory": (
                        request.diagnostics_root
                        if request.retain_failure_diagnostics
                        else None
                    ),
                    "adapter_id": self.adapter_id,
                    "product_name": self.product_name,
                    "purpose": request.purpose,
                    "calibration_round": request.calibration_round,
                }
            )
        return selected_runner.run(
            prepared.executable,
            prepared.arguments,
            **kwargs,
        )

    def finalize_slice(
        self,
        prepared: PreparedSlice,
        outcome: ProcessOutcome,
    ) -> SliceResult:
        """Validate and persist outputs after the process has fully stopped."""

        request = prepared.request
        produced = tuple(
            sorted(path for path in prepared.output_directory.rglob("*") if path.is_file())
        )
        failure_reason = self._failure_reason(outcome, produced)
        record_diagnostic(
            "slice_output_files_checked",
            adapter=self.adapter_id,
            product_name=self.product_name,
            output_file_count=len(produced),
            success=failure_reason is None,
            return_code=outcome.return_code,
            timed_out=outcome.timed_out,
            cancelled=outcome.cancelled,
            crashed=outcome.crashed,
            backend=outcome.backend,
        )
        if failure_reason is not None:
            diagnostic = self._write_failure_diagnostic(
                request,
                outcome,
                failure_reason,
            )
            record_diagnostic(
                "slice_job_failed",
                failure_reason=failure_reason,
                diagnostic_path=diagnostic,
                process_output_diagnostic_path=outcome.output_diagnostic_path,
            )
            return SliceResult(
                success=False,
                return_code=outcome.return_code,
                command=outcome.command,
                output_files=(),
                gcode_path=None,
                metadata_paths=(),
                stdout=outcome.stdout,
                stderr=outcome.stderr,
                duration_s=outcome.duration_s,
                diagnostic_path=diagnostic,
                failure_reason=failure_reason,
                timed_out=outcome.timed_out,
                cancelled=outcome.cancelled,
                crashed=outcome.crashed,
                process_backend=outcome.backend,
                stdout_truncated=outcome.stdout_truncated,
                stderr_truncated=outcome.stderr_truncated,
                process_output_diagnostic_path=outcome.output_diagnostic_path,
            )

        ensure_writable_output(
            request.output_directory,
            protected_roots=(request.profile.installation.executable_path.parent, *request.profile.installation.profile_roots),
            protected_files=request.profile.source_paths,
        )
        request.output_directory.mkdir(parents=True, exist_ok=True)
        copied_outputs: list[Path] = []
        for source in produced:
            relative = source.relative_to(prepared.output_directory)
            destination = ensure_writable_output(
                request.output_directory / relative,
                protected_roots=(request.profile.installation.executable_path.parent, *request.profile.installation.profile_roots),
                protected_files=request.profile.source_paths,
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            copied_outputs.append(destination.resolve())
        gcode_path = next(
            (
                path
                for path in copied_outputs
                if path.suffix.casefold() in {".gcode", ".gco"}
            ),
            None,
        )
        metadata_paths = tuple(
            path
            for path in copied_outputs
            if path.name.casefold().endswith(
                (".gcode.metadata", ".gco.metadata", ".metadata")
            )
        )
        return SliceResult(
            success=True,
            return_code=outcome.return_code,
            command=outcome.command,
            output_files=tuple(copied_outputs),
            gcode_path=gcode_path,
            metadata_paths=metadata_paths,
            stdout=outcome.stdout,
            stderr=outcome.stderr,
            duration_s=outcome.duration_s,
            crashed=outcome.crashed,
            process_backend=outcome.backend,
            stdout_truncated=outcome.stdout_truncated,
            stderr_truncated=outcome.stderr_truncated,
            process_output_diagnostic_path=outcome.output_diagnostic_path,
        )

    @staticmethod
    def cleanup_prepared_slice(prepared: PreparedSlice) -> None:
        shutil.rmtree(prepared.working_root, ignore_errors=True)
        record_diagnostic(
            "temporary_data_cleaned",
            temporary_kind="slicer_working_directory",
        )

    def build_slice_command(
        self,
        request: SliceRequest,
        model_path: Path,
        output_directory: Path,
        working_root: Path,
    ) -> tuple[Path, tuple[str, ...]]:
        raise SlicerProcessError(
            f"Automatisches Slicing ist für {self.product_name} nicht implementiert."
        )

    @staticmethod
    def _failure_reason(
        outcome: ProcessOutcome,
        produced: Sequence[Path],
    ) -> str | None:
        if outcome.cancelled:
            return "Der Slicervorgang wurde abgebrochen."
        if outcome.timed_out:
            return "Der Slicervorgang hat das Zeitlimit überschritten."
        output_explanation = _slicer_output_failure_explanation(outcome)
        if outcome.crashed:
            windows_status = windows_process_status(outcome.return_code)
            normalized_return_code = (
                int(outcome.return_code) & 0xFFFFFFFF
                if outcome.return_code is not None
                else None
            )
            if normalized_return_code == WINDOWS_DLL_INITIALIZATION_FAILED:
                return (
                    "Windows konnte den Slicer-Prozess nicht initialisieren, "
                    "weil eine benötigte Programmbibliothek nicht geladen "
                    "werden konnte."
                )
            if windows_status is not None:
                description = windows_process_status_description(
                    outcome.return_code
                )
                if description is not None:
                    return (
                        "Der Slicer-Prozess ist abgestürzt. Windows meldete "
                        f"als Ursache: {description}."
                    )
            return output_explanation or (
                "Der Slicer-Prozess ist aufgrund eines internen Fehlers "
                "abgestürzt."
            )
        if outcome.return_code != 0:
            # subprocess can expose DWORD exits as unsigned values, whereas
            # QProcess uses signed int. Keep both backends' messages identical.
            return_code = outcome.return_code
            if return_code is not None and 0x80000000 <= return_code <= 0xFFFFFFFF:
                return_code -= 0x100000000
            return (
                output_explanation
                or _SLICER_RETURN_CODE_EXPLANATIONS.get(return_code)
                or (
                    "Der Slicer hat den Auftrag wegen eines internen oder "
                    "nicht näher beschriebenen Verarbeitungsfehlers "
                    "abgebrochen."
                )
            )
        if not any(path.suffix.casefold() in {".gcode", ".gco"} for path in produced):
            return "Der Slicer meldete Erfolg, erzeugte aber keine G-Code-Datei."
        return None

    @staticmethod
    def _write_failure_diagnostic(
        request: SliceRequest,
        outcome: ProcessOutcome,
        failure_reason: str,
    ) -> Path | None:
        if not request.retain_failure_diagnostics:
            return None
        root = request.diagnostics_root or (
            request.output_directory.parent / "slicer_diagnostics"
        )
        root.mkdir(parents=True, exist_ok=True)
        path = root / "slicer_failure.json"
        payload = {
            "success": False,
            "failure_reason": failure_reason,
            "return_code": outcome.return_code,
            "timed_out": outcome.timed_out,
            "cancelled": outcome.cancelled,
            "crashed": outcome.crashed,
            "process_backend": outcome.backend,
            "duration_s": outcome.duration_s,
            "command": list(outcome.command),
            "stdout": outcome.stdout,
            "stderr": outcome.stderr,
            "stdout_truncated": outcome.stdout_truncated,
            "stderr_truncated": outcome.stderr_truncated,
            "process_output_diagnostic_path": (
                str(outcome.output_diagnostic_path)
                if outcome.output_diagnostic_path is not None
                else None
            ),
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path.resolve()

    def extract_layer_times(self, result: SliceResult) -> tuple[float, ...]:
        if not result.success or result.gcode_path is None:
            return ()
        from cooling_tower.services.analysis_service import GCodeAnalysisService

        snapshot = GCodeAnalysisService().analyze(result.gcode_path, force=True)
        return tuple(layer.total_time_s for layer in snapshot.layers)

    def validate_process_backends(
        self,
        request: SliceRequest,
        *,
        report_path: str | Path | None = None,
    ):
        """Compare legacy and QProcess semantics for this specific adapter."""

        from cooling_tower.slicers.validation import validate_adapter_backends

        return validate_adapter_backends(self, request, report_path=report_path)


def environment_roots() -> tuple[Path, ...]:
    values = (
        os.environ.get("ProgramW6432"),
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
        os.environ.get("LOCALAPPDATA"),
    )
    roots: list[Path] = []
    for value in values:
        if not value:
            continue
        path = Path(value).expanduser()
        if path not in roots:
            roots.append(path)
    return tuple(roots)


def existing_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    seen: set[Path] = set()
    result: list[Path] = []
    for path in paths:
        try:
            resolved = path.expanduser().resolve()
            exists = resolved.exists()
        except OSError:
            # Protected profile folders are optional discovery evidence.  They
            # must never invalidate an otherwise verified slicer executable.
            continue
        if resolved in seen or not exists:
            continue
        seen.add(resolved)
        result.append(resolved)
    return tuple(result)
