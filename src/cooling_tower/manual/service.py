"""One fixed-form slice, truthful timing evidence and checked export artifacts."""
from __future__ import annotations

import json
import math
import shutil
import tempfile
from bisect import bisect_left
from dataclasses import dataclass, field, fields, replace
from pathlib import Path

from cooling_tower.calibration.slice_evaluator import SliceEvaluator, build_calibration_profile
from cooling_tower.file_integrity import sha256_file
from cooling_tower.manual.context import ManualContext
from cooling_tower.manual.geometry import ManualDraft, create_mesh, tessellate
from cooling_tower.preview import PreviewCancelled, PreviewExportService
from cooling_tower.preview.models import PreviewRequest, PreviewResult, PreviewExportResult, PreviewScene, Point3D, LineSegment3D
from cooling_tower.preview.service import PreviewService
from cooling_tower.preview.layer_silhouette import load_layer_silhouette
from cooling_tower.preview.mesh_silhouette import build_mesh_silhouette
from cooling_tower.slicers import SliceRequest, assert_profile_copies_are_isolated, protect_profile_sources
from cooling_tower.tower.mesh_generator import write_binary_stl
from cooling_tower.write_policy import ensure_writable_output


def check_cancel(event):
    if event is not None and event.is_set():
        raise PreviewCancelled()


def cancelable_layers(layers, event):
    """Add cooperative cancellation without changing the shared STL reader."""
    for layer in layers:
        check_cancel(event)
        yield layer
    check_cancel(event)


