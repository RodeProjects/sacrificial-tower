"""Reports for fixed geometry, without claiming calibration or convergence."""
from cooling_tower.manual.geometry import CURVE_RADIAL_ERROR_MM


def technical_report(preview, request, *, output_path, output_sha256, created_at, project_path=None):
    from cooling_tower.preview.reporting import _source_provenance
    evaluation = preview.manual_evaluation
    return {"technical_report_schema_version": 3, "report_type": "manual_cooling_tower_export_diagnostics",
            "generation_method": "manual", "generation_kind": preview.generation_kind,
            "created_at": created_at.astimezone().isoformat(timespec="seconds"),
            "preview_signature": preview.request_signature, "output_mode": "stl",
            "source_provenance": _source_provenance(request), "source_sha256": preview.source_sha256,
            "output_path": str(output_path), "output_sha256": output_sha256,
            "joint_project_path": str(project_path) if project_path else None,
            "joint_project_sha256": preview.project_sha256, "joint_sliced": preview.joint_sliced,
            "calibrated": False, "slicer_optimized": False,
            "manual_geometry": request.draft.artifact_payload(),
            "manual_settings": request.draft.settings.to_dict(),
            "maximum_vertical_curve_radial_error_mm": CURVE_RADIAL_ERROR_MM,
            "summary": {"export_succeeded": True, "technically_complete": True,
                        "calibration_attempted": False,
                        "user_attention_required": not evaluation.joint_sliced},
            "manual_evaluation": evaluation.to_dict(), "warnings": list(preview.warnings)}


def user_report(preview, request, *, output_path, technical_report_path, created_at, project_path=None):
    e = preview.manual_evaluation
    lines = ["Sacrificial Tower – manuelle Turmerstellung", "",
             "Ergebnis: Technisch erfolgreich erzeugt und vollständig bewertet.",
             "Die ausdrücklich gestaltete Form wurde unverändert geprüft und exportiert.",
             "Zeitprüfung: Ein gemeinsamer Slice von Originalobjekt und Kühlturm." if e.joint_sliced else
             "Zeitprüfung: Separater Turm-Slice; Prognose zum Original-G-Code. Keine gemeinsame Verifikation.",
             f"Kleinste {'geprüfte' if e.joint_sliced else 'prognostizierte'} Layerzeit: {e.minimum_time_s:.3f} s",
             "Ein Prüfslice, keine automatische Formanpassung oder Kalibrierung.", "", f"Turm-STL: {output_path}"]
    if project_path:
        lines.append(f"Geprüftes gemeinsames 3MF: {project_path}")
    lines += ["", "Hinweise:", *[f"- {w}" for w in preview.warnings], "", f"Technischer Bericht: {technical_report_path}", ""]
    return "\n".join(lines)
