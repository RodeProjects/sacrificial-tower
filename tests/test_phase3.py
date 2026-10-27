from __future__ import annotations

import csv
import math
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tower_generator import (
    LayerRadiusRecord,
    ProfileCalculationError,
    StabilityProfileConfig,
    TowerProfileConfig,
    TowerRadiusProfile,
    build_stable_tower_profile,
)


def make_phase2_profile(
    z_positions: tuple[float, ...],
    radii: tuple[float, ...],
    *,
    minimum_radius_mm: float = 6.0,
) -> TowerRadiusProfile:
    if len(z_positions) != len(radii):
        raise ValueError("Z positions and radii must have equal length.")

    layers = tuple(
        LayerRadiusRecord(
            layer_index=index,
            z_mm=z_mm,
            height_mm=(
                z_mm
                if index == 1
                else z_mm - z_positions[index - 2]
            ),
            layer_time_s=10.0,
            target_layer_time_s=10.0,
            time_deficit_s=0.0,
            seconds_per_deposition_mm=0.05,
            time_factor_source="local",
            reference_start_layer=1,
            reference_end_layer=len(z_positions),
            additional_path_mm=0.0,
            safety_adjusted_path_mm=0.0,
            calculated_radius_mm=radius_mm,
            radius_mm=radius_mm,
            radius_limit="none",
            estimated_added_time_s=(
                math.tau * radius_mm * 0.05
            ),
            estimated_combined_layer_time_s=(
                10.0 + math.tau * radius_mm * 0.05
            ),
        )
        for index, (z_mm, radius_mm) in enumerate(
            zip(z_positions, radii, strict=True),
            start=1,
        )
    )

    return TowerRadiusProfile(
        config=TowerProfileConfig(
            target_layer_time_s=10.0,
            minimum_radius_mm=minimum_radius_mm,
        ),
        global_seconds_per_deposition_mm=0.05,
        layers=layers,
    )


