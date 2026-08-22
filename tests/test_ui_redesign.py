from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("COOLING_TOWER_DISABLE_SLICER_DISCOVERY", "1")

from PySide6.QtWidgets import QApplication

from cooling_tower.gui.main_window import MainWindow
from cooling_tower.gui.widgets import PreviewCanvas
from cooling_tower.models import BedBounds, FeasibilityIssue
from cooling_tower.preview import (
    LineSegment3D,
    Point3D,
    PreviewScene,
)


class UiRedesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.app.processEvents()
        self.temporary.cleanup()

    def window(self) -> MainWindow:
        return MainWindow(user_settings_path=self.root / "settings.json")

    def test_01_expert_sections_start_collapsed_and_progress_is_not_idle_noise(self) -> None:
        window = self.window()
        self.assertFalse(hasattr(window, "profile_group"))
        self.assertTrue(window.geometry_settings_group.isChecked())
        self.assertFalse(hasattr(window, "advanced_group"))
        self.assertFalse(hasattr(window, "output_group"))
        for group in (window.geometry_group, window.stability_group):
            self.assertTrue(group.isChecked())
        self.assertTrue(window.progress_bar.isHidden())
        window.close()

    def test_02_stl_and_preview_iteration_explanations_are_compact(self) -> None:
        window = self.window()
        self.assertEqual(
            window.stl_mode_description.text(),
            "STL-Dateien bleiben allgemein anpassbar.",
        )
        self.assertFalse(hasattr(window, "preview_quality_label"))
        self.assertEqual(window.preview_faster_label.text(), "Schneller")
        self.assertEqual(window.preview_precise_label.text(), "Präziser")
        self.assertEqual(window.preview_iteration_count_label.text(), "3 Durchläufe")
        self.assertTrue(window.preview_iteration_slider.toolTip())
        self.assertIn("endgültige Layerzeit", window.layer_time_check_hint.text())
        window.close()

    def test_03_hundreds_of_layer_issues_become_one_actionable_summary(self) -> None:
        window = self.window()
        issues = tuple(
            FeasibilityIssue(
                code="EXPANSION_ANGLE_TOO_SMALL",
                message="Der eingestellte Zunahmewinkel ist zu flach.",
                affected_layer_index=layer,
                affected_z_mm=layer * 0.2,
                related_setting_names=("maximum_expansion_angle_deg",),
                required_value=88.5,
                achievable_value=50.0,
            )
            for layer in range(23, 824)
        )
        grouped = window._group_feasibility_issues(issues)
        window._last_changed_setting_name = "maximum_expansion_angle_deg"
        field_errors = window._field_errors_for_issues(issues)
        self.assertEqual(len(grouped), 1)
        self.assertIn("Betroffen sind 801 Layer", grouped[0]["summary"])
        self.assertIn(
            "Erforderlich sind bis zu 88,50°. Zulässig sind höchstens 70,00°.",
            grouped[0]["summary"],
        )
        self.assertEqual(
            len(field_errors["maximum_expansion_angle_deg"]), 1
        )
        window.close()

    def test_04_issue_panel_only_appears_for_real_errors(self) -> None:
        window = self.window()
        window.show()
        window.workflow.set_slicer_step_visible(True)
        window.workflow.source_validation_succeeded(
            "referenz.stl geprüft",
            analysis_complete=True,
        )
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        self.app.processEvents()
        self.assertTrue(window.error_panel.isHidden())
        window.minimum_outer_spin.setValue(0.0)
        window.validate_form()
        self.app.processEvents()
        self.assertTrue(window.error_panel.isVisible())
        self.assertTrue(window.geometry_group.isChecked())
        self.assertEqual(
            window.validation_label.text().splitlines(),
            [
                "Kleinster Außendurchmesser: 0,000 mm",
                "• Liegt unter dem Mindestwert 0,002 mm.",
            ],
        )
        window.close()

    def test_05_preview_defaults_to_objects_but_can_show_the_whole_bed(self) -> None:
        canvas = PreviewCanvas()
        scene = PreviewScene(
            (
                LineSegment3D(
                    Point3D(80.0, 80.0, 0.2),
                    Point3D(90.0, 90.0, 15.0),
                ),
            ),
            (
                LineSegment3D(
                    Point3D(110.0, 100.0, 0.0),
                    Point3D(110.0, 100.0, 15.0),
                ),
            ),
            BedBounds(0.0, 250.0, 0.0, 250.0),
            (110.0, 100.0),
            1,
            1,
            15.0,
        )
        canvas.set_scene(scene)
        self.assertFalse(canvas._fit_whole_bed)
        canvas.fit_scene()
        self.assertTrue(canvas._fit_whole_bed)
        canvas.fit_objects()
        self.assertFalse(canvas._fit_whole_bed)
        canvas.close()


if __name__ == "__main__":
    unittest.main()
