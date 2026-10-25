"""Application-owned cooling G-code, independently generated from an immutable pre-slice.

No slicer code or third-party postprocessor implementation is used here.
"""
from __future__ import annotations

from bisect import bisect_right
from copy import copy
from dataclasses import dataclass, replace
from functools import lru_cache
import math
import os
import re
import shutil
from pathlib import Path
import tempfile
from threading import Event
from cooling_tower.models import GCodeAnalysisSnapshot, PreparedAnalysisSource
from cooling_tower.slicers import EffectiveProfile
from cooling_tower.services.analysis_service import GCodeAnalysisService, AnalysisCancelled
from cooling_tower.preprocessor_travel import safe_travel_path, original_exclusions_clear
from cooling_tower.preprocessor_placement import OriginalMotionIndex
from cooling_tower.preprocessor_state import PreprocessorStateTracker
from cooling_tower.gcode.slicer_layer_times import LAYER_TIME_MARKER, END_TIME_MARKER

from cooling_tower.calibration.gcode_integration import (
    parse_bed_geometry, _circle_fits_bed,
    _circle_intersects_bounds,
    _point_in_polygon, _distance_to_polygon_edges,
)
from cooling_tower.file_integrity import sha256_file
from cooling_tower.gcode.parser import (
    MachineState, MachineStateTracker, Movement, iter_parsed_gcode_lines,
    normalize_command,
)
from cooling_tower.preview.models import LineSegment3D, Point3D, PreviewScene
from cooling_tower.preview.toolpath import PreviewCancelled, analyze_deposition_toolpaths
from cooling_tower.write_policy import ensure_writable_output
from cooling_tower.settings_defaults import GENERATION_DEFAULTS
from cooling_tower.tower.diameter_transitions import full_infill_foot_taper
from cooling_tower.preprocessor_profiles import resolve_profile_settings, flow_limited_speed, printhead_envelope, profile_flow_limit, first_layer_parameters
from cooling_tower.preprocessor_safety import ExclusionRect, with_exclusions

BEGIN = "; SACRIFICIAL_TOWER_PREPROCESSOR_BEGIN"
END = "; SACRIFICIAL_TOWER_PREPROCESSOR_END"
SUPPORTED_SLICERS = frozenset({"prusa_slicer", "orca_slicer", "bambu_studio", "anycubic_slicer_next"})


@dataclass(frozen=True, slots=True)
class PreprocessorSettings:
    target_layer_time_s: float = GENERATION_DEFAULTS["target_layer_time_s"]
    automatic_height: bool = True
    height_mm: float = 50.0
    automatic_diameter: bool = True
    diameter_mm: float = 10.0
    automatic_base: bool = True
    base_width_mm: float = 25.0
    automatic_position: bool = True
    center_x_mm: float = 30.0
    center_y_mm: float = 30.0
    automatic_wait_position: bool = True
    wait_x_mm: float = 30.0
    wait_y_mm: float = 50.0
    wait_clearance_mm: float = 10.0
    clearance_mm: float = 10.0
    edge_clearance_mm: float = 5.0
    travel_speed_mm_s: float = 100.0
    print_speed_mm_s: float = 25.0
    retract_mm: float = 0.8
    retract_speed_mm_s: float = 30.0
    z_hop_mm: float = 0.6
    prime_mm: float = 0.3
    hollow_tower: bool = True
    wall_count: int = 2
    automatic_target_time: bool = True
    automatic_retraction: bool = True
    automatic_print_speed: bool = True
    automatic_travel_speed: bool = True
    exclusions: tuple[ExclusionRect, ...] = ()
    unretract_speed_mm_s: float | None = None
    restart_extra_mm: float = 0.0

    def __post_init__(self):
        limits = {
            "target_layer_time_s": (0.1, 3600), "height_mm": (0.01, 1000),
            "diameter_mm": (3, 100), "base_width_mm": (3, 150),
            "center_x_mm": (-2000, 2000), "center_y_mm": (-2000, 2000),
            "wait_x_mm": (-2000, 2000), "wait_y_mm": (-2000, 2000),
            "wait_clearance_mm": (5, 100),
            "clearance_mm": (5, 100), "edge_clearance_mm": (5, 100),
            "travel_speed_mm_s": (1, 300), "print_speed_mm_s": (1, 100),
            "retract_mm": (0, 10), "retract_speed_mm_s": (1, 100),
            "z_hop_mm": (0.2, 10), "prime_mm": (0, 5),
            "restart_extra_mm": (-10, 10),
        }
        for name, (low, high) in limits.items():
            value = getattr(self, name)
            if isinstance(value, bool) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"Ungültiger Präprozessorwert {name}: {low} bis {high} erforderlich.")
        if type(self.wall_count) is not int or not 1 <= self.wall_count <= 3:
            raise ValueError("Für die Turmwand sind 1 bis 3 Wandlinien erforderlich.")
        if self.unretract_speed_mm_s is not None and (isinstance(self.unretract_speed_mm_s, bool)
                or not math.isfinite(self.unretract_speed_mm_s) or not 1 <= self.unretract_speed_mm_s <= 100):
            raise ValueError("Ungültiges Tempo für den Rückzugsausgleich.")
        if not isinstance(self.exclusions, tuple) or len(self.exclusions) > 64 or any(not isinstance(zone, ExclusionRect) for zone in self.exclusions):
            raise ValueError("Ungültige eigene Sperrflächen.")
        for name in ("automatic_height", "automatic_diameter", "automatic_base", "automatic_position", "automatic_wait_position", "hollow_tower",
                "automatic_target_time", "automatic_retraction", "automatic_print_speed", "automatic_travel_speed"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} muss ein Wahrheitswert sein.")


