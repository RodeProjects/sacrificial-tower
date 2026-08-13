from __future__ import annotations

import math
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path


NUMBER_PATTERN = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"

COMMAND_PATTERN = re.compile(
    rf"^(?P<command>(?:[A-Za-z]+(?:_[A-Za-z0-9]+)+|[A-Za-z]{NUMBER_PATTERN}))",
    re.ASCII,
)

PARAMETER_PATTERN = re.compile(
    rf"\s*(?P<letter>[A-Za-z])\s*(?P<value>{NUMBER_PATTERN})",
    re.ASCII,
)

NAMED_PARAMETER_PATTERN = re.compile(
    rf"\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*"
    rf"(?P<value>{NUMBER_PATTERN})",
    re.ASCII,
)

LINE_NUMBER_PATTERN = re.compile(
    r"^N\d+\s*",
    re.IGNORECASE | re.ASCII,
)

CHECKSUM_PATTERN = re.compile(
    r"\*\s*\d+\s*$",
    re.ASCII,
)

PARENTHESIS_COMMENT_PATTERN = re.compile(
    r"\(([^)]*)\)",
)


@dataclass(frozen=True, slots=True)
class GCodeLine:
    number: int
    text: str


@dataclass(frozen=True, slots=True)
class ParsedGCodeLine:
    number: int
    raw_text: str
    code_text: str
    command: str | None
    parameters: dict[str, float]
    comment: str | None
    unparsed_text: str | None


def validate_gcode_path(gcode_path: str | Path) -> Path:
    """
    Validate the supplied G-code file path.

    The file extension is intentionally not restricted because slicers may use
    extensions such as .gcode, .gco, or other custom variants.
    """
    path = Path(gcode_path).expanduser()

    if not path.exists():
        raise FileNotFoundError(f"The G-code file does not exist: {path}")

    if not path.is_file():
        raise IsADirectoryError(f"The supplied path is not a file: {path}")

    return path


def iter_gcode_lines(gcode_path: str | Path) -> Iterator[GCodeLine]:
    """
    Read a G-code file line by line.

    The complete file is never loaded into memory. This allows very large
    G-code files to be processed efficiently.
    """
    path = validate_gcode_path(gcode_path)

    with path.open(
        mode="r",
        encoding="utf-8-sig",
        errors="replace",
    ) as gcode_file:
        for line_number, raw_line in enumerate(gcode_file, start=1):
            yield GCodeLine(
                number=line_number,
                text=raw_line.rstrip("\r\n"),
            )


def split_code_and_comment(text: str) -> tuple[str, str | None]:
    """
    Separate executable G-code from semicolon and parenthesis comments.
    """
    semicolon_index = text.find(";")

    if semicolon_index >= 0:
        code_part = text[:semicolon_index]
        semicolon_comment = text[semicolon_index + 1:].strip()
        has_semicolon_comment = True
    else:
        code_part = text
        semicolon_comment = ""
        has_semicolon_comment = False

    parenthesis_comments = [
        match.group(1).strip()
        for match in PARENTHESIS_COMMENT_PATTERN.finditer(code_part)
    ]

    code_part = PARENTHESIS_COMMENT_PATTERN.sub(" ", code_part)

    comment_parts = [
        comment
        for comment in parenthesis_comments
        if comment
    ]

    if has_semicolon_comment and semicolon_comment:
        comment_parts.append(semicolon_comment)

    has_any_comment = (
        has_semicolon_comment
        or bool(parenthesis_comments)
    )

    if has_any_comment:
        comment = " | ".join(comment_parts)
    else:
        comment = None

    return code_part.strip(), comment


def remove_line_number_and_checksum(code_text: str) -> str:
    """
    Remove optional communication-related line numbers and checksums.

    Example:
        N123 G1 X10 Y20*45
    becomes:
        G1 X10 Y20
    """
    code_text = CHECKSUM_PATTERN.sub("", code_text)
    code_text = LINE_NUMBER_PATTERN.sub("", code_text)

    return code_text.strip()


def parse_parameters(
    parameter_text: str,
) -> tuple[dict[str, float], str | None]:
    """
    Parse consecutive numeric letter parameters.

    Both spaced and compact G-code formats are supported:

        G1 X10 Y20 E0.5
        G1X10Y20E0.5
    """
    parameters: dict[str, float] = {}
    current_position = 0

    if "=" in parameter_text:
        while current_position < len(parameter_text):
            match = NAMED_PARAMETER_PATTERN.match(
                parameter_text,
                current_position,
            )

            if match is None:
                break

            name = match.group("name").upper()
            value = float(match.group("value"))
            if not math.isfinite(value):
                break
            parameters[name] = value
            current_position = match.end()

        remaining_text = parameter_text[current_position:].strip()

        if not remaining_text:
            remaining_text = None

        return parameters, remaining_text

    while current_position < len(parameter_text):
        match = PARAMETER_PATTERN.match(
            parameter_text,
            current_position,
        )

        if match is None:
            break

        letter = match.group("letter").upper()
        value = float(match.group("value"))
        if not math.isfinite(value):
            break

        parameters[letter] = value
        current_position = match.end()

    remaining_text = parameter_text[current_position:].strip()

    if not remaining_text:
        remaining_text = None

    return parameters, remaining_text


def parse_gcode_line(gcode_line: GCodeLine) -> ParsedGCodeLine:
    """
    Parse one source line into command, parameters, comment, and remainder.
    """
    code_text, comment = split_code_and_comment(gcode_line.text)
    code_text = remove_line_number_and_checksum(code_text)

    if not code_text:
        return ParsedGCodeLine(
            number=gcode_line.number,
            raw_text=gcode_line.text,
            code_text="",
            command=None,
            parameters={},
            comment=comment,
            unparsed_text=None,
        )

    command_match = COMMAND_PATTERN.match(code_text)

    if command_match is None:
        return ParsedGCodeLine(
            number=gcode_line.number,
            raw_text=gcode_line.text,
            code_text=code_text,
            command=None,
            parameters={},
            comment=comment,
            unparsed_text=code_text,
        )

    command = command_match.group("command").upper()
    parameter_text = code_text[command_match.end():]

    parameters, unparsed_text = parse_parameters(parameter_text)

    return ParsedGCodeLine(
        number=gcode_line.number,
        raw_text=gcode_line.text,
        code_text=code_text,
        command=command,
        parameters=parameters,
        comment=comment,
        unparsed_text=unparsed_text,
    )


