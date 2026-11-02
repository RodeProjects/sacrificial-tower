"""Immutable, content-derived native project context; no installed presets."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import math
from pathlib import Path
import re

from cooling_tower.protected_io import InputSnapshot, OwnedWorkspace
from cooling_tower.native_project.archive import ProjectArchive, ProjectArchiveError, parse_xml
from cooling_tower.native_project.graph import ProjectGraph, NativeGraphError, UnsupportedProjectExtension, read_graph


class ProjectProblem(str, Enum):
    DAMAGED = 'damaged'
    INCOMPLETE = 'incomplete'
    UNSUPPORTED = 'unsupported'
    UNSAFE = 'unsafe'
    MISSING_SLICER = 'missing_slicer'


class NativeProjectError(ValueError):
    def __init__(self, problem: ProjectProblem, message: str):
        super().__init__(message)
        self.problem = problem


@dataclass(frozen=True, slots=True)
class NativePlate:
    identifier: str
    ordinal: int
    name: str
    build_indices: tuple[int, ...]
    thumbnail: str | None
    metadata: tuple[tuple[str, str], ...]

    @property
    def object_count(self) -> int:
        return len(self.build_indices)


@dataclass(frozen=True, slots=True)
class NativeSettings:
    # JSON values stay serialized: consumers cannot mutate the authoritative
    # project settings through an accidentally shared dictionary/list.
    values: tuple[tuple[str, str], ...]

    def get(self, key: str, default=None):
        for name, value in self.values:
            if name == key:
                return json.loads(value)
        return default

    def as_dict(self) -> dict:
        return {name: json.loads(value) for name, value in self.values}


@dataclass(frozen=True, slots=True)
class NativeProjectContext:
    snapshot: InputSnapshot
    graph: ProjectGraph
    adapter_id: str
    producer_version: str
    settings: NativeSettings
    plates: tuple[NativePlate, ...]
    printer: str
    nozzle_diameters: tuple[float, ...]
    materials: tuple[str, ...]
    bed_polygon: tuple[tuple[float, float], ...]
    printable_height: float
    layer_height: float
    initial_layer_height: float

    def plate(self, identifier: str) -> NativePlate:
        for plate in self.plates:
            if plate.identifier == identifier:
                return plate
        raise NativeProjectError(ProjectProblem.INCOMPLETE, 'Die ausgewählte Druckplatte gehört nicht zum importierten Projekt.')

    def binding(self, plate_id: str, *, engine_version: str, options: dict | None = None) -> str:
        plate = self.plate(plate_id)
        payload = [1, self.snapshot.sha256, self.adapter_id, self.producer_version,
                   plate.identifier, plate.ordinal, self.settings.values, engine_version, options or {}]
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise NativeProjectError(ProjectProblem.DAMAGED, 'Eine native Projekteinstellung ist doppelt vergeben.')
        result[key] = value
    return result


def _number(value, description: str, *, positive: bool = True) -> float:
    try:
        if isinstance(value, bool):
            raise ValueError()
        number = float(value)
        if not math.isfinite(number) or (positive and number <= 0):
            raise ValueError()
        return number
    except (TypeError, ValueError, OverflowError) as error:
        raise NativeProjectError(ProjectProblem.INCOMPLETE, f'{description} fehlt oder ist ungültig.') from error


def _strings(value, *, separator=';') -> tuple[str, ...]:
    if isinstance(value, list):
        if not all(isinstance(item, str) for item in value):
            raise NativeProjectError(ProjectProblem.DAMAGED, 'Eine native Einstellungsliste enthält ungültige Werte.')
        return tuple(value)
    return tuple(value.split(separator)) if isinstance(value, str) else ()


def _has_postprocessing(value) -> bool:
    if isinstance(value, list):
        if not all(isinstance(item, str) for item in value):
            raise NativeProjectError(ProjectProblem.DAMAGED, 'Die native Skriptliste enthält ungültige Werte.')
        return any(item.strip() for item in value)
    if not isinstance(value, str):
        raise NativeProjectError(ProjectProblem.DAMAGED, 'Die native Skriptliste ist ungültig.')
    # Prusa's coStrings serializes a vector containing empty strings as quoted
    # empty items. Those do not name an external command.
    return bool(value.strip()) and re.fullmatch(r'\s*""\s*(?:;\s*""\s*)*', value) is None


def _metadata(element) -> dict[str, str]:
    result = {}
    for child in element.findall('metadata'):
        key, value = child.get('key'), child.get('value')
        if key is None or value is None:
            continue
        if key in result:
            raise NativeProjectError(ProjectProblem.DAMAGED, 'Eine native Objekt- oder Platteneinstellung ist doppelt vergeben.')
        result[key] = value
    return result


def _prusa_settings(data: bytes) -> dict:
    result = {}
    try:
        lines = data.decode('utf-8-sig').splitlines()
    except UnicodeError as error:
        raise NativeProjectError(ProjectProblem.DAMAGED, 'Die eingebetteten Prusa-Projekteinstellungen sind beschädigt.') from error
    for line in lines:
        # Native config is a comment-style serialization, not an INI profile.
        match = re.fullmatch(r';\s*([a-zA-Z][a-zA-Z0-9_]*)\s*=\s*(.*)', line)
        if match:
            key, value = match.groups()
            if key in result:
                raise NativeProjectError(ProjectProblem.DAMAGED, 'Eine Prusa-Projekteinstellung ist doppelt vergeben.')
            result[key] = value
    return result


def _validate_layer_ranges(archive: ProjectArchive, prusa: bool) -> None:
    path = ('Metadata/Prusa_Slicer_layer_config_ranges.xml' if prusa
            else 'Metadata/layer_config_ranges.xml')
    if path not in archive.names:
        return
    root = parse_xml(archive.read(path, metadata=True))
    if root.tag != 'objects':
        raise NativeProjectError(ProjectProblem.DAMAGED, 'Die native Höhenbereichsdatei besitzt eine ungültige Struktur.')
    for item in root.findall('object/range'):
        values = {option.get('opt_key'): option.text for option in item.findall('option')}
        # The native Slicing reader dereferences this option directly. It is
        # written even for a range that changes only walls or infill.
        _number(values.get('layer_height'), 'Die Schichthöhe eines nativen Höhenbereichs')
        low = _number(item.get('min_z'), 'Die Untergrenze eines nativen Höhenbereichs', positive=False)
        high = _number(item.get('max_z'), 'Die Obergrenze eines nativen Höhenbereichs', positive=False)
        if low < 0 or high <= low:
            raise NativeProjectError(ProjectProblem.INCOMPLETE, 'Ein nativer Höhenbereich besitzt ungültige Grenzen.')


def _identify(graph: ProjectGraph, settings: dict, prusa: bool) -> tuple[str, str]:
    metadata = dict(graph.main.metadata)
    application = metadata.get('Application', '')
    if prusa and application.startswith('PrusaSlicer-'):
        return 'prusa_slicer', application.removeprefix('PrusaSlicer-')
    if prusa:
        raise NativeProjectError(ProjectProblem.UNSUPPORTED, 'Die native Prusa-Erzeugerkennung ist nicht eindeutig.')
    if 'OrcaSlicer' in metadata:
        return 'orca_slicer', metadata['OrcaSlicer']
    if application.startswith('OrcaSlicer-'):
        return 'orca_slicer', application.removeprefix('OrcaSlicer-')
    if settings.get('app_full_name') == 'AnycubicSlicerNext':
        return 'anycubic_slicer_next', str(settings.get('app_version') or settings.get('version') or '')
    if application.startswith(('AnycubicSlicerNext-', 'AnycubicSlicer-')):
        return 'anycubic_slicer_next', application.split('-', 1)[1]
    # Older Anycubic releases retained the Bambu Application marker. Their
    # native ACE/nozzle-material configuration is distinguishable in content;
    # neither a printer/profile name nor a locally installed preset is used.
    anycubic_fields = {'fan_cooling_layer_time_BRASS', 'fan_cooling_layer_time_HS',
                      'nozzle_temperature_BRASS', 'nozzle_temperature_HS',
                      'flush_volumes_chan_multipliers'}
    if application.startswith('BambuStudio-') and anycubic_fields <= settings.keys():
        return 'anycubic_slicer_next', str(settings.get('version') or application.split('-', 1)[1])
    if application.startswith('BambuStudio-'):
        return 'bambu_studio', application.removeprefix('BambuStudio-')
    raise NativeProjectError(ProjectProblem.UNSUPPORTED, 'Der erzeugende Slicer lässt sich aus dem nativen Projekt nicht zuverlässig zuordnen.')


def _plates(archive: ProjectArchive, graph: ProjectGraph, prusa: bool) -> tuple[NativePlate, ...]:
    filename = 'Metadata/Slic3r_PE_model.config' if prusa else 'Metadata/model_settings.config'
    root = archive.xml(filename) if filename in archive.names else None
    if root is not None:
        for node in root.iter():
            if node.tag in {'option', 'metadata'} and node.get('key', node.get('opt_key', '')).casefold() == 'post_process' and _has_postprocessing(node.get('value', node.text or '')):
                raise NativeProjectError(ProjectProblem.UNSAFE, 'Das Projekt enthält ein externes Nachbearbeitungsskript. Dieses muss vor dem automatischen Verarbeiten aus einer eigenen Projektkopie entfernt werden.')
    plate_nodes = root.findall('plate') if root is not None and not prusa else []
    if not plate_nodes:
        return (NativePlate('1', 1, 'Druckplatte 1', tuple(i for i, item in enumerate(graph.main.build) if item.printable), None, ()),)
    occurrences: dict[int, list[int]] = {}
    for index, item in enumerate(graph.main.build):
        occurrences.setdefault(item.object_id, []).append(index)
    identifiers, assigned, plates = set(), set(), []
    for ordinal, node in enumerate(plate_nodes, 1):
        values = _metadata(node)
        identifier = values.get('plater_id')
        if identifier is None or identifier in identifiers:
            raise NativeProjectError(ProjectProblem.DAMAGED, 'Die nativen Druckplattenkennungen fehlen oder sind mehrdeutig.')
        identifiers.add(identifier)
        indices = []
        for instance in node.findall('model_instance'):
            entry = _metadata(instance)
            try:
                object_id, instance_id = int(entry['object_id']), int(entry['instance_id'])
                if instance_id < 0:
                    raise ValueError()
                index = occurrences[object_id][instance_id]
            except (KeyError, IndexError, ValueError) as error:
                raise NativeProjectError(ProjectProblem.DAMAGED, 'Eine Druckplatte verweist auf eine fehlende Objektinstanz.') from error
            if index in assigned:
                raise NativeProjectError(ProjectProblem.DAMAGED, 'Eine Objektinstanz ist mehreren Druckplatten zugeordnet.')
            assigned.add(index)
            if graph.main.build[index].printable:
                indices.append(index)
        preview = values.get('thumbnail_file')
        thumbnail = archive.relationship_target('_rels/.rels', preview, require_exists=False) if preview else None
        if thumbnail not in archive.names:
            thumbnail = None
        plates.append(NativePlate(identifier, ordinal, values.get('plater_name') or f'Druckplatte {ordinal}',
                                  tuple(indices), thumbnail, tuple(values.items())))
    return tuple(plates)


def load_context(snapshot: InputSnapshot) -> NativeProjectContext:
    snapshot.verify()
    try:
        with ProjectArchive(snapshot.path) as archive:
            archive.check_relationships()
            graph = read_graph(archive)
            prusa = 'Metadata/Slic3r_PE.config' in archive.names
            if prusa:
                values = _prusa_settings(archive.read('Metadata/Slic3r_PE.config', metadata=True))
            elif 'Metadata/project_settings.config' in archive.names:
                try:
                    values = json.loads(archive.read('Metadata/project_settings.config', metadata=True), object_pairs_hook=_json_object,
                                        parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                except (UnicodeError, ValueError) as error:
                    if isinstance(error, NativeProjectError):
                        raise
                    raise NativeProjectError(ProjectProblem.DAMAGED, 'Die nativen Projekteinstellungen sind kein gültiges JSON.') from error
                if not isinstance(values, dict):
                    raise NativeProjectError(ProjectProblem.DAMAGED, 'Die native Projektkonfiguration ist ungültig.')
            else:
                raise NativeProjectError(ProjectProblem.INCOMPLETE, 'Die Datei enthält Geometrie, aber keine vollständigen nativen Druckprojekteinstellungen. Im Slicer als Projekt speichern.')
            adapter, version = _identify(graph, values, prusa)
            _validate_layer_ranges(archive, prusa)
            if _has_postprocessing(values.get('post_process', '')):
                raise NativeProjectError(ProjectProblem.UNSAFE, 'Das Projekt enthält ein externes Nachbearbeitungsskript. Dieses muss vor dem automatischen Verarbeiten aus einer eigenen Projektkopie entfernt werden.')
            if str(values.get('printer_technology', 'FFF')).casefold() not in {'fff', 'filament'}:
                raise NativeProjectError(ProjectProblem.UNSUPPORTED, 'Der automatische Turm benötigt ein natives Filament-Druckprojekt.')
            printer = values.get('printer_model')
            if not isinstance(printer, str):
                raise NativeProjectError(ProjectProblem.INCOMPLETE, 'Die eingebettete Druckerkennung fehlt.')
            if not printer.strip():
                label = values.get('printer_settings_id')
                printer = label.strip() if isinstance(label, str) and label.strip() else 'Benutzerdefinierter Drucker'
            nozzles = _strings(values.get('nozzle_diameter'), separator=',')
            if not nozzles:
                raise NativeProjectError(ProjectProblem.INCOMPLETE, 'Die eingebetteten Düsendurchmesser fehlen.')
            diameters = tuple(_number(item, 'Der Düsendurchmesser') for item in nozzles)
            materials = _strings(values.get('filament_type'))
            if not materials or any(not item.strip() for item in materials):
                raise NativeProjectError(ProjectProblem.INCOMPLETE, 'Die eingebetteten Materialangaben fehlen.')
            area = values.get('bed_shape' if prusa else 'printable_area')
            vertices = _strings(area, separator=',')
            polygon = []
            for point in vertices:
                parts = point.split('x')
                if len(parts) != 2:
                    raise NativeProjectError(ProjectProblem.INCOMPLETE, 'Die eingebettete Druckbettkontur ist ungültig.')
                polygon.append(tuple(_number(part, 'Die Druckbettkoordinate', positive=False) for part in parts))
            if len(polygon) < 3:
                raise NativeProjectError(ProjectProblem.INCOMPLETE, 'Die eingebettete Druckbettkontur fehlt.')
            plates = _plates(archive, graph, prusa)
            archive.verify_remaining_members()
            layer_height = _number(values.get('layer_height'), 'Die Schichthöhe')
            initial = values.get('first_layer_height' if prusa else 'initial_layer_print_height')
            if prusa and isinstance(initial, str) and initial.endswith('%'):
                # Prusa PrintConfig's ratio_over is layer_height (not nozzle).
                initial = _number(initial[:-1], 'Die erste Schichthöhe') / 100 * layer_height
            return NativeProjectContext(snapshot, graph, adapter, version,
                NativeSettings(tuple((key, json.dumps(value, ensure_ascii=True, allow_nan=False)) for key, value in sorted(values.items()))),
                plates, printer, diameters, materials, tuple(polygon),
                _number(values.get('max_print_height' if prusa else 'printable_height'), 'Die Druckhöhe'),
                layer_height, _number(initial, 'Die erste Schichthöhe'))
    except UnsupportedProjectExtension as error:
        raise NativeProjectError(ProjectProblem.UNSUPPORTED, str(error)) from error
    except (ProjectArchiveError, NativeGraphError) as error:
        raise NativeProjectError(ProjectProblem.DAMAGED, str(error)) from error
