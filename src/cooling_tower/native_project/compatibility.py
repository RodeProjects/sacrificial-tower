"""Narrow execution-only workarounds; the native export remains unchanged."""
from pathlib import Path
import json
import re
import zipfile
from xml.etree import ElementTree as ET

from cooling_tower.native_project.archive import ProjectArchive, parse_xml
from cooling_tower.native_project.compose import xml_span, xml_spans
from cooling_tower.native_project.context import NativeProjectContext
from cooling_tower.protected_io import OwnedWorkspace


def _encode_scalar(value: str) -> str:
    # Native scalar ConfigOptionString serialization. This is distinct from
    # JSON escaping and from JSON vector-of-string values (which remain raw).
    return value.translate(str.maketrans({'\\': '\\\\', '"': '\\"', '\n': '\\n', '\r': '\\r'}))


def _decode_scalar(value: str) -> str:
    if len(value) - len(value.rstrip('\\')) & 1:
        raise ValueError('Eine native Zeichenketteneinstellung endet mit einer unvollständigen Escape-Sequenz.')
    return re.sub(r'\\(.)', lambda match: {'n': '\n', 'r': '\r'}.get(match[1], match[1]), value, flags=re.DOTALL)


def freeze_plate_name(template: str, name: str) -> str:
    """Specialize one immutable native placeholder; leave evaluation native.

    Replace only identifier tokens inside macro expressions, never quoted text
    or ordinary G-code. Legacy substitutions become string expressions, so a
    name containing braces cannot accidentally become another macro program.
    """
    literal = '"' + _encode_scalar(name) + '"'
    result, cursor, depth, quote = [], 0, 0, None
    while cursor < len(template):
        char = template[cursor]
        if quote is not None:
            result.append(char)
            if char == '\\' and cursor + 1 < len(template):
                cursor += 1
                result.append(template[cursor])
            elif char == quote:
                quote = None
            cursor += 1
            continue
        if template.startswith('[plate_name]', cursor):
            result.append(literal if depth else '{' + literal + '}')
            cursor += len('[plate_name]')
            continue
        if char == '{':
            depth += 1
        elif char == '}':
            depth = max(0, depth - 1)
        elif depth and char in {'"', "'"}:
            quote = char
        elif depth and (char.isalpha() or char == '_'):
            end = cursor + 1
            while end < len(template) and (template[end].isalnum() or template[end] == '_'):
                end += 1
            token = template[cursor:end]
            result.append(literal if token == 'plate_name' else token)
            cursor = end
            continue
        result.append(char)
        cursor += 1
    return ''.join(result)


def _gcode_setting(key: str) -> bool:
    return 'gcode' in key.casefold() or key.casefold().endswith('filename_format')


def _freeze_value(value, name, *, scalar=True):
    if isinstance(value, str):
        if 'plate_name' not in value:
            return value
        decoded = _decode_scalar(value) if scalar else value
        specialized = freeze_plate_name(decoded, name)
        return (_encode_scalar(specialized) if scalar else specialized) if specialized != decoded else value
    if isinstance(value, list):
        return [_freeze_value(item, name, scalar=False) for item in value]
    return value


