from __future__ import annotations

import json
import math
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import struct
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cooling_tower.models import GenerationSettings
from cooling_tower.services import (
    GenerationService,
    OutputService,
    build_generation_report,
    format_generation_report,
)
from cooling_tower.tower.hollow_profile import build_hollow_tower_profile
from cooling_tower.tower.profile import (
    LayerRadiusRecord,
    TowerProfileConfig,
    TowerRadiusProfile,
)
from cooling_tower.tower.wall_calculator import calculate_wall_path_length


def base_settings(**changes: object) -> GenerationSettings:
    result = GenerationSettings(
        target_layer_time_s=10.0,
        safety_factor=1.0,
        minimum_outer_radius_mm=5.0,
        maximum_outer_radius_mm=10.0,
        minimum_wall_thickness_mm=0.8,
        maximum_wall_thickness_mm=4.2,
        wall_path_width_mm=0.42,
        minimum_inner_radius_mm=2.0,
        minimum_base_radius_mm=5.0,
        base_height_mm=0.0,
        base_margin_mm=0.0,
        base_height_factor=0.0,
        minimum_radius_height_factor=0.0,
        maximum_radius_change_per_mm_z=100.0,
        maximum_wall_change_per_mm_z=100.0,
        local_reference_window=3,
        mesh_segments=16,
    )
    return replace(result, **changes)


def make_phase2(
    required_paths: tuple[float, ...],
    z_positions: tuple[float, ...],
) -> TowerRadiusProfile:
    layers = tuple(
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
        for index, (required, z) in enumerate(
            zip(required_paths, z_positions, strict=True), start=1
        )
    )
    return TowerRadiusProfile(
        TowerProfileConfig(target_layer_time_s=10.0),
        0.1,
        layers,
    )


class LineWidthPresetTests(unittest.TestCase):
    def test_040_042_and_045_presets_quantize_and_step_correctly(self) -> None:
        expected_minimum = {0.40: 0.80, 0.42: 0.84, 0.45: 0.90}
        for width in (0.40, 0.42, 0.45):
            configured = base_settings(wall_path_width_mm=width)
            at_two = calculate_wall_path_length(10.0, 2, width) - 0.001
            at_three = calculate_wall_path_length(10.0, 3, width) - 0.001
            profile = build_hollow_tower_profile(
                make_phase2((at_two, at_three), (1.0, 2.0)),
                configured,
            )
            with self.subTest(width=width):
                self.assertEqual(
                    [layer.wall_path_count for layer in profile.layers],
                    [2, 3],
                )
                self.assertAlmostEqual(
                    profile.layers[0].wall_thickness_mm,
                    expected_minimum[width],
                )
                self.assertAlmostEqual(
                    profile.layers[1].wall_thickness_mm
                    - profile.layers[0].wall_thickness_mm,
                    width,
                )


