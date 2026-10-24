"""Collision checks and XY routes for lifted preprocessor travel moves."""
from __future__ import annotations

import heapq
import math

from cooling_tower.calibration.gcode_integration import (
    _point_in_polygon, _point_segment_distance, _distance_to_polygon_edges,
)
from cooling_tower.gcode.parser import MachineStateTracker, Movement, iter_parsed_gcode_lines
from cooling_tower.preview.toolpath import PreviewCancelled


def safe_travel_path(start, end, geometry, *, margin_mm=1.0):
    """Shortest visibility route, keeping clear of profile exclusion polygons.

    All these XY moves are executed at a height above every printed layer.
    Exclusions are still treated as obstacles, regardless of their height.
    """
    def point_safe(point):
        return (_point_in_polygon(point, geometry.printable_polygon)
            and all(not _point_in_polygon(point, polygon)
                and _distance_to_polygon_edges(point, polygon) >= margin_mm - 1e-6
                for polygon in geometry.excluded_polygons))

    def visible(a, b):
        # Segments cannot cross a thin exclusion between sampled points.
        for polygon in geometry.excluded_polygons:
            for i, p in enumerate(polygon):
                q = polygon[i - 1]
                if segments_cross(a, b, p, q):
                    return False
                if min(_point_segment_distance(a, p, q), _point_segment_distance(b, p, q),
                        _point_segment_distance(p, a, b), _point_segment_distance(q, a, b)) < margin_mm - 1e-6:
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
    for polygon in geometry.excluded_polygons:
        xs, ys = zip(*polygon)
        gap = margin_mm + 0.1
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


def original_paths_clear(source, center, base_radius, insertion_lines, *, cancellation_event=None):
    """Reject a tower intersecting an unmodified later model/end-code move.

    The entire original program resumes at precisely its original coordinates.
    Its future travels therefore also need to avoid the added structure.
    """
    tracker = MachineStateTracker()
    tower_z = 0.0
    for parsed in iter_parsed_gcode_lines(source):
        if parsed.number % 2000 == 0 and cancellation_event is not None and cancellation_event.is_set():
            raise PreviewCancelled()
        event = tracker.process_line(parsed)
        if tower_z and parsed.command in {"G28", "G29", "G53", "G54", "G55", "G56", "G57", "G58", "G59"}:
            if parsed.command == "G28" and parsed.parameters and set(parsed.parameters).issubset({"X", "Y"}):
                # The renderer adds a verified Z lift before terminal XY homing.
                continue
            raise ValueError("Der Original-G-Code enthält nach dem Turmaufbau eine Referenzfahrt oder einen "
                "Koordinatenwechsel. Dafür kann kein kollisionsfreier Weg nachgewiesen werden. "
                "Bitte ein Profil mit einer sicheren Endsequenz ohne erneutes Homing wählen.")
        if tower_z and isinstance(event, Movement) and min(event.start_z, event.end_z) < tower_z + .1:
            a, b = (event.start_x, event.start_y), (event.end_x, event.end_y)
            if event.is_arc:
                # Enclose a possible arc in a conservative swept envelope.
                radius = 2 * (event.arc_radius_mm or 0)
                near = (min(a[0], b[0])-radius <= center[0] <= max(a[0], b[0])+radius
                    and min(a[1], b[1])-radius <= center[1] <= max(a[1], b[1])+radius)
                if near:
                    return False
            elif _point_segment_distance(center, a, b) < base_radius + 1.0:
                return False
        if parsed.number in insertion_lines:
            tower_z = insertion_lines[parsed.number]
    return True