def _freeze_metadata(archive, config_path, config, name):
    changes = {config_path: config}
    for path in archive.names:
        if not path.startswith('Metadata/') or path == config_path:
            continue
        if path.endswith('.config'):
            raw = archive.read(path, metadata=True)
            if not raw.lstrip().startswith(b'{'):
                continue
            values = json.loads(raw)
            changed = False
            if not isinstance(values, dict):
                continue
            for key, value in tuple(values.items()):
                if _gcode_setting(key):
                    specialized = _freeze_value(value, name)
                    if specialized != value:
                        values[key] = specialized
                        changed = True
            if changed:
                changes[path] = json.dumps(values, ensure_ascii=True).encode()
        elif path in {'Metadata/custom_gcode_per_layer.xml', 'Metadata/layer_config_ranges.xml'}:
            raw = archive.read(path, metadata=True)
            root = parse_xml(raw)
            changed = False
            for node in root.iter():
                key = node.get('key', node.get('opt_key', ''))
                for attribute, value in tuple(node.attrib.items()):
                    if attribute in {'gcode', 'extra'} or (attribute == 'value' and _gcode_setting(key)):
                        specialized = (_freeze_value(value, name) if attribute == 'value' else freeze_plate_name(value, name))
                        if specialized != value:
                            node.set(attribute, specialized)
                            changed = True
                if node.text and (node.tag == 'gcode' or _gcode_setting(key)):
                    specialized = freeze_plate_name(node.text, name) if node.tag == 'gcode' else _freeze_value(node.text, name)
                    if specialized != node.text:
                        node.text = specialized
                        changed = True
            if changed:
                changes[path] = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    # Object/part/plate overrides stay in their original raw XML unless a
    # G-code setting actually contains the placeholder needing specialization.
    root = parse_xml(changes[config_path])
    changed = False
    for node in root.findall('.//metadata'):
        if _gcode_setting(node.get('key', '')) and node.get('value'):
            value = node.get('value')
            specialized = _freeze_value(value, name)
            if specialized != value:
                node.set('value', specialized)
                changed = True
    if changed:
        changes[config_path] = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    return changes


def _tower_only_model(context, archive, plate_id):
    data = archive.read(context.graph.main_path)
    spans = xml_spans(data, ('model', 'build', 'item'))
    for index in reversed(context.plate(plate_id).build_indices):
        first, last, _, _ = spans[index]
        item = data[first:last]
        match = re.match(rb'<[^\s/>]+(?P<attributes>(?:[^"\'>]|"[^"]*"|\'[^\']*\')*)>', item)
        if match is None:
            raise ValueError('Der native Druckplatteneintrag konnte nicht isoliert werden.')
        attributes = match['attributes']
        # Match attributes as complete name/value pairs so a quoted value
        # containing the word printable cannot be mistaken for the flag.
        token = next((attribute for attribute in re.finditer(
            rb'\s+([^\s=]+)\s*=\s*(?:"[^"]*"|\'[^\']*\')', attributes)
            if attribute[1] == b'printable'), None)
        if token is None:
            start = end = match.start('attributes')
        else:
            start = match.start('attributes') + token.start()
            end = match.start('attributes') + token.end()
        data = data[:first+start] + b' printable="0"' + data[first+end:]
    return data


def execution_project(context: NativeProjectContext, source: Path, workspace: OwnedWorkspace, *,
                      plate_id: str, tower_only: bool = False) -> Path:
    # Anycubic 2.0.0.3 PartPlate::set_plate_name unconditionally creates a GUI
    # text texture. Its CLI has no Plater and crashes even on a neutral named
    # plate. Preserve the selected name's native G-code placeholder semantics
    # before bypassing that GUI path. Basis and exported project stay unchanged.
    if context.adapter_id != 'anycubic_slicer_next' and not tower_only:
        return source
    with ProjectArchive(source) as archive:
        changes = {context.graph.main_path: _tower_only_model(context, archive, plate_id)} if tower_only else {}
        config_path = 'Metadata/model_settings.config'
        if context.adapter_id == 'anycubic_slicer_next' and config_path in archive.names:
            config = archive.read(config_path, metadata=True)
            original = config
            plates = parse_xml(config).findall('plate')
            for index, plate in reversed(tuple(enumerate(plates))):
                names = [node for node in plate.findall('metadata') if node.get('key') == 'plater_name' and node.get('value')]
                if names:
                    for node in names:
                        node.set('value', '')
                    first, last, _, _ = xml_span(config, ('config', 'plate'), index)
                    config = config[:first] + ET.tostring(plate, encoding='utf-8') + config[last:]
            if config != original:
                selected_name = dict(context.plate(plate_id).metadata).get('plater_name', '')
                changes.update(_freeze_metadata(archive, config_path, config, selected_name))
        if not changes:
            return source
        target = workspace.child('cli-project.3mf')
        with zipfile.ZipFile(target, 'x', zipfile.ZIP_DEFLATED) as output:
            for name in archive.names:
                if name in changes:
                    output.writestr(name, changes[name])
                else:
                    with output.open(name, 'w', force_zip64=True) as stream:
                        for block in archive.iter_bytes(name):
                            stream.write(block)
        return target