def iter_parsed_gcode_lines(
    gcode_path: str | Path,
) -> Iterator[ParsedGCodeLine]:
    """
    Read and parse a G-code file line by line.
    """
    for gcode_line in iter_gcode_lines(gcode_path):
        yield parse_gcode_line(gcode_line)

MOTION_COMMANDS = {
    "G0",
    "G1",
    "G2",
    "G3",
}

LINEAR_MOTION_COMMANDS = {
    "G0",
    "G1",
}

ARC_MOTION_COMMANDS = {
    "G2",
    "G3",
}

MOVEMENT_EPSILON = 1e-9
ARC_EPSILON = 1e-7


@dataclass(slots=True)
class MachineState:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    e: float = 0.0

    feedrate_mm_min: float | None = None
    speed_factor_percent: float = 100.0

    print_acceleration_mm_s2: float | None = None
    travel_acceleration_mm_s2: float | None = None
    retract_acceleration_mm_s2: float | None = None

    maximum_acceleration_x_mm_s2: float | None = None
    maximum_acceleration_y_mm_s2: float | None = None
    maximum_acceleration_z_mm_s2: float | None = None
    maximum_acceleration_e_mm_s2: float | None = None

    jerk_x_mm_s: float | None = None
    jerk_y_mm_s: float | None = None
    jerk_z_mm_s: float | None = None
    jerk_e_mm_s: float | None = None
    square_corner_velocity_mm_s: float | None = None

    xyz_relative: bool = False
    extrusion_relative: bool = False

    active_tool: int | None = None

    arc_plane: str = "XY"
    arc_center_relative: bool = True


@dataclass(frozen=True, slots=True)
class ArcGeometry:
    path_length_mm: float | None
    radius_mm: float | None
    sweep_degrees: float | None
    error: str | None


@dataclass(frozen=True, slots=True)
class MovementTiming:
    distance_mm: float | None
    effective_feedrate_mm_min: float | None
    duration_s: float | None
    error: str | None
    acceleration_mm_s2: float | None = None
    entry_speed_mm_s: float | None = None
    cruise_speed_mm_s: float | None = None
    exit_speed_mm_s: float | None = None


@dataclass(frozen=True, slots=True)
class Dwell:
    line_number: int
    milliseconds_parameter: float | None
    seconds_parameter: float | None
    duration_s: float | None
    error: str | None


@dataclass(frozen=True, slots=True)
class Movement:
    line_number: int
    command: str

    start_x: float
    start_y: float
    start_z: float
    start_e: float

    end_x: float
    end_y: float
    end_z: float
    end_e: float

    delta_x: float
    delta_y: float
    delta_z: float
    delta_e: float

    endpoint_distance_xy_mm: float
    endpoint_distance_xyz_mm: float

    path_length_mm: float | None
    feedrate_mm_min: float | None

    effective_feedrate_mm_min: float | None
    timing_distance_mm: float | None
    duration_s: float | None
    timing_error: str | None

    is_arc: bool
    arc_plane: str | None
    arc_radius_mm: float | None
    arc_sweep_degrees: float | None
    arc_error: str | None

    category: str

    acceleration_mm_s2: float | None = None
    entry_speed_mm_s: float | None = None
    cruise_speed_mm_s: float | None = None
    exit_speed_mm_s: float | None = None

    jerk_x_mm_s: float | None = None
    jerk_y_mm_s: float | None = None
    jerk_z_mm_s: float | None = None
    jerk_e_mm_s: float | None = None
    square_corner_velocity_mm_s: float | None = None


def normalize_command(command: str) -> str:
    """
    Normalize commands such as G00 to G0 and G01 to G1.

    Commands with a meaningful decimal component, such as G90.1, remain
    unchanged.
    """
    command = command.upper()

    if len(command) < 2:
        return command

    command_letter = command[0]
    command_number = command[1:]

    if command_letter not in {"G", "M", "T"}:
        return command

    try:
        numeric_value = float(command_number)
    except ValueError:
        return command
    if not math.isfinite(numeric_value):
        return command

    if numeric_value.is_integer():
        return f"{command_letter}{int(numeric_value)}"

    return command


def resolve_axis_position(
    current_position: float,
    parameter_value: float | None,
    relative_mode: bool,
) -> float:
    """
    Calculate an axis target position using the current coordinate mode.
    """
    if parameter_value is None:
        return current_position

    if relative_mode:
        return current_position + parameter_value

    return parameter_value


def classify_movement(
    *,
    has_spatial_motion: bool,
    delta_e: float,
    feedrate_changed: bool,
) -> str:
    """
    Classify a movement based on spatial and extruder changes.
    """
    has_positive_extrusion = delta_e > MOVEMENT_EPSILON
    has_negative_extrusion = delta_e < -MOVEMENT_EPSILON

    if has_spatial_motion and has_positive_extrusion:
        return "deposition"

    if has_spatial_motion and has_negative_extrusion:
        return "travel_with_retraction"

    if has_spatial_motion:
        return "travel"

    if has_negative_extrusion:
        return "retraction"

    if has_positive_extrusion:
        return "unretraction"

    if feedrate_changed:
        return "feedrate_only"

    return "no_op"


def select_commanded_acceleration(
    state: MachineState,
    category: str,
) -> float | None:
    """Select the active M204 acceleration for a movement category."""
    if category in {"retraction", "unretraction"}:
        return state.retract_acceleration_mm_s2

    if category in {"travel", "travel_with_retraction"}:
        return state.travel_acceleration_mm_s2

    return state.print_acceleration_mm_s2


