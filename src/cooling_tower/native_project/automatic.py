"""Native-only feedback loop: immutable basis → append → jointly slice → verify."""
from __future__ import annotations

from dataclasses import dataclass, replace
from bisect import bisect_left, bisect_right
from enum import Enum
import math
from threading import Event
import time

from cooling_tower.calibration.gcode_integration import parse_bed_geometry
from cooling_tower.models.layer_ranges import excluded_layer_indices
from cooling_tower.native_project.adjust import adjust_radius_profile, joint_growth_scale
from cooling_tower.native_project.compose import append_tower
from cooling_tower.native_project.options import NativeCalibrationOptions
from cooling_tower.native_project.session import NativePreparedResult, NativeProjectSession, NativeSliceError, check_cancel
from cooling_tower.native_project.print_space import NativePrintSpace
from cooling_tower.native_project.settings import NativeGenerationSettings, effective_generation_settings
from cooling_tower.native_project.layer_profile import object_geometry_layers, tower_geometry_height
from cooling_tower.protected_io import OwnedWorkspace
from cooling_tower.tower.mesh_generator import TowerMeshConfig, configured_mesh_segments, generate_solid_tower_mesh
from cooling_tower.tower.profile import TowerProfileConfig, build_tower_radius_profile
from cooling_tower.tower.solid_profile import build_solid_tower_profile, validate_solid_settings


class NativeAutomaticState(str, Enum):
    CONVERGED = 'converged'
    LIMIT_REACHED = 'limit_reached'
    NO_TOWER_NEEDED = 'no_tower_needed'


@dataclass(frozen=True, slots=True)
class NativeIteration:
    number: int
    minimum_combined_time_s: float
    maximum_deficit_s: float
    maximum_radius_mm: float
    layer_count: int


@dataclass(frozen=True, slots=True)
class NativeAutomaticResult:
    state: NativeAutomaticState
    prepared: NativePreparedResult | None
    iterations: tuple[NativeIteration, ...]
    settings: NativeGenerationSettings
    message: str
    tower_center_mm: tuple[float, float] | None
    tower_radius_mm: float
    base_width_mm: float | None = None
    circle_segments: int | None = None

    def close(self):
        if self.prepared:
            self.prepared.close()


def _combined_times(source: NativePreparedResult, candidate: NativePreparedResult) -> dict[int, float]:
    layers = candidate.analysis.layers
    heights = [layer.z_mm for layer in layers]
    result = {}
    for original in source.analysis.layers:
        matching = layers[bisect_left(heights, original.z_mm - 1e-4):bisect_right(heights, original.z_mm + 1e-4)]
        if len(matching) != 1:
            raise NativeSliceError('Die gemeinsam geslicten Schichten lassen sich nicht eindeutig den ursprünglichen Druckschichten zuordnen.')
        result[original.index] = matching[0].total_time_s
    return result


def _validate_tower(candidate: NativePreparedResult, source: NativePreparedResult, center, radius,
                    object_layers):
    # The reserved circle is disjoint from exact original toolpath bounds plus
    # physical extrusion width. Sampled preview paths are not a success
    # oracle: inspect every actual deposition move in the tower region.
    from cooling_tower.gcode.parser import MachineStateTracker, Movement, iter_parsed_gcode_lines
    if candidate.analysis.maximum_print_z_mm > source.analysis.maximum_print_z_mm + 1e-4:
        raise NativeSliceError('Der gemeinsam geslicte Turm überschreitet die ursprüngliche Druckhöhe.')
    tracker = MachineStateTracker()
    role = ''
    wipe = [math.inf, -math.inf, math.inf, -math.inf]
    counts = {layer.index: 0 for layer in candidate.analysis.layers}
    layers = candidate.analysis.layers
    index = 0
    for parsed in iter_parsed_gcode_lines(candidate.gcode_path):
        comment = (parsed.comment or '').strip().casefold()
        if comment.startswith(('type:', 'feature:')):
            role = comment.partition(':')[2].strip()
        event = tracker.process_line(parsed)
        if not isinstance(event, Movement) or event.category != 'deposition' or event.delta_e <= 0:
            continue
        while index + 1 < len(layers) and parsed.number > layers[index].end_line:
            index += 1
        if not (layers[index].first_deposition_line <= parsed.number <= layers[index].end_line):
            continue
        if role in {'prime tower', 'wipe tower'}:
            from cooling_tower.native_project.path_bounds import movement_bounds
            for axis, value in enumerate(movement_bounds(event)):
                wipe[axis] = (min if axis % 2 == 0 else max)(wipe[axis], value)
            continue
        distance = max(math.hypot(event.start_x - center[0], event.start_y - center[1]),
                       math.hypot(event.end_x - center[0], event.end_y - center[1]))
        if distance <= radius + max(candidate.context.nozzle_diameters):
            counts[layers[index].index] += 1
    if not any(counts.values()):
        raise NativeSliceError('Der gemeinsame Druck-G-Code enthält keine nachgewiesenen Turmbahnen an der vorgesehenen Position.')
    if math.isfinite(wipe[0]):
        dx = max(wipe[0]-center[0], 0., center[0]-wipe[1])
        dy = max(wipe[2]-center[1], 0., center[1]-wipe[3])
        if math.hypot(dx, dy) <= radius + max(candidate.context.nozzle_diameters):
            raise NativeSliceError('Der gemeinsam geslicte Wipe Tower überschneidet die Kühlturmfläche.')
    # The tower follows object layers. Independently scheduled support-only
    # intervals remain part of the combined time check, without inventing
    # physically unprintable tower layers between adjacent object heights.
    for original in source.analysis.layers:
        if original.index not in object_layers:
            continue
        match = next(layer for layer in layers if abs(layer.z_mm - original.z_mm) < 1e-4)
        if not counts[match.index]:
            raise NativeSliceError('Auf mindestens einer ursprünglichen Schicht fehlen gemeinsam geslicte Turmbahnen.')


