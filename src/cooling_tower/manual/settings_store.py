"""Separate versioned manual preferences; no object geometry is persisted."""
from dataclasses import fields, replace
import math
from pathlib import Path

from cooling_tower.manual.geometry import GeometryError, ManualSettings, MINIMUM_TOWER_DIAMETER_MM, MAXIMUM_MANUAL_CIRCLE_SEGMENTS, validate_settings
from cooling_tower.persistence.versioned_json import VersionedJsonStore, VersionedDocumentError

MANUAL_SCHEMA_VERSION = 19


def migrate_manual_v1(payload):
    """Keep the old threshold only as a visual reference; discard tolerance."""
    raw = payload.get("manual",{})
    manual = dict(raw) if isinstance(raw,dict) else {}
    manual["color_reference_time_s"] = manual.pop("target_layer_time_s",10.0)
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
    # Validate independent candidates, then the dependent diameter group.
    dependent = {"minimum_diameter_mm", "maximum_diameter_mm", "foot_diameter_mm",
                 "maximum_foot_diameter_mm","color_reference_time_s","color_deficit_time_s","color_scale_max_time_s"}
    for item in fields(defaults):
        if item.name in dependent or item.name not in raw:
            continue
        candidate = replace(defaults, **{item.name: raw[item.name]})
        try:
            validate_settings(candidate)
        except GeometryError:
            continue
        values[item.name] = raw[item.name]
    reference=raw.get("color_reference_time_s",defaults.color_reference_time_s)
    if type(reference) in (int,float) and math.isfinite(reference) and reference>=3:
        values["color_reference_time_s"]=reference
    values["color_deficit_time_s"]=min(defaults.color_deficit_time_s,values["color_reference_time_s"])
    deficit=raw.get("color_deficit_time_s",defaults.color_deficit_time_s)
    if type(deficit) in (int,float) and math.isfinite(deficit) and 0<=deficit<=values["color_reference_time_s"]:
        values["color_deficit_time_s"]=deficit
    maximum=raw.get("color_scale_max_time_s")
    if type(maximum) in (int,float) and math.isfinite(maximum) and maximum>=values["color_reference_time_s"]:
        values["color_scale_max_time_s"]=math.ceil(maximum*10-1e-9)/10 if maximum<1e14 else float(maximum)
    else:
        reference=values["color_reference_time_s"]
        values["color_scale_max_time_s"]=max(14.,math.ceil(reference*10)/10 if reference<1e14 else float(reference))
    for group in (("minimum_diameter_mm", "maximum_diameter_mm", "foot_diameter_mm", "maximum_foot_diameter_mm"),):
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


def migrate_manual_v8(payload):
    """Interpret existing preview selections as automatic quality preferences."""
    raw=payload.get("manual",{})
    manual=dict(raw) if isinstance(raw,dict) else {}
    value=manual.get("object_resolution_percent")
    if type(value) is not int or value not in (0,1,5,10,15,25,50,75,100):
        manual["object_resolution_percent"]=0
    return {**payload,"manual_settings_schema_version":9,"manual":manual}


def migrate_manual_v9(payload):
    """Raise old positive sub-millimetre diameter preferences to the new floor."""
    raw = payload.get("manual", {})
    manual = dict(raw) if isinstance(raw,dict) else {}
    for name in ("minimum_diameter_mm", "maximum_diameter_mm", "foot_diameter_mm", "maximum_foot_diameter_mm"):
        value = manual.get(name)
        if type(value) in (int,float) and math.isfinite(value) and 0 < value < MINIMUM_TOWER_DIAMETER_MM:
            manual[name] = MINIMUM_TOWER_DIAMETER_MM
    return {**payload,"manual_settings_schema_version":10,"manual":manual}


def migrate_manual_v10(payload):
    """Replace deficit thresholds with absolute green/red layer times."""
    raw = payload.get("manual", {})
    manual = dict(raw) if isinstance(raw,dict) else {}
    reference = manual.get("color_reference_time_s",10.0)
    if type(reference) not in (int,float) or not math.isfinite(reference) or not 5 <= reference <= 30:
        reference = 10.0
    start = manual.pop("gradient_start_deficit_s",0.0)
    full = manual.pop("gradient_full_deficit_s",1.0)
    valid = (all(type(value) in (int,float) and math.isfinite(value) for value in (start,full))
             and 0 <= start < full <= 30)
    manual["color_reference_time_s"] = reference
    manual["color_red_time_s"] = reference + (full-start if valid else 1.0)
    return {**payload,"manual_settings_schema_version":11,"manual":manual}


