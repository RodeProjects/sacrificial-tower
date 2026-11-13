"""Native-only feedback loop: immutable basis → append → jointly slice → verify."""
from __future__ import annotations

from dataclasses import dataclass, replace
from bisect import bisect_left, bisect_right
from collections import deque
from enum import Enum
import math
from threading import Event
import time

from cooling_tower.calibration.gcode_integration import parse_bed_geometry
from cooling_tower.gcode.parser import MachineStateTracker, Movement, iter_parsed_gcode_lines
from cooling_tower.models.analysis import GCodeAnalysisSnapshot
from cooling_tower.models.layer_ranges import excluded_layer_indices
from cooling_tower.native_project.adjust import adjust_radius_profile, joint_radius_scale
from cooling_tower.native_project.compose import append_tower
from cooling_tower.native_project.context import NativeProjectContext
from cooling_tower.native_project.options import NativeCalibrationOptions
from cooling_tower.native_project.path_bounds import movement_bounds
from cooling_tower.native_project.session import (
    NativeOperationCancelled, NativePreparedResult, NativeProjectSession, NativeSliceError, check_cancel,
)
from cooling_tower.native_project.print_space import NativePrintSpace
from cooling_tower.native_project.settings import (
    NativeGenerationSettings, effective_generation_settings, embedded_shell_layers,
)
from cooling_tower.native_project.layer_profile import object_geometry_layers, tower_geometry_height
from cooling_tower.native_project.top_layer import SupportFootprint, TopLayerShape, extend_mesh, extrusion_segments
from cooling_tower.native_project.toolpath import DepositionToolpathAnalysis
from cooling_tower.protected_io import OwnedWorkspace
from cooling_tower.tower.mesh_generator import TowerMeshConfig, configured_mesh_segments, generate_solid_tower_mesh
from cooling_tower.tower.profile import TowerProfileConfig, TowerRadiusProfile, build_tower_radius_profile
from cooling_tower.tower.solid_profile import build_solid_tower_profile, validate_solid_settings
from cooling_tower.tower.spline_profile import angle_to_radial_slope


class NativeAutomaticState(str, Enum):
    CONVERGED = 'converged'
    LIMIT_REACHED = 'limit_reached'
    NO_TOWER_NEEDED = 'no_tower_needed'
    PAUSED = 'paused'


@dataclass(frozen=True, slots=True)
class NativeIteration:
    number: int
    minimum_combined_time_s: float
    maximum_deficit_s: float
    maximum_radius_mm: float
    layer_count: int


@dataclass(frozen=True, slots=True)
class NativeBestCandidate:
    number: int
    minimum_layer_time_s: float
    target_layer_time_s: float


@dataclass(frozen=True, slots=True)
class NativeCalibrationCheckpoint:
    """Continuation after the last completely verified joint slice."""
    source: NativePreparedResult
    options: NativeCalibrationOptions
    profile: TowerRadiusProfile
    history: tuple[tuple[int, tuple[tuple[float, float], ...]], ...]
    best_score: tuple[float, float, float]
    active_runtime_s: float


@dataclass(frozen=True, slots=True)
class _NativeSliceStop:
    cancel: Event | None
    accept: Event

    def is_set(self) -> bool:
        return self.accept.is_set() or (self.cancel is not None and self.cancel.is_set())


@dataclass(frozen=True, slots=True)
class NativeSlicePreview:
    """Read-only display data that outlives a discarded slice workspace."""
    context: NativeProjectContext
    analysis: GCodeAnalysisSnapshot
    toolpaths: DepositionToolpathAnalysis
    tower_center_mm: tuple[float, float]
    tower_radius_mm: float
    tower_only: bool
    estimated_times: tuple[float, ...] = ()
    best_candidate: NativeBestCandidate | None = None


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
    separate_iterations: int = 0
    extra_layer_z_mm: float | None = None
    minimum_layer_time_s: float | None = None
    best_iteration: int | None = None
    continuation: NativeCalibrationCheckpoint | None = None

    @property
    def best_candidate(self) -> NativeBestCandidate | None:
        if self.best_iteration is None or self.minimum_layer_time_s is None:
            return None
        return NativeBestCandidate(self.best_iteration, self.minimum_layer_time_s,
                                   self.settings.target_layer_time_s)

    def close(self):
        if self.prepared:
            self.prepared.close()


