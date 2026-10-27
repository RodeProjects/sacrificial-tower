from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from cooling_tower.gcode.layer_detector import LayerAnalysis, LayerRecord
from cooling_tower.gcode.metadata_parser import GCodeMetadataCollector
from cooling_tower.gcode.parser import ParsedGCodeLine
from cooling_tower.models.gcode_metadata import GCodeMetadata
from cooling_tower.models.timing import TimingEvidence

try:
    from cooling_tower import _native_timing
except (ImportError, OSError):
    _native_timing = None


CancellationCallback = Callable[[], bool]


class NativeAnalysisCancelled(RuntimeError):
    """Raised when the native core observes a cancellation request."""


@dataclass(frozen=True, slots=True)
class NativePreviewProduct:
    segments: tuple[tuple[float, float, float, float, float, float], ...]
    source_segment_count: int
    occupied_bounds: tuple[float, float, float, float] | None
    seam_points: tuple[tuple[float, float, float], ...] = ()


@dataclass(frozen=True, slots=True)
class NativeInfillProduct:
    tower_block_count: int
    sparse_tower_infill: bool
    label_bounds: Mapping[int, tuple[float, float, float, float]]
    sparse_labels: frozenset[int]


@dataclass(frozen=True, slots=True)
class NativeAnalysisResult:
    analysis: LayerAnalysis | None
    metadata: GCodeMetadata | None
    timing_evidence: TimingEvidence | None
    preview: NativePreviewProduct | None
    infill: NativeInfillProduct | None
    status: str
    fallback_line: int = 0
    fallback_command: str = ""
    message: str = ""
    diagnostics: Mapping[str, int] | None = None

    @property
    def succeeded(self) -> bool:
        return (
            self.status == "success"
            and self.analysis is not None
            and self.metadata is not None
            and self.timing_evidence is not None
        )


def native_full_analysis_available() -> bool:
    return (
        _native_timing is not None
        and callable(getattr(_native_timing, "analyze_file", None))
        and not _force_python_analysis()
    )


def _force_python_analysis() -> bool:
    value = os.environ.get("COOLING_TOWER_FORCE_PYTHON_ANALYSIS", "")
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def analyze_native_gcode(
    source: Path,
    *,
    bambu_compatible: bool,
    anycubic_slicer_next_compatible: bool,
    use_explicit_layer_markers: bool,
    collect_preview: bool = False,
    maximum_preview_segments: int = 60_000,
    collect_infill: bool = False,
    cancellation_callback: CancellationCallback | None = None,
    orca_policy=None,
    prusa_policy=None,
) -> NativeAnalysisResult:
    if not native_full_analysis_available():
        return NativeAnalysisResult(
            analysis=None,
            metadata=None,
            timing_evidence=None,
            preview=None,
            infill=None,
            status="unavailable",
            message="The native full-analysis extension is unavailable.",
        )
    try:
        if collect_preview and getattr(_native_timing, "ENGINE_VERSION", 0) < 6:
            raise TypeError("Outer-wall seam preview data requires native engine version 6.")
        if (not bambu_compatible and use_explicit_layer_markers
                and getattr(_native_timing, "ENGINE_VERSION", 0) < 4):
            raise TypeError("Prusa-style layer markers require native engine version 4.")
        arguments = (
            str(source),
            bool(bambu_compatible),
            bool(anycubic_slicer_next_compatible),
            bool(use_explicit_layer_markers),
            bool(collect_preview),
            bool(collect_infill),
            int(maximum_preview_segments),
            cancellation_callback,
        )
        if orca_policy is not None:
            arguments += ({"marlin2": orca_policy.uses_junction_deviation, "limits": orca_policy.limits},)
        elif prusa_policy is not None:
            # An old extension must fall back instead of silently selecting
            # the Orca policy for Prusa's different junction equations.
            if getattr(_native_timing, "ENGINE_VERSION", 0) < 3:
                raise TypeError("Prusa timing requires native engine version 3.")
            arguments += ({"producer": "prusa", "marlin2": prusa_policy.uses_junction_deviation,
                           "limits": prusa_policy.limits},)
        payload = _native_timing.analyze_file(*arguments)
    except (OverflowError, RuntimeError, TypeError, ValueError) as error:
        return NativeAnalysisResult(
            analysis=None,
            metadata=None,
            timing_evidence=None,
            preview=None,
            infill=None,
            status="native_error",
            message=str(error),
        )
    if not isinstance(payload, Mapping):
        return NativeAnalysisResult(
            analysis=None,
            metadata=None,
            timing_evidence=None,
            preview=None,
            infill=None,
            status="invalid_result",
            message="The native analyzer returned no mapping.",
        )
    status = str(payload.get("status", "invalid_result"))
    if status == "cancelled":
        raise NativeAnalysisCancelled(
            str(payload.get("message") or "G-Code analysis was cancelled.")
        )
    if status != "success":
        return NativeAnalysisResult(
            analysis=None,
            metadata=None,
            timing_evidence=None,
            preview=None,
            infill=None,
            status=status,
            fallback_line=_safe_int(payload.get("fallback_line")),
            fallback_command=str(payload.get("fallback_command") or ""),
            message=str(payload.get("message") or ""),
            diagnostics=_validated_diagnostics(payload.get("diagnostics")),
        )
    try:
        analysis = _build_layer_analysis(payload)
        metadata, timing_evidence = _build_metadata(source, payload)
        preview = _build_preview(payload) if collect_preview else None
        infill = _build_infill(payload) if collect_infill else None
        diagnostics = _validated_diagnostics(payload.get("diagnostics"))
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        return NativeAnalysisResult(
            analysis=None,
            metadata=None,
            timing_evidence=None,
            preview=None,
            infill=None,
            status="invalid_result",
            message=f"Invalid native result: {error}",
        )
    return NativeAnalysisResult(
        analysis=analysis,
        metadata=metadata,
        timing_evidence=timing_evidence,
        preview=preview,
        infill=infill,
        status="success",
        diagnostics=diagnostics,
    )


