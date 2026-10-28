"""Model silhouettes used only to prefer cleaner, non-crossing travel routes.

Placement and collision decisions continue to use the complete motion index.
These conservative projected islands are a route preference, never a safety
substitute or a reason to reject otherwise valid lifted travel. Required tower
outlines remain obstacles even when an optional model detour is unavailable.
"""
import math

from cooling_tower.calibration.gcode_integration import _point_in_polygon
from cooling_tower.postprocessor_travel import safe_travel_path, segments_cross
from cooling_tower.preview.toolpath import PreviewCancelled


def _hull(points):
    points = sorted(set(points))
    def cross(a, b, c):
        return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    halves = []
    for ordered in (points, reversed(points)):
        half = []
        for point in ordered:
            while len(half) >= 2 and cross(half[-2], half[-1], point) <= 0:
                half.pop()
            half.append(point)
        halves.append(half[:-1])
    return tuple(halves[0]+halves[1])


def model_travel_islands(index, bounds, line_margin, *, cancellation_event=None):
    """Rasterize unshortened deposition paths, then enclose connected islands."""
    step = max(1.5, max(bounds.maximum_x_mm-bounds.minimum_x_mm,
        bounds.maximum_y_mm-bounds.minimum_y_mm)/80)
    cells = set()
    xs = range(math.floor(bounds.minimum_x_mm/step)-1, math.ceil(bounds.maximum_x_mm/step)+1)
    ys = range(math.floor(bounds.minimum_y_mm/step)-1, math.ceil(bounds.maximum_y_mm/step)+1)
    margin = step/math.sqrt(2)+line_margin
    for x in xs:
        if cancellation_event is not None and cancellation_event.is_set():
            raise PreviewCancelled()
        for y in ys:
            if not index.model_clear(((x+.5)*step, (y+.5)*step), margin, lambda _z: margin):
                cells.add((x, y))
    polygons = []
    while cells:
        pending, corners = [cells.pop()], []
        while pending:
            x, y = pending.pop()
            corners.extend(((x*step, y*step), ((x+1)*step, y*step),
                ((x+1)*step, (y+1)*step), (x*step, (y+1)*step)))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    neighbour = x+dx, y+dy
                    if neighbour in cells:
                        cells.remove(neighbour)
                        pending.append(neighbour)
        polygons.append(_hull(corners))
    return tuple(sorted(polygons))


def model_crossings(start, end, polygons):
    return sum(_point_in_polygon(start, polygon) or _point_in_polygon(end, polygon)
        or any(segments_cross(start, end, p, polygon[i-1]) for i, p in enumerate(polygon)) for polygon in polygons)


def prefer_model_avoiding_route(start, end, geometry, polygons, *, margin_mm, direct=None, required_polygons=()):
    if direct is None:
        direct = safe_travel_path(start, end, geometry, margin_mm=margin_mm, soft_polygons=required_polygons)
    # Entering/leaving the source/destination island is unavoidable. Other
    # projected islands, and all islands on the parking-to-tower leg, are avoided.
    obstacles = tuple(polygon for polygon in polygons if not _point_in_polygon(start, polygon)
        and not _point_in_polygon(end, polygon))
    if not obstacles or not model_crossings(start, end, obstacles):
        return direct
    try:
        preferred = safe_travel_path(start, end, geometry, margin_mm=margin_mm, soft_polygons=required_polygons+obstacles)
    except ValueError:
        return direct
    length = lambda route: sum(math.dist(a, b) for a, b in zip(route, route[1:]))
    return preferred if length(preferred) <= max(length(direct)*2.5, length(direct)+30) else direct
