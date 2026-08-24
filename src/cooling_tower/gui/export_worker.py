from __future__ import annotations

import traceback
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Signal, Slot

from cooling_tower.gui.worker_contract import CancelableWorker
from cooling_tower.preview import (
    PreviewCancelled,
    PreviewExportService,
    PreviewRequest,
    PreviewResult,
    PreviewService,
)
from cooling_tower.preview.controller import PreviewBuildController


class ExportWorker(CancelableWorker):
    progress = Signal(int, int, str)
    succeeded = Signal(int, object)
    failed = Signal(int, str, str)
    finished = Signal(int)

    def __init__(
        self,
        request_id: int,
        preview: PreviewResult | None,
        request: PreviewRequest,
        output_root: Path,
        export_service: PreviewExportService,
        preview_service: PreviewService,
        seed_preview: PreviewResult | None = None,
        fallback_preview: PreviewResult | None = None,
        fallback_request: PreviewRequest | None = None,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.preview = preview
        self.request = request
        self.output_root = output_root
        self.export_service = export_service
        self.preview_service = preview_service
        self.seed_preview = seed_preview
        self.fallback_preview = fallback_preview
        self.fallback_request = fallback_request

    def _build_and_export(
        self,
        preview: PreviewResult | None,
        request: PreviewRequest,
        *,
        seed_preview: PreviewResult | None,
        generated_previews: list[PreviewResult],
    ) -> object:
        if preview is None:
            controller = PreviewBuildController(self.preview_service, self)
            preview = controller.execute(
                request,
                cancellation_event=self.cancellation_event,
                progress_callback=lambda percent, status: self.progress.emit(
                    self.request_id, percent, status
                ),
                seed_preview=seed_preview,
            )
            generated_previews.append(preview)
        else:
            self.progress.emit(
                self.request_id,
                75,
                "Aktuelle Vorschau wird für den Export übernommen …",
            )
        if self.cancellation_requested():
            raise PreviewCancelled()
        self.progress.emit(
            self.request_id,
            95,
            "STL-Datei und Berichte werden gespeichert …",
        )
        return self.export_service.export(preview, request, self.output_root)

    @Slot()
    def run(self) -> None:
        with self.diagnostic_scope():
            generated_previews: list[PreviewResult] = []
            try:
                try:
                    result = self._build_and_export(
                        self.preview,
                        self.request,
                        seed_preview=self.seed_preview,
                        generated_previews=generated_previews,
                    )
                except PreviewCancelled:
                    raise
                except Exception as primary_error:
                    if self.fallback_request is None:
                        raise
                    self.progress.emit(
                        self.request_id,
                        70,
                        "Gemeinsamer Bambu-Slice fehlgeschlagen; der geprüfte "
                        "STL-Notfallexport wird erstellt …",
                    )
                    try:
                        fallback_result = self._build_and_export(
                            self.fallback_preview,
                            self.fallback_request,
                            seed_preview=None,
                            generated_previews=generated_previews,
                        )
                    except PreviewCancelled:
                        raise
                    except Exception as fallback_error:
                        raise RuntimeError(
                            "Der gemeinsame Bambu-Slice und der STL-Notfallexport "
                            "sind fehlgeschlagen."
                        ) from fallback_error
                    result = replace(
                        fallback_result,
                        emergency_fallback_used=True,
                        primary_failure_reason=str(primary_error),
                    )
            except PreviewCancelled:
                pass
            except Exception as error:
                if not self.cancellation_requested():
                    self.failed.emit(
                        self.request_id,
                        str(error),
                        traceback.format_exc(),
                    )
            else:
                self.succeeded.emit(self.request_id, result)
            finally:
                for generated_preview in generated_previews:
                    generated_preview.dispose()
                if generated_previews:
                    self.diagnose("temporary_data_cleaned")
                self.finished.emit(self.request_id)
