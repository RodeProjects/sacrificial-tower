from __future__ import annotations

import csv
import math
import random
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cooling_tower.models import GenerationSettings
from cooling_tower.paths import RunPaths
from cooling_tower.services.output_service import OutputService
from cooling_tower.tower.hollow_profile import (
    build_hollow_tower_profile,
    validate_hollow_settings,
)
from cooling_tower.tower.mesh_generator import (
    TowerMeshConfig,
    calculate_face_normal,
    generate_hollow_tower_mesh,
    validate_triangle_mesh,
)
from cooling_tower.tower.profile import (
    LayerRadiusRecord,
    TowerProfileConfig,
    TowerRadiusProfile,
)
from cooling_tower.tower.wall_calculator import (
    calculate_required_outer_radius,
    calculate_wall_path_bounds,
    calculate_wall_path_length,
)


def settings(**changes: object) -> GenerationSettings:
    base = GenerationSettings(
        target_layer_time_s=10.0,
        minimum_outer_radius_mm=5.0,
        maximum_outer_radius_mm=10.0,
        minimum_wall_thickness_mm=0.8,
        maximum_wall_thickness_mm=4.2,
        wall_path_width_mm=0.42,
        minimum_inner_radius_mm=2.0,
        minimum_base_radius_mm=5.0,
        automatic_base_width=False,
        manual_base_width_mm=20.0,
        base_height_mm=0.0,
        base_margin_mm=0.0,
        base_height_factor=0.0,
        minimum_radius_height_factor=0.0,
        maximum_radius_change_per_mm_z=100.0,
        maximum_wall_change_per_mm_z=100.0,
        local_reference_window=3,
    )
    return replace(base, **changes)


def phase2_profile(
    required_paths: tuple[float, ...],
    z_positions: tuple[float, ...] | None = None,
) -> TowerRadiusProfile:
    if z_positions is None:
        z_positions = tuple(
            0.2 * index for index in range(1, len(required_paths) + 1)
        )
    layers = []
    for index, (required, z) in enumerate(
        zip(required_paths, z_positions, strict=True), start=1
    ):
        layers.append(
            LayerRadiusRecord(
                layer_index=index,
                z_mm=z,
                height_mm=z if index == 1 else z - z_positions[index - 2],
                layer_time_s=10.0,
                target_layer_time_s=10.0,
                time_deficit_s=required * 0.1,
                seconds_per_deposition_mm=0.1,
                time_factor_source="local",
                reference_start_layer=1,
                reference_end_layer=len(required_paths),
                additional_path_mm=required,
                safety_adjusted_path_mm=required,
                calculated_radius_mm=required / math.tau,
                radius_mm=required / math.tau,
                radius_limit="none",
                estimated_added_time_s=required * 0.1,
                estimated_combined_layer_time_s=10.0 + required * 0.1,
            )
        )
    return TowerRadiusProfile(
        config=TowerProfileConfig(target_layer_time_s=10.0),
        global_seconds_per_deposition_mm=0.1,
        layers=tuple(layers),
    )


class WallPathCalculationTests(unittest.TestCase):
    def test_minimum_wall_is_rounded_up_to_complete_paths(self) -> None:
        bounds = calculate_wall_path_bounds(0.8, 4.2, 0.42)
        self.assertEqual(bounds.minimum_path_count, 2)
        self.assertEqual(bounds.maximum_path_count, 10)
        self.assertAlmostEqual(bounds.effective_minimum_thickness_mm, 0.84)

    def test_concentric_path_length_uses_smaller_inner_circumferences(self) -> None:
        length = calculate_wall_path_length(10.0, 3, 0.42)
        expected = math.tau * (9.79 + 9.37 + 8.95)
        self.assertAlmostEqual(length, expected)
        self.assertLess(length, 3 * math.tau * 10.0)

    def test_radius_equation_roundtrips_required_path(self) -> None:
        required = 87.5
        radius = calculate_required_outer_radius(required, 2, 0.42)
        self.assertAlmostEqual(
            calculate_wall_path_length(radius, 2, 0.42), required
        )

    def test_invalid_wall_bounds_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            calculate_wall_path_bounds(1.0, 0.8, 0.42)
        with self.assertRaises(ValueError):
            calculate_wall_path_bounds(0.8, 1.0, 0.0)


