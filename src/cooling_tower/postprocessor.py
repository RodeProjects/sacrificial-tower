"""Application-owned cooling G-code, independently generated from an immutable pre-slice.

No slicer code or third-party postprocessor implementation is used here.
"""
from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable
from copy import copy
from dataclasses import dataclass, replace
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
import math
import os
import re
import shutil
from pathlib import Path
import tempfile
from threading import Event, Lock
from cooling_tower.models import BedGeometry, GCodeAnalysisSnapshot, PreparedAnalysisSource
from cooling_tower.slicers import EffectiveProfile
from cooling_tower.services.analysis_service import GCodeAnalysisService, AnalysisCancelled
from cooling_tower.postprocessor_travel import safe_travel_path, original_exclusions_clear
from cooling_tower.postprocessor_placement import OriginalMotionCollector
from cooling_tower.postprocessor_regions import PlacementRegions
from cooling_tower.postprocessor_features import FeatureComments
from cooling_tower.postprocessor_toolpaths import contour_path, tower_paths
from cooling_tower.postprocessor_capture import (
    CAPTURE_MARKER, DEPARTURE_WIPE_MARKER, DRY_EXIT_MARKER, MODEL_WIPE_MARKER, CaptureDesign, capture_design,
    capture_frame, additional_prime, alignment_penalty, supported_tail,
    configure_capture_design, automatic_capture_base, capture_floor_reserve, supported_foot_holes,
    capture_obstacle, nearest_capture_point,
)
from cooling_tower.postprocessor_routing import model_travel_islands, model_crossings, prefer_model_avoiding_route
from cooling_tower.postprocessor_state import PostprocessorStateTracker
from cooling_tower.legacy_method_ids import LEGACY_POSTPROCESSOR_BEGIN
from cooling_tower.gcode.slicer_layer_times import LAYER_TIME_MARKER, END_TIME_MARKER, read_slicer_layer_times

from cooling_tower.calibration.gcode_integration import (
    parse_bed_geometry, _circle_fits_bed,
    _point_in_polygon, _distance_to_polygon_edges,
)
from cooling_tower.file_integrity import sha256_file
from cooling_tower.gcode.parser import (
    MachineState, Movement, iter_parsed_gcode_lines,
    normalize_command,
)
from cooling_tower.preview.models import LineSegment3D, Point3D, PreviewScene
from cooling_tower.preview.toolpath import PreviewCancelled, DepositionToolpathCollector
from cooling_tower.preview.seams import read_seam_points
from cooling_tower.write_policy import ensure_writable_output
from cooling_tower.tower.diameter_transitions import full_infill_foot_taper
from cooling_tower.postprocessor_profiles import DEFAULT_TOWER_BRIM_WIDTH_MM, resolve_profile_settings, flow_limited_speed, printhead_envelope, profile_flow_limit, first_layer_parameters, profile_flag
from cooling_tower.postprocessor_safety import ExclusionRect, with_exclusions

BEGIN = "; SACRIFICIAL_TOWER_POSTPROCESSOR_BEGIN"
END = "; SACRIFICIAL_TOWER_POSTPROCESSOR_END"
FINAL_PARK = "; SACRIFICIAL_TOWER_FINAL_PARK"
PARKED = "; SACRIFICIAL_TOWER_PARKED"
SUPPORTED_SLICERS = frozenset({"prusa_slicer", "orca_slicer", "bambu_studio", "anycubic_slicer_next"})


@dataclass(frozen=True, slots=True)
class PostprocessorSettings:
    target_layer_time_s: float = 10.0
    automatic_height: bool = True
    height_mm: float = 50.0
    automatic_diameter: bool = True
    diameter_mm: float = 10.0
    automatic_base: bool = True
    base_width_mm: float = 25.0
    automatic_tower_brim_width: bool = True
    tower_brim_width_mm: float = DEFAULT_TOWER_BRIM_WIDTH_MM
    automatic_tower_brim_gap: bool = True
    tower_brim_gap_mm: float = 0.2
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
    z_hop_mm: float = 0.2
    automatic_z_hop: bool = True
    prime_mm: float = 0.3
    automatic_prime: bool = True
    hollow_tower: bool = True
    wall_count: int = 2
    automatic_target_time: bool = False
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
            "tower_brim_width_mm": (0, 20),
            "tower_brim_gap_mm": (0, 10) if self.automatic_tower_brim_gap else (0.1, 1),
            "center_x_mm": (-2000, 2000), "center_y_mm": (-2000, 2000),
            "wait_x_mm": (-2000, 2000), "wait_y_mm": (-2000, 2000),
            "wait_clearance_mm": (5, 100),
            "clearance_mm": (5, 100), "edge_clearance_mm": (5, 100),
            "travel_speed_mm_s": (1, 300), "print_speed_mm_s": (1, 100),
            "retract_mm": (0, 10), "retract_speed_mm_s": (1, 100),
            "z_hop_mm": (0, 10), "prime_mm": (0, 5),
            "restart_extra_mm": (-10, 10),
        }
        for name, (low, high) in limits.items():
            value = getattr(self, name)
            if isinstance(value, bool) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"Ungültiger Postprozessorwert {name}: {low} bis {high} erforderlich.")
        if type(self.wall_count) is not int or not 1 <= self.wall_count <= 3:
            raise ValueError("Für die Turmwand sind 1 bis 3 Wandlinien erforderlich.")
        if self.unretract_speed_mm_s is not None and (isinstance(self.unretract_speed_mm_s, bool)
                or not math.isfinite(self.unretract_speed_mm_s) or not 1 <= self.unretract_speed_mm_s <= 100):
            raise ValueError("Ungültiges Tempo für den Rückzugsausgleich.")
        if not isinstance(self.exclusions, tuple) or len(self.exclusions) > 64 or any(not isinstance(zone, ExclusionRect) for zone in self.exclusions):
            raise ValueError("Ungültige eigene Sperrflächen.")
        for name in ("automatic_height", "automatic_diameter", "automatic_base", "automatic_position", "automatic_wait_position", "hollow_tower",
                "automatic_target_time", "automatic_retraction", "automatic_print_speed", "automatic_travel_speed",
                "automatic_tower_brim_width", "automatic_tower_brim_gap", "automatic_z_hop", "automatic_prime"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} muss ein Wahrheitswert sein.")
        object.__setattr__(self, "z_hop_mm", float(Decimal(str(self.z_hop_mm)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP)))


@dataclass(frozen=True, slots=True)
class PostprocessorRequest:
    prepared_source: PreparedAnalysisSource
    snapshot: GCodeAnalysisSnapshot
    profile: EffectiveProfile
    settings: PostprocessorSettings

    def validate_source(self):
        prepared = self.prepared_source
        if (not prepared.matches_analysis_gcode()
                or not prepared.source_artifact.matches_current_file(verify_content=True)
                or not self.snapshot.matches_file(prepared.analysis_gcode_path)):
            raise ValueError("Die Originalquelle oder der Pre-Slice wurde verändert. Bitte erneut vorbereiten.")
        if self.profile.installation.adapter_id not in SUPPORTED_SLICERS:
            raise ValueError("Dieser Slicer wird vom Postprozessor nicht unterstützt.")


@dataclass(slots=True)
class PostprocessorResult:
    request: PostprocessorRequest
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
    effective_settings: PostprocessorSettings | None = None
    profile_notes: tuple[str, ...] = ()
    original_layer_times_s: tuple[float, ...] = ()
    layer_heights_mm: tuple[float, ...] = ()
    wipe_angles_rad: tuple[float, ...] = ()
    printhead: object = None
    first_layer: object = None
    collision_notes: tuple[str, ...] = ()
    placement_statistics: dict | None = None
    placement: PostprocessorPlacement | None = None
    placement_solution: tuple | None = None
    capture_design: CaptureDesign | None = None
    layer_primes_mm: tuple[float, ...] = ()
    final_position_xy_mm: tuple[float, float] | None = None

    def dispose(self):
        self.workspace.cleanup()


