"""Bounded seam markers from actual perimeter starts, before path sampling."""
import math

from cooling_tower.gcode.parser import Movement
from cooling_tower.preview.models import Point3D


class NativeSeamCollector:
    MAXIMUM_POINTS = 20_000
    WALL_FEATURES = frozenset({"outer wall", "external perimeter"})

    def __init__(self):
        self._wall = False
        self._printing = False
        self._layer_z = None
        self._points = []
        self._layer_heights = []
        self._seen = 0
        self._stride = 1

    def consume(self, parsed, event):
        comment = (parsed.comment or "").strip().lower()
        if comment.startswith(("type:", "feature:")):
            wall = comment.partition(":")[2].strip() in self.WALL_FEATURES
            if wall != self._wall:
                self._printing = False
            self._wall = wall
        elif comment in {"layer_change", "change_layer"}:
            self._printing = False
            self._layer_z = None
        elif comment.startswith(("z:", "z_height:")):
            try:
                z = float(comment.partition(":")[2])
            except ValueError:
                pass
            else:
                self._layer_z = z if math.isfinite(z) else None
        if not isinstance(event, Movement):
            return
        if event.category == "deposition":
            if self._wall and not self._printing:
                point = Point3D(event.start_x, event.start_y,
                    event.start_z)
                self._seen += 1
                if (self._seen-1) % self._stride == 0:
                    self._points.append(point)
                    self._layer_heights.append(event.end_z if self._layer_z is None else self._layer_z)
                    if len(self._points) > self.MAXIMUM_POINTS:
                        self._points = self._points[::2]
                        self._layer_heights = self._layer_heights[::2]
                        self._stride *= 2
            self._printing = True
        elif event.endpoint_distance_xyz_mm > 1e-6 or event.category in {"retraction", "unretraction"}:
            self._printing = False

    @property
    def points(self):
        return tuple(self._points)


    @property
    def layer_z(self):
        return tuple(self._layer_heights)
