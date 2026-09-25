from __future__ import annotations

import math
from dataclasses import dataclass

from cooling_tower.gcode.layer_detector import LayerRecord


VALUE_EPSILON = 1e-12
Z_EPSILON_MM = 1e-9


class ProfileCalculationError(ValueError):
    """Raised when a reliable Phase-2 radius profile cannot be calculated."""


@dataclass(frozen=True, slots=True)
class TowerProfileConfig:
    """Configuration values required for the Phase-2 radius profile."""

    target_layer_time_s: float
    minimum_radius_mm: float = 6.0
    maximum_radius_mm: float = 40.0
    local_time_factor_window: int = 5


@dataclass(frozen=True, slots=True)
class LayerRadiusRecord:
    """Calculated Phase-2 values for one detected print layer."""

    layer_index: int
    z_mm: float
    height_mm: float
    layer_time_s: float

    target_layer_time_s: float
    time_deficit_s: float

    seconds_per_deposition_mm: float | None
    time_factor_source: str
    reference_start_layer: int | None
    reference_end_layer: int | None

    additional_path_mm: float
    safety_adjusted_path_mm: float

    calculated_radius_mm: float
    radius_mm: float
    radius_limit: str

    estimated_added_time_s: float | None
    estimated_combined_layer_time_s: float | None


@dataclass(frozen=True, slots=True)
class TowerRadiusProfile:
    """Complete Phase-2 result for all detected layers."""

    config: TowerProfileConfig
    global_seconds_per_deposition_mm: float | None
    layers: tuple[LayerRadiusRecord, ...]

    @property
    def deficit_layer_count(self) -> int:
        return sum(
            layer.time_deficit_s > VALUE_EPSILON
            for layer in self.layers
        )

    @property
    def minimum_limited_layer_count(self) -> int:
        return sum(
            layer.radius_limit == "minimum"
            for layer in self.layers
        )

    @property
    def maximum_limited_layer_count(self) -> int:
        return sum(
            layer.radius_limit == "maximum"
            for layer in self.layers
        )


@dataclass(frozen=True, slots=True)
class StabilityProfileConfig:
    """Configuration values required for the Phase-3 stable profile."""

    minimum_radius_height_factor: float = 0.04
    minimum_base_radius_mm: float = 10.0
    base_height_factor: float = 0.05
    base_margin_mm: float = 2.0
    base_height_mm: float = 1.0
    maximum_radius_change_per_mm_z: float = 0.35


@dataclass(frozen=True, slots=True)
class StableLayerRadiusRecord:
    """Phase-3 stability values corresponding to one print layer."""

    layer_index: int
    z_mm: float
    phase2_radius_mm: float
    height_adjusted_minimum_radius_mm: float
    base_radius_applied: bool
    required_radius_before_smoothing_mm: float
    stabilized_radius_mm: float
    smoothing_increase_mm: float
    total_stability_increase_mm: float


@dataclass(frozen=True, slots=True)
class TowerProfilePoint:
    """One linear interpolation support point of the stable tower profile."""

    z_mm: float
    required_radius_mm: float
    radius_mm: float
    source: str
    layer_index: int | None


@dataclass(frozen=True, slots=True)
class StableTowerProfile:
    """Complete stable profile used later as the Phase-4 mesh input."""

    phase2_profile: TowerRadiusProfile
    config: StabilityProfileConfig

    total_height_mm: float
    height_adjusted_minimum_radius_mm: float
    maximum_required_profile_radius_mm: float

    height_based_base_radius_mm: float
    profile_based_base_radius_mm: float
    base_radius_mm: float
    effective_base_height_mm: float

    layers: tuple[StableLayerRadiusRecord, ...]
    points: tuple[TowerProfilePoint, ...]


@dataclass(frozen=True, slots=True)
class _TimeFactorReference:
    seconds_per_mm: float | None
    source: str
    start_layer: int | None
    end_layer: int | None


def validate_profile_config(
    config: TowerProfileConfig,
) -> None:
    """Validate all user-controlled Phase-2 settings."""
    numeric_values = {
        "target layer time": config.target_layer_time_s,
        "minimum radius": config.minimum_radius_mm,
        "maximum radius": config.maximum_radius_mm,
    }

    for label, value in numeric_values.items():
        if not math.isfinite(value):
            raise ProfileCalculationError(
                f"The {label} must be a finite number."
            )

    if config.target_layer_time_s <= 0.0:
        raise ProfileCalculationError(
            "The target layer time must be greater than zero."
        )


    if config.minimum_radius_mm <= 0.0:
        raise ProfileCalculationError(
            "The minimum radius must be greater than zero."
        )

    if config.maximum_radius_mm < config.minimum_radius_mm:
        raise ProfileCalculationError(
            "The maximum radius must be greater than or equal to "
            "the minimum radius."
        )

    if config.local_time_factor_window <= 0:
        raise ProfileCalculationError(
            "The local time-factor window must be greater than zero."
        )

    if config.local_time_factor_window % 2 == 0:
        raise ProfileCalculationError(
            "The local time-factor window must be an odd number."
        )


