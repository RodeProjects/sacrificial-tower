"""Read-only profile defaults and conservative printhead clearance envelopes."""
from __future__ import annotations

from dataclasses import dataclass, replace
import math


DEFAULT_TOWER_BRIM_WIDTH_MM = 2.0


def profile_number(values, keys, *, allow_zero=False, percent_base=None):
    """Resolve the active extruder only; nil overrides inherit the machine value."""
    for key in keys:
        value = values.get(key)
        while isinstance(value, (tuple, list)):
            value = value[0] if value else None
        if value is None or isinstance(value, bool):
            continue
        if isinstance(value, str) and "," in value:
            value = value.split(",", 1)[0].strip()
        try:
            if isinstance(value, str) and value.strip().endswith("%"):
                if percent_base is None:
                    continue
                number = float(value.strip()[:-1]) * percent_base / 100
            else:
                number = float(value)
        except (ValueError, TypeError):
            continue
        if math.isfinite(number) and (number >= 0 if allow_zero else number > 0):
            return number, key
    return None, None


def resolve_profile_settings(settings, values):
    changes, notes = {}, []
    if settings.automatic_z_hop:
        hop, _ = profile_number(values,
            ("filament_z_hop", "filament_retract_lift", "z_hop", "retract_lift"), allow_zero=True)
        if hop is None or hop == 0:
            changes["z_hop_mm"] = 0.2
            notes.append("Z-Hop: im Profil nicht aktiviert oder nicht verfügbar; Ersatzwert 0,2 mm verwendet.")
        elif hop > 10:
            raise ValueError("Der Profil-Z-Hop ist ungültig.")
        else:
            changes["z_hop_mm"] = hop
            notes.append("Z-Hop: aus dem bestätigten Profil übernommen.")
    if settings.automatic_tower_brim_width:
        changes["tower_brim_width_mm"] = DEFAULT_TOWER_BRIM_WIDTH_MM
    if settings.automatic_tower_brim_gap:
        gap, _ = profile_number(values, ("brim_separation", "brim_object_gap"), allow_zero=True)
        if gap is None:
            changes["tower_brim_gap_mm"] = 0.2
            notes.append("Turm-Brim Abstand: kein verwertbarer Profilwert; Ersatzwert 0,2 mm verwendet.")
        elif gap > 10:
            raise ValueError("Der Profil-Brimabstand ist ungültig.")
        else:
            changes["tower_brim_gap_mm"] = gap
            notes.append("Turm-Brim Abstand: aus dem bestätigten Profil übernommen.")
    definitions = (
        ("automatic_target_time", "target_layer_time_s", ("slow_down_layer_time", "slowdown_below_layer_time"), .1, 3600, "Mindest-Layerzeit"),
        ("automatic_retraction", "retract_mm", ("filament_retraction_length", "filament_retract_length", "retraction_length", "retract_length"), 0, 10, "Rückzug"),
        ("automatic_retraction", "retract_speed_mm_s", ("filament_retraction_speed", "filament_retract_speed", "retraction_speed", "retract_speed"), 1, 100, "Rückzugstempo"),
        ("automatic_print_speed", "print_speed_mm_s", ("outer_wall_speed", "external_perimeter_speed", "perimeter_speed"), 1, 100, "Turmdrucktempo"),
        ("automatic_travel_speed", "travel_speed_mm_s", ("travel_speed",), 1, 300, "Fahrtempo"),
    )
    reference, _ = profile_number(values, ("perimeter_speed", "inner_wall_speed"))
    for flag, field, keys, low, high, title in definitions:
        if not getattr(settings, flag):
            continue
        if field == "target_layer_time_s" and any(profile_flag(values.get(key)) is False for key in ("slow_down_for_layer_cooling", "cooling")):
            notes.append(f"{title}: Profilkühlung deaktiviert; Ersatzwert {settings.target_layer_time_s:g} s verwendet.")
            continue
        value, key = profile_number(values, keys, allow_zero=low == 0,
            percent_base=reference if field == "print_speed_mm_s" else None)
        if value is None:
            notes.append(f"{title}: kein verwertbarer Profilwert; Ersatzwert {getattr(settings, field):g} verwendet.")
        else:
            changes[field] = min(high, max(low, value))
            notes.append(f"{title}: aus dem bestätigten Profil übernommen.")
    if settings.automatic_retraction:
        restore, _ = profile_number(values, ("filament_deretraction_speed", "filament_deretract_speed", "deretraction_speed", "deretract_speed"), allow_zero=True)
        if restore is not None:
            changes["unretract_speed_mm_s"] = min(100, max(1, restore or changes.get("retract_speed_mm_s", settings.retract_speed_mm_s)))
            notes.append("Rückzugsausgleich: eigenes Profiltempo übernommen.")
        changes["restart_extra_mm"] = _restart_extra(values)
        if changes["restart_extra_mm"]:
            notes.append(f"Profil-Wiederanlauf: {changes['restart_extra_mm']:g} mm zusätzlich je ausgeführtem Rückzug.")
    effective = replace(settings, **changes)
    # These limits apply to manual values too: an override cannot exceed a
    # known machine limit or the material's maximum volumetric flow.
    limits = [profile_number(values, keys)[0] for keys in (
        ("machine_max_speed_x", "machine_max_feedrate_x"),
        ("machine_max_speed_y", "machine_max_feedrate_y"))]
    cap = min((value for value in limits if value is not None), default=300)
    if cap < 1:
        raise ValueError("Die bekannte X-/Y-Maschinenbegrenzung liegt unter dem zulässigen Geschwindigkeitsbereich.")
    extruder_cap, _ = profile_number(values, ("machine_max_speed_e", "machine_max_feedrate_e"))
    if extruder_cap is not None:
        if extruder_cap < 1:
            raise ValueError("Die bekannte Extruder-Maschinenbegrenzung liegt unter dem unterstützten Bereich.")
        effective = replace(effective, retract_speed_mm_s=min(effective.retract_speed_mm_s, extruder_cap),
            unretract_speed_mm_s=min(effective.unretract_speed_mm_s or effective.retract_speed_mm_s, extruder_cap))
    return replace(effective, travel_speed_mm_s=min(effective.travel_speed_mm_s, cap),
        print_speed_mm_s=min(effective.print_speed_mm_s, cap)), tuple(notes)


