from __future__ import annotations

import math
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

_MISSING = object()


@dataclass(frozen=True, slots=True)
class SettingCompatibilityRule:
    stable_id: str
    token: str
    path: tuple[str, ...]
    value_type: str
    group: str
    minimum: float | int | None = None
    maximum: float | int | None = None
    choices: frozenset[str] = frozenset()

    def normalized_value(self, value: object) -> object:
        if self.value_type == "bool":
            if not isinstance(value, bool):
                raise ValueError("boolescher Wert erwartet")
            return value
        if self.value_type == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("Ganzzahl erwartet")
            normalized: object = value
        elif self.value_type == "float":
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
            ):
                raise ValueError("endlicher Zahlenwert erwartet")
            normalized = float(value)
        elif self.value_type == "string":
            if not isinstance(value, str) or not value.strip():
                raise ValueError("nicht leerer Text erwartet")
            normalized = value
        elif self.value_type == "choice":
            if not isinstance(value, str) or value not in self.choices:
                raise ValueError("nicht unterstützte Auswahl")
            normalized = value
        else:  # pragma: no cover - construction-time programming error
            raise ValueError(f"Unbekannter Kompatibilitätstyp: {self.value_type}")

        if self.minimum is not None and normalized < self.minimum:
            raise ValueError("Wert unterschreitet den Mindestwert")
        if self.maximum is not None and normalized > self.maximum:
            raise ValueError("Wert überschreitet den Höchstwert")
        return normalized


def _generation_rule(
    name: str,
    token: str,
    value_type: str,
    *,
    group: str | None = None,
    minimum: float | int | None = None,
    maximum: float | int | None = None,
) -> SettingCompatibilityRule:
    stable_id = f"generation.{name}"
    return SettingCompatibilityRule(
        stable_id=stable_id,
        token=token,
        path=("generation", name),
        value_type=value_type,
        group=group or stable_id,
        minimum=minimum,
        maximum=maximum,
    )


