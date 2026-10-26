from __future__ import annotations

import math
import random
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cooling_tower.models import GenerationSettings
from cooling_tower.services.tower_need_service import assess_tower_need, layers_for_tower
from cooling_tower.tower.diameter_transitions import Taper, plan_diameter_transitions
from cooling_tower.tower.mesh_generator import (
    TowerMeshConfig, generate_solid_tower_mesh, validate_triangle_mesh,
)
from cooling_tower.tower.profile import TowerRadiusProfile, TowerProfileConfig
from cooling_tower.tower.solid_profile import build_solid_tower_profile
from test_phase9 import make_snapshot
from test_solid_tower_changes import radius_layer


def profile_for(z, radii, *, full=True, end=None, base_height=0.0,
                source_times=None):
    settings = GenerationSettings(
        minimum_outer_diameter_mm=4.0, maximum_outer_diameter_mm=40.0,
        automatic_base_width=False, manual_base_width_mm=20.0,
        base_height_mm=base_height, maximum_expansion_angle_deg=45.0,
        maximum_contraction_angle_deg=45.0, simulate_full_tower_infill=full,
    )
    source_times = source_times or {}
    source = TowerRadiusProfile(
        config=TowerProfileConfig(target_layer_time_s=11.0), global_seconds_per_deposition_mm=0.1,
        layers=tuple(
            replace(
                radius_layer(index=i + 1, z=height, calculated_radius=r, radius=r),
                layer_time_s=source_times.get(i + 1, 1.0),
                time_deficit_s=max(0.0, 11.0 - source_times.get(i + 1, 1.0)),
            )
            for i, (height, r) in enumerate(zip(z, radii))
        ),
    )
    return build_solid_tower_profile(source, settings, tower_end_z_mm=end)


