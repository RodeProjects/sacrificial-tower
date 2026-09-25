from cooling_tower.settings_defaults import GENERATION_DEFAULTS
import argparse
import csv
import sys
from pathlib import Path
from cooling_tower.write_policy import ensure_writable_output

from cooling_tower.gcode.parser import (
    MachineStateTracker,
    MotionTimingPlanner,
    iter_parsed_gcode_lines,
    validate_gcode_path,
)
from cooling_tower.gcode.layer_detector import (
    LayerAnalysis,
    LayerDetector,
    LayerRecord,
)
from cooling_tower.tower.mesh_generator import (
    MeshGenerationError,
    StlExportResult,
    TowerMeshConfig,
    automatic_mesh_segments,
    TriangleMesh,
    generate_tower_mesh,
    validate_mesh_config,
    write_binary_stl,
)
from cooling_tower.tower.profile import (
    LayerRadiusRecord,
    ProfileCalculationError,
    StabilityProfileConfig,
    StableLayerRadiusRecord,
    StableTowerProfile,
    TowerProfileConfig,
    TowerRadiusProfile,
    build_stable_tower_profile,
    build_tower_radius_profile,
    validate_profile_config,
    validate_stability_config,
)
from cooling_tower.models import GenerationSettings, NoTowerRequiredResult
from cooling_tower.services.generation_service import GenerationService
from cooling_tower.services.reporting_service import (
    format_generation_report,
    format_no_tower_report,
)


DEFAULT_PREVIEW_COUNT = 10
DEFAULT_CSV_PATH = Path("output/layer_analysis.csv")
DEFAULT_MINIMUM_DIAMETER_MM = GENERATION_DEFAULTS["minimum_outer_diameter_mm"]
DEFAULT_MAXIMUM_DIAMETER_MM = GENERATION_DEFAULTS["maximum_outer_diameter_mm"]
DEFAULT_MINIMUM_OBJECT_TOWER_DISTANCE_MM = GENERATION_DEFAULTS["minimum_object_tower_distance_mm"]
DEFAULT_LOCAL_TIME_FACTOR_WINDOW = GENERATION_DEFAULTS["local_reference_window"]
DEFAULT_MINIMUM_RADIUS_HEIGHT_FACTOR = GENERATION_DEFAULTS["minimum_radius_height_factor"]
DEFAULT_MINIMUM_BASE_RADIUS_MM = GENERATION_DEFAULTS["minimum_base_radius_mm"]
DEFAULT_BASE_HEIGHT_FACTOR = GENERATION_DEFAULTS["base_height_factor"]
DEFAULT_BASE_MARGIN_MM = GENERATION_DEFAULTS["base_margin_mm"]
DEFAULT_BASE_HEIGHT_MM = 1.0  # Historical Phase-3 API only; solid feet use two layers.
DEFAULT_MANUAL_BASE_WIDTH_MM = GENERATION_DEFAULTS["manual_base_width_mm"]
DEFAULT_EXPANSION_ANGLE_DEG = GENERATION_DEFAULTS["maximum_expansion_angle_deg"]
DEFAULT_CONTRACTION_ANGLE_DEG = GENERATION_DEFAULTS["maximum_contraction_angle_deg"]
DEFAULT_MAXIMUM_RADIUS_CHANGE_PER_MM_Z = GENERATION_DEFAULTS["maximum_radius_change_per_mm_z"]
FLOAT_EPSILON = 1e-12


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Detect printed layers and export detailed layer data."
    )

    parser.add_argument(
        "--gcode",
        required=True,
        help="Path to the G-code file.",
    )

    parser.add_argument(
        "--preview",
        type=int,
        default=DEFAULT_PREVIEW_COUNT,
        help=(
            "Number of first and last layers to display. "
            f"Default: {DEFAULT_PREVIEW_COUNT}"
        ),
    )

    parser.add_argument(
        "--csv",
        default=str(DEFAULT_CSV_PATH),
        help=(
            "Path of the generated CSV analysis file. "
            f"Default: {DEFAULT_CSV_PATH}"
        ),
    )

    parser.add_argument(
        "--target-time",
        type=float,
        default=None,
        help=(
            "Minimum desired layer time in seconds. Supplying this "
            "option enables the Phase-2 radius calculation."
        ),
    )

    parser.add_argument(
        "--minimum-diameter",
        type=float,
        default=DEFAULT_MINIMUM_DIAMETER_MM,
        help=(
            "Minimum tower outer diameter in millimeters. "
            f"Default: {DEFAULT_MINIMUM_DIAMETER_MM}"
        ),
    )

    parser.add_argument(
        "--maximum-diameter",
        type=float,
        default=DEFAULT_MAXIMUM_DIAMETER_MM,
        help=(
            "Maximum tower outer diameter in millimeters. "
            f"Default: {DEFAULT_MAXIMUM_DIAMETER_MM}"
        ),
    )

    parser.add_argument(
        "--simulate-full-tower-infill",
        action="store_true",
        help=(
            "Use an object-specific 100 percent infill override for the tower "
            "in joint calibration projects."
        ),
    )

    parser.add_argument(
        "--minimum-object-tower-distance",
        type=float,
        default=DEFAULT_MINIMUM_OBJECT_TOWER_DISTANCE_MM,
        help=(
            "Minimum edge-to-edge distance between source object and tower "
            "in millimeters. Default: "
            f"{DEFAULT_MINIMUM_OBJECT_TOWER_DISTANCE_MM}"
        ),
    )

    parser.add_argument(
        "--local-window",
        type=int,
        default=DEFAULT_LOCAL_TIME_FACTOR_WINDOW,
        help=(
            "Odd number of layers in the centered local time-factor "
            "window. "
            f"Default: {DEFAULT_LOCAL_TIME_FACTOR_WINDOW}"
        ),
    )

    parser.add_argument(
        "--minimum-radius-height-factor",
        type=float,
        default=DEFAULT_MINIMUM_RADIUS_HEIGHT_FACTOR,
        help=(
            "Minimum tower radius per millimeter of total height. "
            f"Default: {DEFAULT_MINIMUM_RADIUS_HEIGHT_FACTOR}"
        ),
    )

    parser.add_argument(
        "--minimum-base-radius",
        type=float,
        default=DEFAULT_MINIMUM_BASE_RADIUS_MM,
        help=(
            "Absolute minimum base radius in millimeters. "
            f"Default: {DEFAULT_MINIMUM_BASE_RADIUS_MM}"
        ),
    )

    parser.add_argument(
        "--base-height-factor",
        type=float,
        default=DEFAULT_BASE_HEIGHT_FACTOR,
        help=(
            "Additional base radius per millimeter of total height. "
            f"Default: {DEFAULT_BASE_HEIGHT_FACTOR}"
        ),
    )

    parser.add_argument(
        "--base-margin",
        type=float,
        default=DEFAULT_BASE_MARGIN_MM,
        help=(
            "Base-radius margin beyond the largest required profile "
            f"radius. Default: {DEFAULT_BASE_MARGIN_MM}"
        ),
    )

    parser.set_defaults(base_height=DEFAULT_BASE_HEIGHT_MM)

    parser.add_argument(
        "--manual-base-width",
        type=float,
        default=None,
        help=(
            "Manual stand-base outer diameter in millimeters (minimum 20). "
            "If omitted, the width is calculated automatically from the "
            "complete G-code object height."
        ),
    )

    parser.add_argument(
        "--expansion-angle",
        type=float,
        default=DEFAULT_EXPANSION_ANGLE_DEG,
        help=(
            "Maximum spline expansion angle from the vertical in degrees. "
            f"Default: {DEFAULT_EXPANSION_ANGLE_DEG}"
        ),
    )

    parser.add_argument(
        "--contraction-angle",
        type=float,
        default=DEFAULT_CONTRACTION_ANGLE_DEG,
        help=(
            "Maximum spline contraction angle from the vertical in degrees. "
            f"Default: {DEFAULT_CONTRACTION_ANGLE_DEG}"
        ),
    )

    parser.add_argument(
        "--maximum-radius-change",
        type=float,
        default=DEFAULT_MAXIMUM_RADIUS_CHANGE_PER_MM_Z,
        help=(
            "Maximum allowed radius change per millimeter Z. "
            f"Default: {DEFAULT_MAXIMUM_RADIUS_CHANGE_PER_MM_Z}"
        ),
    )

    parser.add_argument(
        "--output-stl",
        default=None,
        help=(
            "Path of the generated binary STL. Supplying this option "
            "enables Phase 4 and requires --target-time."
        ),
    )

    parser.add_argument(
        "--output-root",
        default="output",
        help=(
            "Root directory for timestamped generation runs. "
            "Default: output"
        ),
    )

    return parser