def migrate_manual_v11(payload):
    """Preserve the fade width as a positive deficit; reverse the color direction."""
    raw = payload.get("manual", {})
    manual = dict(raw) if isinstance(raw,dict) else {}
    reference = manual.get("color_reference_time_s",10.0)
    valid_reference = type(reference) in (int,float) and math.isfinite(reference) and 5 <= reference <= 30
    red = manual.pop("color_red_time_s",None)
    valid_red = (valid_reference and type(red) in (int,float) and math.isfinite(red)
                 and reference < red <= 60)
    manual["color_reference_time_s"] = reference if valid_reference else 10.0
    manual["color_deficit_time_s"] = red-reference if valid_red else 4.0
    return {**payload,"manual_settings_schema_version":12,"manual":manual}


def migrate_manual_v12(payload):
    """Cap tower complexity and represent only physically valid red layer times."""
    raw=payload.get("manual",{})
    manual=dict(raw) if isinstance(raw,dict) else {}
    segments=manual.get("circle_segments")
    if type(segments) is int and 12<=segments<=720:manual["circle_segments"]=min(segments,MAXIMUM_MANUAL_CIRCLE_SEGMENTS)
    reference=manual.get("color_reference_time_s",10.)
    deficit=manual.get("color_deficit_time_s",4.)
    if (type(reference) in (int,float) and math.isfinite(reference) and 5<=reference<=30
            and type(deficit) in (int,float) and math.isfinite(deficit) and 0<deficit<=60):
        manual["color_deficit_time_s"]=min(deficit,reference)
    return {**payload,"manual_settings_schema_version":13,"manual":manual}


def migrate_manual_v13(payload):
    """Add the displayed time-axis end without changing either color boundary."""
    raw=payload.get("manual",{})
    manual=dict(raw) if isinstance(raw,dict) else {}
    reference=manual.get("color_reference_time_s",10.)
    valid=type(reference) in (int,float) and math.isfinite(reference) and 5<=reference<=30
    manual["color_scale_max_time_s"]=max(14.,math.ceil(reference*10)/10) if valid else 14.
    return {**payload,"manual_settings_schema_version":14,"manual":manual}


def migrate_manual_v14(payload):
    """Allow lower color times without accepting invalid values from schema 14."""
    raw=payload.get("manual",{})
    manual=dict(raw) if isinstance(raw,dict) else {}
    reference=manual.get("color_reference_time_s",10.)
    if type(reference) not in (int,float) or not math.isfinite(reference) or not 5<=reference<=30:
        manual["color_reference_time_s"]=10.
    return {**payload,"manual_settings_schema_version":15,"manual":manual}


def migrate_manual_v15(payload):
    """Allow object-dependent scale limits, preserving the old validity rules."""
    raw=payload.get("manual",{})
    manual=dict(raw) if isinstance(raw,dict) else {}
    maximum=manual.get("color_scale_max_time_s")
    if type(maximum) not in (int,float) or not math.isfinite(maximum) or not 0<maximum<=3600:
        manual.pop("color_scale_max_time_s",None)
    return {**payload,"manual_settings_schema_version":16,"manual":manual}


def migrate_manual_v16(payload):
    """Extend the green range without accepting formerly invalid references."""
    raw=payload.get("manual",{})
    manual=dict(raw) if isinstance(raw,dict) else {}
    reference=manual.get("color_reference_time_s",10.)
    if type(reference) not in (int,float) or not math.isfinite(reference) or not 3<=reference<=30:
        manual["color_reference_time_s"]=10.
    return {**payload,"manual_settings_schema_version":17,"manual":manual}


def migrate_manual_v17(payload):
    """Enable hard color boundaries; zero was invalid in the previous schema."""
    raw=payload.get("manual",{})
    manual=dict(raw) if isinstance(raw,dict) else {}
    reference=manual.get("color_reference_time_s",10.)
    if type(reference) not in (int,float) or not math.isfinite(reference) or reference<3:
        reference=10.
    deficit=manual.get("color_deficit_time_s",4.)
    if type(deficit) not in (int,float) or not math.isfinite(deficit) or not 0<deficit<=reference:
        manual["color_deficit_time_s"]=min(4.,reference)
    return {**payload,"manual_settings_schema_version":18,"manual":manual}


def migrate_manual_v18(payload):
    """Keep stored vertical angles; profile binding starts disabled."""
    raw = payload.get("manual", {})
    manual = dict(raw) if isinstance(raw, dict) else {}
    manual["limit_expansion_to_profile"] = False
    return {**payload, "manual_settings_schema_version": 19, "manual": manual}


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
                                                    7: migrate_manual_v7,
                                                    8: migrate_manual_v8,
                                                    9: migrate_manual_v9,
                                                    10: migrate_manual_v10,
                                                    11: migrate_manual_v11,
                                                    12: migrate_manual_v12,
                                                    13: migrate_manual_v13,
                                                    14: migrate_manual_v14,
                                                    15: migrate_manual_v15,
                                                    16: migrate_manual_v16,
                                                    17: migrate_manual_v17,
                                                    18: migrate_manual_v18},
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