def write_slice_diagnostics(result, root):
    """Retain successful timing evidence as well as unsuccessful transports."""
    destination = root / "diagnostics"
    destination.mkdir(parents=True, exist_ok=True)
    record = {
        "command": list(result.command), "success": result.success,
        "return_code": result.return_code, "duration_s": result.duration_s,
        "process_backend": result.process_backend,
        "timed_out": result.timed_out, "cancelled": result.cancelled,
        "crashed": result.crashed, "failure_reason": result.failure_reason,
        "stdout_truncated": result.stdout_truncated,
        "stderr_truncated": result.stderr_truncated,
    }
    (destination / "manual_slice.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (destination / "stdout.log").write_text(result.stdout, encoding="utf-8")
    (destination / "stderr.log").write_text(result.stderr, encoding="utf-8")


def retain_failure_diagnostics(root):
    """Keep only diagnostic files outside the disposable unsuccessful job."""
    try:
        destination = Path(tempfile.mkdtemp(prefix="manual_failed_", dir=root.parent))
        for name in ("diagnostics", "project_diagnostics"):
            source = root / name
            if source.is_dir():
                shutil.copytree(source, destination / name)
        return f" Diagnose: {destination}"
    except OSError:
        return " Die Fehlerdiagnose konnte nicht dauerhaft gespeichert werden."


@dataclass(frozen=True, slots=True)
class ManualRequest(PreviewRequest):
    draft: ManualDraft | None = None
    context: ManualContext | None = field(default=None, compare=False, repr=False)
    profile_source_hashes: tuple[tuple[str, str], ...] = ()
    generation_method: str = "manual"

    def signature_payload(self):
        source = PreviewRequest.signature_payload(self)
        return {key: value for key, value in source.items() if key in
                {"source", "original_source", "gcode_origin", "analysis_gcode_sha256", "analysis_file_size",
                 "analysis_modified_ns", "slicer_identity_key", "profile_fingerprint", "supports_simulated", "draft_shield_simulated"}} | {
                     "manual_request_schema_version": 3,
                     "simulations": {"full_tower_infill": self.settings.simulate_full_tower_infill,
                                     "source_supports": self.settings.simulate_source_supports},
                     "geometry": self.draft.artifact_payload() if self.draft else None,
                     "effective_profile": dict(self.effective_profile.effective_values),
                     "profile_source_hashes": self.profile_source_hashes}

    def profiles_are_current(self):
        return all(Path(path).is_file() and sha256_file(path) == digest for path, digest in self.profile_source_hashes)


@dataclass(frozen=True, slots=True)
class ManualReference:
    context: ManualContext
    source_data: object
    silhouette: object | None
    profile_source_hashes: tuple[tuple[str, str], ...]
    object_triangles: object | None = field(default=None,compare=False,repr=False)
    object_silhouette: object | None = field(default=None,compare=False,repr=False)


@dataclass(frozen=True, slots=True)
class ManualEvaluation:
    joint_sliced: bool
    layer_times: tuple[tuple[int, float, float], ...]  # ID, Z, total
    time_source: str
    diagnostics: tuple[str, ...]
    gcode_path: Path | None
    gcode_sha256: str

    @property
    def minimum_time_s(self):
        return min(row[2] for row in self.layer_times)

    def to_dict(self):
        return {"technically_complete": True, "fixed_geometry": True, "slice_count": 1,
                "time_verification": "joint_slice" if self.joint_sliced else "separate_tower_prognosis",
                "time_source": self.time_source,
                "minimum_layer_time_s": self.minimum_time_s,
                "layers": [{"index": i, "z_mm": z, "total_time_s": t}
                           for i, z, t in self.layer_times],
                "diagnostics": list(self.diagnostics), "evaluated_gcode_sha256": self.gcode_sha256}


@dataclass(slots=True)
class ManualResult(PreviewResult):
    manual_evaluation: ManualEvaluation | None = None
    diagnostics_directory: Path | None = None


@dataclass(frozen=True,slots=True)
class ManualExportResult(PreviewExportResult):
    generation_method: str = "manual"
    joint_sliced: bool = False


class _CancelableAnalysis:
    def __init__(self, service, event):
        self.service, self.event, self.snapshot = service, event, None

    def analyze(self, *args, **kwargs):
        check_cancel(self.event)
        self.snapshot = self.service.analyze(*args, cancellation_callback=self.event.is_set if self.event is not None else None, **kwargs)
        check_cancel(self.event)
        return self.snapshot


def wireframe(draft, placement):
    rings = []
    count = draft.settings.circle_segments
    for p in tessellate(draft).points:
        rings.append(tuple(Point3D(placement.center_x_mm+p.radius_mm*math.cos(math.tau*i/count),
                                   placement.center_y_mm+p.radius_mm*math.sin(math.tau*i/count), p.z_mm)
                           for i in range(count)))
    lines = [LineSegment3D(ring[i], ring[(i+1)%count]) for ring in rings for i in range(count)]
    lines += [LineSegment3D(a[i], b[i]) for a, b in zip(rings, rings[1:]) for i in range(0, count, 4)]
    return tuple(lines)


class ManualGenerationService:
    def __init__(self, preview_service=None, workspace_parent=None, analysis_service=None):
        from cooling_tower.services.analysis_service import GCodeAnalysisService
        self.preview_service = preview_service or PreviewService()
        self.workspace_parent = workspace_parent
        self.analysis_service = analysis_service or GCodeAnalysisService()

    def prepare_reference(self, request, *, cancellation_event=None, progress_callback=None):
        notify = progress_callback or (lambda *_: None)
        if not request.original_source_is_current():
            raise ValueError("Die Originalquelle wurde verändert; bitte erneut vorbereiten.")
        data = self.preview_service._source_data(request, cancellation_event=cancellation_event, notify=notify)
        check_cancel(cancellation_event)
        context = ManualContext.from_request(request, data, request.signature())
        from cooling_tower.manual.placement import largest_tower_envelope
        notify(20, "Maximal verfügbare Fußbreite und Druckbettplatzierung werden berechnet …")
        largest_tower_envelope(context.bed_geometry,context.occupied_bounds,cancellation_event)
        hashes = tuple((str(p), sha256_file(p)) for p in request.effective_profile.source_paths)
        silhouette = None
        mesh_silhouette = None
        triangles = None
        if request.source_artifact is not None and request.source_artifact.source_kind.value == "stl":
            notify(30, "Vollständige STL-Layerquerschnitte werden vorbereitet …")
            silhouette = load_layer_silhouette(request.source_artifact, cancelable_layers(request.snapshot.layers, cancellation_event))
            import numpy as np
            import trimesh
            check_cancel(cancellation_event)
            mesh = trimesh.load(request.source_artifact.original_path,file_type="stl",force="mesh",process=False)
            triangles = np.asarray(mesh.triangles,dtype=float).copy()
            triangles[:,:,2] -= float(mesh.bounds[0,2])
            triangles.setflags(write=False)
            mesh_silhouette = build_mesh_silhouette(triangles,cancellation_event)
            if not request.original_source_is_current():
                raise ValueError("Die Original-STL wurde während der Vorschauaufbereitung verändert.")
        check_cancel(cancellation_event)
        return ManualReference(context, data, silhouette, hashes,triangles,mesh_silhouette)

    def prepare(self, request, *, cancellation_event=None, progress_callback=None):
        notify = progress_callback or (lambda *_: None)
        check_cancel(cancellation_event)
        if request.draft is None or request.context is None:
            raise ValueError("Der manuelle Entwurf ist noch nicht vorbereitet.")
        if not request.original_source_is_current() or not request.profiles_are_current():
            raise ValueError("Quelle oder bestätigte Profile wurden verändert; bitte erneut vorbereiten.")
        signature = request.signature()
        placement = request.context.validate(request.draft)
        data = self.preview_service._source_data(request, cancellation_event=cancellation_event, notify=notify)
        owner = None
        try:
            if self.workspace_parent is not None:
                ensure_writable_output(self.workspace_parent).mkdir(parents=True, exist_ok=True)
            owner = tempfile.TemporaryDirectory(prefix="manual_tower_", dir=self.workspace_parent)
            root = Path(owner.name)
            stl = root / "manual_tower.stl"
            notify(25, "Die gestaltete Form wird unverändert als geschlossenes STL erzeugt …")
            write_binary_stl(create_mesh(request.draft, cancellation_event), stl)
            from cooling_tower.services.stl_validation import StlValidationService
            stored_mesh = StlValidationService().validate(stl,cancellation_callback=cancellation_event.is_set if cancellation_event is not None else None)
            if not stored_mesh.valid:
                raise ValueError("Das geschriebene manuelle STL besteht die strenge Geometrieprüfung nicht. "+stored_mesh.technical_summary)
            artifact_hash = sha256_file(stl)
            check_cancel(cancellation_event)
            adapter = request.adapter
            project_factory = getattr(adapter, "create_joint_project", None)
            lightweight_factory = None if getattr(adapter, "prefer_native_joint_project", False) else getattr(adapter, "prepare_joint_slice_input", None)
            artifact = request.source_artifact
            joint = artifact is not None and artifact.source_kind.value == "stl" and callable(project_factory)
            if request.settings.simulate_source_supports and not joint:
                raise ValueError("Objektspezifische STL-Stützen benötigen einen gemeinsamen Slice mit einem unterstützten Slicer.")
            warnings = []
            if not joint:
                warnings.append("Separater Turm-Slice: Die Zeitbewertung ist eine Prognose zum Original-G-Code, keine gemeinsame Verifikation.")
                if artifact is not None and artifact.source_kind.value == "stl":
                    warnings.append("Dieser Adapter kann kein geprüftes natives gemeinsames Projekt erzeugen.")
            with protect_profile_sources(request.effective_profile):
                copied, overrides = build_calibration_profile(
                    request.effective_profile, root / "profiles",
                    simulate_full_tower_infill=request.settings.simulate_full_tower_infill and not joint)
                if copied.installation.adapter_id in {"orca_slicer", "bambu_studio", "anycubic_slicer_next"}:
                    assert_profile_copies_are_isolated(request.effective_profile, copied, root / "profiles")
                project = None
                use_assemble = False
                slice_model = stl
                project_request = SliceRequest(model_path=artifact.original_path if joint else stl, profile=copied,
                                               output_directory=root / "project_export", diagnostics_root=root / "project_diagnostics",
                                               temporary_overrides=overrides, cancellation_event=cancellation_event,
                                               purpose="calibration")
                if joint:
                    notify(35, "Festes gemeinsames Objekt-/Turm-Projekt wird aufgebaut …")
                    if callable(lightweight_factory):
                        product = lightweight_factory(project_request, artifact.original_path, stl, root / "assemble.json",
                                                       occupied=request.context.occupied_bounds, placement=placement, tower_full_infill=request.settings.simulate_full_tower_infill,
                                                       **({"source_supports_enabled": True} if request.settings.simulate_source_supports else {}))
                        slice_model = Path(product.slice_input_path)
                        use_assemble = True
                    else:
                        project = root / "object_with_manual_tower.3mf"
                        product = project_factory(project_request, artifact.original_path, stl, project,
                                                  occupied=request.context.occupied_bounds, placement=placement, tower_full_infill=request.settings.simulate_full_tower_infill,
                                                       **({"source_supports_enabled": True} if request.settings.simulate_source_supports else {}))
                        native_input = getattr(product, "slice_input_path", None)
                        slice_model = Path(native_input) if native_input is not None and not getattr(adapter, "prefer_native_joint_project", False) else project
                        use_assemble = native_input is not None and slice_model != project
                check_cancel(cancellation_event)
                notify(45, "Gemeinsamer Prüfslice der festen Form …" if joint else "Separater Prüfslice der festen Form …")
                sliced = adapter.slice_model(SliceRequest(model_path=slice_model, profile=copied, output_directory=root / "slice",
                                                         diagnostics_root=root / "diagnostics", temporary_overrides=overrides,
                                                         expected_layer_heights_mm=tuple(float(l.height_mm) for l in request.snapshot.layers),
                                                         placement_xy_mm=None if joint else (placement.center_x_mm, placement.center_y_mm),
                                                         preserve_model_positions=joint, use_cli_assemble_list=use_assemble,
                                                         cancellation_event=cancellation_event, purpose="calibration"))
                check_cancel(cancellation_event)
                write_slice_diagnostics(sliced, root)
                if not sliced.success or sliced.gcode_path is None:
                    diagnostic_note = retain_failure_diagnostics(root)
                    raise ValueError((sliced.failure_reason or "Der manuelle Prüfslice ist fehlgeschlagen.") + " " + (sliced.stderr or sliced.stdout)[-1500:] + diagnostic_note)
                notify(75, "G-Code und tatsächliche Layerzeiten werden ausgewertet …")
                analysis = _CancelableAnalysis(self.analysis_service, cancellation_event)
                evaluator = SliceEvaluator(analysis)
                layers = tuple(request.snapshot.layers) if joint else tuple(l for l in request.snapshot.layers if l.z_mm <= request.draft.height_mm+1e-6)
                evaluation = evaluator.evaluate(
                    sliced, layers,
                    validate_tower_full_infill=joint and request.settings.simulate_full_tower_infill,
                    tower_center_xy_mm=(placement.center_x_mm, placement.center_y_mm))
                actual_layers = analysis.snapshot.layers
                tops = tuple(l.z_mm for l in actual_layers)
                # Reject unsafe nearest-neighbour guesses, especially variable layers.
                for layer in layers:
                    pos = bisect_left(tops, layer.z_mm)
                    distance = min(abs(tops[i]-layer.z_mm) for i in {min(pos,len(tops)-1), max(0,pos-1)})
                    if distance > max(0.005, min(.03, float(layer.height_mm)*.15)):
                        raise ValueError(f"Layer {layer.index} bei {layer.z_mm:.3f} mm kann dem Prüfslice nicht sicher zugeordnet werden.")
                measured = evaluation.added_time_by_layer
                rows = []
                for layer in request.snapshot.layers:
                    t = measured[layer.index] if joint else layer.total_time_s+measured.get(layer.index, 0)
                    rows.append((layer.index, layer.z_mm, t))
                if joint:
                    # Include layers newly introduced by supports or slicing.
                    known = {round(row[1], 6) for row in rows}
                    rows.extend((l.index, l.z_mm, l.total_time_s)
                                for l in actual_layers if round(l.z_mm,6) not in known)
                warnings.extend(evaluation.diagnostics)
                if joint and project is None:
                    check_cancel(cancellation_event)
                    notify(90, "Geprüftes natives 3MF der identischen Anordnung wird erhalten …")
                    project = root / "object_with_manual_tower.3mf"
                    project_factory(project_request, artifact.original_path, stl, project,
                                    occupied=request.context.occupied_bounds, placement=placement, tower_full_infill=request.settings.simulate_full_tower_infill,
                                                       **({"source_supports_enabled": True} if request.settings.simulate_source_supports else {}))
            check_cancel(cancellation_event)
            if artifact_hash != sha256_file(stl):
                raise ValueError("Die manuelle Geometrie wurde während der Prüfung verändert.")
            if signature != request.signature() or not request.original_source_is_current() or not request.profiles_are_current():
                raise ValueError("Quelle oder Profile wurden während der Prüfung verändert.")
            if sha256_file(request.source_path) != data.key.content_sha256 or not request.snapshot.matches_file(request.source_path):
                raise ValueError("Der Analyse-G-Code wurde während der manuellen Prüfung verändert.")
            result_evaluation = ManualEvaluation(joint, tuple(rows), evaluation.metadata_source,
                                                 tuple(warnings), Path(sliced.gcode_path), sha256_file(sliced.gcode_path))
            scene = PreviewScene(data.object_segments, wireframe(request.draft, placement), placement.bed_bounds,
                                 (placement.center_x_mm, placement.center_y_mm), data.source_segment_count, len(data.object_segments),
                                 request.draft.height_mm, object_height_mm=request.snapshot.maximum_print_z_mm,
                                 object_layer_count=request.snapshot.layer_count, tower_layer_count=len(layers),
                                 tower_circle_segments=request.draft.settings.circle_segments)
            result = ManualResult(request_signature=signature, output_mode=request.output_mode, scene=scene, artifact_path=stl,
                                  source_sha256=data.key.content_sha256, artifact_sha256=artifact_hash,
                                  calibrated=False, slicer_optimized=False,
                                  generation_kind="Manuell: gemeinsamer Prüfslice" if joint else "Manuell: separate Zeitprognose",
                                  project_path=project, project_sha256=sha256_file(project) if project is not None else None,
                                  joint_sliced=joint, completed_joint_slice_count=int(joint), configured_joint_slice_count=int(joint),
                                  minimum_verified_layer_time_s=result_evaluation.minimum_time_s,
                                  warnings=tuple(warnings), _temporary_owner=owner,
                                  manual_evaluation=result_evaluation, diagnostics_directory=root)
            owner = None
            notify(100, "Manueller Turm vollständig geprüft")
            return result
        finally:
            if owner is not None:
                owner.cleanup()


class ManualExportService(PreviewExportService):
    def export(self, preview, request, output_root):
        if not request.profiles_are_current():
            raise ValueError("Die bestätigten Slicerprofile wurden nach der Prüfung verändert.")
        e = preview.manual_evaluation
        if e is None or (e.gcode_path is not None and (
                not e.gcode_path.is_file() or sha256_file(e.gcode_path) != e.gcode_sha256)):
            raise ValueError("Der vollständig geprüfte G-Code ist nicht mehr unverändert verfügbar.")
        result = super().export(preview, request, output_root)
        try:
            # Timing values and the evaluated hash are already in the report.
            # Printer instructions belong only to this disposable verification job.
            root = preview.diagnostics_directory
            for name in ("diagnostics", "project_diagnostics"):
                source = root / name
                if source.is_dir():
                    shutil.copytree(source, result.run_directory / name)
            if not request.profiles_are_current() or not request.original_source_is_current() or sha256_file(request.source_path) != preview.source_sha256:
                raise ValueError("Quelle oder Profile wurden während des Exports verändert.")
            if e.gcode_path is not None:
                owner = preview._temporary_owner
                if owner is None or not e.gcode_path.resolve().is_relative_to(Path(owner.name).resolve()):
                    raise ValueError("Der Prüfslice liegt außerhalb des temporären Arbeitsbereichs.")
                if sha256_file(e.gcode_path) != e.gcode_sha256:
                    raise ValueError("Die Prüfdaten wurden während des Exports verändert.")
                e.gcode_path.unlink()
                # Re-exports use the retained measurements and still verify the
                # source, profiles, geometry and project through the base service.
                preview.manual_evaluation = replace(e, gcode_path=None)
        except Exception:
            shutil.rmtree(result.run_directory, ignore_errors=True)
            raise
        return ManualExportResult(**{f.name:getattr(result,f.name) for f in fields(result)},
                                  joint_sliced=e.joint_sliced)
