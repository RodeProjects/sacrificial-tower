"""Native plate occupancy, material choice and nearest safe tower placement."""
from __future__ import annotations

from dataclasses import dataclass
import heapq
import math

from cooling_tower.calibration.gcode_integration import _circle_fits_bed
from cooling_tower.gcode.parser import MachineStateTracker, Movement, iter_parsed_gcode_lines
from cooling_tower.models import TowerPlacement
from cooling_tower.native_project.archive import ProjectArchive, parse_xml
from cooling_tower.native_project.path_bounds import movement_bounds
from cooling_tower.native_project.placement import occupied_print_bounds


_WIPE = frozenset({'prime tower', 'wipe tower'})
_AUXILIARY = _WIPE | {'skirt', 'brim', 'skirt/brim', 'custom', 'custom gcode'}


def _expand_row(bits: int, radius: int) -> int:
    """Dilate set cells horizontally without iterating over individual cells."""
    result, covered, total = bits << radius, 1, radius * 2 + 1
    while covered < total:
        shift = min(covered, total - covered)
        result |= result >> shift
        covered += shift
    return result


def _single_project_material(context, plate_id):
    """Resolve unpainted native object/part assignments before tool remapping."""
    graph = context.graph
    selected = {graph.main.build[index].object_id for index in context.plate(plate_id).build_indices}
    visited, pending = set(), [(graph.main_path,identifier) for identifier in selected]
    while pending:
        key = pending.pop()
        if key in visited:
            continue
        visited.add(key)
        obj = graph.object(*key)
        if obj.painted_material_triangles:
            return None
        pending.extend((part.model_path,part.object_id) for part in obj.components)
    path = ('Metadata/Slic3r_PE_model.config' if context.adapter_id == 'prusa_slicer'
            else 'Metadata/model_settings.config')
    with ProjectArchive(context.snapshot.path) as archive:
        if path not in archive.names:
            return None
        root = parse_xml(archive.read(path, metadata=True))
    materials = set()
    for obj in root.findall('object'):
        if obj.get('id') not in {str(value) for value in selected}:
            continue
        values = {node.get('key'): node.get('value') for node in obj.findall('metadata')}
        default = values.get('extruder', '1')
        parts = obj.findall('volume' if context.adapter_id == 'prusa_slicer' else 'part')
        for part in parts or (obj,):
            if part.get('subtype', 'normal_part') != 'normal_part':
                continue
            values = {node.get('key'): node.get('value') for node in part.findall('metadata')}
            if values.get('volume_type', 'ModelPart') != 'ModelPart':
                continue
            try:
                value = int(values.get('extruder', default))
                materials.add(value if value > 0 else max(1, int(default)))
            except (TypeError, ValueError):
                return None
    return next(iter(materials)) if len(materials) == 1 else None


