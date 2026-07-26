from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

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
    ) -> PreviewExportResult:
        current_signature = request.signature()
        if current_signature != preview.request_signature:
            raise StalePreviewError(
                "Die Vorschau stimmt nicht mehr mit den aktuellen Einstellungen überein."
            )
        source = request.source_path
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

        root = Path(output_root).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        created_at = datetime.now().astimezone()
        stamp = created_at.strftime("%Y%m%d_%H%M%S")
        source_name = sanitize_filename_component(source.stem)
        base_name = f"{stamp}_{source_name}"
        destination = root / base_name
        suffix = 2
        while destination.exists():
            destination = root / f"{base_name}_{suffix}"
            suffix += 1
        destination.mkdir()
        extension = ".gcode" if preview.output_mode is OutputMode.GCODE else ".stl"
        output_name = (
            f"{source_name}_mit_kuehlturm{extension}"
            if preview.output_mode is OutputMode.GCODE
            else f"{source_name}_kuehlturm{extension}"
        )
        output_path = destination / output_name
        shutil.copy2(artifact, output_path)
        output_hash = sha256_file(output_path)
        report_path = destination / "export_report.json"
        user_report_path = destination / "export_summary.txt"
        report = build_technical_report(
            preview,
            request,
            output_path=output_path,
            output_sha256=output_hash,
            created_at=created_at,
        )
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        user_report_path.write_text(
            build_user_report(
                preview,
                request,
                output_path=output_path,
                technical_report_path=report_path.resolve(),
                created_at=created_at,
            ),
            encoding="utf-8",
        )
        return PreviewExportResult(
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
        )
