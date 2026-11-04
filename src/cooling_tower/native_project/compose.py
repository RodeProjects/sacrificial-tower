"""Append only new tower resources to the authoritative native archive.

Original mesh entries, triangle order and native overrides are copied verbatim.
The small edited XML fragments retain their original namespace spelling.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
import math
from pathlib import Path
import uuid
import zipfile
from xml.etree import ElementTree as ET
from xml.parsers import expat

from cooling_tower.native_project.archive import ProjectArchive, parse_xml
from cooling_tower.native_project.context import NativeProjectContext, NativeProjectError, ProjectProblem
from cooling_tower.native_project.graph import CORE_NAMESPACE, UNIT_SCALE_MM
from cooling_tower.native_project.layer_profile import encode_tower_profile, inherited_tower_profile, inherited_height_inputs, uses_embedded_layer_schedule
from cooling_tower.protected_io import OwnedWorkspace
from cooling_tower.tower.mesh_generator import TriangleMesh, validate_triangle_mesh


PROVENANCE = 'Metadata/SacrificialTower/manifest.json'
PATCH_ROOT = 'Metadata/SacrificialTower/base/'


def xml_span(data: bytes, path: tuple[str, ...], occurrence: int = 0) -> tuple[int, int, int, bool]:
    """Locate an XML element by parsed structure, including self-closing tags."""
    parser = expat.ParserCreate()
    stack, starts, matches = [], [], []

    def start(name, attrs):
        stack.append(name.split(':')[-1])
        offset, quote = parser.CurrentByteIndex, None
        cursor = offset
        while cursor < len(data):
            char = data[cursor]
            if quote is not None:
                if char == quote:
                    quote = None
            elif char in (34, 39):
                quote = char
            elif char == 62:
                break
            cursor += 1
        starts.append((offset, cursor + 1, data[offset:cursor].rstrip().endswith(b'/')))

    def end(name):
        first, open_end, empty = starts.pop()
        if tuple(stack) == path:
            closing = parser.CurrentByteIndex
            last = open_end if empty else data.index(b'>', closing) + 1
            matches.append((first, last, closing, empty))
        stack.pop()

    parser.StartElementHandler, parser.EndElementHandler = start, end
    parser.StartDoctypeDeclHandler = lambda *_: (_ for _ in ()).throw(ValueError('DTD is forbidden'))
    parser.Parse(data, True)
    if occurrence < 0 or occurrence >= len(matches):
        raise NativeProjectError(ProjectProblem.DAMAGED, 'Eine benötigte native XML-Struktur fehlt.')
    return matches[occurrence]


def insert_xml(data: bytes, path: tuple[str, ...], fragment: bytes, occurrence: int = 0) -> bytes:
    first, last, closing, empty = xml_span(data, path, occurrence)
    if empty:
        original = data[first:last]
        name = original[1:].split(None, 1)[0].split(b'/', 1)[0].split(b'>', 1)[0]
        replacement = original.rstrip()[:-2] + b'>' + fragment + b'</' + name + b'>'
        return data[:first] + replacement + data[last:]
    return data[:closing] + fragment + data[closing:]


def _mesh_xml(mesh: TriangleMesh, *, scale: float = 1.) -> bytes:
    result = io.StringIO()
    result.write('<mesh><vertices>')
    for point in mesh.vertices:
        result.write('<vertex x="%.12g" y="%.12g" z="%.12g"/>' % tuple(value / scale for value in point))
    result.write('</vertices><triangles>')
    for triangle in mesh.faces:
        result.write('<triangle v1="%d" v2="%d" v3="%d"/>' % triangle)
    result.write('</triangles></mesh>')
    return result.getvalue().encode('utf-8')


def plate_origin(context: NativeProjectContext, plate_id: str) -> tuple[float, float]:
    """Native rectangular multi-plate layout; qualified against native slices."""
    if context.adapter_id == 'prusa_slicer':
        return 0., 0.
    index = context.plate(plate_id).ordinal - 1
    columns = math.ceil(math.sqrt(len(context.plates)))
    xs, ys = zip(*context.bed_polygon)
    return (index % columns) * int(max(xs) - min(xs)) * 1.2, -(index // columns) * int(max(ys) - min(ys)) * 1.2


def _metadata(parent, key, value, *, kind=None):
    attributes = {'key': key, 'value': str(value)}
    if kind:
        attributes['type'] = kind
    ET.SubElement(parent, 'metadata', attributes)


def _declare_parts(data: bytes | None, parts: dict[str, str]) -> bytes:
    namespace = 'http://schemas.openxmlformats.org/package/2006/content-types'
    root = parse_xml(data) if data else ET.Element('Types', {'xmlns': namespace})
    existing = {node.get('PartName') for node in root if node.tag.rsplit('}', 1)[-1] == 'Override'}
    additions = []
    for name, mime in parts.items():
        if '/' + name not in existing:
            additions.append(ET.tostring(ET.Element('Override', {
                'xmlns': namespace, 'PartName': '/' + name, 'ContentType': mime})))
    return insert_xml(data or ET.tostring(root), ('Types',), b''.join(additions))


def _tower_config(identifier: int, face_count: int, *, prusa: bool, full_infill: bool,
                  supports_disabled: bool, filament: int, height_settings=None, wall_count=None) -> bytes:
    obj = ET.Element('object', {'id': str(identifier), **({'instances_count': '1'} if prusa else {})})
    kind = 'object' if prusa else None
    _metadata(obj, 'name', 'Sacrificial Tower', kind=kind)
    _metadata(obj, 'extruder', filament, kind=kind)
    _metadata(obj, 'brim_type', 'no_brim', kind=kind)
    _metadata(obj, 'brim_width', '0', kind=kind)
    for key, value in (height_settings or {}).items():
        _metadata(obj, key, value, kind=kind)
    if wall_count is not None and not full_infill:
        if type(wall_count) is not int or not 1 <= wall_count <= 10:
            raise ValueError("Ungültige Anzahl Turm-Wandlinien.")
        _metadata(obj, "perimeters" if prusa else "wall_loops", wall_count, kind=kind)
    if full_infill:
        _metadata(obj, 'fill_density' if prusa else 'sparse_infill_density', '100%', kind=kind)
        _metadata(obj, 'fill_pattern' if prusa else 'sparse_infill_pattern', 'rectilinear' if prusa else 'zig-zag', kind=kind)
    if supports_disabled:
        _metadata(obj, 'support_material' if prusa else 'enable_support', '0', kind=kind)
    if prusa:
        part = ET.SubElement(obj, 'volume', {'firstid': '0', 'lastid': str(face_count - 1)})
        _metadata(part, 'name', 'Sacrificial Tower', kind='volume')
        _metadata(part, 'volume_type', 'ModelPart', kind='volume')
    else:
        part = ET.SubElement(obj, 'part', {'id': str(identifier), 'subtype': 'normal_part', 'uuid': str(uuid.uuid4())})
        _metadata(part, 'name', 'Sacrificial Tower')
        _metadata(part, 'matrix', '1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1')
        ET.SubElement(part, 'mesh_stat', {'face_count': str(face_count), 'edges_fixed': '0', 'degenerate_facets': '0',
                                       'facets_removed': '0', 'facets_reversed': '0', 'backwards_edges': '0'})
    return ET.tostring(obj, encoding='utf-8')


@dataclass(frozen=True, slots=True)
class ComposedProject:
    path: Path
    tower_object_id: int
    plate_id: str
    placement_mm: tuple[float, float]
    mesh_sha256: str


def append_tower(context: NativeProjectContext, plate_id: str, mesh: TriangleMesh, *,
                 workspace: OwnedWorkspace, name: str = 'combined.3mf', center_mm: tuple[float, float],
                 full_infill: bool = True, supports_disabled: bool = True, filament: int = 1,
                 layer_print_z: tuple[float, ...] | None = None, wall_count: int | None = None) -> ComposedProject:
    context.snapshot.verify()
    plate = context.plate(plate_id)
    if not plate.build_indices:
        raise NativeProjectError(ProjectProblem.INCOMPLETE, 'Die ausgewählte Druckplatte enthält kein druckbares Objekt.')
    if not validate_triangle_mesh(mesh).is_valid:
        raise ValueError('Der ergänzte Turm ist kein gültiges geschlossenes Mesh.')
    if not all(math.isfinite(value) for value in center_mm) or len(center_mm) != 2:
        raise ValueError('Ungültige Turmposition.')
    if not 1 <= filament <= len(context.materials):
        raise ValueError('Das Turmmaterial gehört nicht zum eingebetteten Projekt.')
    target = workspace.child(name)
    if target.exists():
        raise FileExistsError(target)
    prusa = context.adapter_id == 'prusa_slicer'
    identifier = max(context.graph.main.resource_ids, default=0) + 1
    scale = UNIT_SCALE_MM[context.graph.main.unit]
    origin = plate_origin(context, plate_id)
    # Native readers scale mesh coordinates by the model unit, but retain
    # component/build translations in internal millimetres.
    translation = (origin[0] + center_mm[0], origin[1] + center_mm[1], 0.)
    matrix = '1 0 0 0 1 0 0 0 1 %.12g %.12g %.12g' % translation
    mesh_bytes = _mesh_xml(mesh, scale=scale)
    # Inline append works in all four native readers, without rebuilding any
    # existing component documents or relying on their resource-number spaces.
    object_xml = f'<object xmlns="{CORE_NAMESPACE}" id="{identifier}" type="model" name="Sacrificial Tower">'.encode() + mesh_bytes + b'</object>'
    item_xml = f'<item xmlns="{CORE_NAMESPACE}" objectid="{identifier}" transform="{matrix}" printable="1"/>'.encode()
    changed, removed, originals = {}, set(), {}
    with ProjectArchive(context.snapshot.path) as archive:
        if PROVENANCE in archive.names:
            raise NativeProjectError(ProjectProblem.UNSAFE, 'Ein eigener Export muss vor einer erneuten Verarbeitung auf seine geprüfte Projektbasis zurückgeführt werden.')
        main = archive.read(context.graph.main_path)
        changed[context.graph.main_path] = insert_xml(insert_xml(main, ('model', 'resources'), object_xml), ('model', 'build'), item_xml)
        config_path = 'Metadata/Slic3r_PE_model.config' if prusa else 'Metadata/model_settings.config'
        config = archive.read(config_path, metadata=True) if config_path in archive.names else b'<config/>'
        ranges_path = ('Metadata/Prusa_Slicer_layer_config_ranges.xml' if prusa
                       else 'Metadata/layer_config_ranges.xml')
        ranges = archive.read(ranges_path, metadata=True) if ranges_path in archive.names else b''
        heights, tower_ranges = inherited_height_inputs(context, plate_id, config, ranges)
        if tower_ranges:
            changed[ranges_path] = insert_xml(ranges, ('objects',), tower_ranges)
        config = insert_xml(config, ('config',), _tower_config(identifier, len(mesh.faces), prusa=prusa,
            full_infill=full_infill, supports_disabled=supports_disabled, filament=filament,
            height_settings=heights, wall_count=wall_count))
        if not prusa:
            root = parse_xml(config)
            plates = root.findall('plate')
            if not plates:
                node = ET.Element('plate')
                _metadata(node, 'plater_id', plate.identifier)
                for index in plate.build_indices:
                    object_id = context.graph.main.build[index].object_id
                    instance_index = sum(item.object_id == object_id for item in context.graph.main.build[:index])
                    instance = ET.SubElement(node, 'model_instance')
                    _metadata(instance, 'object_id', object_id)
                    _metadata(instance, 'instance_id', instance_index)
                config = insert_xml(config, ('config',), ET.tostring(node))
                root = parse_xml(config)
                plates = root.findall('plate')
            selected = plates[plate.ordinal - 1]
            for entry in list(selected):
                if entry.tag == 'metadata' and entry.get('key') in {'gcode_file', 'thumbnail_file', 'thumbnail_no_light_file', 'top_file', 'pick_file'}:
                    value = entry.get('value', '')
                    if value:
                        internal = archive.relationship_target('_rels/.rels', value, require_exists=False)
                        if internal in archive.names and not any(other is not selected and any(m.get('value') == value for m in other.findall('metadata')) for other in plates):
                            removed.add(internal)
                    entry.set('value', '')
            instance = ET.SubElement(selected, 'model_instance')
            _metadata(instance, 'object_id', identifier)
            _metadata(instance, 'instance_id', '0')
            # Use a fresh stable number, never an original object's name.
            used = [int(m.get('value')) for m in root.findall('.//model_instance/metadata')
                    if m.get('key') == 'identify_id' and m.get('value', '').isdecimal()]
            _metadata(instance, 'identify_id', max(used, default=0) + 1)
            first, last, _, _ = xml_span(config, ('config', 'plate'), plate.ordinal - 1)
            config = config[:first] + ET.tostring(selected) + config[last:]
        changed[config_path] = config
        if layer_print_z is not None and not uses_embedded_layer_schedule(context, layer_print_z):
            profile_path = ('Metadata/Slic3r_PE_layer_heights_profile.txt' if prusa
                            else 'Metadata/layer_heights_profile.txt')
            profile = archive.read(profile_path, metadata=True) if profile_path in archive.names else b''
            top_mm = max(point[2] for point in mesh.vertices)
            tower_profile = inherited_tower_profile(context, plate_id, profile, top_mm)
            if tower_profile is None and not (heights or tower_ranges):
                tower_profile = encode_tower_profile(context, layer_print_z, top_mm)
            if tower_profile is not None:
                changed[profile_path] = profile + (b'\n' if profile and not profile.endswith(b'\n') else b'') + tower_profile
        # Native slice summaries and the global thumbnail describe old output.
        # Other plates' model/settings/individual preview entries remain intact.
        removed.update(n for n in ('Metadata/slice_info.config', 'Metadata/thumbnail.png') if n in archive.names)
        for name in archive.names:
            if name.endswith('.rels'):
                data = archive.read(name, metadata=True)
                root = parse_xml(data)
                spans = []
                relations = [node for node in root if node.tag.rsplit('}', 1)[-1] == 'Relationship']
                for index, relation in enumerate(relations):
                    if archive.relationship_target(name, relation.get('Target', ''), require_exists=False) in removed:
                        first, last, _, _ = xml_span(data, ('Relationships', 'Relationship'), index)
                        spans.append((first, last))
                if spans:
                    # Native readers may compare literal XML names rather than
                    # namespace-expanded names. Preserve the original spelling;
                    # ElementTree's ns0 prefix can hide the main-model relation.
                    for first, last in reversed(spans):
                        data = data[:first] + data[last:]
                    changed[name] = data
        content_types = '[Content_Types].xml'
        # Include the patch for this content-type edit itself. Original native
        # declarations stay byte-identical; every new own part gets a MIME type.
        own_parts = {PROVENANCE: 'application/json'}
        own_parts.update({PATCH_ROOT + str(index) + '.bin': 'application/octet-stream'
            for index, entry in enumerate(archive.names)
            if entry in changed or entry in removed or entry == content_types})
        own_parts.update({entry: 'text/plain' for entry in changed if entry not in archive.names and entry.endswith('.txt')})
        changed[content_types] = _declare_parts(
            archive.read(content_types, metadata=True) if content_types in archive.names else None, own_parts)
        base_hashes, result_hashes, patches = {}, {}, []
        with zipfile.ZipFile(target, 'x', zipfile.ZIP_DEFLATED, compresslevel=6) as output:
            for index, entry in enumerate(archive.names):
                # Models are streamed to keep large painted meshes bounded.
                digest = hashlib.sha256()
                replacement = changed.get(entry)
                store_patch = entry in changed or entry in removed
                saved = io.BytesIO() if store_patch else None
                if entry not in removed:
                    destination = output.open(entry, 'w', force_zip64=True)
                else:
                    destination = None
                try:
                    for block in archive.iter_bytes(entry):
                        digest.update(block)
                        if saved is not None:
                            saved.write(block)
                        if destination is not None and replacement is None:
                            destination.write(block)
                    if destination is not None and replacement is not None:
                        destination.write(replacement)
                finally:
                    if destination is not None:
                        destination.close()
                base_hashes[entry] = digest.hexdigest()
                if entry not in removed:
                    result_hashes[entry] = hashlib.sha256(replacement).hexdigest() if replacement is not None else digest.hexdigest()
                if saved is not None:
                    patch = PATCH_ROOT + str(index) + '.bin'
                    output.writestr(patch, saved.getvalue())
                    patches.append([entry, patch])
            for entry, data in changed.items():
                if entry not in archive.names:
                    output.writestr(entry, data)
                    result_hashes[entry] = hashlib.sha256(data).hexdigest()
            manifest = {'schema': 1, 'base': base_hashes, 'result': result_hashes, 'patches': patches,
                        'plate_id': plate_id, 'tower_object_id': identifier,
                        'mesh_sha256': hashlib.sha256(mesh_bytes).hexdigest()}
            output.writestr(PROVENANCE, json.dumps(manifest, sort_keys=True, ensure_ascii=True))
    return ComposedProject(target, identifier, plate_id, center_mm, hashlib.sha256(mesh_bytes).hexdigest())


def restore_basis(source: Path, *, workspace: OwnedWorkspace) -> Path | None:
    """Verify the complete own-export record before removing any addition."""
    with ProjectArchive(source) as archive:
        if PROVENANCE not in archive.names:
            return None
        try:
            record = json.loads(archive.read(PROVENANCE, metadata=True))
            if record['schema'] != 1:
                raise ValueError()
            base, result, patches = record['base'], record['result'], dict(record['patches'])
            if not isinstance(base, dict) or not isinstance(result, dict):
                raise ValueError()
            reserved = {PROVENANCE, *patches.values()}
            if set(archive.names) != set(result) | reserved or not set(patches) <= set(base):
                raise ValueError()
            for name, digest in result.items():
                actual = hashlib.sha256()
                for block in archive.iter_bytes(name):
                    actual.update(block)
                if actual.hexdigest() != digest:
                    raise ValueError()
            target = workspace.child('restored_base.3mf')
            with zipfile.ZipFile(target, 'x', zipfile.ZIP_DEFLATED) as output:
                for name, digest in base.items():
                    # Validate every restored name with the archive path rules.
                    from cooling_tower.native_project.archive import _member_name
                    _member_name(name)
                    part = patches.get(name, name)
                    if part != name and not part.startswith(PATCH_ROOT):
                        raise ValueError()
                    actual = hashlib.sha256()
                    with output.open(name, 'w', force_zip64=True) as destination:
                        for block in archive.iter_bytes(part):
                            actual.update(block)
                            destination.write(block)
                    if actual.hexdigest() != digest:
                        raise ValueError()
            return target
        except (KeyError, TypeError, ValueError) as error:
            raise NativeProjectError(ProjectProblem.UNSAFE, 'Dieser bearbeitete Export stimmt nicht mehr mit seinem Herkunftsnachweis überein. Die unveränderte Projektbasis erneut auswählen.') from error
