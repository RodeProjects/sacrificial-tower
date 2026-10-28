"""Compact capture chambers, supported retracts and time-dependent replenishment.

A broad capsule keeps separate capture/departure faces with short perimeters.
The concave foot expands its end radius without stretching wall thickness.
"""
from dataclasses import dataclass, replace
import math

from cooling_tower.postprocessor_toolpaths import TowerPath
from cooling_tower.tower.base_calculator import widen_automatic_foot_width
from cooling_tower.tower.diameter_transitions import full_infill_foot_taper

CAPTURE_SPEED_MM_S = 35.0
TOWER_TRAVEL_CLEARANCE_MM = 2.0
FINAL_TOWER_CLEARANCE_MM = .5
CAPTURE_MARKER = "; SACRIFICIAL_TOWER_CAPTURE"
DEPARTURE_WIPE_MARKER = "; SACRIFICIAL_TOWER_DEPARTURE_WIPE"
DRY_EXIT_MARKER = "; SACRIFICIAL_TOWER_DRY_EXIT"
MODEL_WIPE_MARKER = "; SACRIFICIAL_TOWER_MODEL_DEPARTURE_WIPE"


def supported_tail(points, length=3.0):
    """Keep a bounded tail of a continuous, already deposited planar path."""
    if not points:
        return ()
    # Extremely finely segmented seams must not create an unbounded reverse
    # move list. A too-short remaining tail falls back to stationary retract.
    points = points[-129:]
    result = [points[-1]]
    remaining = length
    for a, b in zip(reversed(points[:-1]), reversed(points[1:])):
        distance = math.dist(a, b)
        if distance <= 1e-9:
            continue
        if distance >= remaining:
            result.append(tuple(b[i]+(a[i]-b[i])*remaining/distance for i in (0, 1)))
            break
        result.append(a)
        remaining -= distance
    return tuple(reversed(result))


@dataclass(frozen=True, slots=True)
class CaptureDesign:
    diameter_mm: float
    reserve_wait_s: float
    rib_count: int
    depth_mm: float
    shape: str = "compact_capsule"
    concave_base_width_mm: float = 0.
    bottom_widths_mm: tuple[float, ...] = ()


def capture_design(height, waits, *, diameter=None):
    reserve = max(waits, default=0.0)
    automatic = max(12.0, height*.10, 12.0*math.sqrt(1+reserve/90.0))
    width = min(100., automatic) if diameter is None else diameter
    return CaptureDesign(width, reserve, 1, min(width-1., max(5., .35*width)))


def configure_capture_design(design, thickness, inner_width):
    minimum_depth = 2*thickness+max(1.5, 2*inner_width)
    depth = max(minimum_depth, min(max(5., .35*design.diameter_mm),
        design.diameter_mm-max(1., 2*inner_width)))
    if depth >= design.diameter_mm:
        raise ValueError("Die Turmbreite ist für Wandstärke und Fangkammern zu klein.")
    return replace(design, depth_mm=depth,
        rib_count=int(design.diameter_mm-depth >= 4*inner_width))


def automatic_capture_base(design, height, *, first_layer_minimum_depth=0.):
    width = widen_automatic_foot_width(max(14., 1.10*design.diameter_mm, height*.25), maximum=150.)
    # Preserve depth against tipping despite the compact shaft. The same
    # concave radius profile widens both axes by the same absolute amount.
    depth = max(12., height*.25, first_layer_minimum_depth)
    return min(150., max(width, design.diameter_mm+depth-design.depth_mm))


