from __future__ import annotations

import csv
import math
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cooling_tower.cli import build_argument_parser
from cooling_tower.models import GenerationSettings
from cooling_tower.paths import RunPaths
from cooling_tower.services.output_service import OutputService
from cooling_tower.tower.base_calculator import (
    calculate_phase10_base_outer_radius,
)
from cooling_tower.tower.hollow_profile import (
    ProfileFeasibilityError,
    build_hollow_tower_profile,
)
from cooling_tower.tower.mesh_generator import (
    TowerMeshConfig,
    generate_hollow_tower_mesh,
    validate_triangle_mesh,
)
from cooling_tower.tower.profile import (
    LayerRadiusRecord,
    TowerProfileConfig,
    TowerRadiusProfile,
)
from cooling_tower.tower.spline_profile import (
    SMOOTHSTEP_MAX_DERIVATIVE,
    adaptive_quintic_segment_samples,
    angle_to_radial_slope,
    build_asymmetric_spline_envelope,
    maximum_quintic_segment_slope,
    quintic_smoothstep,
    quintic_smoothstep_derivative,
    slope_to_angle_deg,
)
from cooling_tower.tower.wall_calculator import calculate_wall_path_length


def settings(**changes: object) -> GenerationSettings:
    configured = GenerationSettings(
        target_layer_time_s=10.0,
        minimum_outer_radius_mm=5.0,
        maximum_outer_radius_mm=10.0,
        minimum_wall_thickness_mm=0.8,
        maximum_wall_thickness_mm=4.2,
        wall_path_width_mm=0.42,
        minimum_inner_radius_mm=2.0,
        base_height_mm=1.0,
        automatic_base_width=False,
        manual_base_width_mm=20.0,
        maximum_expansion_angle_deg=50.0,
        maximum_contraction_angle_deg=50.0,
        maximum_wall_change_per_mm_z=100.0,
        local_reference_window=3,
    )
    return replace(configured, **changes)


def phase2_profile(
    requirements: tuple[float, ...],
    z_positions: tuple[float, ...],
) -> TowerRadiusProfile:
    layers: list[LayerRadiusRecord] = []
    for position, (required, z_mm) in enumerate(
        zip(requirements, z_positions, strict=True)
    ):
        height = z_mm if position == 0 else z_mm - z_positions[position - 1]
        layers.append(
            LayerRadiusRecord(
                layer_index=position + 1,
                z_mm=z_mm,
                height_mm=height,
                layer_time_s=max(0.0, 10.0 - required * 0.01),
                target_layer_time_s=10.0,
                time_deficit_s=required * 0.01,
                seconds_per_deposition_mm=0.01,
                time_factor_source="local",
                reference_start_layer=1,
                reference_end_layer=len(requirements),
                additional_path_mm=required,
                safety_adjusted_path_mm=required,
                calculated_radius_mm=required / math.tau,
                radius_mm=max(5.0, min(10.0, required / math.tau)),
                radius_limit="none",
                estimated_added_time_s=required * 0.01,
                estimated_combined_layer_time_s=10.0,
            )
        )
    return TowerRadiusProfile(
        config=TowerProfileConfig(
            target_layer_time_s=10.0,
            minimum_radius_mm=5.0,
            maximum_radius_mm=10.0,
        ),
        global_seconds_per_deposition_mm=0.01,
        layers=tuple(layers),
    )


