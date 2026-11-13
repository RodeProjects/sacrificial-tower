"""Describe the added object's layers in each slicer's native height format."""
from __future__ import annotations

import math
from dataclasses import replace
from xml.etree import ElementTree as ET

from cooling_tower.native_project.context import NativeProjectContext


_AUXILIARY_FEATURES = frozenset({'prime tower', 'wipe tower', 'skirt', 'brim',
                                'skirt/brim', 'custom', 'custom gcode'})


def object_print_layer_indices(gcode_path, layers) -> frozenset[int]:
    """Separate object heights from independently scheduled support heights.

    Native support may use a different Z grid, including gaps too small for a
    model layer. Keep those print intervals in the time analysis without
    forcing the added object onto the support grid.
    """
    return frozenset(_object_layer_heights(gcode_path, layers))


def _object_layer_heights(gcode_path, layers):
    from cooling_tower.gcode.parser import MachineStateTracker, Movement, iter_parsed_gcode_lines
    if not layers:
        return {}
    tracker, role, index, found = MachineStateTracker(), '', 0, {}
    declared_height = None
    for parsed in iter_parsed_gcode_lines(gcode_path):
        comment = (parsed.comment or '').strip().casefold()
        if comment.startswith(('feature:', 'type:')):
            role = comment.partition(':')[2].strip()
        elif comment.startswith(('height:', 'layer_height:')):
            try:
                value = float(comment.partition(':')[2].strip())
                declared_height = value if math.isfinite(value) and value > 0 else None
            except ValueError:
                declared_height = None
        move = tracker.process_line(parsed)
        if not isinstance(move, Movement) or move.category != 'deposition' or move.delta_e <= 0:
            continue
        while index + 1 < len(layers) and parsed.number > layers[index].end_line:
            index += 1
        layer = layers[index]
        if (layer.first_deposition_line <= parsed.number <= layer.end_line
                and 'support' not in role and role not in _AUXILIARY_FEATURES):
            found.setdefault(layer.index, declared_height)
    return found


def object_geometry_layers(context, gcode_path, layers):
    """Use local model heights for geometry and retain original time indices.

    Raft print Z includes its base and contact gap. The first actual object
    extrusion's native HEIGHT tag supplies the model thickness, independently
    of preceding support heights in the same print interval.
    """
    heights = _object_layer_heights(gcode_path, layers)
    objects = tuple(layer for layer in layers if layer.index in heights)
    if not objects:
        return ()
    raft = float(context.settings.get('raft_layers', 0))
    # Prusa's print-layer Z already includes the configured machine Z offset;
    # the Bambu-family layer markers retain the unshifted logical print Z.
    lift = (float(context.settings.get('z_offset', 0))
            if getattr(context, 'adapter_id', '') == 'prusa_slicer' else 0.)
    if raft > 0:
        first_height = heights[objects[0].index]
        if first_height is None:
            raise ValueError('Die native Modellschichthöhe über dem Raft fehlt im Druck-G-Code.')
        lift = objects[0].z_mm - first_height
        if lift < -1e-5:
            raise ValueError('Die native Raft-Anhebung lässt sich nicht eindeutig zuordnen.')
    previous, result = 0., []
    for layer in objects:
        local_z = layer.z_mm - lift
        if local_z - previous <= 1e-5:
            raise ValueError('Die native Modellschichtfolge besitzt keine eindeutige lokale Höhe.')
        result.append(replace(layer, z_mm=local_z, height_mm=local_z-previous))
        previous = local_z
    return tuple(result)


def tower_model_index(context: NativeProjectContext) -> int:
    """Native profiles use a model-list ordinal, rather than a resource ID.

    The Bambu family creates model objects on the first build occurrence;
    Prusa creates them while reading mesh resources (component aliases are
    removed immediately). The tower is appended after all original resources.
    """
    if context.adapter_id == 'prusa_slicer':
        return 1 + sum(obj.vertex_count > 0 for doc in context.graph.documents for obj in doc.objects)
    return 1 + len({item.object_id for item in context.graph.main.build})


