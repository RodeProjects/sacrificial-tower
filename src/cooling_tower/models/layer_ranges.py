"""Object-bound, inclusive ranges of one-based printable layer positions."""
from __future__ import annotations

from collections.abc import Iterable, Sequence

LayerRange = tuple[int, int]


def normalize_layer_ranges(
    ranges: Iterable[Sequence[int]], *, layer_count: int | None = None,
) -> tuple[LayerRange, ...]:
    """Validate, sort and union overlapping or immediately adjacent ranges."""
    ordered: list[LayerRange] = []
    for item in ranges:
        if len(item) != 2 or any(type(value) is not int for value in item):
            raise ValueError("Layer ranges require two integer layer numbers.")
        start, end = item
        if start < 1 or end < start:
            raise ValueError("Layer ranges must be ordered and start at layer 1 or higher.")
        if layer_count is not None and end > layer_count:
            raise ValueError("Layer range exceeds the original object's layer count.")
        ordered.append((start, end))
    merged: list[LayerRange] = []
    for start, end in sorted(ordered):
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return tuple(merged)


def excluded_layer_indices(
    layers: Sequence[object], ranges: tuple[LayerRange, ...],
) -> frozenset[int]:
    """Translate displayed positions to original G-code indices, without renumbering."""
    normalized = normalize_layer_ranges(ranges, layer_count=len(layers))
    return frozenset(
        int(getattr(layers[position - 1], "index"))
        for start, end in normalized for position in range(start, end + 1)
    )