@dataclass(frozen=True, slots=True)
class NativePrintSpace:
    rows: tuple[int, ...]
    origin: tuple[float, float]
    step: float
    columns: int
    model_center: tuple[float, float]
    filament: int
    extrusion_margin: float

    @classmethod
    def capture(cls, prepared, bed):
        bounds = bed.bounds
        width = bounds.maximum_x_mm - bounds.minimum_x_mm
        height = bounds.maximum_y_mm - bounds.minimum_y_mm
        step = max(1., width / 1024., height / 1024.)
        columns, count = math.ceil(width / step) + 1, math.ceil(height / step) + 1
        origin = bounds.minimum_x_mm, bounds.minimum_y_mm
        rows, tools = [0] * count, set()
        model = [math.inf, -math.inf, math.inf, -math.inf]
        wipe = [math.inf, -math.inf, math.inf, -math.inf]

        def occupy(extents):
            x0, x1, y0, y1 = extents
            first_x = max(0, math.floor((x0-origin[0]) / step))
            last_x = min(columns-1, math.floor((x1-origin[0]) / step))
            first_y = max(0, math.floor((y0-origin[1]) / step))
            last_y = min(count-1, math.floor((y1-origin[1]) / step))
            if first_x > last_x or first_y > last_y:
                return
            bits = ((1 << (last_x-first_x+1))-1) << first_x
            for row in range(first_y, last_y+1):
                rows[row] |= bits

        tracker, role = MachineStateTracker(), ''
        first = prepared.analysis.layers[0].first_deposition_line
        last = prepared.analysis.layers[-1].end_line
        for parsed in iter_parsed_gcode_lines(prepared.gcode_path):
            comment = (parsed.comment or '').strip().casefold()
            if comment.startswith(('type:', 'feature:')):
                role = comment.partition(':')[2].strip()
            move = tracker.process_line(parsed)
            if (not isinstance(move, Movement) or move.category != 'deposition'
                    or move.delta_e <= 0 or not first <= parsed.number <= last):
                continue
            extents = movement_bounds(move)
            occupy(extents)
            if role in _WIPE:
                for axis, value in enumerate(extents):
                    wipe[axis] = (min if axis % 2 == 0 else max)(wipe[axis], value)
            elif role not in _AUXILIARY and 'support' not in role:
                tools.add(tracker.state.active_tool)
                for axis, value in enumerate(extents):
                    model[axis] = (min if axis % 2 == 0 else max)(model[axis], value)
        # A sparse wipe tower still reserves its complete interior footprint.
        if math.isfinite(wipe[0]):
            occupy(wipe)
        if not math.isfinite(model[0]):
            raise ValueError('Die native Platte enthält keine belegte Modellfläche.')
        actual = prepared.toolpaths.occupied_bounds
        padded = occupied_print_bounds(prepared)
        margin = padded.maximum_x_mm-actual.maximum_x_mm
        assigned = _single_project_material(prepared.context, prepared.plate_id) if len(tools) == 1 else None
        filament = assigned or (min(tools)+1 if tools else 1)
        if not 1 <= filament <= len(prepared.context.materials):
            raise ValueError('Das Modellmaterial lässt sich keinem eingebetteten Filament zuordnen.')
        return cls(tuple(rows), origin, step, columns,
                   ((model[0]+model[1])/2, (model[2]+model[3])/2), filament, margin)

    def place(self, bed, radius, *, clearance, edge_clearance):
        clearance, edge_clearance = max(5., clearance), max(5., edge_clearance)
        # Raster cells cover complete native deposition bounds. An extra cell
        # diagonal makes the discretized circle test conservative at cell edges.
        reach = radius + clearance + self.extrusion_margin + math.sqrt(2)*self.step
        limit = math.ceil(reach/self.step)
        blocked, cache = [0] * len(self.rows), {}
        mask = (1 << self.columns)-1
        for index, bits in enumerate(self.rows):
            if not bits:
                continue
            for offset in range(-limit, limit+1):
                row = index+offset
                if not 0 <= row < len(blocked):
                    continue
                dy = max(0, abs(offset)-1)*self.step
                dx = math.ceil(math.sqrt(max(0., reach*reach-dy*dy))/self.step)
                key = bits, dx
                expanded = cache.get(key)
                if expanded is None:
                    expanded = _expand_row(bits, dx) & mask
                    cache[key] = expanded
                blocked[row] |= expanded
        min_x = math.ceil((radius+edge_clearance)/self.step)
        max_x = math.floor((bed.bounds.maximum_x_mm-self.origin[0]-radius-edge_clearance)/self.step)
        if min_x > max_x:
            raise ValueError('Der Kühlturm passt mit den gewählten Abständen nicht auf das Druckbett.')
        allowed = ((1 << (max_x-min_x+1))-1) << min_x
        free, candidates = {}, []
        preferred_x = round((self.model_center[0]-self.origin[0])/self.step)

        def candidate(row):
            bits = free[row]
            if not bits:
                return
            split = max(0, min(preferred_x, self.columns-1))
            left, right = bits & ((1 << (split+1))-1), bits >> (split+1)
            choices = ([left.bit_length()-1] if left else [])
            if right:
                choices.append(split+1+(right & -right).bit_length()-1)
            x = min(choices, key=lambda value: (abs(value-preferred_x), value))
            point = self.origin[0]+x*self.step, self.origin[1]+row*self.step
            score = sum((a-b)**2 for a, b in zip(point, self.model_center))
            heapq.heappush(candidates, (score, row, x, point))

        for row in range(len(blocked)):
            y = self.origin[1]+row*self.step
            if bed.bounds.minimum_y_mm+radius+edge_clearance <= y <= bed.bounds.maximum_y_mm-radius-edge_clearance:
                free[row] = allowed & ~blocked[row]
                candidate(row)
        while candidates:
            _, row, x, point = heapq.heappop(candidates)
            if _circle_fits_bed(point, radius, edge_clearance, bed):
                return TowerPlacement(*point, radius, bed.bounds, clearance)
            free[row] &= ~(1 << x)
            candidate(row)
        raise ValueError('Auf der Druckplatte ist kein gültiger freier Platz für den Kühlturm vorhanden.')
