"""Separate versioned manual preferences; no object geometry is persisted."""
from dataclasses import fields, replace
from pathlib import Path

from cooling_tower.manual.geometry import GeometryError, ManualSettings, validate_settings
from cooling_tower.persistence.versioned_json import VersionedJsonStore, VersionedDocumentError

MANUAL_SCHEMA_VERSION = 1


def normalize_manual_settings(payload):
    raw = payload.get("manual", {})
    if not isinstance(raw, dict):
        raw = {}
    defaults = ManualSettings()
    values = defaults.to_dict()
    # Validate each candidate, then dependent diameter/color groups together.
    dependent = {"minimum_diameter_mm", "maximum_diameter_mm", "foot_diameter_mm",
                 "maximum_foot_diameter_mm", "gradient_start_deficit_s", "gradient_full_deficit_s"}
    for item in fields(defaults):
        if item.name in dependent or item.name not in raw:
            continue
        candidate = replace(defaults, **{item.name: raw[item.name]})
        try:
            validate_settings(candidate)
        except GeometryError:
            continue
        values[item.name] = raw[item.name]
    for group in (("minimum_diameter_mm", "maximum_diameter_mm", "foot_diameter_mm", "maximum_foot_diameter_mm"),
                  ("gradient_start_deficit_s", "gradient_full_deficit_s")):
        candidate = {name: raw.get(name, values[name]) for name in group}
        try:
            validate_settings(ManualSettings(**{**values, **candidate}))
        except GeometryError:
            continue
        values.update(candidate)
    return {"manual_settings_schema_version": MANUAL_SCHEMA_VERSION, "manual": values}


class ManualSettingsStore:
    def __init__(self, path: Path):
        self.store = VersionedJsonStore(path, schema_key="manual_settings_schema_version",
                                        current_version=MANUAL_SCHEMA_VERSION,
                                        migrations={0: lambda p: {**p, "manual_settings_schema_version": 1}},
                                        normalizer=normalize_manual_settings,
                                        document_name="Die manuellen Einstellungen")
        self.warning = None

    def load(self):
        if not self.store.path.exists():
            return ManualSettings()
        try:
            return ManualSettings(**self.store.load().payload["manual"])
        except (OSError, VersionedDocumentError) as error:
            self.warning = str(error)
            return ManualSettings()

    def save(self, settings):
        validate_settings(settings)
        self.store.save({"manual_settings_schema_version": 1, "manual": settings.to_dict()})

    def recover(self):
        return self.store.replace_with_recovery(normalize_manual_settings({}))
