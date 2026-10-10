"""Qt-independent cubic radius profiles, exact extrema and atomic editing.

Coordinates are (radius, absolute Z) in millimetres. The radius error of a
tessellated chord is bounded by the convex hull of its Bezier controls, rather
than by samples. Circular polygon error is separate from vertical curve error.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from threading import Event
from uuid import uuid4

from cooling_tower.settings_defaults import GENERATION_DEFAULTS
from cooling_tower.tower.mesh_generator import TriangleMesh

MINIMUM_POINT_GAP_MM = 0.05
CURVE_RADIAL_ERROR_MM = 0.02
MAXIMUM_CURVE_Z_STEP_MM = 1.0
MAXIMUM_PROFILE_POINTS = 2048
EPS = 1e-9


@dataclass(frozen=True, slots=True)
class ManualSettings:
    target_layer_time_s: float = GENERATION_DEFAULTS["target_layer_time_s"]
    layer_time_tolerance_s: float = GENERATION_DEFAULTS["layer_time_tolerance_s"]
    minimum_diameter_mm: float = GENERATION_DEFAULTS["minimum_outer_diameter_mm"]
    maximum_diameter_mm: float = GENERATION_DEFAULTS["maximum_outer_diameter_mm"]
    foot_diameter_mm: float = 25.0
    maximum_foot_diameter_mm: float = 80.0
    foot_height_mm: float = 8.0
    circle_segments: int | None = None
    expansion_enabled: bool = False
    expansion_angle_deg: float = GENERATION_DEFAULTS["maximum_expansion_angle_deg"]
    contraction_enabled: bool = False
    contraction_angle_deg: float = GENERATION_DEFAULTS["maximum_contraction_angle_deg"]
    overhang_enabled: bool = False
    overhang_angle_deg: float = 45.0
    overhang_user_set: bool = False
    critical_layers_enabled: bool = False
    gradient_start_deficit_s: float = 0.0
    gradient_full_deficit_s: float = 1.0

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Coordinate:
    radius_mm: float
    z_mm: float

    @property
    def diameter_mm(self):
        return self.radius_mm * 2

    def lerp(self, other, t):
        return Coordinate(self.radius_mm + (other.radius_mm - self.radius_mm) * t,
                          self.z_mm + (other.z_mm - self.z_mm) * t)


@dataclass(frozen=True, slots=True)
class ProfilePoint:
    identity: str
    position: Coordinate
    kind: str = "free"
    smooth: bool = False


@dataclass(frozen=True, slots=True)
class Cubic:
    start: Coordinate
    control1: Coordinate
    control2: Coordinate
    end: Coordinate
    curved: bool = True

    @classmethod
    def line(cls, start, end):
        return cls(start, start.lerp(end, 1 / 3), start.lerp(end, 2 / 3), end, False)

    def at(self, t):
        a, b, c = (self.start.lerp(self.control1, t),
                   self.control1.lerp(self.control2, t), self.control2.lerp(self.end, t))
        return a.lerp(b, t).lerp(b.lerp(c, t), t)

    def split(self, t):
        a, b, c = (self.start.lerp(self.control1, t),
                   self.control1.lerp(self.control2, t), self.control2.lerp(self.end, t))
        d, e = a.lerp(b, t), b.lerp(c, t)
        middle = d.lerp(e, t)
        return (Cubic(self.start, a, d, middle, self.curved),
                Cubic(middle, e, c, self.end, self.curved))

    def parameter_at_z(self, z):
        lo, hi = 0.0, 1.0
        for _ in range(48):
            mid = (lo + hi) / 2
            if self.at(mid).z_mm < z:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    def coefficients(self, axis):
        a, b, c, d = (getattr(p, axis) for p in
                      (self.start, self.control1, self.control2, self.end))
        return a, 3 * (b - a), 3 * (a - 2 * b + c), -a + 3 * b - 3 * c + d

    def derivative(self, t, axis):
        _, a, b, c = self.coefficients(axis)
        return a + 2 * b * t + 3 * c * t * t

    def radius_extrema(self):
        _, a, b, c = self.coefficients("radius_mm")
        return tuple(self.at(t).radius_mm for t in (0.0, 1.0, *roots(3*c, 2*b, a)))

    def slope_extrema(self):
        _, r0, rb, rc = self.coefficients("radius_mm")
        _, z0, zb, zc = self.coefficients("z_mm")
        r1, r2, z1, z2 = 2*rb, 3*rc, 2*zb, 3*zc
        # Exact stationary points of r'(t)/z'(t); cubic terms cancel.
        ts = (0.0, 1.0, *roots(r2*z1-r1*z2, 2*(r2*z0-r0*z2), r1*z0-r0*z1))
        return tuple(self.derivative(t, "radius_mm") / self.derivative(t, "z_mm") for t in ts)

    def relocated(self, start, end):
        if not self.curved:
            return Cubic.line(start, end)
        def shifted(point, weight):
            return Coordinate(point.radius_mm + (start.radius_mm-self.start.radius_mm)*(1-weight)
                              + (end.radius_mm-self.end.radius_mm)*weight,
                              point.z_mm + (start.z_mm-self.start.z_mm)*(1-weight)
                              + (end.z_mm-self.end.z_mm)*weight)
        return Cubic(start, shifted(self.control1, 1/3), shifted(self.control2, 2/3), end)


def roots(a, b, c):
    """Stable real quadratic roots restricted to the open unit interval."""
    scale = max(abs(a), abs(b), abs(c), 1.0)
    if abs(a) < 1e-14 * scale:
        values = () if abs(b) < 1e-14*scale else (-c/b,)
    else:
        disc = b*b - 4*a*c
        if disc < 0:
            return ()
        q = -0.5 * (b + math.copysign(math.sqrt(disc), b))
        values = (-b/(2*a),) if q == 0 else (q/a, c/q)
    return tuple(t for t in values if 0 < t < 1)


class GeometryError(ValueError):
    def __init__(self, setting, message):
        super().__init__(message)
        self.setting = setting


@dataclass(frozen=True, slots=True)
class ManualDraft:
    settings: ManualSettings
    points: tuple[ProfilePoint, ...]
    curves: tuple[Cubic, ...]  # foot, then body segments
    first_layer_z_mm: float
    maximum_height_mm: float
    context_key: str
    top_follows_base: bool = True

    @property
    def height_mm(self):
        return self.points[-1].position.z_mm

    @property
    def base_diameter_mm(self):
        return self.points[1].position.diameter_mm

    @property
    def foot_diameter_mm(self):
        return self.points[0].position.diameter_mm

    @property
    def maximum_radius_mm(self):
        return max(max(c.radius_extrema()) for c in self.curves)

    def radius_at_z(self, z):
        if z <= self.first_layer_z_mm:
            return self.points[0].position.radius_mm
        for curve in self.curves:
            if z <= curve.end.z_mm + EPS:
                return curve.at(curve.parameter_at_z(z)).radius_mm
        return self.points[-1].position.radius_mm

    def artifact_payload(self):
        # IDs, selection and purely visual options do not alter artifacts.
        return {"curves": [[(p.radius_mm, p.z_mm) for p in
                             (c.start, c.control1, c.control2, c.end)] for c in self.curves],
                "first_layer_z_mm": self.first_layer_z_mm,
                "circle_segments": self.settings.circle_segments,
                "target_layer_time_s": self.settings.target_layer_time_s,
                "layer_time_tolerance_s": self.settings.layer_time_tolerance_s}


def validate_settings(s):
    for name, value in s.to_dict().items():
        default = getattr(ManualSettings(), name)
        if isinstance(default, bool):
            if not isinstance(value, bool):
                raise GeometryError(name, "Die Option benötigt einen gültigen Ein-/Aus-Wert.")
        elif name == "circle_segments":
            if value is not None and (type(value) is not int or not 12 <= value <= 720):
                raise GeometryError(name, "Die Kreissegmentzahl muss zwischen 12 und 720 liegen.")
        elif isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
            raise GeometryError(name, "Der Wert muss eine endliche Zahl sein.")
    for name in ("minimum_diameter_mm", "maximum_diameter_mm", "foot_diameter_mm",
                 "maximum_foot_diameter_mm", "foot_height_mm"):
        if not 0 < getattr(s, name) <= 1000:
            raise GeometryError(name, "Der Wert muss positiv sein und darf 1000 mm nicht überschreiten.")
    if s.minimum_diameter_mm > s.maximum_diameter_mm:
        raise GeometryError("maximum_diameter_mm", "Das Maximum unterschreitet den Mindestdurchmesser.")
    if s.minimum_diameter_mm > s.maximum_foot_diameter_mm or s.foot_diameter_mm > s.maximum_foot_diameter_mm:
        raise GeometryError("maximum_foot_diameter_mm", "Die Fußgrenze reicht für Fuß und Körperanschluss nicht aus.")
    for name in ("expansion_angle_deg", "contraction_angle_deg", "overhang_angle_deg"):
        if not 0.1 <= getattr(s, name) <= 89.0:
            raise GeometryError(name, "Der Winkel zur Vertikalen muss zwischen 0,1° und 89° liegen.")
    if not 5 <= s.target_layer_time_s <= 30:
        raise GeometryError("target_layer_time_s", "Die Ziel-Layerzeit muss zwischen 5 und 30 s liegen.")
    if not 0.1 <= s.layer_time_tolerance_s <= 3:
        raise GeometryError("layer_time_tolerance_s", "Die Toleranz muss zwischen 0,1 und 3 s liegen.")
    if not 0 <= s.gradient_start_deficit_s < s.gradient_full_deficit_s <= 30:
        raise GeometryError("gradient_full_deficit_s", "Die Farbgrenzen müssen 0 ≤ Beginn < vollständig Rot ≤ 30 s erfüllen.")


def validate(draft):
    s = draft.settings
    validate_settings(s)
    if not 3 <= len(draft.points) <= MAXIMUM_PROFILE_POINTS or len(draft.curves) != len(draft.points)-1:
        raise GeometryError("points", "Das Profil benötigt Fuß, Körperanschluss und oberen Abschluss.")
    if len({p.identity for p in draft.points}) != len(draft.points):
        raise GeometryError("points", "Profilpunkte benötigen eindeutige Kennungen.")
    if not math.isfinite(draft.maximum_height_mm) or draft.maximum_height_mm <= 0:
        raise GeometryError("height_mm", "Eine sichere Höhengrenze fehlt.")
    if not math.isfinite(draft.first_layer_z_mm) or draft.first_layer_z_mm <= 0:
        raise GeometryError("foot_height_mm", "Die erste tatsächliche Layerhöhe fehlt.")
    if abs(draft.points[0].position.z_mm - draft.first_layer_z_mm) > EPS:
        raise GeometryError("foot_height_mm", "Der Fußrand muss auf der ersten Druckschicht liegen.")
    if draft.height_mm > draft.maximum_height_mm + EPS:
        raise GeometryError("height_mm", "Die zulässige Maschinen-/Objekthöhe wurde erreicht.")
    if abs(s.foot_diameter_mm - draft.foot_diameter_mm) > EPS or abs(s.foot_height_mm-draft.points[1].position.z_mm) > EPS:
        raise GeometryError("foot_height_mm", "Fußwerte und Profil widersprechen sich.")
    if draft.foot_diameter_mm + EPS < draft.base_diameter_mm:
        raise GeometryError("foot_diameter_mm", "Der Fuß muss mindestens so breit wie der Körperanschluss sein.")
    for i, c in enumerate(draft.curves):
        if c.start != draft.points[i].position or c.end != draft.points[i+1].position:
            raise GeometryError("points", "Die Kurvenanschlüsse stimmen nicht mit den Profilpunkten überein.")
        controls = (c.start, c.control1, c.control2, c.end)
        if any(not math.isfinite(v) for p in controls for v in (p.radius_mm, p.z_mm)):
            raise GeometryError("points", "Profilkoordinaten müssen endlich sein.")
        if c.end.z_mm-c.start.z_mm < MINIMUM_POINT_GAP_MM-EPS:
            raise GeometryError("foot_height_mm" if i == 0 else "point_height_mm", "Benachbarte Punkte benötigen mindestens 0,05 mm Höhenabstand.")
        if any(b.z_mm < a.z_mm for a, b in zip(controls, controls[1:])):
            raise GeometryError("control_height_mm", "Kurvengriffe dürfen in Z nicht rückläufig sein.")
        _, a, b, cc = c.coefficients("z_mm")
        ts = (0.0, 1.0, *roots(0, 6*cc, 2*b))
        if min(c.derivative(t, "z_mm") for t in ts) <= 1e-8:
            raise GeometryError("control_height_mm", "Die Kurve benötigt eine eindeutig steigende Höhe, auch an ihren Enden.")
        radii = c.radius_extrema()
        minimum = 0 if i == 0 else s.minimum_diameter_mm / 2
        maximum = (s.maximum_foot_diameter_mm if i == 0 else s.maximum_diameter_mm) / 2
        if min(radii) <= 0 or min(radii) < minimum-EPS:
            raise GeometryError("minimum_diameter_mm", "Die vollständige Kurve unterschreitet den Mindestdurchmesser.")
        if max(radii) > maximum+EPS:
            raise GeometryError("maximum_foot_diameter_mm" if i == 0 else "maximum_diameter_mm", "Die vollständige Kurve überschreitet den Maximaldurchmesser.")
        slopes = c.slope_extrema()
        if s.expansion_enabled and max(slopes) > math.tan(math.radians(s.expansion_angle_deg))+EPS:
            raise GeometryError("expansion_angle_deg", "Die lokale Aufweitung überschreitet den aktivierten Winkel zur Vertikalen.")
        if s.contraction_enabled and -min(slopes) > math.tan(math.radians(s.contraction_angle_deg))+EPS:
            raise GeometryError("contraction_angle_deg", "Die lokale Verjüngung überschreitet den aktivierten Winkel zur Vertikalen.")
    for i,p in enumerate(draft.points[1:-1],1):
        if p.smooth:
            a,b = draft.curves[i-1:i+1]
            incoming = a.derivative(1,"radius_mm")/a.derivative(1,"z_mm")
            outgoing = b.derivative(0,"radius_mm")/b.derivative(0,"z_mm")
            if abs(incoming-outgoing) > 1e-6:
                raise GeometryError("points","Die gekoppelten Tangenten müssen am gemeinsamen Profilpunkt dieselbe Steigung besitzen.")
    return draft


def initial_draft(settings, layers, maximum_height_mm, context_key):
    validate_settings(settings)
    height = min(float(layers[-1].z_mm), maximum_height_mm)
    first = float(layers[0].z_mm)
    if height-first < 2*MINIMUM_POINT_GAP_MM:
        raise GeometryError("height_mm", "Das Objekt ist für Fußkurve und Turmkörper zu niedrig.")
    body = settings.minimum_diameter_mm / 2
    foot = min(settings.maximum_foot_diameter_mm, max(settings.foot_diameter_mm, 2*body+2)) / 2
    foot_z = max(first+MINIMUM_POINT_GAP_MM, min(settings.foot_height_mm, height-MINIMUM_POINT_GAP_MM))
    start, end = Coordinate(foot, first), Coordinate(body, foot_z)
    dz, dr = foot_z-first, foot-body
    curve = Cubic(start, Coordinate(body+dr*.2, first+dz*.3), Coordinate(body, first+dz*.7), end)
    top = Coordinate(body, height)
    s = replace(settings, foot_diameter_mm=foot*2, foot_height_mm=foot_z,
                circle_segments=settings.circle_segments or max(25, math.ceil(foot*2)))
    d = ManualDraft(s, (ProfilePoint("foot", start, "foot"), ProfilePoint("base", end, "base"),
                       ProfilePoint("top", top, "top")), (curve, Cubic.line(end, top)),
                    first, maximum_height_mm, context_key)
    return validate(d)


def move_point(draft, identity, *, diameter_mm=None, z_mm=None):
    index = next(i for i, p in enumerate(draft.points) if p.identity == identity)
    positions = [p.position for p in draft.points]
    old = positions[index]
    radius = old.radius_mm if diameter_mm is None else diameter_mm/2
    z = old.z_mm if z_mm is None else z_mm
    if index == 0:
        z = draft.first_layer_z_mm
    if index == len(positions)-1:
        radius = old.radius_mm
    positions[index] = Coordinate(radius, z)
    if index == 1:
        if radius*2 > draft.settings.maximum_foot_diameter_mm:
            raise GeometryError("maximum_foot_diameter_mm", "Die maximale Fußbreite begrenzt den Körperanschluss.")
        if radius >= positions[0].radius_mm:
            positions[0] = Coordinate(min(draft.settings.maximum_foot_diameter_mm/2, radius+1), positions[0].z_mm)
        if draft.top_follows_base and len(positions) == 3:
            positions[-1] = Coordinate(radius, positions[-1].z_mm)
    points = tuple(replace(p, position=pos) for p, pos in zip(draft.points, positions))
    curves = tuple(c.relocated(positions[i], positions[i+1]) for i, c in enumerate(draft.curves))
    # Keep the foot's relative radial shape when its endpoints change.
    old_foot, new_foot = draft.curves[0], curves[0]
    old_dr = old_foot.start.radius_mm-old_foot.end.radius_mm
    new_dr = new_foot.start.radius_mm-new_foot.end.radius_mm
    if old_dr > EPS:
        def foot_control(p, moved):
            fraction = (p.radius_mm-old_foot.end.radius_mm)/old_dr
            return Coordinate(new_foot.end.radius_mm+fraction*new_dr, moved.z_mm)
        curves = (replace(new_foot, control1=foot_control(old_foot.control1, new_foot.control1),
                          control2=foot_control(old_foot.control2, new_foot.control2)), *curves[1:])
    s = replace(draft.settings, foot_diameter_mm=positions[0].diameter_mm, foot_height_mm=positions[1].z_mm)
    updated = replace(draft, points=points, curves=curves, settings=s)
    for i,p in enumerate(points[1:-1],1):
        if p.smooth:
            incoming,outgoing = updated.curves[i-1:i+1]
            dz = incoming.control2.z_mm-p.position.z_mm
            if abs(dz) < 1e-8:
                raise GeometryError("control_height_mm","Gekoppelte Tangenten benötigen einen eindeutigen Höhenabstand.")
            slope = (incoming.control2.radius_mm-p.position.radius_mm)/dz
            control1 = Coordinate(p.position.radius_mm+slope*(outgoing.control1.z_mm-p.position.z_mm),outgoing.control1.z_mm)
            current_curves = list(updated.curves)
            current_curves[i] = replace(outgoing,control1=control1,curved=True)
            updated = replace(updated,curves=tuple(current_curves))
    return validate(updated)


def insert_point(draft, z_mm):
    if len(draft.points) >= MAXIMUM_PROFILE_POINTS:
        raise GeometryError("points", "Das Schutzlimit von 2048 Profilpunkten wurde erreicht.")
    for i, c in enumerate(draft.curves[1:], 1):
        if c.start.z_mm+MINIMUM_POINT_GAP_MM <= z_mm <= c.end.z_mm-MINIMUM_POINT_GAP_MM:
            left, right = c.split(c.parameter_at_z(z_mm))
            point = ProfilePoint(uuid4().hex, left.end)
            result = replace(draft, points=(*draft.points[:i+1], point, *draft.points[i+1:]),
                             curves=(*draft.curves[:i], left, right, *draft.curves[i+1:]), top_follows_base=False)
            return validate(result), point.identity
    raise GeometryError("point_height_mm", "Ein neuer Körperpunkt benötigt 0,05 mm Abstand zu seinen Nachbarn und zum Fuß.")


def remove_point(draft, identity):
    i = next(i for i, p in enumerate(draft.points) if p.identity == identity)
    if draft.points[i].kind != "free":
        raise GeometryError("points", "Fuß, Körperanschluss und oberer Abschluss können nicht entfernt werden.")
    a, b = draft.curves[i-1], draft.curves[i]
    c = Cubic(a.start, a.control1, b.control2, b.end) if a.curved or b.curved else Cubic.line(a.start, b.end)
    return validate(replace(draft, points=(*draft.points[:i], *draft.points[i+1:]),
                            curves=(*draft.curves[:i-1], c, *draft.curves[i+1:])))


def set_curve(draft, index, *, curved=None, control=None, position=None):
    c = draft.curves[index]
    if curved is not None:
        if index == 0 and not curved:
            raise GeometryError("points", "Der Fuß bleibt ein eigener Bézierabschnitt.")
        c = replace(c, curved=True) if curved else Cubic.line(c.start, c.end)
    if control is not None:
        c = replace(c, **{f"control{control}": position}, curved=True)
    curves = list(draft.curves)
    curves[index] = c
    for selected_control in ((control,) if control is not None else (1,2)):
        position = getattr(c,f"control{selected_control}")
        anchor_index = index if selected_control == 1 else index+1
        anchor = draft.points[anchor_index]
        opposite = (index-1,2) if selected_control == 1 else (index+1,1)
        if anchor.smooth and 0 <= opposite[0] < len(curves):
            other = curves[opposite[0]]
            original = getattr(other,f"control{opposite[1]}")
            dz = position.z_mm-anchor.position.z_mm
            if abs(dz) < 1e-8:
                raise GeometryError("control_height_mm","Gekoppelte Tangenten benötigen einen eindeutigen Höhenabstand.")
            slope = (position.radius_mm-anchor.position.radius_mm)/dz
            linked = Coordinate(anchor.position.radius_mm+slope*(original.z_mm-anchor.position.z_mm),original.z_mm)
            curves[opposite[0]] = replace(other,**{f"control{opposite[1]}":linked},curved=True)
    return validate(replace(draft, curves=tuple(curves)))


def couple_point(draft,identity,enabled):
    i = next(i for i,p in enumerate(draft.points) if p.identity == identity)
    if not 0 < i < len(draft.points)-1:
        raise GeometryError("points","Tangenten lassen sich nur an einem inneren Profilpunkt koppeln.")
    points = list(draft.points)
    points[i] = replace(points[i],smooth=enabled)
    candidate = replace(draft,points=tuple(points))
    if not enabled:
        return validate(candidate)
    incoming = candidate.curves[i-1]
    return set_curve(candidate,i-1,control=2,position=incoming.control2)


def bounded_edit(draft, operation):
    """Try a continuous movement, then find its closest valid fraction."""
    try:
        return operation(1.0), None
    except GeometryError as error:
        limiting = error
    lo, hi, best = 0.0, 1.0, draft
    for _ in range(32):
        mid = (lo+hi)/2
        try:
            candidate = operation(mid)
        except GeometryError as error:
            limiting = error
            hi = mid
        else:
            lo, best = mid, candidate
    return best, limiting


@dataclass(frozen=True, slots=True)
class MeshPoint:
    radius_mm: float
    z_mm: float


@dataclass(frozen=True, slots=True)
class TessellatedProfile:
    points: tuple[MeshPoint, ...]


def tessellate(draft, cancellation_event: Event | None = None, *, radial_error_mm=CURVE_RADIAL_ERROR_MM):
    validate(draft)
    if not math.isfinite(radial_error_mm) or radial_error_mm <= 0:
        raise ValueError("The radial curve tolerance must be positive and finite.")
    result = [MeshPoint(draft.foot_diameter_mm/2, 0.0),
              MeshPoint(draft.foot_diameter_mm/2, draft.first_layer_z_mm)]
    def sample(c, depth=0):
        if cancellation_event is not None and cancellation_event.is_set():
            from cooling_tower.preview import PreviewCancelled
            raise PreviewCancelled()
        dz = c.end.z_mm-c.start.z_mm
        slope = (c.end.radius_mm-c.start.radius_mm)/dz
        error = max(abs(p.radius_mm-c.start.radius_mm-slope*(p.z_mm-c.start.z_mm)) for p in (c.control1, c.control2))
        if error <= radial_error_mm and dz <= MAXIMUM_CURVE_Z_STEP_MM:
            result.append(MeshPoint(c.end.radius_mm, c.end.z_mm))
        elif depth >= 24:
            raise GeometryError("points", "Die Kurve kann nicht innerhalb der sicheren Tessellierungsgrenzen aufgelöst werden.")
        else:
            a, b = c.split(.5)
            sample(a, depth+1)
            sample(b, depth+1)
    for curve in draft.curves:
        sample(curve)
    return TessellatedProfile(tuple(result))


def _check_cancellation(event):
    if event is not None and event.is_set():
        from cooling_tower.preview import PreviewCancelled
        raise PreviewCancelled()


class _CancelableFaces(tuple):
    """Keep existing mesh validation/STL writing interruptible without changing them."""
    def __new__(cls,values,event):
        instance = super().__new__(cls,values)
        instance.event = event
        return instance

    def __iter__(self):
        for i,value in enumerate(super().__iter__()):
            if i % 1024 == 0: _check_cancellation(self.event)
            yield value


def create_mesh(draft, cancellation_event=None):
    profile = tessellate(draft,cancellation_event)
    count = draft.settings.circle_segments
    vertices,faces = [],[]
    for p in profile.points:
        _check_cancellation(cancellation_event)
        vertices.extend((p.radius_mm*math.cos(math.tau*i/count),p.radius_mm*math.sin(math.tau*i/count),p.z_mm) for i in range(count))
    for ring in range(len(profile.points)-1):
        _check_cancellation(cancellation_event)
        for i in range(count):
            k = (i+1)%count
            a,b,c,d = ring*count+i,ring*count+k,(ring+1)*count+i,(ring+1)*count+k
            faces.extend(((a,b,d),(a,d,c)))
    bottom,top = len(vertices),len(vertices)+1
    vertices.extend(((0,0,0),(0,0,draft.height_mm)))
    last = (len(profile.points)-1)*count
    for i in range(count):
        k = (i+1)%count
        faces.extend(((bottom,k,i),(top,last+i,last+k)))
    _check_cancellation(cancellation_event)
    return TriangleMesh(tuple(vertices),_CancelableFaces(faces,cancellation_event),len(profile.points),count)
