"""Verified physical limits shared by manual editing and fixed slicing."""
import math
from dataclasses import dataclass

from cooling_tower.calibration.gcode_integration import parse_bed_geometry
from cooling_tower.manual.geometry import GeometryError, validate
from cooling_tower.manual.placement import maximum_foot_diameter, manual_placement


def scalar(value):
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def overhang_default(profile):
    from cooling_tower.slicers.support_angles import profile_support_threshold
    value = profile_support_threshold(profile)
    if value is not None:
        return 90-value, "Profilwert, angezeigt zur Horizontalen"
    return 45.0, "Fallback: 45° zur Horizontalen; kein verlässlich interpretierbarer Profilwinkel"


@dataclass(frozen=True, slots=True)
class ManualContext:
    key: str
    layers: tuple
    maximum_height_mm: float
    height_note: str
    bed_geometry: object
    occupied_bounds: object
    brim_width_mm: float
    support_threshold_angle_deg: float | None = None

    @property
    def maximum_foot_diameter_mm(self):
        return maximum_foot_diameter(self.bed_geometry, self.occupied_bounds, self.brim_width_mm)

    @classmethod
    def from_request(cls, request, source_data, key):
        values = request.effective_profile.effective_values
        height = next((n for name in ("printable_height", "max_print_height", "machine_height", "machine_height_mm")
                       if (n := scalar(values.get(name))) is not None and n > 0), None)
        if height is None:
            height = float(request.snapshot.maximum_print_z_mm)
            note = "Maschinenhöhe unbekannt: sicher auf die vorbereitete Objekthöhe begrenzt."
        else:
            note = f"Verifizierte maximale Turmhöhe: {height:.2f} mm.".replace(".",",",1)
        bed = parse_bed_geometry(values)
        if bed is None:
            raise GeometryError("technical_bed", "Das bestätigte Maschinenprofil enthält keine verlässliche Druckbettfläche.")
        brim_type = values.get("brim_type", "none")
        if isinstance(brim_type, (list, tuple)):
            brim_type = brim_type[0] if brim_type else "none"
        brim = max(0, scalar(values.get("brim_width")) or 0) if str(brim_type).casefold() not in {"", "none", "no_brim", "disabled"} else 0
        adapter_id = request.effective_profile.installation.adapter_id
        if adapter_id == "prusa_slicer" and "brim_type" not in values:
            brim = max(0,scalar(values.get("brim_width")) or 0)
        elif adapter_id == "cura":
            adhesion = values.get("adhesion_type","")
            if isinstance(adhesion,(list,tuple)): adhesion = adhesion[0] if adhesion else ""
            brim = max(0,scalar(values.get("brim_width")) or 0) if str(adhesion).casefold() == "brim" else 0
        from cooling_tower.slicers.support_angles import profile_binding_threshold
        return cls(key, tuple(request.snapshot.layers), height, note, bed, source_data.occupied_bounds, brim,
                   profile_binding_threshold(request.effective_profile))

    def validate(self, draft):
        validate(draft)
        if draft.context_key != self.key:
            raise GeometryError("context", "Der Entwurf gehört zu einem anderen Quellen-/Profilkontext.")
        if draft.height_mm > self.maximum_height_mm+1e-9:
            raise GeometryError("height_mm", "Die verifizierte Maschinenhöhe wurde erreicht.")
        if draft.settings.maximum_foot_diameter_mm > self.maximum_foot_diameter_mm+1e-9:
            raise GeometryError("maximum_foot_diameter_mm", "Die maximal verfügbare Fußbreite wurde erreicht.")
        try:
            return manual_placement(self.bed_geometry, self.occupied_bounds,
                                    draft.maximum_radius_mm, self.brim_width_mm)
        except ValueError as error:
            raise GeometryError("technical_bed", str(error)) from error
