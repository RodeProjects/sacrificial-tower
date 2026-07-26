from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence


VALUE_EPSILON = 1e-12
SMOOTHSTEP_MAX_DERIVATIVE = 1.875


@dataclass(frozen=True, slots=True)
class EnvelopeResult:
    values: tuple[float, ...]
    unconstrained_values: tuple[float, ...]
    unreachable_positions: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class SplineSample:
    z_mm: float
    outer_radius_mm: float
    wall_thickness_mm: float
    t: float


def quintic_smoothstep(t: float) -> float:
    """C2-continuous monotone interpolation on the inclusive unit interval."""
    clamped = min(1.0, max(0.0, t))
    return (
        6.0 * clamped**5
        - 15.0 * clamped**4
        + 10.0 * clamped**3
    )


def quintic_smoothstep_derivative(t: float) -> float:
    clamped = min(1.0, max(0.0, t))
    return 30.0 * clamped**2 * (clamped - 1.0) ** 2


def angle_to_radial_slope(angle_deg: float) -> float:
    """Convert an angle measured from the vertical axis to dr/dz."""
    if not math.isfinite(angle_deg) or not 0.0 < angle_deg < 90.0:
        raise ValueError(
            "Transition angles must be finite and strictly between 0 and 90 degrees."
        )
    return math.tan(math.radians(angle_deg))


def slope_to_angle_deg(slope: float) -> float:
    if not math.isfinite(slope) or slope < 0.0:
        raise ValueError("A radial slope must be finite and non-negative.")
    return math.degrees(math.atan(slope))


def maximum_quintic_segment_slope(
    start_value: float,
    end_value: float,
    delta_z_mm: float,
) -> float:
    if not math.isfinite(delta_z_mm) or delta_z_mm <= 0.0:
        raise ValueError("Spline segment height must be greater than zero.")
    return (
        SMOOTHSTEP_MAX_DERIVATIVE
        * abs(end_value - start_value)
        / delta_z_mm
    )


def build_asymmetric_spline_envelope(
    z_positions: Sequence[float],
    required_values: Sequence[float],
    *,
    maximum_increase_per_mm_z: float,
    maximum_decrease_per_mm_z: float,
    fixed_start_value: float | None = None,
) -> EnvelopeResult:
    """Build support values whose quintic segments obey asymmetric slopes.

    The backward and forward passes may only enlarge the requested profile.
    If a fixed start boundary makes a later request unreachable, the returned
    profile respects the slope boundary and records the affected positions.
    """
    if len(z_positions) != len(required_values):
        raise ValueError("Z positions and required values must have equal length.")
    if not z_positions:
        raise ValueError("At least one spline support point is required.")
    for label, value in (
        ("maximum increase", maximum_increase_per_mm_z),
        ("maximum decrease", maximum_decrease_per_mm_z),
    ):
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError(f"The {label} must be finite and greater than zero.")

    z_values = tuple(float(value) for value in z_positions)
    requested = tuple(float(value) for value in required_values)
    previous_z: float | None = None
    for z_value, required in zip(z_values, requested, strict=True):
        if not math.isfinite(z_value):
            raise ValueError("Spline Z positions must be finite.")
        if previous_z is not None and z_value <= previous_z + VALUE_EPSILON:
            raise ValueError("Spline Z positions must be strictly increasing.")
        if not math.isfinite(required) or required < 0.0:
            raise ValueError(
                "Required spline values must be finite and non-negative."
            )
        previous_z = z_value

    average_increase = (
        maximum_increase_per_mm_z / SMOOTHSTEP_MAX_DERIVATIVE
    )
    average_decrease = (
        maximum_decrease_per_mm_z / SMOOTHSTEP_MAX_DERIVATIVE
    )
    envelope = list(requested)

    for index in range(len(envelope) - 2, -1, -1):
        delta_z = z_values[index + 1] - z_values[index]
        envelope[index] = max(
            envelope[index],
            envelope[index + 1] - average_increase * delta_z,
        )

    for index in range(1, len(envelope)):
        delta_z = z_values[index] - z_values[index - 1]
        envelope[index] = max(
            envelope[index],
            envelope[index - 1] - average_decrease * delta_z,
        )

    unconstrained = tuple(envelope)
    if fixed_start_value is None:
        return EnvelopeResult(
            values=unconstrained,
            unconstrained_values=unconstrained,
            unreachable_positions=(),
        )
    if not math.isfinite(fixed_start_value) or fixed_start_value < 0.0:
        raise ValueError("The fixed spline start value must be non-negative.")

    actual = list(envelope)
    actual[0] = fixed_start_value
    for index in range(1, len(actual)):
        delta_z = z_values[index] - z_values[index - 1]
        maximum_reachable = (
            actual[index - 1] + average_increase * delta_z
        )
        minimum_reachable = max(
            0.0,
            actual[index - 1] - average_decrease * delta_z,
        )
        actual[index] = min(envelope[index], maximum_reachable)
        actual[index] = max(actual[index], minimum_reachable)

    unreachable = tuple(
        index
        for index, (actual_value, required_value) in enumerate(
            zip(actual, requested, strict=True)
        )
        if actual_value + VALUE_EPSILON < required_value
    )
    return EnvelopeResult(
        values=tuple(actual),
        unconstrained_values=unconstrained,
        unreachable_positions=unreachable,
    )


