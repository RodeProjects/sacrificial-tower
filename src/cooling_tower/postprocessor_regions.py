"""Source-bound, conservative drag guidance built once from all original moves.

Native array operations run in the worker. No source path is sampled for these
checks; repeated XY primitives are merged using their largest required margin.
The exact placement resolver remains authoritative when a handle is released.
"""
from collections import OrderedDict
from dataclasses import dataclass
import math
from threading import Lock

import numpy as np

from cooling_tower.preview.toolpath import PreviewCancelled


def _cancel(event):
    if event is not None and event.is_set():
        raise PreviewCancelled()


@dataclass(frozen=True, slots=True)
class PositionRegionMap:
    bounds: object
    columns: int
    rows: int
    states: bytes  # 0: invalid, 1: conservatively clear, 2: not yet checked


def _polygon(points, polygon, margin):
    """Vector equivalent of point-in-polygon and distance to every edge."""
    inside = np.zeros(len(points), dtype=bool)
    clear = np.ones(len(points), dtype=bool)
    x, y = points.T
    for i, (bx, by) in enumerate(polygon):
        ax, ay = polygon[i-1]
        if by != ay:
            inside ^= ((by > y) != (ay > y)) & (x < (ax-bx)*(y-by)/(ay-by)+bx)
        dx, dy = bx-ax, by-ay
        t = np.clip(((x-ax)*dx+(y-ay)*dy)/max(1e-18, dx*dx+dy*dy), 0, 1)
        clear &= (x-ax-t*dx)**2+(y-ay-t*dy)**2 >= max(0, margin-1e-9)**2
    return inside, clear


def _merge_lines(lines):
    if not len(lines):
        return np.empty((0, 5))
    # Opposite traversal directions describe the same capsule.
    reverse = (lines[:, 0] > lines[:, 2]) | ((lines[:, 0] == lines[:, 2]) & (lines[:, 1] > lines[:, 3]))
    lines[reverse, :4] = lines[reverse][:, (2, 3, 0, 1)]
    xy, inverse = np.unique(lines[:, :4], axis=0, return_inverse=True)
    radii = np.zeros(len(xy))
    np.maximum.at(radii, inverse, lines[:, 4])
    return np.column_stack((xy, radii))


