from dataclasses import dataclass
import math
from cooling_tower.native_project.defaults import DEFAULT_JOINT_SLICES, DEFAULT_SEPARATE_SLICES


@dataclass(frozen=True, slots=True)
class NativeCalibrationOptions:
    maximum_iterations: int = DEFAULT_JOINT_SLICES
    maximum_runtime_s: float = 1800.
    timeout_per_slice_s: float = 480.
    time_tolerance_s: float = .25
    maximum_path_growth_factor: float = 2.
    minimum_path_growth_mm: float = .5
    material_reduction_factor: float = 1.
    bed_edge_clearance_mm: float = 5.
    maximum_separate_iterations: int = DEFAULT_SEPARATE_SLICES

    def __post_init__(self):
        if type(self.maximum_iterations) is not int or not 1 <= self.maximum_iterations <= 50:
            raise ValueError('Zwischen einem und 50 nativen Durchläufen wählen.')
        if type(self.maximum_separate_iterations) is not int or not 0 <= self.maximum_separate_iterations <= 50:
            raise ValueError('Zwischen 0 und 50 getrennten Durchläufen wählen.')
        for name in ('maximum_runtime_s', 'timeout_per_slice_s', 'time_tolerance_s',
                     'maximum_path_growth_factor', 'minimum_path_growth_mm', 'material_reduction_factor', 'bed_edge_clearance_mm'):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError('Native Verarbeitungsgrenzen müssen positiv und endlich sein.')