def validate_stability_config(
    config: StabilityProfileConfig,
) -> None:
    """Validate all user-controlled Phase-3 stability settings."""
    numeric_values = {
        "minimum-radius height factor": (
            config.minimum_radius_height_factor
        ),
        "minimum base radius": config.minimum_base_radius_mm,
        "base-height factor": config.base_height_factor,
        "base margin": config.base_margin_mm,
        "base height": config.base_height_mm,
        "maximum radius change per millimeter Z": (
            config.maximum_radius_change_per_mm_z
        ),
    }

    for label, value in numeric_values.items():
        if not math.isfinite(value):
            raise ProfileCalculationError(
                f"The {label} must be a finite number."
            )

    if config.minimum_radius_height_factor < 0.0:
        raise ProfileCalculationError(
            "The minimum-radius height factor must not be negative."
        )

    if config.minimum_base_radius_mm <= 0.0:
        raise ProfileCalculationError(
            "The minimum base radius must be greater than zero."
        )

    if config.base_height_factor < 0.0:
        raise ProfileCalculationError(
            "The base-height factor must not be negative."
        )

    if config.base_margin_mm < 0.0:
        raise ProfileCalculationError(
            "The base margin must not be negative."
        )

    if config.base_height_mm <= 0.0:
        raise ProfileCalculationError(
            "The base height must be greater than zero."
        )

    if config.maximum_radius_change_per_mm_z <= 0.0:
        raise ProfileCalculationError(
            "The maximum radius change per millimeter Z must be "
            "greater than zero."
        )


def _validate_layer_values(layers: tuple[LayerRecord, ...]) -> None:
    for layer in layers:
        values = {
            "Z position": layer.z_mm,
            "layer height": layer.height_mm,
            "layer time": layer.total_time_s,
            "deposition time": layer.deposition_time_s,
            "deposition path": layer.deposition_path_mm,
        }

        for label, value in values.items():
            if not math.isfinite(value):
                raise ProfileCalculationError(
                    f"Layer {layer.index}: the {label} is not finite."
                )

        if layer.total_time_s < 0.0:
            raise ProfileCalculationError(
                f"Layer {layer.index}: the layer time is negative."
            )

        if layer.deposition_time_s < 0.0:
            raise ProfileCalculationError(
                f"Layer {layer.index}: the deposition time is negative."
            )

        if layer.deposition_path_mm < 0.0:
            raise ProfileCalculationError(
                f"Layer {layer.index}: the deposition path is negative."
            )


def calculate_seconds_per_deposition_mm(
    layers: tuple[LayerRecord, ...],
) -> float | None:
    """Calculate a path-weighted time factor for a group of layers."""
    deposition_time_s = 0.0
    deposition_path_mm = 0.0

    for layer in layers:
        if (
            layer.deposition_time_s <= VALUE_EPSILON
            or layer.deposition_path_mm <= VALUE_EPSILON
        ):
            continue

        deposition_time_s += layer.deposition_time_s
        deposition_path_mm += layer.deposition_path_mm

    if (
        deposition_time_s <= VALUE_EPSILON
        or deposition_path_mm <= VALUE_EPSILON
    ):
        return None

    return deposition_time_s / deposition_path_mm


def _get_centered_window_bounds(
    *,
    layer_position: int,
    layer_count: int,
    window_size: int,
) -> tuple[int, int]:
    """Return a centered, bounded window while retaining its full size."""
    effective_window_size = min(window_size, layer_count)
    half_window = effective_window_size // 2

    start = layer_position - half_window
    end = start + effective_window_size

    if start < 0:
        start = 0
        end = effective_window_size

    if end > layer_count:
        end = layer_count
        start = layer_count - effective_window_size

    return start, end


