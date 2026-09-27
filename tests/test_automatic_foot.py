import math
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from cooling_tower.models import GenerationSettings
from cooling_tower.tower.profile import TowerRadiusProfile, TowerProfileConfig
from cooling_tower.tower.profile import _get_time_factor_reference
from cooling_tower.tower.solid_profile import build_solid_tower_profile
from cooling_tower.tower.mesh_generator import generate_solid_tower_mesh, TowerMeshConfig, validate_triangle_mesh
from test_solid_tower_changes import radius_layer


class AutomaticFootTests(unittest.TestCase):
    def test_timing_window_does_not_anticipate_later_large_surface(self):
        layers = tuple(SimpleNamespace(index=i+1, total_time_s=(1 if i < 30 else 30),
            deposition_time_s=(1 if i < 30 else 20), deposition_path_mm=(10 if i < 30 else 40))
            for i in range(60))
        before = _get_time_factor_reference(layers=layers, layer_position=29,
            window_size=51, global_seconds_per_mm=0.4, target_time_s=10)
        after = _get_time_factor_reference(layers=layers, layer_position=30,
            window_size=51, global_seconds_per_mm=0.4, target_time_s=10)
        self.assertAlmostEqual(before.seconds_per_mm, 0.1)
        self.assertEqual(before.end_layer, 30)
        self.assertAlmostEqual(after.seconds_per_mm, 0.5)
        self.assertEqual(after.start_layer, 31)

    def make_profile(self, heights, radii=None, *, full=True, angle=10, object_height=160, sufficient=(), manual_width=20):
        radii = radii or [2.0] * len(heights)
        layers = []
        for i, (z, radius) in enumerate(zip(heights, radii)):
            layer = radius_layer(index=i + 1, z=z, calculated_radius=radius, radius=radius)
            if i in sufficient:
                layer = replace(layer, layer_time_s=30.0, time_deficit_s=0.0)
            layers.append(layer)
        source = TowerRadiusProfile(TowerProfileConfig(10), 0.1, tuple(layers))
        settings = GenerationSettings(minimum_outer_diameter_mm=4,
            maximum_outer_diameter_mm=max(40, manual_width),
            automatic_base_width=False, manual_base_width_mm=manual_width, simulate_full_tower_infill=full,
            maximum_expansion_angle_deg=45, maximum_contraction_angle_deg=angle)
        return build_solid_tower_profile(source, settings, object_height_mm=object_height)

    def test_full_infill_curve_ends_five_layers_above_six_mm_minimum(self):
        heights = [0.2 * i for i in range(1, 101)]
        profile = self.make_profile(heights)
        normal = self.make_profile(heights, full=False, angle=80)
        self.assertAlmostEqual(profile.effective_base_height_mm, 0.2)
        self.assertEqual(profile.layers[0].outer_radius_mm, 10)
        self.assertLess(profile.layers[1].outer_radius_mm, 10)
        self.assertGreater(normal.layers[29].outer_radius_mm, 2)
        self.assertAlmostEqual(normal.layers[30].outer_radius_mm, 2)
        self.assertGreater(profile.layers[34].outer_radius_mm, 2)
        self.assertAlmostEqual(profile.layers[35].outer_radius_mm, 2)
        slopes = [(b.outer_radius_mm-a.outer_radius_mm)/(b.z_mm-a.z_mm)
                  for a,b in zip(profile.points, profile.points[1:]) if a.z_mm >= 0.2]
        self.assertTrue(all(b >= a - 1e-8 for a,b in zip(slopes, slopes[1:])))

    def test_object_height_can_extend_curve_beyond_six_mm(self):
        profile = self.make_profile([0.3 * i for i in range(1, 101)], object_height=1000)
        self.assertGreater(profile.layers[88].outer_radius_mm, 2)
        self.assertAlmostEqual(profile.layers[89].outer_radius_mm, 2)
        self.assertAlmostEqual(profile.layers[89].z-profile.effective_base_height_mm, 26.7)

    def test_six_mm_or_twenty_two_layers_with_variable_heights(self):
        profile = self.make_profile([0.1 * i for i in range(1, 101)])
        self.assertGreater(profile.layers[64].outer_radius_mm, 2)
        self.assertAlmostEqual(profile.layers[65].outer_radius_mm, 2)
        thick = self.make_profile([0.4 * i for i in range(1, 101)])
        self.assertGreater(thick.layers[26].outer_radius_mm, 2)
        self.assertAlmostEqual(thick.layers[27].outer_radius_mm, 2)
        variable = self.make_profile([0.3, 0.5] + [0.5 + i * 0.15 for i in range(1, 61)], object_height=40)
        self.assertEqual(variable.effective_base_height_mm, 0.3)
        self.assertGreater(variable.layers[44].outer_radius_mm, 2)
        self.assertAlmostEqual(variable.layers[45].outer_radius_mm, 2)

    def test_short_tower_and_angle_policy(self):
        short = self.make_profile([0.2, 0.4, 0.6, 0.8])
        self.assertEqual(short.total_height_mm, 0.8)
        self.assertAlmostEqual(short.layers[-1].outer_radius_mm, 2)
        heights = [0.2 * i for i in range(1, 801)]
        low = self.make_profile(heights, angle=5)
        high = self.make_profile(heights, angle=80)
        self.assertEqual(low.points, high.points)
        ignored = self.make_profile(heights, angle=0)
        self.assertEqual(low.points, ignored.points)
        limited = self.make_profile(heights, full=False, angle=10)
        for a,b in zip(limited.points, limited.points[1:]):
            self.assertGreater(b.z_mm, a.z_mm)
            self.assertGreaterEqual((b.outer_radius_mm-a.outer_radius_mm)/(b.z_mm-a.z_mm), -math.tan(math.radians(10))-1e-8)

    def test_no_early_taper_before_self_sufficient_surface_and_closed_mesh(self):
        heights = [0.2 * i for i in range(1, 121)]
        radii = [10.0]*40 + [10.0-i*0.05 for i in range(1,21)] + [2.0]*40 + [8.0]*20
        profile = self.make_profile(heights, radii, sufficient=range(60,100))
        for layer in profile.layers[39:60]:
            self.assertAlmostEqual(layer.outer_radius_mm, 10)
        steps = [p for p in profile.points if p.source == 'inward_step']
        self.assertTrue(steps)
        self.assertAlmostEqual(steps[0].z_mm, heights[59])
        self.assertAlmostEqual(steps[0].outer_radius_mm, 2)
        self.assertGreaterEqual(profile.layers[100].outer_radius_mm, 8-1e-8)
        validation = validate_triangle_mesh(generate_solid_tower_mesh(profile,TowerMeshConfig(segment_count=24)))
        self.assertTrue(validation.is_watertight)
        self.assertTrue(validation.has_outward_orientation)

    def test_wide_normal_foot_has_two_equal_tiers_then_closed_curved_mesh(self):
        profile = self.make_profile(
            [0.2 * i for i in range(1, 201)],
            full=False, angle=55, manual_width=50,
        )
        self.assertAlmostEqual(profile.effective_base_height_mm, 0.2)
        self.assertAlmostEqual(profile.layers[0].outer_radius_mm, 25)
        self.assertAlmostEqual(profile.layers[1].outer_radius_mm, 20)
        steps = [point for point in profile.points
                 if point.source == "base_tier_step"]
        self.assertEqual([(point.z_mm, point.outer_radius_mm)
                          for point in steps], [(0.2, 20.0), (0.4, 15.0)])
        self.assertLess(profile.layers[2].outer_radius_mm, 15.0)
        self.assertTrue(all(point.source != "inward_step" for point in profile.points))
        validation = validate_triangle_mesh(generate_solid_tower_mesh(
            profile, TowerMeshConfig(segment_count=24),
        ))
        self.assertTrue(validation.is_watertight)
        self.assertTrue(validation.has_outward_orientation)

    def test_normal_foot_at_30_mm_keeps_one_layer_before_curve(self):
        profile = self.make_profile(
            [0.2 * i for i in range(1, 101)],
            full=False, angle=55, manual_width=30,
        )
        self.assertFalse(any(point.source == "base_tier_step"
                             for point in profile.points))
        self.assertAlmostEqual(profile.layers[0].outer_radius_mm, 15.0)
        self.assertLess(profile.layers[1].outer_radius_mm, 15.0)


if __name__ == '__main__':
    unittest.main()