def format_duration(duration_s: float) -> str:
    hours = int(duration_s // 3600)
    remaining_seconds = duration_s - hours * 3600

    minutes = int(remaining_seconds // 60)
    seconds = remaining_seconds - minutes * 60

    return f"{hours:02d}:{minutes:02d}:{seconds:06.3f}"


def format_optional_float(
    value: float | None,
    decimals: int,
) -> str:
    if value is None:
        return "-"

    return f"{value:.{decimals}f}"


def format_csv_float(
    value: float | None,
    decimals: int = 6,
) -> str:
    if value is None:
        return ""

    return f"{value:.{decimals}f}"


def get_primary_comment(comment: str | None) -> str | None:
    """
    Return the primary comment when multiple comment parts were combined.
    """
    if comment is None:
        return None

    return comment.split("|", maxsplit=1)[0].strip()


def is_layer_change_comment(comment: str | None) -> bool:
    """
    Match only an exact LAYER_CHANGE marker.

    Using an exact match avoids counting related comments that merely begin
    with the same text.
    """
    primary_comment = get_primary_comment(comment)

    if primary_comment is None:
        return False

    return primary_comment.upper() == "LAYER_CHANGE"


def is_layer_index_comment(comment: str | None) -> bool:
    primary_comment = get_primary_comment(comment)

    if primary_comment is None:
        return False

    return primary_comment.upper().startswith("LAYER:")


def calculate_seconds_per_deposition_mm(
    layer: LayerRecord,
) -> float | None:
    """
    Calculate nominal seconds per millimeter of deposited print path.
    """
    if layer.deposition_path_mm <= FLOAT_EPSILON:
        return None

    if layer.deposition_time_s <= FLOAT_EPSILON:
        return None

    return (
        layer.deposition_time_s
        / layer.deposition_path_mm
    )


def calculate_effective_deposition_speed(
    layer: LayerRecord,
) -> float | None:
    """
    Calculate the nominal effective deposition speed in millimeters per second.
    """
    if layer.deposition_time_s <= FLOAT_EPSILON:
        return None

    if layer.deposition_path_mm <= FLOAT_EPSILON:
        return None

    return (
        layer.deposition_path_mm
        / layer.deposition_time_s
    )


def write_layer_csv(
    layers: tuple[LayerRecord, ...],
    csv_path: str | Path,
    radius_profile: TowerRadiusProfile | None = None,
    stable_profile: StableTowerProfile | None = None,
) -> Path:
    """
    Write all detected layer values to a semicolon-separated CSV file.

    UTF-8 with BOM is used for convenient opening under Windows.
    """
    output_path = ensure_writable_output(csv_path)
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    field_names = [
        "layer_index",
        "z_mm",
        "height_mm",

        "start_line",
        "first_deposition_line",
        "end_line",

        "event_count",
        "movement_count",
        "deposition_count",

        "total_time_s",
        "deposition_time_s",
        "travel_time_s",
        "retraction_time_s",
        "unretraction_time_s",
        "dwell_time_s",
        "other_time_s",

        "deposition_path_mm",
        "deposition_e_mm",

        "effective_deposition_speed_mm_s",
        "seconds_per_deposition_mm",

        "untimed_event_count",
        "untimed_distance_mm",
    ]

    radius_layers_by_index: dict[int, LayerRadiusRecord] = {}
    stable_layers_by_index: dict[int, StableLayerRadiusRecord] = {}

    if radius_profile is not None:
        if len(radius_profile.layers) != len(layers):
            raise RuntimeError(
                "The radius profile does not match the layer analysis."
            )

        radius_layers_by_index = {
            layer.layer_index: layer
            for layer in radius_profile.layers
        }

        if set(radius_layers_by_index) != {
            layer.index for layer in layers
        }:
            raise RuntimeError(
                "The radius profile layer indices do not match the "
                "layer analysis."
            )

        field_names.extend(
            [
                "target_layer_time_s",
                "time_deficit_s",
                "time_factor_s_per_mm",
                "time_factor_source",
                "reference_start_layer",
                "reference_end_layer",
                "additional_path_mm",
                "calculated_radius_mm",
                "tower_radius_mm",
                "radius_limit",
                "estimated_added_time_s",
                "estimated_combined_layer_time_s",
            ]
        )

    if stable_profile is not None:
        if radius_profile is None:
            raise RuntimeError(
                "A stable profile requires a Phase-2 radius profile."
            )

        if len(stable_profile.layers) != len(layers):
            raise RuntimeError(
                "The stable profile does not match the layer analysis."
            )

        stable_layers_by_index = {
            layer.layer_index: layer
            for layer in stable_profile.layers
        }

        if set(stable_layers_by_index) != {
            layer.index for layer in layers
        }:
            raise RuntimeError(
                "The stable-profile layer indices do not match the "
                "layer analysis."
            )

        field_names.extend(
            [
                "height_adjusted_minimum_radius_mm",
                "base_radius_applied",
                "required_radius_before_smoothing_mm",
                "stabilized_radius_mm",
                "smoothing_increase_mm",
                "total_stability_increase_mm",
            ]
        )

    with output_path.open(
        mode="w",
        encoding="utf-8-sig",
        newline="",
    ) as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=field_names,
            delimiter=";",
            lineterminator="\n",
        )

        writer.writeheader()

        for layer in layers:
            effective_speed = (
                calculate_effective_deposition_speed(layer)
            )

            seconds_per_mm = (
                calculate_seconds_per_deposition_mm(layer)
            )

            row: dict[str, str | int] = {
                "layer_index": layer.index,
                "z_mm": format_csv_float(layer.z_mm),
                "height_mm": format_csv_float(layer.height_mm),

                "start_line": layer.start_line,
                "first_deposition_line": (
                    layer.first_deposition_line
                ),
                "end_line": layer.end_line,

                "event_count": layer.event_count,
                "movement_count": layer.movement_count,
                "deposition_count": layer.deposition_count,

                "total_time_s": format_csv_float(
                    layer.total_time_s
                ),
                "deposition_time_s": format_csv_float(
                    layer.deposition_time_s
                ),
                "travel_time_s": format_csv_float(
                    layer.travel_time_s
                ),
                "retraction_time_s": format_csv_float(
                    layer.retraction_time_s
                ),
                "unretraction_time_s": format_csv_float(
                    layer.unretraction_time_s
                ),
                "dwell_time_s": format_csv_float(
                    layer.dwell_time_s
                ),
                "other_time_s": format_csv_float(
                    layer.other_time_s
                ),

                "deposition_path_mm": format_csv_float(
                    layer.deposition_path_mm
                ),
                "deposition_e_mm": format_csv_float(
                    layer.deposition_e_mm
                ),

                "effective_deposition_speed_mm_s": (
                    format_csv_float(effective_speed)
                ),
                "seconds_per_deposition_mm": (
                    format_csv_float(seconds_per_mm)
                ),

                "untimed_event_count": layer.untimed_event_count,
                "untimed_distance_mm": format_csv_float(
                    layer.untimed_distance_mm
                ),
            }

            radius_layer = radius_layers_by_index.get(layer.index)

            if radius_layer is not None:
                row.update(
                    {
                        "target_layer_time_s": format_csv_float(
                            radius_layer.target_layer_time_s
                        ),
                        "time_deficit_s": format_csv_float(
                            radius_layer.time_deficit_s
                        ),
                        "time_factor_s_per_mm": format_csv_float(
                            radius_layer.seconds_per_deposition_mm
                        ),
                        "time_factor_source": (
                            radius_layer.time_factor_source
                        ),
                        "reference_start_layer": (
                            ""
                            if radius_layer.reference_start_layer is None
                            else radius_layer.reference_start_layer
                        ),
                        "reference_end_layer": (
                            ""
                            if radius_layer.reference_end_layer is None
                            else radius_layer.reference_end_layer
                        ),
                        "additional_path_mm": format_csv_float(
                            radius_layer.additional_path_mm
                        ),
                        "calculated_radius_mm": format_csv_float(
                            radius_layer.calculated_radius_mm
                        ),
                        "tower_radius_mm": format_csv_float(
                            radius_layer.radius_mm
                        ),
                        "radius_limit": radius_layer.radius_limit,
                        "estimated_added_time_s": format_csv_float(
                            radius_layer.estimated_added_time_s
                        ),
                        "estimated_combined_layer_time_s": (
                            format_csv_float(
                                radius_layer.estimated_combined_layer_time_s
                            )
                        ),
                    }
                )

            stable_layer = stable_layers_by_index.get(layer.index)

            if stable_layer is not None:
                row.update(
                    {
                        "height_adjusted_minimum_radius_mm": (
                            format_csv_float(
                                stable_layer.
                                height_adjusted_minimum_radius_mm
                            )
                        ),
                        "base_radius_applied": (
                            "1" if stable_layer.base_radius_applied else "0"
                        ),
                        "required_radius_before_smoothing_mm": (
                            format_csv_float(
                                stable_layer.
                                required_radius_before_smoothing_mm
                            )
                        ),
                        "stabilized_radius_mm": format_csv_float(
                            stable_layer.stabilized_radius_mm
                        ),
                        "smoothing_increase_mm": format_csv_float(
                            stable_layer.smoothing_increase_mm
                        ),
                        "total_stability_increase_mm": format_csv_float(
                            stable_layer.total_stability_increase_mm
                        ),
                    }
                )

            writer.writerow(row)

    return output_path.resolve()


def print_layer(layer: LayerRecord) -> None:
    seconds_per_mm = calculate_seconds_per_deposition_mm(
        layer
    )

    effective_speed = calculate_effective_deposition_speed(
        layer
    )

    print(
        f"{layer.index:>6}  "
        f"{layer.z_mm:>8.3f}  "
        f"{layer.height_mm:>7.3f}  "
        f"{layer.total_time_s:>10.3f}  "
        f"{layer.deposition_time_s:>10.3f}  "
        f"{layer.travel_time_s:>9.3f}  "
        f"{layer.deposition_path_mm:>12.3f}  "
        f"{format_optional_float(effective_speed, 3):>10}  "
        f"{format_optional_float(seconds_per_mm, 5):>10}"
    )


def print_layer_table(
    layers: tuple[LayerRecord, ...],
    preview_count: int,
) -> None:
    print(
        f"{'Layer':>6}  "
        f"{'Z':>8}  "
        f"{'Height':>7}  "
        f"{'Total s':>10}  "
        f"{'Print s':>10}  "
        f"{'Travel s':>9}  "
        f"{'Print path':>12}  "
        f"{'mm/s':>10}  "
        f"{'s/mm':>10}"
    )

    print("-" * 111)

    if len(layers) <= preview_count * 2:
        for layer in layers:
            print_layer(layer)

        return

    for layer in layers[:preview_count]:
        print_layer(layer)

    print(
        f"{'...':>6}  "
        f"{'...':>8}  "
        f"{'...':>7}  "
        f"{'...':>10}  "
        f"{'...':>10}  "
        f"{'...':>9}  "
        f"{'...':>12}  "
        f"{'...':>10}  "
        f"{'...':>10}"
    )

    for layer in layers[-preview_count:]:
        print_layer(layer)


def print_radius_layer(layer: LayerRadiusRecord) -> None:
    print(
        f"{layer.layer_index:>6}  "
        f"{layer.z_mm:>8.3f}  "
        f"{layer.layer_time_s:>10.3f}  "
        f"{layer.time_deficit_s:>10.3f}  "
        f"{format_optional_float(layer.seconds_per_deposition_mm, 5):>10}  "
        f"{layer.time_factor_source:>8}  "
        f"{layer.additional_path_mm:>12.3f}  "
        f"{layer.radius_mm:>10.3f}  "
        f"{layer.radius_limit:>8}"
    )


def print_radius_profile_table(
    layers: tuple[LayerRadiusRecord, ...],
    preview_count: int,
) -> None:
    print(
        f"{'Layer':>6}  "
        f"{'Z':>8}  "
        f"{'Layer s':>10}  "
        f"{'Deficit s':>10}  "
        f"{'s/mm':>10}  "
        f"{'Factor':>8}  "
        f"{'Added path':>12}  "
        f"{'Radius':>10}  "
        f"{'Limit':>8}"
    )

    print("-" * 112)

    if len(layers) <= preview_count * 2:
        for layer in layers:
            print_radius_layer(layer)

        return

    for layer in layers[:preview_count]:
        print_radius_layer(layer)

    print(
        f"{'...':>6}  "
        f"{'...':>8}  "
        f"{'...':>10}  "
        f"{'...':>10}  "
        f"{'...':>10}  "
        f"{'...':>8}  "
        f"{'...':>12}  "
        f"{'...':>10}  "
        f"{'...':>8}"
    )

    for layer in layers[-preview_count:]:
        print_radius_layer(layer)


def print_radius_profile_summary(
    profile: TowerRadiusProfile,
) -> None:
    config = profile.config
    layers = profile.layers
    global_seconds_per_mm_text = format_optional_float(
        profile.global_seconds_per_deposition_mm,
        6,
    )

    print()
    print("Phase-2 radius profile")
    print("----------------------")
    print(
        f"Target layer time:                  "
        f"{config.target_layer_time_s:.3f} s"
    )
    print(
        f"Allowed radius range:               "
        f"{config.minimum_radius_mm:.3f} to "
        f"{config.maximum_radius_mm:.3f} mm"
    )
    print(
        f"Local time-factor window:           "
        f"{config.local_time_factor_window} layers"
    )
    print(
        f"Global seconds per deposition mm:   "
        f"{global_seconds_per_mm_text}"
    )

    if not layers:
        print("No layer radii were calculated.")
        return

    local_reference_count = sum(
        layer.time_factor_source == "local"
        for layer in layers
    )
    global_reference_count = sum(
        layer.time_factor_source == "global"
        for layer in layers
    )
    unavailable_reference_count = sum(
        layer.time_factor_source == "unavailable"
        for layer in layers
    )
    total_added_path_mm = sum(
        layer.additional_path_mm
        for layer in layers
    )
    estimated_target_miss_count = sum(
        layer.estimated_combined_layer_time_s is not None
        and (
            layer.estimated_combined_layer_time_s
            + FLOAT_EPSILON
            < layer.target_layer_time_s
        )
        for layer in layers
    )

    print(
        f"Layers below target:                "
        f"{profile.deficit_layer_count}"
    )
    print(
        f"Layers limited by minimum radius:   "
        f"{profile.minimum_limited_layer_count}"
    )
    print(
        f"Layers limited by maximum radius:   "
        f"{profile.maximum_limited_layer_count}"
    )
    print(
        f"Estimated target misses after cap:  "
        f"{estimated_target_miss_count}"
    )
    print(
        f"Local/global/unavailable factors:   "
        f"{local_reference_count}/"
        f"{global_reference_count}/"
        f"{unavailable_reference_count}"
    )
    print(
        f"Total added path:             "
        f"{total_added_path_mm:.3f} mm"
    )
    print(
        f"Calculated radius range:            "
        f"{min(layer.radius_mm for layer in layers):.3f} to "
        f"{max(layer.radius_mm for layer in layers):.3f} mm"
    )


def print_stable_layer(layer: StableLayerRadiusRecord) -> None:
    print(
        f"{layer.layer_index:>6}  "
        f"{layer.z_mm:>8.3f}  "
        f"{layer.phase2_radius_mm:>10.3f}  "
        f"{layer.required_radius_before_smoothing_mm:>10.3f}  "
        f"{layer.stabilized_radius_mm:>10.3f}  "
        f"{layer.smoothing_increase_mm:>10.3f}  "
        f"{layer.total_stability_increase_mm:>10.3f}  "
        f"{('yes' if layer.base_radius_applied else 'no'):>6}"
    )


def print_stable_profile_table(
    layers: tuple[StableLayerRadiusRecord, ...],
    preview_count: int,
) -> None:
    print(
        f"{'Layer':>6}  "
        f"{'Z':>8}  "
        f"{'Phase 2':>10}  "
        f"{'Required':>10}  "
        f"{'Stable':>10}  "
        f"{'Smooth +':>10}  "
        f"{'Total +':>10}  "
        f"{'Base':>6}"
    )
    print("-" * 92)

    if len(layers) <= preview_count * 2:
        for layer in layers:
            print_stable_layer(layer)

        return

    for layer in layers[:preview_count]:
        print_stable_layer(layer)

    print(
        f"{'...':>6}  "
        f"{'...':>8}  "
        f"{'...':>10}  "
        f"{'...':>10}  "
        f"{'...':>10}  "
        f"{'...':>10}  "
        f"{'...':>10}  "
        f"{'...':>6}"
    )

    for layer in layers[-preview_count:]:
        print_stable_layer(layer)


def print_stable_profile_summary(
    profile: StableTowerProfile,
) -> None:
    layers = profile.layers
    points = profile.points

    maximum_observed_change_per_mm_z = max(
        (
            abs(current.radius_mm - previous.radius_mm)
            / (current.z_mm - previous.z_mm)
        )
        for previous, current in zip(points, points[1:])
    )
    smoothed_layer_count = sum(
        layer.smoothing_increase_mm > FLOAT_EPSILON
        for layer in layers
    )
    base_layer_count = sum(
        layer.base_radius_applied
        for layer in layers
    )

    print()
    print("Phase-3 stable profile")
    print("----------------------")
    print(
        f"Total tower height:                 "
        f"{profile.total_height_mm:.3f} mm"
    )
    print(
        f"Height-adjusted minimum radius:     "
        f"{profile.height_adjusted_minimum_radius_mm:.3f} mm"
    )
    print(
        f"Largest required profile radius:    "
        f"{profile.maximum_required_profile_radius_mm:.3f} mm"
    )
    print(
        f"Height-based base radius:           "
        f"{profile.height_based_base_radius_mm:.3f} mm"
    )
    print(
        f"Profile-based base radius:          "
        f"{profile.profile_based_base_radius_mm:.3f} mm"
    )
    print(
        f"Selected base radius:               "
        f"{profile.base_radius_mm:.3f} mm"
    )
    print(
        f"Effective base height:              "
        f"{profile.effective_base_height_mm:.3f} mm"
    )
    print(
        f"Profile support points:             "
        f"{len(points)}"
    )
    print(
        f"Layers inside base:                 "
        f"{base_layer_count}"
    )
    print(
        f"Layers enlarged by smoothing:       "
        f"{smoothed_layer_count}"
    )
    print(
        f"Maximum configured radius change:   "
        f"{profile.config.maximum_radius_change_per_mm_z:.6f} mm/mm"
    )
    print(
        f"Maximum observed radius change:     "
        f"{maximum_observed_change_per_mm_z:.6f} mm/mm"
    )
    print(
        f"Stable radius range:                "
        f"{min(point.radius_mm for point in points):.3f} to "
        f"{max(point.radius_mm for point in points):.3f} mm"
    )
    print(
        f"Largest total stability increase:   "
        f"{max(layer.total_stability_increase_mm for layer in layers):.3f} mm"
    )


def print_mesh_export_summary(
    mesh: TriangleMesh,
    export_result: StlExportResult,
) -> None:
    validation = export_result.validation

    print()
    print("Phase-4 mesh and STL export")
    print("---------------------------")
    print(
        f"Profile rings:                      "
        f"{mesh.ring_count}"
    )
    print(
        f"Segments per ring:                  "
        f"{mesh.segment_count}"
    )
    print(
        f"Vertices:                           "
        f"{validation.vertex_count}"
    )
    print(
        f"Triangles:                          "
        f"{validation.face_count}"
    )
    print(
        f"Degenerate triangles:               "
        f"{validation.degenerate_face_count}"
    )
    print(
        f"Boundary edges:                     "
        f"{validation.boundary_edge_count}"
    )
    print(
        f"Non-manifold edges:                 "
        f"{validation.non_manifold_edge_count}"
    )
    print(
        f"Inconsistent winding edges:         "
        f"{validation.inconsistent_winding_edge_count}"
    )
    print(
        f"Watertight:                         "
        f"{'yes' if validation.is_watertight else 'no'}"
    )
    print(
        f"Consistent winding:                 "
        f"{'yes' if validation.has_consistent_winding else 'no'}"
    )
    print(
        f"Outward orientation:                "
        f"{'yes' if validation.has_outward_orientation else 'no'}"
    )
    print(
        f"Surface area:                       "
        f"{validation.surface_area_mm2:.3f} mm^2"
    )
    print(
        f"Signed enclosed volume:             "
        f"{validation.signed_volume_mm3:.3f} mm^3"
    )
    print(
        f"Mesh height:                        "
        f"{validation.minimum_z_mm:.3f} to "
        f"{validation.maximum_z_mm:.3f} mm"
    )
    print(
        f"STL file size:                      "
        f"{export_result.file_size_bytes} bytes"
    )
    print(
        f"STL output:                         "
        f"{export_result.output_path}"
    )


def print_analysis_summary(
    analysis: LayerAnalysis,
    *,
    layer_change_comment_count: int,
    layer_index_comment_count: int,
) -> None:
    layers = analysis.layers

    if not layers:
        print("No printed layers were detected.")
        return

    layer_heights = [
        layer.height_mm
        for layer in layers
    ]

    total_layer_time_s = sum(
        layer.total_time_s
        for layer in layers
    )

    total_deposition_time_s = sum(
        layer.deposition_time_s
        for layer in layers
    )

    total_travel_time_s = sum(
        layer.travel_time_s
        for layer in layers
    )

    total_deposition_path_mm = sum(
        layer.deposition_path_mm
        for layer in layers
    )

    total_deposition_e_mm = sum(
        layer.deposition_e_mm
        for layer in layers
    )

    total_untimed_events = sum(
        layer.untimed_event_count
        for layer in layers
    )

    shortest_layer = min(
        layers,
        key=lambda layer: layer.total_time_s,
    )

    longest_layer = max(
        layers,
        key=lambda layer: layer.total_time_s,
    )

    global_seconds_per_mm: float | None

    if (
        total_deposition_path_mm > FLOAT_EPSILON
        and total_deposition_time_s > FLOAT_EPSILON
    ):
        global_seconds_per_mm = (
            total_deposition_time_s
            / total_deposition_path_mm
        )
    else:
        global_seconds_per_mm = None

    print()
    print("Layer analysis completed")
    print("------------------------")
    print(f"Detected layers:                    {len(layers)}")
    print(
        f"Confirmed layer changes:            "
        f"{analysis.confirmed_layer_changes}"
    )
    print(
        f"Rejected Z candidates:              "
        f"{analysis.rejected_z_candidates}"
    )
    print(
        f"Exact LAYER_CHANGE comments:        "
        f"{layer_change_comment_count}"
    )
    print(
        f"LAYER:<index> comments:             "
        f"{layer_index_comment_count}"
    )

    print()
    print("Layer geometry")
    print("--------------")
    print(
        f"First printed Z:                    "
        f"{layers[0].z_mm:.5f} mm"
    )
    print(
        f"Last printed Z:                     "
        f"{layers[-1].z_mm:.5f} mm"
    )
    print(
        f"Minimum detected layer height:      "
        f"{min(layer_heights):.5f} mm"
    )
    print(
        f"Maximum detected layer height:      "
        f"{max(layer_heights):.5f} mm"
    )

    print()
    print("Layer timing")
    print("------------")
    print(
        f"Nominal time assigned to layers:    "
        f"{format_duration(total_layer_time_s)}"
    )
    print(
        f"Nominal deposition time:            "
        f"{format_duration(total_deposition_time_s)}"
    )
    print(
        f"Nominal travel time:                "
        f"{format_duration(total_travel_time_s)}"
    )
    print(
        f"Shortest layer:                     "
        f"{shortest_layer.index} "
        f"({shortest_layer.total_time_s:.3f} s)"
    )
    print(
        f"Longest layer:                      "
        f"{longest_layer.index} "
        f"({longest_layer.total_time_s:.3f} s)"
    )

    print()
    print("Deposition reference values")
    print("---------------------------")
    print(
        f"Total deposition path:              "
        f"{total_deposition_path_mm:.3f} mm"
    )
    print(
        f"Total extruded filament:            "
        f"{total_deposition_e_mm:.3f} mm"
    )
    print(
        f"Global seconds per print-path mm:   "
        f"{format_optional_float(global_seconds_per_mm, 6)}"
    )

    print()
    print("Unassigned and untimed events")
    print("-----------------------------")
    print(
        f"Untimed layer events:               "
        f"{total_untimed_events}"
    )
    print(
        f"Events before first layer:          "
        f"{analysis.pre_layer_event_count}"
    )
    print(
        f"Known time before first layer:      "
        f"{format_duration(analysis.pre_layer_time_s)}"
    )
    print(
        f"Untimed events before first layer:  "
        f"{analysis.pre_layer_untimed_event_count}"
    )


def main() -> int:
    parser = build_argument_parser()
    arguments = parser.parse_args()

    if arguments.preview < 0:
        print(
            "Error: --preview must be zero or greater.",
            file=sys.stderr,
        )
        return 2

    if (
        arguments.output_stl is not None
        and arguments.target_time is None
    ):
        print(
            "Error: --output-stl requires --target-time.",
            file=sys.stderr,
        )
        return 2

    # Phase 5 run-directory mode. Explicit legacy CSV/STL destinations remain
    # supported so existing scripts keep producing byte-compatible artifacts.
    if (
        arguments.target_time is not None
        and arguments.output_stl is None
        and arguments.csv == str(DEFAULT_CSV_PATH)
    ):
        try:
            settings = GenerationSettings(
                target_layer_time_s=arguments.target_time,
                minimum_outer_diameter_mm=arguments.minimum_diameter,
                maximum_outer_diameter_mm=arguments.maximum_diameter,
                minimum_object_tower_distance_mm=(
                    arguments.minimum_object_tower_distance
                ),
                simulate_full_tower_infill=(
                    arguments.simulate_full_tower_infill
                ),
                minimum_base_radius_mm=arguments.minimum_base_radius,
                base_height_mm=arguments.base_height,
                base_margin_mm=arguments.base_margin,
                base_height_factor=arguments.base_height_factor,
                automatic_base_width=(
                    arguments.manual_base_width is None
                ),
                manual_base_width_mm=(
                    DEFAULT_MANUAL_BASE_WIDTH_MM
                    if arguments.manual_base_width is None
                    else arguments.manual_base_width
                ),
                minimum_radius_height_factor=(
                    arguments.minimum_radius_height_factor
                ),
                maximum_radius_change_per_mm_z=(
                    arguments.maximum_radius_change
                ),
                maximum_expansion_angle_deg=arguments.expansion_angle,
                maximum_contraction_angle_deg=arguments.contraction_angle,
                local_reference_window=arguments.local_window,
            )
            result = GenerationService(arguments.output_root).generate(
                gcode_path=arguments.gcode,
                settings=settings,
            )
        except (
            FileNotFoundError,
            IsADirectoryError,
            PermissionError,
            OSError,
            MeshGenerationError,
            ProfileCalculationError,
            RuntimeError,
            ValueError,
        ) as error:
            print(f"Error: {error}", file=sys.stderr)
            return 1

        if isinstance(result, NoTowerRequiredResult):
            print()
            print("No cooling tower required")
            print("-------------------------")
            print(format_no_tower_report(result))
            return 0

        print()
        print("Cooling-tower generation completed")
        print("----------------------------------")
        print(format_generation_report(result))
        print(f"Analyse: {result.analysis_path}")
        print(f"Profil: {result.profile_path}")
        print(f"Einstellungen: {result.settings_path}")
        print(
            "Watertight:     "
            f"{'yes' if result.mesh_validation.is_watertight else 'no'}"
        )
        for warning in result.warnings:
            print(f"Warning: {warning}")
        return 0

    radius_profile: TowerRadiusProfile | None = None
    stable_profile: StableTowerProfile | None = None
    tower_mesh: TriangleMesh | None = None
    stl_export_result: StlExportResult | None = None

    try:
        profile_config: TowerProfileConfig | None = None
        stability_config: StabilityProfileConfig | None = None
        mesh_config: TowerMeshConfig | None = None

        if arguments.target_time is not None:
            profile_config = TowerProfileConfig(
                target_layer_time_s=arguments.target_time,
                minimum_radius_mm=arguments.minimum_diameter / 2.0,
                maximum_radius_mm=arguments.maximum_diameter / 2.0,
                local_time_factor_window=arguments.local_window,
            )
            validate_profile_config(profile_config)

            stability_config = StabilityProfileConfig(
                minimum_radius_height_factor=(
                    arguments.minimum_radius_height_factor
                ),
                minimum_base_radius_mm=(
                    arguments.minimum_base_radius
                ),
                base_height_factor=arguments.base_height_factor,
                base_margin_mm=arguments.base_margin,
                base_height_mm=arguments.base_height,
                maximum_radius_change_per_mm_z=(
                    arguments.maximum_radius_change
                ),
            )
            validate_stability_config(stability_config)

            if arguments.output_stl is not None:
                mesh_config = TowerMeshConfig()
                validate_mesh_config(mesh_config)

        gcode_path = validate_gcode_path(arguments.gcode)

        machine_tracker = MachineStateTracker()
        motion_planner = MotionTimingPlanner()
        layer_detector = LayerDetector()

        layer_change_comment_count = 0
        layer_index_comment_count = 0

        for parsed_line in iter_parsed_gcode_lines(gcode_path):
            if is_layer_change_comment(parsed_line.comment):
                layer_change_comment_count += 1

            if is_layer_index_comment(parsed_line.comment):
                layer_index_comment_count += 1

            event = machine_tracker.process_line(parsed_line)

            if event is not None:
                for timed_event in motion_planner.process_event(event):
                    layer_detector.process_event(timed_event)

        for timed_event in motion_planner.finish():
            layer_detector.process_event(timed_event)

        analysis = layer_detector.finish()

        if profile_config is not None:
            radius_profile = build_tower_radius_profile(
                layers=analysis.layers,
                config=profile_config,
            )

            if stability_config is None:
                raise RuntimeError(
                    "The Phase-3 stability configuration is unavailable."
                )

            stable_profile = build_stable_tower_profile(
                phase2_profile=radius_profile,
                config=stability_config,
            )

            if mesh_config is not None:
                mesh_config = TowerMeshConfig(automatic_mesh_segments(stable_profile))
                tower_mesh = generate_tower_mesh(
                    profile=stable_profile,
                    config=mesh_config,
                )
                stl_export_result = write_binary_stl(
                    mesh=tower_mesh,
                    output_path=arguments.output_stl,
                )

        csv_output_path = write_layer_csv(
            layers=analysis.layers,
            csv_path=arguments.csv,
            radius_profile=radius_profile,
            stable_profile=stable_profile,
        )

    except (
        FileNotFoundError,
        IsADirectoryError,
        PermissionError,
        OSError,
        MeshGenerationError,
        ProfileCalculationError,
        RuntimeError,
    ) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print()
    print(f"G-code file: {gcode_path.resolve()}")
    print(f"CSV output:  {csv_output_path}")

    print_analysis_summary(
        analysis,
        layer_change_comment_count=layer_change_comment_count,
        layer_index_comment_count=layer_index_comment_count,
    )

    if radius_profile is not None:
        print_radius_profile_summary(radius_profile)

    if stable_profile is not None:
        print_stable_profile_summary(stable_profile)

    if tower_mesh is not None and stl_export_result is not None:
        print_mesh_export_summary(
            tower_mesh,
            stl_export_result,
        )

    if analysis.layers and arguments.preview > 0:
        print()
        print("Layer preview")
        print("-------------")

        print_layer_table(
            analysis.layers,
            arguments.preview,
        )

    if (
        radius_profile is not None
        and radius_profile.layers
        and arguments.preview > 0
    ):
        print()
        print("Radius profile preview")
        print("----------------------")

        print_radius_profile_table(
            radius_profile.layers,
            arguments.preview,
        )

    if (
        stable_profile is not None
        and stable_profile.layers
        and arguments.preview > 0
    ):
        print()
        print("Stable profile preview")
        print("----------------------")

        print_stable_profile_table(
            stable_profile.layers,
            arguments.preview,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