def _get_time_factor_reference(
    *,
    layers: tuple[LayerRecord, ...],
    layer_position: int,
    window_size: int,
    global_seconds_per_mm: float | None,
    target_time_s: float | None = None,
) -> _TimeFactorReference:
    start, end = _get_centered_window_bounds(
        layer_position=layer_position,
        layer_count=len(layers),
        window_size=window_size,
    )

    if target_time_s is not None:
        # Do not mix opposite sides of a sharp change in cooling demand.
        # A large surface on a later layer must not alter the earlier layer's
        # estimated deposition speed and cause an anticipatory narrowing.
        for boundary in range(start + 1, end):
            before, after = layers[boundary - 1], layers[boundary]
            crosses_target = ((before.total_time_s < target_time_s)
                              != (after.total_time_s < target_time_s))
            low = min(before.total_time_s, after.total_time_s)
            high = max(before.total_time_s, after.total_time_s)
            if crosses_target and high > 1.5 * max(low, VALUE_EPSILON):
                if boundary <= layer_position:
                    start = boundary
                else:
                    end = boundary
                    break
    local_layers = layers[start:end]
    local_seconds_per_mm = calculate_seconds_per_deposition_mm(
        local_layers
    )

    if local_seconds_per_mm is not None:
        return _TimeFactorReference(
            seconds_per_mm=local_seconds_per_mm,
            source="local",
            start_layer=local_layers[0].index,
            end_layer=local_layers[-1].index,
        )

    if global_seconds_per_mm is not None:
        return _TimeFactorReference(
            seconds_per_mm=global_seconds_per_mm,
            source="global",
            start_layer=layers[0].index,
            end_layer=layers[-1].index,
        )

    return _TimeFactorReference(
        seconds_per_mm=None,
        source="unavailable",
        start_layer=None,
        end_layer=None,
    )


def _calculate_layer_radius(
    *,
    layer: LayerRecord,
    config: TowerProfileConfig,
    reference: _TimeFactorReference,
) -> LayerRadiusRecord:
    time_deficit_s = max(
        0.0,
        config.target_layer_time_s - layer.total_time_s,
    )

    seconds_per_mm = reference.seconds_per_mm

    if time_deficit_s > VALUE_EPSILON and seconds_per_mm is None:
        raise ProfileCalculationError(
            f"Layer {layer.index} has a time deficit of "
            f"{time_deficit_s:.6f} s, but no usable deposition-time "
            "reference exists in the G-code."
        )

    if time_deficit_s <= VALUE_EPSILON:
        additional_path_mm = 0.0
        safety_adjusted_path_mm = 0.0
        calculated_radius_mm = 0.0
    else:
        if seconds_per_mm is None:
            raise RuntimeError(
                "A validated time factor unexpectedly became unavailable."
            )

        additional_path_mm = time_deficit_s / seconds_per_mm
        safety_adjusted_path_mm = additional_path_mm
        calculated_radius_mm = (
            safety_adjusted_path_mm / math.tau
        )

    radius_mm = min(
        config.maximum_radius_mm,
        max(config.minimum_radius_mm, calculated_radius_mm),
    )

    if calculated_radius_mm < config.minimum_radius_mm:
        radius_limit = "minimum"
    elif calculated_radius_mm > config.maximum_radius_mm:
        radius_limit = "maximum"
    else:
        radius_limit = "none"

    if seconds_per_mm is None:
        estimated_added_time_s = None
        estimated_combined_layer_time_s = None
    else:
        estimated_added_time_s = (
            math.tau * radius_mm * seconds_per_mm
        )
        estimated_combined_layer_time_s = (
            layer.total_time_s + estimated_added_time_s
        )

    return LayerRadiusRecord(
        layer_index=layer.index,
        z_mm=layer.z_mm,
        height_mm=layer.height_mm,
        layer_time_s=layer.total_time_s,

        target_layer_time_s=config.target_layer_time_s,
        time_deficit_s=time_deficit_s,

        seconds_per_deposition_mm=seconds_per_mm,
        time_factor_source=reference.source,
        reference_start_layer=reference.start_layer,
        reference_end_layer=reference.end_layer,

        additional_path_mm=additional_path_mm,
        safety_adjusted_path_mm=safety_adjusted_path_mm,

        calculated_radius_mm=calculated_radius_mm,
        radius_mm=radius_mm,
        radius_limit=radius_limit,

        estimated_added_time_s=estimated_added_time_s,
        estimated_combined_layer_time_s=(
            estimated_combined_layer_time_s
        ),
    )


