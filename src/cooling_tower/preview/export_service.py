from __future__ import annotations

import json
from datetime import datetime
from hmac import compare_digest
from pathlib import Path
from cooling_tower.export_io import atomic_export, atomic_export_data, export_directory

from cooling_tower.file_integrity import sha256_file
from cooling_tower.preview.models import (
    OutputMode,
    PreviewExportResult,
    PreviewRequest,
    PreviewResult,
)
from cooling_tower.preview.reporting import (
    build_technical_report,
    build_user_report,
)
from cooling_tower.services.output_service import sanitize_filename_component


class StalePreviewError(RuntimeError):
    pass


class PreviewExportService:
    """Export only artifacts proven to match the current preview request."""

    def export(
        self,
        preview: PreviewResult,
        request: PreviewRequest,
        output_root: str | Path,
        *, cancellation_callback=None,
    ) -> PreviewExportResult:
        validate_output = getattr(
            getattr(request, "adapter", None), "validate_output_directory", None
        )
        if callable(validate_output):
            validate_output(request.effective_profile, output_root)
        current_signature = request.signature()
        if current_signature != preview.request_signature:
            raise StalePreviewError(
                "Die Vorschau stimmt nicht mehr mit den aktuellen Einstellungen überein."
            )
        source = request.source_path
        if not request.original_source_is_current():
            raise StalePreviewError(
                "Die ursprüngliche Quelldatei wurde nach der Vorschau verändert."
            )
        prepared = request.prepared_analysis_source
        if prepared is not None and not prepared.matches_analysis_gcode():
            raise StalePreviewError(
                "Der vorbereitete Analyse-G-Code wurde nach der Vorschau verändert."
            )
        if not source.is_file() or sha256_file(source) != preview.source_sha256:
            raise StalePreviewError(
                "Der Quell-G-Code wurde nach der Vorschau verändert."
            )
        artifact = preview.artifact_path
        if (
            not artifact.is_file()
            or sha256_file(artifact) != preview.artifact_sha256
        ):
            raise StalePreviewError(
                "Das geprüfte Vorschau-Artefakt ist nicht mehr unverändert verfügbar."
            )
        project = preview.project_path
        if project is not None and (
            preview.project_sha256 is None
            or not project.is_file()
            or sha256_file(project) != preview.project_sha256
        ):
            raise StalePreviewError(
                "Das gemeinsame 3MF ist nicht mehr unverändert verfügbar."
            )

        profile = request.effective_profile
        installation = getattr(profile, 'installation', None)
        protected_roots = ((installation.executable_path.parent, *installation.profile_roots)
                           if installation is not None else ())
        protected_files = (source, request.output_source_path, *getattr(profile, 'source_paths', ()))
        protections = dict(protected_files=protected_files, protected_roots=protected_roots,
                           cancellation_callback=cancellation_callback)
        created_at = datetime.now().astimezone()
        stamp = created_at.strftime("%Y%m%d_%H%M%S")
        source_name = sanitize_filename_component(request.output_source_path.stem)
        base_name = f"{stamp}_{source_name}"
        with export_directory(output_root, base_name, protected_files=protected_files,
                              protected_roots=protected_roots) as destination:
            extension = (
                ".gcode" if preview.output_mode is OutputMode.GCODE else ".stl"
            )
            output_name = (
                f"{source_name}_mit_kuehlturm{extension}"
                if preview.output_mode is OutputMode.GCODE
                else f"{source_name}_kuehlturm{extension}"
            )
            output_path = destination / output_name
            atomic_export(artifact, output_path, expected_sha256=preview.artifact_sha256, **protections)
            output_hash = sha256_file(output_path)
            if not compare_digest(output_hash, preview.artifact_sha256):
                raise StalePreviewError(
                    "Das Vorschau-Artefakt wurde während des Exports verändert."
                )
            project_output_path = None
            if project is not None:
                project_output_path = destination / (
                    f"{source_name}_mit_kuehlturm.3mf"
                )
                atomic_export(project, project_output_path, expected_sha256=preview.project_sha256, **protections)
                if sha256_file(project_output_path) != preview.project_sha256:
                    raise StalePreviewError(
                        "Das gemeinsame 3MF wurde während des Exports verändert."
                    )
            report_path = destination / "export_report.json"
            user_report_path = destination / "export_summary.txt"
            report = build_technical_report(
                preview,
                request,
                output_path=output_path,
                output_sha256=output_hash,
                created_at=created_at,
                project_path=project_output_path,
            )
            atomic_export_data((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode('utf-8'),
                               report_path, **protections)
            atomic_export_data(
                build_user_report(
                    preview,
                    request,
                    output_path=output_path,
                    technical_report_path=report_path.resolve(),
                    created_at=created_at,
                    project_path=project_output_path,
                ).encode('utf-8'), user_report_path, **protections,
            )
            self._finish_export(preview, request, destination, protections)
        return PreviewExportResult(
            full_tower_infill_simulated=request.settings.simulate_full_tower_infill,
            tower_supports_disabled_simulated=request.settings.simulate_tower_without_supports,
            source_supports_simulated=request.settings.simulate_source_supports,
            supports_simulated=bool(getattr(request.effective_profile, "supports_simulated", False)),
            draft_shield_simulated=bool(getattr(request.effective_profile, "draft_shield_simulated", False)),
            output_mode=preview.output_mode,
            run_directory=destination.resolve(),
            output_path=output_path.resolve(),
            report_path=report_path.resolve(),
            user_report_path=user_report_path.resolve(),
            calibrated=preview.calibrated,
            slicer_optimized=preview.slicer_optimized,
            minimum_verified_layer_time_s=(
                preview.minimum_verified_layer_time_s
            ),
            source_sha256=preview.source_sha256,
            output_sha256=output_hash,
            project_path=(
                project_output_path.resolve()
                if project_output_path is not None else None
            ),
            target_layer_time_s=preview.target_layer_time_s,
            calibration_time_tolerance_s=(
                preview.calibration_time_tolerance_s
            ),
        )

    def _finish_export(self, preview, request, destination, protections) -> None:
        """Complete method-specific outputs while the new folder is still owned."""