def limit_acceleration_by_axes(
    *,
    commanded_acceleration_mm_s2: float | None,
    state: MachineState,
    has_spatial_motion: bool,
    is_arc: bool,
    timing_distance_mm: float,
    delta_x: float,
    delta_y: float,
    delta_z: float,
    delta_e: float,
) -> float | None:
    """Project M201 axis limits onto the current movement path."""
    if commanded_acceleration_mm_s2 is None:
        return None

    if commanded_acceleration_mm_s2 <= MOVEMENT_EPSILON:
        return commanded_acceleration_mm_s2

    acceleration_limits = [commanded_acceleration_mm_s2]

    axis_movements = (
        (delta_x, state.maximum_acceleration_x_mm_s2),
        (delta_y, state.maximum_acceleration_y_mm_s2),
        (delta_z, state.maximum_acceleration_z_mm_s2),
    )

    if has_spatial_motion and is_arc:
        # The tangent of an XY arc changes along the path. Limiting the path
        # acceleration to each participating axis maximum is conservative and
        # remains valid for full circles whose endpoint delta is zero.
        for maximum in (
            state.maximum_acceleration_x_mm_s2,
            state.maximum_acceleration_y_mm_s2,
        ):
            if maximum is not None:
                acceleration_limits.append(maximum)

        if abs(delta_z) > MOVEMENT_EPSILON:
            maximum_z = state.maximum_acceleration_z_mm_s2
            if maximum_z is not None:
                acceleration_limits.append(
                    maximum_z
                    * timing_distance_mm
                    / abs(delta_z)
                )
    elif has_spatial_motion:
        for axis_delta, maximum in axis_movements:
            if (
                maximum is not None
                and abs(axis_delta) > MOVEMENT_EPSILON
            ):
                acceleration_limits.append(
                    maximum
                    * timing_distance_mm
                    / abs(axis_delta)
                )

    if (
        state.maximum_acceleration_e_mm_s2 is not None
        and abs(delta_e) > MOVEMENT_EPSILON
    ):
        acceleration_limits.append(
            state.maximum_acceleration_e_mm_s2
            * timing_distance_mm
            / abs(delta_e)
        )

    return min(acceleration_limits)

def calculate_movement_timing(
    *,
    has_spatial_motion: bool,
    path_length_mm: float | None,
    delta_e: float,
    feedrate_mm_min: float | None,
    speed_factor_percent: float,
    acceleration_mm_s2: float | None = None,
    entry_speed_mm_s: float = 0.0,
    exit_speed_mm_s: float = 0.0,
) -> MovementTiming:
    """
    Calculate the duration of one movement.

    Spatial movements use the XYZ or arc path length. Pure extruder movements
    use the absolute E distance. If an acceleration is known, a triangular or
    trapezoidal velocity profile is used. Otherwise the legacy constant-speed
    estimate is retained because inventing a machine acceleration would be
    less reliable than using the values explicitly supplied by the G-code.
    """
    if has_spatial_motion:
        if path_length_mm is None:
            return MovementTiming(
                distance_mm=None,
                effective_feedrate_mm_min=None,
                duration_s=None,
                error="The movement path length is unavailable.",
            )

        timing_distance_mm = path_length_mm

    elif abs(delta_e) > MOVEMENT_EPSILON:
        timing_distance_mm = abs(delta_e)

    else:
        timing_distance_mm = 0.0

    if feedrate_mm_min is None:
        effective_feedrate_mm_min = None
    else:
        effective_feedrate_mm_min = (
            feedrate_mm_min
            * speed_factor_percent
            / 100.0
        )

    if timing_distance_mm <= MOVEMENT_EPSILON:
        return MovementTiming(
            distance_mm=timing_distance_mm,
            effective_feedrate_mm_min=effective_feedrate_mm_min,
            duration_s=0.0,
            error=None,
            acceleration_mm_s2=acceleration_mm_s2,
            entry_speed_mm_s=0.0,
            cruise_speed_mm_s=0.0,
            exit_speed_mm_s=0.0,
        )

    if feedrate_mm_min is None:
        return MovementTiming(
            distance_mm=timing_distance_mm,
            effective_feedrate_mm_min=None,
            duration_s=None,
            error="The feedrate is unknown.",
        )

    if effective_feedrate_mm_min is None:
        return MovementTiming(
            distance_mm=timing_distance_mm,
            effective_feedrate_mm_min=None,
            duration_s=None,
            error="The effective feedrate is unavailable.",
        )

    if effective_feedrate_mm_min <= MOVEMENT_EPSILON:
        return MovementTiming(
            distance_mm=timing_distance_mm,
            effective_feedrate_mm_min=effective_feedrate_mm_min,
            duration_s=None,
            error="The effective feedrate is zero or negative.",
        )

    target_speed_mm_s = effective_feedrate_mm_min / 60.0

    if acceleration_mm_s2 is None:
        duration_s = timing_distance_mm / target_speed_mm_s

        return MovementTiming(
            distance_mm=timing_distance_mm,
            effective_feedrate_mm_min=effective_feedrate_mm_min,
            duration_s=duration_s,
            error=None,
            acceleration_mm_s2=None,
            entry_speed_mm_s=target_speed_mm_s,
            cruise_speed_mm_s=target_speed_mm_s,
            exit_speed_mm_s=target_speed_mm_s,
        )

    if acceleration_mm_s2 <= MOVEMENT_EPSILON:
        return MovementTiming(
            distance_mm=timing_distance_mm,
            effective_feedrate_mm_min=effective_feedrate_mm_min,
            duration_s=None,
            error="The movement acceleration is zero or negative.",
            acceleration_mm_s2=acceleration_mm_s2,
        )

    if (
        entry_speed_mm_s < -MOVEMENT_EPSILON
        or exit_speed_mm_s < -MOVEMENT_EPSILON
    ):
        return MovementTiming(
            distance_mm=timing_distance_mm,
            effective_feedrate_mm_min=effective_feedrate_mm_min,
            duration_s=None,
            error="Entry and exit speeds must not be negative.",
            acceleration_mm_s2=acceleration_mm_s2,
        )

    entry_speed_mm_s = min(
        max(0.0, entry_speed_mm_s),
        target_speed_mm_s,
    )
    exit_speed_mm_s = min(
        max(0.0, exit_speed_mm_s),
        target_speed_mm_s,
    )

    peak_speed_squared = (
        acceleration_mm_s2 * timing_distance_mm
        + (
            entry_speed_mm_s ** 2
            + exit_speed_mm_s ** 2
        )
        / 2.0
    )
    cruise_speed_mm_s = min(
        target_speed_mm_s,
        math.sqrt(max(0.0, peak_speed_squared)),
    )

    acceleration_distance_mm = max(
        0.0,
        (
            cruise_speed_mm_s ** 2
            - entry_speed_mm_s ** 2
        )
        / (2.0 * acceleration_mm_s2),
    )
    deceleration_distance_mm = max(
        0.0,
        (
            cruise_speed_mm_s ** 2
            - exit_speed_mm_s ** 2
        )
        / (2.0 * acceleration_mm_s2),
    )
    constant_speed_distance_mm = max(
        0.0,
        timing_distance_mm
        - acceleration_distance_mm
        - deceleration_distance_mm,
    )

    duration_s = (
        (cruise_speed_mm_s - entry_speed_mm_s)
        / acceleration_mm_s2
        + (cruise_speed_mm_s - exit_speed_mm_s)
        / acceleration_mm_s2
        + constant_speed_distance_mm / cruise_speed_mm_s
    )

    return MovementTiming(
        distance_mm=timing_distance_mm,
        effective_feedrate_mm_min=effective_feedrate_mm_min,
        duration_s=duration_s,
        error=None,
        acceleration_mm_s2=acceleration_mm_s2,
        entry_speed_mm_s=entry_speed_mm_s,
        cruise_speed_mm_s=cruise_speed_mm_s,
        exit_speed_mm_s=exit_speed_mm_s,
    )