@dataclass(frozen=True, slots=True)
class PreprocessorRequest:
    prepared_source: PreparedAnalysisSource
    snapshot: GCodeAnalysisSnapshot
    profile: EffectiveProfile
    settings: PreprocessorSettings

    def validate_source(self):
        prepared = self.prepared_source
        if (not prepared.matches_analysis_gcode()
                or not prepared.source_artifact.matches_current_file(verify_content=True)
                or not self.snapshot.matches_file(prepared.analysis_gcode_path)):
            raise ValueError("Die Originalquelle oder der Pre-Slice wurde verändert. Bitte erneut vorbereiten.")
        if self.profile.installation.adapter_id not in SUPPORTED_SLICERS:
            raise ValueError("Dieser Slicer wird vom Präprozessor nicht unterstützt.")


@dataclass(slots=True)
class PreprocessorResult:
    request: PreprocessorRequest
    workspace: object
    gcode_path: Path
    sha256: str
    scene: PreviewScene
    height_mm: float
    diameter_mm: float
    base_width_mm: float
    wait_count: int
    total_wait_s: float
    layer_waits_s: tuple[float, ...]
    layer_times_s: tuple[float, ...]
    added_motion_times_s: tuple[float, ...]
    effective_z_hop_mm: float
    wall_thickness_range_mm: tuple[float, float] = (0.0, 0.0)
    effective_settings: PreprocessorSettings | None = None
    profile_notes: tuple[str, ...] = ()
    original_layer_times_s: tuple[float, ...] = ()
    layer_heights_mm: tuple[float, ...] = ()
    wipe_angles_rad: tuple[float, ...] = ()
    printhead: object = None
    first_layer: object = None
    collision_notes: tuple[str, ...] = ()
    placement_statistics: dict | None = None

    def dispose(self):
        self.workspace.cleanup()


def _number(values, key, default):
    value = values.get(key, default)
    while isinstance(value, (tuple, list)):
        if not value:
            return default
        value = value[0]
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (ValueError, TypeError):
        return default


def _profile_line_width(values, keys, nozzle, default, *, percent_base=None):
    for key in keys:
        value = values.get(key)
        while isinstance(value, (tuple, list)):
            value = value[0] if value else None
        if value is None:
            continue
        try:
            width = (float(value.strip()[:-1]) * (percent_base if percent_base is not None else nozzle) / 100
                if isinstance(value, str) and value.strip().endswith("%") else float(value))
        except (TypeError, ValueError):
            raise ValueError(f"Ungültige Profil-Linienbreite: {key}.") from None
        if isinstance(value, bool) or not math.isfinite(width) or width < 0 or width > 5 * nozzle:
            raise ValueError(f"Ungültige Profil-Linienbreite: {key}.")
        if width > 0:
            return width
    return default


def _wall_thickness(widths, layer_height):
    return sum(widths) - (len(widths) - 1) * layer_height * (1 - math.pi / 4)


def _check_cancel(event):
    if event is not None and event.is_set():
        raise PreviewCancelled()


def _fmt(value):
    return f"{value:.6f}".rstrip("0").rstrip(".") or "0"


def _scan(request, cancellation_event):
    """Capture the exact modal state immediately after each layer's last deposit."""
    starts = [layer.first_deposition_line for layer in request.snapshot.layers]
    tracker = PreprocessorStateTracker(request.profile.installation.adapter_id)
    endpoints = {}
    tools = set()
    extrusion_declared = False
    pending_error = None
    conditional_depth = 0
    xy_homing = []
    first, last = starts[0], request.snapshot.layers[-1].end_line
    for parsed in iter_parsed_gcode_lines(request.prepared_source.analysis_gcode_path):
        if parsed.number % 2000 == 0:
            _check_cancel(cancellation_event)
        command = normalize_command(parsed.command or "")
        if BEGIN in parsed.raw_text or "COOLING_TOWER_BEGIN" in parsed.raw_text:
            raise ValueError("Der Pre-Slice enthält bereits einen bearbeiteten Turm.")
        if "\x00" in parsed.raw_text or parsed.raw_text.lstrip().startswith("N") and "*" in parsed.raw_text:
            raise ValueError("Binärer oder nummerierter G-Code mit Prüfsummen wird nicht bearbeitet.")
        if command in {"M82", "M83"}:
            extrusion_declared = True
        if command == "M622":
            conditional_depth += 1
        elif command == "M623":
            conditional_depth = max(0, conditional_depth - 1)
        if (command in {"G20", "G93", "G95"}
                or command == "M200" and parsed.parameters.get("D", 0) > 0
                or command == "G92" and any(axis in parsed.parameters for axis in "XYZ")):
            raise ValueError(f"Nicht unterstützte Einheiten, Extrusion oder Koordinaten in {command}.")
        if first <= parsed.number <= last:
            if command in {"G20", "G28", "G29", "G53", "G54", "G55", "G56", "G57", "G58", "G59", "G93", "G95", "M200", "M600", "G10", "G11"}:
                pending_error = f"Nicht unterstützter Druckzustand {command} im Modellbereich."
            if command == "G92" and any(axis in parsed.parameters for axis in "XYZ"):
                raise ValueError("Koordinatenwechsel im Modellbereich werden nicht unterstützt.")
        event = tracker.process_line(parsed)
        if command == "G28" and parsed.parameters and set(parsed.parameters).issubset({"X", "Y"}):
            xy_homing.append((parsed.number, copy(tracker.state)))
        if xy_homing and isinstance(event, Movement) and event.endpoint_distance_xyz_mm > 1e-6:
            if xy_homing[-1][0] > starts[-1]:
                raise ValueError("Auf die abschließende XY-Referenzfahrt folgen weitere räumliche Bewegungen. "
                    "Ein sicherer Endablauf kann dafür nicht rekonstruiert werden.")
        if not isinstance(event, Movement) or event.category != "deposition" or parsed.number < first:
            continue
        index = bisect_right(starts, parsed.number) - 1
        layer = request.snapshot.layers[index]
        if parsed.number > layer.end_line:
            continue
        if pending_error:
            raise ValueError(pending_error)
        if conditional_depth:
            raise ValueError("Modell-Extrusion innerhalb bedingter Firmwarebefehle wird nicht unterstützt.")
        state = tracker.state
        tools.add(state.active_tool or 0)
        if (not extrusion_declared or state.unit_scale_mm != 1
                or state.feedrate_mm_min is None or state.feedrate_mm_min <= 0
                or state.speed_factor_percent <= 0 or state.extrusion_factor <= 0):
            raise ValueError("Der Pre-Slice benötigt Millimeter, M82/M83 und eindeutige Vorschübe.")
        if abs(event.end_z - layer.z_mm) > 0.001 or abs(event.delta_z) > 0.001:
            raise ValueError(f"Nichtplanare Extrusion in Zeile {parsed.number}: Z={event.start_z:.4f} → "
                f"{event.end_z:.4f} mm, erwartete Schichthöhe Z={layer.z_mm:.4f} mm. "
                "Spiral- und sequentieller Druck werden nicht unterstützt.")
        endpoints[index] = (parsed.number, copy(state))
    if len(endpoints) != len(starts) or len(tools) != 1 or tools != {0}:
        raise ValueError("Der Präprozessor benötigt planare Schichten mit einem einzelnen Extruder T0.")
    return endpoints, {line: state for line, state in xy_homing if line > endpoints[len(starts)-1][0]}


