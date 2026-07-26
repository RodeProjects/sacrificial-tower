from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path
from typing import Any, Mapping

from cooling_tower.config import SETTINGS_SCHEMA_VERSION
from cooling_tower.models import GenerationSettings


_GENERATION_FIELD_NAMES = {
    field.name for field in fields(GenerationSettings)
}
_LEGACY_ALIASES = {
    "minimum_radius_mm": "minimum_outer_radius_mm",
    "maximum_radius_mm": "maximum_outer_radius_mm",
    "expansion_angle_deg": "maximum_expansion_angle_deg",
    "contraction_angle_deg": "maximum_contraction_angle_deg",
    "base_width_mm": "manual_base_width_mm",
}


class UserSettingsStore:
    def __init__(
        self,
        user_path: str | Path,
        default_path: str | Path,
    ) -> None:
        self.user_path = Path(user_path)
        self.default_path = Path(default_path)

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
                path = self.default_path.resolve().parent.parent / path
            return path.resolve()
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return (
                self.default_path.resolve().parent.parent / "output"
            ).resolve()

    def load(self) -> tuple[GenerationSettings, dict[str, Any]]:
        defaults = self.load_defaults()
        if not self.user_path.is_file():
            return defaults, {}
        try:
            payload = self._read_payload(self.user_path)
            generation = payload.get("generation", payload)
            merged = defaults.to_dict()
            merged.update(self._migrate_generation(generation))
            return GenerationSettings.from_mapping(merged), payload
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return defaults, {}

    def save(
        self,
        generation: GenerationSettings,
        *,
        output_root: str,
        window_width: int,
        window_height: int,
        preview_quality: str = "balanced",
        preview_camera: Mapping[str, Any] | None = None,
        expanded_sections: Mapping[str, Any] | None = None,
    ) -> Path:
        self.user_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "settings_schema_version": SETTINGS_SCHEMA_VERSION,
            "generation": generation.to_dict(),
            "output_root": output_root,
            "window": {
                "width": window_width,
                "height": window_height,
            },
            "preview_quality": (
                preview_quality
                if preview_quality in {"fast", "balanced", "exact"}
                else "balanced"
            ),
            "preview_camera": dict(preview_camera or {}),
            "expanded_sections": {
                str(name): bool(value)
                for name, value in (expanded_sections or {}).items()
            },
        }
        self.user_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return self.user_path

    @staticmethod
    def _load_generation(
        path: Path,
        fallback: GenerationSettings,
    ) -> GenerationSettings:
        try:
            payload = UserSettingsStore._read_payload(path)
            generation = payload.get("generation", payload)
            merged = fallback.to_dict()
            merged.update(UserSettingsStore._migrate_generation(generation))
            return GenerationSettings.from_mapping(merged)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return fallback

    @staticmethod
    def _read_payload(path: Path) -> dict[str, Any]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Settings payload must be a JSON object.")
        return payload

    @staticmethod
    def _migrate_generation(values: object) -> dict[str, Any]:
        if not isinstance(values, Mapping):
            return {}
        migrated = dict(values)
        for legacy_name, current_name in _LEGACY_ALIASES.items():
            if current_name not in migrated and legacy_name in migrated:
                migrated[current_name] = migrated[legacy_name]
        return {
            name: value
            for name, value in migrated.items()
            if name in _GENERATION_FIELD_NAMES
        }