def calculate_directed_sweep(
    *,
    start_angle: float,
    end_angle: float,
    clockwise: bool,
    full_circle: bool,
) -> float:
    """
    Calculate the directed sweep angle in radians.
    """
    if full_circle:
        return math.tau

    if clockwise:
        sweep = (start_angle - end_angle) % math.tau
    else:
        sweep = (end_angle - start_angle) % math.tau

    if sweep < ARC_EPSILON:
        return 0.0

    return sweep


def calculate_ij_arc_geometry(
    *,
    start_x: float,
    start_y: float,
    start_z: float,
    end_x: float,
    end_y: float,
    end_z: float,
    parameters: dict[str, float],
    clockwise: bool,
    center_relative: bool,
) -> ArcGeometry:
    """
    Calculate an XY-plane arc defined by I and J center coordinates.
    """
    if center_relative:
        center_x = start_x + parameters.get("I", 0.0)
        center_y = start_y + parameters.get("J", 0.0)
    else:
        center_x = parameters.get("I", start_x)
        center_y = parameters.get("J", start_y)

    start_radius = math.hypot(
        start_x - center_x,
        start_y - center_y,
    )

    end_radius = math.hypot(
        end_x - center_x,
        end_y - center_y,
    )

    if start_radius <= ARC_EPSILON:
        return ArcGeometry(
            path_length_mm=None,
            radius_mm=None,
            sweep_degrees=None,
            error="Arc radius is zero.",
        )

    radius = (start_radius + end_radius) / 2.0

    start_angle = math.atan2(
        start_y - center_y,
        start_x - center_x,
    )

    end_angle = math.atan2(
        end_y - center_y,
        end_x - center_x,
    )

    endpoint_distance = math.hypot(
        end_x - start_x,
        end_y - start_y,
    )

    full_circle = endpoint_distance <= ARC_EPSILON

    sweep = calculate_directed_sweep(
        start_angle=start_angle,
        end_angle=end_angle,
        clockwise=clockwise,
        full_circle=full_circle,
    )

    planar_length = radius * sweep
    height_change = end_z - start_z

    path_length = math.hypot(
        planar_length,
        height_change,
    )

    return ArcGeometry(
        path_length_mm=path_length,
        radius_mm=radius,
        sweep_degrees=math.degrees(sweep),
        error=None,
    )


def calculate_r_arc_geometry(
    *,
    start_x: float,
    start_y: float,
    start_z: float,
    end_x: float,
    end_y: float,
    end_z: float,
    radius_parameter: float,
    clockwise: bool,
) -> ArcGeometry:
    """
    Calculate an XY-plane arc defined by an R radius parameter.
    """
    radius = abs(radius_parameter)

    delta_x = end_x - start_x
    delta_y = end_y - start_y

    chord_length = math.hypot(delta_x, delta_y)

    if radius <= ARC_EPSILON:
        return ArcGeometry(
            path_length_mm=None,
            radius_mm=None,
            sweep_degrees=None,
            error="Arc radius is zero.",
        )

    if chord_length <= ARC_EPSILON:
        return ArcGeometry(
            path_length_mm=None,
            radius_mm=None,
            sweep_degrees=None,
            error="A full circle cannot be defined with R only.",
        )

    if chord_length > 2.0 * radius + ARC_EPSILON:
        return ArcGeometry(
            path_length_mm=None,
            radius_mm=radius,
            sweep_degrees=None,
            error=(
                "Arc chord is longer than the diameter defined by R."
            ),
        )

    midpoint_x = (start_x + end_x) / 2.0
    midpoint_y = (start_y + end_y) / 2.0

    half_chord = chord_length / 2.0

    center_distance_squared = (
        radius ** 2
        - half_chord ** 2
    )

    center_distance = math.sqrt(
        max(0.0, center_distance_squared)
    )

    perpendicular_x = -delta_y / chord_length
    perpendicular_y = delta_x / chord_length

    candidate_centers = [
        (
            midpoint_x + perpendicular_x * center_distance,
            midpoint_y + perpendicular_y * center_distance,
        ),
        (
            midpoint_x - perpendicular_x * center_distance,
            midpoint_y - perpendicular_y * center_distance,
        ),
    ]

    candidates: list[tuple[float, float, float]] = []

    for center_x, center_y in candidate_centers:
        start_angle = math.atan2(
            start_y - center_y,
            start_x - center_x,
        )

        end_angle = math.atan2(
            end_y - center_y,
            end_x - center_x,
        )

        sweep = calculate_directed_sweep(
            start_angle=start_angle,
            end_angle=end_angle,
            clockwise=clockwise,
            full_circle=False,
        )

        candidates.append(
            (
                center_x,
                center_y,
                sweep,
            )
        )

    if radius_parameter >= 0.0:
        _, _, sweep = min(
            candidates,
            key=lambda candidate: candidate[2],
        )
    else:
        _, _, sweep = max(
            candidates,
            key=lambda candidate: candidate[2],
        )

    planar_length = radius * sweep
    height_change = end_z - start_z

    path_length = math.hypot(
        planar_length,
        height_change,
    )

    return ArcGeometry(
        path_length_mm=path_length,
        radius_mm=radius,
        sweep_degrees=math.degrees(sweep),
        error=None,
    )


