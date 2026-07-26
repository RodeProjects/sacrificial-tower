from __future__ import annotations

import platform
import re
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from cooling_tower.preview.models import OutputMode, PreviewRequest, PreviewResult


TECHNICAL_REPORT_SCHEMA_VERSION = 1

_STATE_LABELS = {
    "disabled": "Slicer-Durchläufe wurden vom Benutzer deaktiviert",
    "not_started": "Kalibrierung wurde nicht gestartet",
    "converged": "Slicerbasierte Kalibrierung erfolgreich abgeschlossen",
    "limit_reached": "Kalibrierung konnte die Zielzeit nicht vollständig erreichen",
    "slicer_failed": "Slicer konnte den Kalibrierungslauf nicht abschließen",
    "unsupported": "G-Code oder Slicer wird für diese Kalibrierung nicht unterstützt",
    "invalid_geometry": "Keine gültige Turmgeometrie erzeugbar",
    "cancelled": "Kalibrierung wurde abgebrochen",
}

_FAILURE_LABELS = {
    "maximum_radius": "Der eingestellte maximale Turmradius wurde erreicht.",
    "maximum_wall_thickness": "Die eingestellte maximale Wandstärke wurde erreicht.",
    "transition_angle": "Die eingestellten Übergangswinkel lassen die benötigte Form nicht zu.",
    "no_bed_space": "Auf dem Druckbett wurde kein sicherer Platz für den Turm gefunden.",
    "slicer_failure": "Der Slicer konnte einen Kalibrierungslauf nicht erfolgreich abschließen.",
    "profile_incomplete": "Das ausgewählte Druckprofil enthält nicht alle benötigten Angaben.",
    "layer_mismatch": "Die Layer des geslicten Turms konnten nicht eindeutig dem Objekt zugeordnet werden.",
    "unsupported_gcode": "Der Quell-G-Code verwendet eine nicht sicher unterstützte Funktion.",
    "slicer_timing_mismatch": "Slicerangabe und aus dem G-Code berechnete Zeit widersprechen sich zu stark.",
    "iteration_limit": "Die maximale Anzahl der Kalibrierungsdurchläufe wurde erreicht.",
    "runtime_limit": "Die maximale Kalibrierungsdauer wurde erreicht.",
    "stalled": "Weitere Kalibrierungsdurchläufe brachten keine ausreichende Verbesserung.",
    "geometry_invalid": "Die erzeugte Turmgeometrie war ungültig.",
    "final_timing_deficit": "Mindestens ein Layer unterschreitet weiterhin die Zielzeit.",
}


def _value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return _value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _enum_value(value: Any) -> str | None:
    if isinstance(value, Enum):
        return str(value.value)
    if value is None:
        return None
    return str(value)


def _failure_dict(failure: Any) -> dict[str, Any]:
    code = _enum_value(getattr(failure, "code", None)) or "unknown"
    return {
        "code": code,
        "user_explanation": _FAILURE_LABELS.get(
            code, "Die Kalibrierung konnte diesen Schritt nicht abschließen."
        ),
        "technical_message": str(getattr(failure, "message", "")),
        "layer_index": getattr(failure, "layer_index", None),
        "related_setting_names": list(
            getattr(failure, "related_setting_names", ())
        ),
        "required_value": getattr(failure, "required_value", None),
        "achievable_value": getattr(failure, "achievable_value", None),
    }


def _concise_failure_cause(technical_message: str) -> str | None:
    """Translate common slicer diagnostics into one useful user-facing cause."""

    folded = technical_message.casefold()
    if "unknown config type" in folded:
        match = re.search(
            r"unknown config type of file\s+(.+?)\s+in load-settings",
            technical_message,
            flags=re.IGNORECASE,
        )
        name = Path(match.group(1).strip()).name if match else "ein Profil"
        return (
            f"Das Profil „{name}“ enthielt für den Slicer-CLI-Aufruf keinen "
            "erkennbaren Profiltyp."
        )
    if "nothing to be sliced" in folded or "no object is fully inside" in folded:
        return "Der Slicer konnte das Modell nicht vollständig auf dem Druckbett platzieren."
    if "source" in folded and "profile" in folded and "changed" in folded:
        return "Ein originales Slicer-Profil änderte sich unerwartet; der Vorgang wurde sicher abgebrochen."
    if "slicer-quelldatei" in folded or "slicer-quellprofil" in folded:
        return "Ein originales Slicer-Profil konnte nicht unverändert geschützt werden."
    return None