SETTING_COMPATIBILITY_RULES = (
    _generation_rule(
        "layer_time_tolerance_s", "layer-time-tolerance-seconds-v1", "float",
        minimum=0.1, maximum=3.0,
    ),
    _generation_rule(
        "target_layer_time_s", "duration-seconds-v1", "float", minimum=5.0, maximum=30.0
    ),
    _generation_rule(
        "minimum_outer_diameter_mm", "outer-diameter-mm-v1", "float",
        group="generation.solid-geometry-v1", minimum=3.0, maximum=99.0,
    ),
    _generation_rule(
        "maximum_outer_diameter_mm", "outer-diameter-mm-v1", "float",
        group="generation.solid-geometry-v1", minimum=5.0, maximum=100.0,
    ),
    _generation_rule(
        "simulate_full_tower_infill", "full-tower-infill-simulation-v1", "bool",
        group="generation.solid-geometry-v1",
    ),
    _generation_rule(
        "simulate_tower_without_supports", "tower-support-simulation-v1", "bool",
        group="generation.solid-geometry-v1",
    ),
    _generation_rule(
        "minimum_base_radius_mm", "base-radius-mm-v1", "float",
        group="generation.base-v1", minimum=0.0, maximum=500.0,
    ),
    _generation_rule(
        "base_margin_mm", "base-margin-mm-v1", "float",
        group="generation.base-v1", minimum=0.0, maximum=500.0,
    ),
    _generation_rule(
        "base_height_factor", "base-height-factor-v1", "float",
        group="generation.base-v1", minimum=0.0, maximum=10.0,
    ),
    _generation_rule(
        "automatic_base_width", "automatic-base-width-v1", "bool",
        group="generation.base-v1",
    ),
    _generation_rule(
        "manual_base_width_mm", "manual-base-width-mm-v1", "float",
        group="generation.base-v1", minimum=20.0, maximum=80.0,
    ),
    _generation_rule(
        "minimum_radius_height_factor", "radius-height-factor-v1", "float",
        minimum=0.0, maximum=10.0,
    ),
    _generation_rule(
        "maximum_radius_change_per_mm_z", "radius-change-per-mm-z-v1", "float",
        minimum=0.0, maximum=100.0,
    ),
    _generation_rule(
        "maximum_expansion_angle_deg", "expansion-angle-degrees-v1", "float",
        minimum=1.0, maximum=70.0,
    ),
    _generation_rule(
        "maximum_contraction_angle_deg", "contraction-angle-degrees-v1", "float",
        minimum=1.0, maximum=85.0,
    ),
    _generation_rule(
        "local_reference_window", "layer-window-count-v1", "int", minimum=1, maximum=999
    ),
    SettingCompatibilityRule(
        "output_root", "output-directory-path-v1", ("output_root",), "string", "output_root"
    ),
    SettingCompatibilityRule(
        "window.width", "window-pixel-width-v1", ("window", "width"), "int",
        "window.width", minimum=100, maximum=100_000,
    ),
    SettingCompatibilityRule(
        "window.height", "window-pixel-height-v1", ("window", "height"), "int",
        "window.height", minimum=100, maximum=100_000,
    ),
    SettingCompatibilityRule(
        "preview_iterations", "preview-refinement-mode-v2",
        ("preview_iterations",), "int", "preview_iterations",
        minimum=4, maximum=8,
    ),
    SettingCompatibilityRule(
        "show_setting_limits", "numeric-limits-visibility-v1",
        ("show_setting_limits",), "bool", "show_setting_limits",
    ),
    SettingCompatibilityRule(
        "maximum_joint_slices", "joint-slice-budget-v1",
        ("maximum_joint_slices",), "int", "maximum_joint_slices",
        minimum=5, maximum=25,
    ),
    SettingCompatibilityRule(
        "maximum_separate_slices", "separate-slice-budget-v1",
        ("maximum_separate_slices",), "int", "maximum_separate_slices",
        minimum=1, maximum=25,
    ),
    SettingCompatibilityRule(
        "preview_camera.yaw_deg", "camera-yaw-degrees-v1", ("preview_camera", "yaw_deg"),
        "float", "preview_camera.yaw_deg",
    ),
    SettingCompatibilityRule(
        "preview_camera.pitch_deg", "camera-pitch-degrees-v1",
        ("preview_camera", "pitch_deg"), "float", "preview_camera.pitch_deg",
    ),
    SettingCompatibilityRule(
        "preview_camera.zoom", "camera-positive-zoom-v1", ("preview_camera", "zoom"),
        "float", "preview_camera.zoom", minimum=0.000001,
    ),
    SettingCompatibilityRule(
        "preview_camera.pan_x", "camera-pan-x-v1", ("preview_camera", "pan_x"),
        "float", "preview_camera.pan_x",
    ),
    SettingCompatibilityRule(
        "preview_camera.pan_y", "camera-pan-y-v1", ("preview_camera", "pan_y"),
        "float", "preview_camera.pan_y",
    ),
    SettingCompatibilityRule(
        "expanded_sections.timing", "section-expanded-state-v1",
        ("expanded_sections", "timing"), "bool", "expanded_sections.timing",
    ),
    SettingCompatibilityRule(
        "expanded_sections.prediction", "section-expanded-state-v1",
        ("expanded_sections", "prediction"), "bool", "expanded_sections.prediction",
    ),
    SettingCompatibilityRule(
        "expanded_sections.geometry", "section-expanded-state-v1",
        ("expanded_sections", "geometry"), "bool", "expanded_sections.geometry",
    ),
)

RULE_BY_ID = {rule.stable_id: rule for rule in SETTING_COMPATIBILITY_RULES}
SETTING_COMPATIBILITY_CATALOG = {
    rule.stable_id: rule.token for rule in SETTING_COMPATIBILITY_RULES
}


@dataclass(frozen=True, slots=True)
class SettingMergeResult:
    payload: dict[str, Any]
    accepted_ids: tuple[str, ...]
    rejected_ids: tuple[str, ...]