def uses_embedded_layer_schedule(context: NativeProjectContext, print_z: tuple[float, ...]) -> bool:
    """Keep native constant-height objects free of artificial adaptive profiles.

    The Bambu-family prime tower validates adaptive profiles across objects.
    An explicit profile can fail that validation even when it describes the
    very same layers already supplied by the embedded global configuration.
    """
    return bool(print_z) and len(print_z) <= 100_000 and all(
        math.isclose(z, context.initial_layer_height + index * context.layer_height,
                     rel_tol=0., abs_tol=1e-5)
        for index, z in enumerate(print_z))


def _selected_model_objects(context, plate_id):
    if context.adapter_id == 'prusa_slicer':
        objects = ((doc.path, obj.object_id) for doc in context.graph.documents
                   for obj in doc.objects if obj.vertex_count > 0)
    else:
        objects = dict.fromkeys((context.graph.main_path, item.object_id)
                                for item in context.graph.main.build)
    ordinals = {key: index for index, key in enumerate(objects, start=1)}
    selected, visited = set(), set()
    pending = [(context.graph.main_path, context.graph.main.build[index].object_id)
               for index in context.plate(plate_id).build_indices]
    while pending:
        key = pending.pop()
        if key in visited:
            continue
        visited.add(key)
        obj = context.graph.object(*key)
        if key in ordinals:
            selected.add(ordinals[key])
        pending.extend((component.model_path, component.object_id) for component in obj.components)
    return {index: key for key, index in ordinals.items() if index in selected}


def inherited_tower_profile(context: NativeProjectContext, plate_id: str,
                            profiles: bytes, top_mm: float, *,
                            top_tolerance_mm: float = 1e-4) -> bytes | None:
    """Retain the selected native curve, including its exact control points.

    Prime/wipe tower validation compares these points, rather than merely
    the resulting print heights. A measured staircase loses that equality.
    """
    selected = _selected_model_objects(context, plate_id)
    candidates = []
    for line in profiles.splitlines():
        key, separator, curve = line.partition(b'|')
        if not separator or not key.startswith(b'object_id='):
            continue
        try:
            identifier = int(key[len(b'object_id='):])
            values = tuple(float(value) for value in curve.split(b';'))
        except ValueError:
            continue
        if (identifier not in selected or len(values) < 6 or len(values) % 2
                or not all(math.isfinite(value) for value in values)
                or any(value <= 0 for value in values[1::2])
                or any(a > b for a, b in zip(values[::2], values[2::2]))
                or not math.isclose(values[0], 0., abs_tol=1e-6)
                or not math.isclose(values[-2], top_mm, rel_tol=0., abs_tol=top_tolerance_mm)):
            continue
        candidates.append((values[-2], curve))
    if not candidates:
        return None
    return b'object_id=%d|' % tower_model_index(context) + max(candidates)[1] + b'\n'


def inherited_height_inputs(context, plate_id, model_config: bytes, ranges: bytes):
    """Give a prime tower's companion the same native height inputs.

    Only height settings are inherited. Original range wall/infill/material
    overrides must never become settings of the added cooling tower.
    """
    from cooling_tower.native_project.archive import parse_xml
    prime = context.settings.get('wipe_tower' if context.adapter_id == 'prusa_slicer'
                                 else 'enable_prime_tower', False)
    if str(prime).casefold() not in {'1', 'true'}:
        return {}, b''
    selected = _selected_model_objects(context, plate_id)
    if not selected:
        return {}, b''
    def height(index):
        obj = context.graph.object(*selected[index])
        return obj.bounds_mm[5] - obj.bounds_mm[2] if obj.bounds_mm else 0.
    reference = max(selected, key=height)
    resource_id = str(selected[reference][1])
    original = next((obj for obj in parse_xml(model_config).findall('object')
                     if obj.get('id') == resource_id), None)
    values = ({node.get('key'): node.get('value') for node in original.findall('metadata')
               if node.get('key') == 'layer_height' and node.get('value') is not None}
              if original is not None else {})
    if not ranges:
        return values, b''
    original = next((obj for obj in parse_xml(ranges).findall('object')
                     if obj.get('id') == str(reference)), None)
    if original is None:
        return values, b''
    target = ET.Element('object', {'id': str(tower_model_index(context))})
    for item in original.findall('range'):
        layer = next((node for node in item.findall('option') if node.get('opt_key') == 'layer_height'), None)
        if layer is not None:
            clone = ET.SubElement(target, 'range', dict(item.attrib))
            ET.SubElement(clone, 'option', {'opt_key': 'layer_height'}).text = layer.text
            ET.SubElement(clone, 'option', {'opt_key': 'extruder'}).text = '0'
    return values, ET.tostring(target) if len(target) else b''


