"""Largest safe circular tower envelope, shared by the manual preview and slice."""
import heapq
import math
from collections import OrderedDict
from threading import RLock

from cooling_tower.calibration.gcode_integration import _distance_to_polygon_edges, _point_in_polygon
from cooling_tower.models.calibration import TowerPlacement

OBJECT_GAP_MM = 0.3
SEARCH_TOLERANCE_MM = 0.002
_envelopes = OrderedDict()
_cache_lock = RLock()


def _check_cancel(event):
    if event is not None and event.is_set():
        from cooling_tower.preview import PreviewCancelled
        raise PreviewCancelled()


def largest_tower_envelope(bed, occupied, cancellation_event=None):
    _check_cancel(cancellation_event)
    key = (bed,occupied)
    with _cache_lock:
        if key in _envelopes:
            _envelopes.move_to_end(key)
            return _envelopes[key]
    result = _calculate_envelope(bed,occupied,cancellation_event)
    _check_cancel(cancellation_event)
    with _cache_lock:
        _envelopes[key] = result
        _envelopes.move_to_end(key)
        if len(_envelopes)>32:_envelopes.popitem(last=False)
    return result


def _signed_distance(point, polygon):
    distance = _distance_to_polygon_edges(point, polygon)
    return distance if _point_in_polygon(point, polygon) else -distance


def available_radius(bed, occupied, x, y):
    point = (x, y)
    radius = _signed_distance(point, bed.printable_polygon)
    for polygon in bed.excluded_polygons:
        radius = min(radius, -_signed_distance(point, polygon))
    dx = max(occupied.minimum_x_mm-x, 0, x-occupied.maximum_x_mm)
    dy = max(occupied.minimum_y_mm-y, 0, y-occupied.maximum_y_mm)
    if dx or dy:
        separation = math.hypot(dx, dy)
    else:
        separation = -min(x-occupied.minimum_x_mm, occupied.maximum_x_mm-x,
                          y-occupied.minimum_y_mm, occupied.maximum_y_mm-y)
    return min(radius, separation-OBJECT_GAP_MM)


def _calculate_envelope(bed, occupied, cancellation_event):
    """Maximize a 1-Lipschitz distance field within 0.002 mm of its supremum.

    The occupied footprint includes supports. Polygon boundaries and exclusions
    remain hard limits; unlike the automatic placement this also finds corners.
    Returning an evaluated point (never an upper bound) keeps the radius safe.
    """
    bounds = bed.bounds
    width = bounds.maximum_x_mm-bounds.minimum_x_mm
    height = bounds.maximum_y_mm-bounds.minimum_y_mm
    if (occupied.minimum_x_mm <= bounds.minimum_x_mm and occupied.maximum_x_mm >= bounds.maximum_x_mm and
            occupied.minimum_y_mm <= bounds.minimum_y_mm and occupied.maximum_y_mm >= bounds.maximum_y_mm):
        return -OBJECT_GAP_MM,bounds.minimum_x_mm,bounds.minimum_y_mm
    corners = {(x,y) for x in (bounds.minimum_x_mm,bounds.maximum_x_mm)
               for y in (bounds.minimum_y_mm,bounds.maximum_y_mm)}
    if len(bed.printable_polygon) == 4 and set(bed.printable_polygon) == corners and not bed.excluded_polygons:
        # For a rectangle, the farthest point from the occupied rectangle in
        # the radius-inset bed lies at an inset corner (a convex distance).
        # Bisection therefore solves the common case without a spatial search.
        lower,upper = 0., min(width,height)/2
        chosen = (bounds.minimum_x_mm,bounds.minimum_y_mm)
        for _ in range(60):
            radius = (lower+upper)/2
            found = None
            for x in (bounds.minimum_x_mm+radius,bounds.maximum_x_mm-radius):
                for y in (bounds.minimum_y_mm+radius,bounds.maximum_y_mm-radius):
                    dx=max(occupied.minimum_x_mm-x,0,x-occupied.maximum_x_mm)
                    dy=max(occupied.minimum_y_mm-y,0,y-occupied.maximum_y_mm)
                    if math.hypot(dx,dy) >= radius+OBJECT_GAP_MM:
                        found = (x,y)
                        break
                if found is not None:break
            if found is None:upper=radius
            else:lower,chosen=radius,found
        return (lower if lower > 0 else -OBJECT_GAP_MM),*chosen
    best = (-math.inf, 0., 0.)
    queue = []

    def cell(x, y, half_x, half_y):
        nonlocal best
        radius = available_radius(bed, occupied, x, y)
        if radius > best[0]:
            best = (radius, x, y)
        upper = min(radius+math.hypot(half_x, half_y), width/2, height/2,
                    x+half_x-bounds.minimum_x_mm, bounds.maximum_x_mm-x+half_x,
                    y+half_y-bounds.minimum_y_mm, bounds.maximum_y_mm-y+half_y)
        if upper > best[0]+SEARCH_TOLERANCE_MM:
            heapq.heappush(queue, (-upper, x, y, half_x, half_y))

    # Good seeds reduce work without constraining the possible placement.
    for i in range(1, 8):
        for j in range(1, 8):
            cell(bounds.minimum_x_mm+width*i/8, bounds.minimum_y_mm+height*j/8, 0, 0)
    cell((bounds.minimum_x_mm+bounds.maximum_x_mm)/2,
         (bounds.minimum_y_mm+bounds.maximum_y_mm)/2, width/2, height/2)
    iterations = 0
    while queue:
        iterations += 1
        if iterations%256 == 0:_check_cancel(cancellation_event)
        negative_upper, x, y, half_x, half_y = heapq.heappop(queue)
        if -negative_upper <= best[0]+SEARCH_TOLERANCE_MM:
            continue
        if half_x >= half_y:
            half_x /= 2
            cell(x-half_x, y, half_x, half_y)
            cell(x+half_x, y, half_x, half_y)
        else:
            half_y /= 2
            cell(x, y-half_y, half_x, half_y)
            cell(x, y+half_y, half_x, half_y)
    return best


def maximum_foot_diameter(bed, occupied, brim_width_mm):
    radius, _, _ = largest_tower_envelope(bed, occupied)
    # Round down so the displayed/resettable two-decimal value remains valid.
    return max(0., min(1000., math.floor((radius-brim_width_mm)*200)/100))


def manual_placement(bed, occupied, radius_mm, brim_width_mm):
    capacity, x, y = largest_tower_envelope(bed, occupied)
    if radius_mm+brim_width_mm > capacity+1e-9:
        raise ValueError("Turm und Brim passen mit mindestens 0,3 mm Objektabstand nicht auf die freie Druckbettfläche.")
    return TowerPlacement(x, y, radius_mm+brim_width_mm, bed.bounds, OBJECT_GAP_MM)