def _user_visible_warning(warning: str) -> str:
    """Keep the short report German and move raw setting details to JSON."""

    if warning.startswith((
        "Für die Kalibrierung temporär angepasste Kühlwerte:",
        "Temporary cooling overrides:",
    )):
        return "Für die Kalibrierung wurden temporäre Kühlwerte verwendet."
    if warning.startswith("The calibrated STL is a timing prognosis"):
        return (
            "Die kalibrierte STL-Datei ist eine Zeitprognose. Spätere "
            "Sliceränderungen können die endgültige Layerzeit verändern."
        )
    if warning.startswith("Calibration did not fully converge"):
        match = re.search(r"iteration\s+(\d+)", warning, re.IGNORECASE)
        suffix = f" aus Durchlauf {match.group(1)}" if match else ""
        return (
            "Die Zielzeit wurde nicht vollständig erreicht; verwendet wird "
            f"der beste vom Slicer gemessene Zwischenstand{suffix}."
        )
    return warning


def calibration_diagnostics(
    preview: PreviewResult,
    request: PreviewRequest | None = None,
) -> dict[str, Any]:
    calibration = preview.calibration
    requested_iterations = (
        request.calibration_config.maximum_iterations
        if request is not None
        else int(getattr(calibration, "configured_iteration_count", 0))
    )
    intentionally_disabled = requested_iterations == 0
    attempted = calibration is not None and not intentionally_disabled
    state = _enum_value(getattr(calibration, "state", None))
    failures = tuple(getattr(calibration, "failures", ())) if attempted else ()
    iterations = tuple(getattr(calibration, "iterations", ())) if attempted else ()
    raw_details: Any = None
    converter = getattr(calibration, "to_dict", None)
    if callable(converter):
        try:
            raw_details = _value(converter())
        except (AttributeError, TypeError, ValueError):
            raw_details = None
    best_iteration_number = getattr(
        calibration,
        "best_iteration_number",
        None,
    )
    best_iteration = getattr(calibration, "best_iteration", None)
    if best_iteration is None and iterations:
        if best_iteration_number is not None:
            best_iteration = next(
                (
                    item
                    for item in iterations
                    if getattr(item, "number", None) == best_iteration_number
                ),
                None,
            )
        best_iteration = best_iteration or iterations[-1]
    failure_dicts = [_failure_dict(item) for item in failures]
    if intentionally_disabled:
        state_value = "disabled"
        state_explanation = _STATE_LABELS[state_value]
    else:
        state_value = state or "not_attempted"
        if failure_dicts and state_value == "limit_reached":
            state_explanation = failure_dicts[-1]["user_explanation"]
        else:
            state_explanation = (
                _STATE_LABELS.get(state, "Kalibrierung wurde nicht durchgeführt")
                if attempted
                else "Keine verwendbare Slicer-/Profilkombination stand für die Kalibrierung bereit."
            )
    return {
        "attempted": attempted,
        "succeeded": bool(preview.calibrated),
        "slicer_optimized": bool(preview.slicer_optimized),
        "improved_over_analytical": bool(
            getattr(calibration, "improved_over_analytical", False)
        ),
        "state": state_value,
        "state_explanation": state_explanation,
        "mode": _enum_value(getattr(calibration, "mode", None)),
        "configured_iteration_count": requested_iterations,
        "iteration_count": len(iterations),
        "best_iteration_number": best_iteration_number,
        "best_maximum_remaining_deficit_s": getattr(
            best_iteration,
            "maximum_remaining_deficit_s",
            None,
        ),
        "best_deficient_layer_count": getattr(
            best_iteration,
            "deficient_layer_count",
            None,
        ),
        "best_total_remaining_deficit_s": getattr(
            best_iteration,
            "total_remaining_deficit_s",
            None,
        ),
        "failures": failure_dicts,
        "warnings": list(getattr(calibration, "warnings", ())) if attempted else [],
        "minimum_verified_layer_time_s": preview.minimum_verified_layer_time_s,
        "raw_calibration_result": raw_details,
    }