def capture_floor_reserve(design, z, reference_height):
    """Transfer the former circular floor/shaft area ratios to the capsule.

    Enlarge only the two closed floor plates. The concave profile starting at
    the third layer keeps its economical dimensions and supported inner taper.
    """
    if not z:
        return ()
    shaft = design.diameter_mm/2
    spine = shaft-design.depth_mm/2
    minor = design.depth_mm/2
    area = math.pi*minor*minor+4*spine*minor
    legacy_base = widen_automatic_foot_width(
        max(14., 1.8*design.diameter_mm, z[-1]*.25), maximum=150.)
    reference = full_infill_foot_taper(z, legacy_base/2, shaft, reference_height)
    result = []
    for height in z[:2]:
        target = area*(reference.radius(height)/shaft)**2
        # Invert A = pi*r^2 + 4*spine*r, keeping the shaft's spine fixed.
        end_radius = math.sqrt((2*spine/math.pi)**2+target/math.pi)-2*spine/math.pi
        result.append(spine+end_radius)
    return tuple(result)


def supported_foot_holes(outer_radii, shaft_radius, thicknesses, heights, widths):
    """Remove a tapering inner wedge while keeping every closure supported.

    Work backwards: a wide lower cavity must already allow the later narrower
    cavity within a bounded overhang. The two solid floors remain unchanged.
    """
    holes = [max(0., shaft_radius-t)+.65*max(0., r-shaft_radius)
        for r, t in zip(outer_radii, thicknesses)]
    for i in range(len(holes)-2, 1, -1):
        allowed = min(heights[i+1]*.5, min(widths[i], widths[i+1])*.30)
        holes[i] = min(holes[i], holes[i+1]+allowed)
    return tuple(holes)


def additional_prime(wait_s, maximum, nominal_filament):
    """Engineering allowance, capped by actual pause and supported bead volume."""
    return min(maximum, max(0., wait_s)*.02, nominal_filament*.15)