def calculate_xy_arc_geometry(
    *,
    command: str,
    start_x: float,
    start_y: float,
    start_z: float,
    end_x: float,
    end_y: float,
    end_z: float,
    parameters: dict[str, float],
    center_relative: bool,
) -> ArcGeometry:
    """
    Calculate the geometry of a G2 or G3 arc in the XY plane.
    """
    clockwise = command == "G2"

    has_center_parameters = (
        "I" in parameters
        or "J" in parameters
    )

    if has_center_parameters:
        return calculate_ij_arc_geometry(
            start_x=start_x,
            start_y=start_y,
            start_z=start_z,
            end_x=end_x,
            end_y=end_y,
            end_z=end_z,
            parameters=parameters,
            clockwise=clockwise,
            center_relative=center_relative,
        )

    if "R" in parameters:
        return calculate_r_arc_geometry(
            start_x=start_x,
            start_y=start_y,
            start_z=start_z,
            end_x=end_x,
            end_y=end_y,
            end_z=end_z,
            radius_parameter=parameters["R"],
            clockwise=clockwise,
        )

    return ArcGeometry(
        path_length_mm=None,
        radius_mm=None,
        sweep_degrees=None,
        error="Arc has neither I/J nor R parameters.",
    )


class MachineStateTracker:
    """
    Reconstruct the modal machine state while processing parsed G-code lines.
    """

    def __init__(self) -> None:
        self.state = MachineState()

    def process_line(
        self,
        parsed_line: ParsedGCodeLine,
    ) -> Movement | Dwell | None:
        """
        Apply one parsed G-code line to the current machine state.

        A Movement object is returned for G0, G1, G2, and G3 commands.
        Other supported modal commands update the state and return None.
        """
        if parsed_line.command is None:
            return None

        command = normalize_command(parsed_line.command)
        parameters = parsed_line.parameters

        if command == "G4":
            return self._create_dwell(
                line_number=parsed_line.number,
                parameters=parameters,
            )

        if command == "M201":
            self._apply_maximum_acceleration(parameters)
            return None

        if command == "M204":
            self._apply_movement_acceleration(parameters)
            return None

        if command == "M205":
            self._apply_classic_jerk(parameters)
            return None

        if command == "SET_VELOCITY_LIMIT":
            self._apply_velocity_limit(parameters)
            return None

        if command == "M220":
            if "S" in parameters:
                self.state.speed_factor_percent = parameters["S"]

            return None

        if command == "G90":
            self.state.xyz_relative = False
            return None

        if command == "G91":
            self.state.xyz_relative = True
            return None

        if command == "M82":
            self.state.extrusion_relative = False
            return None

        if command == "M83":
            self.state.extrusion_relative = True
            return None

        if command == "G90.1":
            self.state.arc_center_relative = False
            return None

        if command == "G91.1":
            self.state.arc_center_relative = True
            return None

        if command == "G17":
            self.state.arc_plane = "XY"
            return None

        if command == "G18":
            self.state.arc_plane = "XZ"
            return None

        if command == "G19":
            self.state.arc_plane = "YZ"
            return None

        if command == "G92":
            self._apply_position_reset(parameters)
            return None

        if command.startswith("T"):
            self._apply_tool_change(command)
            return None

        if command not in MOTION_COMMANDS:
            return None

        return self._apply_movement(
            line_number=parsed_line.number,
            command=command,
            parameters=parameters,
        )

    def _apply_maximum_acceleration(
        self,
        parameters: dict[str, float],
    ) -> None:
        """Apply M201 per-axis maximum accelerations in mm/s²."""
        axis_attributes = {
            "X": "maximum_acceleration_x_mm_s2",
            "Y": "maximum_acceleration_y_mm_s2",
            "Z": "maximum_acceleration_z_mm_s2",
            "E": "maximum_acceleration_e_mm_s2",
        }

        for parameter, attribute in axis_attributes.items():
            if parameter in parameters:
                setattr(self.state, attribute, parameters[parameter])

    def _apply_movement_acceleration(
        self,
        parameters: dict[str, float],
    ) -> None:
        """Apply Marlin/Klipper-compatible M204 acceleration settings."""
        shared_acceleration = parameters.get("S")

        if shared_acceleration is not None:
            self.state.print_acceleration_mm_s2 = shared_acceleration
            self.state.travel_acceleration_mm_s2 = shared_acceleration
            self.state.retract_acceleration_mm_s2 = shared_acceleration

        if "P" in parameters:
            self.state.print_acceleration_mm_s2 = parameters["P"]

        if "T" in parameters:
            self.state.travel_acceleration_mm_s2 = parameters["T"]

        if "R" in parameters:
            self.state.retract_acceleration_mm_s2 = parameters["R"]

    def _apply_classic_jerk(
        self,
        parameters: dict[str, float],
    ) -> None:
        """Apply M205 classic-jerk limits used at movement junctions."""
        axis_attributes = {
            "X": "jerk_x_mm_s",
            "Y": "jerk_y_mm_s",
            "Z": "jerk_z_mm_s",
            "E": "jerk_e_mm_s",
        }

        for parameter, attribute in axis_attributes.items():
            if parameter in parameters:
                setattr(self.state, attribute, parameters[parameter])

    def _apply_velocity_limit(
        self,
        parameters: dict[str, float],
    ) -> None:
        """Apply numeric Klipper SET_VELOCITY_LIMIT parameters."""
        if "ACCEL" in parameters:
            acceleration = parameters["ACCEL"]
            self.state.print_acceleration_mm_s2 = acceleration
            self.state.travel_acceleration_mm_s2 = acceleration
            self.state.retract_acceleration_mm_s2 = acceleration

        if "SQUARE_CORNER_VELOCITY" in parameters:
            self.state.square_corner_velocity_mm_s = parameters[
                "SQUARE_CORNER_VELOCITY"
            ]

    def _create_dwell(
        self,
        *,
        line_number: int,
        parameters: dict[str, float],
    ) -> Dwell:
        """
        Create a timed G4 dwell event.

        P is interpreted as milliseconds and S as seconds.
        """
        milliseconds_parameter = parameters.get("P")
        seconds_parameter = parameters.get("S")

        if (
            milliseconds_parameter is not None
            and milliseconds_parameter < 0.0
        ):
            return Dwell(
                line_number=line_number,
                milliseconds_parameter=milliseconds_parameter,
                seconds_parameter=seconds_parameter,
                duration_s=None,
                error="The G4 P parameter is negative.",
            )

        if (
            seconds_parameter is not None
            and seconds_parameter < 0.0
        ):
            return Dwell(
                line_number=line_number,
                milliseconds_parameter=milliseconds_parameter,
                seconds_parameter=seconds_parameter,
                duration_s=None,
                error="The G4 S parameter is negative.",
            )

        duration_s = 0.0

        if milliseconds_parameter is not None:
            duration_s += milliseconds_parameter / 1000.0

        if seconds_parameter is not None:
            duration_s += seconds_parameter

        return Dwell(
            line_number=line_number,
            milliseconds_parameter=milliseconds_parameter,
            seconds_parameter=seconds_parameter,
            duration_s=duration_s,
            error=None,
        )

    def _apply_position_reset(
        self,
        parameters: dict[str, float],
    ) -> None:
        """
        Apply a G92 coordinate reset.

        G92 assigns coordinates directly and is independent of relative mode.
        """
        if "X" in parameters:
            self.state.x = parameters["X"]

        if "Y" in parameters:
            self.state.y = parameters["Y"]

        if "Z" in parameters:
            self.state.z = parameters["Z"]

        if "E" in parameters:
            self.state.e = parameters["E"]

    def _apply_tool_change(self, command: str) -> None:
        """
        Store the currently selected tool when the command is T<number>.
        """
        tool_number_text = command[1:]

        if not tool_number_text.isdigit():
            return

        self.state.active_tool = int(tool_number_text)

    def _apply_movement(
        self,
        *,
        line_number: int,
        command: str,
        parameters: dict[str, float],
    ) -> Movement:
        start_x = self.state.x
        start_y = self.state.y
        start_z = self.state.z
        start_e = self.state.e

        feedrate_changed = "F" in parameters

        if feedrate_changed:
            self.state.feedrate_mm_min = parameters["F"]

        end_x = resolve_axis_position(
            current_position=start_x,
            parameter_value=parameters.get("X"),
            relative_mode=self.state.xyz_relative,
        )

        end_y = resolve_axis_position(
            current_position=start_y,
            parameter_value=parameters.get("Y"),
            relative_mode=self.state.xyz_relative,
        )

        end_z = resolve_axis_position(
            current_position=start_z,
            parameter_value=parameters.get("Z"),
            relative_mode=self.state.xyz_relative,
        )

        end_e = resolve_axis_position(
            current_position=start_e,
            parameter_value=parameters.get("E"),
            relative_mode=self.state.extrusion_relative,
        )

        delta_x = end_x - start_x
        delta_y = end_y - start_y
        delta_z = end_z - start_z
        delta_e = end_e - start_e

        endpoint_distance_xy_mm = math.hypot(
            delta_x,
            delta_y,
        )

        endpoint_distance_xyz_mm = math.sqrt(
            delta_x ** 2
            + delta_y ** 2
            + delta_z ** 2
        )

        is_arc = command in ARC_MOTION_COMMANDS

        arc_plane: str | None = None
        arc_radius_mm: float | None = None
        arc_sweep_degrees: float | None = None
        arc_error: str | None = None

        if command in LINEAR_MOTION_COMMANDS:
            path_length_mm: float | None = endpoint_distance_xyz_mm

        elif self.state.arc_plane == "XY":
            arc_plane = self.state.arc_plane

            arc_geometry = calculate_xy_arc_geometry(
                command=command,
                start_x=start_x,
                start_y=start_y,
                start_z=start_z,
                end_x=end_x,
                end_y=end_y,
                end_z=end_z,
                parameters=parameters,
                center_relative=self.state.arc_center_relative,
            )

            path_length_mm = arc_geometry.path_length_mm
            arc_radius_mm = arc_geometry.radius_mm
            arc_sweep_degrees = arc_geometry.sweep_degrees
            arc_error = arc_geometry.error

        else:
            arc_plane = self.state.arc_plane
            path_length_mm = None
            arc_error = (
                f"Arc plane {self.state.arc_plane} is not supported yet."
            )

        has_spatial_motion = (
            endpoint_distance_xyz_mm > MOVEMENT_EPSILON
            or (
                is_arc
                and path_length_mm is not None
                and path_length_mm > MOVEMENT_EPSILON
            )
        )

        category = classify_movement(
            has_spatial_motion=has_spatial_motion,
            delta_e=delta_e,
            feedrate_changed=feedrate_changed,
        )

        if has_spatial_motion:
            timing_distance_mm = path_length_mm or 0.0
        else:
            timing_distance_mm = abs(delta_e)

        commanded_acceleration_mm_s2 = select_commanded_acceleration(
            self.state,
            category,
        )
        acceleration_mm_s2 = limit_acceleration_by_axes(
            commanded_acceleration_mm_s2=(
                commanded_acceleration_mm_s2
            ),
            state=self.state,
            has_spatial_motion=has_spatial_motion,
            is_arc=is_arc,
            timing_distance_mm=timing_distance_mm,
            delta_x=delta_x,
            delta_y=delta_y,
            delta_z=delta_z,
            delta_e=delta_e,
        )

        timing = calculate_movement_timing(
            has_spatial_motion=has_spatial_motion,
            path_length_mm=path_length_mm,
            delta_e=delta_e,
            feedrate_mm_min=self.state.feedrate_mm_min,
            speed_factor_percent=self.state.speed_factor_percent,
            acceleration_mm_s2=acceleration_mm_s2,
        )

        self.state.x = end_x
        self.state.y = end_y
        self.state.z = end_z
        self.state.e = end_e

        return Movement(
            line_number=line_number,
            command=command,

            start_x=start_x,
            start_y=start_y,
            start_z=start_z,
            start_e=start_e,

            end_x=end_x,
            end_y=end_y,
            end_z=end_z,
            end_e=end_e,

            delta_x=delta_x,
            delta_y=delta_y,
            delta_z=delta_z,
            delta_e=delta_e,

            endpoint_distance_xy_mm=endpoint_distance_xy_mm,
            endpoint_distance_xyz_mm=endpoint_distance_xyz_mm,

            path_length_mm=path_length_mm,
            feedrate_mm_min=self.state.feedrate_mm_min,

            effective_feedrate_mm_min=(
                timing.effective_feedrate_mm_min
            ),
            timing_distance_mm=timing.distance_mm,
            duration_s=timing.duration_s,
            timing_error=timing.error,

            is_arc=is_arc,
            arc_plane=arc_plane,
            arc_radius_mm=arc_radius_mm,
            arc_sweep_degrees=arc_sweep_degrees,
            arc_error=arc_error,

            category=category,

            acceleration_mm_s2=acceleration_mm_s2,
            entry_speed_mm_s=timing.entry_speed_mm_s,
            cruise_speed_mm_s=timing.cruise_speed_mm_s,
            exit_speed_mm_s=timing.exit_speed_mm_s,

            jerk_x_mm_s=self.state.jerk_x_mm_s,
            jerk_y_mm_s=self.state.jerk_y_mm_s,
            jerk_z_mm_s=self.state.jerk_z_mm_s,
            jerk_e_mm_s=self.state.jerk_e_mm_s,
            square_corner_velocity_mm_s=(
                self.state.square_corner_velocity_mm_s
            ),
        )