def _matched_layers(source, candidate):
    layers = candidate.analysis.layers
    heights = [layer.z_mm for layer in layers]
    result = {}
    for original in source.analysis.layers:
        matching = layers[bisect_left(heights, original.z_mm - 1e-4):bisect_right(heights, original.z_mm + 1e-4)]
        if len(matching) == 1:
            result[original.index] = matching[0]
    return result


def _tower_paths(candidate, center, radius, *, capture=(), tower_only=False, cancellation_event=None):
    """Verify real deposition moves, independent of the sampled preview."""
    tracker = MachineStateTracker()
    role = ''
    width = None
    nozzle = max(candidate.context.nozzle_diameters)
    wipe = [math.inf, -math.inf, math.inf, -math.inf]
    printed = set()
    paths = {index: [] for index in capture}
    layers = candidate.analysis.layers
    index = 0
    for parsed in iter_parsed_gcode_lines(candidate.gcode_path):
        if parsed.number % 4096 == 0:
            check_cancel(cancellation_event)
        comment = (parsed.comment or '').strip().casefold()
        if comment.startswith(('type:', 'feature:')):
            role = comment.partition(':')[2].strip()
        if paths and comment.startswith(('width:', 'line_width:')):
            try:
                value = float(comment.partition(':')[2])
                width = value if math.isfinite(value) and value > 0 else None
            except ValueError:
                width = None
        event = tracker.process_line(parsed)
        if not isinstance(event, Movement) or event.category != 'deposition' or event.delta_e <= 0:
            continue
        while index + 1 < len(layers) and parsed.number > layers[index].end_line:
            index += 1
        if not (layers[index].first_deposition_line <= parsed.number <= layers[index].end_line):
            continue
        if role in {'prime tower', 'wipe tower'}:
            for axis, value in enumerate(movement_bounds(event)):
                wipe[axis] = (min if axis % 2 == 0 else max)(wipe[axis], value)
            continue
        if role in {'skirt', 'brim', 'skirt/brim', 'custom', 'custom gcode'}:
            continue
        distance = max(math.hypot(event.start_x - center[0], event.start_y - center[1]),
                       math.hypot(event.end_x - center[0], event.end_y - center[1]))
        if distance <= radius + nozzle:
            layer_index = layers[index].index
            if 'support' not in role:
                printed.add(layer_index)
                if layer_index in paths:
                    paths[layer_index].extend(extrusion_segments(event, width or nozzle))
        elif tower_only:
            raise NativeSliceError('Der getrennte Slice enthält Bahnen außerhalb der reservierten Turmfläche.')
    if not printed:
        raise NativeSliceError('Der gemeinsame Druck-G-Code enthält keine nachgewiesenen Turmbahnen an der vorgesehenen Position.')
    if math.isfinite(wipe[0]):
        dx = max(wipe[0]-center[0], 0., center[0]-wipe[1])
        dy = max(wipe[2]-center[1], 0., center[1]-wipe[3])
        if math.hypot(dx, dy) <= radius + nozzle:
            raise NativeSliceError('Der gemeinsam geslicte Wipe Tower überschneidet die Kühlturmfläche.')
    return printed, paths


def _solid_foot_layers(solid, settings, nozzle):
    if not settings.concave_base or settings.simulate_full_tower_infill:
        return 0
    # A contracting perimeter has support from the preceding walls while the
    # inward shift still lies within their combined deposited width. Keep the
    # foot dense through the last critical transition.
    slope = 1.0 if settings.automatic_contraction_angle else angle_to_radial_slope(
        settings.maximum_contraction_angle_deg)
    supported_shift = nozzle * (settings.tower_wall_count - .5)
    solid_through = 0
    needs_solid = False
    for number, (lower, upper) in enumerate(zip(solid.layers, solid.layers[1:]), 2):
        if lower.z >= solid.base_taper_end_z_mm - 1e-5:
            break
        shift = lower.outer_radius_mm - upper.outer_radius_mm
        if shift > supported_shift:
            needs_solid = True
        if needs_solid and shift > min(supported_shift, slope * (upper.z-lower.z)):
            solid_through = number
    return solid_through