class HollowProfileTests(unittest.TestCase):
    def test_no_time_requirement_uses_minimum_radius_and_wall(self) -> None:
        profile = build_hollow_tower_profile(
            phase2_profile((0.0,), (10.0,)), settings()
        )
        layer = profile.layers[0]
        self.assertAlmostEqual(layer.outer_radius_mm, 5.0)
        self.assertEqual(layer.wall_path_count, 2)
        self.assertAlmostEqual(layer.wall_thickness_mm, 0.84)
        self.assertTrue(layer.target_reached)

    def test_only_outer_radius_grows_before_wall(self) -> None:
        required = calculate_wall_path_length(8.0, 2, 0.42)
        layer = build_hollow_tower_profile(
            phase2_profile((required,), (10.0,)), settings()
        ).layers[0]
        self.assertAlmostEqual(layer.outer_radius_mm, 8.0)
        self.assertEqual(layer.wall_path_count, 2)

    def test_maximum_radius_is_reached_exactly(self) -> None:
        required = calculate_wall_path_length(10.0, 2, 0.42)
        layer = build_hollow_tower_profile(
            phase2_profile((required,)), settings()
        ).layers[0]
        self.assertAlmostEqual(layer.outer_radius_mm, 10.0)
        self.assertEqual(layer.wall_path_count, 2)

    def test_wall_grows_after_maximum_radius(self) -> None:
        required = calculate_wall_path_length(10.0, 3, 0.42) - 0.01
        layer = build_hollow_tower_profile(
            phase2_profile((required,)), settings()
        ).layers[0]
        self.assertAlmostEqual(layer.outer_radius_mm, 10.0)
        self.assertEqual(layer.wall_path_count, 3)
        self.assertAlmostEqual(layer.wall_thickness_mm, 1.26)

    def test_each_wall_step_is_exactly_one_path_width(self) -> None:
        requirements = tuple(
            calculate_wall_path_length(10.0, count, 0.42) - 0.01
            for count in (2, 3, 4)
        )
        profile = build_hollow_tower_profile(
            phase2_profile(requirements), settings()
        )
        thicknesses = [layer.wall_thickness_mm for layer in profile.layers]
        self.assertAlmostEqual(thicknesses[1] - thicknesses[0], 0.42)
        self.assertAlmostEqual(thicknesses[2] - thicknesses[1], 0.42)

    def test_maximum_wall_is_respected_and_unreachable_is_warned(self) -> None:
        profile = build_hollow_tower_profile(
            phase2_profile((10_000.0,)), settings()
        )
        layer = profile.layers[0]
        self.assertEqual(layer.wall_path_count, 10)
        self.assertFalse(layer.target_reached)
        self.assertTrue(any("maximaler Wandstärke" in warning for warning in profile.warnings))

    def test_minimum_inner_radius_limits_wall_paths(self) -> None:
        configured = settings(
            minimum_outer_radius_mm=9.5,
            minimum_inner_radius_mm=8.5,
        )
        profile = build_hollow_tower_profile(
            phase2_profile((10_000.0,)), configured
        )
        layer = profile.layers[0]
        self.assertGreaterEqual(layer.inner_radius_mm, 8.5)
        self.assertEqual(layer.wall_path_count, 3)
        self.assertTrue(any("Mindest-Innenradius" in warning for warning in profile.warnings))

    def test_variable_layer_heights_preserve_profile_invariants(self) -> None:
        z = (0.15, 0.35, 0.70, 1.20, 2.0)
        required = tuple(30.0 + index * 15.0 for index in range(len(z)))
        profile = build_hollow_tower_profile(
            phase2_profile(required, z),
            settings(maximum_radius_change_per_mm_z=2.0),
        )
        self.assertEqual(tuple(layer.z for layer in profile.layers), z)
        self.assertTrue(all(layer.inner_radius_mm > 0 for layer in profile.layers))

    def test_outer_radius_spike_is_bidirectionally_smoothed(self) -> None:
        z = (1.0, 2.0, 3.0, 4.0, 5.0)
        required = (
            calculate_wall_path_length(5.0, 2, 0.42),
            calculate_wall_path_length(5.0, 2, 0.42),
            calculate_wall_path_length(9.0, 2, 0.42),
            calculate_wall_path_length(5.0, 2, 0.42),
            calculate_wall_path_length(5.0, 2, 0.42),
        )
        profile = build_hollow_tower_profile(
            phase2_profile(required, z),
            settings(maximum_radius_change_per_mm_z=1.0, maximum_contraction_angle_deg=50.0),
        )
        radii = [layer.outer_radius_mm for layer in profile.layers]
        # Phase 10 limits the maximum derivative inside each quintic segment,
        # so anticipation is wider than the former piecewise-linear profile.
        self.assertEqual(
            [round(value, 6) for value in radii],
            [9.364398, 8.728796, 9.0, 8.364398, 7.728796],
        )

    def test_wall_spike_creates_gradual_intermediate_path_counts(self) -> None:
        z = tuple(float(index) for index in range(1, 10))
        low = calculate_wall_path_length(10.0, 2, 0.42) - 0.01
        high = calculate_wall_path_length(10.0, 6, 0.42) - 0.01
        profile = build_hollow_tower_profile(
            phase2_profile((low, low, low, low, high, low, low, low, low), z),
            settings(maximum_wall_change_per_mm_z=0.42),
        )
        counts = [layer.wall_path_count for layer in profile.layers]
        self.assertEqual(counts, [3, 4, 4, 5, 6, 5, 4, 4, 3])

    def test_base_remains_hollow_and_may_exceed_regular_maximum(self) -> None:
        profile = build_hollow_tower_profile(
            phase2_profile((0.0, 0.0), (1.0, 20.0)),
            settings(
                maximum_outer_radius_mm=8.0,
                base_height_mm=2.0,
            ),
        )
        self.assertAlmostEqual(profile.base_outer_radius_mm, 10.0)
        self.assertGreater(
            profile.base_outer_radius_mm,
            profile.settings.maximum_outer_radius_mm,
        )
        self.assertGreater(profile.points[0].inner_radius_mm, 0.0)

    def test_random_profiles_never_break_radius_wall_or_inner_limits(self) -> None:
        randomizer = random.Random(20260713)
        for _ in range(50):
            required = tuple(randomizer.uniform(0.0, 500.0) for _ in range(20))
            profile = build_hollow_tower_profile(
                phase2_profile(required), settings()
            )
            for layer in profile.layers:
                self.assertLessEqual(layer.outer_radius_mm, 10.0 + 1e-9)
                self.assertGreaterEqual(layer.inner_radius_mm, 2.0 - 1e-9)
                self.assertGreaterEqual(layer.wall_thickness_mm, 0.84 - 1e-9)
                self.assertLessEqual(layer.wall_thickness_mm, 4.2 + 1e-9)

    def test_infeasible_inner_radius_configuration_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_hollow_settings(
                settings(
                    maximum_outer_radius_mm=5.0,
                    minimum_inner_radius_mm=4.5,
                )
            )


class HollowMeshAndOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        required = (
            calculate_wall_path_length(8.0, 2, 0.42),
            calculate_wall_path_length(9.0, 3, 0.42),
        )
        self.profile = build_hollow_tower_profile(
            phase2_profile(required, (1.0, 3.0)), settings()
        )

    def test_hollow_mesh_is_watertight_volume_with_expected_counts(self) -> None:
        mesh = generate_hollow_tower_mesh(
            self.profile, TowerMeshConfig(segment_count=12)
        )
        validation = validate_triangle_mesh(mesh)
        self.assertTrue(validation.is_valid)
        self.assertEqual(
            len(mesh.vertices), len(self.profile.points) * 2 * 12
        )
        self.assertEqual(len(mesh.faces), len(self.profile.points) * 4 * 12)

    def test_inner_wall_normals_face_cavity_and_annuli_are_open(self) -> None:
        mesh = generate_hollow_tower_mesh(
            self.profile, TowerMeshConfig(segment_count=12)
        )
        inner_face = mesh.faces[2]
        vertices = [mesh.vertices[index] for index in inner_face]
        normal = calculate_face_normal(*vertices)
        center = tuple(sum(vertex[axis] for vertex in vertices) / 3 for axis in range(3))
        self.assertLess(normal[0] * center[0] + normal[1] * center[1], 0.0)
        self.assertFalse(any(abs(x) < 1e-12 and abs(y) < 1e-12 for x, y, z in mesh.vertices))

    def test_profile_csv_contains_solid_geometry_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            paths = RunPaths.for_directory(temporary_directory)
            paths.profiles_directory.mkdir(parents=True)
            OutputService(temporary_directory).write_tower_profile(
                paths, self.profile.layers
            )
            with paths.profile_path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter=";"))
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(float(row["outer_diameter_mm"]) > 0 for row in rows))
            self.assertNotIn("inner_radius_mm", rows[0])
            self.assertNotIn("wall_path_count", rows[0])


if __name__ == "__main__":
    unittest.main()
