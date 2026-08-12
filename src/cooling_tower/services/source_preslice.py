from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import math
from pathlib import Path
import re
import shutil
from threading import Event
import tempfile
import time

from cooling_tower.calibration.slice_evaluator import build_calibration_profile
from cooling_tower.file_integrity import sha256_file
from cooling_tower.models import (
    GCodeOrigin,
    PreSliceProvenance,
    PreparedAnalysisSource,
    SourceArtifact,
    SourceKind,
)
from cooling_tower.models.analysis import (
    ANALYSIS_PARSER_VERSION,
    GCodeAnalysisSnapshot,
)
from cooling_tower.persistence import PreSliceCache, PreSliceCacheEntry
from cooling_tower.slicers import (
    ProfileConfirmation,
    ProfileMatchResult,
    SliceRequest,
    SliceResult,
    SlicerAdapter,
    SlicerProcessError,
    fingerprint_profile_paths,
    profile_paths_fingerprint,
    protect_profile_paths,
    assert_profile_copies_are_isolated,
)
from cooling_tower.slicers.profile_models import stable_json_fingerprint
from cooling_tower.slicers.profile_matching import metadata_values
from cooling_tower.slicers.orca_profile_compatibility import (
    temporary_orca_machine_identity,
)
from cooling_tower.services.analysis_service import (
    AnalysisCancelled,
    GCodeAnalysisService,
)
from cooling_tower.services.stl_validation import StlValidationResult


PRESLICE_ADAPTER_VERSION = 3
_WORKSPACE_PREFIX = "cooling_tower_source_preslice_"
_WORKSPACE_MARKER = ".cooling_tower_preslice_workspace"

PreSliceProgressCallback = Callable[[int, str, bool], None]


class SourcePreSliceError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        technical_details: str | None = None,
    ) -> None:
        super().__init__(message)
        self.technical_details = technical_details


class SourcePreSliceCancelled(SourcePreSliceError):
    pass


@dataclass(slots=True)
class SourcePreSliceResult:
    prepared_source: PreparedAnalysisSource
    analysis_snapshot: GCodeAnalysisSnapshot
    slice_result: SliceResult
    workspace_root: Path
    metadata_verified: bool
    cache_hit: bool = False

    def cleanup(self) -> None:
        _safe_cleanup_workspace(self.workspace_root)