def profile_flag(value):
    while isinstance(value, (list, tuple)):
        value = value[0] if value else None
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if value is None or str(value).strip().lower() not in {"0", "false", "1", "true"}:
        return None
    return str(value).strip().lower() in {"1", "true"}


@dataclass(frozen=True, slots=True)
class FirstLayerParameters:
    wall_speed_mm_s: float
    infill_speed_mm_s: float
    line_width_mm: float
    notes: tuple[str, ...]


def first_layer_parameters(values, *, print_speed, nozzle, line_width, layer_height, adapter_id):
    """First-layer caps also apply to a manually selected tower speed.

    Prusa percentages refer to the corresponding normal feature speed, while
    width percentages use layer height on Prusa and nozzle diameter on Orca.
    """
    perimeter, _ = profile_number(values, ("perimeter_speed", "inner_wall_speed"))
    reference, _ = profile_number(values, ("external_perimeter_speed", "outer_wall_speed", "perimeter_speed"), percent_base=perimeter)
    wall, _ = profile_number(values, ("initial_layer_speed", "first_layer_speed"), percent_base=reference)
    notes = []
    if wall is None:
        wall = min(print_speed, 20.0)
        notes.append("Erstschichttempo fehlt oder ist automatisch: begrenzter Ersatzwert bis 20 mm/s.")
    regular_infill, _ = profile_number(values, ("infill_speed", "sparse_infill_speed"))
    infill_reference, _ = profile_number(values, ("solid_infill_speed", "internal_solid_infill_speed"), percent_base=regular_infill)
    infill, _ = profile_number(values, ("initial_layer_infill_speed", "first_layer_infill_speed"),
        percent_base=infill_reference)
    width_keys = (("first_layer_extrusion_width", "initial_layer_line_width") if adapter_id == "prusa_slicer"
        else ("initial_layer_line_width", "first_layer_extrusion_width"))
    width, _ = profile_number(values, width_keys, percent_base=layer_height if adapter_id == "prusa_slicer" else nozzle)
    if width is None:
        width = line_width
        notes.append("Erstschicht-Linienbreite nicht explizit angegeben: reguläre Profil-Linienbreite verwendet.")
    if not 0 < width <= nozzle * 5:
        raise ValueError("Ungültige Erstschicht-Linienbreite im Profil.")
    wall, infill = min(print_speed, wall), min(print_speed, infill if infill is not None else wall)
    if min(wall, infill) < 1:
        raise ValueError("Das Erstschichttempo liegt unter dem unterstützten Bereich von 1 mm/s.")
    notes.append(f"Erste Turmschicht: Wand {wall:g} mm/s, Füllung {infill:g} mm/s, Linienbreite {width:g} mm.")
    return FirstLayerParameters(wall, infill, width, tuple(notes))


