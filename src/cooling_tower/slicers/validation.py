from __future__ import annotations

import json
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from cooling_tower.slicers.models import SliceRequest, SliceResult
from cooling_tower.slicers.process import SecureSlicerProcessRunner

if TYPE_CHECKING:
    from cooling_tower.slicers.base import BaseSlicerAdapter


@dataclass(frozen=True, slots=True)
class SliceSemantics:
    success: bool
    timed_out: bool
    cancelled: bool
    crashed: bool
    return_code: int | None
    file_extensions: tuple[str, ...]
    gcode_readable: bool
    layer_count: int | None
    maximum_print_z_mm: float | None
    total_layer_time_s: float | None
    slicer_family: str | None
    slicer_product: str | None
    timing_material_metadata: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class BackendValidationReport:
    adapter_id: str
    product_name: str
    equivalent: bool
    differences: tuple[str, ...]
    legacy: SliceSemantics
    qprocess: SliceSemantics

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def write(self, path: str | Path) -> Path:
        destination = Path(path).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return destination


def _slice_semantics(result: SliceResult) -> SliceSemantics:
    extensions = tuple(sorted({path.suffix.casefold() for path in result.output_files}))
    readable = False
    layer_count: int | None = None
    maximum_z: float | None = None
    total_time: float | None = None
    family: str | None = None
    product: str | None = None
    selected_metadata: tuple[tuple[str, str], ...] = ()
    if result.success and result.gcode_path is not None:
        # Import lazily so ``import cooling_tower.slicers`` does not enter the
        # services package while the slicer facade is still initialising.
        from cooling_tower.services.analysis_service import GCodeAnalysisService

        try:
            snapshot = GCodeAnalysisService().analyze(result.gcode_path, force=True)
        except (OSError, UnicodeError, ValueError):
            pass
        else:
            readable = True
            layer_count = snapshot.layer_count
            maximum_z = round(snapshot.maximum_print_z_mm, 6)
            total_time = round(sum(layer.total_time_s for layer in snapshot.layers), 6)
            family = snapshot.metadata.slicer.family.value
            product = snapshot.metadata.slicer.product_name
            selected_metadata = tuple(
                sorted(
                    (item.key.casefold(), item.canonical_value())
                    for item in snapshot.metadata.typed_config
                    if any(
                        marker in item.key.casefold()
                        for marker in ("time", "filament", "material")
                    )
                )
            )
    return SliceSemantics(
        success=result.success,
        timed_out=result.timed_out,
        cancelled=result.cancelled,
        crashed=result.crashed,
        return_code=result.return_code,
        file_extensions=extensions,
        gcode_readable=readable,
        layer_count=layer_count,
        maximum_print_z_mm=maximum_z,
        total_layer_time_s=total_time,
        slicer_family=family,
        slicer_product=product,
        timing_material_metadata=selected_metadata,
    )


def validate_adapter_backends(
    adapter: BaseSlicerAdapter,
    request: SliceRequest,
    *,
    report_path: str | Path | None = None,
) -> BackendValidationReport:
    """Run one adapter sequentially in isolated legacy and QProcess workspaces."""

    from cooling_tower.slicers.qprocess_backend import QProcessSlicerProcessRunner

    with tempfile.TemporaryDirectory(
        prefix=f"cooling_tower_backend_validation_{adapter.adapter_id}_"
    ) as temporary:
        root = Path(temporary)
        results: dict[str, SliceResult] = {}
        for backend, runner in (
            ("legacy", SecureSlicerProcessRunner()),
            ("qprocess", QProcessSlicerProcessRunner()),
        ):
            backend_request = replace(
                request,
                output_directory=root / backend / "output",
                diagnostics_root=root / backend / "diagnostics",
            )
            prepared = adapter.prepare_slice(backend_request)
            try:
                outcome = adapter.execute_prepared_slice(prepared, runner=runner)
                results[backend] = adapter.finalize_slice(prepared, outcome)
            finally:
                adapter.cleanup_prepared_slice(prepared)
        legacy = _slice_semantics(results["legacy"])
        qprocess = _slice_semantics(results["qprocess"])
        differences = tuple(
            field
            for field in SliceSemantics.__dataclass_fields__
            if getattr(legacy, field) != getattr(qprocess, field)
        )
        report = BackendValidationReport(
            adapter_id=adapter.adapter_id,
            product_name=adapter.product_name,
            equivalent=not differences,
            differences=differences,
            legacy=legacy,
            qprocess=qprocess,
        )
        if report_path is not None:
            report.write(report_path)
        return report