@dataclass(frozen=True, slots=True)
class CaptureFrame:
    center: tuple[float, float]
    angle: float
    outer_radius: float  # bounding half-width, along the broad face
    core_radius: float   # inner bounding half-width, including the foot taper
    width: float
    inner_width: float
    height: float
    rib_count: int
    spine_half: float
    shaft_radius: float
    contact_index: int = 0

    def xy(self, u, v=0.):
        c, s = math.cos(self.angle), math.sin(self.angle)
        return self.center[0]+u*c-v*s, self.center[1]+u*s+v*c

    @property
    def minor_radius(self):
        return self.outer_radius-self.spine_half

    @property
    def core_minor(self):
        return self.core_radius-self.spine_half

    @property
    def entry(self):
        return self.xy(self.minor_radius+self.width/2, self.contact_v)

    @property
    def print_start(self):
        return self.xy(-self.minor_radius+self.width/2)

    @property
    def lane_limit(self):
        return max(1e-4, self.spine_half-self.width/2)

    @property
    def lane_guard(self):
        return min(self.lane_limit*.5, max(.5, 1.5*self.inner_width)) if self.rib_count else 0.

    @property
    def contact_lane_count(self):
        side = max(1, min(6, math.floor((self.lane_limit-self.lane_guard)/max(.8, 2*self.inner_width))+1))
        return 2*side

    @property
    def contact_v(self):
        count = self.contact_lane_count
        step = self.contact_index % count
        level = step//2
        fraction = level/max(1, count//2-1)
        value = self.lane_limit-fraction*(self.lane_limit-self.lane_guard)
        return (-1 if step % 2 == 0 else 1)*value

    @property
    def pocket_u(self):
        return self.core_minor-min(.35, self.inner_width*.75)

    @property
    def capture_points(self):
        # Stop early; during the solid foot do not cross the entire annulus.
        thickness = self.shaft_radius-self.core_radius
        u = max(self.pocket_u, self.minor_radius-max(1., thickness+self.width*.75))
        v = self.contact_v
        available = abs(v)-self.lane_guard
        if available >= .3:
            other = math.copysign(abs(v)-min(1.2, available), v)
        else:
            other = math.copysign(abs(v)+min(1.2, self.lane_limit-abs(v)), v)
        return self.entry, self.xy(u, v), self.xy(u, other)

    @property
    def departure_origin(self):
        if self.rib_count:
            return self.internal_paths()[-1].points[-1]
        return self.xy(-self.core_minor-self.inner_width/2)

    @property
    def exit(self):
        point = self.departure_origin
        v = -(point[0]-self.center[0])*math.sin(self.angle)+(point[1]-self.center[1])*math.cos(self.angle)
        return self.xy(-self.minor_radius-self.width/2, v)

    @property
    def departure_points(self):
        return self.departure_origin, self.exit

    def internal_paths(self):
        if not self.rib_count:
            return ()
        bond = min(.06, self.inner_width*.12)
        half = (self.inner_width-self.height*(1-math.pi/4))/2
        back, front = -self.core_minor-bond, self.core_minor+bond
        # Join only the inside edge of the walls. Crossing their full width
        # while extruding would stack material on the same junction each layer.
        return (TowerPath((self.xy(back,-half),self.xy(front,-half)), self.inner_width,"inner"),
            TowerPath((self.xy(front,half),self.xy(back,half)), self.inner_width,"inner"))


def capture_frame(center, park, outer_radius, shaft_radius, width, inner_width,
        height, walls, rib_count, *, contact_index=0, structural_width=None,
        depth_mm=None, core_radius=None):
    angle = math.atan2(park[1]-center[1], park[0]-center[0])
    thickness = width+(walls-1)*(inner_width-height*(1-math.pi/4))
    depth = depth_mm if depth_mm is not None else configure_capture_design(
        capture_design(0., (), diameter=2*shaft_radius), thickness, inner_width).depth_mm
    spine = shaft_radius-depth/2
    ribs = rib_count if spine >= 2*(structural_width or inner_width) else 0
    return CaptureFrame(center, angle, outer_radius,
        shaft_radius-thickness if core_radius is None else core_radius,
        width, structural_width or inner_width, height, ribs, spine, shaft_radius, contact_index)


def alignment_penalty(center, park, model_center):
    """Zero means model -> tower -> waiting point lie on the same ray."""
    a = (center[0]-model_center[0], center[1]-model_center[1])
    b = (park[0]-center[0], park[1]-center[1])
    length = math.hypot(*a)*math.hypot(*b)
    return 1.0-(a[0]*b[0]+a[1]*b[1])/length if length > 1e-9 else 2.0


def capture_obstacle(center, park, design, outer_radius):
    """Circumscribed capsule; the travel planner adds its own 0.5 mm gap."""
    angle = math.atan2(park[1]-center[1], park[0]-center[0])
    spine = (design.diameter_mm-design.depth_mm)/2
    radius = (outer_radius-spine+TOWER_TRAVEL_CLEARANCE_MM-.5)/math.cos(math.pi/64)
    c, s = math.cos(angle), math.sin(angle)
    points = []
    for offset, first in ((-spine, math.pi), (spine, 0.)):
        for i in range(33):
            theta = first+math.pi*i/32
            u, v = radius*math.cos(theta), offset+radius*math.sin(theta)
            points.append((center[0]+u*c-v*s, center[1]+u*s+v*c))
    return tuple(points)


def nearest_capture_point(center, park, design, origin):
    """Closest point outside the virtual shaft, including after early ending."""
    angle = math.atan2(park[1]-center[1], park[0]-center[0])
    c, s = math.cos(angle), math.sin(angle)
    dx, dy = origin[0]-center[0], origin[1]-center[1]
    u, v = dx*c+dy*s, -dx*s+dy*c
    spine = (design.diameter_mm-design.depth_mm)/2
    anchor = min(spine, max(-spine, v))
    length = math.hypot(u,v-anchor)
    if length <= 1e-9:
        # An overhang above an early-ended tower can share its projected axis.
        # Both sides are equally close; prefer the model-facing side.
        u, length = -1., 1.
    radius = design.depth_mm/2+FINAL_TOWER_CLEARANCE_MM
    u, v = radius*u/length, anchor+radius*(v-anchor)/length
    return center[0]+u*c-v*s, center[1]+u*s+v*c