@dataclass(frozen=True, slots=True)
class PostprocessorPlacement:
    """Source-bound placement checks shared by generation and the position editor.

    The resolver owns the unsampled original-motion index and route cache.
    Calls must be sequential; a managed worker supplies its cancellation event.
    """
    request: PostprocessorRequest
    geometry: BedGeometry
    object_segments: tuple[LineSegment3D, ...]
    base_width_mm: float
    height_mm: float
    settings: PostprocessorSettings
    resolve: Callable[..., tuple]
    printhead: object
    reserved_radius_mm: float
    position_valid: Callable[..., bool]
    head_clearance_required: bool
    brim_width_mm: float = 0.0
    brim_gap_mm: float = 0.0
    brim_line_width_mm: float = 0.0
    regions: PlacementRegions | None = None


class PostprocessorPlacementError(ValueError):
    def __init__(self, reason, note=""):
        self.reason = reason or "Für die gewählten Turmmaße und Abstände ist auf dem Druckbett kein geeigneter Platz frei."
        super().__init__("Keine sichere Turm- und Warteposition mit freien Originalbahnen und kollisionsfreien Fahrwegen gefunden. "
            "Abstände, Turmmaße oder manuelle Turm-/Warteposition prüfen. " + self.reason + (" " + note if note else ""))


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


def _final_park_block(state, settings, route):
    """One departure to the virtual tower edge, without another tower layer."""
    lines = [BEGIN, FINAL_PARK, f"; layer_z = {_fmt(state.z)}", "G90", "M83"]
    lines.append(f"G1 E{_fmt(-settings.retract_mm/state.extrusion_factor)} F{_fmt(settings.retract_speed_mm_s*6000/state.speed_factor_percent)}")
    for i, (x,y) in enumerate(route[1:]):
        z = f" Z{_fmt(state.z+settings.z_hop_mm)}" if i == 0 and settings.z_hop_mm else ""
        lines.append(f"G1 X{_fmt(x)} Y{_fmt(y)}{z} F{_fmt(settings.travel_speed_mm_s*6000/state.speed_factor_percent)}")
    lines += [PARKED, f"G92 E{_fmt(state.e)}", "G91" if state.xyz_relative else "G90",
        "M83" if state.extrusion_relative else "M82", f"G1 F{_fmt(state.feedrate_mm_min)}", END]
    return lines


def _parked_end_instruction(parsed, state, max_z):
    """Keep shutdown and E commands, replacing the slicer's spatial parking."""
    if parsed.command == "G28" and parsed.parameters and set(parsed.parameters).issubset({"X", "Y"}):
        return "; SACRIFICIAL_TOWER_REPLACED_END_MOVE: " + parsed.raw_text
    if parsed.command not in {"G0", "G1", "G2", "G3"} or not any(axis in parsed.parameters for axis in "XYZIJKR"):
        return parsed.raw_text
    axes = {key: value for key, value in parsed.parameters.items() if key in {"E", "F"}}
    if "Z" in parsed.parameters:
        z = parsed.parameters["Z"]
        height = state.z + max(0.0, z) if state.xyz_relative else max(state.z, z)
        if height > max_z + 1e-6:
            raise ValueError("Die Endsequenz überschreitet mit dem abschließenden Sicherheitshub die maximale Druckhöhe.")
        if height > state.z + 1e-6:
            axes["Z"] = height-state.z if state.xyz_relative else height
    return ("G1 " + " ".join(key + _fmt(value) for key, value in axes.items()) + "\n" if axes else "") + (
        "; SACRIFICIAL_TOWER_REPLACED_END_MOVE: " + parsed.raw_text)


def _scan(request, cancellation_event, *, collector=None, motion_collector=None, model_wipes=None):
    """Capture the exact modal state immediately after each layer's last deposit."""
    def source_setting(name):
        setting = request.snapshot.metadata.config_for(name)
        return setting.value if setting is not None and setting.valid else request.profile.effective_values.get(name)

    if any(profile_flag(source_setting(name)) is True for name in ("spiral_mode", "spiral_vase")):
        raise ValueError("Spiraldruck wird vom Postprozessor nicht unterstützt.")
    scarf = profile_flag(source_setting("has_scarf_joint_seam")) is True
    for name in ("seam_slope_type", "scarf_seam_placement", "filament_scarf_seam_type"):
        value = source_setting(name)
        while isinstance(value, (list, tuple)):
            value = value[0] if value else None
        scarf |= value is not None and str(value).strip().lower() not in {"", "none", "nowhere", "off", "0", "nil"}
    starts = [layer.first_deposition_line for layer in request.snapshot.layers]
    tracker = PostprocessorStateTracker(request.profile.installation.adapter_id)
    endpoints = {}
    tools = set()
    extrusion_declared = False
    pending_error = None
    conditional_depth = 0
    stroke, stroke_layer = (), -1
    first, last = starts[0], request.snapshot.layers[-1].end_line
    for parsed in iter_parsed_gcode_lines(request.prepared_source.analysis_gcode_path):
        if parsed.number % 2000 == 0:
            _check_cancel(cancellation_event)
        command = normalize_command(parsed.command or "")
        if any(marker in parsed.raw_text for marker in (BEGIN, LEGACY_POSTPROCESSOR_BEGIN, "COOLING_TOWER_BEGIN")):
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
        if collector is not None:
            collector.consume(parsed, event)
        if motion_collector is not None:
            motion_collector.consume(parsed, event)
        if isinstance(event, Movement) and event.category != "deposition" and event.endpoint_distance_xy_mm > 1e-9:
            stroke = ()
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
        planar = abs(event.end_z - layer.z_mm) <= 0.001 and abs(event.delta_z) <= 0.001
        in_layer_scarf = (scarf and min(event.start_z, event.end_z) >= layer.z_mm-layer.height_mm-0.001
            and max(event.start_z, event.end_z) <= layer.z_mm+0.001)
        if not planar and not in_layer_scarf:
            raise ValueError(f"Nichtplanare Extrusion in Zeile {parsed.number}: Z={event.start_z:.4f} → "
                f"{event.end_z:.4f} mm, erwartete Schichthöhe Z={layer.z_mm:.4f} mm. "
                "Spiral- und sequentieller Druck werden nicht unterstützt.")
        if model_wipes is not None:
            a, b = (event.start_x, event.start_y), (event.end_x, event.end_y)
            wipe_planar = abs(event.end_z-layer.z_mm) <= 1e-6 and abs(event.delta_z) <= 1e-6
            if wipe_planar and not event.is_arc and math.dist(a, b) > 1e-9:
                if stroke_layer != index or not stroke or math.dist(stroke[-1], a) > 1e-6:
                    stroke = (a,)
                stroke = supported_tail((*stroke, b))
                length = sum(math.dist(x, y) for x, y in zip(stroke, stroke[1:]))
                model_wipes[index] = tuple(reversed(stroke)) if length >= .2 else ()
            else:
                stroke = ()
                model_wipes[index] = ()
            stroke_layer = index
        endpoints[index] = (parsed.number, copy(state))
    if len(endpoints) != len(starts) or len(tools) != 1 or tools != {0}:
        raise ValueError("Der Postprozessor benötigt planare Schichten mit einem einzelnen Extruder T0.")
    if any(abs(state.z-request.snapshot.layers[index].z_mm) > .001 for index, (_, state) in endpoints.items()):
        raise ValueError("Eine Scarf-Naht endet nicht auf ihrer nominellen Schichthöhe; eine sichere Turmfahrt ist nicht möglich.")
    return endpoints