def adaptive_quintic_segment_samples(
    *,
    start_z_mm: float,
    end_z_mm: float,
    start_outer_radius_mm: float,
    end_outer_radius_mm: float,
    start_wall_thickness_mm: float,
    end_wall_thickness_mm: float,
    maximum_radial_error_mm: float = 0.03,
    maximum_z_step_mm: float = 1.0,
) -> tuple[SplineSample, ...]:
    """Approximate a paired outer/wall spline within a radial error bound.

    The start point is omitted and the end point is included so adjacent
    segments can be concatenated without duplicate rings.
    """
    delta_z = end_z_mm - start_z_mm
    if not math.isfinite(delta_z) or delta_z <= 0.0:
        raise ValueError("Adaptive spline segments need increasing Z values.")
    if maximum_radial_error_mm <= 0.0:
        raise ValueError("Maximum radial spline error must be greater than zero.")
    if maximum_z_step_mm <= 0.0:
        raise ValueError("Maximum spline Z step must be greater than zero.")

    subdivisions = max(1, math.ceil(delta_z / maximum_z_step_mm))
    while True:
        maximum_error = _maximum_piecewise_linear_error(
            subdivisions=subdivisions,
            start_outer=start_outer_radius_mm,
            end_outer=end_outer_radius_mm,
            start_wall=start_wall_thickness_mm,
            end_wall=end_wall_thickness_mm,
        )
        if maximum_error <= maximum_radial_error_mm + VALUE_EPSILON:
            break
        subdivisions *= 2
        if subdivisions > 65536:
            raise RuntimeError("Adaptive spline sampling did not converge.")

    samples: list[SplineSample] = []
    for step in range(1, subdivisions + 1):
        t = step / subdivisions
        factor = quintic_smoothstep(t)
        samples.append(
            SplineSample(
                z_mm=start_z_mm + delta_z * t,
                outer_radius_mm=_interpolate(
                    start_outer_radius_mm,
                    end_outer_radius_mm,
                    factor,
                ),
                wall_thickness_mm=_interpolate(
                    start_wall_thickness_mm,
                    end_wall_thickness_mm,
                    factor,
                ),
                t=t,
            )
        )
    return tuple(samples)


def _maximum_piecewise_linear_error(
    *,
    subdivisions: int,
    start_outer: float,
    end_outer: float,
    start_wall: float,
    end_wall: float,
) -> float:
    maximum_error = 0.0
    for segment in range(subdivisions):
        left_t = segment / subdivisions
        right_t = (segment + 1) / subdivisions
        left_factor = quintic_smoothstep(left_t)
        right_factor = quintic_smoothstep(right_t)
        for fraction in (0.25, 0.5, 0.75):
            t = left_t + (right_t - left_t) * fraction
            true_factor = quintic_smoothstep(t)
            linear_factor = _interpolate(
                left_factor,
                right_factor,
                fraction,
            )
            factor_error = abs(true_factor - linear_factor)
            outer_error = factor_error * abs(end_outer - start_outer)
            wall_error = factor_error * abs(end_wall - start_wall)
            inner_error = factor_error * abs(
                (end_outer - end_wall) - (start_outer - start_wall)
            )
            maximum_error = max(
                maximum_error,
                outer_error,
                wall_error,
                inner_error,
            )
    return maximum_error


def _interpolate(start: float, end: float, factor: float) -> float:
    return start + (end - start) * factor
