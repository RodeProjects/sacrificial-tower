"""Linear widening, inward-curved tapering and supported solid shoulders.

All radii are requirements at layer tops. A backward linear envelope reserves
enough radius for every later peak before a shoulder is considered. A shoulder
is a horizontal annulus at the preceding layer top, never a disconnected mesh.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


EPSILON = 1e-9


@dataclass(frozen=True, slots=True)
class Taper:
    start_z: float
    start_radius: float
    minimum_radius: float
    duration: float

    def radius(self, z: float) -> float:
        t = min(1.0, max(0.0, (z - self.start_z) / self.duration))
        return self.minimum_radius + (
            self.start_radius - self.minimum_radius
        ) * (1.0 - t) ** 2


@dataclass(frozen=True, slots=True)
class DiameterSegment:
    start_z: float
    end_z: float
    start_radius: float
    end_radius: float
    step_radius: float | None = None
    taper: Taper | None = None
    rising_floor_start: float | None = None

    def radius(self, t: float) -> float:
        start = self.start_radius if self.step_radius is None else self.step_radius
        if self.taper is None:
            return start + (self.end_radius - start) * t
        z = self.start_z + (self.end_z - self.start_z) * t
        value = self.taper.radius(z)
        if self.rising_floor_start is not None:
            value = max(value, self.rising_floor_start + (
                self.end_radius - self.rising_floor_start
            ) * t)
        return value

    def samples(self, *, radial_error: float, maximum_z_step: float):
        """Chord-error bound, also across a taper/linear intersection."""
        def split(left: float, right: float):
            r0, r1 = self.radius(left), self.radius(right)
            # Each interval is convex (quadratic taper, possibly the maximum
            # with a rising line). Twice its midpoint chord error bounds the
            # error everywhere, including an off-centre intersection.
            error = 2.0 * max(abs(self.radius(left + (right - left) * f)
                            - (r0 + (r1 - r0) * f))
                        for f in (0.25, 0.5, 0.75))
            if (error > radial_error or
                    (right - left) * (self.end_z - self.start_z) > maximum_z_step):
                middle = (left + right) / 2.0
                yield from split(left, middle)
                yield from split(middle, right)
            else:
                yield (self.start_z + (self.end_z - self.start_z) * right, r1)
        yield from split(0.0, 1.0)


def plan_diameter_transitions(
    z: tuple[float, ...],
    required: tuple[float, ...],
    *,
    base_index: int,
    base_radius: float,
    minimum_radius: float,
    expansion_slope: float,
    contraction_slope: float,
    allow_steps: bool,
    base_taper_height: float | None = None,
    abrupt_drop_indices: frozenset[int] = frozenset(),
) -> tuple[tuple[float, ...], tuple[int, ...], tuple[DiameterSegment, ...]]:
    """Reserve future expansion, then form tapers above the demand envelope.

    A taper is one quadratic curve across a descending run, including flat
    requirements. Its duration is enlarged until all those requirements and
    the maximum contraction angle fit. It is not restarted at each layer.
    """
    demand = list(required)
    for i in range(len(z) - 2, base_index - 1, -1):
        demand[i] = max(demand[i], demand[i + 1] - expansion_slope * (z[i + 1] - z[i]))
    # A manually or automatically fixed foot remains the boundary. Keep
    # unreachable requests visible in the returned diagnostic indices.
    for i in range(base_index, len(z)):
        demand[i] = min(demand[i], base_radius + expansion_slope * (z[i] - z[base_index]))

    radii = [base_radius]
    segments: list[DiameterSegment] = []
    taper: Taper | None = None
    base_taper = None
    if base_taper_height is not None and base_taper_height > EPSILON:
        if not allow_steps:
            base_taper_height = max(base_taper_height, 2.0 * (base_radius - minimum_radius) / contraction_slope)
        end_z = z[base_index] + base_taper_height
        target_radius = minimum_radius
        for j in range(base_index + 1, len(z)):
            t = min(1.0, (z[j] - z[base_index]) / base_taper_height)
            if t > 0:
                weight = (1.0 - t) ** 2
                target_radius = max(target_radius, (demand[j] - base_radius * weight) / (1.0 - weight))
            if z[j] >= end_z:
                break
        if target_radius < base_radius - EPSILON:
            base_taper = Taper(z[base_index], base_radius, target_radius, base_taper_height)
    for i in range(1, len(z)):
        previous = radii[-1]
        dz = z[i] - z[i - 1]
        step = None
        floor_start = None
        if i <= base_index:
            value = base_radius
            taper = None
        elif base_taper is not None and z[i - 1] < base_taper.start_z + base_taper.duration - EPSILON:
            taper = base_taper
            value = max(demand[i], taper.radius(z[i]))
            if demand[i] > taper.radius(z[i]) + EPSILON:
                floor_start = demand[i - 1]
        else:
            if taper is base_taper:
                taper = None
            # Only the caller can certify that the next source layer has
            # enough time of its own. A steep fall in the estimated radius
            # is not evidence of that and must not create a shoulder.
            abrupt_drop = allow_steps and i in abrupt_drop_indices
            if abrupt_drop:
                # A later peak can require more than this layer's own demand.
                # Start the new trunk as thin as possible while retaining the
                # full configured linear expansion distance above the shoulder.
                candidate = max(
                    minimum_radius, required[i], demand[i] - expansion_slope * dz,
                )
                if candidate < previous - EPSILON:
                    step = candidate
                    taper = None
            if step is not None:
                value = max(step, demand[i])
            elif demand[i] >= previous - EPSILON:
                value = max(previous, demand[i])
                taper = None
            else:
                if taper is None:
                    amplitude = previous - minimum_radius
                    # Even with full infill, a layer that still needs the
                    # tower must taper continuously instead of collapsing
                    # almost vertically after a steep demand change.
                    duration = 2.0 * amplitude / contraction_slope
                    # Find the duration needed to stay above this descending
                    # run. A subsequent rise is handled by the linear floor.
                    j = i
                    while j < len(z):
                        if j > i and demand[j] > demand[j - 1] + EPSILON:
                            break
                        fraction = max(0.0, (demand[j] - minimum_radius) / amplitude)
                        denominator = 1.0 - math.sqrt(min(1.0, fraction))
                        if denominator > EPSILON:
                            duration = max(duration, (z[j] - z[i - 1]) / denominator)
                        j += 1
                    taper = Taper(z[i - 1], previous, minimum_radius, max(duration, EPSILON))
                value = max(demand[i], taper.radius(z[i]))
                if demand[i] > taper.radius(z[i]) + EPSILON:
                    # The next widening starts where its straight line meets
                    # the still-active concave taper, including between layers.
                    floor_start = demand[i - 1]
            value = min(value, previous + expansion_slope * dz)
        segment = DiameterSegment(
            z[i - 1], z[i], previous, value, step, taper, floor_start,
        )
        segments.append(segment)
        radii.append(value)
        if floor_start is not None:
            taper = None

    unreachable = tuple(i for i, (actual, wanted) in enumerate(zip(radii, required))
                        if actual + EPSILON < wanted)
    return tuple(radii), unreachable, tuple(segments)
