"""Pure ranking and convergence measurements for slicer feedback candidates.

Smaller scores win lexicographically: deficient layers, remaining deficits,
avoidable added time, then material. Joint/isolated precedence stays in the loop.
"""
from __future__ import annotations
import math


def minimum_combined_layer_time(evaluation: object) -> float | None:
    """Read complete-project timing evidence, without applying exclusions."""

    if getattr(evaluation, "metadata_source", None) == "final_combined_gcode":
        minimum = getattr(evaluation, "minimum_sliced_layer_time_s", None)
        if minimum is not None:
            value = float(minimum)
            return value if math.isfinite(value) and value >= 0.0 else None
    values = tuple(
        float(timing.combined_layer_time_s)
        for timing in getattr(evaluation, "layer_timings", ())
        if getattr(timing, "combined_layer_time_s", None) is not None
    )
    if not values or not all(math.isfinite(value) and value >= 0.0 for value in values):
        return None
    return min(values)


def maximum_slicer_result_change(
    previous_added_times_s: dict[int, float] | None,
    current_added_times_s: dict[int, float],
    source_layers: tuple[object, ...],
) -> float | None:
    """Compare consecutive slicer timings for every relevant source layer."""

    if previous_added_times_s is None:
        return None
    expected_indices = tuple(
        int(getattr(layer, "index")) for layer in source_layers
    )
    if any(
        index not in previous_added_times_s
        or index not in current_added_times_s
        for index in expected_indices
    ):
        return math.inf
    changes = []
    for index in expected_indices:
        previous = previous_added_times_s[index]
        current = current_added_times_s[index]
        if not math.isfinite(previous) or not math.isfinite(current):
            return math.inf
        changes.append(abs(current - previous))
    return max(changes, default=0.0)


def maximum_target_deviation(
    source_layers: tuple[object, ...],
    added_times_s: dict[int, float],
    *,
    target_time_s: float,
    combined_times_s: dict[int, float] | None = None,
) -> float:
    """Measure over- and undershoot only where the object needs a tower."""

    deviations = []
    for layer in source_layers:
        index = int(getattr(layer, "index"))
        required_added = max(
            0.0,
            target_time_s - float(getattr(layer, "total_time_s")),
        )
        if required_added <= 0.0:
            continue
        combined = (
            float(combined_times_s[index])
            if combined_times_s and index in combined_times_s
            else float(getattr(layer, "total_time_s"))
            + max(0.0, float(added_times_s.get(index, 0.0)))
        )
        deviations.append(abs(combined - target_time_s))
    return max(deviations, default=0.0)


def minimum_target_difference(
    source_layers: tuple[object, ...],
    added_times_s: dict[int, float],
    *,
    target_time_s: float,
    combined_times_s: dict[int, float] | None = None,
) -> float:
    """Return the signed deviation of the critical minimum layer time."""

    combined_times = [
        (
            float(combined_times_s[int(getattr(layer, "index"))])
            if combined_times_s
            and int(getattr(layer, "index")) in combined_times_s
            else float(getattr(layer, "total_time_s"))
            + max(
                0.0,
                float(
                    added_times_s.get(
                        int(getattr(layer, "index")),
                        0.0,
                    )
                ),
            )
        )
        for layer in source_layers
    ]
    if not combined_times or not all(
        math.isfinite(value) for value in combined_times
    ):
        return math.inf
    return min(combined_times) - target_time_s


def candidate_score(
    convergence: object,
    profile: object,
    *,
    source_layers: tuple[object, ...],
    added_times_s: dict[int, float],
    target_time_s: float,
    combined_times_s: dict[int, float] | None = None,
) -> tuple[int, float, float, float, float, float]:
    """Rank target compliance, tower-time excess, then material."""

    material = sum(
        max(
            0.0,
            float(layer.outer_radius_mm) ** 2,
        )
        for layer in getattr(profile, "layers")
    )
    required_by_index = {
        int(getattr(layer, "index")): max(
            0.0,
            target_time_s - float(getattr(layer, "total_time_s")),
        )
        for layer in source_layers
    }
    avoidable_excesses = tuple(
        max(
            0.0,
            (
                float(combined_times_s[index]) - target_time_s
                if combined_times_s and index in combined_times_s
                else float(added_times_s.get(index, 0.0)) - required_added
            ),
        )
        for index, required_added in required_by_index.items()
    )
    deficient_layer_count = int(
        getattr(convergence, "deficient_layer_count")
    )
    return (
        deficient_layer_count,
        (
            float(getattr(convergence, "maximum_remaining_deficit_s"))
            if deficient_layer_count > 0
            else 0.0
        ),
        float(getattr(convergence, "total_remaining_deficit_s")),
        sum(avoidable_excesses),
        max(avoidable_excesses, default=0.0),
        material,
    )

