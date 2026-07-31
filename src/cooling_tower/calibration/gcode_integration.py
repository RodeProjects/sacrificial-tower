from __future__ import annotations

import hashlib
import math
import re
from copy import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from cooling_tower.gcode.parser import (
    MachineState,
    MachineStateTracker,
    Movement,
    iter_parsed_gcode_lines,
    parse_gcode_line,
    GCodeLine,
)
from cooling_tower.models import BedBounds, OccupiedBounds, TowerPlacement
from cooling_tower.services.analysis_service import GCodeAnalysisService


BEGIN_MARKER = "; --- COOLING_TOWER_BEGIN"
END_MARKER = "; --- COOLING_TOWER_END"
_UNSUPPORTED_TEXT = {
    "sequential": "sequentieller Objektdruck",
    "complete_objects": "sequentieller Objektdruck",
    "belt printer": "Endlosbanddruck",
    "nonplanar": "nichtplanarer Druck",
}


class GCodeIntegrationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GCodeSupportAssessment:
    supported: bool
    reasons: tuple[str, ...]
    extrusion_relative: bool | None
    tool_numbers: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class GCodeIntegrationResult:
    output_path: Path
    source_sha256: str
    output_sha256: str
    inserted_layer_count: int
    inserted_line_count: int
    placement: TowerPlacement


def assess_gcode_support(path: str | Path) -> GCodeSupportAssessment:
    source = Path(path)
    data = source.read_bytes()
    reasons: list[str] = []
    if b"\x00" in data:
        reasons.append("Binärer oder verschlüsselter G-Code wird nicht unterstützt.")
    text = data.decode("utf-8-sig", errors="replace")
    folded = text.casefold()
    if BEGIN_MARKER.casefold() in folded or END_MARKER.casefold() in folded:
        reasons.append(
            "Der Quell-G-Code enthält bereits Einfügemarkierungen für einen Kühlturm."
        )
    for marker, description in _UNSUPPORTED_TEXT.items():
        if marker in folded:
            reasons.append(f"Nicht unterstützter Modus erkannt: {description}.")
    tools: set[int] = set()
    modes: list[bool] = []
    for parsed in iter_parsed_gcode_lines(source):
        command = parsed.command or ""
        if re.fullmatch(r"T\d+", command, re.IGNORECASE):
            tools.add(int(command[1:]))
        elif command.upper() == "M82":
            modes.append(False)
        elif command.upper() == "M83":
            modes.append(True)
        elif command.upper() in {"G93", "G95"}:
            reasons.append(
                f"Nicht unterstützter Vorschubmodus {command.upper()}."
            )
    if len(tools) > 1 or (tools and tools != {0}):
        reasons.append(
            "Es wird nur G-Code für einen einzelnen Extruder mit Werkzeug T0 unterstützt."
        )
    extrusion_mode = modes[-1] if modes else None
    if extrusion_mode is None:
        reasons.append("Der Extrusionsmodus M82/M83 ist nicht eindeutig angegeben.")
    return GCodeSupportAssessment(
        supported=not reasons,
        reasons=tuple(dict.fromkeys(reasons)),
        extrusion_relative=extrusion_mode,
        tool_numbers=tuple(sorted(tools)),
    )


def determine_occupied_bounds(path: str | Path) -> OccupiedBounds:
    tracker = MachineStateTracker()
    coordinates: list[tuple[float, float]] = []
    for parsed in iter_parsed_gcode_lines(path):
        event = tracker.process_line(parsed)
        if isinstance(event, Movement) and event.category == "deposition":
            coordinates.extend(
                ((event.start_x, event.start_y), (event.end_x, event.end_y))
            )
    if not coordinates:
        raise GCodeIntegrationError(
            "Es konnte keine gedruckte XY-Fläche bestimmt werden."
        )
    return OccupiedBounds(
        min(item[0] for item in coordinates),
        max(item[0] for item in coordinates),
        min(item[1] for item in coordinates),
        max(item[1] for item in coordinates),
    )


