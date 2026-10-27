from __future__ import annotations

import csv
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from layer_analyzer import LayerRecord
from main import write_layer_csv
from tower_generator import (
    ProfileCalculationError,
    TowerProfileConfig,
    build_tower_radius_profile,
)


def make_layer(
    index: int,
    *,
    total_time_s: float,
    deposition_time_s: float,
    deposition_path_mm: float,
) -> LayerRecord:
    travel_time_s = max(0.0, total_time_s - deposition_time_s)

    return LayerRecord(
        index=index,
        z_mm=index * 0.2,
        height_mm=0.2,
        start_line=index * 10,
        first_deposition_line=index * 10 + 1,
        end_line=index * 10 + 9,
        event_count=2,
        movement_count=2,
        deposition_count=(
            1 if deposition_path_mm > 0.0 else 0
        ),
        total_time_s=total_time_s,
        deposition_time_s=deposition_time_s,
        travel_time_s=travel_time_s,
        retraction_time_s=0.0,
        unretraction_time_s=0.0,
        dwell_time_s=0.0,
        other_time_s=0.0,
        deposition_path_mm=deposition_path_mm,
        deposition_e_mm=(
            deposition_path_mm / 20.0
            if deposition_path_mm > 0.0
            else 0.0
        ),
        untimed_event_count=0,
        untimed_distance_mm=0.0,
    )


