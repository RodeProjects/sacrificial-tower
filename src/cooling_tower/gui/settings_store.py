from __future__ import annotations

import json
import math
from dataclasses import fields
from pathlib import Path
from typing import Any, Mapping

from cooling_tower.config import SETTINGS_SCHEMA_VERSION
from cooling_tower.models import GenerationSettings
from cooling_tower.persistence import (
    FutureSchemaVersionError,
    VersionedDocumentError,
    VersionedJsonStore,
)
from cooling_tower.persistence.downgrade_settings import DowngradeSettingsJournal
from cooling_tower.settings_compatibility import (
    SETTING_COMPATIBILITY_CATALOG,
    project_compatible_settings,
)


_GENERATION_FIELD_NAMES = {
    field.name
    for field in fields(GenerationSettings)
    if not field.name.startswith("_legacy_")
}
_LEGACY_ALIASES = {
    "expansion_angle_deg": "maximum_expansion_angle_deg",
    "contraction_angle_deg": "maximum_contraction_angle_deg",
    "base_width_mm": "manual_base_width_mm",
}
_LEGACY_RADIUS_NAMES = {
    "minimum_radius_mm": "minimum_outer_diameter_mm",
    "minimum_outer_radius_mm": "minimum_outer_diameter_mm",
    "maximum_radius_mm": "maximum_outer_diameter_mm",
    "maximum_outer_radius_mm": "maximum_outer_diameter_mm",
}
_OBSOLETE_HOLLOW_FIELDS = {
    "minimum_wall_thickness_mm",
    "maximum_wall_thickness_mm",
    "wall_path_width_mm",
    "minimum_inner_radius_mm",
    "maximum_wall_change_per_mm_z",
}
_GENERATION_DEFAULTS = GenerationSettings().to_dict()
_PREVIEW_QUALITIES = {"fast", "balanced", "exact"}
_LEGACY_PREVIEW_ITERATIONS = {"fast": 1, "balanced": 3, "exact": 5}
_DEFAULT_PREVIEW_ITERATIONS = 4
_MINIMUM_PREVIEW_ITERATIONS = 4
_MAXIMUM_PREVIEW_ITERATIONS = 8
_PRECISE_PREVIEW_THRESHOLD = 5
_DEFAULT_MAXIMUM_JOINT_SLICES = 12
_DEFAULT_MAXIMUM_SEPARATE_SLICES = 6
_SCHEMA_14_DEFAULT_MAXIMUM_JOINT_SLICES = 10
_MINIMUM_JOINT_SLICES = 5
_MAXIMUM_JOINT_SLICES = 20
_MINIMUM_SEPARATE_SLICES = 1
_MAXIMUM_SEPARATE_SLICES = 15
_WINDOW_SIZE_KEYS = {"width", "height"}
_WINDOW_POSITION_KEYS = {"x", "y"}
_CAMERA_KEYS = {"yaw_deg", "pitch_deg", "zoom", "pan_x", "pan_y"}
_EXPANDED_SECTION_KEYS = {"timing", "prediction", "geometry"}
_OBSOLETE_UI_KEYS = {"output_mode", "preview_signature"}


def _generation_values(values: object) -> dict[str, Any]:
    if not isinstance(values, Mapping):
        return {}
    migrated = dict(values)
    for legacy_name, current_name in _LEGACY_ALIASES.items():
        if current_name not in migrated and legacy_name in migrated:
            migrated[current_name] = migrated[legacy_name]

    for legacy_name, diameter_name in _LEGACY_RADIUS_NAMES.items():
        if diameter_name in migrated or legacy_name not in migrated:
            continue
        value = migrated[legacy_name]
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        ):
            migrated[diameter_name] = 2.0 * float(value)

    normalized: dict[str, Any] = {}
    for name in _GENERATION_FIELD_NAMES:
        if name not in migrated:
            continue
        value = migrated[name]
        if name == "layer_time_tolerance_s" and (
            isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(float(value)) or not 0.01 <= value <= 3.0
        ):
            continue
        default = _GENERATION_DEFAULTS[name]
        if isinstance(default, bool):
            if isinstance(value, bool):
                normalized[name] = value
        elif isinstance(default, int):
            if isinstance(value, int) and not isinstance(value, bool):
                normalized[name] = value
        elif (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        ):
            normalized[name] = float(value)
    normalized["minimum_object_tower_distance_mm"] = 5.0
    return normalized


