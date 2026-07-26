from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LayerData:
    """Service-facing timing data for one detected G-code layer."""

    index: int
    z: float
    height: float
    total_time_s: float
    extrusion_time_s: float
    travel_time_s: float
    extrusion_path_mm: float
    time_deficit_s: float = 0.0

    @classmethod
    def from_layer_record(
        cls,
        layer: object,
        *,
        time_deficit_s: float = 0.0,
    ) -> "LayerData":
        return cls(
            index=int(getattr(layer, "index")),
            z=float(getattr(layer, "z_mm")),
            height=float(getattr(layer, "height_mm")),
            total_time_s=float(getattr(layer, "total_time_s")),
            extrusion_time_s=float(
                getattr(layer, "deposition_time_s")
            ),
            travel_time_s=float(getattr(layer, "travel_time_s")),
            extrusion_path_mm=float(
                getattr(layer, "deposition_path_mm")
            ),
            time_deficit_s=float(time_deficit_s),
        )