def _movement_direction(
    movement: Movement,
) -> tuple[float, float, float, float] | None:
    """Return a normalized XYZ or pure-E direction for junction planning."""
    if movement.endpoint_distance_xyz_mm > MOVEMENT_EPSILON:
        distance = movement.endpoint_distance_xyz_mm
        return (
            movement.delta_x / distance,
            movement.delta_y / distance,
            movement.delta_z / distance,
            0.0,
        )

    if abs(movement.delta_e) > MOVEMENT_EPSILON:
        return (
            0.0,
            0.0,
            0.0,
            math.copysign(1.0, movement.delta_e),
        )

    return None


def calculate_junction_speed(
    previous: Movement,
    current: Movement,
) -> float:
    """Calculate the maximum speed shared by two adjacent movements."""
    previous_speed = (
        (previous.effective_feedrate_mm_min or 0.0) / 60.0
    )
    current_speed = (
        (current.effective_feedrate_mm_min or 0.0) / 60.0
    )
    maximum_speed = min(previous_speed, current_speed)

    if maximum_speed <= MOVEMENT_EPSILON:
        return 0.0

    previous_direction = _movement_direction(previous)
    current_direction = _movement_direction(current)

    if previous_direction is None or current_direction is None:
        return 0.0

    previous_is_extruder_only = abs(previous_direction[3]) > 0.0
    current_is_extruder_only = abs(current_direction[3]) > 0.0

    if previous_is_extruder_only != current_is_extruder_only:
        return 0.0

    direction_change = tuple(
        current_component - previous_component
        for previous_component, current_component in zip(
            previous_direction,
            current_direction,
        )
    )
    direction_change_length = math.sqrt(
        sum(component ** 2 for component in direction_change)
    )

    if direction_change_length <= MOVEMENT_EPSILON:
        return maximum_speed

    square_corner_velocity = current.square_corner_velocity_mm_s

    if square_corner_velocity is not None:
        if square_corner_velocity <= 0.0:
            return 0.0

        return min(
            maximum_speed,
            math.sqrt(2.0)
            * square_corner_velocity
            / direction_change_length,
        )

    jerk_limits = (
        current.jerk_x_mm_s,
        current.jerk_y_mm_s,
        current.jerk_z_mm_s,
        current.jerk_e_mm_s,
    )
    junction_speed = maximum_speed
    found_limit = False

    for component_change, jerk_limit in zip(
        direction_change,
        jerk_limits,
    ):
        if abs(component_change) <= MOVEMENT_EPSILON:
            continue

        if jerk_limit is None:
            continue

        found_limit = True
        junction_speed = min(
            junction_speed,
            max(0.0, jerk_limit) / abs(component_change),
        )

    if not found_limit:
        return 0.0

    return junction_speed


