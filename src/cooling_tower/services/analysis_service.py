from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from threading import RLock

from cooling_tower.gcode.layer_detector import LayerDetector
from cooling_tower.gcode.metadata_parser import GCodeMetadataCollector
from cooling_tower.gcode.parser import (
    MachineStateTracker,
    MotionTimingPlanner,
    iter_parsed_gcode_lines,
    validate_gcode_path,
)
from cooling_tower.models import GCodeAnalysisSnapshot
from cooling_tower.tower.profile import (
    calculate_seconds_per_deposition_mm,
)


AnalysisProgressCallback = Callable[[int, str], None]
CancellationCallback = Callable[[], bool]


class AnalysisCancelled(RuntimeError):
    """Raised when an obsolete background analysis is cancelled."""


class GCodeChangedDuringAnalysisError(RuntimeError):
    """Raised when a source file changes while it is being parsed."""


class GCodeAnalysisService:
    """Analyze G-code once and reuse snapshots while the file is unchanged."""

    def __init__(self) -> None:
        self._cache: dict[Path, GCodeAnalysisSnapshot] = {}
        self._lock = RLock()

    def analyze(
        self,
        gcode_path: str | Path,
        *,
        progress_callback: AnalysisProgressCallback | None = None,
        cancellation_callback: CancellationCallback | None = None,
        force: bool = False,
    ) -> GCodeAnalysisSnapshot:
        source = validate_gcode_path(gcode_path).resolve()
        before = source.stat()
        notify = progress_callback or (lambda percent, status: None)
        cancelled = cancellation_callback or (lambda: False)

        if not force:
            cached = self.get_cached(source)
            if cached is not None:
                notify(
                    100,
                    "Zwischengespeicherte G-Code-Analyse wird verwendet",
                )
                return cached

        notify(0, "G-Code wird analysiert")
        tracker = MachineStateTracker()
        motion_planner = MotionTimingPlanner()
        detector = LayerDetector()
        metadata_collector = GCodeMetadataCollector(source)

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
        )
        with self._lock:
            self._cache[source] = snapshot
        notify(100, "G-Code-Analyse abgeschlossen")
        return snapshot

    def get_cached(
        self,
        gcode_path: str | Path,
    ) -> GCodeAnalysisSnapshot | None:
        try:
            source = Path(gcode_path).expanduser().resolve(strict=True)
        except (FileNotFoundError, OSError):
            return None
        with self._lock:
            snapshot = self._cache.get(source)
        if snapshot is None:
            return None
        if snapshot.matches_file(source):
            return snapshot
        with self._lock:
            self._cache.pop(source, None)
        return None

    def invalidate(self, gcode_path: str | Path | None = None) -> None:
        with self._lock:
            if gcode_path is None:
                self._cache.clear()
                return
            try:
                source = Path(gcode_path).expanduser().resolve()
            except OSError:
                return
            self._cache.pop(source, None)