def build_tower_radius_profile(
    layers: tuple[LayerRecord, ...],
    config: TowerProfileConfig,
) -> TowerRadiusProfile:
    """
    Build the complete Phase-2 radius profile.

    The local reference is a path-weighted, centered moving window. If that
    window contains no usable deposition data, the path-weighted global
    factor is used as a fallback.
    """
    validate_profile_config(config)
    _validate_layer_values(layers)

    global_seconds_per_mm = calculate_seconds_per_deposition_mm(
        layers
    )

    radius_layers: list[LayerRadiusRecord] = []

    for layer_position, layer in enumerate(layers):
        reference = _get_time_factor_reference(
            layers=layers,
            layer_position=layer_position,
            window_size=config.local_time_factor_window,
            global_seconds_per_mm=global_seconds_per_mm,
            target_time_s=config.target_layer_time_s,
        )

        radius_layers.append(
            _calculate_layer_radius(
                layer=layer,
                config=config,
                reference=reference,
            )
        )

    return TowerRadiusProfile(
        config=config,
        global_seconds_per_deposition_mm=global_seconds_per_mm,
        layers=tuple(radius_layers),
    )


def _validate_phase2_profile_for_stability(
    profile: TowerRadiusProfile,
) -> None:
    if not profile.layers:
        raise ProfileCalculationError(
            "A stable tower profile cannot be built without printed layers."
        )

    previous_z: float | None = None
    previous_index: int | None = None

    for layer in profile.layers:
        if not math.isfinite(layer.z_mm):
            raise ProfileCalculationError(
                f"Layer {layer.layer_index}: the Z position is not finite."
            )

        if layer.z_mm <= 0.0:
            raise ProfileCalculationError(
                f"Layer {layer.layer_index}: the Z position must be "
                "greater than zero."
            )

        if (
            previous_z is not None
            and layer.z_mm <= previous_z + Z_EPSILON_MM
        ):
            raise ProfileCalculationError(
                "Layer Z positions must be strictly increasing for the "
                "stable profile."
            )

        if (
            previous_index is not None
            and layer.layer_index <= previous_index
        ):
            raise ProfileCalculationError(
                "Layer indices must be strictly increasing for the "
                "stable profile."
            )

        if (
            not math.isfinite(layer.radius_mm)
            or layer.radius_mm <= 0.0
        ):
            raise ProfileCalculationError(
                f"Layer {layer.layer_index}: the Phase-2 radius must be "
                "finite and greater than zero."
            )

        previous_z = layer.z_mm
        previous_index = layer.layer_index


def _smooth_required_radii(
    *,
    z_positions: list[float],
    required_radii: list[float],
    maximum_change_per_mm_z: float,
) -> list[float]:
    """Apply the required backward and forward only-growing passes."""
    radii = required_radii.copy()

    for position in range(len(radii) - 2, -1, -1):
        delta_z = (
            z_positions[position + 1]
            - z_positions[position]
        )
        maximum_change = delta_z * maximum_change_per_mm_z
        radii[position] = max(
            radii[position],
            radii[position + 1] - maximum_change,
        )

    for position in range(1, len(radii)):
        delta_z = (
            z_positions[position]
            - z_positions[position - 1]
        )
        maximum_change = delta_z * maximum_change_per_mm_z
        radii[position] = max(
            radii[position],
            radii[position - 1] - maximum_change,
        )

    return radii


