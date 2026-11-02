"""Actual XY extents of native deposition, including arc extrema."""
from __future__ import annotations

import math

from cooling_tower.gcode.parser import Movement


def movement_bounds(move: Movement) -> tuple[float, float, float, float]:
    start = (move.start_x, move.start_y, move.start_z)
    end = (move.end_x, move.end_y, move.end_z)
    bounds = [min(start[0], end[0]), max(start[0], end[0]),
              min(start[1], end[1]), max(start[1], end[1])]
    if not move.is_arc:
        return tuple(bounds)
    axes = {'XY': (0, 1), 'XZ': (2, 0), 'YZ': (1, 2)}.get(move.arc_plane)
    radius = move.arc_start_radius_mm or move.arc_radius_mm
    direction = move.entry_direction_xyz
    if axes is None or radius is None or direction is None or move.arc_sweep_degrees is None:
        raise ValueError('Eine native Extrusionskurve besitzt keine prüfbare räumliche Ausdehnung.')
    u, v = axes
    length = math.hypot(direction[u], direction[v])
    if not length > 0 or not radius > 0:
        raise ValueError('Eine native Extrusionskurve ist geometrisch ungültig.')
    clockwise = move.command == 'G2'
    sign = 1 if clockwise else -1
    center = (start[u] + sign * direction[v] / length * radius,
              start[v] - sign * direction[u] / length * radius)
    angle = math.atan2(start[v] - center[1], start[u] - center[0])
    extent_radius = max(radius, move.arc_radius_mm or radius)
    sweep = math.radians(move.arc_sweep_degrees)
    for quadrant in range(4):
        cardinal = quadrant * math.pi / 2
        travelled = ((angle - cardinal) if clockwise else (cardinal - angle)) % math.tau
        if travelled > sweep + 1e-7:
            continue
        for axis, value in ((u, center[0] + extent_radius * math.cos(cardinal)),
                            (v, center[1] + extent_radius * math.sin(cardinal))):
            if axis < 2:
                bounds[axis * 2] = min(bounds[axis * 2], value)
                bounds[axis * 2 + 1] = max(bounds[axis * 2 + 1], value)
    return tuple(bounds)