def _restart_extra(values):
    for key in ("filament_retract_restart_extra", "retract_restart_extra"):
        value = values.get(key)
        while isinstance(value, (list, tuple)):
            value = value[0] if value else None
        if value is None or str(value).strip().lower() in {"nil", ""}:
            continue
        if isinstance(value, str) and "," in value:
            value = value.split(",", 1)[0].strip()
        try:
            result = float(value)
        except (ValueError, TypeError):
            raise ValueError("Ungültige zusätzliche Wiederanlaufmenge im Profil.") from None
        if isinstance(value, bool) or not math.isfinite(result) or not -10 <= result <= 10:
            raise ValueError("Zusätzliche Wiederanlaufmenge außerhalb des unterstützten Bereichs.")
        return result
    return 0.0


def flow_limited_speed(settings, values, widths, heights):
    flow = profile_flow_limit(values)
    if flow is None or not heights:
        return settings
    area = max((width - height * (1 - math.pi / 4)) * height for width in widths for height in heights)
    speed = min(settings.print_speed_mm_s, flow / area)
    if speed < 1:
        raise ValueError("Der Profil-Volumenstrom ist für die Turm-Schichthöhe zu klein.")
    return replace(settings, print_speed_mm_s=speed)


def profile_flow_limit(values):
    caps = [profile_number(values, (key,))[0] for key in ("filament_max_volumetric_speed", "max_volumetric_speed")]
    return min((value for value in caps if value is not None), default=None)


@dataclass(frozen=True, slots=True)
class PrintheadEnvelope:
    radius_mm: float
    clearance_height_mm: float
    estimated: bool
    note: str
    lower_radius_mm: float

    @property
    def limitations(self):
        return ("Der Platzbedarf des Druckkopfs ist eine Profilannahme, keine vermessene Maschinengeometrie. "
            "Firmwareinterne Start-, End- und Referenzabläufe sind nicht vollständig geometrisch prüfbar.")


def printhead_envelope(values, geometry):
    radii = [profile_number(values, (key,))[0] for key in
        ("extruder_clearance_radius", "extruder_clearance_max_radius", "extruder_clearance_dist_to_rod")]
    heights = [profile_number(values, (key,))[0] for key in
        ("extruder_clearance_height", "extruder_clearance_height_to_rod")]
    radius = max((r for r in radii if r is not None and r <= 500), default=None)
    lower_radius, _ = profile_number(values, ("extruder_clearance_radius",))
    if lower_radius is not None and lower_radius > 500:
        lower_radius = None
    height = min((h for h in heights if h is not None and h <= 1000), default=None)
    estimated = radius is None or height is None
    if estimated:
        bed = geometry.bounds
        radius = max(radius or 0, 70.0, min(100.0, min(bed.maximum_x_mm - bed.minimum_x_mm,
            bed.maximum_y_mm - bed.minimum_y_mm) * .30))
    if height is None:
        height = 0.0
    lower_radius = lower_radius or radius
    note = ("Druckkopf-Geometrie im Profil unvollständig. Vorsichtig geschätzter Platzbedarf: "
        if estimated else "Platzbedarf des Druckkopfs aus dem bestätigten Profil: ")
    note += f"Unterer Radius {lower_radius:g} mm; zusätzlicher Platzbedarf bis Radius {radius:g} mm ab {height:g} mm über der Düsenspitze."
    if estimated:
        note += " Ersatzmaße gelten für feste Hindernisse und Originalfahrten unterhalb der bereits aufgebauten Turmhöhe; die reale Bauform bleibt unbekannt."
    note += " Profilabstände ersetzen keine vermessene Maschinengeometrie."
    return PrintheadEnvelope(radius, height, estimated, note, lower_radius)
