from __future__ import annotations

from collections.abc import Callable
from hmac import compare_digest
from pathlib import Path
from threading import RLock

from cooling_tower.diagnostic_context import record_diagnostic
from cooling_tower.file_integrity import sha256_file
from cooling_tower.gcode.layer_detector import LayerDetector
from cooling_tower.gcode.metadata_parser import GCodeMetadataCollector
from cooling_tower.gcode.parser import (
    MachineStateTracker,
    MotionTimingPlanner,
    iter_parsed_gcode_lines,
    validate_gcode_path,
)
from cooling_tower.models import GCodeAnalysisSnapshot
from cooling_tower.persistence.analysis_cache import (
    PersistentAnalysisCacheError,
    PersistentGCodeAnalysisCache,
)
from cooling_tower.tower.profile import (
    calculate_seconds_per_deposition_mm,
)


AnalysisProgressCallback = Callable[[int, str], None]
CancellationCallback = Callable[[], bool]


def _uses_bambu_studio_timing(source: Path) -> bool:
    """Detect Bambu-generated G-code before streaming motion analysis."""

    try:
        with source.open("rb") as handle:
            header = handle.read(16 * 1024).lower()
    except OSError:
        return False
    return b"bambustudio" in header or b"bambu studio" in header


def _uses_bambu_studio_layer_markers(source: Path) -> bool:
    """Detect Bambu's authoritative layer tags near the G-code start."""

    try:
        with source.open("rb") as handle:
            header = handle.read(1024 * 1024).lower()
    except OSError:
        return False
    return (
        (b"bambustudio" in header or b"bambu studio" in header)
        and b"; change_layer" in header
        and b"; z_height:" in header
        and b"; layer_height:" in header
    )


class AnalysisCancelled(RuntimeError):
    """Raised when an obsolete background analysis is cancelled."""


class GCodeChangedDuringAnalysisError(RuntimeError):
    """Raised when a source file changes while it is being parsed."""


