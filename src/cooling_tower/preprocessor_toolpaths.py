"""Independent circular tower paths with closed bottom layers and an annular foot."""
from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class TowerPath:
    points: tuple[tuple[float, float], ...]
    width: float
    feature: str
    prime: bool = False


def circle_path(center, radius, width, feature, angle, *, prime=False):
    segments = max(24, min(180, math.ceil(math.tau*radius/.7)))
    x, y = center
    points = tuple((x+radius*math.cos(angle+math.tau*i/segments),
        y+radius*math.sin(angle+math.tau*i/segments)) for i in range(segments))
    return TowerPath(points+(points[0],), width, feature, prime)


def tower_paths(center, outer_radius, shaft_radius, width, inner_width, height, wall_count, *, hollow, first, angle, closed_bottom=False):
    overlap = height*(1-math.pi/4)
    thickness = width+(wall_count-1)*(inner_width-overlap)
    if first or closed_bottom:
        if width > outer_radius:
            raise ValueError("Die Linienbreite ist für die geschlossene Turmbodenschicht zu groß.")
        # Outer wall, inner walls, then a normal-width, closely spaced bottom
        # surface. Its classification must not depend on the previous model.
        radius, current_width = outer_radius-width/2, width
        for i in range(wall_count):
            if radius < current_width/2:
                break
            yield circle_path(center, radius, current_width, "outer" if i == 0 else "inner", angle, prime=i == 0)
            boundary = max(0., radius-current_width/2)
            radius -= (current_width+inner_width)/2-overlap
            current_width = inner_width
            if boundary < width/2:
                break
        # A small overlap bonds the surface ends to the innermost perimeter.
        surface_width = width if first else inner_width
        fill_radius = min(outer_radius-surface_width/2, boundary+min(surface_width*.15, overlap))
        if fill_radius > 1e-8:
            spacing = surface_width-overlap
            rows = max(1, math.ceil(2*fill_radius/spacing))
            step = 2*fill_radius/rows
            c, s = (math.sqrt(.5), math.sqrt(.5)) if first else (-math.sqrt(.5), math.sqrt(.5))
            for row in range(rows):
                v = -fill_radius+(row+.5)*step
                u = math.sqrt(max(0., fill_radius*fill_radius-v*v))
                a, b = ((-u, v), (u, v)) if row % 2 == 0 else ((u, v), (-u, v))
                points = tuple((center[0]+px*c-py*s, center[1]+px*s+py*c) for px, py in (a, b))
                yield TowerPath(points, surface_width, "bottom" if first else "solid")
        return

    # Keep the same vertical cavity under the shaft above the bottom layers.
    # The excess outside the shaft is solid; no disk closes that cavity again.
    hole = max(0., shaft_radius-thickness) if hollow else 0.
    material = outer_radius-hole
    minimum_count = wall_count if hollow else 1
    count = max(minimum_count, round((material-width)/(inner_width-overlap))+1)
    # Spread a residual annular strip among complete beads, avoiding both a
    # thin gap-fill bead and an overextruded duplicate at the inner boundary.
    while count > minimum_count and count > 1 and (material-width)/(count-1)+overlap <= height:
        count -= 1
    adjusted_inner = (material-width)/(count-1)+overlap if count > 1 else 0
    current_width = width if count > 1 else material
    radius = outer_radius-current_width/2
    for i in range(count):
        feature = "outer" if i == 0 else "inner" if i < wall_count else "solid"
        yield circle_path(center, radius, current_width, feature, angle, prime=i == 0)
        radius -= (current_width+adjusted_inner)/2-overlap
        current_width = adjusted_inner
