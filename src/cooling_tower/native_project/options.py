from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class NativeCalibrationOptions:
    maximum_iterations: int = 12
    maximum_runtime_s: float = 1800.
    timeout_per_slice_s: float = 480.
    time_tolerance_s: float = .25
    maximum_path_growth_factor: float = 2.
    minimum_path_growth_mm: float = .5
    material_reduction_factor: float = 1.
    bed_edge_clearance_mm: float = 5.

    def __post_init__(self):
        if isinstance(self.maximum_iterations, bool) or not 1 <= self.maximum_iterations <= 50:
            raise ValueError('Zwischen einem und 50 nativen Durchläufen wählen.')
        for name in ('maximum_runtime_s', 'timeout_per_slice_s', 'time_tolerance_s',
                     'maximum_path_growth_factor', 'minimum_path_growth_mm', 'material_reduction_factor', 'bed_edge_clearance_mm'):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError('Native Verarbeitungsgrenzen müssen positiv und endlich sein.')