class TowerRadiusProfileTests(unittest.TestCase):
    def test_deficit_and_radius_limits(self) -> None:
        layers = (
            make_layer(
                1,
                total_time_s=30.0,
                deposition_time_s=10.0,
                deposition_path_mm=100.0,
            ),
            make_layer(
                2,
                total_time_s=20.0,
                deposition_time_s=10.0,
                deposition_path_mm=100.0,
            ),
            make_layer(
                3,
                total_time_s=29.0,
                deposition_time_s=10.0,
                deposition_path_mm=100.0,
            ),
        )
        config = TowerProfileConfig(
            target_layer_time_s=30.0,
            minimum_radius_mm=6.0,
            maximum_radius_mm=40.0,
            local_time_factor_window=3,
        )

        profile = build_tower_radius_profile(layers, config)
        first, second, third = profile.layers

        self.assertAlmostEqual(
            profile.global_seconds_per_deposition_mm,
            0.1,
        )
        self.assertEqual(profile.deficit_layer_count, 2)

        self.assertEqual(first.time_deficit_s, 0.0)
        self.assertEqual(first.radius_mm, 6.0)
        self.assertEqual(first.radius_limit, "minimum")

        self.assertAlmostEqual(second.time_deficit_s, 10.0)
        self.assertAlmostEqual(second.additional_path_mm, 100.0)
        self.assertAlmostEqual(second.safety_adjusted_path_mm, 100.0)
        self.assertAlmostEqual(
            second.calculated_radius_mm,
            100.0 / math.tau,
        )
        self.assertAlmostEqual(
            second.radius_mm,
            100.0 / math.tau,
        )
        self.assertEqual(second.radius_limit, "none")
        self.assertAlmostEqual(
            second.estimated_combined_layer_time_s,
            30.0,
        )

        self.assertAlmostEqual(third.time_deficit_s, 1.0)
        self.assertEqual(third.radius_mm, 6.0)
        self.assertEqual(third.radius_limit, "minimum")

    def test_maximum_radius_cap_is_reported(self) -> None:
        layers = (
            make_layer(
                1,
                total_time_s=1.0,
                deposition_time_s=1.0,
                deposition_path_mm=100.0,
            ),
        )
        config = TowerProfileConfig(
            target_layer_time_s=100.0,
            minimum_radius_mm=6.0,
            maximum_radius_mm=40.0,
            local_time_factor_window=1,
        )

        profile = build_tower_radius_profile(layers, config)
        result = profile.layers[0]

        self.assertEqual(result.radius_mm, 40.0)
        self.assertEqual(result.radius_limit, "maximum")
        self.assertEqual(profile.maximum_limited_layer_count, 1)
        self.assertLess(
            result.estimated_combined_layer_time_s,
            result.target_layer_time_s,
        )

    def test_centered_local_window_is_path_weighted(self) -> None:
        factors = (0.01, 0.02, 0.03, 0.04, 0.05)
        layers = tuple(
            make_layer(
                index,
                total_time_s=factor * 100.0,
                deposition_time_s=factor * 100.0,
                deposition_path_mm=100.0,
            )
            for index, factor in enumerate(factors, start=1)
        )
        config = TowerProfileConfig(
            target_layer_time_s=10.0,
            local_time_factor_window=3,
        )

        profile = build_tower_radius_profile(layers, config)

        self.assertAlmostEqual(
            profile.layers[0].seconds_per_deposition_mm,
            0.02,
        )
        self.assertEqual(
            (
                profile.layers[0].reference_start_layer,
                profile.layers[0].reference_end_layer,
            ),
            (1, 3),
        )
        self.assertAlmostEqual(
            profile.layers[2].seconds_per_deposition_mm,
            0.03,
        )
        self.assertEqual(
            (
                profile.layers[2].reference_start_layer,
                profile.layers[2].reference_end_layer,
            ),
            (2, 4),
        )
        self.assertAlmostEqual(
            profile.layers[4].seconds_per_deposition_mm,
            0.04,
        )
        self.assertEqual(
            (
                profile.layers[4].reference_start_layer,
                profile.layers[4].reference_end_layer,
            ),
            (3, 5),
        )

    def test_time_factor_uses_path_weighting_not_layer_average(
        self,
    ) -> None:
        layers = (
            make_layer(
                1,
                total_time_s=2.0,
                deposition_time_s=2.0,
                deposition_path_mm=100.0,
            ),
            make_layer(
                2,
                total_time_s=24.0,
                deposition_time_s=24.0,
                deposition_path_mm=300.0,
            ),
            make_layer(
                3,
                total_time_s=20.0,
                deposition_time_s=20.0,
                deposition_path_mm=100.0,
            ),
        )
        config = TowerProfileConfig(
            target_layer_time_s=30.0,
            local_time_factor_window=3,
        )

        profile = build_tower_radius_profile(layers, config)

        expected_weighted_factor = 46.0 / 500.0
        arithmetic_layer_average = (0.02 + 0.08 + 0.20) / 3.0

        self.assertAlmostEqual(
            profile.global_seconds_per_deposition_mm,
            expected_weighted_factor,
        )
        self.assertAlmostEqual(
            profile.layers[1].seconds_per_deposition_mm,
            expected_weighted_factor,
        )
        self.assertNotAlmostEqual(
            expected_weighted_factor,
            arithmetic_layer_average,
        )

    def test_global_factor_is_used_when_local_window_has_no_data(
        self,
    ) -> None:
        layers = (
            make_layer(
                1,
                total_time_s=2.0,
                deposition_time_s=2.0,
                deposition_path_mm=100.0,
            ),
            make_layer(
                2,
                total_time_s=0.0,
                deposition_time_s=0.0,
                deposition_path_mm=0.0,
            ),
            make_layer(
                3,
                total_time_s=0.0,
                deposition_time_s=0.0,
                deposition_path_mm=0.0,
            ),
            make_layer(
                4,
                total_time_s=0.0,
                deposition_time_s=0.0,
                deposition_path_mm=0.0,
            ),
            make_layer(
                5,
                total_time_s=4.0,
                deposition_time_s=4.0,
                deposition_path_mm=100.0,
            ),
        )
        config = TowerProfileConfig(
            target_layer_time_s=10.0,
            local_time_factor_window=3,
        )

        profile = build_tower_radius_profile(layers, config)
        center = profile.layers[2]

        self.assertAlmostEqual(
            profile.global_seconds_per_deposition_mm,
            0.03,
        )
        self.assertAlmostEqual(
            center.seconds_per_deposition_mm,
            0.03,
        )
        self.assertEqual(center.time_factor_source, "global")
        self.assertEqual(center.reference_start_layer, 1)
        self.assertEqual(center.reference_end_layer, 5)

    def test_missing_reference_raises_only_when_time_is_missing(
        self,
    ) -> None:
        no_deposition = (
            make_layer(
                1,
                total_time_s=1.0,
                deposition_time_s=0.0,
                deposition_path_mm=0.0,
            ),
        )

        with self.assertRaisesRegex(
            ProfileCalculationError,
            "no usable deposition-time reference",
        ):
            build_tower_radius_profile(
                no_deposition,
                TowerProfileConfig(
                    target_layer_time_s=5.0,
                    local_time_factor_window=1,
                ),
            )

        profile = build_tower_radius_profile(
            no_deposition,
            TowerProfileConfig(
                target_layer_time_s=0.5,
                local_time_factor_window=1,
            ),
        )

        self.assertEqual(profile.layers[0].radius_mm, 6.0)
        self.assertEqual(
            profile.layers[0].time_factor_source,
            "unavailable",
        )
        self.assertIsNone(
            profile.layers[0].estimated_added_time_s
        )

    def test_invalid_configuration_is_rejected(self) -> None:
        layer = make_layer(
            1,
            total_time_s=5.0,
            deposition_time_s=2.0,
            deposition_path_mm=100.0,
        )
        invalid_configs = (
            TowerProfileConfig(target_layer_time_s=0.0),
            TowerProfileConfig(
                target_layer_time_s=5.0,
                minimum_radius_mm=0.0,
            ),
            TowerProfileConfig(
                target_layer_time_s=5.0,
                minimum_radius_mm=10.0,
                maximum_radius_mm=9.0,
            ),
            TowerProfileConfig(
                target_layer_time_s=5.0,
                local_time_factor_window=4,
            ),
        )

        for config in invalid_configs:
            with self.subTest(config=config):
                with self.assertRaises(ProfileCalculationError):
                    build_tower_radius_profile((layer,), config)


