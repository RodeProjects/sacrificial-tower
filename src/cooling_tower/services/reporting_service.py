from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cooling_tower.models import (
    AnalysisDiagnosticReport,
    GenerationResult,
    NoTowerRequiredResult,
)


@dataclass(frozen=True, slots=True)
class GenerationReport:
    tower_required: bool
    gcode_path: Path | None
    layer_count: int
    layers_below_target: int
    maximum_time_deficit_s: float
    minimum_outer_diameter_mm: float
    maximum_outer_diameter_mm: float
    unresolved_layer_count: int
    first_deficit_layer_index: int | None
    last_deficit_layer_index: int | None
    tower_end_layer_index: int | None
    tower_end_z_mm: float | None
    original_model_height_mm: float | None
    saved_tower_height_mm: float
    synthetic_final_layer_used: bool
    stl_path: Path
    run_directory: Path


def build_generation_report(result: GenerationResult) -> GenerationReport:
    profile = tuple(result.profile or ())
    outer = [layer.outer_diameter_mm for layer in profile]
    maximum_deficit = 0.0
    if result.analysis is not None and result.settings is not None:
        maximum_deficit = max(
            (
                max(
                    0.0,
                    result.settings.target_layer_time_s
                    - layer.total_time_s,
                )
                for layer in result.analysis.layers
            ),
            default=0.0,
        )
    assessment = result.assessment
    return GenerationReport(
        tower_required=True,
        gcode_path=result.source_gcode_path,
        layer_count=result.layer_count,
        layers_below_target=result.layers_below_target,
        maximum_time_deficit_s=maximum_deficit,
        minimum_outer_diameter_mm=min(outer, default=0.0),
        maximum_outer_diameter_mm=max(
            max(outer, default=0.0), result.maximum_outer_diameter_mm
        ),
        unresolved_layer_count=sum(
            not layer.target_reached for layer in profile
        ),
        first_deficit_layer_index=(
            assessment.first_deficit_layer_index
            if assessment is not None
            else None
        ),
        last_deficit_layer_index=(
            assessment.last_deficit_layer_index
            if assessment is not None
            else None
        ),
        tower_end_layer_index=(
            assessment.tower_end_layer_index
            if assessment is not None
            else None
        ),
        tower_end_z_mm=(
            assessment.tower_end_z_mm
            if assessment is not None
            else None
        ),
        original_model_height_mm=(
            assessment.original_model_height_mm
            if assessment is not None
            else None
        ),
        saved_tower_height_mm=(
            assessment.saved_tower_height_mm
            if assessment is not None
            else 0.0
        ),
        synthetic_final_layer_used=(
            assessment.synthetic_final_layer_used
            if assessment is not None
            else False
        ),
        stl_path=result.stl_path,
        run_directory=result.run_directory,
    )


def format_generation_report(result: GenerationResult) -> str:
    report = build_generation_report(result)
    gcode = str(report.gcode_path) if report.gcode_path else "-"
    return "\n".join(
        (
            f"G-Code-Datei: {gcode}",
            "Kühlturm erforderlich: Ja",
            f"Erkannte Layer: {report.layer_count}",
            f"Layer unter Zielzeit: {report.layers_below_target}",
            f"Maximales Zeitdefizit: {report.maximum_time_deficit_s:.3f} s",
            "Außendurchmesser min/max: "
            f"{report.minimum_outer_diameter_mm:.3f} / "
            f"{report.maximum_outer_diameter_mm:.3f} mm",
            f"Nicht vollständig lösbare Layer: {report.unresolved_layer_count}",
            "Erster/letzter kritischer Layer: "
            f"{report.first_deficit_layer_index or '-'} / "
            f"{report.last_deficit_layer_index or '-'}",
            f"Letzter Turmlayer: {report.tower_end_layer_index or '-'}",
            "Erzeugte Kühlturmhöhe: "
            f"{report.tower_end_z_mm:.3f} mm"
            if report.tower_end_z_mm is not None
            else "Erzeugte Kühlturmhöhe: -",
            "Ursprüngliche Modellhöhe: "
            f"{report.original_model_height_mm:.3f} mm"
            if report.original_model_height_mm is not None
            else "Ursprüngliche Modellhöhe: -",
            f"Eingesparte Turmhöhe: {report.saved_tower_height_mm:.3f} mm",
            "Synthetischer Abschlusslayer: "
            f"{'Ja' if report.synthetic_final_layer_used else 'Nein'}",
            f"STL: {report.stl_path}",
            f"Laufordner: {report.run_directory}",
        )
    )


def format_no_tower_report(result: NoTowerRequiredResult) -> str:
    assessment = result.assessment
    snapshot = result.analysis_snapshot
    minimum_time = getattr(snapshot, "minimum_layer_time_s", None)
    lines = [
        f"G-Code-Datei: {result.source_gcode_path}",
        "Kühlturm erforderlich: Nein",
        f"Erkannte Layer: {result.layer_count}",
        f"Eingestellte Ziel-Layerzeit: {assessment.target_layer_time_s:.3f} s",
    ]
    if minimum_time is not None:
        lines.append(f"Kleinste erkannte Layerzeit: {minimum_time:.3f} s")
    lines.extend(
        (
            "STL: nicht erzeugt",
            f"Begründung: {result.reason}",
        )
    )
    return "\n".join(lines)


def build_analysis_diagnostic_report(
    snapshot: object,
    *,
    local_installation_verified: bool = False,
    exact_profile_verified: bool = False,
) -> AnalysisDiagnosticReport:
    return AnalysisDiagnosticReport.from_snapshot(
        snapshot,
        local_installation_verified=local_installation_verified,
        exact_profile_verified=exact_profile_verified,
    )


def format_analysis_diagnostic_report(
    report_or_snapshot: AnalysisDiagnosticReport | object,
) -> str:
    report = (
        report_or_snapshot
        if isinstance(report_or_snapshot, AnalysisDiagnosticReport)
        else build_analysis_diagnostic_report(report_or_snapshot)
    )
    slicer = report.metadata.slicer
    if slicer.product_name is None:
        generator = "nicht ausdrücklich angegeben"
    else:
        generator = slicer.product_name
        if slicer.version:
            generator += f" {slicer.version}"
        generator += f" ({slicer.confidence.value})"
    printer_model_present = bool(
        report.metadata.values_for("printer_model")
    )
    fingerprint = report.metadata.profile_fingerprint.digest_sha256
    return "\n".join(
        (
            f"G-Code-Datei: {report.source_gcode}",
            f"Generatorangabe im G-Code: {generator}",
            "Lokale Installation verifiziert: "
            f"{'ja' if report.local_installation_verified else 'nein'}",
            "Druckermodellangabe im G-Code vorhanden: "
            f"{'ja' if printer_model_present else 'nein'}",
            "Exakte Profilzuordnung verifiziert: "
            f"{'ja' if report.exact_profile_verified else 'nein'}",
            "Profilfingerabdruck: "
            f"{fingerprint or 'nicht verfügbar'}",
            "Timing-Evidenz: "
            f"{report.timing_evidence.confidence_state.value}",
        )
    )