def _shell_overrides(settings, context):
    for surface in ('top', 'bottom'):
        automatic = getattr(settings, f'automatic_{surface}_shell_layers')
        embedded = embedded_shell_layers(context, surface) if automatic else None
        layers = embedded if embedded is not None else getattr(settings, f'{surface}_shell_layers')
        yield surface, layers, embedded is not None


class NativeAutomaticService:
    def run(self, session: NativeProjectSession, prepared: NativePreparedResult,
            settings: NativeGenerationSettings, *, options: NativeCalibrationOptions | None = None,
            cancellation_event: Event | None = None, progress=None, preview=None,
            force_tower: bool = False, acceptance_event: Event | None = None,
            resume: NativeAutomaticResult | None = None) -> NativeAutomaticResult:
        """Take ownership of the seed and return ownership of the best result."""
        owned = resume

        def adopt(result):
            nonlocal owned
            previous, owned = owned, result
            if previous is not None:
                previous.close()

        try:
            return self._run(session, prepared, settings, options=options, cancellation_event=cancellation_event,
                             progress=progress, preview=preview, force_tower=force_tower,
                             acceptance_event=acceptance_event, resume=resume, adopt=adopt)
        except BaseException:
            if owned is not None:
                owned.close()
            raise

    def _run(self, session, prepared, settings, *, options, cancellation_event, progress,
             preview, force_tower, acceptance_event, resume, adopt):
        settings = effective_generation_settings(settings, session.context)
        options = options or NativeCalibrationOptions(time_tolerance_s=settings.layer_time_tolerance_s)
        validate_solid_settings(settings)
        checkpoint = resume.continuation if resume is not None else None
        if resume is not None and (checkpoint is None or checkpoint.source is not prepared
                                   or checkpoint.options != options or resume.settings != settings):
            raise NativeSliceError('Der gespeicherte Durchlauf gehört nicht zu dieser Druckplatte und Konfiguration.')
        check_cancel(cancellation_event)
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
        target = settings.target_layer_time_s
        if checkpoint is None and not (force_tower or settings.extra_top_layer) and all(
                layer.total_time_s + options.time_tolerance_s >= target for layer in selected):
            return NativeAutomaticResult(NativeAutomaticState.NO_TOWER_NEEDED, None, (), settings,
                'Alle gewählten Schichten erreichen die Zielzeit bereits ohne Turm.', None, 0.,
                minimum_layer_time_s=min(layer.total_time_s for layer in selected))
        profile = checkpoint.profile if checkpoint is not None else build_tower_radius_profile(profile_layers, TowerProfileConfig(
            settings.target_layer_time_s, settings.minimum_outer_radius_mm, settings.maximum_outer_radius_mm,
            settings.local_reference_window, excluded))
        bed = parse_bed_geometry(session.context.settings.as_dict())
        if bed is None:
            raise NativeSliceError('Die native Druckbettkontur konnte nicht für eine sichere Turmposition verwendet werden.')
        space = NativePrintSpace.capture(prepared, bed)
        started = time.monotonic()
        previously_active_s = checkpoint.active_runtime_s if checkpoint is not None else 0.
        slice_stop = (_NativeSliceStop(cancellation_event, acceptance_event)
                      if acceptance_event is not None else cancellation_event)

        def remaining():
            return options.maximum_runtime_s - previously_active_s - (time.monotonic() - started)

        def make_geometry(profile):
            solid = build_solid_tower_profile(profile, settings, object_height_mm=model_height,
                                              allow_wide_base=True, concave_base=settings.concave_base)
            radius = max(point.radius_mm for point in solid.points)
            placement = space.place(bed, radius, clearance=settings.minimum_object_tower_distance_mm,
                                    edge_clearance=options.bed_edge_clearance_mm)
            center = placement.center_x_mm, placement.center_y_mm
            segments = configured_mesh_segments(solid, settings)
            return solid, radius, center, generate_solid_tower_mesh(solid, TowerMeshConfig(segments))

        def slice_mesh(solid, center, mesh, *, tower_only=False, extra=False):
            stop = cancellation_event if tower_only else slice_stop
            check_cancel(stop)
            if remaining() <= 0:
                raise NativeSliceError('Das Laufzeitlimit wurde vor dem nächsten Slice erreicht.')
            heights = object_heights + ((object_heights[-1]+geometry_layers[-1].height_mm,) if extra else ())
            foot_layers = _solid_foot_layers(solid, settings, min(session.context.nozzle_diameters))
            foot_top = min(solid.total_height_mm, object_heights[foot_layers-1]) if foot_layers else 0.
            with OwnedWorkspace(prefix='nc_') as composed_work:
                project = append_tower(session.context, prepared.plate_id, mesh, workspace=composed_work,
                    center_mm=center, full_infill=settings.simulate_full_tower_infill,
                    wall_count=None if settings.simulate_full_tower_infill else settings.tower_wall_count,
                    supports_disabled=settings.simulate_tower_without_supports,
                    layer_print_z=heights, filament=space.filament,
                    shell_layers=tuple(_shell_overrides(settings, session.context)),
                    extra_layer_base_z=solid.total_height_mm if extra else None,
                    solid_foot_top_mm=foot_top)
                return session.slice(prepared.installation, prepared.plate_id, composed=project,
                    cancellation_event=stop, timeout_s=min(remaining(), options.timeout_per_slice_s),
                    tower_only=tower_only)

        def read_joint(candidate, center, radius, *, extra=False, capture=()):
            matches = _matched_layers(prepared, candidate)
            if len(matches) != prepared.analysis.layer_count:
                raise NativeSliceError('Die gemeinsam geslicten Schichten lassen sich nicht eindeutig den ursprünglichen Druckschichten zuordnen.')
            layers_above = tuple(layer for layer in candidate.analysis.layers
                if layer.z_mm > prepared.analysis.layers[-1].z_mm + 1e-4)
            if len(layers_above) != int(extra):
                raise NativeSliceError('Der gemeinsame Slice enthält eine unerwartete Anzahl Schichten oberhalb des Modells.')
            extra_layer = layers_above[0] if extra else None
            printed, paths = _tower_paths(candidate, center, radius, capture=capture,
                                          cancellation_event=slice_stop)
            required = {matches[index].index for index in object_layers}
            if extra_layer is not None:
                required.add(extra_layer.index)
            if not required <= printed:
                raise NativeSliceError('Auf mindestens einer erwarteten Schicht fehlen gemeinsam geslicte Turmbahnen.')
            matched = {layer.index for layer in matches.values()}
            additional = tuple(layer.total_time_s for layer in candidate.analysis.layers
                               if layer.index not in matched and layer is not extra_layer)
            return {index: layer.total_time_s for index, layer in matches.items()}, additional, paths

        def add_top_layer(previous_paths, solid, radius, center, mesh):
            nozzle = session.context.nozzle_diameters[min(space.filament-1, len(session.context.nozzle_diameters)-1)]
            outer = solid.points[-1].radius_mm
            footprint = SupportFootprint(previous_paths, center, outer, nozzle)
            cap_radius = settings.minimum_outer_radius_mm
            offset = footprint.nearest_disk(cap_radius, outer, mesh.segment_count, nozzle)
            rim_depth = min(outer, settings.tower_wall_count * nozzle)
            rim = TopLayerShape(outer, inner_radius=outer-rim_depth)
            cap = TopLayerShape(cap_radius, offset) if offset is not None else None
            shapes = deque((rim,) if cap is None or cap == rim else (cap, rim))
            z_top = max(solid.total_height_mm, object_heights[-1]) + geometry_layers[-1].height_mm
            while shapes:
                shape = shapes.popleft()
                extended = extend_mesh(mesh, shape, z_top)
                result = None
                accepted = False
                try:
                    result = slice_mesh(solid, center, extended, extra=True)
                    if len(result.analysis.layers) < 2:
                        raise NativeSliceError('Der zusätzliche Turmlayer fehlt im gemeinsamen Slice.')
                    previous, top = result.analysis.layers[-2:]
                    combined, additional, paths = read_joint(result, center, radius, extra=True,
                        capture=(previous.index, top.index))
                    actual_support = SupportFootprint(paths[previous.index], center, outer, nozzle)
                    if not actual_support.supports(paths[top.index]):
                        if shape is cap:
                            revised_offset = actual_support.nearest_disk(cap_radius, outer, mesh.segment_count, nozzle)
                            if revised_offset is not None and revised_offset != offset:
                                revised = TopLayerShape(cap_radius, revised_offset)
                                if revised != rim:
                                    shapes.appendleft(revised)
                        raise NativeSliceError('Der zusätzliche Turmlayer besitzt im gemeinsamen Slice keine ausreichende Auflage.')
                    accepted = True
                    return result, combined, additional, top.z_mm
                except NativeSliceError:
                    if not shapes:
                        raise
                finally:
                    if result is not None and not accepted:
                        result.close()

        separate_count = resume.separate_iterations if resume is not None else 0
        separate_limit = 0 if checkpoint is not None else options.maximum_separate_iterations
        for number in range(1, separate_limit + 1):
            if remaining() <= 0:
                break
            if progress:
                progress(number, options.maximum_separate_iterations, 'Turm wird getrennt geslict')
            solid, radius, center, mesh = make_geometry(profile)
            try:
                isolated = slice_mesh(solid, center, mesh, tower_only=True)
                try:
                    printed, _ = _tower_paths(isolated, center, radius, tower_only=True,
                                              cancellation_event=cancellation_event)
                    matches = _matched_layers(prepared, isolated)
                    if not all(index in matches and matches[index].index in printed for index in object_layers):
                        raise NativeSliceError('Der getrennte Slice verwendet abweichende Modellschichthöhen.')
                    added = {index: layer.total_time_s for index, layer in matches.items()
                             if index in object_layers}
                    estimate = {layer.index: layer.total_time_s + added.get(layer.index, 0.)
                                for layer in prepared.analysis.layers}
                    separate_count += 1
                    if preview:
                        preview(NativeSlicePreview(isolated.context, isolated.analysis,
                            isolated.toolpaths, center, radius, True,
                            tuple(estimate[layer.index] for layer in prepared.analysis.layers)))
                finally:
                    isolated.close()
            except NativeSliceError as error:
                if progress:
                    progress(number, options.maximum_separate_iterations,
                             f'{error} Kalibrierung wird mit gemeinsamen Slices fortgesetzt.')
                break
            estimated_minimum = min((estimate[index] for index in object_layers - excluded), default=target)
            if abs(estimated_minimum - target) <= options.time_tolerance_s:
                break
            if progress:
                progress(number, options.maximum_separate_iterations,
                         'Getrennter Slice geprüft · Turmgeometrie wird angepasst')
            profile, change = adjust_radius_profile(profile, prepared.analysis.layers, added,
                target_time_s=target,
                realized_outer_radii_mm={layer.index: layer.outer_radius_mm for layer in solid.layers},
                config=options)
            if change < .01:
                break

        best = resume
        best_score = checkpoint.best_score if checkpoint is not None else None
        records = list(resume.iterations) if resume is not None else []
        history = {index: list(samples) for index, samples in checkpoint.history} if checkpoint is not None else {}
        paused = False
        failure = None
        for number in range(len(records) + 1, options.maximum_iterations + 1):
            check_cancel(cancellation_event)
            if remaining() <= 0:
                break
            if best is not None and acceptance_event is not None and acceptance_event.is_set():
                paused = True
                break
            if progress:
                progress(number, options.maximum_iterations, 'Turm wird ergänzt und gemeinsam geslict')
            candidate = None
            try:
                try:
                    solid, radius, center, mesh = make_geometry(profile)
                except ValueError as error:
                    raise NativeSliceError(str(error)) from error
                candidate = slice_mesh(solid, center, mesh)
                last = candidate.analysis.layers[-1]
                capture = (last.index,) if settings.extra_top_layer else ()
                combined, additional, paths = read_joint(candidate, center, radius, capture=capture)
                extra_z = None
                if settings.extra_top_layer:
                    if progress:
                        progress(number, options.maximum_iterations, 'Zusätzlicher Turmlayer wird geprüft')
                    extended, combined, additional, extra_z = add_top_layer(
                        paths[last.index], solid, radius, center, mesh)
                    candidate.close()
                    candidate = extended
                check_cancel(slice_stop)
                measured = tuple(combined[layer.index] for layer in selected) + additional
                minimum = min(measured)
                difference = minimum - target
                deficit = max(0., -difference)
                reached = abs(difference) <= options.time_tolerance_s
                records.append(NativeIteration(number, minimum, deficit, radius, candidate.analysis.layer_count))
                # Break ties using all layer deficits, then tower size.
                score = (abs(difference), sum(max(0., target-seconds) for seconds in measured), radius)
                if best_score is None or score < best_score:
                    best_score = score
                    best = NativeAutomaticResult(NativeAutomaticState.LIMIT_REACHED, candidate, (), settings, '',
                        center, radius, solid.base_outer_radius_mm*2, mesh.segment_count,
                        separate_count, extra_z, minimum, best_iteration=number)
                    adopt(best)
                if preview:
                    preview(NativeSlicePreview(candidate.context, candidate.analysis, candidate.toolpaths,
                                               center, radius, False, best_candidate=best.best_candidate))
                if progress:
                    progress(number, options.maximum_iterations, f'Gemeinsamer Slice geprüft: kleinste Schichtzeit {minimum:.2f} s')
                if reached:
                    break
                added = {layer.index: max(0., combined[layer.index] - layer.total_time_s) for layer in prepared.analysis.layers}
                realized = {layer.index: layer.outer_radius_mm for layer in solid.layers}
                for index, seconds in added.items():
                    history.setdefault(index, []).append((realized.get(index, radius), seconds))
                profile, change = adjust_radius_profile(profile, prepared.analysis.layers, added,
                    target_time_s=target, realized_outer_radii_mm=realized,
                    measurement_history=history, combined_layer_times_s=combined,
                    coupled_radius_scale=joint_radius_scale(
                        {layer.index: combined[layer.index] for layer in selected},
                        target_time_s=target, config=options), config=options)
                if change < .01:
                    break
            except NativeOperationCancelled:
                check_cancel(cancellation_event)
                if best is None or acceptance_event is None or not acceptance_event.is_set():
                    raise
                paused = True
                break
            except NativeSliceError as error:
                if best is None:
                    raise
                failure = error
                break
            finally:
                if candidate is not None and (best is None or candidate is not best.prepared):
                    candidate.close()
        check_cancel(cancellation_event)
        if best is None:
            raise NativeSliceError('Das Laufzeitlimit wurde vor einem vollständig geprüften gemeinsamen Slice erreicht.')

        continuation = None
        if paused and len(records) < options.maximum_iterations and remaining() > 0:
            state = NativeAutomaticState.PAUSED
            status = f'Vorläufig übernommen aus Durchlauf {best.best_iteration}'
            continuation = NativeCalibrationCheckpoint(prepared, options, profile,
                tuple((index, tuple(samples)) for index, samples in history.items()), best_score,
                previously_active_s + time.monotonic() - started)
        elif best_score[0] <= options.time_tolerance_s:
            state = NativeAutomaticState.CONVERGED
            status = 'Zielzeit innerhalb der Toleranz'
        else:
            state = NativeAutomaticState.LIMIT_REACHED
            status = 'Durchlauf- oder Geometriegrenze erreicht'
        message = f'Mindest-Layerzeit {best.minimum_layer_time_s:.2f} s · {status}'
        if best.extra_layer_z_mm is not None:
            message += f' · Zusatzlayer bei Z {best.extra_layer_z_mm:.2f} mm'
        if failure is not None:
            message += f' · Weiterer Slice fehlgeschlagen: {failure}'
        return replace(best, state=state, message=message, iterations=tuple(records), continuation=continuation)
