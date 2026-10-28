"""Unsampled, immutable motion index reused by all placement candidates.

The XY tree only prunes candidates. Line distances, original chronology and
height tests remain authoritative. Arc chords retain their full deviation as
a safety margin, independent of preview sampling.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from cooling_tower.calibration.gcode_integration import _point_segment_distance
from cooling_tower.gcode.parser import MachineStateTracker, Movement, iter_parsed_gcode_lines
from cooling_tower.preview.toolpath import PreviewCancelled


def _cancel(event):
    if event is not None and event.is_set():
        raise PreviewCancelled()


@dataclass(frozen=True, slots=True)
class _Move:
    a: tuple[float, float]
    b: tuple[float, float]
    z: float
    tower_z: float
    arc_guard: float
    deposition: bool
    line: int
    bounds: tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class _Node:
    bounds: tuple[float, float, float, float]
    moves: tuple[_Move, ...] = ()
    left: _Node | None = None
    right: _Node | None = None


def _tree(moves, event):
    if not moves:
        return None
    _cancel(event)
    bounds = (min(m.bounds[0] for m in moves), min(m.bounds[1] for m in moves),
        max(m.bounds[2] for m in moves), max(m.bounds[3] for m in moves))
    if len(moves) <= 16:
        return _Node(bounds, tuple(moves))
    axis = 0 if bounds[2] - bounds[0] >= bounds[3] - bounds[1] else 1
    moves = sorted(moves, key=lambda m: m.bounds[axis] + m.bounds[axis + 2])
    middle = len(moves) // 2
    return _Node(bounds, left=_tree(moves[:middle], event), right=_tree(moves[middle:], event))


def _overlap(a, b):
    return a[0] <= b[2] and a[2] >= b[0] and a[1] <= b[3] and a[3] >= b[1]


def _near(move, point, radius):
    return _point_segment_distance(point, move.a, move.b) < radius + move.arc_guard


def motion_envelopes(event):
    """Enclose every original move with chords plus a proven radial margin.

    A short fitted arc can have a metre-scale radius. Its enclosing *circle*
    is irrelevant to occupied space. Split the swept curve so the sagitta of
    each chord is at most .01 mm, adding that deviation and any endpoint radius
    mismatch to every distance test. A bounded subdivision count still retains
    the actual (possibly larger) deviation, never silently dropping geometry.
    Tangents and radii come from the modal parser, including R, G90.1 and units.
    """
    start = (event.start_x, event.start_y, event.start_z)
    end = (event.end_x, event.end_y, event.end_z)

    def move(a, b, guard=0.0):
        z = min(a[2], b[2]) - (guard if event.is_arc and event.arc_plane != "XY" else 0)
        return _Move(a[:2], b[:2], z, 0, guard, event.category == "deposition", event.line_number,
            (min(a[0], b[0])-guard, min(a[1], b[1])-guard,
                max(a[0], b[0])+guard, max(a[1], b[1])+guard))

    if not event.is_arc:
        yield move(start, end)
        return
    radius = event.arc_start_radius_mm
    tangent = event.entry_direction_xyz
    planes = {"XY": (0, 1, 2), "XZ": (2, 0, 1), "YZ": (1, 2, 0)}
    if (event.arc_error or radius is None or not math.isfinite(radius) or radius <= 0 or tangent is None
            or event.arc_sweep_degrees is None or not math.isfinite(event.arc_sweep_degrees)
            or not 0 < event.arc_sweep_degrees <= 360 or event.arc_plane not in planes
            or not all(math.isfinite(value) for value in (*start, *end, *tangent))):
        raise ValueError(f"Kreisbogen in Zeile {event.line_number} kann nicht sicher geometrisch geprüft werden.")
    u, v, w = planes[event.arc_plane]
    direction = -1 if event.command == "G2" else 1
    center_u = start[u] - direction*tangent[v]*radius
    center_v = start[v] + direction*tangent[u]*radius
    angle = math.atan2(start[v]-center_v, start[u]-center_u)
    sweep = math.radians(event.arc_sweep_degrees)
    step = min(math.pi/2, 4*math.asin(math.sqrt(min(1., .005/radius))))
    count = max(1, math.ceil(min(4096., sweep/step))) if step else 4096
    # Stable for tiny sweeps; 1-cos(theta/2) loses precision there.
    sagitta = radius*(2*math.sin(sweep/count/4)**2)
    mismatch = abs(math.hypot(end[u]-center_u, end[v]-center_v)-radius)
    # A rounded end radius can shift both the firmware's curve and the last
    # chord from the ideal start-radius circle. Reserve both deviations.
    guard = sagitta + 2*mismatch + 1e-7
    a = start
    for i in range(1, count+1):
        if i == count:
            b = end
        else:
            point = list(start)
            theta = angle + direction*sweep*i/count
            point[u], point[v] = center_u+radius*math.cos(theta), center_v+radius*math.sin(theta)
            point[w] = start[w]+(end[w]-start[w])*i/count
            b = tuple(point)
        yield move(a, b, guard)
        a = b


class OriginalMotionIndex:
    def __init__(self, moves, *, cancellation_event=None):
        self.cancellation_event = cancellation_event
        self.move_count = len({move.line for move in moves})
        self.root = _tree(moves, cancellation_event)
        self.depositions = _tree([move for move in moves if move.deposition], cancellation_event)
        self.deposition_count = len({move.line for move in moves if move.deposition})
        self.has_lowered_tower_moves = any(move.tower_z and move.z < move.tower_z-.001 for move in moves)
        self.examined_moves = 0

    @classmethod
    def capture(cls, source, insertion_lines, *, cancellation_event=None):
        _cancel(cancellation_event)
        tracker, collector = MachineStateTracker(), OriginalMotionCollector()
        for parsed in iter_parsed_gcode_lines(source):
            if parsed.number % 2000 == 0:
                _cancel(cancellation_event)
            event = tracker.process_line(parsed)
            collector.consume(parsed, event)
        return collector.finish(insertion_lines, cancellation_event=cancellation_event)

    def _query(self, root, box):
        pending = [root] if root else []
        while pending:
            node = pending.pop()
            if not _overlap(node.bounds, box):
                continue
            _cancel(self.cancellation_event)
            if node.moves:
                for move in node.moves:
                    if _overlap(move.bounds, box):
                        self.examined_moves += 1
                        yield move
            else:
                pending.extend((node.left, node.right))

    def model_clear(self, point, maximum_radius, radius_at_z, *, height=float("inf")):
        x, y = point
        box = (x-maximum_radius, y-maximum_radius, x+maximum_radius, y+maximum_radius)
        for move in self._query(self.depositions, box):
            if move.z <= height + .001 and _near(move, point, radius_at_z(move.z)):
                return False
        return True

    def tower_rejection(self, center, base_radius, *, head_radius=0.0, head_height=0.0,
            lower_head_radius=0.0, gantry_height=None):
        margin = base_radius + max(head_radius, lower_head_radius) + 1
        x, y = center
        for move in self._query(self.root, (x-margin, y-margin, x+margin, y+margin)):
            if not move.tower_z:
                continue
            # A nozzle at the current layer height does not place the whole
            # print head at that height. Its body extends above the nozzle.
            radius = base_radius + 1 if move.z < move.tower_z + .1 else 0
            if move.z < move.tower_z - .001:
                radius = max(radius, base_radius + lower_head_radius + 1)
            if move.z + head_height < move.tower_z - .001:
                radius = max(radius, base_radius + head_radius + 1)
            if radius and _near(move, center, radius):
                return f"Originalfahrt in Zeile {move.line} schneidet den Druckkopf-Sicherheitsbereich am Turm (Z {move.z:g} mm)."
        if gantry_height is not None and self.root:
            bounds = self.root.bounds
            # Both possible axis spans remain enclosed if the profile does not
            # establish the crossbar direction. No kinematics are guessed.
            for box in ((x-margin, bounds[1], x+margin, bounds[3]),
                    (bounds[0], y-margin, bounds[2], y+margin)):
                for move in self._query(self.root, box):
                    if move.tower_z and move.z + gantry_height < move.tower_z - .001:
                        return f"Originalfahrt in Zeile {move.line} schneidet den angenommenen Querträger-Sicherheitsbereich am Turm."
        return None


class OriginalMotionCollector:
    """Reuse parsed events; bind exact tower chronology once endpoints are known."""

    def __init__(self):
        self.moves, self.reference_lines = [], []

    def consume(self, parsed, event):
        if parsed.command in {"G28", "G29", "G53", "G54", "G55", "G56", "G57", "G58", "G59"}:
            if not (parsed.command == "G28" and parsed.parameters and set(parsed.parameters).issubset({"X", "Y"})):
                self.reference_lines.append(parsed.number)
        if isinstance(event, Movement) and (event.endpoint_distance_xyz_mm > 1e-9 or event.is_arc):
            self.moves.extend(motion_envelopes(event))

    def finish(self, insertion_lines, *, cancellation_event=None, end_line=None):
        _cancel(cancellation_event)
        insertions = iter(sorted(insertion_lines.items()))
        next_insertion = next(insertions, None)
        reference_limit = next_insertion[0] if next_insertion else end_line
        if reference_limit is not None and any(line > reference_limit for line in self.reference_lines):
            raise ValueError("Der Original-G-Code enthält nach dem Turmaufbau eine Referenzfahrt oder einen "
                "Koordinatenwechsel. Dafür kann kein kollisionsfreier Weg nachgewiesen werden. "
                "Bitte ein Profil mit einer sicheren Endsequenz ohne erneutes Homing wählen.")
        tower_z, moves = 0.0, []
        for i, move in enumerate(self.moves):
            if i % 2000 == 0:
                _cancel(cancellation_event)
            # End parking is replaced by the postprocessor. Its original XY
            # paths no longer constrain tower placement; unknown references
            # above still fail closed, including when no tower is needed.
            if end_line is not None and move.line > end_line:
                continue
            while next_insertion and next_insertion[0] < move.line:
                tower_z = next_insertion[1]
                next_insertion = next(insertions, None)
            moves.append(_Move(move.a, move.b, move.z, tower_z, move.arc_guard, move.deposition, move.line, move.bounds))
        return OriginalMotionIndex(moves, cancellation_event=cancellation_event)