class SourcePreSliceService:
    """Create and validate one isolated analysis G-code from a confirmed STL."""

    def __init__(
        self,
        *,
        analysis_service: GCodeAnalysisService | None = None,
        workspace_parent: str | Path | None = None,
        diagnostics_root: str | Path | None = None,
        cache: PreSliceCache | None = None,
        timeout_s: float = 300.0,
    ) -> None:
        if timeout_s <= 0 or not math.isfinite(timeout_s):
            raise ValueError("Das Pre-Slice-Zeitlimit muss positiv und endlich sein.")
        self.analysis_service = analysis_service or GCodeAnalysisService()
        self.workspace_parent = (
            Path(workspace_parent).expanduser().resolve()
            if workspace_parent is not None
            else None
        )
        self.diagnostics_root = (
            Path(diagnostics_root).expanduser().resolve()
            if diagnostics_root is not None
            else None
        )
        self.timeout_s = timeout_s
        self.cache = cache

    def run(
        self,
        *,
        stl_validation: StlValidationResult,
        profile_match: ProfileMatchResult,
        confirmation: ProfileConfirmation,
        adapter: SlicerAdapter,
        cancellation_event: Event | None = None,
        progress_callback: PreSliceProgressCallback | None = None,
    ) -> SourcePreSliceResult:
        notify = progress_callback or (lambda _percent, _status, _busy: None)
        cancelled = cancellation_event or Event()
        try:
            self._validate_request(
                stl_validation,
                profile_match,
                confirmation,
                adapter,
            )
        except SlicerProcessError as error:
            raise SourcePreSliceError(str(error)) from error
        source = stl_validation.source_artifact
        selected = profile_match.selected
        assert selected is not None
        if cancelled.is_set():
            raise SourcePreSliceCancelled("Der Pre-Slice wurde abgebrochen.")

        try:
            cache_key = build_preslice_cache_key(
                stl_validation=stl_validation,
                profile_match=profile_match,
                confirmation=confirmation,
                adapter_version=PRESLICE_ADAPTER_VERSION,
            )
            if self.cache is not None:
                self.cache.assert_safe_location(
                    self._slicer_roots(profile_match),
                    source_parent=source.original_path.parent,
                    # Both model types normalize their paths at construction.
                    # Repeating Windows realpath calls here can delay cancel.
                    trusted_resolved_paths=True,
                )
        except (OSError, ValueError, SlicerProcessError) as error:
            raise SourcePreSliceError(str(error)) from error
        if self.cache is not None:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return self._restore_cached(
                    cached,
                    stl_validation=stl_validation,
                    profile_match=profile_match,
                    confirmation=confirmation,
                    cancellation_event=cancelled,
                    notify=notify,
                )

        notify(5, "Slicer wird vorbereitet", False)
        workspace = self._create_workspace(profile_match, source.original_path)
        output_directory = workspace / "output"
        output_directory.mkdir()
        started = time.monotonic()
        try:
            before_source_hash = sha256_file(source.original_path)
            if before_source_hash != source.original_sha256:
                raise SourcePreSliceError(
                    "Die STL wurde nach ihrer Validierung verändert."
                )
            notify(20, "Modell wird geslict", True)
            try:
                with protect_profile_paths(
                    selected.source_paths,
                    expected_initial_fingerprint=(
                        confirmation.profile_sources_fingerprint
                    ),
                ):
                    timing_profile, timing_overrides = build_calibration_profile(
                        selected.effective_profile,
                        workspace / "timing_profile",
                        simulate_full_tower_infill=False,
                        resolved_profiles=selected.resolved_profiles,
                    )
                    if selected.effective_profile.installation.adapter_id in {
                        "anycubic_slicer_next",
                        "orca_slicer",
                        "bambu_studio",
                    }:
                        assert_profile_copies_are_isolated(
                            selected.effective_profile,
                            timing_profile,
                            workspace / "timing_profile",
                        )
                    request = SliceRequest(
                        model_path=source.original_path,
                        profile=timing_profile,
                        output_directory=output_directory,
                        timeout_s=self.timeout_s,
                        diagnostics_root=self.diagnostics_root,
                        retain_failure_diagnostics=True,
                        temporary_overrides=timing_overrides,
                        purpose="source_preslice",
                        cancellation_event=cancelled,
                    )
                    slice_result = adapter.slice_model(request)
            except SlicerProcessError as error:
                if cancelled.is_set():
                    raise SourcePreSliceCancelled(
                        "Der Pre-Slice wurde abgebrochen."
                    ) from error
                raise
            if cancelled.is_set() or slice_result.cancelled:
                raise SourcePreSliceCancelled("Der Pre-Slice wurde abgebrochen.")
            if not slice_result.success:
                raise SourcePreSliceError(
                    slice_result.failure_reason
                    or "Der Slicer konnte keinen G-Code erzeugen.",
                    technical_details=self._slice_failure_details(slice_result),
                )
            notify(55, "Slicer-Ausgabe wird geprüft", False)
            gcode_path = self._validated_output_gcode(
                slice_result,
                output_directory,
            )
            if gcode_path.suffix.casefold() != ".gcode":
                normalized = output_directory / "prepared_analysis.gcode"
                shutil.copy2(gcode_path, normalized)
                gcode_path = normalized.resolve()
            if cancelled.is_set():
                raise SourcePreSliceCancelled("Der Pre-Slice wurde abgebrochen.")
            notify(70, "Layerzeiten werden analysiert", False)
            try:
                snapshot = self.analysis_service.analyze(
                    gcode_path,
                    force=True,
                    progress_callback=lambda percent, status: (
                        self._forward_analysis_progress(
                            notify,
                            percent,
                            status,
                        )
                    ),
                    cancellation_callback=cancelled.is_set,
                )
            except AnalysisCancelled as error:
                raise SourcePreSliceCancelled(
                    "Die Pre-Slice-Analyse wurde abgebrochen."
                ) from error
            if snapshot.layer_count < 1:
                raise SourcePreSliceError(
                    "Der erzeugte G-Code enthält keine druckbaren Layer."
                )
            notify(90, "Slicer- und Profilmetadaten werden abgeglichen", False)
            self._verify_generated_metadata(snapshot, profile_match)
            if sha256_file(source.original_path) != source.original_sha256:
                raise SourcePreSliceError(
                    "Sicherheitsabbruch: Die Original-STL wurde während "
                    "des Pre-Slices verändert."
                )
            duration = max(0.0, time.monotonic() - started)
            provenance = PreSliceProvenance.now(
                duration_s=duration,
                cache_key=cache_key,
                adapter_version=PRESLICE_ADAPTER_VERSION,
            )
            prepared = PreparedAnalysisSource.capture(
                source_artifact=source,
                analysis_gcode_path=gcode_path,
                gcode_origin=GCodeOrigin.GENERATED_PRESLICE,
                slicer_identity=snapshot.metadata.slicer,
                slicer_version=profile_match.execution_slicer.version,
                effective_profile_fingerprint=(
                    confirmation.effective_profile_fingerprint
                ),
                preslice_provenance=provenance,
            )
            if self.cache is not None:
                try:
                    self.cache.put(
                        cache_key=cache_key,
                        gcode_path=gcode_path,
                        created_at_utc=provenance.created_at_utc,
                        preslice_duration_s=duration,
                    )
                except (OSError, ValueError):
                    # Cache availability never turns an otherwise fully
                    # verified Pre-Slice into a failed user operation.
                    pass
            notify(100, "Prognose wird vorbereitet", False)
            return SourcePreSliceResult(
                prepared_source=prepared,
                analysis_snapshot=snapshot,
                slice_result=slice_result,
                workspace_root=workspace,
                metadata_verified=True,
                cache_hit=False,
            )
        except (SourcePreSliceCancelled, SourcePreSliceError) as error:
            _safe_cleanup_workspace(workspace)
            self._raise_if_source_changed(source, cause=error)
            raise
        except (OSError, ValueError, SlicerProcessError) as error:
            _safe_cleanup_workspace(workspace)
            self._raise_if_source_changed(source, cause=error)
            raise SourcePreSliceError(str(error)) from error

    @staticmethod
    def _forward_analysis_progress(
        notify: PreSliceProgressCallback,
        percent: int,
        status: str,
    ) -> None:
        analysis_percent = max(0, min(100, int(percent)))
        overall_percent = 70 + round(analysis_percent * 19 / 100)
        notify(
            overall_percent,
            f"{status} ({analysis_percent} %)",
            False,
        )

    def _validate_request(
        self,
        stl_validation: StlValidationResult,
        profile_match: ProfileMatchResult,
        confirmation: ProfileConfirmation,
        adapter: SlicerAdapter,
    ) -> None:
        source = stl_validation.source_artifact
        selected = profile_match.selected
        if not stl_validation.valid or source.source_kind is not SourceKind.STL:
            raise SourcePreSliceError("Nur eine gültige STL darf geslict werden.")
        if (
            selected is None
            or selected.machine is None
            or selected.process is None
            or not selected.effective_profile.filaments
            or not profile_match.user_confirmed
        ):
            raise SourcePreSliceError(
                "Slicer und Profile müssen vor dem Pre-Slice bestätigt werden."
            )
        if not confirmation.matches_source(source):
            raise SourcePreSliceError(
                "Die Profilbestätigung gehört nicht zu dieser STL."
            )
        installation = profile_match.execution_slicer
        if not installation.can_slice or adapter.adapter_id != installation.adapter_id:
            raise SourcePreSliceError(
                "Der bestätigte Slicer kann nicht automatisiert slicen."
            )
        if confirmation.slicer_identity_key != installation.identity_key:
            raise SourcePreSliceError(
                "Der bestätigte Slicer wurde zwischenzeitlich geändert."
            )
        if confirmation.slicer_path != installation.executable_path:
            raise SourcePreSliceError(
                "Der Pfad des bestätigten Slicers wurde zwischenzeitlich geändert."
            )
        if confirmation.slicer_version != installation.version:
            raise SourcePreSliceError(
                "Die bestätigte Slicerversion wurde zwischenzeitlich geändert."
            )
        if (
            confirmation.machine_profile_id != selected.machine.profile_id
            or confirmation.process_profile_id != selected.process.profile_id
            or confirmation.filament_profile_ids
            != tuple(
                item.profile_id
                for item in selected.effective_profile.filaments
            )
        ):
            raise SourcePreSliceError(
                "Die ausgewählten Profile wurden nach der Bestätigung geändert."
            )
        effective_fingerprint = stable_json_fingerprint(
            selected.effective_profile.effective_values
        )
        if effective_fingerprint != confirmation.effective_profile_fingerprint:
            raise SourcePreSliceError(
                "Die effektiven Profilwerte wurden nach der Bestätigung geändert."
            )
        if (
            profile_paths_fingerprint(selected.source_paths)
            != confirmation.profile_sources_fingerprint
        ):
            raise SourcePreSliceError(
                "Mindestens eine Profildatei wurde nach der Bestätigung geändert. "
                "Bitte die Profile erneut prüfen und bestätigen."
            )

    def _create_workspace(
        self,
        profile_match: ProfileMatchResult,
        source_path: Path,
    ) -> Path:
        parent = (
            self.workspace_parent
            or Path(tempfile.gettempdir()).expanduser().resolve()
        )
        forbidden = self._slicer_roots(profile_match)
        self._assert_app_owned_location(
            parent,
            forbidden,
            source_path.parent,
            "Arbeitsverzeichnis",
        )
        if self.diagnostics_root is not None:
            self._assert_app_owned_location(
                self.diagnostics_root,
                forbidden,
                source_path.parent,
                "Diagnoseverzeichnis",
            )
        parent.mkdir(parents=True, exist_ok=True)
        root = Path(
            tempfile.mkdtemp(
                prefix=_WORKSPACE_PREFIX,
                dir=str(parent),
            )
        ).resolve()
        (root / _WORKSPACE_MARKER).write_text("source_preslice_v1\n", encoding="ascii")
        return root

    @staticmethod
    def _slicer_roots(
        profile_match: ProfileMatchResult,
    ) -> tuple[Path, ...]:
        return (
            profile_match.execution_slicer.executable_path.parent,
            *profile_match.execution_slicer.profile_roots,
        )

    def _restore_cached(
        self,
        entry: PreSliceCacheEntry,
        *,
        stl_validation: StlValidationResult,
        profile_match: ProfileMatchResult,
        confirmation: ProfileConfirmation,
        cancellation_event: Event,
        notify: PreSliceProgressCallback,
    ) -> SourcePreSliceResult:
        source = stl_validation.source_artifact
        workspace = self._create_workspace(profile_match, source.original_path)
        output_directory = workspace / "output"
        output_directory.mkdir()
        try:
            if cancellation_event.is_set():
                raise SourcePreSliceCancelled("Der Pre-Slice wurde abgebrochen.")
            notify(15, "Gespeicherter Pre-Slice wird geprüft", False)
            target = output_directory / "prepared_analysis.gcode"
            shutil.copy2(entry.artifact_path, target)
            if (
                target.stat().st_size != entry.gcode_size_bytes
                or sha256_file(target) != entry.gcode_sha256
            ):
                raise SourcePreSliceError(
                    "Der gespeicherte Pre-Slice ist nicht mehr unverändert."
                )
            notify(70, "Layerzeiten werden analysiert", False)
            try:
                snapshot = self.analysis_service.analyze(
                    target,
                    force=True,
                    progress_callback=lambda percent, status: (
                        self._forward_analysis_progress(
                            notify,
                            percent,
                            status,
                        )
                    ),
                    cancellation_callback=cancellation_event.is_set,
                )
            except AnalysisCancelled as error:
                raise SourcePreSliceCancelled(
                    "Die Pre-Slice-Analyse wurde abgebrochen."
                ) from error
            if snapshot.layer_count < 1:
                raise SourcePreSliceError(
                    "Der gespeicherte Pre-Slice enthält keine druckbaren Layer."
                )
            self._verify_generated_metadata(snapshot, profile_match)
            if not source.matches_current_file(verify_content=True):
                raise SourcePreSliceError(
                    "Die STL wurde nach ihrer Validierung verändert."
                )
            provenance = PreSliceProvenance(
                created_at_utc=entry.created_at_utc,
                duration_s=entry.preslice_duration_s,
                cache_key=entry.cache_key,
                adapter_version=PRESLICE_ADAPTER_VERSION,
                cache_hit=True,
            )
            prepared = PreparedAnalysisSource.capture(
                source_artifact=source,
                analysis_gcode_path=target,
                gcode_origin=GCodeOrigin.GENERATED_PRESLICE,
                slicer_identity=snapshot.metadata.slicer,
                slicer_version=profile_match.execution_slicer.version,
                effective_profile_fingerprint=(
                    confirmation.effective_profile_fingerprint
                ),
                preslice_provenance=provenance,
            )
            notify(100, "Prognose wird vorbereitet", False)
            return SourcePreSliceResult(
                prepared_source=prepared,
                analysis_snapshot=snapshot,
                slice_result=SliceResult(
                    success=True,
                    return_code=0,
                    command=("preslice-cache",),
                    output_files=(target,),
                    gcode_path=target,
                    metadata_paths=(),
                    stdout="",
                    stderr="",
                    duration_s=0.0,
                ),
                workspace_root=workspace,
                metadata_verified=True,
                cache_hit=True,
            )
        except (SourcePreSliceCancelled, SourcePreSliceError):
            _safe_cleanup_workspace(workspace)
            raise
        except (OSError, ValueError) as error:
            _safe_cleanup_workspace(workspace)
            raise SourcePreSliceError(str(error)) from error

    @staticmethod
    def _assert_app_owned_location(
        candidate: Path,
        forbidden: tuple[Path, ...],
        source_parent: Path,
        label: str,
    ) -> None:
        if any(
            candidate == path or candidate.is_relative_to(path)
            for path in forbidden
        ):
            raise SourcePreSliceError(
                f"Das {label} darf weder in einem Slicer-Verzeichnis noch "
                "neben der Benutzer-STL liegen."
            )
        original_parent = source_parent
        if candidate == original_parent or candidate.parent == original_parent:
            raise SourcePreSliceError(
                f"Das {label} darf nicht direkt neben der Benutzer-STL liegen."
            )

    @staticmethod
    def _raise_if_source_changed(
        source: SourceArtifact,
        *,
        cause: BaseException,
    ) -> None:
        try:
            unchanged = (
                source.original_path.is_file()
                and sha256_file(source.original_path) == source.original_sha256
            )
        except OSError:
            unchanged = False
        if not unchanged:
            raise SourcePreSliceError(
                "Sicherheitsabbruch: Die Original-STL wurde während des "
                "Pre-Slices verändert."
            ) from cause

    @staticmethod
    def _validated_output_gcode(
        result: SliceResult,
        output_directory: Path,
    ) -> Path:
        path = result.gcode_path
        if path is None:
            raise SourcePreSliceError(
                "Der Slicer meldete Erfolg, erzeugte aber keinen G-Code."
            )
        resolved = path.resolve(strict=True)
        root = output_directory.resolve()
        if not resolved.is_file() or not resolved.is_relative_to(root):
            raise SourcePreSliceError(
                "Der Slicer lieferte eine Ausgabe außerhalb des isolierten Arbeitsbereichs."
            )
        if resolved.suffix.casefold() not in {".gcode", ".gco"}:
            raise SourcePreSliceError("Die Slicer-Ausgabe ist kein G-Code.")
        if resolved.stat().st_size <= 0:
            raise SourcePreSliceError("Die erzeugte G-Code-Datei ist leer.")
        return resolved

    @staticmethod
    def _slice_failure_details(result: SliceResult) -> str:
        lines = [
            f"Returncode: {result.return_code}",
            f"Zeitüberschreitung: {result.timed_out}",
            f"Abgebrochen: {result.cancelled}",
            f"Abgestürzt: {result.crashed}",
            f"Prozess-Backend: {result.process_backend}",
            "Befehl: " + " ".join(result.command),
        ]
        if result.stdout:
            lines.append("stdout (begrenzt):\n" + result.stdout[-4000:])
        if result.stderr:
            lines.append("stderr (begrenzt):\n" + result.stderr[-4000:])
        if result.diagnostic_path is not None:
            lines.append(f"Diagnose: {result.diagnostic_path}")
        if result.process_output_diagnostic_path is not None:
            lines.append(
                "Prozessausgabe-Diagnose: "
                f"{result.process_output_diagnostic_path}"
            )
        return "\n".join(lines)

    @staticmethod
    def _verify_generated_metadata(
        snapshot: GCodeAnalysisSnapshot,
        profile_match: ProfileMatchResult,
    ) -> None:
        installation = profile_match.execution_slicer
        identity = snapshot.metadata.slicer
        if (
            identity.family.value != "unknown"
            and installation.family.value != "unknown"
            and identity.family is not installation.family
        ):
            raise SourcePreSliceError(
                "Der erzeugte G-Code nennt eine andere Slicerfamilie als bestätigt."
            )
        if (
            identity.adapter_id
            and identity.adapter_id != installation.adapter_id
        ):
            raise SourcePreSliceError(
                "Der erzeugte G-Code nennt einen anderen Sliceradapter als bestätigt."
            )
        if identity.version and installation.version:
            generated_version = _version_tuple(identity.version)
            confirmed_version = _version_tuple(installation.version)
            if (
                generated_version
                and confirmed_version
                and generated_version[:2] != confirmed_version[:2]
            ):
                raise SourcePreSliceError(
                    "Die Slicerversion im G-Code widerspricht der Bestätigung."
                )
        selected = profile_match.selected
        assert selected is not None
        values = metadata_values(snapshot.metadata)
        expected_ids = _expected_generated_profile_ids(profile_match)
        for key, expected in expected_ids.items():
            actual = _text_values(values.get(key))
            actual_normalized = {item.casefold() for item in actual}
            if expected and actual and not any(
                item.casefold() in actual_normalized for item in expected
            ):
                raise SourcePreSliceError(
                    f"Die G-Code-Metadaten für {key} widersprechen der Bestätigung."
                )
        effective = selected.effective_profile.effective_values
        for key in ("nozzle_diameter", "layer_height"):
            actual_numbers = _numbers(values.get(key))
            expected_numbers = _numbers(effective.get(key))
            if actual_numbers and expected_numbers and not any(
                math.isclose(actual, expected, rel_tol=1e-6, abs_tol=1e-6)
                for actual in actual_numbers
                for expected in expected_numbers
            ):
                raise SourcePreSliceError(
                    f"Der erzeugte G-Code widerspricht beim Wert {key} der Bestätigung."
                )


