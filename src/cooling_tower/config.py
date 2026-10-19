from __future__ import annotations

import json
from pathlib import Path
from cooling_tower.write_policy import ensure_writable_output

from cooling_tower.models import GenerationSettings


SETTINGS_SCHEMA_VERSION = 22
_CONFIG_METADATA_KEYS = {
    "angle_storage_reference",
    "settings_schema_version",
    "default_output_root",
    "maximum_joint_slices",
    "maximum_separate_slices",
    "show_setting_limits",
    "setting_compatibility",
    "safety_factor",
    "mesh_segments",
}


def load_generation_settings(path: str | Path) -> GenerationSettings:
    settings_path = Path(path)
    with settings_path.open("r", encoding="utf-8") as handle:
        values = json.load(handle)
    if not isinstance(values, dict):
        raise ValueError("The settings file must contain a JSON object.")
    generation = values.get("generation", values)
    if not isinstance(generation, dict):
        raise ValueError("The generation settings must be a JSON object.")
    if any(container.get("angle_storage_reference", "vertical") != "vertical"
           for container in (values, generation)):
        raise ValueError("Die gespeicherten Winkel besitzen einen unbekannten Bezug; erwartet wird der vertikale Speicherbezug.")
    filtered = {
        key: value
        for key, value in generation.items()
        if key not in _CONFIG_METADATA_KEYS
    }
    return GenerationSettings.from_mapping(filtered)


def save_generation_settings(
    settings: GenerationSettings,
    path: str | Path,
) -> Path:
    settings_path = Path(path)
    ensure_writable_output(settings_path)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    with settings_path.open("w", encoding="utf-8", newline="\n") as handle:
        payload = {
            "settings_schema_version": SETTINGS_SCHEMA_VERSION,
            "angle_storage_reference": "vertical",
            **settings.to_dict(),
        }
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return settings_path.resolve()