class SplineMathematicsTests(unittest.TestCase):
    def test_01_quintic_end_values(self) -> None:
        self.assertEqual(quintic_smoothstep(0.0), 0.0)
        self.assertEqual(quintic_smoothstep(1.0), 1.0)

    def test_02_quintic_end_derivatives_are_zero(self) -> None:
        self.assertEqual(quintic_smoothstep_derivative(0.0), 0.0)
        self.assertEqual(quintic_smoothstep_derivative(1.0), 0.0)

    def test_03_quintic_maximum_derivative_factor(self) -> None:
        self.assertAlmostEqual(
            quintic_smoothstep_derivative(0.5),
            SMOOTHSTEP_MAX_DERIVATIVE,
        )

    def test_04_quintic_is_monotone_and_does_not_overshoot(self) -> None:
        values = [quintic_smoothstep(index / 100) for index in range(101)]
        self.assertTrue(all(0.0 <= value <= 1.0 for value in values))
        self.assertTrue(all(a <= b for a, b in zip(values, values[1:])))

    def test_05_angle_slope_roundtrip(self) -> None:
        self.assertAlmostEqual(
            slope_to_angle_deg(angle_to_radial_slope(50.0)), 50.0
        )

    def test_06_segment_slope_uses_quintic_factor(self) -> None:
        self.assertAlmostEqual(
            maximum_quintic_segment_slope(5.0, 9.0, 10.0),
            1.875 * 4.0 / 10.0,
        )

    def test_07_asymmetric_envelope_obeys_expansion_limit(self) -> None:
        result = build_asymmetric_spline_envelope(
            (0.0, 2.0, 4.0),
            (5.0, 5.0, 9.0),
            maximum_increase_per_mm_z=1.875,
            maximum_decrease_per_mm_z=10.0,
        )
        for start, end in zip(result.values, result.values[1:]):
            if end > start:
                self.assertLessEqual(1.875 * (end - start) / 2.0, 1.875)

    def test_08_asymmetric_envelope_obeys_contraction_limit(self) -> None:
        result = build_asymmetric_spline_envelope(
            (0.0, 2.0, 4.0),
            (9.0, 5.0, 5.0),
            maximum_increase_per_mm_z=10.0,
            maximum_decrease_per_mm_z=1.875,
        )
        for start, end in zip(result.values, result.values[1:]):
            if start > end:
                self.assertLessEqual(1.875 * (start - end) / 2.0, 1.875)

    def test_09_envelope_never_reduces_a_requirement(self) -> None:
        required = (5.0, 9.0, 5.0, 8.0, 5.0)
        result = build_asymmetric_spline_envelope(
            (0.0, 1.0, 2.0, 3.0, 4.0),
            required,
            maximum_increase_per_mm_z=2.0,
            maximum_decrease_per_mm_z=2.0,
        )
        self.assertTrue(all(a >= b for a, b in zip(result.values, required)))

    def test_10_close_expansions_merge_without_a_narrow_notch(self) -> None:
        result = build_asymmetric_spline_envelope(
            (0.0, 1.0, 2.0, 3.0, 4.0),
            (5.0, 9.0, 5.0, 9.0, 5.0),
            maximum_increase_per_mm_z=2.0,
            maximum_decrease_per_mm_z=2.0,
        )
        self.assertGreater(result.values[2], 5.0)

    def test_11_distant_expansions_can_return_to_minimum(self) -> None:
        result = build_asymmetric_spline_envelope(
            (0.0, 5.0, 15.0, 25.0, 30.0),
            (5.0, 9.0, 5.0, 9.0, 5.0),
            maximum_increase_per_mm_z=2.0,
            maximum_decrease_per_mm_z=2.0,
        )
        self.assertAlmostEqual(result.values[2], 5.0)

    def test_12_fixed_start_reports_unreachable_requirement(self) -> None:
        result = build_asymmetric_spline_envelope(
            (0.0, 1.0),
            (5.0, 20.0),
            maximum_increase_per_mm_z=1.0,
            maximum_decrease_per_mm_z=1.0,
            fixed_start_value=5.0,
        )
        self.assertEqual(result.unreachable_positions, (1,))

    def test_13_adaptive_sampling_inserts_intermediate_rings(self) -> None:
        samples = adaptive_quintic_segment_samples(
            start_z_mm=0.0,
            end_z_mm=10.0,
            start_outer_radius_mm=5.0,
            end_outer_radius_mm=20.0,
            start_wall_thickness_mm=0.84,
            end_wall_thickness_mm=2.1,
        )
        self.assertGreater(len(samples), 10)
        self.assertAlmostEqual(samples[-1].outer_radius_mm, 20.0)

    def test_14_outer_and_inner_profiles_share_sample_heights(self) -> None:
        samples = adaptive_quintic_segment_samples(
            start_z_mm=0.0,
            end_z_mm=3.0,
            start_outer_radius_mm=5.0,
            end_outer_radius_mm=9.0,
            start_wall_thickness_mm=0.84,
            end_wall_thickness_mm=1.68,
        )
        self.assertTrue(
            all(sample.outer_radius_mm > sample.wall_thickness_mm for sample in samples)
        )


