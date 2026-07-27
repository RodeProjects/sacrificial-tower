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
    field.name for field in fields(GenerationSettings)
}
_LEGACY_ALIASES = {
    "minimum_radius_mm": "minimum_outer_radius_mm",
    "maximum_radius_mm": "maximum_outer_radius_mm",
    "expansion_angle_deg": "maximum_expansion_angle_deg",
    "contraction_angle_deg": "maximum_contraction_angle_deg",
    "base_width_mm": "manual_base_width_mm",
}
_GENERATION_DEFAULTS = GenerationSettings().to_dict()
_PREVIEW_QUALITIES = {"fast", "balanced", "exact"}
_WINDOW_KEYS = {"width", "height"}
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

    normalized: dict[str, Any] = {}
    for name in _GENERATION_FIELD_NAMES:
        if name not in migrated:
            continue
        value = migrated[name]
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
    return normalized


def _nest_legacy_generation(payload: dict[str, Any]) -> dict[str, Any]:
    migrated = dict(payload)
    raw_generation = migrated.get("generation")
    generation = (
        dict(raw_generation) if isinstance(raw_generation, Mapping) else {}
    )
    legacy_generation_names = _GENERATION_FIELD_NAMES | set(_LEGACY_ALIASES)
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


def _normalize_user_settings(payload: dict[str, Any]) -> dict[str, Any]:
    nested = _nest_legacy_generation(payload)
    normalized: dict[str, Any] = {
        "generation": _generation_values(nested.get("generation")),
    }

    output_root = nested.get("output_root")
    if isinstance(output_root, str) and output_root.strip():
        normalized["output_root"] = output_root

    raw_window = nested.get("window")
    window: dict[str, int] = {}
    if isinstance(raw_window, Mapping):
        for name in _WINDOW_KEYS:
            value = raw_window.get(name)
            if (
                isinstance(value, int)
                and not isinstance(value, bool)
                and 100 <= value <= 100_000
            ):
                window[name] = value
    if window:
        normalized["window"] = window

    quality = str(nested.get("preview_quality", "")).casefold()
    normalized["preview_quality"] = (
        quality if quality in _PREVIEW_QUALITIES else "balanced"
    )

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
        preview_quality: str = "balanced",
        preview_camera: Mapping[str, Any] | None = None,
        expanded_sections: Mapping[str, Any] | None = None,
    ) -> Path:
        payload = self._build_payload(
            generation,
            output_root=output_root,
            window_width=window_width,
            window_height=window_height,
            preview_quality=preview_quality,
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
        preview_quality: str = "balanced",
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
                preview_quality=preview_quality,
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
        preview_quality: str,
        preview_camera: Mapping[str, Any] | None,
        expanded_sections: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        return {
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
            "setting_compatibility": dict(SETTING_COMPATIBILITY_CATALOG),
        }

    def _default_payload(self, defaults: GenerationSettings) -> dict[str, Any]:
        return {
            "settings_schema_version": SETTINGS_SCHEMA_VERSION,
            "generation": defaults.to_dict(),
            "output_root": str(self.load_default_output_root()),
            "preview_quality": "balanced",
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