class StableTowerProfileTests(unittest.TestCase):
    def test_height_adjusted_minimum_and_height_based_base(self) -> None:
        phase2 = make_phase2_profile(
            (0.2, 2.0, 10.0, 200.0),
            (6.0, 6.0, 6.0, 6.0),
        )
        config = StabilityProfileConfig(
            minimum_radius_height_factor=0.04,
            minimum_base_radius_mm=10.0,
            base_height_factor=0.05,
            base_margin_mm=2.0,
            base_height_mm=4.0,
            maximum_radius_change_per_mm_z=1.0,
        )

        profile = build_stable_tower_profile(phase2, config)

        self.assertEqual(profile.total_height_mm, 200.0)
        self.assertEqual(
            profile.height_adjusted_minimum_radius_mm,
            8.0,
        )
        self.assertEqual(
            profile.maximum_required_profile_radius_mm,
            8.0,
        )
        self.assertEqual(profile.height_based_base_radius_mm, 20.0)
        self.assertEqual(profile.profile_based_base_radius_mm, 10.0)
        self.assertEqual(profile.base_radius_mm, 20.0)
        self.assertEqual(profile.effective_base_height_mm, 4.0)

        self.assertTrue(profile.layers[0].base_radius_applied)
        self.assertTrue(profile.layers[1].base_radius_applied)
        self.assertEqual(
            profile.layers[0].required_radius_before_smoothing_mm,
            20.0,
        )
        self.assertEqual(
            profile.layers[-1].required_radius_before_smoothing_mm,
            8.0,
        )

    def test_profile_based_base_radius_wins(self) -> None:
        phase2 = make_phase2_profile(
            (1.0, 10.0, 20.0),
            (6.0, 30.0, 6.0),
        )
        config = StabilityProfileConfig(
            minimum_radius_height_factor=0.0,
            minimum_base_radius_mm=10.0,
            base_height_factor=0.05,
            base_margin_mm=2.0,
            base_height_mm=4.0,
            maximum_radius_change_per_mm_z=2.0,
        )

        profile = build_stable_tower_profile(phase2, config)

        self.assertEqual(profile.height_based_base_radius_mm, 11.0)
        self.assertEqual(profile.profile_based_base_radius_mm, 32.0)
        self.assertEqual(profile.base_radius_mm, 32.0)
        self.assertEqual(profile.points[0].z_mm, 0.0)
        self.assertEqual(profile.points[0].radius_mm, 32.0)
        self.assertEqual(profile.points[0].source, "base_bottom")

    def test_base_transition_is_inserted_without_overlap(self) -> None:
        phase2 = make_phase2_profile(
            (0.2, 2.0, 5.0, 10.0),
            (6.0, 6.0, 6.0, 6.0),
        )
        config = StabilityProfileConfig(
            minimum_radius_height_factor=0.0,
            minimum_base_radius_mm=10.0,
            base_height_factor=0.0,
            base_margin_mm=0.0,
            base_height_mm=4.0,
            maximum_radius_change_per_mm_z=2.0,
        )

        profile = build_stable_tower_profile(phase2, config)
        points_at_base_height = [
            point
            for point in profile.points
            if math.isclose(point.z_mm, 4.0)
        ]

        self.assertEqual(len(points_at_base_height), 1)
        self.assertEqual(
            points_at_base_height[0].source,
            "base_transition",
        )
        self.assertEqual(
            points_at_base_height[0].required_radius_mm,
            profile.base_radius_mm,
        )
        self.assertEqual(
            len({point.z_mm for point in profile.points}),
            len(profile.points),
        )

    def test_existing_layer_at_base_height_is_not_duplicated(self) -> None:
        phase2 = make_phase2_profile(
            (0.2, 4.0, 10.0),
            (6.0, 6.0, 6.0),
        )
        profile = build_stable_tower_profile(
            phase2,
            StabilityProfileConfig(
                minimum_radius_height_factor=0.0,
                base_height_mm=4.0,
                maximum_radius_change_per_mm_z=2.0,
            ),
        )

        points_at_base_height = [
            point for point in profile.points if point.z_mm == 4.0
        ]

        self.assertEqual(len(points_at_base_height), 1)
        self.assertEqual(points_at_base_height[0].source, "layer")
        self.assertEqual(points_at_base_height[0].layer_index, 2)

    def test_short_tower_clips_base_height_to_total_height(self) -> None:
        phase2 = make_phase2_profile(
            (0.2, 1.0, 2.0),
            (6.0, 6.0, 6.0),
        )
        profile = build_stable_tower_profile(
            phase2,
            StabilityProfileConfig(
                base_height_mm=4.0,
                maximum_radius_change_per_mm_z=1.0,
            ),
        )

        self.assertEqual(profile.effective_base_height_mm, 2.0)
        self.assertTrue(
            all(layer.base_radius_applied for layer in profile.layers)
        )
        self.assertFalse(
            any(
                point.source == "base_transition"
                for point in profile.points
            )
        )

    def test_bidirectional_smoothing_anticipates_and_holds_width(
        self,
    ) -> None:
        phase2 = make_phase2_profile(
            (10.0, 20.0, 21.0, 22.0, 40.0),
            (6.0, 6.0, 20.0, 6.0, 6.0),
        )
        config = StabilityProfileConfig(
            minimum_radius_height_factor=0.0,
            minimum_base_radius_mm=1.0,
            base_height_factor=0.0,
            base_margin_mm=0.0,
            base_height_mm=0.5,
            maximum_radius_change_per_mm_z=2.0,
        )

        profile = build_stable_tower_profile(phase2, config)
        stable_by_layer = {
            layer.layer_index: layer.stabilized_radius_mm
            for layer in profile.layers
        }

        self.assertEqual(stable_by_layer[1], 6.0)
        self.assertEqual(stable_by_layer[2], 18.0)
        self.assertEqual(stable_by_layer[3], 20.0)
        self.assertEqual(stable_by_layer[4], 18.0)
        self.assertEqual(stable_by_layer[5], 6.0)

        self.assertGreater(
            profile.layers[1].smoothing_increase_mm,
            0.0,
        )
        self.assertGreater(
            profile.layers[3].smoothing_increase_mm,
            0.0,
        )

    def test_all_stability_and_slope_invariants_hold(self) -> None:
        phase2 = make_phase2_profile(
            (0.2, 0.35, 0.7, 1.4, 2.8, 5.0, 9.0),
            (6.0, 12.0, 6.0, 18.0, 7.0, 30.0, 6.0),
        )
        config = StabilityProfileConfig(
            minimum_radius_height_factor=0.03,
            minimum_base_radius_mm=10.0,
            base_height_factor=0.05,
            base_margin_mm=2.0,
            base_height_mm=1.0,
            maximum_radius_change_per_mm_z=0.35,
        )

        profile = build_stable_tower_profile(phase2, config)

        for point in profile.points:
            self.assertGreaterEqual(
                point.radius_mm + 1e-9,
                point.required_radius_mm,
            )

        for previous, current in zip(
            profile.points,
            profile.points[1:],
        ):
            delta_z = current.z_mm - previous.z_mm
            maximum_change = (
                delta_z * config.maximum_radius_change_per_mm_z
            )
            self.assertLessEqual(
                abs(current.radius_mm - previous.radius_mm),
                maximum_change + 1e-9,
            )

        for phase2_layer, stable_layer in zip(
            phase2.layers,
            profile.layers,
            strict=True,
        ):
            self.assertGreaterEqual(
                stable_layer.stabilized_radius_mm,
                phase2_layer.radius_mm,
            )
            self.assertGreaterEqual(
                stable_layer.total_stability_increase_mm,
                0.0,
            )

    def test_deterministic_random_profiles_preserve_all_invariants(
        self,
    ) -> None:
        random_source = random.Random(20260713)

        for profile_number in range(100):
            layer_count = random_source.randint(5, 40)
            z_positions: list[float] = []
            current_z = 0.0

            for _ in range(layer_count):
                current_z += random_source.uniform(0.05, 0.8)
                z_positions.append(current_z)

            radii = tuple(
                random_source.uniform(5.0, 40.0)
                for _ in range(layer_count)
            )
            phase2 = make_phase2_profile(
                tuple(z_positions),
                radii,
                minimum_radius_mm=5.0,
            )
            config = StabilityProfileConfig(
                minimum_radius_height_factor=(
                    random_source.uniform(0.0, 0.08)
                ),
                minimum_base_radius_mm=random_source.uniform(5.0, 15.0),
                base_height_factor=random_source.uniform(0.0, 0.1),
                base_margin_mm=random_source.uniform(0.0, 5.0),
                base_height_mm=random_source.uniform(0.1, 5.0),
                maximum_radius_change_per_mm_z=(
                    random_source.uniform(0.1, 2.0)
                ),
            )

            with self.subTest(profile_number=profile_number):
                profile = build_stable_tower_profile(phase2, config)

                self.assertEqual(len(profile.layers), layer_count)
                self.assertEqual(profile.points[0].z_mm, 0.0)
                self.assertEqual(
                    profile.points[0].radius_mm,
                    profile.base_radius_mm,
                )

                for phase2_layer, stable_layer in zip(
                    phase2.layers,
                    profile.layers,
                    strict=True,
                ):
                    self.assertGreaterEqual(
                        stable_layer.stabilized_radius_mm + 1e-9,
                        phase2_layer.radius_mm,
                    )
                    self.assertGreaterEqual(
                        stable_layer.stabilized_radius_mm + 1e-9,
                        stable_layer.
                        required_radius_before_smoothing_mm,
                    )

                for previous, current in zip(
                    profile.points,
                    profile.points[1:],
                ):
                    delta_z = current.z_mm - previous.z_mm
                    self.assertGreater(delta_z, 0.0)
                    self.assertLessEqual(
                        abs(current.radius_mm - previous.radius_mm),
                        (
                            delta_z
                            * config.maximum_radius_change_per_mm_z
                            + 1e-9
                        ),
                    )

    def test_invalid_stability_configuration_is_rejected(self) -> None:
        phase2 = make_phase2_profile((1.0,), (6.0,))
        invalid_configs = (
            StabilityProfileConfig(
                minimum_radius_height_factor=-0.1
            ),
            StabilityProfileConfig(minimum_base_radius_mm=0.0),
            StabilityProfileConfig(base_height_factor=-0.1),
            StabilityProfileConfig(base_margin_mm=-0.1),
            StabilityProfileConfig(base_height_mm=0.0),
            StabilityProfileConfig(
                maximum_radius_change_per_mm_z=0.0
            ),
        )

        for config in invalid_configs:
            with self.subTest(config=config):
                with self.assertRaises(ProfileCalculationError):
                    build_stable_tower_profile(phase2, config)

    def test_empty_or_non_increasing_phase2_profile_is_rejected(
        self,
    ) -> None:
        empty_profile = TowerRadiusProfile(
            config=TowerProfileConfig(target_layer_time_s=10.0),
            global_seconds_per_deposition_mm=None,
            layers=(),
        )

        with self.assertRaises(ProfileCalculationError):
            build_stable_tower_profile(
                empty_profile,
                StabilityProfileConfig(),
            )

        duplicate_z_profile = make_phase2_profile(
            (1.0, 1.0),
            (6.0, 7.0),
        )

        with self.assertRaisesRegex(
            ProfileCalculationError,
            "strictly increasing",
        ):
            build_stable_tower_profile(
                duplicate_z_profile,
                StabilityProfileConfig(),
            )