def _layer_block(state: MachineState, layer, radius, center, settings, line_width, filament, wait_s, *, capture, model_wipe=(), prime_wait_s=None, inner_line_width=None, first_layer=False, closed_bottom=False, shaft_radius=0.0, travel_routes, start_angle=0.0, maximum_flow=None, infill_speed=None, brim_width=0.0, brim_gap=0.0, brim_line_width=None, base_radius=0.0, comments=None, cancellation_event=None):
    """Print an intermediate tower layer and restore the original print state."""
    x, y = center
    start = capture.print_start
    hop = max(state.z, layer.z_mm) + settings.z_hop_mm
    factor = state.speed_factor_percent / 100
    travel_speed = settings.travel_speed_mm_s / factor
    retract = settings.retract_mm / state.extrusion_factor
    restart = (settings.retract_mm + settings.restart_extra_mm) / state.extrusion_factor if retract else 0.0
    if restart < 0:
        raise ValueError("Die negative Profil-Wiederanlaufmenge übersteigt die Rückzugslänge.")
    restore_speed = (settings.unretract_speed_mm_s or settings.retract_speed_mm_s) / factor
    lines = [BEGIN, f"; layer_z = {_fmt(layer.z_mm)}", "G90", "M83"]
    comments = comments or FeatureComments.for_adapter("prusa_slicer")
    lines.append(comments.wipe(False))
    def emit(code):
        lines.append(code)
    def move(**axes):
        emit("G1 " + " ".join(key + _fmt(value) for key, value in axes.items()))
    if len(model_wipe) > 1:
        emit(MODEL_WIPE_MARKER)
        distances = tuple(math.dist(a, b) for a, b in zip(model_wipe, model_wipe[1:]))
        total = sum(distances)
        speed = min(20., settings.print_speed_mm_s,
            total*settings.retract_speed_mm_s/retract if retract else 20.)
        covered, sent = 0., 0.
        for point, distance in zip(model_wipe[1:], distances):
            covered += distance
            cumulative = float(_fmt(retract*covered/total))
            move(X=point[0], Y=point[1], E=sent-cumulative, F=speed/factor*60)
            sent = cumulative
    else:
        move(E=-retract, F=settings.retract_speed_mm_s / factor * 60)
    if hop != state.z:
        move(Z=hop, F=600)
    to_wait, to_tower, to_model = travel_routes
    if to_wait:
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
    if brim_width:
        first_brim_radius = base_radius + brim_gap + brim_width - min(
            line_width if brim_line_width is None else brim_line_width, brim_width) / 2
        # Reach the first deposited ring while lifted, including when the
        # independent brim extends beyond the checked tower approach point.
        brim_start = contour_path(center, first_brim_radius, line_width,
            "brim", start_angle, spine_half=capture.spine_half).points[0]
        move(X=brim_start[0], Y=brim_start[1], F=travel_speed * 60)
    elif first_layer or not to_wait:
        move(X=start[0], Y=start[1], F=travel_speed * 60)
    if hop != layer.z_mm:
        move(Z=layer.z_mm, F=600)
    if not first_layer and to_wait:
        emit(CAPTURE_MARKER)
        # The previous layer supports all structural paths. The incoming
        # strand is intercepted at the shell and pulled into its first open
        # chamber, before the head crosses the tower or starts to extrude.
        for point in capture.capture_points[1:]:
            move(X=point[0], Y=point[1], F=min(20., settings.print_speed_mm_s)/factor*60)
        if hop != layer.z_mm:
            move(Z=hop, F=600)
        move(X=start[0], Y=start[1], F=travel_speed*60)
        if hop != layer.z_mm:
            move(Z=layer.z_mm, F=600)
    elif not brim_width:
        move(X=start[0], Y=start[1], F=travel_speed*60)
    emit("; SACRIFICIAL_TOWER_CAPTURE_END")
    move(E=restart, F=restore_speed * 60)
    emit("; sacrificial wipe / prime and " + ("hollow tower / annular foot" if settings.hollow_tower and not closed_bottom else "solid bottom / tower"))
    area = math.pi * (filament / 2) ** 2
    inner_line_width = line_width if inner_line_width is None else inner_line_width
    overlap = layer.height_mm * (1 - math.pi / 4)
    paths = []
    if brim_width:
        brim_line_width = min(line_width if brim_line_width is None else brim_line_width, brim_width)
        # Cover the requested band without crossing its inner gap or outer edge.
        brim_count = max(1, math.ceil((brim_width-brim_line_width) / (brim_line_width-overlap)) + 1)
        step = (brim_width-brim_line_width)/(brim_count-1) if brim_count > 1 else 0
        paths.extend(contour_path(center, base_radius+brim_gap+brim_width-brim_line_width/2-i*step,
            brim_line_width, "brim", start_angle, spine_half=capture.spine_half) for i in range(brim_count))
    from itertools import chain
    body = iter(tower_paths(center, radius+line_width/2,
        capture.core_radius+line_width+(settings.wall_count-1)*(inner_line_width-overlap), line_width,
        inner_line_width, layer.height_mm, settings.wall_count, hollow=settings.hollow_tower,
        first=first_layer, closed_bottom=closed_bottom or not settings.hollow_tower,
        angle=start_angle, spine_half=capture.spine_half))
    outer = next(body)
    # Print every contour first, then the two brace beads out and back. Their
    # model-facing return bead is the final supported departure wipe track.
    paths = chain(paths, (outer,), body,
        capture.internal_paths() if settings.hollow_tower and not closed_bottom else ())
    ring = contour_path(center, radius, line_width, "outer", start_angle, spine_half=capture.spine_half)
    nominal_ring = sum(math.dist(a, b) for a, b in zip(ring.points, ring.points[1:])) * (
        line_width-overlap)*layer.height_mm/area
    prime = additional_prime(wait_s if prime_wait_s is None else prime_wait_s, settings.prime_mm, nominal_ring)
    emit(f"; SACRIFICIAL_TOWER_ADDITIONAL_PRIME_MM {_fmt(prime)}")
    brim_active = False
    for path in paths:
        _check_cancel(cancellation_event)
        current_width, is_brim = path.width, path.feature == "brim"
        if is_brim != brim_active:
            emit("; SACRIFICIAL_TOWER_BRIM_BEGIN" if is_brim else "; SACRIFICIAL_TOWER_BRIM_END")
            brim_active = is_brim
        lines.extend(comments.describe(path.feature, current_width, layer.height_mm))
        extrusion_per_mm = (current_width - overlap) * layer.height_mm / area / state.extrusion_factor
        points = tuple(tuple(float(_fmt(value)) for value in point) for point in path.points)
        prime_per_edge = prime / (len(points)-1) / state.extrusion_factor if path.prime else 0.0
        # Prime while moving on the first ring, rather than leaving a stationary
        # lump at its seam. Include this extra volume in the flow cap as well.
        feature_speed = infill_speed if path.feature == "bottom" and infill_speed is not None else settings.print_speed_mm_s
        previous = points[0]
        move(X=previous[0], Y=previous[1], F=feature_speed/factor*60)
        for point in points[1:]:
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
    emit(DEPARTURE_WIPE_MARKER)
    # The final bead is still soft: retract immediately instead of retracing it.
    move(E=-retract, F=settings.retract_speed_mm_s/factor*60)
    relief = min(hop-layer.z_mm, .05, layer.height_mm*.25)
    if relief > 1e-9:
        move(Z=layer.z_mm+relief, F=600)
    emit(DRY_EXIT_MARKER)
    # One outward draw-off above the fresh surface, without rubbing back and
    # forth. The small relief stays within the requested hop, including zero.
    move(X=capture.exit[0], Y=capture.exit[1], F=min(20., settings.print_speed_mm_s)/factor*60)
    if hop > layer.z_mm+relief+1e-9:
        move(Z=hop, F=600)
    emit("; SACRIFICIAL_TOWER_TRAVEL_TO_MODEL")
    for point in to_model[1:]:
        move(X=point[0], Y=point[1], F=travel_speed * 60)
    if hop != state.z:
        move(Z=state.z, F=600)
    move(E=restart, F=restore_speed * 60)
    emit("G92 E" + _fmt(state.e))
    emit("G91" if state.xyz_relative else "G90")
    emit("M83" if state.extrusion_relative else "M82")
    move(F=state.feedrate_mm_min)
    lines.extend(comments.restore())
    emit(END)
    return lines