def plan_movement_run(
    movements: list[Movement],
    *,
    start_speed_mm_s: float = 0.0,
    end_speed_mm_s: float = 0.0,
) -> list[Movement]:
    """Plan a continuous run with junction and acceleration constraints."""
    if not movements:
        return []

    movement_count = len(movements)
    target_speeds = [
        (movement.effective_feedrate_mm_min or 0.0) / 60.0
        for movement in movements
    ]
    distances = [
        movement.timing_distance_mm or 0.0
        for movement in movements
    ]
    accelerations = [
        movement.acceleration_mm_s2 or 0.0
        for movement in movements
    ]

    boundary_speeds = [0.0] * (movement_count + 1)
    boundary_speeds[0] = min(
        max(0.0, start_speed_mm_s),
        target_speeds[0],
    )
    boundary_speeds[-1] = min(
        max(0.0, end_speed_mm_s),
        target_speeds[-1],
    )

    for index in range(1, movement_count):
        boundary_speeds[index] = calculate_junction_speed(
            movements[index - 1],
            movements[index],
        )

    # Reverse pass: every movement must be long enough to decelerate to its
    # requested exit speed. This mirrors the essential look-ahead constraint
    # used by printer motion planners.
    for index in range(movement_count - 1, -1, -1):
        maximum_entry_speed = math.sqrt(
            max(
                0.0,
                boundary_speeds[index + 1] ** 2
                + 2.0
                * accelerations[index]
                * distances[index],
            )
        )
        boundary_speeds[index] = min(
            boundary_speeds[index],
            target_speeds[index],
            maximum_entry_speed,
        )

    # Forward pass: the exit speed must likewise be reachable from the entry
    # speed within the available movement distance.
    for index in range(movement_count):
        maximum_exit_speed = math.sqrt(
            max(
                0.0,
                boundary_speeds[index] ** 2
                + 2.0
                * accelerations[index]
                * distances[index],
            )
        )
        boundary_speeds[index + 1] = min(
            boundary_speeds[index + 1],
            target_speeds[index],
            maximum_exit_speed,
        )

    planned_movements: list[Movement] = []

    for index, movement in enumerate(movements):
        timing = calculate_movement_timing(
            has_spatial_motion=(
                movement.endpoint_distance_xyz_mm > MOVEMENT_EPSILON
                or (
                    movement.is_arc
                    and movement.path_length_mm is not None
                    and movement.path_length_mm > MOVEMENT_EPSILON
                )
            ),
            path_length_mm=movement.path_length_mm,
            delta_e=movement.delta_e,
            feedrate_mm_min=movement.effective_feedrate_mm_min,
            speed_factor_percent=100.0,
            acceleration_mm_s2=movement.acceleration_mm_s2,
            entry_speed_mm_s=boundary_speeds[index],
            exit_speed_mm_s=boundary_speeds[index + 1],
        )
        # ``dataclasses.replace`` discovers and reads every field dynamically.
        # This function runs more than once per physical G-code movement due
        # to the bounded look-ahead window, making that convenience overhead a
        # measurable part of large joint slices. The explicit copy preserves
        # the exact immutable value while avoiding repeated field reflection.
        planned_movements.append(
            Movement(
                line_number=movement.line_number,
                command=movement.command,
                start_x=movement.start_x,
                start_y=movement.start_y,
                start_z=movement.start_z,
                start_e=movement.start_e,
                end_x=movement.end_x,
                end_y=movement.end_y,
                end_z=movement.end_z,
                end_e=movement.end_e,
                delta_x=movement.delta_x,
                delta_y=movement.delta_y,
                delta_z=movement.delta_z,
                delta_e=movement.delta_e,
                endpoint_distance_xy_mm=movement.endpoint_distance_xy_mm,
                endpoint_distance_xyz_mm=movement.endpoint_distance_xyz_mm,
                path_length_mm=movement.path_length_mm,
                feedrate_mm_min=movement.feedrate_mm_min,
                effective_feedrate_mm_min=(
                    movement.effective_feedrate_mm_min
                ),
                timing_distance_mm=movement.timing_distance_mm,
                duration_s=timing.duration_s,
                timing_error=timing.error,
                is_arc=movement.is_arc,
                arc_plane=movement.arc_plane,
                arc_radius_mm=movement.arc_radius_mm,
                arc_sweep_degrees=movement.arc_sweep_degrees,
                arc_error=movement.arc_error,
                category=movement.category,
                acceleration_mm_s2=movement.acceleration_mm_s2,
                entry_speed_mm_s=timing.entry_speed_mm_s,
                cruise_speed_mm_s=timing.cruise_speed_mm_s,
                exit_speed_mm_s=timing.exit_speed_mm_s,
                jerk_x_mm_s=movement.jerk_x_mm_s,
                jerk_y_mm_s=movement.jerk_y_mm_s,
                jerk_z_mm_s=movement.jerk_z_mm_s,
                jerk_e_mm_s=movement.jerk_e_mm_s,
                square_corner_velocity_mm_s=(
                    movement.square_corner_velocity_mm_s
                ),
            )
        )

    return planned_movements


