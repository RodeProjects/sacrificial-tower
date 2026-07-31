from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from hmac import compare_digest
from pathlib import Path
from threading import RLock
from typing import Any

from cooling_tower.gcode.layer_detector import LayerAnalysis, LayerRecord
from cooling_tower.models.analysis import (
    ANALYSIS_PARSER_VERSION,
    ANALYSIS_SCHEMA_VERSION,
    GCodeAnalysisSnapshot,
)
from cooling_tower.models.gcode_metadata import GCodeMetadata
from cooling_tower.models.timing import TimingEvidence
from cooling_tower.persistence.versioned_json import atomic_write_json
from cooling_tower.tower.profile import calculate_seconds_per_deposition_mm


PERSISTENT_ANALYSIS_CACHE_SCHEMA_VERSION = 1
DEFAULT_MAXIMUM_ANALYSIS_CACHE_BYTES = 64 * 1024 * 1024
MAXIMUM_PERSISTED_LAYER_COUNT = 1_000_000

_CACHE_KEYS = {
    "cache_schema_version",
    "payload_sha256",
    "snapshot",
}
_SNAPSHOT_KEYS = {
    "gcode_path",
    "file_size_bytes",
    "file_modified_ns",
    "content_sha256",
    "analysis_schema_version",
    "parser_version",
    "analysis",
    "minimum_layer_time_s",
    "maximum_layer_time_s",
    "maximum_print_z_mm",
    "global_seconds_per_deposition_mm",
    "metadata",
    "timing_evidence",
}
_ANALYSIS_KEYS = {
    "layers",
    "confirmed_layer_changes",
    "rejected_z_candidates",
    "pre_layer_event_count",
    "pre_layer_time_s",
    "pre_layer_untimed_event_count",
}
_LAYER_INTEGER_FIELDS = (
    "index",
    "start_line",
    "first_deposition_line",
    "end_line",
    "event_count",
    "movement_count",
    "deposition_count",
    "untimed_event_count",
)
_LAYER_FLOAT_FIELDS = (
    "z_mm",
    "height_mm",
    "total_time_s",
    "deposition_time_s",
    "travel_time_s",
    "retraction_time_s",
    "unretraction_time_s",
    "dwell_time_s",
    "other_time_s",
    "deposition_path_mm",
    "deposition_e_mm",
    "untimed_distance_mm",
)
_LAYER_KEYS = set(_LAYER_INTEGER_FIELDS) | set(_LAYER_FLOAT_FIELDS)

_PATH_LOCKS_GUARD = RLock()
_PATH_LOCKS: dict[Path, RLock] = {}


class PersistentAnalysisCacheError(ValueError):
    """A persistent analysis cache cannot be used safely."""


class InvalidPersistentAnalysisCacheError(PersistentAnalysisCacheError):
    """A persistent cache is malformed, inconsistent, or corrupted."""


class UnsupportedPersistentAnalysisCacheError(PersistentAnalysisCacheError):
    """A persistent cache uses an unsupported schema version."""


def _lock_for_path(path: Path) -> RLock:
    with _PATH_LOCKS_GUARD:
        lock = _PATH_LOCKS.get(path)
        if lock is None:
            lock = RLock()
            _PATH_LOCKS[path] = lock
        return lock


def _invalid(message: str) -> InvalidPersistentAnalysisCacheError:
    return InvalidPersistentAnalysisCacheError(message)


def _mapping(
    value: object,
    expected_keys: set[str],
    name: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"{name} must be a JSON object.")
    if set(value) != expected_keys:
        raise _invalid(f"{name} contains unexpected or missing fields.")
    return value


