from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cooling_tower.config import load_generation_settings
from cooling_tower.models import GenerationSettings
from cooling_tower.services import (
    GenerationService,
    MigrationService,
    OutputService,
)


SAMPLE_GCODE = "\n".join(
    (
        "G90",
        "M83",
        "G1 Z0.2 F600",
        "G1 X10 E1 F600",
        "G1 Z0.4 F600",
        "G1 X20 E1 F600",
    )
)


class OutputServiceTests(unittest.TestCase):
    def test_creates_complete_timestamped_run_structure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            service = OutputService(Path(temporary_directory) / "out")
            paths = service.create_run_directories(
                "My invalid:model?.gcode",
                timestamp=datetime(2026, 7, 13, 15, 30, 25),
            )

            self.assertEqual(
                paths.run_directory.name,
                "20260713_153025_My_invalid_model",
            )
            self.assertTrue(all(path.is_dir() for path in paths.directories))
            self.assertEqual(paths.stl_path.name, "cooling_tower.stl")
            self.assertEqual(paths.analysis_path.name, "layer_analysis.csv")
            self.assertEqual(paths.profile_path.name, "tower_profile.csv")

    def test_same_timestamp_and_source_never_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            service = OutputService(temporary_directory)
            timestamp = datetime(2026, 7, 13, 15, 30, 25)
            first = service.create_run_directories(
                "model.gcode", timestamp=timestamp
            )
            second = service.create_run_directories(
                "model.gcode", timestamp=timestamp
            )
            self.assertNotEqual(first.run_directory, second.run_directory)
            self.assertEqual(second.run_directory.name, first.run_directory.name + "_2")

    def test_settings_roundtrip_records_actual_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            service = OutputService(temporary_directory)
            paths = service.create_run_directories("model.gcode")
            expected = GenerationSettings(
                target_layer_time_s=17.5,
                wall_path_width_mm=0.45,
                mesh_segments=48,
            )
            service.write_settings(paths, expected)
            self.assertEqual(load_generation_settings(paths.settings_path), expected)


class MigrationServiceTests(unittest.TestCase):
    def test_moves_flat_files_into_categories_and_writes_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "output"
            output.mkdir()
            (output / "tower.stl").write_bytes(b"stl")
            (output / "layer_analysis.csv").write_text("a", encoding="utf-8")
            (output / "tower_profile.csv").write_text("p", encoding="utf-8")
            (output / "generation_settings.json").write_text("{}", encoding="utf-8")
            (output / "generation.log").write_text("ok", encoding="utf-8")

            result = MigrationService(output).migrate_flat_output()

            self.assertEqual(len(result.moved_files), 5)
            self.assertTrue(result.report_path.is_file())
            self.assertTrue((result.migrated_root / "stl" / "tower.stl").is_file())
            self.assertTrue(
                (result.migrated_root / "analysis" / "layer_analysis.csv").is_file()
            )
            self.assertTrue(
                (result.migrated_root / "profiles" / "tower_profile.csv").is_file()
            )
            self.assertEqual(list(output.glob("*.*")), [])

    def test_migration_uses_suffix_instead_of_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "output"
            existing = output / "migrated_legacy" / "stl" / "tower.stl"
            existing.parent.mkdir(parents=True)
            existing.write_bytes(b"old")
            (output / "tower.stl").write_bytes(b"new")

            MigrationService(output).migrate_flat_output()

            self.assertEqual(existing.read_bytes(), b"old")
            self.assertEqual(existing.with_name("tower_2.stl").read_bytes(), b"new")


class GenerationServiceTests(unittest.TestCase):
    def test_complete_run_writes_all_artifacts_and_valid_mesh(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            gcode = root / "sample.gcode"
            gcode.write_text(SAMPLE_GCODE, encoding="utf-8")
            settings = GenerationSettings(
                target_layer_time_s=5.0,
                minimum_outer_radius_mm=2.0,
                maximum_outer_radius_mm=20.0,
                minimum_base_radius_mm=3.0,
                base_height_mm=0.2,
                base_margin_mm=1.0,
                mesh_segments=8,
            )
            progress: list[int] = []

            result = GenerationService(root / "out").generate(
                gcode,
                settings,
                progress_callback=lambda percent, status: progress.append(percent),
            )

            for artifact in (
                result.stl_path,
                result.analysis_path,
                result.profile_path,
                result.settings_path,
                result.summary_path,
                result.log_path,
            ):
                self.assertTrue(artifact.is_file(), artifact)
                self.assertTrue(artifact.is_relative_to(result.run_directory))
            self.assertEqual(result.layer_count, 2)
            self.assertTrue(result.mesh_validation.is_valid)
            self.assertEqual(progress[-1], 100)

    def test_cli_uses_output_root_without_explicit_stl_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            gcode = root / "sample.gcode"
            output = root / "custom output"
            gcode.write_text(SAMPLE_GCODE, encoding="utf-8")
            result = subprocess.run(
                (
                    sys.executable,
                    "-B",
                    str(PROJECT_ROOT / "main.py"),
                    "--gcode",
                    str(gcode),
                    "--target-time",
                    "5",
                    "--minimum-radius",
                    "2",
                    "--maximum-radius",
                    "20",
                    "--minimum-base-radius",
                    "3",
                    "--base-height",
                    "0.2",
                    "--mesh-segments",
                    "8",
                    "--output-root",
                    str(output),
                    "--preview",
                    "0",
                ),
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Cooling-tower generation completed", result.stdout)
            runs = list((output / "runs").iterdir())
            self.assertEqual(len(runs), 1)
            self.assertTrue((runs[0] / "stl" / "cooling_tower.stl").is_file())


if __name__ == "__main__":
    unittest.main()