def _layer_block(state: MachineState, layer, radius, center, settings, line_width, filament, wait_s, *, inner_line_width=None, solid_base=False, travel_routes, start_angle=0.0, maximum_flow=None, infill_speed=None):
    """Return to the exact original XYZ/E/modes/feed without changing original lines."""
    x, y = center
    start = (x + radius * math.cos(start_angle), y + radius * math.sin(start_angle))
    hop = max(state.z, layer.z_mm) + settings.z_hop_mm
    factor = state.speed_factor_percent / 100
    travel_speed = settings.travel_speed_mm_s / factor
    retract = settings.retract_mm / state.extrusion_factor
    restart = (settings.retract_mm + settings.restart_extra_mm) / state.extrusion_factor if retract else 0.0
    if restart < 0:
        raise ValueError("Die negative Profil-Wiederanlaufmenge übersteigt die Rückzugslänge.")
    restore_speed = (settings.unretract_speed_mm_s or settings.retract_speed_mm_s) / factor
    lines = [BEGIN, f"; layer_z = {_fmt(layer.z_mm)}", "G90", "M83"]
    def emit(code):
        lines.append(code)
    def move(**axes):
        emit("G1 " + " ".join(key + _fmt(value) for key, value in axes.items()))
    move(E=-retract, F=settings.retract_speed_mm_s / factor * 60)
    move(Z=hop, F=600)
    to_wait, to_tower, to_model = travel_routes
    emit("; SACRIFICIAL_TOWER_TRAVEL_TO_WAIT")
    for point in to_wait[1:]:
        move(X=point[0], Y=point[1], F=travel_speed * 60)
    # The park point is outside both model and tower, at lifted Z.
    emit("; SACRIFICIAL_TOWER_WAIT")
    emit("M400")
    remaining_ms = math.ceil(wait_s * 1000)
    if not remaining_ms:
        emit("G4 P0")  # Preserve the identical planner stop in timing and output.
    while remaining_ms > 0:
        duration = min(60_000, remaining_ms)
        emit(f"G4 P{duration}")
        remaining_ms -= duration
    emit("; SACRIFICIAL_TOWER_TRAVEL_TO_WIPE")
    for point in to_tower[1:]:
        move(X=point[0], Y=point[1], F=travel_speed * 60)
    move(Z=layer.z_mm, F=600)
    move(E=restart, F=restore_speed * 60)
    emit("; sacrificial wipe / prime and " + ("hollow tower" if settings.hollow_tower and not solid_base else "solid base / tower"))
    area = math.pi * (filament / 2) ** 2
    inner_line_width = line_width if inner_line_width is None else inner_line_width
    overlap = layer.height_mm * (1 - math.pi / 4)
    ring = radius
    ring_count = 0
    current_width = line_width
    while ring >= current_width * 0.5 and (solid_base or not settings.hollow_tower or ring_count < settings.wall_count):
        extrusion_per_mm = (current_width - overlap) * layer.height_mm / area / state.extrusion_factor
        segments = max(24, min(180, math.ceil(math.tau * ring / 0.7)))
        edge_length = 2 * ring * math.sin(math.pi / segments)
        prime_per_edge = settings.prime_mm / segments / state.extrusion_factor if ring_count == 0 else 0.0
        # Prime while moving on the first ring, rather than leaving a stationary
        # lump at its seam. Include this extra volume in the flow cap as well.
        volume_per_mm = (extrusion_per_mm + prime_per_edge / edge_length) * area * state.extrusion_factor
        feature_speed = infill_speed if solid_base and ring_count > 0 and infill_speed is not None else settings.print_speed_mm_s
        print_speed = min(feature_speed, maximum_flow / volume_per_mm if maximum_flow else feature_speed) / factor
        previous = tuple(float(_fmt(value)) for value in (x + ring * math.cos(start_angle), y + ring * math.sin(start_angle)))
        move(X=previous[0], Y=previous[1], F=print_speed * 60)
        for part in range(1, segments + 1):
            angle = start_angle + math.tau * part / segments
            point = tuple(float(_fmt(value)) for value in (x + ring * math.cos(angle), y + ring * math.sin(angle)))
            distance = math.dist(previous, point)
            extrusion = float(_fmt(distance * extrusion_per_mm + prime_per_edge))
            actual_volume_per_mm = extrusion * area * state.extrusion_factor / distance if distance else 0.0
            actual_speed = min(feature_speed, maximum_flow / actual_volume_per_mm
                if maximum_flow and actual_volume_per_mm else feature_speed)
            # Cap the serialized move, including E/XY quantization. Round feed
            # downward so decimal formatting cannot exceed a known flow limit.
            feed = math.floor(actual_speed / factor * 60 * 1e6) / 1e6
            move(X=point[0], Y=point[1], E=extrusion, F=feed)
            previous = point
        ring -= (current_width + inner_line_width) / 2 - overlap
        current_width = inner_line_width
        ring_count += 1
    move(E=-retract, F=settings.retract_speed_mm_s / factor * 60)
    move(Z=hop, F=600)
    emit("; SACRIFICIAL_TOWER_TRAVEL_TO_MODEL")
    # Printing ends on an inner ring: join the exact checked route at its start.
    move(X=start[0], Y=start[1], F=travel_speed * 60)
    for point in to_model[1:]:
        move(X=point[0], Y=point[1], F=travel_speed * 60)
    move(Z=state.z, F=600)
    move(E=restart, F=restore_speed * 60)
    emit("G92 E" + _fmt(state.e))
    emit("G91" if state.xyz_relative else "G90")
    emit("M83" if state.extrusion_relative else "M82")
    move(F=state.feedrate_mm_min)
    emit(END)
    return lines