class Phase3CliTests(unittest.TestCase):
    def test_cli_exports_stable_profile_columns_end_to_end(self) -> None:
        gcode = "\n".join(
            (
                "G90",
                "M83",
                "G1 Z0.2 F600",
                "G1 X10 E1 F600",
                "G1 Z4.0 F600",
                "G1 X20 E1 F600",
                "G1 Z10.0 F600",
                "G1 X30 E1 F600",
            )
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            gcode_path = temporary_path / "model.gcode"
            csv_path = temporary_path / "analysis.csv"
            gcode_path.write_text(gcode, encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(PROJECT_ROOT / "main.py"),
                    "--gcode",
                    str(gcode_path),
                    "--target-time",
                    "5",
                    "--minimum-radius",
                    "2",
                    "--maximum-radius",
                    "20",
                    "--minimum-radius-height-factor",
                    "0.04",
                    "--minimum-base-radius",
                    "5",
                    "--base-height-factor",
                    "0.05",
                    "--base-margin",
                    "1",
                    "--base-height",
                    "1",
                    "--maximum-radius-change",
                    "1",
                    "--local-window",
                    "3",
                    "--preview",
                    "0",
                    "--csv",
                    str(csv_path),
                ],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Phase-3 stable profile", result.stdout)
            self.assertIn("Profile support points:", result.stdout)

            with csv_path.open(
                encoding="utf-8-sig",
                newline="",
            ) as csv_file:
                rows = list(
                    csv.DictReader(csv_file, delimiter=";")
                )

        self.assertEqual(len(rows), 3)
        self.assertTrue(
            all(row["stabilized_radius_mm"] for row in rows)
        )
        self.assertTrue(
            all(
                float(row["stabilized_radius_mm"])
                + 1e-9
                >= float(row["tower_radius_mm"])
                for row in rows
            )
        )
        self.assertEqual(rows[0]["base_radius_applied"], "1")


if __name__ == "__main__":
    unittest.main()