def _profile_details(request: PreviewRequest) -> dict[str, Any]:
    profile = request.effective_profile
    if profile is None:
        return {
            "available": False,
            "profile_fingerprint": request.profile_fingerprint,
        }

    def record(item: Any) -> dict[str, Any] | None:
        if item is None:
            return None
        return {
            "profile_id": getattr(item, "profile_id", None),
            "name": getattr(item, "name", None),
            "source": getattr(item, "source", None),
            "path": str(getattr(item, "path", "")) or None,
        }

    return {
        "available": True,
        "profile_fingerprint": request.profile_fingerprint,
        "machine": record(getattr(profile, "machine", None)),
        "process": record(getattr(profile, "process", None)),
        "filaments": [
            record(item) for item in getattr(profile, "filaments", ())
        ],
        "effective_values": _value(
            dict(getattr(profile, "effective_values", {}))
        ),
        "resolution_notes": list(getattr(profile, "resolution_notes", ())),
    }


def build_technical_report(
    preview: PreviewResult,
    request: PreviewRequest,
    *,
    output_path: Path,
    output_sha256: str,
    created_at: datetime,
) -> dict[str, Any]:
    snapshot = request.snapshot
    calibration = calibration_diagnostics(preview, request)
    status = (
        "success_calibrated"
        if preview.calibrated
        else "success_slicer_optimized_partial"
        if preview.slicer_optimized
        else "success_analytical_requested"
        if request.calibration_config.maximum_iterations == 0
        else "success_with_analytical_fallback"
    )
    target_difference = (
        preview.minimum_verified_layer_time_s
        - request.settings.target_layer_time_s
        if preview.minimum_verified_layer_time_s is not None
        else None
    )
    metadata = getattr(snapshot, "metadata", None)
    timing_evidence = getattr(snapshot, "timing_evidence", None)
    return {
        "technical_report_schema_version": TECHNICAL_REPORT_SCHEMA_VERSION,
        "report_type": "cooling_tower_export_diagnostics",
        "created_at": created_at.astimezone().isoformat(timespec="seconds"),
        # Stable compatibility fields retained for existing report readers.
        "preview_signature": preview.request_signature,
        "output_mode": preview.output_mode.value,
        "source_gcode": str(request.source_path),
        "source_sha256": preview.source_sha256,
        "output_path": str(output_path.resolve()),
        "output_sha256": output_sha256,
        "calibrated": preview.calibrated,
        "slicer_optimized": preview.slicer_optimized,
        "generation_kind": preview.generation_kind,
        "minimum_verified_layer_time_s": preview.minimum_verified_layer_time_s,
        "warnings": list(preview.warnings),
        "software_environment": {
            "python_version": sys.version,
            "platform": platform.platform(),
            "analysis_schema_version": getattr(
                snapshot, "analysis_schema_version", None
            ),
            "parser_version": getattr(snapshot, "parser_version", None),
        },
        "summary": {
            "status": status,
            "export_succeeded": True,
            "output_mode": preview.output_mode.value,
            "generation_kind": preview.generation_kind,
            "calibration_attempted": calibration["attempted"],
            "calibration_succeeded": preview.calibrated,
            "slicer_optimized": preview.slicer_optimized,
            "calibration_state": calibration["state"],
            "minimum_verified_layer_time_s": (
                preview.minimum_verified_layer_time_s
            ),
            "difference_to_target_s": target_difference,
            "maximum_shortfall_s": (
                max(0.0, -target_difference)
                if target_difference is not None
                else None
            ),
            "user_attention_required": not preview.calibrated,
        },
        "source": {
            "gcode_path": str(request.source_path),
            "sha256": preview.source_sha256,
            "file_size_bytes": getattr(snapshot, "file_size_bytes", None),
            "file_modified_ns": getattr(snapshot, "file_modified_ns", None),
            "layer_count": getattr(snapshot, "layer_count", None),
            "minimum_layer_time_s": getattr(
                snapshot, "minimum_layer_time_s", None
            ),
            "maximum_layer_time_s": getattr(
                snapshot, "maximum_layer_time_s", None
            ),
            "maximum_print_z_mm": getattr(snapshot, "maximum_print_z_mm", None),
            "global_seconds_per_deposition_mm": getattr(
                snapshot, "global_seconds_per_deposition_mm", None
            ),
            "metadata": (
                _value(metadata.to_dict())
                if callable(getattr(metadata, "to_dict", None))
                else None
            ),
            "timing_evidence": (
                _value(timing_evidence.to_dict())
                if callable(getattr(timing_evidence, "to_dict", None))
                else None
            ),
        },
        "output": {
            "path": str(output_path.resolve()),
            "sha256": output_sha256,
            "size_bytes": output_path.stat().st_size,
            "mode": preview.output_mode.value,
        },
        "request": {
            "signature": preview.request_signature,
            "signature_payload": _value(request.signature_payload()),
            "slicer_identity_key": request.slicer_identity_key,
            "adapter_type": (
                type(request.adapter).__qualname__
                if request.adapter is not None
                else None
            ),
            "profile": _profile_details(request),
            "slicer_file_protection": {
                "source_profiles_access": "read_only",
                "calibration_uses_temporary_profile_copies": True,
                "slicer_user_data_environment": "isolated_temporary_directory",
                "source_integrity_guard_enabled": True,
            },
        },
        "preview_and_geometry": {
            "generation_kind": preview.generation_kind,
            "calibrated": preview.calibrated,
            "tower_height_mm": preview.scene.tower_height_mm,
            "tower_center_xy_mm": list(preview.scene.tower_center_xy_mm),
            "source_toolpath_segment_count": preview.scene.source_segment_count,
            "displayed_toolpath_segment_count": preview.scene.displayed_segment_count,
            "warnings": list(preview.warnings),
            "notes": list(preview.scene.notes),
        },
        "calibration": calibration,
        "diagnostic_guidance": {
            "fallback_is_valid_export": (
                not preview.calibrated and not preview.slicer_optimized
            ),
            "uses_slicer_evaluated_candidate": preview.slicer_optimized,
            "recommended_user_action": (
                "STL im Slicer laden, gemeinsam mit dem Objekt slicen und die Layerzeitansicht prüfen."
                if preview.output_mode is OutputMode.STL and not preview.calibrated
                else "Keine zusätzliche Prüfung aufgrund dieses Berichts erforderlich."
            ),
            "support_hint": (
                "Bei Problemen diesen technischen Bericht zusammen mit dem Quell-G-Code und der exportierten Datei bereitstellen."
            ),
        },
    }