def _nest_legacy_generation(payload: dict[str, Any]) -> dict[str, Any]:
    migrated = dict(payload)
    raw_generation = migrated.get("generation")
    generation = (
        dict(raw_generation) if isinstance(raw_generation, Mapping) else {}
    )
    legacy_generation_names = (
        _GENERATION_FIELD_NAMES
        | set(_LEGACY_ALIASES)
        | set(_LEGACY_RADIUS_NAMES)
        | _OBSOLETE_HOLLOW_FIELDS
    )
    for name in legacy_generation_names:
        if name in migrated and name not in generation:
            generation[name] = migrated[name]
        migrated.pop(name, None)
    migrated["generation"] = generation
    return migrated


def _migrate_settings_0_to_1(payload: dict[str, Any]) -> dict[str, Any]:
    """Nest the original flat settings format without losing UI state."""

    return _nest_legacy_generation(payload)


def _migrate_settings_1_to_2(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply the documented generation-setting renames."""

    migrated = _nest_legacy_generation(payload)
    migrated["generation"] = _generation_values(migrated["generation"])
    return migrated


def _migrate_settings_2_to_3(payload: dict[str, Any]) -> dict[str, Any]:
    """Replace legacy preview iterations with the named quality preset."""

    migrated = _nest_legacy_generation(payload)
    quality = str(migrated.get("preview_quality", "")).casefold()
    if quality not in _PREVIEW_QUALITIES:
        try:
            iterations = int(migrated.get("slicer_iterations", 2))
        except (TypeError, ValueError):
            iterations = 2
        quality = (
            "fast"
            if iterations <= 1
            else "balanced"
            if iterations < 5
            else "exact"
        )
    migrated["preview_quality"] = quality
    migrated.pop("slicer_iterations", None)
    for name in _OBSOLETE_UI_KEYS:
        migrated.pop(name, None)
    return migrated


def _migrate_settings_3_to_4(payload: dict[str, Any]) -> dict[str, Any]:
    """Declare stable meanings for settings shared across downgrades."""

    migrated = dict(payload)
    migrated["setting_compatibility"] = dict(SETTING_COMPATIBILITY_CATALOG)
    return migrated


def _migrate_settings_4_to_5(payload: dict[str, Any]) -> dict[str, Any]:
    """Allow an optional main-window position alongside its saved size."""

    return dict(payload)


def _migrate_settings_5_to_6(payload: dict[str, Any]) -> dict[str, Any]:
    """Use user-facing diameters and discard obsolete hollow controls."""

    migrated = _nest_legacy_generation(payload)
    migrated["generation"] = _generation_values(migrated["generation"])
    migrated["setting_compatibility"] = dict(SETTING_COMPATIBILITY_CATALOG)
    return migrated


def _migrate_settings_6_to_7(payload: dict[str, Any]) -> dict[str, Any]:
    """Replace named preview presets with an explicit slicer-pass count."""

    migrated = dict(payload)
    try:
        iterations = int(migrated.get("preview_iterations", 0))
    except (TypeError, ValueError):
        iterations = 0
    if not _MINIMUM_PREVIEW_ITERATIONS <= iterations <= _MAXIMUM_PREVIEW_ITERATIONS:
        quality = str(migrated.get("preview_quality", "")).casefold()
        iterations = _LEGACY_PREVIEW_ITERATIONS.get(
            quality,
            _DEFAULT_PREVIEW_ITERATIONS,
        )
    migrated["preview_iterations"] = iterations
    migrated.pop("preview_quality", None)
    migrated.pop("slicer_iterations", None)
    migrated["setting_compatibility"] = dict(SETTING_COMPATIBILITY_CATALOG)
    return migrated


def _migrate_settings_7_to_8(payload: dict[str, Any]) -> dict[str, Any]:
    """Limit persisted slicer-pass counts to the new eight-pass maximum."""

    migrated = dict(payload)
    try:
        iterations = int(
            migrated.get("preview_iterations", _DEFAULT_PREVIEW_ITERATIONS)
        )
    except (TypeError, ValueError):
        iterations = _DEFAULT_PREVIEW_ITERATIONS
    migrated["preview_iterations"] = min(
        _MAXIMUM_PREVIEW_ITERATIONS,
        max(_MINIMUM_PREVIEW_ITERATIONS, iterations),
    )
    migrated["setting_compatibility"] = dict(SETTING_COMPATIBILITY_CATALOG)
    return migrated


def _migrate_settings_8_to_9(payload: dict[str, Any]) -> dict[str, Any]:
    """Add the edge-to-edge object/tower distance with its safe default."""

    migrated = _nest_legacy_generation(payload)
    generation = dict(migrated.get("generation", {}))
    generation.setdefault("minimum_object_tower_distance_mm", 25.0)
    migrated["generation"] = _generation_values(generation)
    migrated["setting_compatibility"] = dict(SETTING_COMPATIBILITY_CATALOG)
    return migrated


def _migrate_settings_9_to_10(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize the historical preview-pass setting."""

    migrated = dict(payload)
    try:
        iterations = int(
            migrated.get("preview_iterations", _DEFAULT_PREVIEW_ITERATIONS)
        )
    except (TypeError, ValueError):
        iterations = _DEFAULT_PREVIEW_ITERATIONS
    migrated["preview_iterations"] = (
        _MAXIMUM_PREVIEW_ITERATIONS
        if iterations >= _PRECISE_PREVIEW_THRESHOLD
        else _DEFAULT_PREVIEW_ITERATIONS
    )
    migrated["setting_compatibility"] = dict(SETTING_COMPATIBILITY_CATALOG)
    return migrated


def _migrate_settings_10_to_11(payload: dict[str, Any]) -> dict[str, Any]:
    """Add the configurable layer-time tolerance in seconds."""
    migrated = _nest_legacy_generation(payload)
    generation = _generation_values(migrated["generation"])
    generation.setdefault("layer_time_tolerance_s", 0.2)
    migrated["generation"] = generation
    migrated["setting_compatibility"] = dict(SETTING_COMPATIBILITY_CATALOG)
    return migrated


def _migrate_settings_11_to_12(payload: dict[str, Any]) -> dict[str, Any]:
    """Replace manual foot height with the geometry's layer-based policy."""
    migrated = _nest_legacy_generation(payload)
    migrated.pop("base_height_mm", None)
    migrated["generation"].pop("base_height_mm", None)
    migrated["setting_compatibility"] = dict(SETTING_COMPATIBILITY_CATALOG)
    return migrated


def _migrate_settings_12_to_13(payload: dict[str, Any]) -> dict[str, Any]:
    """Restrict requested layer times while preserving valid user choices."""
    migrated = _nest_legacy_generation(payload)
    generation = migrated["generation"]
    value = generation.get("target_layer_time_s", 9.0)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0.01:
        value = 9.0
    generation["target_layer_time_s"] = min(value, 30.0)
    migrated["setting_compatibility"] = dict(SETTING_COMPATIBILITY_CATALOG)
    return migrated


def _migrate_settings_13_to_14(payload: dict[str, Any]) -> dict[str, Any]:
    """Add the bounded budget for complete object/tower slices."""

    migrated = dict(payload)
    migrated.setdefault(
        "maximum_joint_slices",
        _SCHEMA_14_DEFAULT_MAXIMUM_JOINT_SLICES,
    )
    migrated["setting_compatibility"] = dict(SETTING_COMPATIBILITY_CATALOG)
    return migrated


def _migrate_settings_14_to_15(payload: dict[str, Any]) -> dict[str, Any]:
    migrated = dict(payload)
    migrated["show_setting_limits"] = False
    migrated["setting_compatibility"] = dict(SETTING_COMPATIBILITY_CATALOG)
    return migrated


def _migrate_settings_15_to_16(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove retired controls and fix the internal object clearance at 5 mm."""
    migrated = dict(payload)
    generation = dict(migrated.get("generation", {}))
    generation.pop("safety_factor", None)
    generation.pop("mesh_segments", None)
    generation["minimum_object_tower_distance_mm"] = 5.0
    migrated["generation"] = generation
    migrated["setting_compatibility"] = dict(SETTING_COMPATIBILITY_CATALOG)
    return migrated


def _migrate_settings_16_to_17(payload: dict[str, Any]) -> dict[str, Any]:
    """Raise the persisted target and tolerance floors without losing valid values."""
    migrated = dict(payload)
    generation = dict(migrated.get("generation", {}))
    for name, old_minimum, new_minimum in (
        ("target_layer_time_s", 0.01, 5.0),
        ("layer_time_tolerance_s", 0.01, 0.1),
    ):
        value = generation.get(name)
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and old_minimum <= value < new_minimum
        ):
            generation[name] = new_minimum
    migrated["generation"] = generation
    migrated["setting_compatibility"] = dict(SETTING_COMPATIBILITY_CATALOG)
    return migrated


def _migrate_settings_17_to_18(payload: dict[str, Any]) -> dict[str, Any]:
    """Constrain stored diameters while retaining the chosen maximum where possible."""
    migrated = dict(payload)
    generation = dict(migrated.get("generation", {}))
    for name, lower, upper in (
        ("minimum_outer_diameter_mm", 3.0, 99.0),
        ("maximum_outer_diameter_mm", 5.0, 100.0),
    ):
        value = generation.get(name)
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        ):
            generation[name] = min(upper, max(lower, float(value)))
    minimum = generation.get(
        "minimum_outer_diameter_mm",
        _GENERATION_DEFAULTS["minimum_outer_diameter_mm"],
    )
    maximum = generation.get(
        "maximum_outer_diameter_mm",
        _GENERATION_DEFAULTS["maximum_outer_diameter_mm"],
    )
    if (
        not isinstance(minimum, (int, float))
        or isinstance(minimum, bool)
        or not math.isfinite(float(minimum))
    ):
        minimum = _GENERATION_DEFAULTS["minimum_outer_diameter_mm"]
    if (
        not isinstance(maximum, (int, float))
        or isinstance(maximum, bool)
        or not math.isfinite(float(maximum))
    ):
        maximum = _GENERATION_DEFAULTS["maximum_outer_diameter_mm"]
    if minimum + 1.0 > maximum:
        generation["minimum_outer_diameter_mm"] = max(3.0, maximum - 1.0)
    migrated["generation"] = generation
    migrated["setting_compatibility"] = dict(SETTING_COMPATIBILITY_CATALOG)
    return migrated


def _migrate_settings_18_to_19(payload: dict[str, Any]) -> dict[str, Any]:
    """Add the configurable budget for separate tower slices."""
    migrated = dict(payload)
    migrated.setdefault(
        "maximum_separate_slices",
        _DEFAULT_MAXIMUM_SEPARATE_SLICES,
    )
    migrated["setting_compatibility"] = dict(SETTING_COMPATIBILITY_CATALOG)
    return migrated


def _migrate_settings_19_to_20(payload: dict[str, Any]) -> dict[str, Any]:
    """Add an explicit, disabled-by-default tower support simulation."""
    migrated = dict(payload)
    generation = dict(migrated.get("generation", {}))
    generation.setdefault("simulate_tower_without_supports", False)
    migrated["generation"] = generation
    migrated["setting_compatibility"] = dict(SETTING_COMPATIBILITY_CATALOG)
    return migrated


def _migrate_settings_20_to_21(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep manual stand widths within the reduced 80 mm limit."""
    migrated = dict(payload)
    generation = dict(migrated.get("generation", {}))
    width = generation.get("manual_base_width_mm")
    if (
        isinstance(width, (int, float))
        and not isinstance(width, bool)
        and math.isfinite(float(width))
        and width > 80.0
    ):
        generation["manual_base_width_mm"] = 80.0
    migrated["generation"] = generation
    migrated["setting_compatibility"] = dict(SETTING_COMPATIBILITY_CATALOG)
    return migrated


def _migrate_settings_21_to_22(payload: dict[str, Any]) -> dict[str, Any]:
    """Add opt-in profile binding, preserving vertical angle storage."""
    migrated = dict(payload)
    generation = dict(migrated.get("generation", {}))
    generation["limit_expansion_to_profile"] = False
    migrated["generation"] = generation
    migrated["setting_compatibility"] = dict(SETTING_COMPATIBILITY_CATALOG)
    return migrated


def _migrate_settings_22_to_23(payload: dict[str, Any]) -> dict[str, Any]:
    """Preserve automatic tessellation and add an independent manual count."""
    migrated = dict(payload)
    generation = dict(migrated.get("generation", {}))
    generation["automatic_circle_segments"] = True
    generation["circle_segments"] = 32
    migrated["generation"] = generation
    migrated["setting_compatibility"] = dict(SETTING_COMPATIBILITY_CATALOG)
    return migrated


def _normalize_user_settings(payload: dict[str, Any]) -> dict[str, Any]:
    nested = _nest_legacy_generation(payload)
    generation = _generation_values(nested.get("generation"))
    for name, minimum, maximum in (
        ("target_layer_time_s", 5.0, 30.0),
        ("layer_time_tolerance_s", 0.1, 3.0),
        ("minimum_outer_diameter_mm", 3.0, 99.0),
        ("maximum_outer_diameter_mm", 5.0, 100.0),
        ("manual_base_width_mm", 20.0, 80.0),
        ("circle_segments", 4, 256),
    ):
        value = generation.get(name)
        if value is not None and not minimum <= value <= maximum:
            generation.pop(name)
    normalized: dict[str, Any] = {
        "generation": generation,
    }

    normalized["show_setting_limits"] = nested.get("show_setting_limits", False) is True
    output_root = nested.get("output_root")
    if isinstance(output_root, str) and output_root.strip():
        normalized["output_root"] = output_root

    raw_window = nested.get("window")
    window: dict[str, int] = {}
    if isinstance(raw_window, Mapping):
        for name in _WINDOW_SIZE_KEYS:
            value = raw_window.get(name)
            if (
                isinstance(value, int)
                and not isinstance(value, bool)
                and 100 <= value <= 100_000
            ):
                window[name] = value
        for name in _WINDOW_POSITION_KEYS:
            value = raw_window.get(name)
            if (
                isinstance(value, int)
                and not isinstance(value, bool)
                and -100_000 <= value <= 100_000
            ):
                window[name] = value
    if window:
        normalized["window"] = window

    try:
        iterations = int(nested.get("preview_iterations", 0))
    except (TypeError, ValueError):
        iterations = 0
    if iterations not in {
        _DEFAULT_PREVIEW_ITERATIONS,
        _MAXIMUM_PREVIEW_ITERATIONS,
    }:
        quality = str(nested.get("preview_quality", "")).casefold()
        iterations = _LEGACY_PREVIEW_ITERATIONS.get(
            quality,
            _DEFAULT_PREVIEW_ITERATIONS,
        )
        iterations = (
            _MAXIMUM_PREVIEW_ITERATIONS
            if iterations >= _PRECISE_PREVIEW_THRESHOLD
            else _DEFAULT_PREVIEW_ITERATIONS
        )
    normalized["preview_iterations"] = iterations

    maximum_joint_slices = nested.get(
        "maximum_joint_slices",
        _DEFAULT_MAXIMUM_JOINT_SLICES,
    )
    if (
        isinstance(maximum_joint_slices, int)
        and not isinstance(maximum_joint_slices, bool)
        and _MINIMUM_JOINT_SLICES
        <= maximum_joint_slices
        <= _MAXIMUM_JOINT_SLICES
    ):
        normalized["maximum_joint_slices"] = maximum_joint_slices
    else:
        normalized["maximum_joint_slices"] = _DEFAULT_MAXIMUM_JOINT_SLICES

    maximum_separate_slices = nested.get(
        "maximum_separate_slices",
        _DEFAULT_MAXIMUM_SEPARATE_SLICES,
    )
    if (
        isinstance(maximum_separate_slices, int)
        and not isinstance(maximum_separate_slices, bool)
        and _MINIMUM_SEPARATE_SLICES
        <= maximum_separate_slices
        <= _MAXIMUM_SEPARATE_SLICES
    ):
        normalized["maximum_separate_slices"] = maximum_separate_slices
    else:
        normalized["maximum_separate_slices"] = _DEFAULT_MAXIMUM_SEPARATE_SLICES

    raw_camera = nested.get("preview_camera")
    camera: dict[str, float] = {}
    if isinstance(raw_camera, Mapping):
        for name in _CAMERA_KEYS:
            value = raw_camera.get(name)
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(float(value))
                and (name != "zoom" or float(value) > 0.0)
            ):
                camera[name] = float(value)
    if camera:
        normalized["preview_camera"] = camera

    raw_expanded = nested.get("expanded_sections")
    expanded: dict[str, bool] = {}
    if isinstance(raw_expanded, Mapping):
        for name in _EXPANDED_SECTION_KEYS:
            value = raw_expanded.get(name)
            if isinstance(value, bool):
                expanded[name] = value
    if expanded:
        normalized["expanded_sections"] = expanded
    normalized["setting_compatibility"] = dict(SETTING_COMPATIBILITY_CATALOG)
    return normalized


_USER_SETTINGS_MIGRATIONS = {
    0: _migrate_settings_0_to_1,
    1: _migrate_settings_1_to_2,
    2: _migrate_settings_2_to_3,
    3: _migrate_settings_3_to_4,
    4: _migrate_settings_4_to_5,
    5: _migrate_settings_5_to_6,
    6: _migrate_settings_6_to_7,
    7: _migrate_settings_7_to_8,
    8: _migrate_settings_8_to_9,
    9: _migrate_settings_9_to_10,
    10: _migrate_settings_10_to_11,
    11: _migrate_settings_11_to_12,
    12: _migrate_settings_12_to_13,
    13: _migrate_settings_13_to_14,
    14: _migrate_settings_14_to_15,
    15: _migrate_settings_15_to_16,
    16: _migrate_settings_16_to_17,
    17: _migrate_settings_17_to_18,
    18: _migrate_settings_18_to_19,
    19: _migrate_settings_19_to_20,
    20: _migrate_settings_20_to_21,
    21: _migrate_settings_21_to_22,
    22: _migrate_settings_22_to_23,
}


class UserSettingsStore:
    def __init__(
        self,
        user_path: str | Path,
        default_path: str | Path,
        *,
        default_output_base: str | Path | None = None,
    ) -> None:
        self.user_path = Path(user_path)
        self.default_path = Path(default_path)
        self.default_output_base = (
            Path(default_output_base).resolve()
            if default_output_base is not None
            else None
        )
        self.last_load_warning: str | None = None
        self.last_migration_backup: Path | None = None
        self._downgrade_journal = DowngradeSettingsJournal(self.user_path)
        self._downgrade_baseline: dict[str, Any] | None = None
        self._downgrade_active = False
        self._pending_merged_payload: dict[str, Any] | None = None
        self._user_document = VersionedJsonStore(
            self.user_path,
            schema_key="settings_schema_version",
            current_version=SETTINGS_SCHEMA_VERSION,
            migrations=_USER_SETTINGS_MIGRATIONS,
            normalizer=_normalize_user_settings,
            document_name="Die gespeicherten Benutzereinstellungen",
        )

    @property
    def write_blocked_reason(self) -> str | None:
        if self._downgrade_active:
            return None
        return self._user_document.write_blocked_reason

    def load_defaults(self) -> GenerationSettings:
        return self._load_generation(self.default_path, GenerationSettings())

    def load_default_output_root(self) -> Path:
        try:
            payload = self._read_payload(self.default_path)
            configured = payload.get("default_output_root", "output")
            if not isinstance(configured, str) or not configured.strip():
                raise ValueError("Default output root must be a path string.")
            path = Path(configured).expanduser()
            if not path.is_absolute():
                base = self.default_output_base or self.default_path.resolve().parent.parent
                path = base / path
            return path.resolve()
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            base = self.default_output_base or self.default_path.resolve().parent.parent
            return (base / "output").resolve()

    def load_default_maximum_joint_slices(self) -> int:
        try:
            value = self._read_payload(self.default_path).get(
                "maximum_joint_slices",
                _DEFAULT_MAXIMUM_JOINT_SLICES,
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return _DEFAULT_MAXIMUM_JOINT_SLICES
        if (
            isinstance(value, int)
            and not isinstance(value, bool)
            and _MINIMUM_JOINT_SLICES <= value <= _MAXIMUM_JOINT_SLICES
        ):
            return value
        return _DEFAULT_MAXIMUM_JOINT_SLICES

    def load_default_maximum_separate_slices(self) -> int:
        try:
            value = self._read_payload(self.default_path).get(
                "maximum_separate_slices",
                _DEFAULT_MAXIMUM_SEPARATE_SLICES,
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return _DEFAULT_MAXIMUM_SEPARATE_SLICES
        if (
            isinstance(value, int)
            and not isinstance(value, bool)
            and _MINIMUM_SEPARATE_SLICES <= value <= _MAXIMUM_SEPARATE_SLICES
        ):
            return value
        return _DEFAULT_MAXIMUM_SEPARATE_SLICES

    def load(self) -> tuple[GenerationSettings, dict[str, Any]]:
        defaults = self.load_defaults()
        self.last_load_warning = None
        self.last_migration_backup = None
        self._downgrade_baseline = None
        self._downgrade_active = False
        self._pending_merged_payload = None
        if not self.user_path.is_file():
            return defaults, {}
        try:
            source_bytes = self.user_path.read_bytes()
            source_payload = json.loads(source_bytes.decode("utf-8"))
            if not isinstance(source_payload, dict):
                source_payload = {}
        except (OSError, UnicodeError, json.JSONDecodeError):
            source_bytes = b""
            source_payload = {}
        try:
            result = self._user_document.load()
            payload = result.payload
            self.last_migration_backup = result.backup_path
            self._apply_pending_downgrade_changes(source_bytes, payload)
            payload = self._pending_merged_payload or payload
            return self._settings_from_payload(payload, defaults), payload
        except FutureSchemaVersionError as error:
            return self._load_downgrade_working_copy(
                defaults,
                source_bytes,
                source_payload,
                error,
            )
        except (OSError, VersionedDocumentError) as error:
            self.last_load_warning = (
                "Die gespeicherten Benutzereinstellungen konnten nicht sicher "
                f"geladen werden: {error} Die Originaldatei bleibt unverändert "
                "und wird nicht automatisch überschrieben."
            )
            return defaults, {}

    def save(
        self,
        generation: GenerationSettings,
        *,
        output_root: str,
        window_width: int,
        window_height: int,
        window_x: int | None = None,
        window_y: int | None = None,
        preview_iterations: int = _DEFAULT_PREVIEW_ITERATIONS,
        maximum_separate_slices: int = _DEFAULT_MAXIMUM_SEPARATE_SLICES,
        maximum_joint_slices: int = _DEFAULT_MAXIMUM_JOINT_SLICES,
        show_setting_limits: bool = False,
        preview_camera: Mapping[str, Any] | None = None,
        expanded_sections: Mapping[str, Any] | None = None,
    ) -> Path:
        payload = self._build_payload(
            generation,
            output_root=output_root,
            window_width=window_width,
            window_height=window_height,
            window_x=window_x,
            window_y=window_y,
            preview_iterations=preview_iterations,
            maximum_separate_slices=maximum_separate_slices,
            maximum_joint_slices=maximum_joint_slices,
            show_setting_limits=show_setting_limits,
            preview_camera=preview_camera,
            expanded_sections=expanded_sections,
        )
        if self._downgrade_active and self._downgrade_baseline is not None:
            self._downgrade_journal.record_changes(
                self._downgrade_baseline,
                payload,
            )
            return self._downgrade_journal.path.resolve()
        return self._user_document.save(payload)

    def recover(
        self,
        generation: GenerationSettings,
        *,
        output_root: str,
        window_width: int,
        window_height: int,
        window_x: int | None = None,
        window_y: int | None = None,
        preview_iterations: int = _DEFAULT_PREVIEW_ITERATIONS,
        maximum_separate_slices: int = _DEFAULT_MAXIMUM_SEPARATE_SLICES,
        maximum_joint_slices: int = _DEFAULT_MAXIMUM_JOINT_SLICES,
        show_setting_limits: bool = False,
        preview_camera: Mapping[str, Any] | None = None,
        expanded_sections: Mapping[str, Any] | None = None,
    ) -> Path:
        """Explicitly replace an unreadable file after creating a backup."""

        path = self._user_document.replace_with_recovery(
            self._build_payload(
                generation,
                output_root=output_root,
                window_width=window_width,
                window_height=window_height,
                window_x=window_x,
                window_y=window_y,
                preview_iterations=preview_iterations,
                maximum_separate_slices=maximum_separate_slices,
                maximum_joint_slices=maximum_joint_slices,
                show_setting_limits=show_setting_limits,
                preview_camera=preview_camera,
                expanded_sections=expanded_sections,
            )
        )
        self.last_load_warning = None
        return path

    @staticmethod
    def _build_payload(
        generation: GenerationSettings,
        *,
        output_root: str,
        window_width: int,
        window_height: int,
        window_x: int | None,
        window_y: int | None,
        preview_iterations: int,
        maximum_separate_slices: int,
        maximum_joint_slices: int,
        show_setting_limits: bool = False,
        preview_camera: Mapping[str, Any] | None,
        expanded_sections: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        window = {
            "width": window_width,
            "height": window_height,
        }
        if window_x is not None and window_y is not None:
            window.update({"x": window_x, "y": window_y})
        return {
            "settings_schema_version": SETTINGS_SCHEMA_VERSION,
            "generation": generation.to_dict(),
            "output_root": output_root,
            "window": window,
            "preview_iterations": (
                _MAXIMUM_PREVIEW_ITERATIONS
                if int(preview_iterations) >= _PRECISE_PREVIEW_THRESHOLD
                else _DEFAULT_PREVIEW_ITERATIONS
            ),
            "maximum_joint_slices": max(
                _MINIMUM_JOINT_SLICES,
                min(_MAXIMUM_JOINT_SLICES, int(maximum_joint_slices)),
            ),
            "maximum_separate_slices": max(
                _MINIMUM_SEPARATE_SLICES,
                min(_MAXIMUM_SEPARATE_SLICES, int(maximum_separate_slices)),
            ),
            "show_setting_limits": show_setting_limits is True,
            "preview_camera": dict(preview_camera or {}),
            "expanded_sections": {
                str(name): bool(value)
                for name, value in (expanded_sections or {}).items()
            },
            "setting_compatibility": dict(SETTING_COMPATIBILITY_CATALOG),
        }

    def _default_payload(self, defaults: GenerationSettings) -> dict[str, Any]:
        return {
            "settings_schema_version": SETTINGS_SCHEMA_VERSION,
            "generation": defaults.to_dict(),
            "output_root": str(self.load_default_output_root()),
            "preview_iterations": _DEFAULT_PREVIEW_ITERATIONS,
            "maximum_joint_slices": self.load_default_maximum_joint_slices(),
            "maximum_separate_slices": (
                self.load_default_maximum_separate_slices()
            ),
            "setting_compatibility": dict(SETTING_COMPATIBILITY_CATALOG),
        }

    @staticmethod
    def _settings_from_payload(
        payload: Mapping[str, Any],
        defaults: GenerationSettings,
    ) -> GenerationSettings:
        generation = payload.get("generation", payload)
        merged = defaults.to_dict()
        merged.update(_generation_values(generation))
        return GenerationSettings.from_mapping(merged)

    def _load_downgrade_working_copy(
        self,
        defaults: GenerationSettings,
        source_bytes: bytes,
        source_payload: Mapping[str, Any],
        error: FutureSchemaVersionError,
    ) -> tuple[GenerationSettings, dict[str, Any]]:
        source_schema = source_payload.get("settings_schema_version")
        fallback = self._default_payload(defaults)
        projection = project_compatible_settings(source_payload, fallback)
        if (
            not source_bytes
            or isinstance(source_schema, bool)
            or not isinstance(source_schema, int)
        ):
            self.last_load_warning = (
                f"{error} Die Datei bleibt unverändert und wird von dieser "
                "Programmversion nicht überschrieben."
            )
            return defaults, {}

        try:
            self._downgrade_journal.prepare(source_bytes, source_schema)
            effective = self._downgrade_journal.apply_to(projection.payload)
        except (OSError, VersionedDocumentError, ValueError) as journal_error:
            self.last_load_warning = (
                f"{error} Die Datei bleibt unverändert und wird nicht "
                "überschrieben. Änderungen konnten nicht sicher getrennt "
                f"gespeichert werden: {journal_error}"
            )
            return (
                self._settings_from_payload(projection.payload, defaults),
                projection.payload,
            )

        self._downgrade_baseline = projection.payload
        self._downgrade_active = True
        rejected = set(projection.rejected_ids) | set(effective.rejected_ids)
        rejection_notice = (
            f" {len(rejected)} nicht kompatible Einstellung(en) wurden zum "
            "Schutz dieser Programmversion nicht übernommen."
            if rejected
            else ""
        )
        self.last_load_warning = (
            f"{error} Die neuere Einstellungsdatei bleibt unverändert und wird "
            "nicht überschrieben. Änderungen dieser Programmversion werden "
            f"sicher getrennt gespeichert.{rejection_notice}"
        )
        return (
            self._settings_from_payload(effective.payload, defaults),
            effective.payload,
        )

    def _apply_pending_downgrade_changes(
        self,
        source_bytes: bytes,
        payload: dict[str, Any],
    ) -> None:
        try:
            journal = self._downgrade_journal.load()
        except (OSError, VersionedDocumentError, ValueError) as error:
            self.last_load_warning = (
                "Gespeicherte Änderungen aus einer älteren Programmversion "
                f"konnten nicht sicher geprüft werden: {error}"
            )
            return
        if journal is None or journal.get("status") != "active":
            return
        protected_schema = journal.get("protected_settings_schema_version")
        protected_schema_is_valid = (
            isinstance(protected_schema, int)
            and not isinstance(protected_schema, bool)
        )
        if (
            not source_bytes
            or not self._downgrade_journal.matches_source(source_bytes)
            or not protected_schema_is_valid
            or SETTINGS_SCHEMA_VERSION < protected_schema
        ):
            if (
                source_bytes
                and protected_schema_is_valid
                and SETTINGS_SCHEMA_VERSION >= protected_schema
            ):
                self.last_load_warning = (
                    "Gespeicherte Änderungen aus einer älteren Programmversion "
                    "wurden nicht übernommen, weil sich die zugehörige neuere "
                    "Einstellungsdatei zwischenzeitlich geändert hat."
                )
            return

        merged = self._downgrade_journal.apply_to(payload)
        try:
            self._user_document.save(merged.payload)
        except (OSError, VersionedDocumentError) as error:
            self.last_load_warning = (
                "Die geprüften Änderungen aus einer älteren Programmversion "
                f"konnten nicht gespeichert werden: {error}"
            )
            return
        self._pending_merged_payload = merged.payload
        try:
            self._downgrade_journal.mark_applied(
                target_schema_version=SETTINGS_SCHEMA_VERSION,
                accepted_ids=merged.accepted_ids,
                rejected_ids=merged.rejected_ids,
            )
        except (OSError, VersionedDocumentError, ValueError) as error:
            self.last_load_warning = (
                "Die gültigen Änderungen aus einer älteren Programmversion "
                "wurden übernommen, ihr Änderungsjournal konnte jedoch nicht "
                f"abschließend markiert werden: {error}"
            )
            return
        if merged.rejected_ids:
            self.last_load_warning = (
                "Änderungen aus einer älteren Programmversion wurden geprüft. "
                f"{len(merged.rejected_ids)} nicht kompatible Einstellung(en) "
                "wurden nicht übernommen; die gültigen neueren Werte bleiben "
                "erhalten."
            )

    @staticmethod
    def _load_generation(
        path: Path,
        fallback: GenerationSettings,
    ) -> GenerationSettings:
        try:
            payload = UserSettingsStore._read_payload(path)
            generation = payload.get("generation", payload)
            merged = fallback.to_dict()
            merged.update(_generation_values(generation))
            return GenerationSettings.from_mapping(merged)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return fallback

    @staticmethod
    def _read_payload(path: Path) -> dict[str, Any]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Settings payload must be a JSON object.")
        return payload
