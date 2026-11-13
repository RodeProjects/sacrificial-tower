"""Independent defaults for new native 3MF automatic sessions."""
from types import MappingProxyType

GENERATION_DEFAULTS = MappingProxyType({
    'automatic_contraction_angle': True,
    'tower_wall_count': 2,
    'layer_time_tolerance_s': 0.25,
    'automatic_base_width': True,
    'automatic_circle_segments': True,
    'circle_segments': 32,
    'base_height_factor': 0.05,
    'base_margin_mm': 2.0,
    'local_reference_window': 51,
    'manual_base_width_mm': 20.0,
    'maximum_contraction_angle_deg': 55.0,
    'maximum_expansion_angle_deg': 50.0,
    'limit_expansion_to_profile': True,
    'maximum_outer_diameter_mm': 40.0,
    'maximum_radius_change_per_mm_z': 0.35,
    'minimum_base_radius_mm': 10.0,
    'minimum_outer_diameter_mm': 5.0,
    'minimum_object_tower_distance_mm': 5.0,
    'minimum_radius_height_factor': 0.04,
    'simulate_full_tower_infill': False,
    'simulate_tower_without_supports': True,
    'top_shell_layers': 1,
    'bottom_shell_layers': 1,
    'automatic_top_shell_layers': False,
    'automatic_bottom_shell_layers': False,
    'extra_top_layer': False,
    'concave_base': False,
    'target_layer_time_s': 9.0,
})

DEFAULT_SEPARATE_SLICES = 6
DEFAULT_JOINT_SLICES = 12