def build_user_report(
    preview: PreviewResult,
    request: PreviewRequest,
    *,
    output_path: Path,
    technical_report_path: Path,
    created_at: datetime,
) -> str:
    diagnostics = calibration_diagnostics(preview, request)
    lines = [
        "Kühlturm-Export – Kurzbericht",
        "=" * 34,
        "",
        f"Erstellt: {created_at.astimezone().strftime('%d.%m.%Y %H:%M:%S %Z')}",
        f"Ausgabe: {output_path}",
        f"Modus: {preview.output_mode.value.upper()}",
        "",
    ]
    if preview.calibrated:
        lines.extend(
            (
                "Ergebnis: Erfolgreich und slicerbasiert kalibriert.",
                "Der Kühlturm wurde durch einen Slicerlauf geprüft und an die gemessenen Layerzeiten angepasst.",
            )
        )
        if preview.minimum_verified_layer_time_s is not None:
            lines.append(
                "Kleinste geprüfte relevante Layerzeit: "
                f"{preview.minimum_verified_layer_time_s:.3f} s"
            )
            difference = (
                preview.minimum_verified_layer_time_s
                - request.settings.target_layer_time_s
            )
            lines.append(
                "Abweichung der kleinsten berechneten Layerzeit vom Ziel: "
                f"{difference:+.3f} s"
            )
        completed = diagnostics["iteration_count"]
        configured = diagnostics["configured_iteration_count"]
        lines.append(
            f"Durchgeführte Slicer-Durchläufe: {completed} von maximal "
            f"{configured}."
        )
        best_iteration = diagnostics["best_iteration_number"]
        if best_iteration is not None:
            lines.append(f"Exportierter bester Durchlauf: {best_iteration}.")
        if completed < configured:
            lines.append(
                "Weitere Durchläufe waren nicht erforderlich, weil die "
                "eingestellte Zielzeit bereits erreicht wurde."
            )
        lines.append(
            "Bitte kontrollieren Sie die tatsächliche Layerzeit dennoch im "
            "final gemeinsam geslicten Projekt."
        )
    elif preview.slicer_optimized:
        lines.extend(
            (
                "Ergebnis: Sliceroptimierter bester Zwischenstand exportiert.",
                "Die Ziel-Layerzeit wurde noch nicht vollständig erreicht, "
                "der ausgegebene Kühlturm ist laut den gemessenen Slicerzeiten "
                "aber besser als die analytische Ausgangsvariante.",
                "",
                "Kalibrierungsergebnis:",
                f"- Durchgeführt: {diagnostics['iteration_count']} von maximal "
                f"{diagnostics['configured_iteration_count']} Slicer-Durchläufen",
                f"- Exportierter bester Durchlauf: "
                f"{diagnostics['best_iteration_number']}",
            )
        )
        if preview.minimum_verified_layer_time_s is not None:
            difference = (
                preview.minimum_verified_layer_time_s
                - request.settings.target_layer_time_s
            )
            lines.extend(
                (
                    "- Kleinste berechnete relevante Layerzeit: "
                    f"{preview.minimum_verified_layer_time_s:.3f} s",
                    "- Abweichung dieser Layerzeit vom Ziel: "
                    f"{difference:+.3f} s",
                    "- Maximale Unterschreitung der Zielzeit: "
                    f"{max(0.0, -difference):.3f} s",
                )
            )
        deficient = diagnostics["best_deficient_layer_count"]
        if deficient is not None:
            lines.append(f"- Noch betroffene Layer: {deficient}")
        lines.extend(
            (
                "",
                "Warum wurde die Optimierung beendet?",
                f"- {diagnostics['state_explanation']}",
            )
        )
        lines.extend(
            f"- {failure['user_explanation']}"
            for failure in diagnostics["failures"][:5]
            if failure["user_explanation"] != diagnostics["state_explanation"]
        )
        lines.extend(
            (
                "",
                "Bitte kontrollieren Sie die tatsächliche Layerzeit nach dem "
                "gemeinsamen Slicen von Objekt und Kühlturm.",
            )
        )
    elif request.calibration_config.maximum_iterations == 0:
        lines.extend(
            (
                "Ergebnis: Analytischer STL-Kühlturm erfolgreich erzeugt.",
                "Slicer-Durchläufe waren auf 0 eingestellt und wurden daher "
                "bewusst nicht ausgeführt.",
                "Eine slicerbasiert bestätigte minimale Layerzeit liegt nicht vor.",
                "Bitte kontrollieren Sie die tatsächliche Layerzeit im final "
                "geslicten Projekt.",
            )
        )
    else:
        lines.extend(
            (
                "Ergebnis: Export erfolgreich, aber nicht slicerbasiert bestätigt.",
                "Es wurde ein analytisch berechneter STL-Kühlturm erzeugt.",
                "Eine garantierte minimale Layerzeit liegt deshalb nicht vor.",
                "",
                "Warum wurde nicht kalibriert?",
                f"- {diagnostics['state_explanation']}",
            )
        )
        for failure in diagnostics["failures"][:5]:
            suffix = (
                f" (Layer {failure['layer_index']})"
                if failure["layer_index"] is not None
                else ""
            )
            lines.append(f"- {failure['user_explanation']}{suffix}")
            cause = _concise_failure_cause(failure["technical_message"])
            if cause:
                lines.append(f"  Ursache: {cause}")
        lines.extend(
            (
                "",
                "Was sollte ich jetzt tun?",
                "- STL zusammen mit dem Objekt im Slicer laden und slicen.",
                "- In der Layerzeitansicht prüfen, ob die gewünschte Zeit erreicht wird.",
                "- Falls nicht, Einstellungen anpassen und den Kühlturm neu erzeugen.",
            )
        )
    user_warnings = list(
        dict.fromkeys(
            _user_visible_warning(warning)
            for warning in preview.warnings
        )
    )
    lines.extend(
        (
            "",
            "Hinweise:",
            "- Das Programm liest Slicer- und Profilinformationen "
            "ausschließlich zur Kühlturmerzeugung aus. Slicerdateien und "
            "Slicerprofile werden niemals verändert.",
        )
    )
    lines.extend(f"- {warning}" for warning in user_warnings)
    lines.extend(
        (
            "",
            f"Technischer Bericht: {technical_report_path}",
            "Dieser enthält detaillierte Angaben für Diagnose und Support.",
            "",
        )
    )
    return "\n".join(lines)
