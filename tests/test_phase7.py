from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from PySide6.QtWidgets import QApplication

from cooling_tower.gui import MainWindow
from cooling_tower.models import GenerationSettings
from cooling_tower.services import GenerationService


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


class GuiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.gcode = self.root / "sample.gcode"
        self.gcode.write_text(SAMPLE_GCODE, encoding="utf-8")
        self.window = MainWindow(
            user_settings_path=self.root / "user_settings.json",
        )

    def tearDown(self) -> None:
        self.window.close()
        self.app.processEvents()
        self.temporary.cleanup()

class SettingsAndValidationTests(GuiTestCase):
    def test_all_generation_settings_are_reachable_and_roundtrip(self) -> None:
        expected = GenerationSettings(
            target_layer_time_s=30.0,
            minimum_outer_radius_mm=7.0,
            maximum_outer_radius_mm=25.0,
            minimum_wall_thickness_mm=0.9,
            maximum_wall_thickness_mm=4.5,
            wall_path_width_mm=0.45,
            minimum_inner_radius_mm=3.0,
            minimum_base_radius_mm=11.0,
            base_height_mm=5.0,
            base_margin_mm=2.5,
            base_height_factor=0.06,
            minimum_radius_height_factor=0.03,
            maximum_radius_change_per_mm_z=0.4,
            maximum_wall_change_per_mm_z=0.45,
            local_reference_window=7,
        )
        self.window.apply_settings(expected)
        self.assertEqual(self.window.collect_settings(), expected)

    def test_full_infill_simulation_hint_compares_both_modes(self) -> None:
        before = self.window.full_infill_info_button.toolTip()
        self.window.full_infill_checkbox.setChecked(True)
        text = self.window.full_infill_info_button.toolTip()
        self.assertEqual(text, before)
        self.assertIn("100%-Füllung", text)
        self.assertIn("Aktiviert", text)
        self.assertIn("Deaktiviert", text)
        self.assertNotIn("Aktuell aktiviert", text)

    def test_base_height_is_automatic(self) -> None:
        self.assertNotIn("base_height_mm", self.window._setting_widgets)

    def test_user_settings_are_persisted_and_restored(self) -> None:
        path = self.root / "user_settings.json"
        self.window.target_time_spin.setValue(27.5)
        self.window.output_root_edit.setText(str(self.root / "custom"))
        self.window.geometry_settings_group.setChecked(False)
        self.window.prediction_frame.setChecked(False)
        self.window.close()
        restored = MainWindow(user_settings_path=path)
        try:
            self.assertAlmostEqual(restored.target_time_spin.value(), 27.5)
            self.assertEqual(restored.output_root_edit.text(), str(self.root / "custom"))
            self.assertFalse(restored.geometry_settings_group.isChecked())
            self.assertFalse(restored.prediction_frame.isChecked())
        finally:
            restored.close()

    def test_defaults_can_be_restored(self) -> None:
        self.window.target_time_spin.setValue(99.0)
        self.window.full_infill_checkbox.setChecked(True)
        self.window.reset_defaults()
        self.assertAlmostEqual(self.window.target_time_spin.value(), 10.0)
        self.assertFalse(self.window.full_infill_checkbox.isChecked())


class SharedServiceTests(GuiTestCase):
    def test_cli_and_gui_settings_generate_identical_profiles(self) -> None:
        configured = GenerationSettings(
            target_layer_time_s=5.0,
            minimum_outer_diameter_mm=4.0,
            maximum_outer_diameter_mm=40.0,
            minimum_base_radius_mm=3.0,
            base_height_mm=0.2,
            base_margin_mm=1.0,
            base_height_factor=0.0,
            minimum_radius_height_factor=0.0,
            maximum_radius_change_per_mm_z=2.0,
            local_reference_window=3,
        )
        self.window.apply_settings(configured)
        gui_result = GenerationService(self.root / "gui_output").generate(
            self.gcode, self.window.collect_settings()
        )
        cli_output = self.root / "cli_output"
        command = (
            sys.executable,
            "-B",
            str(PROJECT_ROOT / "cli_main.py"),
            "--gcode", str(self.gcode),
            "--target-time", "5",
            "--minimum-diameter", "4",
            "--maximum-diameter", "40",
            "--minimum-base-radius", "3",
            "--base-height", "0.2",
            "--base-margin", "1",
            "--base-height-factor", "0",
            "--minimum-radius-height-factor", "0",
            "--maximum-radius-change", "2",
            "--local-window", "3",
            "--output-root", str(cli_output),
            "--preview", "0",
        )
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        cli_run = next((cli_output / "runs").iterdir())
        cli_profile = cli_run / "profiles" / "tower_profile.csv"
        self.assertEqual(
            gui_result.profile_path.read_bytes(), cli_profile.read_bytes()
        )


if __name__ == "__main__":
    unittest.main()
