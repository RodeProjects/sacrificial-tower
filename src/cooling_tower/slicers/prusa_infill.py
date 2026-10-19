"""Verify Prusa's actual rectilinear tower fill, including its feature labels."""
from __future__ import annotations

import math
from statistics import median

from cooling_tower.calibration.joint_project import JointProjectError, TowerInfillEvidenceCollector
from cooling_tower.gcode.parser import MachineStateTracker, Movement


class PrusaInfillEvidenceCollector(TowerInfillEvidenceCollector):
    # Prusa calls even fully dense rectilinear fill "Internal infill". Its
    # label alone cannot prove sparse or solid fill, unlike Orca's label.
    native_product_kind = None

    def __init__(self, **options):
        super().__init__(**options)
        self._tracker = MachineStateTracker()
        self._internal = False
        self._width = None
        self._groups = {}
        self._internal_seen = False
        self._checked_layers = 0
        self._spacing_invalid = False

    def consume(self, parsed):
        super().consume(parsed)
        comment = (parsed.comment or "").strip()
        if comment == "LAYER_CHANGE":
            self._check_layer()
        if comment.startswith("TYPE:"):
            self._internal = comment == "TYPE:Internal infill"
        elif comment.startswith("WIDTH:"):
            try:
                width = float(comment.partition(":")[2])
                self._width = width if math.isfinite(width) and width > 0 else None
            except ValueError:
                self._width = None
        movement = self._tracker.process_line(parsed)
        if not (self.inside_tower and self._internal and isinstance(movement, Movement)
                and movement.category == "deposition"):
            return
        self._internal_seen = True
        width = self._width
        length = math.hypot(movement.delta_x, movement.delta_y)
        if width is None or movement.is_arc or length < width * 3:
            return
        angle = math.atan2(movement.delta_y, movement.delta_x) % math.pi
        bucket = round(math.degrees(angle)) % 180
        normal = math.radians(bucket)
        nx, ny = -math.sin(normal), math.cos(normal)
        offset = nx * (movement.start_x + movement.end_x) / 2 + ny * (movement.start_y + movement.end_y) / 2
        self._groups.setdefault(bucket, []).append((offset, width, length))

    def _check_layer(self):
        if not self._groups:
            return
        rows = max(self._groups.values(), key=lambda items: sum(item[2] for item in items))
        width = median(item[1] for item in rows)
        unique = []
        for offset in sorted(item[0] for item in rows):
            if not unique or offset - unique[-1] > width * .05:
                unique.append(offset)
        if len(unique) >= 3:
            spacing = median(b-a for a, b in zip(unique, unique[1:]))
            self._checked_layers += 1
            self._spacing_invalid |= spacing > width * 1.35
        self._groups.clear()

    def validate(self):
        self._check_layer()
        super().validate()
        if self._spacing_invalid:
            raise JointProjectError("PrusaSlicer hat die 100-%-Turmfüllung nicht übernommen: Die ausgegebenen Fülllinien liegen zu weit auseinander.")
        if self._internal_seen and not self._checked_layers:
            raise JointProjectError("Die tatsächliche 100-%-Turmfüllung konnte im PrusaSlicer-G-Code nicht ausreichend geprüft werden.")
