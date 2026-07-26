from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from PySide6.QtCore import QMimeData, QPointF, QUrl, Qt
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication

from cooling_tower.gui import MainWindow
from cooling_tower.gui.widgets import GCodeDropZone
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

    def _select_file(self) -> None:
        self.assertTrue(self.window.drop_zone.set_file(self.gcode))
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            self.app.processEvents()
            assessment = self.window.tower_assessment
            if (
                self.window.analysis_snapshot is not None
                and assessment is not None
                and (
                    not assessment.tower_required
                    or self.window.profile_feasibility is not None
                )
            ):
                break
            time.sleep(0.005)
        self.app.processEvents()
        self.assertIsNotNone(self.window.analysis_snapshot)
        if self.window.tower_assessment.tower_required:
            self.assertIsNotNone(self.window.profile_feasibility)

class GCodeInputTests(GuiTestCase):
    def test_gcode_can_be_loaded_with_drop_event(self) -> None:
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(self.gcode))])
        event = QDropEvent(
            QPointF(10, 10),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        self.window.drop_zone.dropEvent(event)
        self.assertEqual(self.window.current_gcode_path, self.gcode.resolve())
        self.assertIn("sample.gcode", self.window.drop_zone.file_name_label.text())
        self.assertIn("Pfad:", self.window.drop_zone.file_info_label.text())

    def test_gcode_can_be_loaded_with_file_dialog(self) -> None:
        with patch.object(
            self.window.drop_zone.browse_button,
            "click",
            wraps=self.window.drop_zone.browse_button.click,
        ), patch(
            "cooling_tower.gui.widgets.gcode_drop_zone.QFileDialog.getOpenFileName",
            return_value=(str(self.gcode), "G-Code-Dateien (*.gcode)"),
        ):
            self.window.drop_zone.select_file()
        self.assertEqual(self.window.current_gcode_path, self.gcode.resolve())

    def test_invalid_file_type_is_rejected(self) -> None:
        invalid = self.root / "model.stl"
        invalid.write_text("solid", encoding="utf-8")
        messages: list[str] = []
        self.window.drop_zone.file_rejected.connect(messages.append)
        self.assertFalse(self.window.drop_zone.set_file(invalid))
        self.assertIsNone(self.window.current_gcode_path)
        self.assertTrue(messages)


class SettingsAndValidationTests(GuiTestCase):
    def test_all_generation_settings_are_reachable_and_roundtrip(self) -> None:
        expected = GenerationSettings(
            target_layer_time_s=30.0,
            safety_factor=1.2,
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
            mesh_segments=48,
        )
        self.window.apply_settings(expected)
        self.assertEqual(self.window.collect_settings(), expected)

    def test_wall_path_count_and_effective_values_update_live(self) -> None:
        self.window.minimum_wall_spin.setValue(0.8)
        self.window.maximum_wall_spin.setValue(4.2)
        self.window.path_width_spin.setValue(0.42)
        text = self.window.wall_paths_label.text()
        self.assertIn("2 Bahnen = 0.84 mm", text)
        self.assertIn("10 Bahnen = 4.20 mm", text)

    def test_invalid_values_disable_generation_and_mark_fields(self) -> None:
        self._select_file()
        self.window.workflow.slicer_succeeded("Testslicer")
        self.assertTrue(self.window.preview_button.isEnabled())
        self.window.minimum_outer_spin.setValue(50.0)
        self.window.maximum_outer_spin.setValue(10.0)
        self.assertFalse(self.window.preview_button.isEnabled())
        self.assertFalse(self.window.minimum_outer_spin.property("invalid"))
        self.assertTrue(self.window.maximum_outer_spin.property("invalid"))
        self.assertIn("Kleinster Außenradius", self.window.validation_label.text())
        self.assertIn("Größter Außenradius", self.window.validation_label.text())

    def test_user_settings_are_persisted_and_restored(self) -> None:
        path = self.root / "user_settings.json"
        self.window.target_time_spin.setValue(27.5)
        self.window.output_root_edit.setText(str(self.root / "custom"))
        self.window.timing_group.setChecked(False)
        self.window.prediction_frame.setChecked(False)
        self.window.close()
        restored = MainWindow(user_settings_path=path)
        try:
            self.assertAlmostEqual(restored.target_time_spin.value(), 27.5)
            self.assertEqual(restored.output_root_edit.text(), str(self.root / "custom"))
            self.assertFalse(restored.timing_group.isChecked())
            self.assertFalse(restored.prediction_frame.isChecked())
        finally:
            restored.close()

    def test_defaults_can_be_restored(self) -> None:
        self.window.target_time_spin.setValue(99.0)
        self.window.path_width_spin.setValue(0.45)
        self.window.reset_defaults()
        self.assertAlmostEqual(self.window.target_time_spin.value(), 11.0)
        self.assertAlmostEqual(self.window.path_width_spin.value(), 0.42)


class SharedServiceTests(GuiTestCase):
    def test_cli_and_gui_settings_generate_identical_profiles(self) -> None:
        configured = GenerationSettings(
            target_layer_time_s=5.0,
            safety_factor=1.0,
            minimum_outer_radius_mm=2.0,
            maximum_outer_radius_mm=20.0,
            minimum_wall_thickness_mm=0.8,
            maximum_wall_thickness_mm=2.1,
            wall_path_width_mm=0.42,
            minimum_inner_radius_mm=1.0,
            minimum_base_radius_mm=3.0,
            base_height_mm=0.2,
            base_margin_mm=1.0,
            base_height_factor=0.0,
            minimum_radius_height_factor=0.0,
            maximum_radius_change_per_mm_z=2.0,
            maximum_wall_change_per_mm_z=0.42,
            local_reference_window=3,
            mesh_segments=8,
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
            "--safety-factor", "1",
            "--minimum-radius", "2",
            "--maximum-radius", "20",
            "--minimum-wall", "0.8",
            "--maximum-wall", "2.1",
            "--wall-path-width", "0.42",
            "--minimum-inner-radius", "1",
            "--minimum-base-radius", "3",
            "--base-height", "0.2",
            "--base-margin", "1",
            "--base-height-factor", "0",
            "--minimum-radius-height-factor", "0",
            "--maximum-radius-change", "2",
            "--maximum-wall-change", "0.42",
            "--local-window", "3",
            "--mesh-segments", "8",
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
