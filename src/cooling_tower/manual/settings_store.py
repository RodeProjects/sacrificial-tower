"""Separate versioned manual preferences; no object geometry is persisted."""
from dataclasses import fields, replace
from pathlib import Path

from cooling_tower.manual.geometry import GeometryError, ManualSettings, validate_settings
from cooling_tower.persistence.versioned_json import VersionedJsonStore, VersionedDocumentError

MANUAL_SCHEMA_VERSION = 8


def migrate_manual_v1(payload):
    """Keep the old threshold only as a visual reference; discard tolerance."""
    raw = payload.get("manual",{})
    manual = dict(raw) if isinstance(raw,dict) else {}
    manual["color_reference_time_s"] = manual.pop("target_layer_time_s",ManualSettings().color_reference_time_s)
    manual.pop("layer_time_tolerance_s",None)
    return {**payload,"manual_settings_schema_version":2,"manual":manual}


def migrate_manual_v2(payload):
    """Enable the new layer grid without changing existing geometry preferences."""
    raw = payload.get("manual", {})
    manual = dict(raw) if isinstance(raw, dict) else {}
    manual["layer_snap_enabled"] = True
    return {**payload, "manual_settings_schema_version": 3, "manual": manual}


def migrate_manual_v3(payload):
    raw = payload.get("manual", {})
    manual = dict(raw) if isinstance(raw,dict) else {}
    manual["object_resolution_percent"] = 50
    return {**payload, "manual_settings_schema_version": 4, "manual": manual}


def migrate_manual_v4(payload):
    """Keep supported percentages; map old stages to the nearest new stage."""
    raw = payload.get("manual", {})
    manual = dict(raw) if isinstance(raw,dict) else {}
    value = manual.get("object_resolution_percent")
    if type(value) is int and value in range(10,101,10):
        manual["object_resolution_percent"] = min((1,3,5,10,15,20,25,50,75,100),
                                                   key=lambda stage:(abs(stage-value),-stage))
    else:
        manual["object_resolution_percent"] = 10
    return {**payload, "manual_settings_schema_version": 5, "manual": manual}


def migrate_manual_v5(payload):
    """Preserve mesh percentages; replace the removed 20% stage with 25%."""
    raw = payload.get("manual", {})
    manual = dict(raw) if isinstance(raw,dict) else {}
    value = manual.get("object_resolution_percent")
    previous_stages = (1,3,5,10,15,20,25,50,75,100)
    manual["object_resolution_percent"] = (25 if value == 20 else value) if (
        type(value) is int and value in previous_stages) else 10
    return {**payload, "manual_settings_schema_version": 6, "manual": manual}


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


def migrate_manual_v6(payload):
    """Keep silhouette mode and move removed mesh stages 1/3 to 5%."""
    raw=payload.get("manual",{})
    manual=dict(raw) if isinstance(raw,dict) else {}
    value=manual.get("object_resolution_percent")
    if type(value) is int and value in (0,1,3,5,10,15,25,50,75,100):
        manual["object_resolution_percent"]=5 if value in (1,3) else value
    else:
        manual["object_resolution_percent"]=10
    return {**payload,"manual_settings_schema_version":7,"manual":manual}


def migrate_manual_v7(payload):
    """Add 1% without changing any previously valid preview selection."""
    raw=payload.get("manual",{})
    manual=dict(raw) if isinstance(raw,dict) else {}
    value=manual.get("object_resolution_percent")
    if type(value) is not int or value not in (0,5,10,15,25,50,75,100):
        manual["object_resolution_percent"]=0
    return {**payload,"manual_settings_schema_version":8,"manual":manual}


class ManualSettingsStore:
    def __init__(self, path: Path):
        self.store = VersionedJsonStore(path, schema_key="manual_settings_schema_version",
                                        current_version=MANUAL_SCHEMA_VERSION,
                                        migrations={0: lambda p: {**p, "manual_settings_schema_version": 1},
                                                    1: migrate_manual_v1,
                                                    2: migrate_manual_v2,
                                                    3: migrate_manual_v3,
                                                    4: migrate_manual_v4,
                                                    5: migrate_manual_v5,
                                                    6: migrate_manual_v6,
                                                    7: migrate_manual_v7},
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
        self.store.save({"manual_settings_schema_version": MANUAL_SCHEMA_VERSION, "manual": settings.to_dict()})

    def recover(self):
        return self.store.replace_with_recovery(normalize_manual_settings({}))