def solid_foot_ranges(context, height_settings, tower_ranges: bytes, foot_top_mm: float) -> bytes:
    """Apply dense infill only inside the foot, retaining inherited height overrides."""
    inherited = ET.fromstring(tower_ranges).findall('range') if tower_ranges else ()
    target = ET.Element('object', {'id': str(tower_model_index(context))})
    prusa = context.adapter_id == 'prusa_slicer'
    density_key = 'fill_density' if prusa else 'sparse_infill_density'
    pattern_key = 'fill_pattern' if prusa else 'sparse_infill_pattern'
    pattern = 'rectilinear' if prusa else 'zig-zag'

    def add_range(low, high, options, *, dense):
        item = ET.SubElement(target, 'range', {'min_z': format(low, '.12g'), 'max_z': format(high, '.12g')})
        if dense:
            options = {**options, density_key: '100%', pattern_key: pattern}
        for key, value in options.items():
            ET.SubElement(item, 'option', {'opt_key': key}).text = value

    regular = {'layer_height': str(height_settings.get('layer_height', context.layer_height)), 'extruder': '0'}
    covered = 0.
    for item in sorted(inherited, key=lambda item: float(item.get('min_z'))):
        low, high = float(item.get('min_z')), float(item.get('max_z'))
        options = {node.get('opt_key'): node.text for node in item.findall('option')}
        if covered < min(low, foot_top_mm):
            add_range(covered, min(low, foot_top_mm), regular, dense=True)
        if low < foot_top_mm:
            add_range(low, min(high, foot_top_mm), options, dense=True)
        if high > foot_top_mm:
            add_range(max(low, foot_top_mm), high, options, dense=False)
        covered = max(covered, high)
    if covered < foot_top_mm:
        add_range(covered, foot_top_mm, regular, dense=True)
    return ET.tostring(target)


def tower_geometry_height(context: NativeProjectContext, plate_id: str, layers) -> float:
    """Retain a native curve's true object top past its last rounded print Z."""
    from cooling_tower.native_project.archive import ProjectArchive
    path = ('Metadata/Slic3r_PE_layer_heights_profile.txt' if context.adapter_id == 'prusa_slicer'
            else 'Metadata/layer_heights_profile.txt')
    last = layers[-1]
    with ProjectArchive(context.snapshot.path) as archive:
        profile = archive.read(path, metadata=True) if path in archive.names else b''
    inherited = inherited_tower_profile(context, plate_id, profile, last.z_mm,
        top_tolerance_mm=max(1e-4, .5001 * last.height_mm))
    if inherited is None:
        return last.z_mm
    return float(inherited.partition(b'|')[2].split(b';')[-2])


def encode_tower_profile(context: NativeProjectContext, print_z: tuple[float, ...],
                         top_mm: float) -> bytes:
    """Encode constant steps at the measured original layer boundaries.

    Duplicate Z values represent a native discontinuity, not interpolation.
    Keeping the first-height pair is essential: Anycubic regenerates a profile
    whose first height differs from the project's initial layer height.
    """
    if (not print_z or len(print_z) > 100_000
            or not math.isfinite(top_mm) or top_mm <= 0):
        raise ValueError('Die Turmschichtfolge ist leer oder ungültig.')
    previous = 0.
    points = []
    for z in print_z:
        height = z - previous
        if not math.isfinite(z) or height <= 1e-5 or z > top_mm + 1e-4:
            raise ValueError('Die Turmschichtfolge ist nicht eindeutig aufsteigend.')
        points.extend((previous, height, z, height))
        previous = z
    if top_mm > previous:
        points.extend((top_mm, points[-1]))
    # The native readers require more than two pairs, including one-layer jobs.
    if len(points) == 4:
        points.extend(points[-2:])
    return ('object_id=%d|' % tower_model_index(context)
            + ';'.join(format(value, '.12g') for value in points) + '\n').encode('ascii')