class EdgeCaseTests(unittest.TestCase):
    def test_very_low_and_very_high_towers_are_valid(self) -> None:
        low = build_hollow_tower_profile(
            make_phase2((0.0,), (0.05,)), base_settings(base_height_mm=4.0)
        )
        high = build_hollow_tower_profile(
            make_phase2((0.0, 0.0), (5000.0, 10000.0)),
            base_settings(
                maximum_outer_radius_mm=20.0,
                minimum_radius_height_factor=0.001,
            ),
        )
        self.assertAlmostEqual(low.effective_base_height_mm, 0.05)
        self.assertEqual(high.total_height_mm, 10000.0)
        self.assertTrue(all(layer.inner_radius_mm > 0 for layer in high.layers))

    def test_all_long_and_almost_all_short_layers_finish_with_warnings_as_needed(self) -> None:
        long_profile = build_hollow_tower_profile(
            make_phase2((0.0,) * 20, tuple(range(1, 21))),
            base_settings(),
        )
        short_profile = build_hollow_tower_profile(
            make_phase2((10_000.0,) * 19 + (0.0,), tuple(range(1, 21))),
            base_settings(),
        )
        self.assertTrue(all(layer.target_reached for layer in long_profile.layers))
        self.assertEqual(
            sum(not layer.target_reached for layer in short_profile.layers), 19
        )
        self.assertTrue(short_profile.warnings)

    def test_strongly_variable_heights_preserve_order_and_bounds(self) -> None:
        z = (0.1, 0.3, 1.2, 1.25, 4.0, 10.0, 25.0)
        profile = build_hollow_tower_profile(
            make_phase2((10.0, 200.0, 20.0, 400.0, 0.0, 300.0, 50.0), z),
            base_settings(maximum_radius_change_per_mm_z=1.0),
        )
        self.assertEqual(tuple(layer.z for layer in profile.layers), z)
        self.assertTrue(all(layer.outer_radius_mm <= 10.0 for layer in profile.layers))
        self.assertTrue(all(layer.inner_radius_mm >= 2.0 for layer in profile.layers))

    def test_huge_deficit_hits_radius_wall_and_inner_limits_safely(self) -> None:
        profile = build_hollow_tower_profile(
            make_phase2((100_000.0,), (1.0,)),
            base_settings(minimum_inner_radius_mm=8.5),
        )
        layer = profile.layers[0]
        self.assertAlmostEqual(layer.outer_radius_mm, 10.0)
        self.assertEqual(layer.wall_path_count, 3)
        self.assertGreaterEqual(layer.inner_radius_mm, 8.5)
        self.assertFalse(layer.target_reached)
        self.assertTrue(any("Mindest-Innenradius" in text for text in profile.warnings))

    def test_gcode_without_comments_and_with_many_z_hops_detects_real_layers(self) -> None:
        gcode = "\n".join(
            (
                "G90", "M83", "G1 Z0.2 F600", "G1 X10 E1 F600",
                "G1 Z1.0 F600", "G1 Z0.2 F600", "G1 X20 E1 F600",
                "G1 Z0.4 F600", "G1 X30 E1 F600",
            )
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "hops.gcode"
            source.write_text(gcode, encoding="utf-8")
            result = GenerationService(root / "out").generate(
                source,
                base_settings(
                    target_layer_time_s=5.0,
                    minimum_outer_radius_mm=3.0,
                    maximum_outer_radius_mm=20.0,
                    minimum_inner_radius_mm=1.0,
                    minimum_base_radius_mm=3.0,
                    mesh_segments=8,
                ),
            )
            self.assertEqual(result.layer_count, 2)
            self.assertEqual(
                tuple(layer.z_mm for layer in result.analysis.layers),
                (0.2, 0.4),
            )

    def test_damaged_file_fails_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "damaged.gcode"
            source.write_text("G90\nG1 X??? E???\nBROKEN", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "No printable layers"):
                GenerationService(root / "out").generate(
                    source, base_settings()
                )

    def test_permission_error_from_output_is_propagated_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "sample.gcode"
            source.write_text(
                "G90\nM83\nG1 Z0.2 F600\nG1 X10 E1 F600\n",
                encoding="utf-8",
            )
            with patch.object(
                OutputService,
                "create_run_directories",
                side_effect=PermissionError("read-only output"),
            ):
                with self.assertRaisesRegex(PermissionError, "read-only"):
                    GenerationService(Path(temporary_directory) / "out").generate(
                        source, base_settings()
                    )

    def test_existing_run_name_gets_collision_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            service = OutputService(temporary_directory)
            moment = datetime(2026, 7, 13, 12, 0, 0)
            first = service.create_run_directories("x.gcode", timestamp=moment)
            second = service.create_run_directories("x.gcode", timestamp=moment)
            self.assertEqual(second.run_directory.name, first.run_directory.name + "_2")


class ReportingAndLaunchTests(unittest.TestCase):
    def test_unified_report_contains_every_required_core_value(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "sample.gcode"
            source.write_text(
                "G90\nM83\nG1 Z0.2 F600\nG1 X10 E1 F600\n",
                encoding="utf-8",
            )
            result = GenerationService(root / "out").generate(
                source,
                base_settings(
                    target_layer_time_s=5.0,
                    minimum_outer_radius_mm=3.0,
                    maximum_outer_radius_mm=20.0,
                    minimum_inner_radius_mm=1.0,
                    minimum_base_radius_mm=3.0,
                    mesh_segments=8,
                ),
            )
            report = build_generation_report(result)
            text = format_generation_report(result)
            self.assertGreater(report.maximum_time_deficit_s, 0.0)
            for label in (
                "G-Code-Datei", "Erkannte Layer", "Layer unter Zielzeit",
                "Maximales Zeitdefizit", "Außendurchmesser min/max",
                "Nicht vollständig lösbare Layer", "STL", "Laufordner",
            ):
                self.assertIn(label, text)

    def test_windows_start_file_uses_project_venv_without_shell_launchers(
        self,
    ) -> None:
        launcher_content = (PROJECT_ROOT / "start_gui.pyw").read_text(
            encoding="utf-8"
        ).lower()
        self.assertIn('project_venv = project_root / ".venv"', launcher_content)
        self.assertIn('project_venv / "scripts" / "pythonw.exe"', launcher_content)
        self.assertIn("subprocess.popen(", launcher_content)
        self.assertIn('getattr(subprocess, "create_no_window", 0)', launcher_content)
        self.assertIn('"detached_process"', launcher_content)
        self.assertIn("stdin=subprocess.devnull", launcher_content)
        self.assertIn("path(sys.prefix).resolve()", launcher_content)
        self.assertIn("if not project_pythonw.is_file():", launcher_content)
        self.assertFalse((PROJECT_ROOT / "start_gui.bat").exists())
        self.assertFalse((PROJECT_ROOT / "start_gui.vbs").exists())

        shortcut_script = (
            PROJECT_ROOT / "scripts" / "create_dev_shortcut.ps1"
        ).read_text(encoding="utf-8").lower()
        self.assertIn("sacrificial tower.lnk", shortcut_script)
        self.assertIn(".venv\\scripts\\pythonw.exe", shortcut_script)
        self.assertIn("start_gui.pyw", shortcut_script)
        self.assertIn("app.ico", shortcut_script)
        self.assertIn("createshortcut", shortcut_script)
        self.assertIn("iconlocation", shortcut_script)
        self.assertIn(
            "/sacrificial tower.lnk",
            (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").lower(),
        )

        icon_payload = (
            PROJECT_ROOT
            / "src"
            / "cooling_tower"
            / "gui"
            / "assets"
            / "app.ico"
        ).read_bytes()
        reserved, image_type, image_count = struct.unpack_from(
            "<HHH", icon_payload
        )
        self.assertEqual((reserved, image_type, image_count), (0, 1, 9))
        icon_sizes = [
            256 if icon_payload[6 + index * 16] == 0
            else icon_payload[6 + index * 16]
            for index in range(image_count)
        ]
        self.assertEqual(
            icon_sizes,
            [16, 20, 24, 32, 40, 48, 64, 128, 256],
        )


if __name__ == "__main__":
    unittest.main()
