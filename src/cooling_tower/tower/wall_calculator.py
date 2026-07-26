from __future__ import annotations

import math
from dataclasses import dataclass


EPSILON = 1e-9


@dataclass(frozen=True, slots=True)
class WallPathBounds:
    minimum_path_count: int
    maximum_path_count: int
    effective_minimum_thickness_mm: float
    effective_maximum_thickness_mm: float


def calculate_wall_path_length(
    outer_radius: float,
    path_count: int,
    path_width: float,
) -> float:
    """Estimate the sum of all concentric wall centerline lengths."""
    if outer_radius <= 0.0 or path_count <= 0 or path_width <= 0.0:
        return 0.0
    total = 0.0
    for path_index in range(path_count):
        path_radius = outer_radius - (path_index + 0.5) * path_width
        if path_radius <= 0.0:
            break
        total += math.tau * path_radius
    return total


def calculate_wall_path_bounds(
    minimum_thickness_mm: float,
    maximum_thickness_mm: float,
    path_width_mm: float,
) -> WallPathBounds:
    if not all(
        math.isfinite(value)
        for value in (
            minimum_thickness_mm,
            maximum_thickness_mm,
            path_width_mm,
        )
    ):
        raise ValueError("Wall dimensions must be finite.")
    if path_width_mm <= 0.0:
        raise ValueError("Wall path width must be greater than zero.")
    if minimum_thickness_mm <= 0.0:
        raise ValueError("Minimum wall thickness must be greater than zero.")
    if maximum_thickness_mm < minimum_thickness_mm:
        raise ValueError(
            "Maximum wall thickness must be greater than or equal to "
            "minimum wall thickness."
        )

    minimum_paths = max(1, math.ceil(minimum_thickness_mm / path_width_mm))
    maximum_paths = math.floor(
        (maximum_thickness_mm + EPSILON) / path_width_mm
    )
    if maximum_paths < minimum_paths:
        raise ValueError(
            "The configured maximum wall thickness cannot contain the "
            "quantized minimum number of wall paths."
        )
    return WallPathBounds(
        minimum_path_count=minimum_paths,
        maximum_path_count=maximum_paths,
        effective_minimum_thickness_mm=minimum_paths * path_width_mm,
        effective_maximum_thickness_mm=maximum_paths * path_width_mm,
    )


def calculate_required_outer_radius(
    required_path_mm: float,
    path_count: int,
    path_width_mm: float,
) -> float:
    """Solve the concentric path-length equation for the outer radius."""
    if required_path_mm <= 0.0:
        return 0.0
    if path_count <= 0 or path_width_mm <= 0.0:
        raise ValueError("Path count and width must be greater than zero.")
    return (
        required_path_mm / (math.tau * path_count)
        + path_width_mm * path_count / 2.0
    )


def maximum_paths_for_inner_radius(
    outer_radius_mm: float,
    minimum_inner_radius_mm: float,
    path_width_mm: float,
) -> int:
    return max(
        0,
        math.floor(
            (
                outer_radius_mm
                - minimum_inner_radius_mm
                + EPSILON
            )
            / path_width_mm
        ),
    )


def minimum_paths_for_required_length(
    outer_radius_mm: float,
    required_path_mm: float,
    minimum_paths: int,
    maximum_paths: int,
    path_width_mm: float,
) -> tuple[int, bool]:
    """Return the smallest allowed path count and whether it meets demand."""
    for path_count in range(minimum_paths, maximum_paths + 1):
        if (
            calculate_wall_path_length(
                outer_radius_mm, path_count, path_width_mm
            )
            + EPSILON
            >= required_path_mm
        ):
            return path_count, True
    return maximum_paths, (
        calculate_wall_path_length(
            outer_radius_mm, maximum_paths, path_width_mm
        )
        + EPSILON
        >= required_path_mm
    )
