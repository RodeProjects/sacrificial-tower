from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from test_phase2 import make_layer
from cooling_tower.native_project.adjust import adjust_radius_profile, joint_growth_scale
from cooling_tower.native_project.options import NativeCalibrationOptions
from cooling_tower.native_project.settings import NativeGenerationSettings, effective_generation_settings
from cooling_tower.tower.profile import TowerProfileConfig, build_tower_radius_profile


class NativeJointFeedbackTests(unittest.TestCase):
    def test_native_wide_foot_preserves_regular_diameter_limit_and_stl_default(self):
        from cooling_tower.tower.solid_profile import build_solid_tower_profile, ProfileFeasibilityError
        from cooling_tower.tower.mesh_generator import generate_solid_tower_mesh, TowerMeshConfig
        from cooling_tower.tower.mesh_validator import validate_triangle_mesh
        layers = tuple(make_layer(i,total_time_s=20.,deposition_time_s=10.,deposition_path_mm=100.) for i in range(1,1001))
        settings = NativeGenerationSettings(simulate_full_tower_infill=True)
        profile = build_tower_radius_profile(layers,TowerProfileConfig(9.,2.5,20.,5,frozenset()))
        with self.assertRaises(ProfileFeasibilityError):
            build_solid_tower_profile(profile,settings,object_height_mm=200.)
        solid = build_solid_tower_profile(profile,settings,object_height_mm=200.,allow_wide_base=True)
        self.assertAlmostEqual(solid.base_outer_radius_mm,26.25)
        self.assertGreater(solid.base_outer_radius_mm,settings.maximum_outer_radius_mm)
        self.assertTrue(all(point.radius_mm<=settings.maximum_outer_radius_mm for point in solid.points if point.z_mm>100.))
        mesh = generate_solid_tower_mesh(solid,TowerMeshConfig(60))
        self.assertTrue(validate_triangle_mesh(mesh).is_valid)

    def test_profile_threshold_uses_embedded_adapter_value_without_mutating_manual_setting(self):
        from types import SimpleNamespace
        manual = NativeGenerationSettings(maximum_expansion_angle_deg=50.)
        for adapter,key in (('prusa_slicer','support_material_threshold'),
                            ('bambu_studio','support_threshold_angle'),
                            ('anycubic_slicer_next','support_threshold_angle'),
                            ('orca_slicer','support_threshold_angle')):
            with self.subTest(adapter=adapter):
                context = SimpleNamespace(adapter_id=adapter,settings={key:'25.5'})
                resolved = effective_generation_settings(manual,context)
                self.assertEqual(resolved.maximum_expansion_angle_deg,64.5)
                self.assertEqual(manual.maximum_expansion_angle_deg,50.)
                free = NativeGenerationSettings(limit_expansion_to_profile=False)
                self.assertIs(effective_generation_settings(free,context),free)
                context.settings[key] = '0'
                self.assertEqual(effective_generation_settings(manual,context).maximum_expansion_angle_deg,60.)
                context.settings[key] = 'nan'
                self.assertIs(effective_generation_settings(manual,context),manual)

    def test_cooling_replan_corrects_actual_radius_and_preserves_excluded_layers(self):
        layers = tuple(make_layer(i, total_time_s=20., deposition_time_s=10.,
                                  deposition_path_mm=100.) for i in (1, 2))
        profile = build_tower_radius_profile(layers, TowerProfileConfig(
            12., 2.5, 40., 5, frozenset((2,))))
        options = NativeCalibrationOptions()
        combined = {1: 10., 2: 10.}
        scale = joint_growth_scale({1: combined[1]}, target_time_s=12., config=options)
        adjusted, _ = adjust_radius_profile(profile, layers, {1: 0., 2: 0.},
            target_time_s=12., realized_outer_radii_mm={1: 10., 2: 10.},
            combined_layer_times_s=combined, coupled_radius_scale=scale, config=options)
        # The source alone exceeded the target; a changed joint cooling plan
        # must still enlarge the actual deficient cross-section.
        self.assertGreater(adjusted.layers[0].radius_mm, 10.)
        self.assertLessEqual(adjusted.layers[0].radius_mm, 40.)
        self.assertEqual(adjusted.layers[1].radius_mm, 2.5)


if __name__ == '__main__':
    unittest.main()