def _safe_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return 0


def _finite_non_negative(value: object, field_name: str) -> float:
    number = float(value)  # type: ignore[arg-type]
    if not math.isfinite(number) or number < 0.0:
        raise ValueError(f"{field_name} must be finite and non-negative")
    return number


def _finite(value: object, field_name: str) -> float:
    number = float(value)  # type: ignore[arg-type]
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite")
    return number


def _required_int(row: Mapping[str, object], field_name: str) -> int:
    value = int(row[field_name])
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return value


def _build_layer_analysis(payload: Mapping[str, object]) -> LayerAnalysis:
    rows = payload["layers"]
    if not isinstance(rows, (tuple, list)) or not rows:
        raise ValueError("layers must be a non-empty sequence")
    layers: list[LayerRecord] = []
    for expected_index, untyped in enumerate(rows, start=1):
        if not isinstance(untyped, Mapping):
            raise TypeError("layer entries must be mappings")
        index = _required_int(untyped, "index")
        if index != expected_index:
            raise ValueError("layer indices must be consecutive")
        start_line = _required_int(untyped, "start_line")
        first_deposition_line = _required_int(
            untyped, "first_deposition_line"
        )
        end_line = _required_int(untyped, "end_line")
        if end_line < start_line:
            raise ValueError("layer line bounds are reversed")
        layers.append(
            LayerRecord(
                index=index,
                z_mm=_finite_non_negative(untyped["z_mm"], "z_mm"),
                height_mm=_finite_non_negative(
                    untyped["height_mm"], "height_mm"
                ),
                start_line=start_line,
                first_deposition_line=first_deposition_line,
                end_line=end_line,
                event_count=_required_int(untyped, "event_count"),
                movement_count=_required_int(untyped, "movement_count"),
                deposition_count=_required_int(untyped, "deposition_count"),
                total_time_s=_finite_non_negative(
                    untyped["total_time_s"], "total_time_s"
                ),
                deposition_time_s=_finite_non_negative(
                    untyped["deposition_time_s"], "deposition_time_s"
                ),
                travel_time_s=_finite_non_negative(
                    untyped["travel_time_s"], "travel_time_s"
                ),
                retraction_time_s=_finite_non_negative(
                    untyped["retraction_time_s"], "retraction_time_s"
                ),
                unretraction_time_s=_finite_non_negative(
                    untyped["unretraction_time_s"], "unretraction_time_s"
                ),
                dwell_time_s=_finite_non_negative(
                    untyped["dwell_time_s"], "dwell_time_s"
                ),
                other_time_s=_finite_non_negative(
                    untyped["other_time_s"], "other_time_s"
                ),
                deposition_path_mm=_finite_non_negative(
                    untyped["deposition_path_mm"], "deposition_path_mm"
                ),
                deposition_e_mm=_finite_non_negative(
                    untyped["deposition_e_mm"], "deposition_e_mm"
                ),
                untimed_event_count=_required_int(
                    untyped, "untimed_event_count"
                ),
                untimed_distance_mm=_finite_non_negative(
                    untyped["untimed_distance_mm"], "untimed_distance_mm"
                ),
            )
        )
    return LayerAnalysis(
        layers=tuple(layers),
        confirmed_layer_changes=_safe_int(
            payload["confirmed_layer_changes"]
        ),
        rejected_z_candidates=_safe_int(payload["rejected_z_candidates"]),
        pre_layer_event_count=_safe_int(payload["pre_layer_event_count"]),
        pre_layer_time_s=_finite_non_negative(
            payload["pre_layer_time_s"], "pre_layer_time_s"
        ),
        pre_layer_untimed_event_count=_safe_int(
            payload["pre_layer_untimed_event_count"]
        ),
    )


