from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


# Anycubic's postprocessor replaces this comment with its own cumulative
# normal-mode time, to three decimal places. It adds no printer instruction.
INLINE_TIME_PLACEHOLDER = ";_GP_INLINE_ESTIMATED_PRINTING_TIME_PLACEHOLDER"
LAYER_TIME_MARKER = "; COOLING_TOWER_NATIVE_LAYER"
END_TIME_MARKER = "; COOLING_TOWER_NATIVE_END"
_BOUNDARY = re.compile(r"^; COOLING_TOWER_NATIVE_LAYER (\d+) Z ([\d.eE+-]+)$")
_CLOCK = re.compile(
    r"^; estimated printing time \(normal mode\) = .* = ([\d.eE+-]+)$"
)


def anycubic_timing_hooks(values: Mapping[str, object]) -> dict[str, str]:
    """Append timing comments to disposable settings, preserving custom code."""

    before = str(values.get("before_layer_change_gcode") or "")
    end = str(values.get("machine_end_gcode") or "")
    if LAYER_TIME_MARKER not in before:
        before += (
            "\n" + LAYER_TIME_MARKER + " [layer_num] Z [layer_z]\n"
            + INLINE_TIME_PLACEHOLDER
        )
    if END_TIME_MARKER not in end:
        end = END_TIME_MARKER + "\n" + INLINE_TIME_PLACEHOLDER + "\n" + end
    return {"before_layer_change_gcode": before, "machine_end_gcode": end}


@dataclass(frozen=True, slots=True)
class SlicerLayerTimes:
    times_s: tuple[float, ...]
    z_values_mm: tuple[float, ...]


def read_slicer_layer_times(source: Path) -> SlicerLayerTimes | None:
    """Read complete native clocks; never interpolate incomplete evidence.

    Boundary n is immediately before layer n+1. Its clock closes layer n.
    At boundary zero Anycubic may leave the placeholder unchanged when there
    have been no movements yet; the clock then starts at zero. The final
    marker closes the last printed layer before machine shutdown commands.
    """

    boundaries: list[tuple[int, float, float | None]] = []
    pending: tuple[int, float] | None = None
    end_seen = False
    end_clock: float | None = None
    with source.open(encoding="utf-8-sig", errors="replace") as stream:
        for raw in stream:
            if not raw.startswith(";"):
                continue
            line = raw.strip()
            if line.startswith("; --- COOLING_TOWER_BEGIN"):
                # Inserting new movements invalidates clocks of either input.
                return None
            match = _BOUNDARY.fullmatch(line)
            if match:
                if pending is not None:
                    boundaries.append((*pending, None))
                pending = (int(match[1]), float(match[2]))
                if end_seen:
                    raise ValueError("Die nativen Slicer-Layerzeiten sind nicht eindeutig.")
            elif line == END_TIME_MARKER:
                if pending is not None:
                    boundaries.append((*pending, None))
                    pending = None
                if end_seen:
                    raise ValueError("Die nativen Slicer-Layerzeiten sind nicht eindeutig.")
                end_seen = True
            elif pending is not None or (end_seen and end_clock is None):
                match = _CLOCK.fullmatch(line)
                if match:
                    value = float(match[1])
                    if not math.isfinite(value) or value < 0:
                        raise ValueError("Der Slicer hat ungültige native Layerzeiten ausgegeben.")
                    if pending is not None:
                        boundaries.append((*pending, value))
                        pending = None
                    else:
                        end_clock = value
    if not boundaries and pending is None and not end_seen:
        return None
    if (
        pending is not None or not end_seen or end_clock is None or not boundaries
        or [item[0] for item in boundaries] != list(range(len(boundaries)))
        or any(item[2] is None for item in boundaries[1:])
    ):
        raise ValueError("Der Slicer hat keine vollständigen nativen Layerzeiten ausgegeben.")
    clocks = [boundaries[0][2] or 0.0]
    clocks.extend(float(item[2]) for item in boundaries[1:] if item[2] is not None)
    clocks.append(end_clock)
    times = tuple(after - before for before, after in zip(clocks, clocks[1:]))
    heights = tuple(item[1] for item in boundaries)
    if (
        any(not math.isfinite(value) or value <= 0 for value in times)
        or any(not math.isfinite(z) for z in heights)
        or any(after <= before for before, after in zip(heights, heights[1:]))
    ):
        raise ValueError("Die nativen Slicer-Layerzeiten passen nicht zu den Drucklayern.")
    return SlicerLayerTimes(times, heights)