class PreprocessorService:
    def __init__(self, temporary_root):
        self.temporary_root = Path(temporary_root)

    def prepare(self, request, *, cancellation_event=None, progress_callback=None):
        notify = progress_callback or (lambda _p, _s: None)
        request.validate_source()
        _check_cancel(cancellation_event)
        source = request.prepared_source.analysis_gcode_path
        motion_analyzer = GCodeAnalysisService(preprocessor_mode=True)
        raw_snapshot = request.snapshot
        if request.profile.installation.adapter_id in {"prusa_slicer", "anycubic_slicer_next"}:
            try:
                raw_snapshot = motion_analyzer.analyze(source,
                    cancellation_callback=lambda: cancellation_event is not None and cancellation_event.is_set())
            except AnalysisCancelled as error:
                raise PreviewCancelled() from error
        source_snapshot = raw_snapshot if request.profile.installation.adapter_id == "prusa_slicer" else request.snapshot
        layers = source_snapshot.layers
        if not layers:
            raise ValueError("Der Pre-Slice enthält keine druckbaren Schichten.")
        if any(layer.height_mm <= 0 or layer.untimed_event_count or not math.isfinite(layer.total_time_s) for layer in layers):
            raise ValueError("Der Pre-Slice enthält unvollständig berechnete Zeiten oder ungültige Schichthöhen.")
        if any(b.z_mm <= a.z_mm for a, b in zip(layers, layers[1:])):
            raise ValueError("Sequentieller Druck oder absteigende Schichten werden nicht unterstützt.")
        values = request.profile.effective_values
        profile_hop = max(_number(values, key, 0) for key in
            ("retract_lift", "z_hop", "filament_retract_lift", "filament_z_hop"))
        # A manual additional hop may increase, never weaken the profile lift.
        settings, profile_notes = resolve_profile_settings(request.settings, values)
        settings = replace(settings, z_hop_mm=max(settings.z_hop_mm, profile_hop))
        waits = tuple(max(0.0, settings.target_layer_time_s - layer.total_time_s) for layer in layers)
        needed = [i for i, wait in enumerate(waits) if wait > 0.001]
        count = needed[-1] + 1 if needed else 0
        if not settings.automatic_height:
            count = bisect_right([layer.z_mm for layer in layers], settings.height_mm + 1e-6)
            if count < (needed[-1] + 1 if needed else 0):
                raise ValueError("Die manuelle Turmhöhe endet vor dem letzten nötigen Wartebefehl.")
            if settings.height_mm > layers[-1].z_mm + 0.001:
                raise ValueError("Die manuelle Turmhöhe darf die Modellhöhe nicht überschreiten.")
        height = layers[count - 1].z_mm if count else 0.0
        # Bounded slenderness heuristics, independent of cooling-time volume.
        diameter = max(6.0, height * 0.10) if settings.automatic_diameter else settings.diameter_mm
        base = max(14.0, diameter * 1.8, height * 0.25) if settings.automatic_base else settings.base_width_mm
        if base < diameter:
            raise ValueError("Die Standfußbreite muss mindestens dem Turmdurchmesser entsprechen.")
        geometry = parse_bed_geometry(values)
        if geometry is None:
            raise ValueError("Im bestätigten Druckprofil fehlt eine eindeutige Druckbettgeometrie.")
        geometry = with_exclusions(geometry, settings.exclusions)
        head = printhead_envelope(values, geometry)
        profile_notes += (head.note,)
        if head.estimated:
            settings = replace(settings, z_hop_mm=max(settings.z_hop_mm, 2.0))
        max_z = _number(values, "printable_height", _number(values, "max_print_height", 0))
        if max_z <= 0:
            raise ValueError("Im bestätigten Druckprofil fehlt die maximale Druckhöhe.")
        if count and height + settings.z_hop_mm > max_z:
            raise ValueError("Der Sicherheitshub würde die maximale Druckhöhe überschreiten.")
        nozzle = _number(values, "nozzle_diameter", 0.4)
        filament = _number(values, "filament_diameter", 1.75)
        if not 0.1 <= nozzle <= 2 or not 1 <= filament <= 4:
            raise ValueError("Düsen- oder Filamentdurchmesser ist ungültig.")
        prusa_widths = request.profile.installation.adapter_id == "prusa_slicer"
        width_records = []
        for layer in layers[:count] or layers[:1]:
            percent_base = layer.height_mm if prusa_widths else nozzle
            general = _profile_line_width(values, ("extrusion_width", "line_width") if prusa_widths else ("line_width", "extrusion_width"),
                nozzle, nozzle * 1.1, percent_base=percent_base)
            outer = _profile_line_width(values, ("external_perimeter_extrusion_width", "outer_wall_line_width") if prusa_widths
                else ("outer_wall_line_width", "external_perimeter_extrusion_width"), nozzle, general, percent_base=percent_base)
            inner = _profile_line_width(values, ("perimeter_extrusion_width", "inner_wall_line_width") if prusa_widths
                else ("inner_wall_line_width", "perimeter_extrusion_width"), nozzle, general, percent_base=percent_base)
            width_records.append((general, outer, inner))
        general_width, width, inner_width = (max(record[i] for record in width_records) for i in range(3))
        first_layer = first_layer_parameters(values, print_speed=settings.print_speed_mm_s,
            nozzle=nozzle, line_width=width_records[0][1], layer_height=layers[0].height_mm,
            adapter_id=request.profile.installation.adapter_id)
        profile_notes += first_layer.notes
        widths = [first_layer.line_width_mm if i == 0 else width_records[i][1] for i in range(count)]
        inner_widths = [first_layer.line_width_mm if i == 0 else width_records[i][2] for i in range(count)]
        if count and first_layer.line_width_mm <= layers[0].height_mm:
            raise ValueError("Die Erstschicht-Linienbreite muss größer als die erste Turm-Schichthöhe sein.")
        if any(min(widths[i], inner_widths[i]) <= layer.height_mm for i, layer in enumerate(layers[:count])):
            raise ValueError("Die Profil-Linienbreite muss größer als die Turm-Schichthöhe sein.")
        # First-layer widening applies to the solid foot, not the hollow
        # shaft's specified wall count or its reported radial thickness.
        thicknesses = [_wall_thickness((width_records[i][1],) + (width_records[i][2],) * (settings.wall_count - 1), layer.height_mm)
            for i, layer in enumerate(layers[:count])]
        minimum_hollow_diameter = 2 * max(thicknesses, default=width + inner_width*(settings.wall_count-1)) + max(width, inner_width)
        if settings.automatic_diameter and settings.hollow_tower:
            diameter = max(diameter, minimum_hollow_diameter)
            if settings.automatic_base:
                base = max(14.0, diameter * 1.8, height * .25)
        if base < diameter:
            raise ValueError("Die Standfußbreite muss mindestens dem Turmdurchmesser entsprechen.")
        if settings.hollow_tower and diameter < minimum_hollow_diameter:
            raise ValueError("Der Durchmesser ist für die gewählte hohle Wandstärke zu klein.")
        if any(layer.height_mm > nozzle * 0.85 for layer in layers[:count]):
            raise ValueError("Die Schichthöhe ist für die Düse des Turms zu groß.")
        settings = flow_limited_speed(settings, values, (width, inner_width), tuple(layer.height_mm for layer in layers[:count]))
        first_layer = replace(first_layer, wall_speed_mm_s=min(first_layer.wall_speed_mm_s, settings.print_speed_mm_s),
            infill_speed_mm_s=min(first_layer.infill_speed_mm_s, settings.print_speed_mm_s))
        notify(10, "Pre-Slice und Druckzustände prüfen …")
        endpoints, end_homing = _scan(replace(request, snapshot=source_snapshot), cancellation_event)
        original_exclusions_clear(source, tuple(zone.polygon for zone in settings.exclusions), head.radius_mm,
            cancellation_event=cancellation_event)
        end_safe_z = max(layer.z_mm for layer in layers) + settings.z_hop_mm
        if count and end_homing and end_safe_z > max_z:
            raise ValueError("Die abschließende XY-Referenzfahrt benötigt einen Sicherheitshub oberhalb der Druckhöhe.")
        paths = analyze_deposition_toolpaths(source, expected_layer_count=len(layers), cancellation_event=cancellation_event)
        if paths.occupied_bounds is None:
            raise ValueError("Die Modellfläche konnte nicht rekonstruiert werden.")
        occupied = paths.occupied_bounds
        model_clearance = max(settings.clearance_mm, head.radius_mm + 2 if head.estimated else settings.clearance_mm)
        wait_clearance = max(settings.wait_clearance_mm, head.radius_mm + 2 if head.estimated else settings.wait_clearance_mm)
        reserved = base / 2 + max(width, first_layer.line_width_mm) / 2
        model_line_margin = max(general_width, inner_width, width, first_layer.line_width_mm) / 2
        foot = full_infill_foot_taper(tuple(layer.z_mm for layer in layers[:count]),
            base / 2, diameter / 2, layers[-1].z_mm) if count else None
        radii = [foot.radius(layer.z_mm) - widths[i] / 2 for i, layer in enumerate(layers[:count])]
        solid_layers = [i < 2 or (base > diameter and layer.z_mm < foot.start_z + foot.duration - 1e-9)
            for i, layer in enumerate(layers[:count])]
        # The golden angle spreads local prime deposits without periodic seams.
        # Every corresponding approach and departure is checked before output.
        wipe_angles = tuple((i * math.pi * (3 - math.sqrt(5))) % math.tau for i in range(count))
        insertions = {endpoints[i][0]: i for i in range(count)}
        insertion_heights = {line: layers[i].z_mm for line, i in insertions.items()}
        motion_index = OriginalMotionIndex.capture(source, insertion_heights, cancellation_event=cancellation_event)
        candidate_count = 0
        rejection = None
        collision_notes = (head.limitations,
            "Modellabstände: ungekürzte Ablagebahnen und höhenabhängiger Turmquerschnitt; Originalfahrten einschließlich Endsequenz geprüft.",
            "Eigene Sperrflächen gelten als unbekannt hohe Hindernisse; ihre Höhe wird nicht geschätzt.")
        def fits(point):
            # The printable polygon is the manufacturer's nozzle travel area;
            # the head may overhang it. Physical keepouts are expanded below.
            head_clear = _circle_fits_bed(point, reserved, settings.edge_clearance_mm, geometry)
            return (head_clear
                and all(not _point_in_polygon(point, polygon) and _distance_to_polygon_edges(point, polygon) >= reserved + head.radius_mm + 1
                    for polygon in geometry.excluded_polygons)
                and motion_index.model_clear(point, reserved + model_clearance + model_line_margin,
                    lambda z: foot.radius(max(foot.start_z, z)) + model_clearance + model_line_margin, height=height))
        @lru_cache(maxsize=8192)
        def checked_route(a, b):
            return safe_travel_path(a, b, geometry, margin_mm=head.radius_mm+1)

        def route(a, b):
            return checked_route(a, b) if a <= b else tuple(reversed(checked_route(b, a)))
        routes = []
        wait_position = None
        if not count:
            center = ((occupied.minimum_x_mm + occupied.maximum_x_mm)/2, (occupied.minimum_y_mm + occupied.maximum_y_mm)/2)
        else:
            candidates = [(settings.center_x_mm, settings.center_y_mm)]
            if settings.automatic_position:
                bed = geometry.bounds
                inset = reserved + settings.edge_clearance_mm
                xs = [bed.minimum_x_mm + inset + (bed.maximum_x_mm-bed.minimum_x_mm-2*inset)*i/32 for i in range(33)]
                ys = [bed.minimum_y_mm + inset + (bed.maximum_y_mm-bed.minimum_y_mm-2*inset)*i/32 for i in range(33)]
                candidates = [(x, y) for x in xs for y in ys if fits((x, y))]
                sample = [endpoints[i][1] for i in range(0, count, max(1, count//64))]
                candidates.sort(key=lambda point: ((-math.hypot(point[0] - (occupied.minimum_x_mm + occupied.maximum_x_mm)/2,
                    point[1] - (occupied.minimum_y_mm + occupied.maximum_y_mm)/2)) if head.estimated else 0,
                    sum(math.hypot(state.x-point[0], state.y-point[1]) for state in sample)))
            center = None
            for point in candidates:
                candidate_count += 1
                _check_cancel(cancellation_event)
                if not fits(point):
                    continue
                rejection = motion_index.tower_rejection(point, reserved,
                    head_radius=head.radius_mm, head_height=head.clearance_height_mm,
                    lower_head_radius=head.lower_radius_mm, gantry_height=head.clearance_height_mm)
                if rejection:
                    continue
                parking = [(settings.wait_x_mm, settings.wait_y_mm)]
                if settings.automatic_wait_position:
                    parking = [(point[0]+distance*math.cos(angle*math.tau/16),
                        point[1]+distance*math.sin(angle*math.tau/16))
                        for distance in (reserved+wait_clearance+.1,
                            reserved+wait_clearance+10, reserved+wait_clearance+2*head.radius_mm)
                        for angle in range(16)]
                    if head.estimated:
                        bed = geometry.bounds
                        inset = settings.edge_clearance_mm
                        parking += [(bed.minimum_x_mm + inset + (bed.maximum_x_mm-bed.minimum_x_mm-2*inset)*ix/8,
                            bed.minimum_y_mm + inset + (bed.maximum_y_mm-bed.minimum_y_mm-2*inset)*iy/8)
                            for ix in range(9) for iy in range(9)]
                    # Prefer a short detour, with deterministic tie-breaking.
                    parking.sort(key=lambda park: sum(math.hypot(state.x-park[0], state.y-park[1])
                        for state in sample) if settings.automatic_position else math.dist(park, point))
                for park in parking:
                    if (not _circle_fits_bed(park, 0, settings.edge_clearance_mm, geometry)
                            or not motion_index.model_clear(park, wait_clearance+model_line_margin, lambda _z: wait_clearance+model_line_margin)
                            or math.dist(park, point) < reserved+wait_clearance):
                        continue
                    try:
                        routes = []
                        for i in range(count):
                            _check_cancel(cancellation_event)
                            origin = (endpoints[i][1].x, endpoints[i][1].y)
                            wipe = (point[0]+radii[i]*math.cos(wipe_angles[i]), point[1]+radii[i]*math.sin(wipe_angles[i]))
                            routes.append((route(origin, park), route(park, wipe), route(wipe, origin)))
                    except ValueError:
                        continue
                    center, wait_position = point, park
                    break
                if center is not None:
                    break
            if center is None:
                raise ValueError("Keine sichere Turm- und Warteposition mit freien Originalbahnen und kollisionsfreien Fahrwegen gefunden. "
                    "Abstände, Turmmaße oder manuelle Turm-/Warteposition prüfen."
                    + (" " + rejection if rejection else "") + (" " + head.note if head.estimated else ""))
        protected_roots = (request.profile.installation.executable_path.parent, *request.profile.installation.profile_roots)
        ensure_writable_output(self.temporary_root, protected_roots=protected_roots)
        self.temporary_root.mkdir(parents=True, exist_ok=True)
        workspace = tempfile.TemporaryDirectory(prefix="preprocessor_", dir=self.temporary_root)
        try:
            output = Path(workspace.name) / "preprocessed.gcode"
            tower_collector = []
            travel_collector = []
            wait_points = []
            wait_point_layers = []
            tower_tracker = PreprocessorStateTracker(request.profile.installation.adapter_id)
            from cooling_tower.gcode.parser import GCodeLine, parse_gcode_line
            def render(destination, actual_waits, *, collect=False, final_times=None):
                with source.open("rb") as original, destination.open("wb") as target:
                    if count:
                        target.write(b"; SACRIFICIAL_TOWER_PREPROCESSED\n")
                    clocks = [0.0]
                    for seconds in final_times or ():
                        clocks.append(clocks[-1] + seconds)
                    for number, raw in enumerate(original, 1):
                        if number % 2000 == 0:
                            _check_cancel(cancellation_event)
                        text = raw.decode("utf-8-sig", errors="replace").strip()
                        if count and number in end_homing:
                            state = end_homing[number]
                            lift = max(end_safe_z, state.z)
                            if lift > max_z:
                                raise ValueError("Die abschließende Referenzfahrt überschreitet die sichere Druckhöhe.")
                            target.write(("; SACRIFICIAL_TOWER_SAFE_END_HOMING\nG90\n"
                                f"G1 Z{_fmt(lift)} F600\n" + ("G91\n" if state.xyz_relative else "G90\n")
                                + ("M83\n" if state.extrusion_relative else "M82\n")
                                + (f"G1 F{_fmt(state.feedrate_mm_min)}\n" if state.feedrate_mm_min else "")).encode("ascii"))
                        # Anycubic's original cumulative clock becomes stale after
                        # processing. Replace only these advisory comments in the
                        # output, retaining the calibrated original times plus the
                        # measured motion delta. No printer instruction is changed.
                        if count and final_times is not None and re.fullmatch(r"; estimated printing time \(normal mode\) = .* = [\d.eE+-]+", text):
                            continue
                        target.write(raw)
                        if count and final_times is not None and (text.startswith(LAYER_TIME_MARKER + " ") or text == END_TIME_MARKER):
                            index = len(final_times) if text == END_TIME_MARKER else int(text.split()[2])
                            if not 0 <= index < len(clocks):
                                raise ValueError("Ungültige native Zeitmarkierung im Pre-Slice.")
                            target.write(f"; estimated printing time (normal mode) = Sacrificial Tower = {clocks[index]:.6f}\n".encode("ascii"))
                        if number not in insertions:
                            continue
                        i = insertions[number]
                        layer = layers[i]
                        state = endpoints[i][1]
                        layer_settings = replace(settings, print_speed_mm_s=min(settings.print_speed_mm_s,
                            first_layer.wall_speed_mm_s)) if i == 0 else settings
                        block = _layer_block(state, layer, radii[i], center, layer_settings, widths[i], filament,
                            actual_waits[i], inner_line_width=inner_widths[i], solid_base=solid_layers[i], travel_routes=routes[i],
                            start_angle=wipe_angles[i], maximum_flow=profile_flow_limit(values),
                            infill_speed=min(settings.print_speed_mm_s, first_layer.infill_speed_mm_s) if i == 0 else None)
                        if not raw.endswith(b"\n"):
                            target.write(b"\n")
                        target.write(("\n".join(block) + "\n").encode("ascii"))
                        # Reconstruct the displayed tower from the emitted instructions.
                        tower_tracker.state = copy(state)
                        wait_travel = True
                        for instruction in block if collect else ():
                            if instruction.startswith("; sacrificial wipe / prime and "):
                                wait_travel = False
                            parsed = parse_gcode_line(GCodeLine(1, instruction))
                            event = tower_tracker.process_line(parsed)
                            if parsed.command == "G4" and parsed.parameters.get("P", 0) > 0:
                                current = tower_tracker.state
                                point = Point3D(current.x, current.y, current.z)
                                if not wait_points or wait_points[-1] != point:
                                    wait_points.append(point)
                                    wait_point_layers.append(i)
                            if isinstance(event, Movement) and event.category == "deposition":
                                tower_collector.append(LineSegment3D(Point3D(event.start_x, event.start_y, event.start_z),
                                    Point3D(event.end_x, event.end_y, event.end_z)))
                            elif isinstance(event, Movement) and event.endpoint_distance_xyz_mm > 1e-6:
                                segment = LineSegment3D(Point3D(event.start_x, event.start_y, event.start_z),
                                    Point3D(event.end_x, event.end_y, event.end_z))
                                travel_collector.append((segment, wait_travel, i))
                        if len(tower_collector) > 120_000:
                            tower_collector[:] = tower_collector[::2]
                        if len(travel_collector) > 60_000:
                            travel_collector[:] = travel_collector[::2]
            notify(35, "Sichere Fahrwege und hohle Turmbahnen berechnen …")
            timing_path = Path(workspace.name) / "timing.gcode"
            render(timing_path, tuple(0.0 for _ in layers))
            notify(55, "Schichtzeiten einschließlich Fahrwegen, Abstreifen und Primen auswerten …")
            try:
                timing = motion_analyzer.analyze(timing_path,
                    cancellation_callback=lambda: cancellation_event is not None and cancellation_event.is_set())
            except AnalysisCancelled as error:
                raise PreviewCancelled() from error
            if timing.layer_count != len(layers) or any(layer.untimed_event_count for layer in timing.layers):
                raise ValueError("Die erzeugten Turm- und Fahrbahnen konnten nicht eindeutig zeitlich ausgewertet werden.")
            if len(raw_snapshot.layers) != len(layers) or any(abs(a.z_mm-b.z_mm) > .001 for a, b in zip(raw_snapshot.layers, layers)):
                raise ValueError("Originalzeiten und rekonstruierte Druckschichten stimmen nicht überein.")
            motion_deltas = tuple(new.total_time_s - old.total_time_s for new, old in zip(timing.layers, raw_snapshot.layers))
            base_times = tuple(original.total_time_s + delta for original, delta in zip(layers, motion_deltas))
            waits = tuple(math.ceil(max(0, settings.target_layer_time_s - seconds - 1e-9)*1000)/1000
                if i < count else 0.0 for i, seconds in enumerate(base_times))
            final_times = tuple(seconds + wait for seconds, wait in zip(base_times, waits))
            notify(80, "Nur verbleibende Wartezeiten einfügen und Vorschau rekonstruieren …")
            render(output, waits, collect=True, final_times=final_times)
            timing_path.unlink()
            if count:
                notify(95, "Fertigen G-Code und alle Schichtzeiten abschließend prüfen …")
                try:
                    verified = GCodeAnalysisService().analyze(output,
                        cancellation_callback=lambda: cancellation_event is not None and cancellation_event.is_set())
                except AnalysisCancelled as error:
                    raise PreviewCancelled() from error
                if (verified.layer_count != len(layers)
                        or any(layer.untimed_event_count or abs(layer.z_mm-original.z_mm) > .001
                            or layer.total_time_s < settings.target_layer_time_s - .005
                            or abs(layer.total_time_s-planned) > .02
                            for layer, original, planned in zip(verified.layers, layers, final_times))):
                    raise ValueError("Die abschließende G-Code-Prüfung bestätigt die geplanten Schichtzeiten nicht. Export gesperrt.")
            _check_cancel(cancellation_event)
            request.validate_source()
            segments = tuple(tower_collector)
            scene = PreviewScene(paths.object_segments, segments, geometry.bounds, center,
                paths.source_segment_count, len(paths.object_segments) + len(segments), height,
                notes=("Rekonstruierte G-Code-Koordinaten; Schichtzeiten enthalten Fahrwege, Turmdruck, Primen und Restwartezeit.",) + profile_notes,
                object_height_mm=layers[-1].z_mm, object_layer_count=len(layers), tower_layer_count=count, bed_geometry=geometry,
                travel_segments=tuple(segment for segment, _wait, _i in travel_collector),
                wait_travel_segments=tuple(segment for segment, wait, _i in travel_collector if wait),
                tower_travel_segments=tuple(segment for segment, wait, _i in travel_collector if not wait),
                wait_points=tuple(wait_points), wait_position_xy_mm=wait_position,
                layer_z_mm=tuple(layer.z_mm for layer in layers),
                wait_travel_layer_indices=tuple(i for _s, wait, i in travel_collector if wait),
                tower_travel_layer_indices=tuple(i for _s, wait, i in travel_collector if not wait),
                wait_point_layer_indices=tuple(wait_point_layers), wait_height_offset_mm=settings.z_hop_mm,
                printhead_radius_mm=head.radius_mm, printhead_lower_radius_mm=head.lower_radius_mm,
                printhead_clearance_height_mm=head.clearance_height_mm, printhead_estimated=head.estimated,
                wipe_points=tuple(Point3D(center[0]+radii[i]*math.cos(wipe_angles[i]),
                    center[1]+radii[i]*math.sin(wipe_angles[i]), layers[i].z_mm + settings.z_hop_mm) for i in range(count)))
            notify(100, "Präprozessor-Vorschau bereit.")
            return PreprocessorResult(request, workspace, output, sha256_file(output), scene,
                height, diameter if count else 0, base if count else 0, sum(wait > 0 for wait in waits), sum(waits), waits,
                final_times, motion_deltas, settings.z_hop_mm,
                (min(thicknesses), max(thicknesses)) if count and settings.hollow_tower else (0.0, 0.0),
                settings, profile_notes, tuple(layer.total_time_s for layer in layers), tuple(layer.z_mm for layer in layers), wipe_angles, head,
                first_layer, collision_notes, {"indexed_moves": motion_index.move_count, "depositions": motion_index.deposition_count,
                    "candidates": candidate_count, "examined_moves": motion_index.examined_moves})
        except BaseException:
            workspace.cleanup()
            raise

    def export(self, result, destination, *, overwrite=False):
        result.request.validate_source()
        profile = result.request.profile
        target = ensure_writable_output(destination,
            protected_roots=(profile.installation.executable_path.parent, *profile.installation.profile_roots),
            protected_files=(*profile.source_paths, result.request.prepared_source.analysis_gcode_path,
                result.request.prepared_source.source_artifact.original_path))
        if target.suffix.casefold() != ".gcode":
            raise ValueError("Der Präprozessor exportiert ausschließlich .gcode-Dateien.")
        if sha256_file(result.gcode_path) != result.sha256:
            raise ValueError("Der erzeugte G-Code wurde nach der Vorschau verändert.")
        target.parent.mkdir(parents=True, exist_ok=True)
        previous_digest = sha256_file(target) if target.is_file() else None
        if previous_digest is not None and not overwrite:
            raise FileExistsError("Die Exportdatei existiert bereits. Bitte einen anderen Namen wählen.")
        descriptor, temporary_name = tempfile.mkstemp(prefix=".preprocessor_export_", suffix=".tmp", dir=target.parent)
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                with result.gcode_path.open("rb") as source:
                    shutil.copyfileobj(source, stream)
                stream.flush()
                os.fsync(stream.fileno())
            result.request.validate_source()
            if sha256_file(temporary_path) != result.sha256:
                raise ValueError("Die Exportkopie stimmt nicht mit der geprüften Vorschau überein.")
            if overwrite:
                current_digest = sha256_file(target) if target.is_file() else None
                if current_digest != previous_digest:
                    raise ValueError("Die Exportdatei wurde zwischenzeitlich verändert und bleibt erhalten.")
                os.replace(temporary_path, target)
            elif os.name == "nt":
                # Windows rename is atomic and fails if a target already exists.
                os.rename(temporary_path, target)
            else:
                os.link(temporary_path, target)
        finally:
            temporary_path.unlink(missing_ok=True)
        return target
