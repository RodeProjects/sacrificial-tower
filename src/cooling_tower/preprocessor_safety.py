"""Session-owned bed exclusions; slicer geometry is never modified in place."""
from dataclasses import dataclass, replace
import math


@dataclass(frozen=True, slots=True)
class ExclusionRect:
    x0: float
    y0: float
    x1: float
    y1: float

    def __post_init__(self):
        if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or abs(v) > 2000
                for v in (self.x0, self.y0, self.x1, self.y1)):
            raise ValueError("Sperrflächen benötigen endliche Druckbettkoordinaten.")
        if self.x1 - self.x0 < .2 or self.y1 - self.y0 < .2:
            raise ValueError("Sperrflächen müssen mindestens 0,2 mm breit und tief sein.")

    @property
    def polygon(self):
        return ((self.x0, self.y0), (self.x1, self.y0), (self.x1, self.y1), (self.x0, self.y1))


def with_exclusions(geometry, exclusions):
    if len(exclusions) > 64 or any(not isinstance(zone, ExclusionRect) for zone in exclusions):
        raise ValueError("Höchstens 64 gültige eigene Sperrflächen sind zulässig.")
    return replace(geometry, excluded_polygons=geometry.excluded_polygons + tuple(zone.polygon for zone in exclusions))