def _expected_generated_profile_ids(
    profile_match: ProfileMatchResult,
) -> dict[str, tuple[str, ...]]:
    selected = profile_match.selected
    assert selected is not None

    def record_ids(record: object | None) -> tuple[str, ...]:
        if record is None:
            return ()
        return tuple(
            dict.fromkeys(
                value.strip()
                for value in (
                    str(getattr(record, "profile_id", "")),
                    str(getattr(record, "name", "")),
                )
                if value.strip()
            )
        )

    machine_ids = record_ids(selected.machine)
    if (
        selected.machine is not None
        and profile_match.execution_slicer.adapter_id
        in {"anycubic_slicer_next", "orca_slicer", "bambu_studio"}
    ):
        resolved_by_path = {
            item.record.path: item
            for item in selected.resolved_profiles
            if item.valid and item.effective_values
        }
        machine_resolved = resolved_by_path.get(selected.machine.path)
        dependent_values = tuple(
            resolved_by_path[record.path].effective_values
            for record in (
                *((selected.process,) if selected.process is not None else ()),
                *selected.effective_profile.filaments,
            )
            if record.path in resolved_by_path
        )
        generated_machine_id = temporary_orca_machine_identity(
            selected.machine,
            machine_resolved.chain if machine_resolved is not None else (),
            dependent_values,
        )
        if generated_machine_id:
            machine_ids = tuple(
                dict.fromkeys((*machine_ids, generated_machine_id))
            )

    return {
        "printer_settings_id": machine_ids,
        "print_settings_id": record_ids(selected.process),
        "filament_settings_id": record_ids(selected.filament),
    }