class NativeAutomaticService:
    def run(self, session: NativeProjectSession, prepared: NativePreparedResult,
            settings: NativeGenerationSettings, *, options: NativeCalibrationOptions | None = None,
            cancellation_event: Event | None = None, progress=None, force_tower: bool = False) -> NativeAutomaticResult:
        settings = effective_generation_settings(settings, session.context)
        options = options or NativeCalibrationOptions(time_tolerance_s=settings.layer_time_tolerance_s)
        validate_solid_settings(settings)
        if settings.simulate_source_supports:
            raise ValueError('Die nativen Originalobjekte behalten ihre eingebetteten Supporteinstellungen.')
        if prepared.context is not session.context or prepared.composed is not None:
            raise NativeSliceError('Die native Kalibrierung benötigt den unveränderten Ausgangsslice dieser Projektsitzung.')
        prepared.verify()
        geometry_layers = object_geometry_layers(session.context, prepared.gcode_path, prepared.analysis.layers)
        object_layers = frozenset(layer.index for layer in geometry_layers)
        if not object_layers:
            raise NativeSliceError('Die Druckplatte enthält keine eindeutig erkennbaren Modellschichten.')
        object_heights = tuple(layer.z_mm for layer in geometry_layers)
        model_height = tower_geometry_height(session.context, prepared.plate_id, geometry_layers)
        # The mesh builder ends at its last geometry record. Native adaptive
        # slicing can round the last printed Z below the original model top;
        # retain that top without changing the measured print-layer schedule.
        previous_z = geometry_layers[-2].z_mm if len(geometry_layers) > 1 else 0.
        profile_layers = geometry_layers[:-1] + (replace(geometry_layers[-1],
            z_mm=model_height, height_mm=model_height-previous_z),)
        excluded = excluded_layer_indices(prepared.analysis.layers, settings.excluded_layer_ranges)
        selected = tuple(layer for layer in prepared.analysis.layers if layer.index not in excluded)
        if not selected:
            raise NativeSliceError('Mindestens eine Druckschicht muss für den automatischen Turm ausgewählt bleiben.')
        if not force_tower and all(layer.total_time_s + options.time_tolerance_s >= settings.target_layer_time_s for layer in selected):
            return NativeAutomaticResult(NativeAutomaticState.NO_TOWER_NEEDED, None, (), settings,
                'Alle gewählten Schichten erreichen die Zielzeit bereits ohne Turm.', None, 0.)
        profile = build_tower_radius_profile(profile_layers, TowerProfileConfig(
            settings.target_layer_time_s, settings.minimum_outer_radius_mm, settings.maximum_outer_radius_mm,
            settings.local_reference_window, excluded))
        bed = parse_bed_geometry(session.context.settings.as_dict())
        if bed is None:
            raise NativeSliceError('Die native Druckbettkontur konnte nicht für eine sichere Turmposition verwendet werden.')
        space = NativePrintSpace.capture(prepared, bed)
        center = None
        best_geometry = (None,None)
        started, best, best_score, best_radius, best_center, records, history = time.monotonic(), None, math.inf, 0., None, [], {}
        try:
            for number in range(1, options.maximum_iterations + 1):
                check_cancel(cancellation_event)
                remaining = options.maximum_runtime_s - (time.monotonic() - started)
                if remaining <= 0:
                    break
                if progress:
                    progress(number, options.maximum_iterations, 'Turm wird ergänzt und gemeinsam geslict')
                solid = build_solid_tower_profile(profile, settings, object_height_mm=model_height,
                                                  allow_wide_base=True)
                radius = max(point.radius_mm for point in solid.points)
                placement = space.place(bed, radius, clearance=settings.minimum_object_tower_distance_mm,
                                        edge_clearance=options.bed_edge_clearance_mm)
                center = placement.center_x_mm, placement.center_y_mm
                segments = configured_mesh_segments(solid, settings)
                mesh = generate_solid_tower_mesh(solid, TowerMeshConfig(segments))
                with OwnedWorkspace(prefix='nc_') as composed_work:
                    project = append_tower(session.context, prepared.plate_id, mesh, workspace=composed_work,
                        center_mm=center, full_infill=settings.simulate_full_tower_infill,
                        supports_disabled=settings.simulate_tower_without_supports,
                        layer_print_z=object_heights, filament=space.filament)
                    candidate = session.slice(prepared.installation, prepared.plate_id, composed=project,
                        cancellation_event=cancellation_event, timeout_s=min(remaining, options.timeout_per_slice_s))
                try:
                    combined = _combined_times(prepared, candidate)
                    _validate_tower(candidate, prepared, center, radius, object_layers)
                    minimum = min(combined[layer.index] for layer in selected)
                    deficit = max(0., settings.target_layer_time_s - minimum)
                    records.append(NativeIteration(number, minimum, deficit, radius, candidate.analysis.layer_count))
                    if progress:
                        progress(number, options.maximum_iterations, f'Gemeinsamer Slice geprüft: kleinste Schichtzeit {minimum:.2f} s')
                    # Prefer a target-reaching result, then reduce its radius;
                    # an unreachable target retains the least deficit observed.
                    score = deficit if deficit > options.time_tolerance_s else -1. + radius / (1000. * max(radius, settings.maximum_outer_radius_mm))
                    if best is None or score < best_score:
                        if best:
                            best.close()
                        best, best_score, best_radius = candidate, score, radius
                        best_center = center
                        best_geometry = (solid.base_outer_radius_mm*2,segments)
                    if deficit <= options.time_tolerance_s:
                        if candidate is not best:
                            candidate.close()
                        return NativeAutomaticResult(NativeAutomaticState.CONVERGED, best, tuple(records), settings,
                            'Die gemeinsam geslicten gewählten Schichten erreichen die Zielzeit innerhalb der Toleranz.', best_center, best_radius,
                            base_width_mm=best_geometry[0], circle_segments=best_geometry[1])
                    added = {layer.index: max(0., combined[layer.index] - layer.total_time_s) for layer in prepared.analysis.layers}
                    realized = {layer.index: layer.outer_radius_mm for layer in solid.layers}
                    for index, seconds in added.items():
                        history.setdefault(index, []).append((realized.get(index, radius), seconds))
                    profile, change = adjust_radius_profile(profile, prepared.analysis.layers, added,
                        target_time_s=settings.target_layer_time_s, realized_outer_radii_mm=realized,
                        measurement_history=history, combined_layer_times_s=combined,
                        coupled_radius_scale=joint_growth_scale(
                            {layer.index: combined[layer.index] for layer in selected},
                            target_time_s=settings.target_layer_time_s, config=options), config=options)
                    if candidate is not best:
                        candidate.close()
                    if change < .01:
                        break
                except BaseException:
                    if candidate is not best:
                        candidate.close()
                    raise
            if best is None:
                raise NativeSliceError('Das Laufzeitlimit wurde vor einem vollständig geprüften gemeinsamen Slice erreicht.')
            return NativeAutomaticResult(NativeAutomaticState.LIMIT_REACHED, best, tuple(records), settings,
                'Die Zielzeit wurde innerhalb der Geometrie- oder Durchlaufgrenzen nicht auf allen gewählten Schichten erreicht.', best_center,
                best_radius, base_width_mm=best_geometry[0], circle_segments=best_geometry[1])
        except BaseException:
            if best:
                best.close()
            raise
