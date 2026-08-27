from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import Callable

from cooling_tower.gcode.parser import (
    MachineStateTracker,
    Movement,
    iter_parsed_gcode_lines,
)
from cooling_tower.models import OccupiedBounds
from cooling_tower.preview.models import LineSegment3D, Point3D


ProgressCallback = Callable[[int, str], None]


class PreviewCancelled(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DepositionToolpathAnalysis:
    """One-pass preview sampling plus exact deposition XY bounds."""

    object_segments: tuple[LineSegment3D, ...]
    source_segment_count: int
    occupied_bounds: OccupiedBounds | None


@dataclass(slots=True)
class _LayerSample:
    limit: int
    seen: int = 0
    samples: list[LineSegment3D] = field(default_factory=list)
    extremes: dict[str, LineSegment3D] = field(default_factory=dict)
    extreme_values: dict[str, float] = field(default_factory=dict)

    def add(self, segment: LineSegment3D, line_number: int) -> None:
        self.seen += 1
        coordinates = {
            "min_x": min(segment.start.x, segment.end.x),
            "max_x": max(segment.start.x, segment.end.x),
            "min_y": min(segment.start.y, segment.end.y),
            "max_y": max(segment.start.y, segment.end.y),
        }
        for key, value in coordinates.items():
            previous = self.extreme_values.get(key)
            if previous is None or (
                key.startswith("min") and value < previous
            ) or (key.startswith("max") and value > previous):
                self.extreme_values[key] = value
                self.extremes[key] = segment

        if len(self.samples) < self.limit:
            self.samples.append(segment)
            return
        # Deterministic reservoir sampling keeps coverage over an entire layer
        # without retaining every extrusion move from a large source file.
        slot = (line_number * 2_654_435_761) % self.seen
        if slot < self.limit:
            self.samples[slot] = segment

    def values(self) -> tuple[LineSegment3D, ...]:
        result: list[LineSegment3D] = []
        seen: set[LineSegment3D] = set()
        for segment in (*self.extremes.values(), *self.samples):
            if segment not in seen:
                seen.add(segment)
                result.append(segment)
        return tuple(result)


def _collinear(first: LineSegment3D, second: LineSegment3D) -> bool:
    if math.dist(
        (first.end.x, first.end.y, first.end.z),
        (second.start.x, second.start.y, second.start.z),
    ) > 1e-5:
        return False
    first_vector = (
        first.end.x - first.start.x,
        first.end.y - first.start.y,
        first.end.z - first.start.z,
    )
    second_vector = (
        second.end.x - second.start.x,
        second.end.y - second.start.y,
        second.end.z - second.start.z,
    )
    first_length = math.sqrt(sum(value * value for value in first_vector))
    second_length = math.sqrt(sum(value * value for value in second_vector))
    if first_length <= 1e-9 or second_length <= 1e-9:
        return False
    dot = sum(
        left * right for left, right in zip(first_vector, second_vector)
    ) / (first_length * second_length)
    return dot >= 0.99995


def analyze_deposition_toolpaths(
    gcode_path: str | Path,
    *,
    expected_layer_count: int,
    maximum_segments: int = 60_000,
    cancellation_event: Event | None = None,
    progress_callback: ProgressCallback | None = None,
) -> DepositionToolpathAnalysis:
    """Collect preview paths and exact occupied bounds in one parser pass."""

    if maximum_segments < 100:
        raise ValueError("maximum_segments must be at least 100")
    notify = progress_callback or (lambda _percent, _status: None)
    notify(-1, "Objekt-Werkzeugpfade werden vereinfacht …")
    per_layer_limit = max(
        8,
        min(256, maximum_segments // max(1, expected_layer_count)),
    )
    layers: dict[float, _LayerSample] = defaultdict(
        lambda: _LayerSample(per_layer_limit)
    )
    tracker = MachineStateTracker()
    total = 0
    pending: LineSegment3D | None = None
    pending_layer: float | None = None
    pending_line = 0
    minimum_x = math.inf
    maximum_x = -math.inf
    minimum_y = math.inf
    maximum_y = -math.inf

    def flush_pending() -> None:
        nonlocal pending, pending_layer
        if pending is not None and pending_layer is not None:
            layers[pending_layer].add(pending, pending_line)
        pending = None
        pending_layer = None

    for parsed in iter_parsed_gcode_lines(gcode_path):
        if parsed.number % 2_000 == 0 and (
            cancellation_event is not None and cancellation_event.is_set()
        ):
            raise PreviewCancelled()
        event = tracker.process_line(parsed)
        if not isinstance(event, Movement) or event.category != "deposition":
            continue
        minimum_x = min(minimum_x, event.start_x, event.end_x)
        maximum_x = max(maximum_x, event.start_x, event.end_x)
        minimum_y = min(minimum_y, event.start_y, event.end_y)
        maximum_y = max(maximum_y, event.start_y, event.end_y)
        coordinates = (
            event.start_x,
            event.start_y,
            event.start_z,
            event.end_x,
            event.end_y,
            event.end_z,
        )
        if not all(math.isfinite(value) for value in coordinates):
            continue
        total += 1
        segment = LineSegment3D(
            Point3D(event.start_x, event.start_y, event.start_z),
            Point3D(event.end_x, event.end_y, event.end_z),
        )
        layer_key = round(event.end_z, 4)
        if pending is not None and pending_layer == layer_key and _collinear(
            pending, segment
        ):
            pending = LineSegment3D(pending.start, segment.end)
        else:
            flush_pending()
            pending = segment
            pending_layer = layer_key
            pending_line = parsed.number
    flush_pending()
    if cancellation_event is not None and cancellation_event.is_set():
        raise PreviewCancelled()

    values = [
        segment
        for layer_key in sorted(layers)
        for segment in layers[layer_key].values()
    ]
    if len(values) > maximum_segments:
        step = len(values) / maximum_segments
        values = [values[int(index * step)] for index in range(maximum_segments)]
    occupied_bounds = (
        OccupiedBounds(minimum_x, maximum_x, minimum_y, maximum_y)
        if all(
            math.isfinite(value)
            for value in (minimum_x, maximum_x, minimum_y, maximum_y)
        )
        else None
    )
    return DepositionToolpathAnalysis(
        object_segments=tuple(values),
        source_segment_count=total,
        occupied_bounds=occupied_bounds,
    )


def extract_deposition_toolpaths(
    gcode_path: str | Path,
    *,
    expected_layer_count: int,
    maximum_segments: int = 60_000,
    cancellation_event: Event | None = None,
    progress_callback: ProgressCallback | None = None,
) -> tuple[tuple[LineSegment3D, ...], int]:
    """Return the backward-compatible preview-only result."""

    analysis = analyze_deposition_toolpaths(
        gcode_path,
        expected_layer_count=expected_layer_count,
        maximum_segments=maximum_segments,
        cancellation_event=cancellation_event,
        progress_callback=progress_callback,
    )
    return analysis.object_segments, analysis.source_segment_count