def build_preslice_cache_key(
    *,
    stl_validation: StlValidationResult,
    profile_match: ProfileMatchResult,
    confirmation: ProfileConfirmation,
    adapter_version: int = PRESLICE_ADAPTER_VERSION,
    gcode_parser_version: int = ANALYSIS_PARSER_VERSION,
) -> str:
    if (
        isinstance(adapter_version, bool)
        or not isinstance(adapter_version, int)
        or adapter_version < 1
        or isinstance(gcode_parser_version, bool)
        or not isinstance(gcode_parser_version, int)
        or gcode_parser_version < 1
    ):
        raise ValueError("Adapter- und Parser-Version müssen positiv sein.")
    installation = profile_match.execution_slicer
    selected = profile_match.selected
    if selected is None:
        raise ValueError("Für den Pre-Slice-Cache fehlt die Profilzuordnung.")
    profile_sources = fingerprint_profile_paths(selected.source_paths)
    return stable_json_fingerprint(
        {
            "source_sha256": stl_validation.source_artifact.original_sha256,
            "slicer_adapter": installation.adapter_id,
            "slicer_path": str(installation.executable_path).casefold(),
            "slicer_version": installation.version,
            "machine_profile": confirmation.machine_profile_id,
            "process_profile": confirmation.process_profile_id,
            "filament_profiles": confirmation.filament_profile_ids,
            "effective_profile_fingerprint": (
                confirmation.effective_profile_fingerprint
            ),
            "inventory_fingerprint": profile_match.inventory_fingerprint,
            "profile_sources": [
                {
                    "path": str(item.path).casefold(),
                    "size": item.size,
                    "modified_ns": item.modified_ns,
                    "sha256": item.sha256,
                }
                for item in profile_sources
            ],
            "adapter_version": adapter_version,
            "gcode_parser_version": gcode_parser_version,
        }
    )


def _safe_cleanup_workspace(
    root: Path,
    *,
    require_marker: bool = True,
) -> None:
    resolved = Path(root).resolve()
    if not resolved.name.startswith(_WORKSPACE_PREFIX):
        return
    if require_marker and not (resolved / _WORKSPACE_MARKER).is_file():
        return
    shutil.rmtree(resolved, ignore_errors=True)


def _text_values(value: object) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        values = value
    else:
        values = (value,)
    return tuple(
        str(item).strip().strip('"')
        for item in values
        if item is not None and str(item).strip().strip('"')
    )


def _numbers(value: object) -> tuple[float, ...]:
    result: list[float] = []
    for item in _text_values(value):
        for token in re.findall(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", item):
            try:
                number = float(token)
            except ValueError:
                continue
            if math.isfinite(number):
                result.append(number)
    return tuple(result)


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(item) for item in re.findall(r"\d+", value))