def _build_metadata(
    source: Path,
    payload: Mapping[str, object],
) -> tuple[GCodeMetadata, TimingEvidence]:
    rows = payload["metadata_events"]
    if not isinstance(rows, (tuple, list)):
        raise TypeError("metadata_events must be a sequence")
    collector = GCodeMetadataCollector(source)
    for row in rows:
        if not isinstance(row, (tuple, list)) or len(row) != 4:
            raise TypeError("metadata event shape is invalid")
        number, command, parameters, comment = row
        if command is not None and not isinstance(command, str):
            raise TypeError("metadata command must be text")
        if comment is not None and not isinstance(comment, str):
            raise TypeError("metadata comment must be text")
        if not isinstance(parameters, dict):
            raise TypeError("metadata parameters must be a dictionary")
        normalized_parameters = {
            str(key): _finite(value, "metadata parameter")
            for key, value in parameters.items()
        }
        collector.consume(
            ParsedGCodeLine(
                number=int(number),
                raw_text="",
                code_text="",
                command=command,
                parameters=normalized_parameters,
                comment=comment,
                unparsed_text=None,
            )
        )
    return collector.finish()


def _build_preview(payload: Mapping[str, object]) -> NativePreviewProduct:
    rows = payload["preview_segments"]
    if not isinstance(rows, (tuple, list)):
        raise TypeError("preview_segments must be a sequence")
    segments: list[tuple[float, float, float, float, float, float]] = []
    for row in rows:
        if not isinstance(row, (tuple, list)) or len(row) != 6:
            raise TypeError("preview segment shape is invalid")
        segments.append(
            tuple(
                _finite(value, "preview coordinate") for value in row
            )  # type: ignore[arg-type]
        )
    bounds_payload = payload.get("occupied_bounds")
    bounds = None
    if bounds_payload is not None:
        if not isinstance(bounds_payload, (tuple, list)) or len(bounds_payload) != 4:
            raise TypeError("occupied_bounds shape is invalid")
        bounds = tuple(
            _finite(value, "occupied bound") for value in bounds_payload
        )  # type: ignore[assignment]
    return NativePreviewProduct(
        segments=tuple(segments),
        source_segment_count=_required_payload_int(
            payload, "preview_source_segment_count"
        ),
        occupied_bounds=bounds,
        seam_points=tuple(tuple(_finite(value, "seam coordinate") for value in point)
            for point in payload["seam_points"] if _valid_seam_shape(point)),
    )


def _valid_seam_shape(point):
    if not isinstance(point, (tuple, list)) or len(point) != 3:
        raise TypeError("seam point shape is invalid")
    return True


def _required_payload_int(
    payload: Mapping[str, object], field_name: str
) -> int:
    value = int(payload[field_name])
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return value


def _build_infill(payload: Mapping[str, object]) -> NativeInfillProduct:
    untyped = payload["infill"]
    if not isinstance(untyped, Mapping):
        raise TypeError("infill must be a mapping")
    bounds_payload = untyped.get("label_bounds", {})
    if not isinstance(bounds_payload, Mapping):
        raise TypeError("label_bounds must be a mapping")
    bounds: dict[int, tuple[float, float, float, float]] = {}
    for label, values in bounds_payload.items():
        if not isinstance(values, (tuple, list)) or len(values) != 4:
            raise TypeError("label bounds shape is invalid")
        bounds[int(label)] = tuple(
            _finite(value, "label bound") for value in values
        )  # type: ignore[assignment]
    sparse_payload = untyped.get("sparse_labels", ())
    if not isinstance(sparse_payload, (tuple, list)):
        raise TypeError("sparse_labels must be a sequence")
    return NativeInfillProduct(
        tower_block_count=max(0, int(untyped.get("tower_block_count", 0))),
        sparse_tower_infill=bool(untyped.get("sparse_tower_infill", False)),
        label_bounds=bounds,
        sparse_labels=frozenset(int(value) for value in sparse_payload),
    )


def _validated_diagnostics(value: object) -> Mapping[str, int]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, int] = {}
    for key, item in value.items():
        numeric = int(item)  # type: ignore[arg-type]
        if numeric < 0:
            raise ValueError("native diagnostic counters must be non-negative")
        result[str(key)] = numeric
    return result
