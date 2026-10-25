"""Unsampled, immutable motion index reused by all placement candidates.

The XY tree only prunes candidates. Exact line distances, original chronology
and height tests remain authoritative; arcs keep a conservative enclosing box.
"""
from __future__ import annotations

from dataclasses import dataclass

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
    if move.arc_guard:
        x, y = point
        return (move.bounds[0] - radius <= x <= move.bounds[2] + radius
            and move.bounds[1] - radius <= y <= move.bounds[3] + radius)
    return _point_segment_distance(point, move.a, move.b) < radius


class OriginalMotionIndex:
    def __init__(self, moves, *, cancellation_event=None):
        self.cancellation_event = cancellation_event
        self.move_count = len(moves)
        self.root = _tree(moves, cancellation_event)
        self.depositions = _tree([move for move in moves if move.deposition], cancellation_event)
        self.deposition_count = sum(move.deposition for move in moves)
        self.examined_moves = 0

    @classmethod
    def capture(cls, source, insertion_lines, *, cancellation_event=None):
        _cancel(cancellation_event)
        tracker, tower_z, moves = MachineStateTracker(), 0.0, []
        for parsed in iter_parsed_gcode_lines(source):
            if parsed.number % 2000 == 0:
                _cancel(cancellation_event)
            event = tracker.process_line(parsed)
            if tower_z and parsed.command in {"G28", "G29", "G53", "G54", "G55", "G56", "G57", "G58", "G59"}:
                if not (parsed.command == "G28" and parsed.parameters and set(parsed.parameters).issubset({"X", "Y"})):
                    raise ValueError("Der Original-G-Code enthält nach dem Turmaufbau eine Referenzfahrt oder einen "
                        "Koordinatenwechsel. Dafür kann kein kollisionsfreier Weg nachgewiesen werden. "
                        "Bitte ein Profil mit einer sicheren Endsequenz ohne erneutes Homing wählen.")
            if isinstance(event, Movement) and (event.endpoint_distance_xyz_mm > 1e-9 or event.is_arc):
                a, b = (event.start_x, event.start_y), (event.end_x, event.end_y)
                guard = 2 * (event.arc_radius_mm or 0) if event.is_arc else 0.0
                moves.append(_Move(a, b, min(event.start_z, event.end_z), tower_z, guard,
                    event.category == "deposition", parsed.number,
                    (min(a[0], b[0])-guard, min(a[1], b[1])-guard,
                        max(a[0], b[0])+guard, max(a[1], b[1])+guard)))
            if parsed.number in insertion_lines:
                tower_z = insertion_lines[parsed.number]
        return cls(moves, cancellation_event=cancellation_event)

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
            radius = base_radius + lower_head_radius + 1 if move.z < move.tower_z + .1 else 0
            if move.z + head_height < move.tower_z + .1:
                radius = max(radius, base_radius + head_radius + 1)
            if radius and _near(move, center, radius):
                return f"Originalfahrt in Zeile {move.line} schneidet die Druckkopf-Freihülle am Turm (Z {move.z:g} mm)."
        if gantry_height is not None and self.root:
            bounds = self.root.bounds
            # Both possible axis spans remain enclosed if the profile does not
            # establish the crossbar direction. No kinematics are guessed.
            for box in ((x-margin, bounds[1], x+margin, bounds[3]),
                    (bounds[0], y-margin, bounds[2], y+margin)):
                for move in self._query(self.root, box):
                    if move.tower_z and move.z + gantry_height < move.tower_z + .1:
                        return f"Originalfahrt in Zeile {move.line} schneidet die angenommene Querträger-Freihülle am Turm."
        return None