class GenerationRefinementTests(unittest.TestCase):
    def test_early_end_is_last_deficit_even_with_variable_layers(self):
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = make_snapshot(Path(temporary) / "input.gcode", (2, 20, 2, 20, 20),
                                     layer_heights=(0.2, 0.3, 0.1, 0.4, 0.2))
            assessment = assess_tower_need(snapshot, GenerationSettings())
            self.assertAlmostEqual(assessment.tower_end_z_mm, 0.6)
            self.assertEqual(assessment.tower_layer_count, 3)
            self.assertEqual(len(layers_for_tower(snapshot, assessment)), 3)
            self.assertFalse(assessment.synthetic_final_layer_used)

    def test_final_deficit_ends_at_object_height(self):
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = make_snapshot(Path(temporary) / "input.gcode", (2, 20, 2),
                                     layer_heights=(0.2, 0.3, 0.15))
            assessment = assess_tower_need(snapshot, GenerationSettings())
            self.assertAlmostEqual(assessment.tower_end_z_mm, 0.65)
            profile = profile_for((0.2, 0.5, 0.65), (8, 2, 8), end=assessment.tower_end_z_mm)
            self.assertEqual(profile.printable_layer_count, snapshot.layer_count)
            self.assertAlmostEqual(profile.points[-1].z_mm, 0.65)

    def test_requested_extension_does_not_add_a_layer_above_short_object(self):
        profile = profile_for((0.2,), (8,), base_height=1.0, end=0.4)
        self.assertEqual(profile.points[-1].outer_radius_mm, 10.0)
        self.assertEqual(profile.printable_layer_count, 1)
        self.assertEqual(profile.points[-1].z_mm, 0.2)

    def test_single_sufficient_top_layer_finishes_at_object_height(self):
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = make_snapshot(Path(temporary) / "input.gcode", (2, 2, 20),
                                     layer_heights=(0.2, 0.3, 0.15))
            assessment = assess_tower_need(snapshot, GenerationSettings())
            self.assertFalse(assessment.synthetic_final_layer_used)
            self.assertEqual(assessment.tower_layer_count, 3)
            self.assertEqual(assessment.tower_end_layer_position, 2)
            self.assertEqual(assessment.tower_end_layer_index, snapshot.layers[-1].index)
            self.assertAlmostEqual(assessment.tower_end_z_mm, 0.65)
            profile = profile_for((0.2, 0.5, 0.65), (8, 8, 2), end=assessment.tower_end_z_mm)
            self.assertEqual(profile.printable_layer_count, 3)

    def test_early_end_does_not_generate_a_final_minimum_trunk(self):
        profile = profile_for((1, 2), (8, 8), end=2)
        self.assertEqual(profile.printable_layer_count, 2)
        self.assertEqual(profile.points[-1].z_mm, 2)
        self.assertFalse(any(p.source == "synthetic_final_layer" for p in profile.points))

    def test_shoulder_reserves_smallest_radius_for_later_peak(self):
        profile = profile_for(tuple(range(1, 23)) + (23, 24, 28, 29),
                              (10,) * 22 + (2, 2, 8, 8), source_times={23: 11.0})
        step = next(p for p in profile.points if p.source == "inward_step")
        self.assertEqual(step.z_mm, 22)
        self.assertAlmostEqual(step.outer_radius_mm, 2)
        # Peak radius 8 at Z=28, maximum dr/dz=1: radius 2 at Z=22.
        self.assertAlmostEqual(step.outer_radius_mm + (28 - step.z_mm), 8)
        for layer in profile.layers:
            self.assertGreaterEqual(layer.outer_radius_mm + 1e-8, layer.raw_outer_radius_mm)
        points = [p for p in profile.points if 22 <= p.z_mm <= 28]
        points = points[1:]  # discard the lower trunk's outer shoulder ring
        for point in points:
            self.assertAlmostEqual(point.outer_radius_mm, point.z_mm - 20)

    def test_close_future_peak_prevents_overly_thin_restart(self):
        profile = profile_for(tuple(range(1, 23)) + (23, 24),
                              (10,) * 22 + (2, 9), source_times={23: 11.0})
        step = next(p for p in profile.points if p.source == "inward_step")
        self.assertAlmostEqual(step.outer_radius_mm, 7)
        self.assertAlmostEqual(profile.layers[-1].outer_radius_mm, 9)

    def test_without_full_infill_all_heights_increase_and_taper_is_concave(self):
        profile = profile_for(tuple(range(1, 22)), (2,) * 21, full=False)
        self.assertFalse(any(p.source == "inward_step" for p in profile.points))
        slopes = []
        for a, b in zip(profile.points, profile.points[1:]):
            self.assertGreater(b.z_mm, a.z_mm)
            if a.z_mm >= profile.effective_base_height_mm:
                slopes.append((b.outer_radius_mm - a.outer_radius_mm) / (b.z_mm - a.z_mm))
        self.assertGreaterEqual(min(slopes), -1.0 - 1e-8)
        self.assertTrue(all(b >= a - 1e-8 for a, b in zip(slopes, slopes[1:])))
        self.assertAlmostEqual(profile.points[-1].outer_radius_mm, 2)

    def test_full_infill_does_not_turn_gentle_taper_or_foot_into_steps(self):
        profile = profile_for(tuple(range(1, 18)), (2,) * 17)
        self.assertFalse(any(p.source == "inward_step" for p in profile.points))

    def test_foot_curves_follow_annotated_half_width_heights(self):
        # The blue outlines cross half of the foot's radial span at about
        # 6% (full infill) and 13% (normal infill) of the taper height.
        curves = []
        for full, half_height, eighty_height in (
            (True, 0.06, 0.28), (False, 0.13, 0.36),
        ):
            _, unreachable, segments = plan_diameter_transitions(
                (0.0, .01, .02, 5.0, 10.0), (10.0, 2.0, 2.0, 2.0, 2.0),
                base_index=0, base_radius=10.0, minimum_radius=2.0,
                expansion_slope=10.0, contraction_slope=100.0,
                allow_steps=full, base_taper_height=5.0,
            )
            self.assertFalse(unreachable)
            curve = segments[0].taper
            self.assertAlmostEqual(curve.radius(5 * half_height), 6.0, delta=0.3)
            self.assertAlmostEqual(curve.radius(5 * eighty_height), 3.6, delta=0.3)
            self.assertAlmostEqual(curve.radius(0.0), 10.0)
            self.assertAlmostEqual(curve.radius(5.0), 2.0)
            curves.append(curve)
        self.assertLess(curves[0].radius(5 * 0.13), curves[1].radius(5 * 0.13))

    def test_normal_foot_curve_respects_contraction_limit(self):
        _, unreachable, segments = plan_diameter_transitions(
            tuple(i * 0.2 for i in range(101)),
            (10.0,) + (2.0,) * 100,
            base_index=0, base_radius=10.0, minimum_radius=2.0,
            expansion_slope=10.0, contraction_slope=0.7,
            allow_steps=False, base_taper_height=5.0,
        )
        self.assertFalse(unreachable)
        for segment in segments:
            samples = [(segment.start_z, segment.radius(0.0)), *segment.samples(
                radial_error=0.005, maximum_z_step=0.05,
            )]
            for (z0, r0), (z1, r1) in zip(samples, samples[1:]):
                self.assertGreaterEqual((r1 - r0) / (z1 - z0), -0.7 - 1e-8)

    def test_foot_curve_prefers_exact_then_partial_then_angle_limited_shape(self):
        options = dict(
            start_z=0.0, start_radius=10.0, minimum_radius=2.0,
            duration=5.0, foot_curve_power=2.15,
            foot_start_fraction=0.02,
        )
        ideal = Taper(**options)
        feasible = Taper(**options, maximum_contraction_slope=20.0)
        partial = Taper(**options, maximum_contraction_slope=4.0)
        angle_only = Taper(**options, maximum_contraction_slope=1.6)

        for z in (0.0, 0.025, 0.1, 0.5, 2.5, 4.0, 5.0):
            self.assertAlmostEqual(feasible.radius(z), ideal.radius(z))
            self.assertAlmostEqual(angle_only.radius(z), 10.0 - 1.6 * z)
        self.assertAlmostEqual(partial.radius(0.5), 8.0)
        self.assertGreater(partial.radius(0.5), ideal.radius(0.5))
        self.assertAlmostEqual(partial.radius(4.0), ideal.radius(4.0))

    def test_normal_foot_curve_uses_angle_only_where_necessary(self):
        z = tuple(i * 0.25 for i in range(121))
        required = (15.0,) + (2.0,) * (len(z) - 1)
        _, unreachable, segments = plan_diameter_transitions(
            z, required, base_index=0, base_radius=15.0,
            minimum_radius=2.0, expansion_slope=10.0,
            contraction_slope=1.4, allow_steps=False,
            base_taper_height=5.0,
        )
        self.assertFalse(unreachable)
        taper = segments[0].taper
        self.assertIsNotNone(taper)
        ideal = replace(taper, maximum_contraction_slope=None)
        self.assertGreater(taper.radius(0.5), ideal.radius(0.5))
        self.assertAlmostEqual(taper.radius(0.5), 15.0 - 1.4 * 0.5)
        self.assertAlmostEqual(taper.radius(taper.duration * 0.8),
                               ideal.radius(taper.duration * 0.8))
        for segment in segments:
            samples = [(segment.start_z, segment.radius(0.0)), *segment.samples(
                radial_error=0.005, maximum_z_step=0.05,
            )]
            for (z0, r0), (z1, r1) in zip(samples, samples[1:]):
                self.assertGreaterEqual((r1 - r0) / (z1 - z0), -1.4 - 1e-8)

    def test_deficient_source_layer_never_receives_a_diameter_step(self):
        # The reproduced export stepped from 7.858 to 5.442 mm at Z=177.5,
        # although the next original layer needed only 1.047 of 11 seconds.
        z = tuple(range(1, 23)) + (22.18, 22.36, 22.54)
        profile = profile_for(
            z, (7.858,) * 22 + (5.442, 5.656, 4.756),
            source_times={22: 1.210, 23: 1.047, 24: 0.581},
        )
        self.assertFalse(any(p.source == "inward_step" for p in profile.points))
        self.assertGreaterEqual(
            profile.layers[22].outer_radius_mm,
            profile.layers[21].outer_radius_mm - 0.18 - 1e-8,
        )

    def test_shoulder_mesh_is_single_closed_outward_volume(self):
        profile = profile_for((1, 2, 3, 4, 8, 9), (10, 10, 2, 2, 8, 8),
                              end=9.2, source_times={5: 11.0})
        mesh = generate_solid_tower_mesh(profile, TowerMeshConfig(segment_count=32))
        validation = validate_triangle_mesh(mesh)
        self.assertTrue(validation.is_watertight)
        self.assertTrue(validation.has_consistent_winding)
        self.assertTrue(validation.has_outward_orientation)
        import trimesh
        actual = trimesh.Trimesh(vertices=mesh.vertices, faces=mesh.faces, process=False)
        adjacency = [set() for _ in mesh.vertices]
        for a, b, c in mesh.faces:
            adjacency[a].update((b, c))
            adjacency[b].update((a, c))
            adjacency[c].update((a, b))
        visited = set()
        pending = [0]
        while pending:
            current = pending.pop()
            if current not in visited:
                visited.add(current)
                pending.extend(adjacency[current] - visited)
        self.assertEqual(len(visited), len(mesh.vertices))
        self.assertTrue(actual.is_volume)
        self.assertTrue((actual.area_faces > 0).all())
        # At the same Z the annulus faces upward and the new trunk starts inside it.
        annuli = [i for i, t in enumerate(actual.triangles)
                  if max(t[:, 2]) == min(t[:, 2]) and 0 < t[0, 2] < 9.2]
        self.assertTrue(annuli)
        self.assertTrue(all(actual.face_normals[i, 2] > 0.99 for i in annuli))

    def test_irregular_demands_preserve_capacity_and_expansion_limits(self):
        rng = random.Random(24)
        for full in (False, True):
            for _ in range(20):
                z = [0.0]
                for _ in range(40):
                    z.append(z[-1] + rng.uniform(0.1, 1.0))
                required = [20.0] + [rng.uniform(2, 20) for _ in z[1:]]
                radii, unreachable, segments = plan_diameter_transitions(
                    tuple(z), tuple(required), base_index=0, base_radius=20,
                    minimum_radius=2, expansion_slope=1, contraction_slope=1,
                    allow_steps=full,
                )
                self.assertFalse(unreachable)
                for radius, wanted in zip(radii, required):
                    self.assertGreaterEqual(radius + 1e-8, wanted)
                for segment in segments:
                    self.assertAlmostEqual(segment.radius(1), segment.end_radius)
                    samples = [(segment.start_z, segment.radius(0)), *segment.samples(
                        radial_error=0.005, maximum_z_step=0.05)]
                    for a, b in zip(samples, samples[1:]):
                        slope = (b[1] - a[1]) / (b[0] - a[0])
                        self.assertLessEqual(slope, 1 + 1e-7)
                        self.assertGreaterEqual(slope, -1 - 1e-7)


if __name__ == "__main__":
    unittest.main()
