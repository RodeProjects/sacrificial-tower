"""Supported circular/capsule paths, closed floors and a concave annular foot."""
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


def contour_path(center, radius, width, feature, angle, *, prime=False, spine_half=0.):
    """A capsule's parallel offsets change its end radius, not its spine.

    `radius` is the bounding radius along the broad side. Constant spine
    length keeps both flat faces and the rounded ends one bead apart.
    """
    if spine_half <= 1e-9:
        return circle_path(center, radius, width, feature, angle, prime=prime)
    minor = radius-spine_half
    if minor <= 0:
        raise ValueError("Für die abgerundete Turmkontur fehlt Platz zwischen den Wandlinien.")
    count = max(12, min(90, math.ceil(math.pi*minor/.5)))
    count += count % 2  # Include the exact broad-side extrema.
    local = [(-minor, 0.), (-minor, -spine_half)]
    local += [(minor*math.cos(math.pi+math.pi*i/count),
        -spine_half+minor*math.sin(math.pi+math.pi*i/count)) for i in range(1, count+1)]
    local.append((minor, spine_half))
    local += [(minor*math.cos(math.pi*i/count),
        spine_half+minor*math.sin(math.pi*i/count)) for i in range(1, count+1)]
    local.append(local[0])
    # angle names the model-facing start, as for the circular path API.
    c, s = math.cos(angle-math.pi), math.sin(angle-math.pi)
    points = tuple((center[0]+u*c-v*s, center[1]+u*s+v*c) for u, v in local)
    return TowerPath(points, width, feature, prime)


def _capsule_surface(center, radius, spine, width, height, angle, first):
    minor = radius-spine
    if minor <= 0:
        return
    spacing = width-height*(1-math.pi/4)
    extent = radius if first else minor
    rows = max(1, math.ceil(2*extent/spacing))
    step = 2*extent/rows
    c, s = math.cos(angle-math.pi), math.sin(angle-math.pi)
    for row in range(rows):
        offset = -extent+(row+.5)*step
        if first:
            reach = minor if abs(offset) <= spine else math.sqrt(max(0., minor*minor-(abs(offset)-spine)**2))
            a, b = (-reach, offset), (reach, offset)
        else:
            reach = spine+math.sqrt(max(0., minor*minor-offset*offset))
            a, b = (offset, -reach), (offset, reach)
        if row % 2:
            a, b = b, a
        yield TowerPath(tuple((center[0]+u*c-v*s, center[1]+u*s+v*c) for u, v in (a, b)),
            width, "bottom" if first else "solid")


def tower_paths(center, outer_radius, shaft_radius, width, inner_width, height, wall_count, *, hollow, first, angle, closed_bottom=False, spine_half=0.):
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
            yield contour_path(center, radius, current_width, "outer" if i == 0 else "inner", angle, prime=i == 0, spine_half=spine_half)
            boundary = max(0., radius-current_width/2)
            radius -= (current_width+inner_width)/2-overlap
            current_width = inner_width
            if boundary < width/2:
                break
        # A small overlap bonds the surface ends to the innermost perimeter.
        surface_width = width if first else inner_width
        fill_radius = min(outer_radius-surface_width/2, boundary+min(surface_width*.15, overlap))
        if fill_radius > 1e-8:
            if spine_half > 1e-9:
                yield from _capsule_surface(center, fill_radius, spine_half, surface_width, height, angle, first)
                return
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

    # The caller supplies the supported cavity for this height, including the
    # tapered foot. No disk closes that cavity above the bottom layers.
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
        yield contour_path(center, radius, current_width, feature, angle, prime=i == 0, spine_half=spine_half)
        radius -= (current_width+adjusted_inner)/2-overlap
        current_width = adjusted_inner