def build_stable_tower_profile(
    phase2_profile: TowerRadiusProfile,
    config: StabilityProfileConfig,
) -> StableTowerProfile:
    """
    Build the Phase-3 profile with a connected base and safe transitions.

    Every stability operation is monotonic with respect to the Phase-2
    requirement: radii may grow, but are never reduced.
    """
    validate_stability_config(config)
    _validate_phase2_profile_for_stability(phase2_profile)

    total_height_mm = phase2_profile.layers[-1].z_mm

    height_adjusted_minimum_radius_mm = max(
        phase2_profile.config.minimum_radius_mm,
        total_height_mm * config.minimum_radius_height_factor,
    )

    maximum_required_profile_radius_mm = max(
        max(
            layer.radius_mm,
            height_adjusted_minimum_radius_mm,
        )
        for layer in phase2_profile.layers
    )

    height_based_base_radius_mm = (
        config.minimum_base_radius_mm
        + total_height_mm * config.base_height_factor
    )
    profile_based_base_radius_mm = (
        maximum_required_profile_radius_mm
        + config.base_margin_mm
    )
    base_radius_mm = max(
        height_based_base_radius_mm,
        profile_based_base_radius_mm,
    )
    effective_base_height_mm = min(
        config.base_height_mm,
        total_height_mm,
    )

    required_points: list[
        tuple[float, float, str, int | None]
    ] = [
        (0.0, base_radius_mm, "base_bottom", None),
    ]

    required_radius_by_layer: dict[int, float] = {}
    base_applied_by_layer: dict[int, bool] = {}

    for layer in phase2_profile.layers:
        base_radius_applied = (
            layer.z_mm
            <= effective_base_height_mm + Z_EPSILON_MM
        )
        required_radius_mm = max(
            layer.radius_mm,
            height_adjusted_minimum_radius_mm,
        )

        if base_radius_applied:
            required_radius_mm = max(
                required_radius_mm,
                base_radius_mm,
            )

        required_radius_by_layer[layer.layer_index] = (
            required_radius_mm
        )
        base_applied_by_layer[layer.layer_index] = (
            base_radius_applied
        )
        required_points.append(
            (
                layer.z_mm,
                required_radius_mm,
                "layer",
                layer.layer_index,
            )
        )

    base_height_has_layer_point = any(
        abs(layer.z_mm - effective_base_height_mm)
        <= Z_EPSILON_MM
        for layer in phase2_profile.layers
    )

    if (
        effective_base_height_mm < total_height_mm - Z_EPSILON_MM
        and not base_height_has_layer_point
    ):
        required_points.append(
            (
                effective_base_height_mm,
                base_radius_mm,
                "base_transition",
                None,
            )
        )

    required_points.sort(key=lambda point: point[0])

    z_positions = [point[0] for point in required_points]
    required_radii = [point[1] for point in required_points]

    for position in range(1, len(z_positions)):
        if (
            z_positions[position]
            <= z_positions[position - 1] + Z_EPSILON_MM
        ):
            raise ProfileCalculationError(
                "Stable profile support-point heights must be strictly "
                "increasing."
            )

    stabilized_radii = _smooth_required_radii(
        z_positions=z_positions,
        required_radii=required_radii,
        maximum_change_per_mm_z=(
            config.maximum_radius_change_per_mm_z
        ),
    )

    stable_points = tuple(
        TowerProfilePoint(
            z_mm=point[0],
            required_radius_mm=point[1],
            radius_mm=stabilized_radius,
            source=point[2],
            layer_index=point[3],
        )
        for point, stabilized_radius in zip(
            required_points,
            stabilized_radii,
            strict=True,
        )
    )

    stable_point_by_layer = {
        point.layer_index: point
        for point in stable_points
        if point.layer_index is not None
    }

    stable_layers: list[StableLayerRadiusRecord] = []

    for layer in phase2_profile.layers:
        stable_point = stable_point_by_layer[layer.layer_index]
        required_radius_mm = required_radius_by_layer[
            layer.layer_index
        ]

        stable_layers.append(
            StableLayerRadiusRecord(
                layer_index=layer.layer_index,
                z_mm=layer.z_mm,
                phase2_radius_mm=layer.radius_mm,
                height_adjusted_minimum_radius_mm=(
                    height_adjusted_minimum_radius_mm
                ),
                base_radius_applied=base_applied_by_layer[
                    layer.layer_index
                ],
                required_radius_before_smoothing_mm=(
                    required_radius_mm
                ),
                stabilized_radius_mm=stable_point.radius_mm,
                smoothing_increase_mm=max(
                    0.0,
                    stable_point.radius_mm - required_radius_mm,
                ),
                total_stability_increase_mm=max(
                    0.0,
                    stable_point.radius_mm - layer.radius_mm,
                ),
            )
        )

    tolerance = 1e-9

    for point in stable_points:
        if point.radius_mm + tolerance < point.required_radius_mm:
            raise RuntimeError(
                "Stable-profile smoothing reduced a required radius."
            )

    for previous_point, point in zip(
        stable_points,
        stable_points[1:],
    ):
        delta_z = point.z_mm - previous_point.z_mm
        maximum_change = (
            delta_z * config.maximum_radius_change_per_mm_z
        )

        if (
            abs(point.radius_mm - previous_point.radius_mm)
            > maximum_change + tolerance
        ):
            raise RuntimeError(
                "Stable-profile smoothing exceeded the configured "
                "radius-change limit."
            )

    return StableTowerProfile(
        phase2_profile=phase2_profile,
        config=config,

        total_height_mm=total_height_mm,
        height_adjusted_minimum_radius_mm=(
            height_adjusted_minimum_radius_mm
        ),
        maximum_required_profile_radius_mm=(
            maximum_required_profile_radius_mm
        ),

        height_based_base_radius_mm=height_based_base_radius_mm,
        profile_based_base_radius_mm=profile_based_base_radius_mm,
        base_radius_mm=base_radius_mm,
        effective_base_height_mm=effective_base_height_mm,

        layers=tuple(stable_layers),
        points=stable_points,
    )