class Phase2OutputTests(unittest.TestCase):
    def test_csv_contains_phase2_columns_and_values(self) -> None:
        layers = (
            make_layer(
                1,
                total_time_s=20.0,
                deposition_time_s=10.0,
                deposition_path_mm=100.0,
            ),
        )
        profile = build_tower_radius_profile(
            layers,
            TowerProfileConfig(
                target_layer_time_s=30.0,
                local_time_factor_window=1,
            ),
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            csv_path = Path(temporary_directory) / "analysis.csv"
            write_layer_csv(
                layers,
                csv_path,
                radius_profile=profile,
            )

            with csv_path.open(
                encoding="utf-8-sig",
                newline="",
            ) as csv_file:
                rows = list(
                    csv.DictReader(csv_file, delimiter=";")
                )

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["time_factor_source"], "local")
        self.assertEqual(row["radius_limit"], "none")
        self.assertAlmostEqual(float(row["time_deficit_s"]), 10.0)
        self.assertAlmostEqual(
            float(row["additional_path_mm"]),
            100.0,
        )
        self.assertAlmostEqual(
            float(row["tower_radius_mm"]),
            100.0 / math.tau,
            places=5,
        )

    def test_phase1_csv_stays_backward_compatible(self) -> None:
        layers = (
            make_layer(
                1,
                total_time_s=20.0,
                deposition_time_s=10.0,
                deposition_path_mm=100.0,
            ),
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            csv_path = Path(temporary_directory) / "analysis.csv"
            write_layer_csv(layers, csv_path)

            with csv_path.open(
                encoding="utf-8-sig",
                newline="",
            ) as csv_file:
                reader = csv.DictReader(csv_file, delimiter=";")
                field_names = reader.fieldnames

        self.assertNotIn("tower_radius_mm", field_names)
        self.assertIn("seconds_per_deposition_mm", field_names)

    def test_cli_runs_phase2_end_to_end(self) -> None:
        gcode = "\n".join(
            (
                "G90",
                "M83",
                "G1 Z0.2 F600",
                "G1 X10 E1 F600",
                "G1 Z0.4 F600",
                "G1 X20 E1 F600",
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
                    "1",
                    "--maximum-radius",
                    "40",
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
            self.assertIn("Phase-2 radius profile", result.stdout)

            with csv_path.open(
                encoding="utf-8-sig",
                newline="",
            ) as csv_file:
                rows = list(
                    csv.DictReader(csv_file, delimiter=";")
                )

        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["tower_radius_mm"] for row in rows))
        self.assertTrue(all(row["time_deficit_s"] for row in rows))


if __name__ == "__main__":
    unittest.main()