class GCodeAnalysisService:
    """Analyze G-code once and reuse snapshots while the file is unchanged."""

    def __init__(
        self,
        persistent_cache_path: str | Path | None = None,
    ) -> None:
        self._cache: dict[Path, GCodeAnalysisSnapshot] = {}
        self._lock = RLock()
        self._operation_lock = RLock()
        self._persistent_cache = (
            PersistentGCodeAnalysisCache(persistent_cache_path)
            if persistent_cache_path is not None
            else None
        )
        self._last_cache_hit_kind: str | None = None

    @property
    def persistent_cache_path(self) -> Path | None:
        cache = self._persistent_cache
        return cache.path if cache is not None else None

    def analyze(
        self,
        gcode_path: str | Path,
        *,
        progress_callback: AnalysisProgressCallback | None = None,
        cancellation_callback: CancellationCallback | None = None,
        force: bool = False,
    ) -> GCodeAnalysisSnapshot:
        # One service may be called by UI and worker threads. Serializing the
        # complete lookup/analysis/store transaction prevents duplicate
        # parsing and makes "last successful analysis" deterministic.
        with self._operation_lock:
            return self._analyze_locked(
                gcode_path,
                progress_callback=progress_callback,
                cancellation_callback=cancellation_callback,
                force=force,
            )

    def _analyze_locked(
        self,
        gcode_path: str | Path,
        *,
        progress_callback: AnalysisProgressCallback | None,
        cancellation_callback: CancellationCallback | None,
        force: bool,
    ) -> GCodeAnalysisSnapshot:
        source = validate_gcode_path(gcode_path).resolve()
        before = source.stat()
        notify = progress_callback or (lambda percent, status: None)
        cancelled = cancellation_callback or (lambda: False)

        if not force:
            cached = self._get_cached_locked(source)
            if cached is not None:
                status = (
                    "Persistente G-Code-Analyse wird verwendet"
                    if self._last_cache_hit_kind == "persistent"
                    else "Zwischengespeicherte G-Code-Analyse wird verwendet"
                )
                notify(
                    100,
                    status,
                )
                return cached

        notify(0, "G-Code wird analysiert")
        bambu_timing = _uses_bambu_studio_timing(source)
        explicit_bambu_layers = _uses_bambu_studio_layer_markers(source)
        tracker = MachineStateTracker(bambu_compatible=bambu_timing)
        motion_planner = MotionTimingPlanner(
            bambu_compatible=bambu_timing
        )
        detector = LayerDetector(
            use_explicit_markers=explicit_bambu_layers
        )
        metadata_collector = GCodeMetadataCollector(source)
        pending_layer_start_line: int | None = None
        pending_layer_z_mm: float | None = None

        processed_bytes = 0
        last_reported_percent = 0
        for parsed_line in iter_parsed_gcode_lines(source):
            if cancelled():
                raise AnalysisCancelled("G-Code analysis was cancelled.")
            processed_bytes += len(parsed_line.raw_text.encode("utf-8")) + 1
            if parsed_line.number % 2_000 == 0 and before.st_size > 0:
                percent = min(
                    95,
                    max(1, round(processed_bytes / before.st_size * 95)),
                )
                if percent > last_reported_percent:
                    last_reported_percent = percent
                    notify(percent, "G-Code-Inhalt wird ausgewertet")
            metadata_collector.consume(parsed_line)
            if explicit_bambu_layers:
                comment = (parsed_line.comment or "").strip()
                if comment == "CHANGE_LAYER":
                    pending_layer_start_line = parsed_line.number
                    pending_layer_z_mm = None
                elif (
                    pending_layer_start_line is not None
                    and comment.startswith("Z_HEIGHT:")
                ):
                    try:
                        pending_layer_z_mm = float(
                            comment.partition(":")[2].strip()
                        )
                    except ValueError:
                        pending_layer_start_line = None
                        pending_layer_z_mm = None
                elif (
                    pending_layer_start_line is not None
                    and pending_layer_z_mm is not None
                    and comment.startswith("LAYER_HEIGHT:")
                ):
                    try:
                        layer_height_mm = float(
                            comment.partition(":")[2].strip()
                        )
                    except ValueError:
                        pending_layer_start_line = None
                        pending_layer_z_mm = None
                    else:
                        detector.mark_layer(
                            start_line=pending_layer_start_line,
                            z_mm=pending_layer_z_mm,
                            height_mm=layer_height_mm,
                        )
                        pending_layer_start_line = None
                        pending_layer_z_mm = None
            event = tracker.process_line(parsed_line)
            if event is not None:
                for timed_event in motion_planner.process_event(event):
                    detector.process_event(timed_event)

        for timed_event in motion_planner.finish():
            detector.process_event(timed_event)

        if cancelled():
            raise AnalysisCancelled("G-Code analysis was cancelled.")

        notify(97, "Layerzeiten und Konfiguration werden zusammengefasst")
        analysis = detector.finish()
        if not analysis.layers:
            raise ValueError("No printable layers were detected in the G-code.")

        after = source.stat()
        if (
            after.st_size != before.st_size
            or after.st_mtime_ns != before.st_mtime_ns
        ):
            raise GCodeChangedDuringAnalysisError(
                "The G-code file changed while it was being analyzed."
            )

        notify(98, "G-Code-Inhalt wird für die Wiederverwendung geprüft")
        try:
            content_sha256 = sha256_file(source)
            after_hash = source.stat()
        except OSError as error:
            raise GCodeChangedDuringAnalysisError(
                "The G-code file became unavailable while it was being hashed."
            ) from error
        if (
            after_hash.st_size != after.st_size
            or after_hash.st_mtime_ns != after.st_mtime_ns
        ):
            raise GCodeChangedDuringAnalysisError(
                "The G-code file changed while it was being hashed."
            )
        after = after_hash

        layers = analysis.layers
        metadata, timing_evidence = metadata_collector.finish()
        snapshot = GCodeAnalysisSnapshot(
            gcode_path=source,
            file_size_bytes=after.st_size,
            file_modified_ns=after.st_mtime_ns,
            analysis=analysis,
            minimum_layer_time_s=min(
                layer.total_time_s for layer in layers
            ),
            maximum_layer_time_s=max(
                layer.total_time_s for layer in layers
            ),
            maximum_print_z_mm=layers[-1].z_mm,
            global_seconds_per_deposition_mm=(
                calculate_seconds_per_deposition_mm(layers)
            ),
            metadata=metadata,
            timing_evidence=timing_evidence,
            content_sha256=content_sha256,
        )
        with self._lock:
            self._cache[source] = snapshot
        persistent_cache = self._persistent_cache
        if persistent_cache is not None:
            try:
                persistent_cache.save(snapshot)
            except (OSError, PersistentAnalysisCacheError) as error:
                record_diagnostic(
                    "persistent_analysis_cache_write_failed",
                    error_type=type(error).__name__,
                )
            else:
                record_diagnostic(
                    "persistent_analysis_cache_stored",
                    layer_count=snapshot.layer_count,
                    file_size_bytes=snapshot.file_size_bytes,
                )
        notify(100, "G-Code-Analyse abgeschlossen")
        return snapshot

    def get_cached(
        self,
        gcode_path: str | Path,
    ) -> GCodeAnalysisSnapshot | None:
        with self._operation_lock:
            return self._get_cached_locked(gcode_path)

    def _get_cached_locked(
        self,
        gcode_path: str | Path,
    ) -> GCodeAnalysisSnapshot | None:
        self._last_cache_hit_kind = None
        try:
            source = Path(gcode_path).expanduser().resolve(strict=True)
        except (FileNotFoundError, OSError):
            return None
        with self._lock:
            snapshot = self._cache.get(source)
        if snapshot is not None:
            if self._snapshot_matches_source(snapshot, source):
                self._last_cache_hit_kind = "memory"
                record_diagnostic("gcode_analysis_memory_cache_hit")
                return snapshot
            with self._lock:
                self._cache.pop(source, None)

        persistent_cache = self._persistent_cache
        if persistent_cache is None:
            return None
        try:
            persisted = persistent_cache.load()
        except (OSError, PersistentAnalysisCacheError) as error:
            record_diagnostic(
                "persistent_analysis_cache_load_failed",
                error_type=type(error).__name__,
            )
            return None
        if persisted is None:
            record_diagnostic("persistent_analysis_cache_miss", reason="absent")
            return None
        if not self._snapshot_matches_source(persisted, source):
            record_diagnostic(
                "persistent_analysis_cache_miss",
                reason="source_version_mismatch",
            )
            return None
        with self._lock:
            self._cache[source] = persisted
        self._last_cache_hit_kind = "persistent"
        record_diagnostic(
            "persistent_analysis_cache_hit",
            layer_count=persisted.layer_count,
            file_size_bytes=persisted.file_size_bytes,
        )
        return persisted

    @staticmethod
    def _snapshot_matches_source(
        snapshot: GCodeAnalysisSnapshot,
        source: Path,
    ) -> bool:
        if not snapshot.matches_file(source):
            return False
        expected_digest = snapshot.content_sha256
        if expected_digest is None:
            return False
        try:
            before = source.stat()
            actual_digest = sha256_file(source)
            after = source.stat()
        except OSError:
            return False
        return (
            before.st_size == after.st_size == snapshot.file_size_bytes
            and before.st_mtime_ns
            == after.st_mtime_ns
            == snapshot.file_modified_ns
            and snapshot.matches_file(source)
            and compare_digest(
                actual_digest,
                str(expected_digest).casefold(),
            )
        )

    def invalidate(self, gcode_path: str | Path | None = None) -> None:
        with self._operation_lock:
            with self._lock:
                if gcode_path is None:
                    self._cache.clear()
                    return
                try:
                    source = Path(gcode_path).expanduser().resolve()
                except OSError:
                    return
                self._cache.pop(source, None)
