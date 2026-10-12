"""Source-independent manual towers: geometry validation and STL-only export."""
from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from cooling_tower.file_integrity import sha256_file
from cooling_tower.manual.geometry import GeometryError, create_mesh, validate
from cooling_tower.models.calibration import BedBounds, OccupiedBounds, TowerPlacement
from cooling_tower.preview.models import OutputMode, PreviewRequest, PreviewScene
from cooling_tower.tower.mesh_generator import write_binary_stl
from cooling_tower.write_policy import ensure_writable_output


@dataclass(frozen=True, slots=True)
class ConstructionLevel:
    """Initial construction coordinates, deliberately not printer layers."""
    z_mm: float


@dataclass(frozen=True, slots=True)
class StandaloneContext:
    key: str
    layers: tuple = (ConstructionLevel(0.0), ConstructionLevel(100.0))
    maximum_height_mm: float = 500.0
    maximum_foot_diameter_mm: float = 250.0
    height_note: str = "Freie Turmerstellung: bis 250 mm Durchmesser und 500 mm Höhe."
    occupied_bounds: OccupiedBounds = OccupiedBounds(0, 0, 0, 0)
    standalone = True

    def validate(self, draft):
        validate(draft)
        if not draft.standalone:
            raise GeometryError("context", "Dieser Entwurf ist kein freier Turm.")
        if draft.context_key != self.key:
            raise GeometryError("context", "Der Entwurf gehört zu einem anderen Turmmodus.")
        if draft.height_mm > self.maximum_height_mm+1e-9:
            raise GeometryError("height_mm", "Die freie Turmhöhe ist auf 500 mm begrenzt.")
        for name in ("minimum_diameter_mm", "maximum_diameter_mm", "maximum_foot_diameter_mm"):
            if getattr(draft.settings, name) > 250+1e-9:
                raise GeometryError(name, "Der freie Turmdurchmesser ist auf 250 mm begrenzt.")
        if draft.maximum_radius_mm > 125+1e-9:
            raise GeometryError("maximum_foot_diameter_mm", "Der freie Turmdurchmesser ist auf 250 mm begrenzt.")
        # The bounds are preview metadata only; no printer is involved.
        return TowerPlacement(0, 0, draft.maximum_radius_mm, BedBounds(-125, 125, -125, 125), 0)


@dataclass(frozen=True, slots=True)
class StandaloneRequest:
    draft: object
    context: StandaloneContext
    generation_method: str = "manual"
    output_mode: OutputMode = OutputMode.STL

    def signature(self):
        return PreviewRequest._signature_for_payload({"standalone_tower_schema_version": 1,
            "geometry": self.draft.artifact_payload(), "context": self.context.key,
            "maximum_diameter_mm": 250, "maximum_height_mm": 500})


def prepare_standalone(request, workspace_parent, cancellation_event=None, progress_callback=None):
    from cooling_tower.manual.service import ManualResult, check_cancel, wireframe
    from cooling_tower.services.stl_validation import StlValidationService
    notify = progress_callback or (lambda *_: None)
    check_cancel(cancellation_event)
    placement = request.context.validate(request.draft)
    if workspace_parent is not None:
        ensure_writable_output(workspace_parent).mkdir(parents=True, exist_ok=True)
    owner = tempfile.TemporaryDirectory(prefix="free_tower_", dir=workspace_parent)
    try:
        path = Path(owner.name) / "tower.stl"
        notify(25, "Freier Turm wird unverändert als STL erzeugt …")
        write_binary_stl(create_mesh(request.draft, cancellation_event), path)
        checked = StlValidationService().validate(path, cancellation_callback=cancellation_event.is_set if cancellation_event is not None else None)
        if not checked.valid:
            raise ValueError("Das Turm-STL besteht die Geometrieprüfung nicht. "+checked.technical_summary)
        check_cancel(cancellation_event)
        scene = PreviewScene((), wireframe(request.draft, placement), placement.bed_bounds, (0, 0), 0, 0,
                             request.draft.height_mm, tower_circle_segments=request.draft.settings.circle_segments)
        result = ManualResult(request_signature=request.signature(), output_mode=OutputMode.STL,
            scene=scene, artifact_path=path, source_sha256="", artifact_sha256=sha256_file(path),
            calibrated=False, generation_kind="Freie Turmerstellung: STL ohne Slice",
            standalone=True, _temporary_owner=owner)
        owner = None
        notify(100, "Freier Turm als STL vorbereitet · kein Slice")
        return result
    finally:
        if owner is not None:
            owner.cleanup()


def export_standalone(preview, request, output_root):
    from cooling_tower.manual.service import ManualExportResult
    request.context.validate(request.draft)
    if (not preview.standalone or preview.request_signature != request.signature() or
            not preview.artifact_path.is_file() or sha256_file(preview.artifact_path) != preview.artifact_sha256):
        raise ValueError("Der vorbereitete Turm ist nicht mehr unverändert verfügbar; bitte erneut generieren.")
    root = ensure_writable_output(output_root)
    root.mkdir(parents=True, exist_ok=True)
    directory = root / (datetime.now().strftime("%Y%m%d_%H%M%S")+"_free_tower_"+uuid4().hex[:8])
    directory.mkdir()
    try:
        path = directory / "tower.stl"
        shutil.copy2(preview.artifact_path, path)
        if sha256_file(path) != preview.artifact_sha256:
            raise ValueError("Das STL wurde während des Exports verändert.")
        report_path = directory / "export_report.json"
        summary_path = directory / "export_summary.txt"
        report = {"schema_version": 1, "generation_method": "manual", "standalone_tower": True,
            "output_mode": "stl", "slicing_performed": False, "slice_count": 0,
            "time_verification": "not_performed", "minimum_layer_time_s": None,
            "original_object_included": False, "printer_constraints_checked": False,
            "project_3mf": None, "maximum_diameter_mm": 250, "maximum_height_mm": 500,
            "geometry": request.draft.artifact_payload(), "request_signature": request.signature(),
            "output_file": str(path), "output_sha256": preview.artifact_sha256}
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        summary_path.write_text("Freie Turmerstellung\n\nNur der gezeichnete Turm wurde als STL exportiert.\n"
            "Originalobjekt, Drucker und Druckbett wurden nicht berücksichtigt.\n"
            "Kein Slice, keine Layerzeitprüfung und keine 3MF-Datei.\n"
            f"Turmhöhe: {request.draft.height_mm:.2f} mm\n"
            f"Größter Außendurchmesser: {request.draft.maximum_radius_mm*2:.2f} mm\n"
            "Konstruktionsgrenzen: 250 mm Durchmesser × 500 mm Höhe.\n", encoding="utf-8")
        return ManualExportResult(output_mode=OutputMode.STL, run_directory=directory, output_path=path,
            report_path=report_path, user_report_path=summary_path, calibrated=False, slicer_optimized=False,
            minimum_verified_layer_time_s=None, source_sha256="", output_sha256=preview.artifact_sha256,
            standalone=True)
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise
