"""Support checks and watertight geometry for a single additional tower layer."""
from dataclasses import dataclass
import math

import numpy as np

from cooling_tower.tower.mesh_generator import TriangleMesh


def extrusion_segments(move, width):
    """Represent the deposited centerline, including XY arcs, as short chords."""
    start, end = (move.start_x, move.start_y), (move.end_x, move.end_y)
    radius, direction = move.arc_start_radius_mm, move.entry_direction_xyz
    if (move.arc_plane != 'XY' or not radius or not direction
            or not move.arc_sweep_degrees or not math.hypot(*direction[:2])):
        return ((start, end, width),)
    sign = 1 if move.command == 'G2' else -1
    length = math.hypot(*direction[:2])
    cx = start[0] + sign * direction[1] / length * radius
    cy = start[1] - sign * direction[0] / length * radius
    angle = math.atan2(start[1] - cy, start[0] - cx)
    sweep = -sign * math.radians(move.arc_sweep_degrees)
    # Bound the sagitta below the footprint grid resolution.
    count = max(1, math.ceil(abs(sweep) * math.sqrt(radius / .04)))
    points = (start, *((cx + radius * math.cos(angle + sweep * i / count),
                        cy + radius * math.sin(angle + sweep * i / count))
                       for i in range(1, count)), end)
    return tuple((a, b, width) for a, b in zip(points, points[1:]))


class SupportFootprint:
    def __init__(self, paths, center, radius, nozzle):
        self.step = max(.04, nozzle / 5, radius / 500)
        half = math.ceil((radius + nozzle) / self.step)
        self.axis = np.arange(-half, half + 1) * self.step
        self.center = center
        self.coverage = np.zeros((len(self.axis), len(self.axis)), dtype=bool)
        cx, cy = center
        for (x0, y0), (x1, y1), width in paths:
            x0, x1, y0, y1 = x0-cx, x1-cx, y0-cy, y1-cy
            reach = width / 2 + self.step * .55
            left, right = self.axis.searchsorted([min(x0,x1)-reach, max(x0,x1)+reach])
            bottom, top = self.axis.searchsorted([min(y0,y1)-reach, max(y0,y1)+reach])
            x, y = self.axis[None, left:right], self.axis[bottom:top, None]
            dx, dy = x1-x0, y1-y0
            factor = np.clip(((x-x0)*dx + (y-y0)*dy) / (dx*dx+dy*dy), 0, 1) if dx or dy else 0
            self.coverage[bottom:top, left:right] |= ((x-x0-factor*dx)**2 + (y-y0-factor*dy)**2 <= reach**2)

    def nearest_disk(self, radius, outer_radius, segments, nozzle):
        """Erode deposited coverage by the cap's printable cross section."""
        samples = max(0., (radius - nozzle * .35) / self.step)
        span = math.ceil(samples)
        size = len(self.axis)
        if 2 * span >= size:
            return None
        # Pack each row into a bitset. Intersect translated rows of the disk
        # rather than testing the full footprint separately at every position.
        rows = [int.from_bytes(row, 'little') for row in np.packbits(self.coverage, axis=1, bitorder='little')]
        widths = [int(math.sqrt(max(0., samples**2-dy**2))) for dy in range(-span, span+1)]
        eroded = {}
        for width in set(widths):
            count = 2 * width + 1
            values, covered = rows.copy(), 1
            while covered < count:
                shift = min(covered, count-covered)
                values = [row & (row >> shift) for row in values]
                covered += shift
            eroded[width] = [row << width for row in values]
        middle = size // 2
        allowed = max(0., outer_radius * math.cos(math.pi / segments) - radius)
        best = None
        for y in sorted(range(span, size-span), key=lambda index: abs(index-middle)):
            y_mm = self.axis[y]
            if abs(y_mm) > allowed or (best is not None and y_mm*y_mm > best[0]):
                break
            bits = (1 << size) - 1
            for dy, width in enumerate(widths, -span):
                bits &= eroded[width][y+dy]
                if not bits:
                    break
            if bits:
                left = bits & ((1 << middle)-1)
                right = bits >> middle
                candidates = ([left.bit_length()-1] if left else []) + (
                    [middle+(right & -right).bit_length()-1] if right else [])
                x = min(candidates, key=lambda index: abs(index-middle))
                x_mm = self.axis[x]
                squared = x_mm*x_mm+y_mm*y_mm
                if squared <= allowed**2 and (best is None or squared < best[0]):
                    best = squared, float(x_mm), float(y_mm)
                    if squared == 0:
                        break
        return None if best is None else best[1:]

    def supports(self, paths):
        cx, cy = self.center
        for (x0, y0), (x1, y1), _ in paths:
            count = max(2, math.ceil(math.hypot(x1-x0, y1-y0) / self.step) + 1)
            origin = len(self.axis) // 2
            xs = np.rint((np.linspace(x0,x1,count)-cx)/self.step).astype(int)+origin
            ys = np.rint((np.linspace(y0,y1,count)-cy)/self.step).astype(int)+origin
            if (min(xs.min(),ys.min()) < 0 or max(xs.max(),ys.max()) >= len(self.axis)
                    or not self.coverage[ys,xs].all()):
                return False
        return bool(paths)


@dataclass(frozen=True, slots=True)
class TopLayerShape:
    radius: float
    offset: tuple[float, float] = (0., 0.)
    inner_radius: float = 0.


def extend_mesh(mesh, shape, z_top):
    """Replace the top disk with a joined cap or a hollow, wall-aligned rim."""
    count = mesh.segment_count
    base = (mesh.ring_count - 1) * count
    old_center = len(mesh.vertices) - 1
    vertices = list(mesh.vertices[:-1])
    faces = [face for face in mesh.faces if old_center not in face]
    z_base = vertices[base][2]
    old_radius = math.hypot(*vertices[base][:2])

    def ring(radius, z, offset=(0., 0.)):
        first = len(vertices)
        for i in range(count):
            angle = math.tau * i / count
            vertices.append((offset[0]+radius*math.cos(angle), offset[1]+radius*math.sin(angle), z))
        return first

    def join(lower, upper):
        for i in range(count):
            j = (i+1) % count
            faces.extend(((lower+i, lower+j, upper+j), (lower+i, upper+j, upper+i)))

    def disk(first, z, offset):
        center_index = len(vertices)
        vertices.append((*offset, z))
        for i in range(count):
            faces.append((center_index, first+i, first+(i+1) % count))

    if shape.inner_radius:
        outer_top = ring(old_radius, z_top)
        inner_top = ring(shape.inner_radius, z_top)
        inner_base = ring(shape.inner_radius, z_base)
        join(base, outer_top)
        join(outer_top, inner_top)
        join(inner_top, inner_base)
        disk(inner_base, z_base, (0., 0.))
    else:
        if abs(old_radius-shape.radius) < 1e-8 and shape.offset == (0., 0.):
            cap_base = base
        else:
            cap_base = ring(shape.radius, z_base, shape.offset)
            join(base, cap_base)
        cap_top = ring(shape.radius, z_top, shape.offset)
        join(cap_base, cap_top)
        disk(cap_top, z_top, shape.offset)
    return TriangleMesh(tuple(vertices), tuple(faces), mesh.ring_count+1, count)