class PostprocessorService:
    def __init__(self, temporary_root):
        self.temporary_root = Path(temporary_root)

    def placement_context(self, request, *, cancellation_event=None, progress_callback=None):
        return self.prepare(request, cancellation_event=cancellation_event, progress_callback=progress_callback, placement_only=True)

    def prepare(self, request, *, cancellation_event=None, progress_callback=None, placement_only=False):
        notify = progress_callback or (lambda _p, _s: None)
        notify(0, "Originalquelle und Druckprofil prüfen …")
        request.validate_source()
        _check_cancel(cancellation_event)
        source = request.prepared_source.analysis_gcode_path
        motion_analyzer = GCodeAnalysisService(postprocessor_mode=True)
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
        settings, profile_notes = resolve_profile_settings(request.settings, values)
        waits = tuple(max(0.0, settings.target_layer_time_s - layer.total_time_s) for layer in layers)
        needed = [i for i, wait in enumerate(waits[:-1]) if wait > 0.001]
        count = needed[-1] + 1 if needed else 0
        if not settings.automatic_height:
            count = min(len(layers)-1, bisect_right([layer.z_mm for layer in layers], settings.height_mm + 1e-6))
            if count < (needed[-1] + 1 if needed else 0):
                raise ValueError("Die manuelle Turmhöhe endet vor dem letzten nötigen Wartebefehl.")
            if settings.height_mm > layers[-1].z_mm + 0.001:
                raise ValueError("Die manuelle Turmhöhe darf die Modellhöhe nicht überschreiten.")
        height = layers[count - 1].z_mm if count else 0.0
        design = capture_design(height, waits[:count],
            diameter=None if settings.automatic_diameter else settings.diameter_mm)
        diameter = design.diameter_mm
        base = automatic_capture_base(design, height) if settings.automatic_base else settings.base_width_mm
        if base < diameter:
            raise ValueError("Die Standfußbreite muss mindestens dem Turmdurchmesser entsprechen.")
        geometry = parse_bed_geometry(values)
        if geometry is None:
            raise ValueError("Im bestätigten Druckprofil fehlt eine eindeutige Druckbettgeometrie.")
        geometry = with_exclusions(geometry, settings.exclusions)
        head = printhead_envelope(values, geometry)
        profile_notes += (head.note,)
        max_z = _number(values, "printable_height", _number(values, "max_print_height", 0))
        if max_z <= 0:
            raise ValueError("Im bestätigten Druckprofil fehlt die maximale Druckhöhe.")
        if layers[-1].z_mm + settings.z_hop_mm > max_z:
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
        minimum_hollow_diameter = 2 * max(thicknesses, default=width + inner_width*(settings.wall_count-1)) + 6*inner_width
        if settings.automatic_diameter and settings.hollow_tower:
            diameter = max(diameter, minimum_hollow_diameter)
        design = configure_capture_design(replace(design, diameter_mm=diameter),
            max(thicknesses, default=width+inner_width*(settings.wall_count-1)), inner_width)
        if settings.automatic_base:
            first_thickness = _wall_thickness((first_layer.line_width_mm,)*settings.wall_count, layers[0].height_mm)
            base = automatic_capture_base(design, height,
                first_layer_minimum_depth=2*first_thickness+first_layer.line_width_mm)
        if base < diameter:
            raise ValueError("Die Standfußbreite muss mindestens dem Turmdurchmesser entsprechen.")
        if settings.hollow_tower and diameter < minimum_hollow_diameter:
            raise ValueError("Der Durchmesser ist für die gewählte Wandstärke und die unterstützten Fangstege zu klein.")
        if diameter > 100:
            raise ValueError("Die nötige Auffanggeometrie überschreitet den unterstützten Turmdurchmesser von 100 mm.")
        if settings.automatic_prime:
            capacities = []
            for i, layer in enumerate(layers[:count]):
                frame = capture_frame((0., 0.), (1., 0.), diameter/2, diameter/2,
                    widths[i], inner_widths[i], layer.height_mm, settings.wall_count,
                    design.rib_count, depth_mm=design.depth_mm)
                ring = contour_path((0., 0.), diameter/2-widths[i]/2,
                    widths[i], "outer", math.pi, spine_half=frame.spine_half)
                length = sum(math.dist(a, b) for a, b in zip(ring.points, ring.points[1:]))
                capacities.append(length*(widths[i]-layer.height_mm*(1-math.pi/4))*layer.height_mm/(math.pi*(filament/2)**2))
            ceiling = additional_prime(design.reserve_wait_s, 1.0, max(capacities, default=0.0))
            settings = replace(settings, prime_mm=ceiling)
            profile_notes += (f"Zusätzliches Primen: automatische Obergrenze {ceiling:.3f} mm Filament; tatsächliche Zugabe je Pause und Bahnkapazität begrenzt.",)
        if not settings.hollow_tower:
            design = replace(design, shape="solid_capsule", rib_count=0)
        profile_notes += (("Abstreifturm: flache Kapsel mit gerader Fangseite, kurzem Stützsteg und getrennter Abfahrseite; konkaver Standfuß mit unterstützter Innenverjüngung."
            if settings.hollow_tower else "Abstreifturm: gefüllte Kapsel mit konkavem Standfuß und getrennten Einfang-/Abfahrbereichen."),
            f"Auffangreserve: {design.reserve_wait_s:g} s größtes ursprüngliches Zeitdefizit; geometrischer Richtwert, keine gemessene Oozing-Menge.")
        if any(layer.height_mm > nozzle * 0.85 for layer in layers[:count]):
            raise ValueError("Die Schichthöhe ist für die Düse des Turms zu groß.")
        settings = flow_limited_speed(settings, values, (width, inner_width), tuple(layer.height_mm for layer in layers[:count]))
        first_layer = replace(first_layer, wall_speed_mm_s=min(first_layer.wall_speed_mm_s, settings.print_speed_mm_s),
            infill_speed_mm_s=min(first_layer.infill_speed_mm_s, settings.print_speed_mm_s))
        notify(10, "Pre-Slice und Druckzustände prüfen …")
        collector = DepositionToolpathCollector()
        motion_collector = OriginalMotionCollector()
        model_wipes = {}
        try:
            endpoints = _scan(replace(request, snapshot=source_snapshot), cancellation_event,
                collector=collector, motion_collector=motion_collector, model_wipes=model_wipes)
            _check_cancel(cancellation_event)
            paths = collector.finish(expected_layer_count=len(layers))
        finally:
            collector.close()
        final_line, final_state = endpoints[len(layers)-1]
        original_exclusions_clear(source, tuple(zone.polygon for zone in settings.exclusions), head.radius_mm,
            cancellation_event=cancellation_event, end_line=final_line)
        notify(18, "Modellbahnen rekonstruieren …")
        if paths.occupied_bounds is None:
            raise ValueError("Die Modellfläche konnte nicht rekonstruiert werden.")
        occupied = paths.occupied_bounds
        model_clearance = settings.clearance_mm
        wait_clearance = settings.wait_clearance_mm
        # Model brim enablement/width never controls the independently generated tower brim.
        brim_width, brim_gap = settings.tower_brim_width_mm, settings.tower_brim_gap_mm
        brim_keys = (("first_layer_extrusion_width", "perimeter_extrusion_width", "extrusion_width") if prusa_widths
            else ("initial_layer_line_width", "inner_wall_line_width", "line_width"))
        brim_line_width = _profile_line_width(values, brim_keys, nozzle, nozzle * 1.1,
            percent_base=layers[0].height_mm if prusa_widths else nozzle) if brim_width else 0.0
        if brim_width and brim_line_width <= layers[0].height_mm:
            raise ValueError("Die Brim-Linienbreite muss größer als die erste Turm-Schichthöhe sein.")
        if brim_width and brim_width <= layers[0].height_mm * (1-math.pi/4):
            raise ValueError("Die Turm-Brimbreite ist für die erste Schichthöhe zu klein.")
        brim_line_width = min(brim_line_width, brim_width)
        model_line_margin = max(general_width, inner_width, width, first_layer.line_width_mm) / 2
        foot = full_infill_foot_taper(tuple(layer.z_mm for layer in layers[:count]),
            base / 2, diameter / 2, layers[-1].z_mm) if count else None
        outer_radii = [foot.radius(layer.z_mm) for layer in layers[:count]]
        concave_base = base
        if settings.automatic_base:
            floors = capture_floor_reserve(design, tuple(layer.z_mm for layer in layers[:count]), layers[-1].z_mm)
            for i, floor_radius in enumerate(floors):
                outer_radii[i] = max(outer_radii[i], floor_radius)
            base = max((2*r for r in outer_radii[:2]), default=base)
        design = replace(design, concave_base_width_mm=concave_base,
            bottom_widths_mm=tuple(2*r for r in outer_radii[:2]))
        reserved = base / 2 + max(max(width, first_layer.line_width_mm) / 2, brim_width+brim_gap if brim_width else 0.0)
        radii = [r-widths[i]/2 for i,r in enumerate(outer_radii)]
        holes = supported_foot_holes([radii[i]+widths[i]/2 for i in range(count)],
            diameter/2, thicknesses, [layer.height_mm for layer in layers[:count]], inner_widths)
        contact_indices, contact_index = [], 0
        for i in range(count):
            contact_indices.append(contact_index)
            if i and waits[i] > .001:
                contact_index += 1
        @lru_cache(maxsize=4)
        def capture_frames(point, park):
            return tuple(capture_frame(point, park, radii[i]+widths[i]/2, diameter/2,
                widths[i], inner_widths[i], layer.height_mm, settings.wall_count,
                design.rib_count, contact_index=contact_indices[i], structural_width=inner_width,
                depth_mm=design.depth_mm, core_radius=holes[i])
                for i, layer in enumerate(layers[:count]))
        insertions = {endpoints[i][0]: i for i in range(count)}
        insertion_heights = {line: layers[i].z_mm for line, i in insertions.items()}
        notify(24, "Originalfahrten und Sicherheitshöhen erfassen …")
        motion_index = motion_collector.finish(insertion_heights, cancellation_event=cancellation_event, end_line=final_line)
        candidate_count = 0
        collision_notes = (head.limitations,
            "Modellabstände: ungekürzte Ablagebahnen und höhenabhängiger Turmquerschnitt; Druckfahrten und Abschlussfahrt geprüft. Slicer-Endparkfahrten ersetzt.",
            "Eigene Sperrflächen gelten als unbekannt hohe Hindernisse; ihre Höhe wird nicht geschätzt.")
        def tower_error(point, settings):
            # The printable polygon is the manufacturer's nozzle travel area;
            # the head may overhang it. Physical keepouts are expanded below.
            if not _circle_fits_bed(point, reserved, settings.edge_clearance_mm, geometry):
                return "Turm: Der vollständige Standfuß unterschreitet den Abstand zur Druckbettkante oder einer gesperrten Profilfläche."
            if any(_point_in_polygon(point, polygon) or _distance_to_polygon_edges(point, polygon) < reserved + head.radius_mm + 1
                    for polygon in geometry.excluded_polygons):
                return "Turm: Der Druckkopf-Abstand zu einer gesperrten Profilfläche ist zu klein."
            if not motion_index.model_clear(point, reserved + model_clearance + model_line_margin,
                    lambda z: (reserved if z <= layers[0].z_mm+.001 else foot.radius(max(foot.start_z, z))) + model_clearance + model_line_margin, height=height):
                return "Turm: Der Abstand zwischen Standfuß beziehungsweise Turmquerschnitt und Modell ist zu klein."
            return None

        def park_error(park, point, settings):
            if not _circle_fits_bed(park, 0, settings.edge_clearance_mm, geometry):
                return "Warteposition: Der Abstand zur Druckbettkante oder einer gesperrten Profilfläche ist zu klein."
            if not motion_index.model_clear(park, wait_clearance+model_line_margin, lambda _z: wait_clearance+model_line_margin):
                return "Warteposition: Der Abstand zum Modell ist zu klein."
            if count and math.dist(park, point) < reserved+wait_clearance:
                return "Warteposition: Der Abstand zum vollständigen Turmfuß ist zu klein."
            return None

        islands = model_travel_islands(motion_index, occupied, model_line_margin, cancellation_event=cancellation_event)
        @lru_cache(maxsize=8192)
        def hard_route(a, b):
            return safe_travel_path(a, b, geometry, margin_mm=head.radius_mm+1)

        @lru_cache(maxsize=8192)
        def preferred_route(a, b):
            return prefer_model_avoiding_route(a, b, geometry, islands, margin_mm=head.radius_mm+1, direct=hard_route(a, b))

        def route(a, b):
            return preferred_route(a, b) if a <= b else tuple(reversed(preferred_route(b, a)))

        @lru_cache(maxsize=8192)
        def route_to_wait(a, park, center):
            obstacle = capture_obstacle(center, park, design, reserved)
            return prefer_model_avoiding_route(a, park, geometry, islands,
                margin_mm=head.radius_mm+1, required_polygons=(obstacle,))

        def final_route_to_tower(center, park):
            origin = (final_state.x, final_state.y)
            target = nearest_capture_point(center, park, design, origin)
            margin = 1+model_line_margin
            if not motion_index.model_clear(target, margin, lambda _z: margin):
                raise ValueError("Die Abschlussposition an der gedachten Turmkontur liegt zu nah am Modell. Turmposition anpassen.")
            # One direct move where physically possible; exclusions still apply.
            return hard_route(origin, target)

        original_settings = settings
        model_center = ((occupied.minimum_x_mm+occupied.maximum_x_mm)/2,
            (occupied.minimum_y_mm+occupied.maximum_y_mm)/2)
        position_fields = ("automatic_position", "center_x_mm", "center_y_mm",
            "automatic_wait_position", "wait_x_mm", "wait_y_mm", "edge_clearance_mm")
        def check_position_settings(settings):
            if replace(settings, **{name: getattr(original_settings, name) for name in position_fields}) != original_settings:
                raise ValueError("Die Platzierungsgrundlage hat sich geändert. Bitte den Positionseditor erneut öffnen.")

        def _resolve_positions(position_settings=None, *, event=None, progress_callback=None):
            nonlocal candidate_count, cancellation_event
            cancellation_event = event
            motion_index.cancellation_event = event
            _check_cancel(event)
            candidate_count = 0
            settings = position_settings or original_settings
            report = progress_callback or (lambda _p, _s: None)
            report(55, "Turm- und Wartepositionen auf freie Abstände prüfen …")
            check_position_settings(settings)
            rejection = None
            def fits(point):
                return tower_error(point, settings) is None
            routes = []
            wait_position = None
            if not count:
                center = ((occupied.minimum_x_mm + occupied.maximum_x_mm)/2, (occupied.minimum_y_mm + occupied.maximum_y_mm)/2)
                parking = [(settings.wait_x_mm, settings.wait_y_mm)]
                if settings.automatic_wait_position:
                    bed = geometry.bounds
                    inset = settings.edge_clearance_mm
                    parking = [(bed.minimum_x_mm+inset+(bed.maximum_x_mm-bed.minimum_x_mm-2*inset)*x/32,
                        bed.minimum_y_mm+inset+(bed.maximum_y_mm-bed.minimum_y_mm-2*inset)*y/32)
                        for x in range(33) for y in range(33)]
                    parking.sort(key=lambda park: math.dist((final_state.x, final_state.y), park))
                for park in parking:
                    _check_cancel(cancellation_event)
                    rejection = park_error(park, center, settings)
                    if rejection:
                        continue
                    try:
                        route((final_state.x, final_state.y), park)
                    except ValueError as error:
                        rejection = "Abschlussfahrt: " + str(error)
                        continue
                    wait_position = park
                    break
                if wait_position is None:
                    raise PostprocessorPlacementError(rejection)
            else:
                candidates = [(settings.center_x_mm, settings.center_y_mm)]
                if settings.automatic_position:
                    bed = geometry.bounds
                    inset = reserved + settings.edge_clearance_mm
                    xs = [bed.minimum_x_mm + inset + (bed.maximum_x_mm-bed.minimum_x_mm-2*inset)*i/32 for i in range(33)]
                    ys = [bed.minimum_y_mm + inset + (bed.maximum_y_mm-bed.minimum_y_mm-2*inset)*i/32 for i in range(33)]
                    candidates = [(x, y) for x in xs for y in ys if fits((x, y))]
                    sample = [endpoints[i][1] for i in range(0, count, max(1, count//64))]
                    candidates.sort(key=lambda point: sum(math.dist((state.x, state.y), point) for state in sample))
                center = None
                for point in candidates:
                    candidate_count += 1
                    _check_cancel(cancellation_event)
                    rejection = tower_error(point, settings)
                    if rejection:
                        continue
                    rejection = motion_index.tower_rejection(point, reserved,
                        head_radius=head.radius_mm, head_height=head.clearance_height_mm,
                        lower_head_radius=head.lower_radius_mm, gantry_height=head.clearance_height_mm)
                    if rejection:
                        continue
                    parking = [(settings.wait_x_mm, settings.wait_y_mm)]
                    if settings.automatic_wait_position:
                        away = math.atan2(point[1]-model_center[1], point[0]-model_center[0])
                        parking = [(point[0]+distance*math.cos(away+angle*math.tau/32),
                            point[1]+distance*math.sin(away+angle*math.tau/32))
                            for distance in (reserved+wait_clearance+.1,
                                reserved+wait_clearance+10, reserved+wait_clearance+25)
                            for angle in range(32)]
                        # Prefer model -> tower -> waiting point, preserving
                        # a fixed dirty arrival side and a separate clean exit.
                        parking.sort(key=lambda park: (model_crossings(park, point, islands),
                            round(alignment_penalty(point, park, model_center), 8),
                            math.dist(park, point) + sum(math.dist((state.x, state.y), park)
                                for state in sample) if settings.automatic_position else math.dist(park, point)))
                    for park in parking:
                        rejection = park_error(park, point, settings)
                        if rejection:
                            continue
                        try:
                            routes = []
                            final_route_to_tower(point, park)
                            frames = capture_frames(point, park)
                            for i in range(count):
                                _check_cancel(cancellation_event)
                                if i % max(1, count//40) == 0:
                                    report(65+int(33*i/count), f"Fahrwege und Sicherheitsabstände prüfen · Schicht {i+1} von {count}")
                                origin = (endpoints[i][1].x, endpoints[i][1].y)
                                departure = model_wipes.get(i, ())[-1] if model_wipes.get(i) else origin
                                entry, exit_point = frames[i].entry, frames[i].exit
                                # Original time decides the route once, before
                                # added tower/travel time reduces the remaining wait.
                                # An empty first leg denotes a direct tower visit.
                                if layers[i].total_time_s >= settings.target_layer_time_s:
                                    routes.append(((), route(departure, entry), route(exit_point, origin)))
                                else:
                                    routes.append((route_to_wait(departure, park, point), route(park, entry), route(exit_point, origin)))
                        except ValueError as error:
                            rejection = "Fahrweg: " + str(error)
                            continue
                        center, wait_position = point, park
                        break
                    if center is not None:
                        break
                if center is None:
                    raise PostprocessorPlacementError(rejection, head.note if head.estimated else "")
            return center, wait_position, routes

        placement_lock = Lock()
        def resolve_positions(position_settings=None, *, event=None, progress_callback=None):
            while not placement_lock.acquire(timeout=.05):
                _check_cancel(event)
            try:
                return _resolve_positions(position_settings, event=event, progress_callback=progress_callback)
            finally:
                placement_lock.release()

        origins_connected = None
        def reachable(point=None, *, event=None):
            nonlocal origins_connected
            while not placement_lock.acquire(timeout=.05):
                _check_cancel(event)
            try:
                _check_cancel(event)
                if not count:
                    return False
                anchor = (endpoints[0][1].x, endpoints[0][1].y)
                if origins_connected is None:
                    try:
                        for origin in {(endpoints[i][1].x, endpoints[i][1].y) for i in range(count)} | {(final_state.x, final_state.y)}:
                            _check_cancel(event)
                            hard_route(anchor, origin)
                    except ValueError:
                        origins_connected = False
                    else:
                        origins_connected = True
                if not origins_connected:
                    return False
                if point is None:
                    return True
                try:
                    hard_route(anchor, point)
                except ValueError:
                    return False
                return True
            finally:
                placement_lock.release()

        def position_valid(kind, point, position_settings, *, event=None):
            nonlocal origins_connected
            if kind not in {"tower", "wait"}:
                raise ValueError("Unbekanntes Positionsziel.")
            check_position_settings(position_settings)
            if not count or any(not math.isfinite(v) or not -2000 <= v <= 2000 for v in point):
                return False
            while not placement_lock.acquire(timeout=.05):
                _check_cancel(event)
            try:
                _check_cancel(event)
                motion_index.cancellation_event = event
                center = point if kind == "tower" else (position_settings.center_x_mm, position_settings.center_y_mm)
                park = point if kind == "wait" else (position_settings.wait_x_mm, position_settings.wait_y_mm)
                if tower_error(center, position_settings) or park_error(park, center, position_settings):
                    return False
                if motion_index.tower_rejection(center, reserved, head_radius=head.radius_mm,
                        head_height=head.clearance_height_mm, lower_head_radius=head.lower_radius_mm,
                        gantry_height=head.clearance_height_mm):
                    return False
                anchor = (endpoints[0][1].x, endpoints[0][1].y)
                if origins_connected is None:
                    try:
                        for origin in {(endpoints[i][1].x, endpoints[i][1].y) for i in range(count)} | {(final_state.x, final_state.y)}:
                            _check_cancel(event)
                            hard_route(anchor, origin)
                    except ValueError:
                        origins_connected = False
                    else:
                        origins_connected = True
                if not origins_connected:
                    return False
                try:
                    # An obstacle strictly inside free bed space cannot split
                    # the connected source region. Near edges/keepouts check
                    # every distinct departure, otherwise one anchor suffices.
                    origins = {anchor}
                    if position_settings.edge_clearance_mm < 3 or geometry.excluded_polygons:
                        origins = {model_wipes.get(i, ())[-1] if model_wipes.get(i) else
                            (endpoints[i][1].x,endpoints[i][1].y) for i in range(count)
                            if layers[i].total_time_s < settings.target_layer_time_s}
                    for origin in origins:
                        _check_cancel(event)
                        route_to_wait(origin, park, center)
                    final_route_to_tower(center, park)
                    hard_route(park, center)
                except ValueError:
                    return False
                # The complete tower foot encloses every local capture/rail
                # point and is free of expanded physical keepouts.
                return True
            finally:
                placement_lock.release()

        notify(28, "Sichere Turm- und Wartepositionen bestimmen …")
        placement = PostprocessorPlacement(request, geometry, paths.object_segments, base, height, settings, resolve_positions,
            head, reserved, position_valid, bool(geometry.excluded_polygons) or motion_index.has_lowered_tower_moves, brim_width, brim_gap, brim_line_width,
            PlacementRegions(geometry, motion_index, reserved_radius=reserved,
                tower_radius_at_z=lambda z: reserved if z <= layers[0].z_mm+.001 or foot is None else foot.radius(max(foot.start_z, z)),
                height=height, model_margin=model_clearance+model_line_margin,
                wait_margin=wait_clearance+model_line_margin, head=head, reachable=reachable))
        if placement_only:
            return placement
        center, wait_position, routes = placement.resolve(event=cancellation_event)
        frames = capture_frames(center, wait_position)
        wipe_angles = tuple(frame.angle+math.pi for frame in frames)
        final_route = final_route_to_tower(center, wait_position) if count else route((final_state.x, final_state.y), wait_position)
        final_position = final_route[-1]
        protected_roots = (request.profile.installation.executable_path.parent, *request.profile.installation.profile_roots)
        ensure_writable_output(self.temporary_root, protected_roots=protected_roots)
        self.temporary_root.mkdir(parents=True, exist_ok=True)
        workspace = tempfile.TemporaryDirectory(prefix="postprocessor_", dir=self.temporary_root)
        try:
            output = Path(workspace.name) / "postprocessed.gcode"
            tower_collector = []
            brim_collector = []
            travel_collector = []
            wait_points = []
            wait_point_layers = []
            layer_primes = [0.0 for _ in layers]
            tower_tracker = PostprocessorStateTracker(request.profile.installation.adapter_id)
            from cooling_tower.gcode.parser import GCodeLine, parse_gcode_line
            def render(destination, actual_waits, *, prime_waits=None, collect=False, final_times=None):
                with source.open("rb") as original, destination.open("wb") as target:
                    comments = FeatureComments.for_adapter(request.profile.installation.adapter_id)
                    end_tracker = None
                    target.write(b"; SACRIFICIAL_TOWER_POSTPROCESSED\n")
                    clocks = [0.0]
                    for seconds in final_times or ():
                        clocks.append(clocks[-1] + seconds)
                    for number, raw in enumerate(original, 1):
                        if number % 2000 == 0:
                            _check_cancel(cancellation_event)
                        text = raw.decode("utf-8-sig", errors="replace").strip()
                        if end_tracker is not None:
                            parsed = parse_gcode_line(GCodeLine(number, text))
                            rewritten = _parked_end_instruction(parsed, end_tracker.state, max_z)
                            if rewritten != parsed.raw_text:
                                raw = (rewritten + "\n").encode("utf-8")
                            for instruction in rewritten.splitlines():
                                end_tracker.process_line(parse_gcode_line(GCodeLine(number, instruction)))
                        comments.observe(text)
                        # Anycubic's original cumulative clock becomes stale after
                        # processing. Replace only these advisory comments in the
                        # output, retaining calibrated times plus the motion delta.
                        if final_times is not None and re.fullmatch(r"; estimated printing time \(normal mode\) = .* = [\d.eE+-]+", text):
                            continue
                        target.write(raw)
                        if final_times is not None and (text.startswith(LAYER_TIME_MARKER + " ") or text == END_TIME_MARKER):
                            index = len(final_times) if text == END_TIME_MARKER else int(text.split()[2])
                            if not 0 <= index < len(clocks):
                                raise ValueError("Ungültige native Zeitmarkierung im Pre-Slice.")
                            target.write(f"; estimated printing time (normal mode) = Sacrificial Tower = {clocks[index]:.6f}\n".encode("ascii"))
                        if number not in insertions and number != final_line:
                            continue
                        i = insertions.get(number, len(layers)-1)
                        layer = layers[i]
                        state = endpoints[i][1]
                        layer_settings = replace(settings, print_speed_mm_s=min(settings.print_speed_mm_s,
                            first_layer.wall_speed_mm_s)) if i == 0 else settings
                        block = _layer_block(state, layer, radii[i], center, layer_settings, widths[i], filament,
                            actual_waits[i], capture=frames[i], model_wipe=model_wipes.get(i, ()),
                            prime_wait_s=(prime_waits or actual_waits)[i],
                            inner_line_width=inner_widths[i], first_layer=i == 0, closed_bottom=i < 2,
                            shaft_radius=diameter/2, travel_routes=routes[i],
                            start_angle=wipe_angles[i], maximum_flow=profile_flow_limit(values),
                            infill_speed=min(settings.print_speed_mm_s, first_layer.infill_speed_mm_s) if i == 0 else None,
                            brim_width=brim_width if i == 0 else 0, brim_gap=brim_gap, brim_line_width=brim_line_width, base_radius=base/2,
                            comments=comments, cancellation_event=cancellation_event) if number in insertions else []
                        if number == final_line:
                            block = _final_park_block(state, settings, final_route)
                            end_tracker = PostprocessorStateTracker(request.profile.installation.adapter_id)
                            end_tracker.state = copy(state)
                            for instruction in block:
                                end_tracker.process_line(parse_gcode_line(GCodeLine(number, instruction)))
                        if not raw.endswith(b"\n"):
                            target.write(b"\n")
                        target.write(("\n".join(block) + "\n").encode("utf-8"))
                        # Reconstruct the displayed tower from the emitted instructions.
                        tower_tracker.state = copy(state)
                        wait_travel = bool(routes[i][0]) if i < count else True
                        brim_active = False
                        for instruction in block if collect else ():
                            if instruction.startswith("; SACRIFICIAL_TOWER_ADDITIONAL_PRIME_MM "):
                                layer_primes[i] = float(instruction.rsplit(" ", 1)[1])
                            if instruction == "; SACRIFICIAL_TOWER_BRIM_BEGIN":
                                brim_active = True
                            elif instruction == "; SACRIFICIAL_TOWER_BRIM_END":
                                brim_active = False
                            if instruction == CAPTURE_MARKER or instruction.startswith("; sacrificial wipe / prime and "):
                                wait_travel = False
                            elif instruction == FINAL_PARK:
                                wait_travel = True
                            parsed = parse_gcode_line(GCodeLine(1, instruction))
                            event = tower_tracker.process_line(parsed)
                            if parsed.command == "G4" and parsed.parameters.get("P", 0) > 0:
                                current = tower_tracker.state
                                point = Point3D(current.x, current.y, current.z)
                                if not wait_points or wait_points[-1] != point:
                                    wait_points.append(point)
                                    wait_point_layers.append(i)
                            if isinstance(event, Movement) and event.category == "deposition":
                                (brim_collector if brim_active else tower_collector).append(LineSegment3D(Point3D(event.start_x, event.start_y, event.start_z),
                                    Point3D(event.end_x, event.end_y, event.end_z)))
                            elif isinstance(event, Movement) and event.endpoint_distance_xyz_mm > 1e-6:
                                segment = LineSegment3D(Point3D(event.start_x, event.start_y, event.start_z),
                                    Point3D(event.end_x, event.end_y, event.end_z))
                                travel_collector.append((segment, wait_travel, i))
                        if len(tower_collector) > 120_000:
                            tower_collector[:] = tower_collector[::2]
                        if len(travel_collector) > 60_000:
                            travel_collector[:] = travel_collector[::2]
                    if end_tracker is None or math.dist((end_tracker.state.x, end_tracker.state.y), final_position) > 1e-5:
                        raise ValueError("Die Endsequenz verlässt die geprüfte Abschlussposition. Export gesperrt.")
            notify(35, "Sichere Fahrwege und hohle Turmbahnen berechnen …")
            timing_path = Path(workspace.name) / "timing.gcode"
            notify(55, "Schichtzeiten einschließlich Fahrwegen, Abstreifen und Primen auswerten …")
            if len(raw_snapshot.layers) != len(layers) or any(abs(a.z_mm-b.z_mm) > .001 for a, b in zip(raw_snapshot.layers, layers)):
                raise ValueError("Originalzeiten und rekonstruierte Druckschichten stimmen nicht überein.")
            reference_layers = raw_snapshot.layers
            if request.profile.installation.adapter_id == "anycubic_slicer_next" and read_slicer_layer_times(source) is not None:
                # Native clocks stop before machine_end_gcode. Compare against
                # the same prefix, retaining footer metadata but no shutdown
                # moves; otherwise their removed duration is subtracted twice.
                reference_path = Path(workspace.name)/"native_reference.gcode"
                with source.open("rb") as original, reference_path.open("wb") as target:
                    ended = False
                    for number, raw in enumerate(original,1):
                        if number % 2000 == 0:
                            _check_cancel(cancellation_event)
                        ended = ended or raw.strip() == END_TIME_MARKER.encode("ascii")
                        if not ended or raw.lstrip().startswith(b";"):
                            target.write(raw)
                try:
                    reference_layers = motion_analyzer.analyze(reference_path,
                        cancellation_callback=lambda: cancellation_event is not None and cancellation_event.is_set()).layers
                except AnalysisCancelled as error:
                    raise PreviewCancelled() from error
                reference_path.unlink()
                if len(reference_layers) != len(layers) or any(abs(a.z_mm-b.z_mm) > .001 for a,b in zip(reference_layers,layers)):
                    raise ValueError("Die native Abschlusszeit konnte nicht eindeutig abgegrenzt werden.")
            # Priming depends on the actual pause and itself costs time when
            # limited by flow. Solve both together instead of timing a different
            # extrusion amount from the one written into the final file.
            prime_waits = waits
            for attempt in range(16):
                _check_cancel(cancellation_event)
                render(timing_path, tuple(0.0 for _ in layers), prime_waits=prime_waits)
                try:
                    timing = motion_analyzer.analyze(timing_path,
                        cancellation_callback=lambda: cancellation_event is not None and cancellation_event.is_set())
                except AnalysisCancelled as error:
                    raise PreviewCancelled() from error
                if timing.layer_count != len(layers) or any(layer.untimed_event_count for layer in timing.layers):
                    raise ValueError("Die erzeugten Turm- und Fahrbahnen konnten nicht eindeutig zeitlich ausgewertet werden.")
                motion_deltas = tuple(new.total_time_s-old.total_time_s for new, old in zip(timing.layers, reference_layers))
                base_times = tuple(original.total_time_s+delta for original, delta in zip(layers, motion_deltas))
                waits = tuple(math.ceil(max(0, settings.target_layer_time_s-seconds-1e-9)*1000)/1000
                    if i < count else 0.0 for i, seconds in enumerate(base_times))
                if all(abs(a-b) <= .001 for a, b in zip(prime_waits, waits)):
                    break
                # Damping also handles very small supported beads and low flow
                # limits, where a direct fixed-point update can oscillate.
                prime_waits = waits if attempt == 0 else tuple((a+b)/2 for a, b in zip(prime_waits, waits))
            else:
                raise ValueError("Wartezeit und bedarfsgerechtes Primen konnten nicht stabil gemeinsam berechnet werden. Export gesperrt.")
            final_times = tuple(seconds + wait for seconds, wait in zip(base_times, waits))
            notify(80, "Nur verbleibende Wartezeiten einfügen und Vorschau rekonstruieren …")
            render(output, waits, prime_waits=waits, collect=True, final_times=final_times)
            timing_path.unlink()
            notify(95, "Fertigen G-Code und alle Schichtzeiten abschließend prüfen …")
            try:
                verified = GCodeAnalysisService().analyze(output,
                    cancellation_callback=lambda: cancellation_event is not None and cancellation_event.is_set())
            except AnalysisCancelled as error:
                raise PreviewCancelled() from error
            if (verified.layer_count != len(layers)
                    or any(layer.untimed_event_count or abs(layer.z_mm-original.z_mm) > .001
                        or (index < len(layers)-1 and layer.total_time_s < settings.target_layer_time_s - .005)
                        or abs(layer.total_time_s-planned) > .02
                        for index, (layer, original, planned) in enumerate(zip(verified.layers, layers, final_times)))):
                raise ValueError("Die abschließende G-Code-Prüfung bestätigt die geplanten Schichtzeiten nicht. Export gesperrt.")
            _check_cancel(cancellation_event)
            request.validate_source()
            segments = tuple(tower_collector)
            seams = read_seam_points(output, cancellation_event=cancellation_event)
            scene = PreviewScene(paths.object_segments, segments, geometry.bounds, center,
                paths.source_segment_count, len(paths.object_segments) + len(segments) + len(brim_collector), height,
                brim_segments=tuple(brim_collector),
                seam_points=seams,
                notes=("Rekonstruierte G-Code-Koordinaten; Schichtzeiten enthalten Fahrwege, Turmdruck, Primen und Restwartezeit.",) + profile_notes,
                object_height_mm=layers[-1].z_mm, object_layer_count=len(layers), tower_layer_count=count, bed_geometry=geometry,
                travel_segments=tuple(segment for segment, _wait, _i in travel_collector),
                wait_travel_segments=tuple(segment for segment, wait, _i in travel_collector if wait),
                tower_travel_segments=tuple(segment for segment, wait, _i in travel_collector if not wait),
                wait_points=tuple(wait_points), wait_position_xy_mm=wait_position,
                layer_z_mm=tuple(layer.z_mm for layer in layers),
                wait_travel_layer_indices=tuple(i for _s, wait, i in travel_collector if wait),
                tower_travel_layer_indices=tuple(i for _s, wait, i in travel_collector if not wait),
                wait_point_layer_indices=tuple(wait_point_layers), wait_height_offset_mm=settings.z_hop_mm)
            notify(100, "Postprozessor-Vorschau bereit.")
            return PostprocessorResult(request, workspace, output, sha256_file(output), scene,
                height, diameter if count else 0, base if count else 0, sum(wait > 0 for wait in waits), sum(waits), waits,
                final_times, motion_deltas, settings.z_hop_mm,
                (min(thicknesses), max(thicknesses)) if count and settings.hollow_tower else (0.0, 0.0),
                settings, profile_notes, tuple(layer.total_time_s for layer in layers), tuple(layer.z_mm for layer in layers), wipe_angles, head,
                first_layer, collision_notes, {"indexed_moves": motion_index.move_count, "depositions": motion_index.deposition_count,
                    "candidates": candidate_count, "examined_moves": motion_index.examined_moves}, placement, (center, wait_position, routes),
                design if count else None, tuple(layer_primes), final_position)
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
            raise ValueError("Der Postprozessor exportiert ausschließlich .gcode-Dateien.")
        if sha256_file(result.gcode_path) != result.sha256:
            raise ValueError("Der erzeugte G-Code wurde nach der Vorschau verändert.")
        target.parent.mkdir(parents=True, exist_ok=True)
        previous_digest = sha256_file(target) if target.is_file() else None
        if previous_digest is not None and not overwrite:
            raise FileExistsError("Die Exportdatei existiert bereits. Bitte einen anderen Namen wählen.")
        descriptor, temporary_name = tempfile.mkstemp(prefix=".postprocessor_export_", suffix=".tmp", dir=target.parent)
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
