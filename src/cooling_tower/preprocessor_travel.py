"""Collision checks and XY routes for lifted postprocessor travel moves."""
from __future__ import annotations

import heapq
import math

from cooling_tower.calibration.gcode_integration import (
    _point_in_polygon, _point_segment_distance, _distance_to_polygon_edges,
)
from cooling_tower.gcode.parser import MachineStateTracker, Movement, iter_parsed_gcode_lines
from cooling_tower.preview.toolpath import PreviewCancelled
from cooling_tower.preprocessor_placement import motion_envelopes


def safe_travel_path(start, end, geometry, *, margin_mm=1.0, soft_polygons=()):
    """Shortest visibility route, keeping clear of profile exclusion polygons.

    All these XY moves are executed at a height above every printed layer.
    Exclusions are still treated as obstacles, regardless of their height.
    """
    obstacles = tuple((polygon, margin_mm) for polygon in geometry.excluded_polygons) + tuple((polygon, .5) for polygon in soft_polygons)
    def point_safe(point):
        return (_point_in_polygon(point, geometry.printable_polygon)
            and all(not _point_in_polygon(point, polygon)
                and _distance_to_polygon_edges(point, polygon) >= margin - 1e-6
                for polygon, margin in obstacles))

    def visible(a, b):
        # Segments cannot cross a thin exclusion between sampled points.
        for polygon, margin in obstacles:
            for i, p in enumerate(polygon):
                q = polygon[i - 1]
                if segments_cross(a, b, p, q):
                    return False
                if min(_point_segment_distance(a, p, q), _point_segment_distance(b, p, q),
                        _point_segment_distance(p, a, b), _point_segment_distance(q, a, b)) < margin - 1e-6:
                    return False
        for i, p in enumerate(geometry.printable_polygon):
            if segments_cross(a, b, p, geometry.printable_polygon[i - 1]):
                return False
        return point_safe(a) and point_safe(b) and point_safe(((a[0]+b[0])/2, (a[1]+b[1])/2))

    if visible(start, end):
        return (start, end)
    nodes = [start, end]
    # Expanded rectangular envelopes are deliberately conservative for any
    # non-rectangular exclusion. Original bed vertices also support concave beds.
    for polygon, margin in obstacles:
        xs, ys = zip(*polygon)
        gap = margin + 0.1
        nodes.extend((x, y) for x in (min(xs)-gap, max(xs)+gap) for y in (min(ys)-gap, max(ys)+gap)
            if point_safe((x, y)))
    cx = sum(x for x, _ in geometry.printable_polygon) / len(geometry.printable_polygon)
    cy = sum(y for _, y in geometry.printable_polygon) / len(geometry.printable_polygon)
    for x, y in geometry.printable_polygon:
        dx, dy = cx-x, cy-y
        length = math.hypot(dx, dy)
        if length:
            point = (x+dx/length*(margin_mm+.1), y+dy/length*(margin_mm+.1))
            if point_safe(point):
                nodes.append(point)
    distances = {0: 0.0}
    previous = {}
    queue = [(0.0, 0)]
    while queue:
        distance, index = heapq.heappop(queue)
        if distance > distances[index]:
            continue
        if index == 1:
            route = [1]
            while route[-1] != 0:
                route.append(previous[route[-1]])
            return tuple(nodes[i] for i in reversed(route))
        for other in range(len(nodes)):
            candidate = distance + math.dist(nodes[index], nodes[other])
            if candidate < distances.get(other, math.inf) and visible(nodes[index], nodes[other]):
                distances[other] = candidate
                previous[other] = index
                heapq.heappush(queue, (candidate, other))
    raise ValueError("Kein sicherer Fahrweg zwischen Modell und Warteposition innerhalb des Druckbetts verfügbar.")


def segments_cross(a, b, c, d):
    def cross(p, q, r):
        return (q[0]-p[0])*(r[1]-p[1]) - (q[1]-p[1])*(r[0]-p[0])
    return cross(a, b, c)*cross(a, b, d) < -1e-10 and cross(c, d, a)*cross(c, d, b) < -1e-10


def original_paths_clear(source, center, base_radius, insertion_lines, *, cancellation_event=None, head_radius=0.0, head_height=0.0, lower_head_radius=0.0, gantry_height=None):
    """Convenience check; placement reuses a single OriginalMotionIndex."""
    from cooling_tower.preprocessor_placement import OriginalMotionIndex
    index = OriginalMotionIndex.capture(source, insertion_lines, cancellation_event=cancellation_event)
    return index.tower_rejection(center, base_radius, head_radius=head_radius,
        head_height=head_height, lower_head_radius=lower_head_radius, gantry_height=gantry_height) is None


def original_exclusions_clear(source, polygons, head_radius, *, cancellation_event=None, end_line=None):
    """Custom unknown-height obstacles cannot be crossed by retained moves."""
    if not polygons:
        return
    tracker = MachineStateTracker()
    printed = False
    for parsed in iter_parsed_gcode_lines(source):
        if end_line is not None and parsed.number > end_line:
            break
        if parsed.number % 2000 == 0 and cancellation_event is not None and cancellation_event.is_set():
            raise PreviewCancelled()
        event = tracker.process_line(parsed)
        if printed and parsed.command in {"G28", "G29", "G53", "G54", "G55", "G56", "G57", "G58", "G59"}:
            raise ValueError("Eine spätere Referenzfahrt kann mit eigenen Sperrflächen nicht sicher geprüft werden. "
                "Bitte eine Quelle mit bekannter Endsequenz ohne erneute Referenzfahrt verwenden.")
        if isinstance(event, Movement) and event.category == "deposition":
            printed = True
        if not isinstance(event, Movement) or event.endpoint_distance_xyz_mm <= 1e-9 and not event.is_arc:
            continue
        for move in motion_envelopes(event):
            a, b = move.a, move.b
            margin = head_radius + 1 + move.arc_guard
            for polygon in polygons:
                if (_point_in_polygon(a, polygon) or _point_in_polygon(b, polygon)
                        or any(segments_cross(a, b, p, polygon[i - 1]) or
                            min(_point_segment_distance(a, p, polygon[i - 1]), _point_segment_distance(b, p, polygon[i - 1]),
                                _point_segment_distance(p, a, b), _point_segment_distance(polygon[i - 1], a, b)) < margin
                            for i, p in enumerate(polygon))):
                    raise ValueError("Eine eigene Sperrfläche einschließlich Druckkopf-Abstand kollidiert mit dem unveränderten Original-G-Code. "
                        "Sperrfläche prüfen oder die Quelle im Slicer neu platzieren; Originalbahnen werden nicht umgeleitet.")