class Phase10ProfileTests(unittest.TestCase):
    def test_15_default_minimum_outer_radius_is_two_and_a_half_mm(self) -> None:
        self.assertEqual(GenerationSettings().minimum_outer_radius_mm, 2.5)
        self.assertEqual(GenerationSettings().base_height_mm, 1.0)

    def test_16_automatic_base_width_has_twenty_five_mm_minimum(self) -> None:
        radius = calculate_phase10_base_outer_radius(
            object_height_mm=10.0,
            automatic_base_width=True,
            manual_base_width_mm=20.0,
        )
        self.assertEqual(radius * 2.0, 25.0)

    def test_17_automatic_base_width_uses_0_21_times_object_height(self) -> None:
        radius = calculate_phase10_base_outer_radius(
            object_height_mm=200.0,
            automatic_base_width=True,
            manual_base_width_mm=20.0,
        )
        self.assertEqual(radius * 2.0, 42.0)

    def test_18_manual_base_width_is_used_as_outer_diameter(self) -> None:
        radius = calculate_phase10_base_outer_radius(
            object_height_mm=100.0,
            automatic_base_width=False,
            manual_base_width_mm=36.0,
        )
        self.assertEqual(radius, 18.0)

    def test_19_manual_base_width_below_twenty_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            calculate_phase10_base_outer_radius(
                object_height_mm=20.0,
                automatic_base_width=False,
                manual_base_width_mm=19.9,
            )

    def test_manual_base_width_accepts_80_but_rejects_more(self) -> None:
        radius = calculate_phase10_base_outer_radius(
            object_height_mm=20.0,
            automatic_base_width=False,
            manual_base_width_mm=80.0,
        )
        self.assertEqual(radius * 2.0, 80.0)
        with self.assertRaises(ValueError):
            calculate_phase10_base_outer_radius(
                object_height_mm=20.0,
                automatic_base_width=False,
                manual_base_width_mm=80.1,
            )

    def test_automatic_base_width_is_capped_at_80(self) -> None:
        radius = calculate_phase10_base_outer_radius(
            object_height_mm=1000.0,
            automatic_base_width=True,
            manual_base_width_mm=20.0,
        )
        self.assertEqual(radius * 2.0, 80.0)

    def test_20_base_may_exceed_regular_maximum_radius(self) -> None:
        configured = settings(
            automatic_base_width=True,
            maximum_outer_radius_mm=12.0,
        )
        profile = build_hollow_tower_profile(
            phase2_profile((0.0,), (100.0,)),
            configured,
            object_height_mm=300.0,
        )
        self.assertEqual(profile.base_outer_radius_mm, 31.5)
        self.assertGreater(
            profile.base_outer_radius_mm,
            configured.maximum_outer_radius_mm,
        )

    def test_20a_short_tower_still_uses_complete_object_height_for_base(self) -> None:
        profile = build_hollow_tower_profile(
            phase2_profile((0.0, 0.0), (0.2, 0.4)),
            settings(automatic_base_width=True),
            tower_end_z_mm=0.4,
            object_height_mm=200.0,
        )
        self.assertEqual(profile.total_height_mm, 0.4)
        self.assertEqual(profile.base_outer_radius_mm * 2.0, 42.0)

    def test_21_outer_and_inner_radius_move_by_same_amount(self) -> None:
        required = calculate_wall_path_length(8.0, 2, 0.42)
        profile = build_hollow_tower_profile(
            phase2_profile((0.0, required), (20.0, 40.0)), settings()
        )
        first, second = profile.layers
        self.assertAlmostEqual(
            second.outer_radius_mm - first.outer_radius_mm,
            second.inner_radius_mm - first.inner_radius_mm,
        )

    def test_22_wall_stays_minimum_before_maximum_radius(self) -> None:
        required = calculate_wall_path_length(8.0, 2, 0.42)
        layer = build_hollow_tower_profile(
            phase2_profile((required,), (20.0,)), settings()
        ).layers[0]
        self.assertAlmostEqual(layer.outer_radius_mm, 8.0)
        self.assertAlmostEqual(layer.wall_thickness_mm, 0.84)

    def test_23_wall_grows_only_at_maximum_radius(self) -> None:
        required = calculate_wall_path_length(10.0, 4, 0.42) - 0.001
        layer = build_hollow_tower_profile(
            phase2_profile((required,), (20.0,)), settings()
        ).layers[0]
        self.assertAlmostEqual(layer.outer_radius_mm, 10.0)
        self.assertEqual(layer.wall_path_count, 4)

    def test_24_decreasing_demand_reduces_wall_before_radius(self) -> None:
        requirements = (
            calculate_wall_path_length(10.0, 4, 0.42) - 0.001,
            calculate_wall_path_length(10.0, 3, 0.42) - 0.001,
            0.0,
            0.0,
        )
        layers = build_hollow_tower_profile(
            phase2_profile(requirements, (20.0, 30.0, 40.0, 50.0)), settings()
        ).layers
        self.assertEqual([layer.wall_path_count for layer in layers[:2]], [4, 3])
        self.assertTrue(all(layer.outer_radius_mm == 10.0 for layer in layers[:3]))
        self.assertAlmostEqual(layers[2].wall_thickness_mm, 0.84)
        self.assertAlmostEqual(layers[3].outer_radius_mm, 5.0)

    def test_25_wall_geometry_has_continuous_fractional_intermediate_values(self) -> None:
        required = calculate_wall_path_length(10.0, 5, 0.42) - 0.001
        profile = build_hollow_tower_profile(
            phase2_profile((0.0, required), (20.0, 30.0)),
            settings(maximum_wall_change_per_mm_z=1.0),
        )
        intermediate = [
            point.wall_thickness_mm / 0.42
            for point in profile.points
            if point.source == "spline_transition"
        ]
        self.assertTrue(any(abs(value - round(value)) > 1e-5 for value in intermediate))

    def test_26_all_adaptive_points_preserve_inner_radius(self) -> None:
        required = calculate_wall_path_length(10.0, 7, 0.42) - 0.001
        profile = build_hollow_tower_profile(
            phase2_profile((0.0, required, 0.0), (10.0, 20.0, 30.0)),
            settings(),
        )
        self.assertTrue(
            all(point.inner_radius_mm >= 2.0 - 1e-9 for point in profile.points)
        )

    def test_26a_all_mesh_rings_prioritize_outer_radius_before_wall(self) -> None:
        required = calculate_wall_path_length(10.0, 5, 0.42) - 0.001
        profile = build_hollow_tower_profile(
            phase2_profile((0.0, required, 0.0), (10.0, 20.0, 30.0)),
            settings(maximum_wall_change_per_mm_z=1.0),
        )
        minimum_wall = profile.wall_bounds.effective_minimum_thickness_mm
        regular_points = (
            point
            for point in profile.points
            if point.z_mm > profile.effective_base_height_mm + 1e-9
        )
        for point in regular_points:
            if point.outer_radius_mm < 10.0 - 1e-9:
                self.assertAlmostEqual(
                    point.wall_thickness_mm,
                    minimum_wall,
                    places=9,
                )

    def test_26b_both_contours_move_together_at_minimum_wall(self) -> None:
        required = calculate_wall_path_length(8.0, 2, 0.42)
        profile = build_hollow_tower_profile(
            phase2_profile((0.0, required, 0.0), (10.0, 20.0, 30.0)),
            settings(maximum_wall_change_per_mm_z=1.0),
        )
        for previous, current in zip(profile.points, profile.points[1:]):
            if (
                abs(previous.wall_thickness_mm - 0.84) <= 1e-9
                and abs(current.wall_thickness_mm - 0.84) <= 1e-9
            ):
                self.assertAlmostEqual(
                    current.outer_radius_mm - previous.outer_radius_mm,
                    current.inner_radius_mm - previous.inner_radius_mm,
                    places=9,
                )

    def test_27_base_layer_time_is_compensated_with_wall_not_width(self) -> None:
        required = calculate_wall_path_length(10.0, 4, 0.42) - 0.001
        profile = build_hollow_tower_profile(
            phase2_profile((required,), (2.0,)),
            settings(base_height_mm=4.0),
        )
        layer = profile.layers[0]
        self.assertAlmostEqual(layer.outer_radius_mm, 10.0)
        self.assertEqual(layer.wall_path_count, 4)

    def test_28_too_shallow_expansion_creates_structured_issue(self) -> None:
        required = calculate_wall_path_length(30.0, 2, 0.42)
        profile = build_hollow_tower_profile(
            phase2_profile((0.0, required), (2.0, 5.0)),
            settings(
                maximum_outer_radius_mm=40.0,
                base_height_mm=4.0,
                maximum_expansion_angle_deg=20.0,
            ),
        )
        codes = {issue.code for issue in profile.feasibility_issues}
        self.assertIn("EXPANSION_ANGLE_TOO_SMALL", codes)
        self.assertFalse(profile.layers[-1].target_reached)

    def test_29_manual_base_transition_reports_base_width_issue(self) -> None:
        required = calculate_wall_path_length(30.0, 2, 0.42)
        profile = build_hollow_tower_profile(
            phase2_profile((0.0, required), (2.0, 5.0)),
            settings(
                maximum_outer_radius_mm=40.0,
                base_height_mm=4.0,
                maximum_expansion_angle_deg=20.0,
            ),
        )
        self.assertIn(
            "BASE_WIDTH_TOO_SMALL",
            {issue.code for issue in profile.feasibility_issues},
        )

    def test_30_capacity_limits_are_structured(self) -> None:
        profile = build_hollow_tower_profile(
            phase2_profile((10000.0,), (20.0,)), settings()
        )
        codes = {issue.code for issue in profile.feasibility_issues}
        self.assertIn("MAXIMUM_OUTER_RADIUS_REACHED", codes)
        self.assertIn("MAXIMUM_WALL_THICKNESS_REACHED", codes)

    def test_31_base_that_cannot_contain_hollow_core_is_rejected_structurally(self) -> None:
        with self.assertRaises(ProfileFeasibilityError) as context:
            build_hollow_tower_profile(
                phase2_profile((0.0,), (20.0,)),
                settings(
                    maximum_outer_radius_mm=15.0,
                    minimum_inner_radius_mm=9.5,
                ),
            )
        self.assertEqual(context.exception.issues[0].code, "BASE_WIDTH_TOO_SMALL")