def _numbers(value: object) -> tuple[float, ...]:
    if isinstance(value, (list, tuple)):
        result: list[float] = []
        for item in value:
            if isinstance(item, (list, tuple)):
                result.extend(_numbers(item))
            elif isinstance(item, str) and "x" in item.casefold():
                result.extend(_numbers(item))
            else:
                try:
                    number = float(item)
                    if math.isfinite(number):
                        result.append(number)
                except (TypeError, ValueError, OverflowError):
                    pass
        return tuple(result)
    if isinstance(value, str):
        result = []
        for match in re.findall(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", value):
            try:
                number = float(match)
            except (ValueError, OverflowError):
                continue
            if math.isfinite(number):
                result.append(number)
        return tuple(result)
    try:
        number = float(value)
        return (number,) if math.isfinite(number) else ()
    except (TypeError, ValueError, OverflowError):
        return ()


def parse_bed_bounds(values: Mapping[str, object]) -> BedBounds | None:
    for key in ("printable_area", "bed_shape", "machine_shape"):
        numbers = _numbers(values.get(key))
        if len(numbers) >= 4 and len(numbers) % 2 == 0:
            xs = numbers[0::2]
            ys = numbers[1::2]
            if max(xs) > min(xs) and max(ys) > min(ys):
                return BedBounds(min(xs), max(xs), min(ys), max(ys))
    width_keys = ("printable_width", "machine_width", "bed_size_x")
    depth_keys = ("printable_depth", "machine_depth", "bed_size_y")
    width = next((_numbers(values.get(key)) for key in width_keys if key in values), ())
    depth = next((_numbers(values.get(key)) for key in depth_keys if key in values), ())
    if width and depth and width[0] > 0.0 and depth[0] > 0.0:
        centered = str(values.get("machine_center_is_zero", "false")).casefold() in {
            "1", "true", "yes",
        }
        if centered:
            return BedBounds(-width[0] / 2, width[0] / 2, -depth[0] / 2, depth[0] / 2)
        return BedBounds(0.0, width[0], 0.0, depth[0])
    return None


def _circle_intersects_bounds(
    x: float,
    y: float,
    radius: float,
    bounds: OccupiedBounds,
) -> bool:
    closest_x = min(max(x, bounds.minimum_x_mm), bounds.maximum_x_mm)
    closest_y = min(max(y, bounds.minimum_y_mm), bounds.maximum_y_mm)
    return math.hypot(x - closest_x, y - closest_y) < radius - 1e-9


def propose_tower_placement(
    bed: BedBounds,
    occupied: OccupiedBounds,
    *,
    tower_radius_mm: float,
    object_clearance_mm: float,
    edge_clearance_mm: float,
) -> TowerPlacement:
    if tower_radius_mm <= 0.0:
        raise ValueError("Der Turmradius muss größer als null sein.")
    inset = tower_radius_mm + edge_clearance_mm
    min_x, max_x = bed.minimum_x_mm + inset, bed.maximum_x_mm - inset
    min_y, max_y = bed.minimum_y_mm + inset, bed.maximum_y_mm - inset
    if min_x > max_x or min_y > max_y:
        raise GCodeIntegrationError("Der Kühlturm passt nicht auf das Druckbett.")
    expanded = occupied.expanded(object_clearance_mm)
    center_x = (bed.minimum_x_mm + bed.maximum_x_mm) / 2.0
    center_y = (bed.minimum_y_mm + bed.maximum_y_mm) / 2.0
    candidates = (
        (min_x, min_y), (max_x, min_y), (min_x, max_y), (max_x, max_y),
        (center_x, min_y), (center_x, max_y), (min_x, center_y), (max_x, center_y),
    )
    valid = [
        point for point in candidates
        if not _circle_intersects_bounds(point[0], point[1], tower_radius_mm, expanded)
    ]
    if not valid:
        raise GCodeIntegrationError(
            "Auf dem Druckbett wurde keine kollisionsfreie Position für den "
            "Kühlturm gefunden."
        )
    # Prefer the shortest average travel to the object while retaining all
    # clearances.  This reduces non-productive time and stringing.
    object_center = (
        (occupied.minimum_x_mm + occupied.maximum_x_mm) / 2.0,
        (occupied.minimum_y_mm + occupied.maximum_y_mm) / 2.0,
    )
    x, y = min(valid, key=lambda point: math.dist(point, object_center))
    return TowerPlacement(x, y, tower_radius_mm, bed, object_clearance_mm)


def _tower_center(path: Path) -> tuple[float, float]:
    occupied = determine_occupied_bounds(path)
    return (
        (occupied.minimum_x_mm + occupied.maximum_x_mm) / 2.0,
        (occupied.minimum_y_mm + occupied.maximum_y_mm) / 2.0,
    )


def _format(value: float) -> str:
    rendered = f"{value:.6f}".rstrip("0").rstrip(".")
    return rendered if rendered not in {"-0", ""} else "0"


def _render_tower_movement(
    movement: Movement,
    *,
    offset_x: float,
    offset_y: float,
) -> str:
    command = movement.command if movement.command in {"G0", "G1"} else "G1"
    parts = [command]
    if abs(movement.delta_x) > 1e-9 or abs(movement.delta_y) > 1e-9:
        parts.extend((f"X{_format(movement.end_x + offset_x)}", f"Y{_format(movement.end_y + offset_y)}"))
    if abs(movement.delta_z) > 1e-9:
        parts.append(f"Z{_format(movement.end_z)}")
    if abs(movement.delta_e) > 1e-12:
        parts.append(f"E{_format(movement.delta_e)}")
    if movement.feedrate_mm_min is not None:
        parts.append(f"F{_format(movement.feedrate_mm_min)}")
    return " ".join(parts)


def _restore_modal_state(state: MachineState) -> list[str]:
    lines: list[str] = []
    if state.print_acceleration_mm_s2 is not None:
        command = f"M204 P{_format(state.print_acceleration_mm_s2)}"
        if state.travel_acceleration_mm_s2 is not None:
            command += f" T{_format(state.travel_acceleration_mm_s2)}"
        if state.retract_acceleration_mm_s2 is not None:
            command += f" R{_format(state.retract_acceleration_mm_s2)}"
        lines.append(command)
    lines.append("G91" if state.xyz_relative else "G90")
    if state.extrusion_relative:
        lines.append("M83")
    else:
        lines.extend(("M82", f"G92 E{_format(state.e)}"))
    if state.feedrate_mm_min is not None:
        lines.append(f"G1 F{_format(state.feedrate_mm_min)}")
    return lines


class GCodeIntegrator:
    """Merge slicer-created tower paths while preserving source commands."""

    def __init__(self, analysis_service: GCodeAnalysisService | None = None) -> None:
        self.analysis_service = analysis_service or GCodeAnalysisService()

    def integrate(
        self,
        source_path: str | Path,
        tower_gcode_path: str | Path,
        output_path: str | Path,
        *,
        placement: TowerPlacement,
        source_layers: Sequence[object],
        target_layer_time_s: float,
        travel_speed_mm_s: float = 150.0,
        retraction_length_mm: float = 0.8,
        retraction_speed_mm_s: float = 35.0,
    ) -> GCodeIntegrationResult:
        source = Path(source_path).resolve()
        tower = Path(tower_gcode_path).resolve()
        support = assess_gcode_support(source)
        if not support.supported:
            raise GCodeIntegrationError(" ".join(support.reasons))
        tower_snapshot = self.analysis_service.analyze(tower, force=True)
        tower_tracker = MachineStateTracker()
        events: dict[int, Movement] = {}
        for parsed in iter_parsed_gcode_lines(tower):
            event = tower_tracker.process_line(parsed)
            if isinstance(event, Movement):
                events[event.line_number] = event

        source_tracker = MachineStateTracker()
        source_states: dict[int, MachineState] = {}
        retracted = False
        retracted_by_line: dict[int, bool] = {}
        for parsed in iter_parsed_gcode_lines(source):
            event = source_tracker.process_line(parsed)
            if isinstance(event, Movement) and event.endpoint_distance_xyz_mm <= 1e-9:
                if event.delta_e < -1e-9:
                    retracted = True
                elif event.delta_e > 1e-9:
                    retracted = False
            source_states[parsed.number] = copy(source_tracker.state)
            retracted_by_line[parsed.number] = retracted

        tower_center_x, tower_center_y = _tower_center(tower)
        offset_x = placement.center_x_mm - tower_center_x
        offset_y = placement.center_y_mm - tower_center_y
        blocks: dict[int, list[str]] = {}
        for source_layer in source_layers:
            source_index = int(getattr(source_layer, "index"))
            source_z = float(getattr(source_layer, "z_mm"))
            tower_layer = min(tower_snapshot.layers, key=lambda item: abs(item.z_mm - source_z))
            layer_events = [
                events[number]
                for number in range(tower_layer.first_deposition_line, tower_layer.end_line + 1)
                if number in events
            ]
            layer_events = [
                item for item in layer_events
                if item.category in {
                    "deposition", "travel", "travel_with_retraction",
                    "retraction", "unretraction",
                }
            ]
            if not any(item.category == "deposition" for item in layer_events):
                raise GCodeIntegrationError(f"Tower layer {tower_layer.index} has no deposition path.")
            insertion_line = int(getattr(source_layer, "end_line"))
            state = source_states[insertion_line]
            first_deposition = next(item for item in layer_events if item.category == "deposition")
            first_x = first_deposition.start_x + offset_x
            first_y = first_deposition.start_y + offset_y
            already_retracted = retracted_by_line[insertion_line]
            retract = max(0.0, retraction_length_mm)
            travel_feed = max(1.0, travel_speed_mm_s) * 60.0
            retract_feed = max(1.0, retraction_speed_mm_s) * 60.0
            lines = [
                f"{BEGIN_MARKER} LAYER={source_index} ---",
                f"; Target layer time: {_format(target_layer_time_s)} s",
                "G90",
                "M83",
            ]
            if retract > 0.0 and not already_retracted:
                lines.append(f"G1 E-{_format(retract)} F{_format(retract_feed)}")
            lines.append(f"G0 X{_format(first_x)} Y{_format(first_y)} F{_format(travel_feed)}")
            if retract > 0.0 and not already_retracted:
                lines.append(f"G1 E{_format(retract)} F{_format(retract_feed)}")
            last_acceleration: float | None = None
            for movement in layer_events:
                if movement.acceleration_mm_s2 is not None and (
                    last_acceleration is None
                    or not math.isclose(movement.acceleration_mm_s2, last_acceleration)
                ):
                    last_acceleration = movement.acceleration_mm_s2
                    lines.append(f"M204 S{_format(last_acceleration)}")
                lines.append(
                    _render_tower_movement(
                        movement,
                        offset_x=offset_x,
                        offset_y=offset_y,
                    )
                )
            if retract > 0.0 and not already_retracted:
                lines.append(f"G1 E-{_format(retract)} F{_format(retract_feed)}")
            lines.append(
                f"G0 X{_format(state.x)} Y{_format(state.y)} F{_format(travel_feed)}"
            )
            if retract > 0.0 and not already_retracted:
                lines.append(f"G1 E{_format(retract)} F{_format(retract_feed)}")
            lines.extend(_restore_modal_state(state))
            lines.append(f"{END_MARKER} LAYER={source_index} ---")
            blocks[insertion_line] = lines

        source_bytes = source.read_bytes()
        source_hash = hashlib.sha256(source_bytes).hexdigest()
        raw_lines = source_bytes.splitlines(keepends=True)
        newline = b"\r\n" if b"\r\n" in source_bytes[:8192] else b"\n"
        output = bytearray()
        inserted_lines = 0
        for number, raw in enumerate(raw_lines, start=1):
            output.extend(raw)
            block = blocks.get(number)
            if block:
                if raw and not raw.endswith((b"\r", b"\n")):
                    output.extend(newline)
                encoded = newline.join(line.encode("ascii") for line in block) + newline
                output.extend(encoded)
                inserted_lines += len(block)
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(bytes(output))
        self._validate_result(source_bytes, bytes(output), destination, placement)
        return GCodeIntegrationResult(
            output_path=destination.resolve(),
            source_sha256=source_hash,
            output_sha256=hashlib.sha256(output).hexdigest(),
            inserted_layer_count=len(blocks),
            inserted_line_count=inserted_lines,
            placement=placement,
        )

    @staticmethod
    def _validate_result(
        source_bytes: bytes,
        output_bytes: bytes,
        output_path: Path,
        placement: TowerPlacement,
    ) -> None:
        text = output_bytes.decode("utf-8-sig", errors="replace")
        if text.count(BEGIN_MARKER) != text.count(END_MARKER):
            raise GCodeIntegrationError(
                "Die eingefügten Kühlturmmarkierungen sind nicht ausgeglichen."
            )
        reconstructed = bytearray()
        skipping = False
        for raw_line in output_bytes.splitlines(keepends=True):
            stripped = raw_line.lstrip(b"\xef\xbb\xbf").decode(
                "ascii", errors="ignore"
            ).strip()
            if stripped.startswith(BEGIN_MARKER):
                skipping = True
                continue
            if stripped.startswith(END_MARKER):
                skipping = False
                continue
            if not skipping:
                reconstructed.extend(raw_line)
        if bytes(reconstructed) != source_bytes:
            raise GCodeIntegrationError(
                "Originalbefehle außerhalb der Kühlturmeinfügepunkte wurden verändert."
            )
        inside = False
        tracker = MachineStateTracker()
        for number, line in enumerate(text.splitlines(), start=1):
            if line.startswith(BEGIN_MARKER):
                inside = True
            parsed = parse_gcode_line(GCodeLine(number, line))
            event = tracker.process_line(parsed)
            if inside and isinstance(event, Movement):
                if not (
                    placement.bed_bounds.minimum_x_mm - 1e-6 <= event.end_x <= placement.bed_bounds.maximum_x_mm + 1e-6
                    and placement.bed_bounds.minimum_y_mm - 1e-6 <= event.end_y <= placement.bed_bounds.maximum_y_mm + 1e-6
                ):
                    raise GCodeIntegrationError(
                        "Eine eingefügte Koordinate liegt außerhalb des Druckbetts."
                    )
            if line.startswith(END_MARKER):
                inside = False
        if inside:
            raise GCodeIntegrationError(
                "Ein eingefügter Kühlturmabschnitt wurde nicht korrekt abgeschlossen."
            )
        # The combined file must remain analyzable and contain printable layers.
        GCodeAnalysisService().analyze(output_path, force=True)