class PlacementRegions:
    def __init__(self, geometry, motion_index, *, reserved_radius, tower_radius_at_z,
            height, model_margin, wait_margin, head, reachable):
        self.geometry, self.index = geometry, motion_index
        self.reserved, self.radius_at_z = reserved_radius, tower_radius_at_z
        self.height, self.model_margin, self.wait_margin = height, model_margin, wait_margin
        self.head, self.reachable = head, reachable
        self._lock = Lock()
        self._primitives = None
        self._fields = OrderedDict()
        self._maps = OrderedDict()
        self._map_lock = Lock()
        polygon = geometry.printable_polygon
        turns = [(b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0])
            for a, b, c in zip(polygon, polygon[1:]+polygon[:1], polygon[2:]+polygon[:2])]
        self._simple_bed = not geometry.excluded_polygons and (all(t >= -1e-9 for t in turns) or all(t <= 1e-9 for t in turns))

    def _build(self, event):
        moves, pending = [], [self.index.root] if self.index.root else []
        while pending:
            _cancel(event)
            node = pending.pop()
            if node.moves:
                moves.extend(node.moves)
            else:
                pending.extend((node.left, node.right))
        chunks = []
        for i in range(0, len(moves), 2048):
            _cancel(event)
            chunks.append(np.array([(*m.a, *m.b, m.z, m.tower_z, m.arc_guard, m.deposition, *m.bounds)
                for m in moves[i:i+2048]], dtype=float))
        data = np.concatenate(chunks) if chunks else np.empty((0, 12))
        z, built, deposit = data[:, 4], data[:, 5], data[:, 7].astype(bool)
        unique_z, inverse = np.unique(z, return_inverse=True)
        model_radii = np.array([self.radius_at_z(float(v)) for v in unique_z])[inverse]+self.model_margin
        tower_radii = np.where(deposit & (z <= self.height+.001), model_radii, 0.)
        motion_radii = np.where((built > 0) & (z < built+.1), self.reserved+1, 0.)
        motion_radii = np.maximum(motion_radii, np.where((built > 0) & (z < built-.001),
            self.reserved+self.head.lower_radius_mm+1, 0.))
        motion_radii = np.maximum(motion_radii, np.where((built > 0) & (z+self.head.clearance_height_mm < built-.001),
            self.reserved+self.head.radius_mm+1, 0.))
        tower_radii = np.maximum(tower_radii, motion_radii)
        wait_radii = np.where(deposit, self.wait_margin, 0.)
        primitives = {}
        for kind, radii in (("tower", tower_radii), ("wait", wait_radii)):
            _cancel(event)
            active = radii > 0
            lines = _merge_lines(np.column_stack((data[active, :4], radii[active]+data[active, 6])))
            boxes = np.empty((0, 4))
            if kind == "tower":
                gantry = (built > 0) & (z+self.head.clearance_height_mm < built-.001)
                margin = self.reserved+max(self.head.radius_mm, self.head.lower_radius_mm)+1
                bounds = data[gantry, 8:12]
                if len(bounds):
                    strips_x = bounds+np.array((-margin, -1e10, margin, 1e10))
                    strips_y = bounds+np.array((-1e10, -margin, 1e10, margin))
                    boxes = np.concatenate((boxes, strips_x, strips_y))
            boxes = np.unique(boxes, axis=0)
            lo = np.minimum(lines[:, :2], lines[:, 2:4])-lines[:, 4, None]
            hi = np.maximum(lines[:, :2], lines[:, 2:4])+lines[:, 4, None]
            primitives[kind] = lines, boxes, np.column_stack((lo, hi))
        _cancel(event)
        self._primitives = primitives

    def _clear(self, kind, points, edge, padding, event):
        radius = self.reserved if kind == "tower" else 0
        inside, clear = _polygon(points, self.geometry.printable_polygon, radius+edge+padding)
        valid = inside & clear
        for polygon in self.geometry.excluded_polygons:
            margin = max(radius+edge, radius+self.head.radius_mm+1) if kind == "tower" else max(edge, self.head.radius_mm+1)
            inside, clear = _polygon(points, polygon, margin+padding)
            valid &= ~inside & clear
        lines, boxes, bounds = self._primitives[kind]
        # Spatial tiles bound the temporary distance matrix, including dense
        # real slices. Every primitive overlapping a tile is still checked.
        b = self.geometry.bounds
        tile_size = max(1., (b.maximum_x_mm-b.minimum_x_mm)/12), max(1., (b.maximum_y_mm-b.minimum_y_mm)/12)
        tiles = np.floor((points-(b.minimum_x_mm, b.minimum_y_mm))/tile_size).astype(int)
        _, groups = np.unique(tiles, axis=0, return_inverse=True)
        order = np.argsort(groups, kind="stable")
        splits = np.flatnonzero(np.diff(groups[order]))+1
        for tile in np.split(order, splits):
            _cancel(event)
            indices = tile[valid[tile]]
            if not len(indices):
                continue
            pts = points[indices]
            low, high = pts.min(axis=0)-padding, pts.max(axis=0)+padding
            near = np.flatnonzero((bounds[:, 0] <= high[0]) & (bounds[:, 2] >= low[0])
                & (bounds[:, 1] <= high[1]) & (bounds[:, 3] >= low[1]))
            for offset in range(0, len(near), 256):
                _cancel(event)
                alive = valid[indices]
                if not np.any(alive):
                    break
                if not np.all(alive):
                    indices, pts = indices[alive], pts[alive]
                batch = lines[near[offset:offset+256]]
                a, delta = batch[:, :2], batch[:, 2:4]-batch[:, :2]
                diff = pts[:, None, :]-a
                t = np.clip(np.sum(diff*delta, axis=2)/np.maximum(1e-18, np.sum(delta*delta, axis=1)), 0, 1)
                dist = diff-t[:, :, None]*delta
                valid[indices] &= ~np.any(np.sum(dist*dist, axis=2) < (batch[:, 4]+padding)**2, axis=1)
            near_boxes = boxes[(boxes[:, 0] <= high[0]) & (boxes[:, 2] >= low[0])
                & (boxes[:, 1] <= high[1]) & (boxes[:, 3] >= low[1])]
            for offset in range(0, len(near_boxes), 256):
                _cancel(event)
                alive = valid[indices]
                if not np.any(alive):
                    break
                if not np.all(alive):
                    indices, pts = indices[alive], pts[alive]
                batch = near_boxes[offset:offset+256]
                valid[indices] &= ~np.any(np.all(pts[:, None, :] >= batch[:, :2]-padding, axis=2)
                    & np.all(pts[:, None, :] <= batch[:, 2:]+padding, axis=2), axis=1)
        return valid

    def _acquire(self, event):
        while not self._lock.acquire(timeout=.05):
            _cancel(event)

    def prepare(self, edge, *, event=None):
        self._acquire(event)
        try:
            _cancel(event)
            if edge in self._fields:
                return self._fields[edge]
            if self._primitives is None:
                self._build(event)
            b = self.geometry.bounds
            nx = min(96, max(24, math.ceil((b.maximum_x_mm-b.minimum_x_mm)/3)))
            ny = min(96, max(24, math.ceil((b.maximum_y_mm-b.minimum_y_mm)/3)))
            dx, dy = (b.maximum_x_mm-b.minimum_x_mm)/nx, (b.maximum_y_mm-b.minimum_y_mm)/ny
            xs, ys = np.meshgrid(b.minimum_x_mm+(np.arange(nx)+.5)*dx, b.maximum_y_mm-(np.arange(ny)+.5)*dy)
            points = np.column_stack((xs.ravel(), ys.ravel()))
            padding = math.hypot(dx, dy)/2
            masks = {kind: self._clear(kind, points, edge, padding, event) for kind in ("tower", "wait")}
            if not self.reachable(event=event):
                masks["tower"][:] = masks["wait"][:] = False
            elif not self._simple_bed:
                for i in np.flatnonzero(masks["tower"] | masks["wait"]):
                    _cancel(event)
                    x, y = points[i]
                    if not all(self.reachable((float(x+ox), float(y+oy)), event=event)
                            for ox, oy in ((0, 0), (-dx/2, -dy/2), (-dx/2, dy/2), (dx/2, -dy/2), (dx/2, dy/2))):
                        masks["tower"][i] = masks["wait"][i] = False
            _cancel(event)
            result = b, nx, ny, points, padding, masks
            self._fields[edge] = result
            while len(self._fields) > 3:
                self._fields.popitem(last=False)
            return result
        finally:
            self._lock.release()

    def regions(self, kind, settings, *, event=None):
        cached = self.cached_regions(kind, settings)
        if cached is not None:
            _cancel(event)
            return cached
        field = self.prepare(settings.edge_clearance_mm, event=event)
        return self._mask(kind, settings, field, event)

    def immediate_regions(self, kind, settings):
        """Bounded mask update only; never start or wait for field preparation.

        Convex beds without keepouts require no route or shared motion-index
        lock. Reuse that prepared field directly for an immediate mouse press.
        """
        cached = self.cached_regions(kind, settings)
        if cached is not None:
            return cached
        if not self._simple_bed or not self._lock.acquire(blocking=False):
            return None
        try:
            field = self._fields.get(settings.edge_clearance_mm)
        finally:
            self._lock.release()
        return self._mask(kind, settings, field, None) if field is not None else None

    def _mask(self, kind, settings, field, event):
        b, nx, ny, points, padding, masks = field
        other_kind = "wait" if kind == "tower" else "tower"
        other = (settings.wait_x_mm, settings.wait_y_mm) if kind == "tower" else (settings.center_x_mm, settings.center_y_mm)
        valid = masks[kind].copy()
        other_clear = self._clear(other_kind, np.array([other]), settings.edge_clearance_mm, 0, event)[0]
        if not other_clear or not self._simple_bed and not self.reachable(other, event=event):
            valid[:] = False
        else:
            required = self.reserved+settings.wait_clearance_mm+padding
            valid &= np.sum((points-other)**2, axis=1) >= required*required
        _cancel(event)
        result = PositionRegionMap(b, nx, ny, valid.astype(np.uint8).tobytes())
        with self._map_lock:
            self._maps[self._map_key(kind, settings)] = result
            while len(self._maps) > 24:
                self._maps.popitem(last=False)
        return result

    @staticmethod
    def _map_key(kind, settings):
        other = (settings.wait_x_mm, settings.wait_y_mm) if kind == "tower" else (settings.center_x_mm, settings.center_y_mm)
        return kind, other, settings.edge_clearance_mm

    def cached_regions(self, kind, settings):
        # Separate from the potentially busy preparation lock: UI lookups must
        # never wait for a source scan or a raster calculation to finish.
        with self._map_lock:
            return self._maps.get(self._map_key(kind, settings))
