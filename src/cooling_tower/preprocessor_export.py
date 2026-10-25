"""Complete preprocessor exports with the same folder/report contract as other methods."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path
import shutil

from cooling_tower.preview.models import OutputMode, PreviewExportResult
from cooling_tower.preprocessor import PreprocessorResult, PreprocessorService
from cooling_tower.services.output_service import sanitize_filename_component
from cooling_tower.write_policy import ensure_writable_output


@dataclass(frozen=True, slots=True)
class PreprocessorExportResult(PreviewExportResult):
    generation_method: str = "preprocessor"


def export_preprocessor_run(service: PreprocessorService, result: PreprocessorResult,
        output_root: str | Path) -> PreprocessorExportResult:
    request = result.request
    request.validate_source()
    profile = request.profile
    root = ensure_writable_output(output_root,
        protected_roots=(profile.installation.executable_path.parent, *profile.installation.profile_roots),
        protected_files=(*profile.source_paths, request.prepared_source.analysis_gcode_path,
            request.prepared_source.source_artifact.original_path))
    root.mkdir(parents=True, exist_ok=True)
    created = datetime.now().astimezone()
    source_name = sanitize_filename_component(request.prepared_source.source_artifact.original_path.stem)
    base = f"{created:%Y%m%d_%H%M%S}_{source_name}"
    directory = root / base
    suffix = 2
    while True:
        try:
            directory.mkdir()
            break
        except FileExistsError:
            directory = root / f"{base}_{suffix}"
            suffix += 1
    try:
        path = service.export(result, directory / f"{source_name}_preprocessor.gcode").resolve()
        minimum = min(result.layer_times_s)
        target = (result.effective_settings or request.settings).target_layer_time_s
        report_path = directory / "export_report.json"
        summary_path = directory / "export_summary.txt"
        report = {
            "report_type": "cooling_tower_export_diagnostics",
            "generation_method": "preprocessor",
            "created_at": created.isoformat(),
            "summary": {"export_succeeded": True},
            "source": {"sha256": request.prepared_source.source_artifact.original_sha256},
            "output": {"path": str(path), "sha256": result.sha256},
            "settings": asdict(request.settings),
            "effective_settings": asdict(result.effective_settings or request.settings),
            "printhead": asdict(result.printhead) if result.printhead is not None else None,
            "profile_notes": result.profile_notes,
            "first_layer": asdict(result.first_layer) if result.first_layer is not None else None,
            "collision_notes": result.collision_notes,
            "placement_statistics": result.placement_statistics,
            "wipe_angles_rad": result.wipe_angles_rad,
            "tower": {"height_mm": result.height_mm, "diameter_mm": result.diameter_mm,
                "base_width_mm": result.base_width_mm, "center_xy_mm": result.scene.tower_center_xy_mm},
            "wait_position_xy_mm": result.scene.wait_position_xy_mm,
            "effective_z_hop_mm": result.effective_z_hop_mm,
            "wait_count": result.wait_count, "total_wait_s": result.total_wait_s,
            "original_layer_times_s": result.original_layer_times_s,
            "added_motion_times_s": result.added_motion_times_s,
            "layer_waits_s": result.layer_waits_s,
            "calculated_layer_times_s": result.layer_times_s,
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        summary_path.write_text(
            f"G-Code-Präprozessor\n\nDatei: {path.name}\n"
            f"Mindest-Schichtzeit: {target:.3f} s\nKürzeste berechnete Schichtzeit: {minimum:.3f} s\n"
            f"Wartephasen: {result.wait_count}\nRestwartezeit gesamt: {result.total_wait_s:.3f} s\n"
            f"Turmhöhe: {result.height_mm:.2f} mm\nTurmdurchmesser: {result.diameter_mm:.2f} mm\n"
            f"Standfußbreite: {result.base_width_mm:.2f} mm\nSicherheitshub: {result.effective_z_hop_mm:.2f} mm\n\n"
            + (("Erstschicht: " + f"Wand {result.first_layer.wall_speed_mm_s:g} mm/s, Füllung {result.first_layer.infill_speed_mm_s:g} mm/s, "
                f"Linienbreite {result.first_layer.line_width_mm:g} mm.\n") if result.first_layer is not None else "")
            + "\n".join(((result.printhead.note,) if result.printhead is not None else ()) + result.collision_notes) + "\n\n"
            +
            "Fahrten, Sicherheitshübe, Turmdruck und Primen sind eingerechnet.\n"
            "Die Zeiten sind rechnerische Prognosen. Der G-Code ist für den vorbereiteten Drucker bestimmt; "
            "erneutes Slicen ersetzt die eingefügten Warte- und Fahrbefehle.\n", encoding="utf-8")
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    return PreprocessorExportResult(output_mode=OutputMode.GCODE,
        run_directory=directory.resolve(), output_path=path, report_path=report_path.resolve(),
        user_report_path=summary_path.resolve(), calibrated=False, slicer_optimized=False,
        minimum_verified_layer_time_s=minimum,
        source_sha256=request.prepared_source.source_artifact.original_sha256, output_sha256=result.sha256,
        target_layer_time_s=target)
