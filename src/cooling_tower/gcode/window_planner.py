"""Bounded reverse/forward motion sweeps shared by independent slicer policies."""
from __future__ import annotations

import math
from typing import Callable

from cooling_tower.gcode.parser import (
    MOVEMENT_EPSILON, Movement, _bambu_cruise_feedrate, _bambu_timing_distance,
    _bambu_safe_feedrate, calculate_movement_timing, _copy_planned_movement,
)


def plan_window(
    movements: list[Movement],
    *,
    junction_speed: Callable[[Movement, Movement, float, float, float, float], float],
    safe_speed: Callable[[Movement, float], float] = _bambu_safe_feedrate,
    start_speed: float = 0.,
    previous: Movement | None = None,
    cache: dict | None = None,
) -> list[Movement]:
    """Plan a bounded window using only its caller's junction/safe-speed policy.

    Existing Bambu and generic planners do not use this path. The retained
    prefix exit is the next window's start; only the final block stops at its
    policy-specific safe speed.
    """
    if not movements:
        return []
    values = []
    for i, movement in enumerate(movements):
        identity = id(movement)
        value = cache.get(identity) if cache is not None else None
        if value is None:
            speed = _bambu_cruise_feedrate(movement, movements[i-1] if i else previous)
            value = (
                speed, _bambu_timing_distance(movement),
                movement.acceleration_mm_s2 or 0., safe_speed(movement, speed),
            )
            if cache is not None:
                cache[identity] = value
        values.append(value)
    count = len(movements)
    boundaries, maximum, nominal = [0.] * (count+1), [], []
    for i, (speed, distance, acceleration, safe) in enumerate(values):
        entry = (start_speed or safe) if i == 0 else junction_speed(
            movements[i-1], movements[i], values[i-1][0], speed, values[i-1][3], safe,
        )
        allowable = math.sqrt(max(0., safe*safe + 2*acceleration*distance))
        maximum.append(entry)
        boundaries[i] = min(entry, allowable)
        nominal.append(speed <= allowable)
    boundaries[-1] = values[-1][3]
    # Bounded reverse/forward sweeps are deliberately separate from Bambu's
    # established pass order. The final entry already has its stopping bound.
    for i in range(count-2, -1, -1):
        if boundaries[i] == maximum[i]:
            continue
        if not nominal[i] and maximum[i] > boundaries[i+1]:
            reachable = math.sqrt(max(0., boundaries[i+1]**2 + 2*values[i][2]*values[i][1]))
            boundaries[i] = min(maximum[i], reachable)
        else:
            boundaries[i] = maximum[i]
    for i in range(count-1):
        if not nominal[i] and boundaries[i] < boundaries[i+1]:
            reachable = math.sqrt(max(0., boundaries[i]**2 + 2*values[i][2]*values[i][1]))
            boundaries[i+1] = min(boundaries[i+1], reachable)
    result = []
    for i, movement in enumerate(movements):
        speed, distance, acceleration, _ = values[i]
        timing = calculate_movement_timing(
            has_spatial_motion=(
                movement.endpoint_distance_xyz_mm > MOVEMENT_EPSILON
                or (movement.is_arc and bool(movement.path_length_mm))
            ),
            path_length_mm=distance if movement.is_arc else movement.path_length_mm,
            delta_e=movement.delta_e, feedrate_mm_min=speed*60, speed_factor_percent=100.,
            acceleration_mm_s2=acceleration, entry_speed_mm_s=boundaries[i],
            exit_speed_mm_s=boundaries[i+1], allow_above_cruise_speeds=True,
        )
        result.append(_copy_planned_movement(
            movement, effective_feedrate_mm_min=speed*60,
            timing_distance_mm=distance, duration_s=timing.duration_s, timing_error=timing.error,
            entry_speed_mm_s=timing.entry_speed_mm_s, cruise_speed_mm_s=timing.cruise_speed_mm_s,
            exit_speed_mm_s=timing.exit_speed_mm_s))
    return result
