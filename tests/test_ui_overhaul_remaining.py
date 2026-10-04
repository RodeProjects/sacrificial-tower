from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("COOLING_TOWER_DISABLE_SLICER_DISCOVERY", "1")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from cooling_tower.gui.main_window import MainWindow
from cooling_tower.gui.widgets import SectionCard
from cooling_tower.models import FeasibilityIssue
from cooling_tower.models import ProfileFeasibilityAssessment
from cooling_tower.preview import OutputMode, PreviewState


class RemainingUiOverhaulTests(unittest.TestCase):
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

    def test_source_card_uses_dedicated_rows_and_only_wraps_the_path(self) -> None:
        window = self.window()
        zone = window.drop_zone
        self.assertFalse(zone.status_value_label.wordWrap())
        self.assertFalse(zone.file_name_label.wordWrap())
        self.assertFalse(zone.file_size_label.wordWrap())
        self.assertTrue(zone.file_path_label.wordWrap())
        self.assertEqual(zone.remove_button.text(), "STL entfernen")
        self.assertEqual(window.source_progress_bar.format(), "%p %")
        self.assertFalse(hasattr(window, "stl_info_button"))
        window.close()

    def test_ready_view_has_the_requested_responsive_card_order(self) -> None:
        window = self.window()
        self.assertIsInstance(window.geometry_group, SectionCard)
        self.assertIsInstance(window.stability_group, SectionCard)
        self.assertIsInstance(window.overhang_group, SectionCard)
        self.assertIsInstance(window.geometry_settings_group, SectionCard)
        grid = window.ready_grid
        window.resize(1400, 900)
        window.show()
        window.workflow.set_slicer_step_visible(True)
        window.workflow.source_validation_succeeded(
            "test.stl geprüft",
            analysis_complete=True,
        )
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        QTest.qWait(600)
        self.app.processEvents()
        self.assertTrue(grid.is_two_column())
        self.assertEqual(
            grid.grid.getItemPosition(grid.grid.indexOf(window.ready_left_column))[:2],
            (0, 0),
        )
        self.assertEqual(
            grid.grid.getItemPosition(grid.grid.indexOf(window.prediction_frame))[:2],
            (0, 1),
        )
        self.assertTrue(
            window.ready_left_column.isAncestorOf(window.timing_group)
        )
        self.assertTrue(
            window.ready_left_column.isAncestorOf(window.geometry_settings_group)
        )
        self.assertLess(window.timing_group.y(), window.geometry_group.y())
        self.assertEqual(window.geometry_split_layout.count(), 2)
        window.resize(800, 900)
        QTest.qWait(30)
        self.app.processEvents()
        self.assertFalse(grid.is_two_column())
        self.assertEqual(
            grid.grid.getItemPosition(grid.grid.indexOf(window.prediction_frame))[:2],
            (0, 0),
        )
        self.assertEqual(
            grid.grid.getItemPosition(grid.grid.indexOf(window.ready_left_column))[:2],
            (1, 0),
        )
        window.close()

    def test_settings_headers_show_only_the_section_name(self) -> None:
        window = self.window()
        for section in (window.timing_group, window.geometry_group,
                        window.stability_group, window.overhang_group,
                        window.geometry_settings_group):
            self.assertEqual(section.summary(), "")
        self.assertEqual(window.geometry_settings_group.title(), "Turmeinstellungen")
        self.assertFalse(window.timing_group.isCheckable())
        self.assertTrue(window.geometry_settings_group.isAncestorOf(window.timing_group))
        window.close()

    def test_reset_buttons_are_consistent_non_sticky_controls(self) -> None:
        window = self.window()
        buttons = [
            widget.reset_button for widget in window._setting_widgets.values()
        ] + [
            window.automatic_base_reset_button,
            window.output_root_reset_button,
        ]
        self.assertTrue(buttons)
        for button in buttons:
            self.assertEqual(button.objectName(), "settingResetButton")
            self.assertNotEqual(button.focusPolicy(), Qt.FocusPolicy.NoFocus)
        original = window.target_time_spin.value()
        window.target_time_spin.setValue(original + 4)
        window._setting_widgets["target_layer_time_s"].reset_button.click()
        self.assertEqual(window.target_time_spin.value(), original)
        stylesheet = window.styleSheet()
        self.assertIn("QPushButton#settingResetButton:hover", stylesheet)
        self.assertIn("QPushButton#settingResetButton:pressed", stylesheet)
        self.assertIn("QPushButton#settingResetButton:focus", stylesheet)
        window.close()

    def test_many_layer_errors_are_grouped_into_readable_lines(self) -> None:
        window = self.window()
        issues = tuple(
            FeasibilityIssue(
                code="EXPANSION_ANGLE_TOO_SMALL",
                message="Winkel reicht nicht aus",
                affected_layer_index=layer,
                affected_z_mm=layer * 0.2,
                related_setting_names=("maximum_expansion_angle_deg",),
                required_value=88.5,
                achievable_value=50.0,
            )
            for layer in range(20, 820)
        )
        grouped = window._group_feasibility_issues(issues)
        self.assertEqual(len(grouped), 1)
        summary = str(grouped[0]["summary"])
        self.assertIn("Betroffen sind 800 Layer", summary)
        self.assertIn(
            "Erforderlich sind bis zu 88,50°. Zulässig sind höchstens 70,00°.",
            summary,
        )
        self.assertNotIn(" · ", summary)
        window.close()

    def test_invalid_geometry_cannot_claim_that_the_target_is_reached(self) -> None:
        window = self.window()
        window.analysis_snapshot = SimpleNamespace(
            minimum_layer_time_s=4.0,
            maximum_print_z_mm=160.4,
        )
        window.tower_assessment = SimpleNamespace(
            target_layer_time_s=25.0,
            deficit_layer_count=34,
            tower_end_z_mm=160.58,
            tower_required=True,
        )
        window.profile_feasibility = ProfileFeasibilityAssessment(
            tower_required=True,
            feasible=False,
            estimated_minimum_combined_layer_time_s=30.0,
        )
        window._refresh_prediction()
        self.assertIn("nicht erreichbar", window.prediction_label.text())
        self.assertNotIn("Ziel voraussichtlich erreicht", window.prediction_label.text())
        self.assertEqual(window.prediction_frame.property("state"), "error")
        window.close()

    def test_preview_legend_is_plain_and_side_view_has_breathing_room(self) -> None:
        window = self.window()
        dialog = window.preview_dialog
        for label in (
            dialog.object_legend,
            dialog.tower_legend,
            dialog.bed_legend,
        ):
            style = label.styleSheet().casefold()
            self.assertNotIn("background", style)
            self.assertNotIn("border-radius", style)
        dialog.canvas.side_view()
        self.assertAlmostEqual(dialog.canvas.zoom, dialog.canvas.SIDE_VIEW_ZOOM)
        window.close()

    def test_footer_labels_stay_compact_and_success_clears_export_result(self) -> None:
        window = self.window()
        window.resize(760, 760)
        window._update_responsive_action_labels()
        self.assertEqual(
            window.reset_button.text(),
            "Standardwerte wiederherstellen",
        )
        self.assertEqual(window.reset_button.parent().objectName(), "footerMessageArea")
        self.assertEqual(window.export_button.text(), "Kühlturm exportieren")
        window.current_preview = SimpleNamespace()
        window.preview_state = PreviewState.CURRENT
        window._update_responsive_action_labels()
        self.assertEqual(window.preview_button.text(), "Kühlturm aktualisieren")
        window.current_preview = None

        output = self.root / "lauf" / "turm.stl"
        window._export_request_id = 7
        result = SimpleNamespace(
            output_mode=OutputMode.STL,
            calibrated=True,
            slicer_optimized=True,
            output_path=output,
            user_report_path=self.root / "lauf" / "export_summary.txt",
            technical_report_path=self.root / "lauf" / "export_report.json",
        )
        window._on_export_succeeded(7, result)
        self.assertFalse(window.result_label.text())
        self.assertFalse(window.result_label.toolTip())
        window.close()


if __name__ == "__main__":
    unittest.main()