class Phase10OutputAndMeshTests(unittest.TestCase):
    def setUp(self) -> None:
        required = calculate_wall_path_length(10.0, 4, 0.42) - 0.001
        self.profile = build_hollow_tower_profile(
            phase2_profile((0.0, required, 0.0), (20.0, 30.0, 40.0)),
            settings(),
            tower_end_z_mm=41.0,
        )

    def test_32_profile_does_not_extend_above_last_object_layer(self) -> None:
        self.assertAlmostEqual(self.profile.points[-1].z_mm, 40.0)
        self.assertNotEqual(self.profile.points[-1].profile_region, "final_cap")

    def test_33_adaptive_mesh_is_hollow_and_watertight(self) -> None:
        mesh = generate_hollow_tower_mesh(
            self.profile, TowerMeshConfig(segment_count=24)
        )
        self.assertTrue(validate_triangle_mesh(mesh).is_watertight)

    def test_34_adaptive_mesh_has_no_degenerate_triangles(self) -> None:
        mesh = generate_hollow_tower_mesh(
            self.profile, TowerMeshConfig(segment_count=24)
        )
        self.assertEqual(validate_triangle_mesh(mesh).degenerate_face_count, 0)

    def test_35_profile_csv_contains_phase10_diagnostic_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            paths = RunPaths.for_directory(temporary_directory)
            paths.profiles_directory.mkdir(exist_ok=True)
            OutputService().write_tower_profile(paths, self.profile.layers)
            with paths.profile_path.open(encoding="utf-8-sig", newline="") as handle:
                fields = csv.DictReader(handle, delimiter=";").fieldnames or []
        for field in (
            "layer_time_s",
            "time_deficit_s",
            "outer_diameter_raw_mm",
            "outer_diameter_spline_mm",
            "expansion_angle_deg",
            "contraction_angle_deg",
            "estimated_added_time_s",
            "profile_region",
        ):
            self.assertIn(field, fields)

    def test_36_cli_exposes_manual_base_and_both_angles(self) -> None:
        arguments = build_argument_parser().parse_args(
            [
                "--gcode",
                "input.gcode",
                "--manual-base-width",
                "34",
                "--expansion-angle",
                "42",
                "--contraction-angle",
                "57",
            ]
        )
        self.assertEqual(arguments.manual_base_width, 34.0)
        self.assertEqual(arguments.expansion_angle, 42.0)
        self.assertEqual(arguments.contraction_angle, 57.0)

    @unittest.skipUnless(os.environ.get("QT_QPA_PLATFORM") == "offscreen", "Qt offscreen run")
    def test_37_gui_exposes_base_mode_and_angle_controls(self) -> None:
        from PySide6.QtWidgets import QApplication
        from cooling_tower.gui.main_window import MainWindow

        application = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            window = MainWindow(
                user_settings_path=root / "user.json",
                default_settings_path=PROJECT_ROOT / "config" / "default_settings.json",
            )
            self.assertTrue(window.automatic_base_checkbox.isChecked())
            self.assertFalse(window.manual_base_width_spin.isEnabled())
            self.assertEqual(window.maximum_expansion_angle_spin.value(), 40.0)
            self.assertEqual(window.maximum_contraction_angle_spin.value(), 35.0)
            window.close()
        application.processEvents()


if __name__ == "__main__":
    unittest.main()