def _value_at(payload: Mapping[str, Any], path: tuple[str, ...]) -> object:
    current: object = payload
    for part in path:
        if not isinstance(current, Mapping) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _set_value(payload: dict[str, Any], path: tuple[str, ...], value: object) -> None:
    current = payload
    for part in path[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[path[-1]] = deepcopy(value)


def _group_is_valid(group: str, payload: Mapping[str, Any]) -> bool:
    if group == "generation.solid-geometry-v1":
        generation = payload.get("generation")
        if not isinstance(generation, Mapping):
            return False
        try:
            minimum_outer = float(generation["minimum_outer_diameter_mm"])
            maximum_outer = float(generation["maximum_outer_diameter_mm"])
        except (KeyError, TypeError, ValueError):
            return False
        return 3.0 <= minimum_outer <= 99.0 and max(5.0, minimum_outer + 1.0) <= maximum_outer <= 100.0
    if group == "generation.base-v1":
        generation = payload.get("generation")
        if not isinstance(generation, Mapping):
            return False
        automatic = generation.get("automatic_base_width")
        manual = generation.get("manual_base_width_mm")
        return isinstance(automatic, bool) and (
            automatic
            or (
                isinstance(manual, (int, float))
                and not isinstance(manual, bool)
                and 20.0 <= float(manual) <= 80.0
            )
        )
    return True


def merge_compatible_setting_changes(
    base_payload: Mapping[str, Any],
    changes: Mapping[str, object],
) -> SettingMergeResult:
    """Apply only target-compatible values, preserving unsafe groups as a unit."""

    result = deepcopy(dict(base_payload))
    result["setting_compatibility"] = dict(SETTING_COMPATIBILITY_CATALOG)
    candidates_by_group: dict[str, list[tuple[SettingCompatibilityRule, object]]] = {}
    rejected: set[str] = set()

    for stable_id, raw_entry in changes.items():
        rule = RULE_BY_ID.get(stable_id)
        if rule is None or not isinstance(raw_entry, Mapping):
            rejected.add(str(stable_id))
            continue
        if raw_entry.get("token") != rule.token:
            rejected.add(stable_id)
            continue
        try:
            value = rule.normalized_value(raw_entry.get("value"))
        except (TypeError, ValueError):
            rejected.add(stable_id)
            continue
        candidates_by_group.setdefault(rule.group, []).append((rule, value))

    accepted: set[str] = set()
    for group in sorted(candidates_by_group):
        candidates = candidates_by_group[group]
        trial = deepcopy(result)
        for rule, value in candidates:
            _set_value(trial, rule.path, value)
        if not _group_is_valid(group, trial):
            rejected.update(rule.stable_id for rule, _value in candidates)
            continue
        result = trial
        accepted.update(rule.stable_id for rule, _value in candidates)

    return SettingMergeResult(
        payload=result,
        accepted_ids=tuple(sorted(accepted)),
        rejected_ids=tuple(sorted(rejected)),
    )


def project_compatible_settings(
    source_payload: Mapping[str, Any],
    fallback_payload: Mapping[str, Any],
) -> SettingMergeResult:
    source_catalog = source_payload.get("setting_compatibility")
    changes: dict[str, dict[str, object]] = {}
    incompatible_ids: set[str] = set()
    if isinstance(source_catalog, Mapping):
        for rule in SETTING_COMPATIBILITY_RULES:
            source_token = source_catalog.get(rule.stable_id)
            if source_token is None:
                continue
            if source_token != rule.token:
                incompatible_ids.add(rule.stable_id)
                continue
            value = _value_at(source_payload, rule.path)
            if value is _MISSING:
                continue
            changes[rule.stable_id] = {"token": rule.token, "value": value}
    merged = merge_compatible_setting_changes(fallback_payload, changes)
    return SettingMergeResult(
        payload=merged.payload,
        accepted_ids=merged.accepted_ids,
        rejected_ids=tuple(sorted(incompatible_ids | set(merged.rejected_ids))),
    )


def compatible_changes_between(
    baseline_payload: Mapping[str, Any],
    candidate_payload: Mapping[str, Any],
) -> SettingMergeResult:
    changes: dict[str, dict[str, object]] = {}
    for rule in SETTING_COMPATIBILITY_RULES:
        baseline = _value_at(baseline_payload, rule.path)
        candidate = _value_at(candidate_payload, rule.path)
        if candidate is _MISSING or candidate == baseline:
            continue
        changes[rule.stable_id] = {"token": rule.token, "value": candidate}
    return merge_compatible_setting_changes(baseline_payload, changes)


def setting_value(payload: Mapping[str, Any], stable_id: str) -> object:
    rule = RULE_BY_ID[stable_id]
    return _value_at(payload, rule.path)