def _integer(
    value: object,
    name: str,
    *,
    minimum: int = 0,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _invalid(f"{name} must be an integer.")
    if value < minimum or value > 2**63 - 1:
        raise _invalid(f"{name} is outside the supported range.")
    return value


def _number(
    value: object,
    name: str,
    *,
    minimum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid(f"{name} must be numeric.")
    result = float(value)
    if not math.isfinite(result):
        raise _invalid(f"{name} must be finite.")
    if minimum is not None and result < minimum:
        raise _invalid(f"{name} is below the supported range.")
    return result


def _sha256(value: object, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise _invalid(f"{name} must be a SHA-256 digest.")
    normalized = value.casefold()
    try:
        int(normalized, 16)
    except ValueError as error:
        raise _invalid(f"{name} must be a SHA-256 digest.") from error
    if value != normalized:
        raise _invalid(f"{name} must use its canonical lowercase form.")
    return normalized


def _canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            dict(payload),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise _invalid("The cache contains non-JSON or non-finite values.") from error


def _payload_digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _invalid(f"The cache contains the duplicate field {key!r}.")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise _invalid(f"The cache contains the invalid numeric value {value}.")


def _layer_to_payload(layer: LayerRecord) -> dict[str, int | float]:
    return {
        name: getattr(layer, name)
        for name in (*_LAYER_INTEGER_FIELDS, *_LAYER_FLOAT_FIELDS)
    }


def _layer_from_payload(value: object, position: int) -> LayerRecord:
    payload = _mapping(value, _LAYER_KEYS, f"Layer {position}")
    integer_values = {
        name: _integer(payload[name], f"Layer {position}.{name}")
        for name in _LAYER_INTEGER_FIELDS
    }
    float_values = {
        name: _number(
            payload[name],
            f"Layer {position}.{name}",
            minimum=(None if name == "z_mm" else 0.0),
        )
        for name in _LAYER_FLOAT_FIELDS
    }
    if integer_values["index"] != position:
        raise _invalid("Layer indices must be continuous and one-based.")
    if not (
        integer_values["start_line"]
        <= integer_values["first_deposition_line"]
        <= integer_values["end_line"]
    ):
        raise _invalid(f"Layer {position} has inconsistent line numbers.")
    if not (
        integer_values["deposition_count"]
        <= integer_values["movement_count"]
        <= integer_values["event_count"]
    ):
        raise _invalid(f"Layer {position} has inconsistent event counts.")
    if integer_values["untimed_event_count"] > integer_values["event_count"]:
        raise _invalid(f"Layer {position} has inconsistent untimed events.")
    timed_sum = sum(
        float_values[name]
        for name in (
            "deposition_time_s",
            "travel_time_s",
            "retraction_time_s",
            "unretraction_time_s",
            "dwell_time_s",
            "other_time_s",
        )
    )
    if not math.isclose(
        timed_sum,
        float_values["total_time_s"],
        rel_tol=1e-9,
        abs_tol=1e-6,
    ):
        raise _invalid(f"Layer {position} has inconsistent timing totals.")
    return LayerRecord(**integer_values, **float_values)


def snapshot_to_payload(snapshot: GCodeAnalysisSnapshot) -> dict[str, Any]:
    analysis = snapshot.analysis
    return {
        "gcode_path": str(snapshot.gcode_path),
        "file_size_bytes": snapshot.file_size_bytes,
        "file_modified_ns": snapshot.file_modified_ns,
        "content_sha256": snapshot.content_sha256,
        "analysis_schema_version": snapshot.analysis_schema_version,
        "parser_version": snapshot.parser_version,
        "analysis": {
            "layers": [_layer_to_payload(layer) for layer in analysis.layers],
            "confirmed_layer_changes": analysis.confirmed_layer_changes,
            "rejected_z_candidates": analysis.rejected_z_candidates,
            "pre_layer_event_count": analysis.pre_layer_event_count,
            "pre_layer_time_s": analysis.pre_layer_time_s,
            "pre_layer_untimed_event_count": (
                analysis.pre_layer_untimed_event_count
            ),
        },
        "minimum_layer_time_s": snapshot.minimum_layer_time_s,
        "maximum_layer_time_s": snapshot.maximum_layer_time_s,
        "maximum_print_z_mm": snapshot.maximum_print_z_mm,
        "global_seconds_per_deposition_mm": (
            snapshot.global_seconds_per_deposition_mm
        ),
        "metadata": snapshot.metadata.to_dict(),
        "timing_evidence": snapshot.timing_evidence.to_dict(),
    }


def _same_number(actual: float, expected: float) -> bool:
    return math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12)


def snapshot_from_payload(value: object) -> GCodeAnalysisSnapshot:
    payload = _mapping(value, _SNAPSHOT_KEYS, "snapshot")
    path_value = payload["gcode_path"]
    if (
        not isinstance(path_value, str)
        or not path_value
        or len(path_value) > 32_767
    ):
        raise _invalid("snapshot.gcode_path is invalid.")
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        raise _invalid("snapshot.gcode_path must be absolute.")
    try:
        path = path.resolve()
    except OSError as error:
        raise _invalid("snapshot.gcode_path cannot be resolved.") from error

    file_size = _integer(payload["file_size_bytes"], "file_size_bytes")
    modified_ns = _integer(payload["file_modified_ns"], "file_modified_ns")
    content_sha256 = _sha256(payload["content_sha256"], "content_sha256")
    analysis_schema = _integer(
        payload["analysis_schema_version"],
        "analysis_schema_version",
        minimum=1,
    )
    parser_version = _integer(
        payload["parser_version"],
        "parser_version",
        minimum=1,
    )
    if analysis_schema != ANALYSIS_SCHEMA_VERSION:
        raise UnsupportedPersistentAnalysisCacheError(
            "The cached analysis schema is not supported."
        )
    if parser_version != ANALYSIS_PARSER_VERSION:
        raise UnsupportedPersistentAnalysisCacheError(
            "The cached parser version is not supported."
        )

    analysis_payload = _mapping(payload["analysis"], _ANALYSIS_KEYS, "analysis")
    raw_layers = analysis_payload["layers"]
    if not isinstance(raw_layers, list):
        raise _invalid("analysis.layers must be a JSON array.")
    if not 1 <= len(raw_layers) <= MAXIMUM_PERSISTED_LAYER_COUNT:
        raise _invalid("analysis.layers has an unsupported size.")
    layers = tuple(
        _layer_from_payload(layer, position)
        for position, layer in enumerate(raw_layers, start=1)
    )
    analysis = LayerAnalysis(
        layers=layers,
        confirmed_layer_changes=_integer(
            analysis_payload["confirmed_layer_changes"],
            "confirmed_layer_changes",
        ),
        rejected_z_candidates=_integer(
            analysis_payload["rejected_z_candidates"],
            "rejected_z_candidates",
        ),
        pre_layer_event_count=_integer(
            analysis_payload["pre_layer_event_count"],
            "pre_layer_event_count",
        ),
        pre_layer_time_s=_number(
            analysis_payload["pre_layer_time_s"],
            "pre_layer_time_s",
            minimum=0.0,
        ),
        pre_layer_untimed_event_count=_integer(
            analysis_payload["pre_layer_untimed_event_count"],
            "pre_layer_untimed_event_count",
        ),
    )
    if analysis.confirmed_layer_changes != len(layers) - 1:
        raise _invalid("The confirmed layer-change count is inconsistent.")

    minimum_time = _number(
        payload["minimum_layer_time_s"],
        "minimum_layer_time_s",
        minimum=0.0,
    )
    maximum_time = _number(
        payload["maximum_layer_time_s"],
        "maximum_layer_time_s",
        minimum=0.0,
    )
    maximum_z = _number(payload["maximum_print_z_mm"], "maximum_print_z_mm")
    expected_minimum = min(layer.total_time_s for layer in layers)
    expected_maximum = max(layer.total_time_s for layer in layers)
    expected_z = layers[-1].z_mm
    if not _same_number(minimum_time, expected_minimum):
        raise _invalid("The minimum layer time is inconsistent.")
    if not _same_number(maximum_time, expected_maximum):
        raise _invalid("The maximum layer time is inconsistent.")
    if not _same_number(maximum_z, expected_z):
        raise _invalid("The maximum print height is inconsistent.")

    raw_global_factor = payload["global_seconds_per_deposition_mm"]
    global_factor = (
        None
        if raw_global_factor is None
        else _number(
            raw_global_factor,
            "global_seconds_per_deposition_mm",
            minimum=0.0,
        )
    )
    expected_global_factor = calculate_seconds_per_deposition_mm(layers)
    if (global_factor is None) != (expected_global_factor is None):
        raise _invalid("The global deposition-time factor is inconsistent.")
    if (
        global_factor is not None
        and expected_global_factor is not None
        and not _same_number(global_factor, expected_global_factor)
    ):
        raise _invalid("The global deposition-time factor is inconsistent.")

    metadata_payload = payload["metadata"]
    if not isinstance(metadata_payload, Mapping):
        raise _invalid("snapshot.metadata must be a JSON object.")
    try:
        metadata = GCodeMetadata.from_dict(metadata_payload)
    except (TypeError, ValueError) as error:
        raise _invalid("snapshot.metadata is invalid.") from error
    if metadata.to_dict() != dict(metadata_payload):
        raise _invalid("snapshot.metadata is not in canonical current format.")

    timing_payload = payload["timing_evidence"]
    if not isinstance(timing_payload, Mapping):
        raise _invalid("snapshot.timing_evidence must be a JSON object.")
    try:
        timing_evidence = TimingEvidence.from_dict(timing_payload)
    except (TypeError, ValueError) as error:
        raise _invalid("snapshot.timing_evidence is invalid.") from error
    if timing_evidence.to_dict() != dict(timing_payload):
        raise _invalid(
            "snapshot.timing_evidence is not in canonical current format."
        )

    return GCodeAnalysisSnapshot(
        gcode_path=path,
        file_size_bytes=file_size,
        file_modified_ns=modified_ns,
        analysis=analysis,
        minimum_layer_time_s=expected_minimum,
        maximum_layer_time_s=expected_maximum,
        maximum_print_z_mm=expected_z,
        global_seconds_per_deposition_mm=expected_global_factor,
        metadata=metadata,
        timing_evidence=timing_evidence,
        content_sha256=content_sha256,
        analysis_schema_version=analysis_schema,
        parser_version=parser_version,
    )


class PersistentGCodeAnalysisCache:
    """Atomically retain the last successful, versioned analysis snapshot."""

    def __init__(
        self,
        path: str | Path,
        *,
        maximum_bytes: int = DEFAULT_MAXIMUM_ANALYSIS_CACHE_BYTES,
    ) -> None:
        if (
            isinstance(maximum_bytes, bool)
            or not isinstance(maximum_bytes, int)
            or maximum_bytes < 1
        ):
            raise ValueError("maximum_bytes must be a positive integer.")
        self.path = Path(path).expanduser().resolve()
        self.maximum_bytes = maximum_bytes
        self._lock = _lock_for_path(self.path)

    def load(self) -> GCodeAnalysisSnapshot | None:
        with self._lock:
            try:
                statistics = self.path.stat()
            except FileNotFoundError:
                return None
            except OSError as error:
                raise PersistentAnalysisCacheError(
                    "The persistent analysis cache cannot be inspected."
                ) from error
            if statistics.st_size > self.maximum_bytes:
                raise _invalid("The persistent analysis cache is too large.")
            try:
                raw = self.path.read_bytes()
            except OSError as error:
                raise PersistentAnalysisCacheError(
                    "The persistent analysis cache cannot be read."
                ) from error
            if len(raw) > self.maximum_bytes:
                raise _invalid("The persistent analysis cache is too large.")
            try:
                payload = json.loads(
                    raw.decode("utf-8"),
                    object_pairs_hook=_reject_duplicate_keys,
                    parse_constant=_reject_json_constant,
                )
            except PersistentAnalysisCacheError:
                raise
            except (
                UnicodeError,
                json.JSONDecodeError,
                RecursionError,
                ValueError,
            ) as error:
                raise _invalid(
                    "The persistent analysis cache is not valid UTF-8 JSON."
                ) from error
            document = _mapping(payload, _CACHE_KEYS, "cache")
            version = _integer(
                document["cache_schema_version"],
                "cache_schema_version",
                minimum=1,
            )
            if version != PERSISTENT_ANALYSIS_CACHE_SCHEMA_VERSION:
                raise UnsupportedPersistentAnalysisCacheError(
                    f"Persistent cache schema {version} is not supported."
                )
            snapshot_payload = document["snapshot"]
            if not isinstance(snapshot_payload, Mapping):
                raise _invalid("cache.snapshot must be a JSON object.")
            expected_digest = _sha256(
                document["payload_sha256"],
                "payload_sha256",
            )
            actual_digest = _payload_digest(snapshot_payload)
            if not compare_digest(actual_digest, expected_digest):
                raise _invalid(
                    "The persistent analysis cache checksum is invalid."
                )
            return snapshot_from_payload(snapshot_payload)

    def save(self, snapshot: GCodeAnalysisSnapshot) -> Path:
        snapshot_payload = snapshot_to_payload(snapshot)
        # Validate the exact object that is about to become persistent. This
        # prevents a manually assembled or future incompatible snapshot from
        # poisoning the cache while leaving the successful analysis usable.
        snapshot_from_payload(snapshot_payload)
        document = {
            "cache_schema_version": PERSISTENT_ANALYSIS_CACHE_SCHEMA_VERSION,
            "payload_sha256": _payload_digest(snapshot_payload),
            "snapshot": snapshot_payload,
        }
        try:
            serialized = json.dumps(
                document,
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            ).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise _invalid(
                "The persistent analysis cache cannot be serialized."
            ) from error
        if len(serialized) + 1 > self.maximum_bytes:
            raise _invalid("The persistent analysis cache is too large.")
        with self._lock:
            return atomic_write_json(self.path, document)