class MotionTimingPlanner:
    """Bounded streaming look-ahead for acceleration-aware movement timing."""

    def __init__(self, lookahead_movements: int = 128) -> None:
        if lookahead_movements < 1:
            raise ValueError("lookahead_movements must be at least 1.")

        self.lookahead_movements = lookahead_movements
        self._pending_events: list[Movement] = []
        self._pending_physical_count = 0
        self._start_speed_mm_s = 0.0

    def process_event(
        self,
        event: Movement | Dwell,
    ) -> tuple[Movement | Dwell, ...]:
        if isinstance(event, Dwell):
            return self._flush_all() + (event,)

        if not self._is_physical(event):
            self._pending_events.append(event)
            return ()

        if not self._is_plannable(event):
            flushed = self._flush_all()
            self._start_speed_mm_s = 0.0
            return flushed + (event,)

        self._pending_events.append(event)
        self._pending_physical_count += 1

        if (
            self._pending_physical_count
            >= self.lookahead_movements * 2
        ):
            return self._flush_prefix(self.lookahead_movements)

        return ()

    def finish(self) -> tuple[Movement | Dwell, ...]:
        return self._flush_all()

    @staticmethod
    def _is_physical(movement: Movement) -> bool:
        return (
            (movement.timing_distance_mm or 0.0) > MOVEMENT_EPSILON
        )

    @classmethod
    def _is_plannable(cls, movement: Movement) -> bool:
        return (
            cls._is_physical(movement)
            and movement.duration_s is not None
            and (movement.effective_feedrate_mm_min or 0.0)
            > MOVEMENT_EPSILON
            and (movement.acceleration_mm_s2 or 0.0)
            > MOVEMENT_EPSILON
        )

    def _planned_pending(self) -> list[Movement]:
        physical_movements = [
            event
            for event in self._pending_events
            if self._is_plannable(event)
        ]
        planned_physical = iter(
            plan_movement_run(
                physical_movements,
                start_speed_mm_s=self._start_speed_mm_s,
                end_speed_mm_s=0.0,
            )
        )

        return [
            next(planned_physical)
            if self._is_plannable(event)
            else event
            for event in self._pending_events
        ]

    def _flush_prefix(
        self,
        physical_count: int,
    ) -> tuple[Movement | Dwell, ...]:
        planned = self._planned_pending()
        seen_physical = 0
        cutoff_index = -1

        for index, event in enumerate(planned):
            if self._is_plannable(event):
                seen_physical += 1

            if seen_physical == physical_count:
                cutoff_index = index
                break

        if cutoff_index < 0:
            raise RuntimeError("Unable to locate motion-planner cutoff.")

        cutoff_event = planned[cutoff_index]
        self._start_speed_mm_s = cutoff_event.exit_speed_mm_s or 0.0
        emitted = tuple(planned[:cutoff_index + 1])
        self._pending_events = self._pending_events[cutoff_index + 1:]
        self._pending_physical_count -= physical_count
        return emitted

    def _flush_all(self) -> tuple[Movement | Dwell, ...]:
        if not self._pending_events:
            self._start_speed_mm_s = 0.0
            return ()

        emitted = tuple(self._planned_pending())
        self._pending_events.clear()
        self._pending_physical_count = 0
        self._start_speed_mm_s = 0.0
        return emitted
