from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("COOLING_TOWER_DISABLE_SLICER_DISCOVERY", "1")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from cooling_tower.gui.generation_session import GenerationMode
from cooling_tower.gui.main_window import MainWindow
from cooling_tower.preview import PreviewState
from gui_lifecycle import dispose_test_widget
import test_preprocessor as fixture_module


class PreprocessorGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.fixture = fixture_module.PreprocessorTests()
        self.fixture.setUp()
        self.request = self.fixture.request()
        self.window = MainWindow(user_settings_path=self.fixture.root / "user.json",
            enable_update_check=False, enable_startup_slicer_discovery=False)
        self.controller = self.window.preprocessor_controller
        self.controller.service = self.fixture.service
        self.request_patch = patch.object(self.controller, "request", side_effect=lambda:
            replace(self.request, settings=self.window.preprocessor_panel.settings()))
        self.request_patch.start()
        self.window.show()
        workflow = self.window.workflow
        workflow.set_slicer_step_visible(True)
        workflow.source_validation_succeeded("model.stl", analysis_complete=True)
        workflow.slicer_succeeded("Testslicer")
        workflow.complete_preparation()
        self.app.processEvents()

    def tearDown(self):
        self.request_patch.stop()
        dispose_test_widget(self.window)
        self.app.processEvents()
        self.fixture.tearDown()

    def wait_for_result(self):
        if self.controller.job_id is None and self.controller.session.preview is None:
            self.window.preprocessor_panel.generate_button.click()
        end = time.monotonic() + 30
        while time.monotonic() < end:
            self.app.processEvents()
            if self.controller.job_id is None and self.controller.session.preview is not None:
                return self.controller.session.preview
            QTest.qWait(20)
        self.fail(self.window.preprocessor_panel.status.text())

    def test_third_card_generates_hollow_preview_and_exports_exact_gcode(self):
        self.window.preprocessor_generation_card.click()
        self.assertIs(self.window.generation_mode, GenerationMode.PREPROCESSOR)
        self.assertTrue(self.window.preprocessor_panel.isVisible())
        self.assertTrue(self.window.ready_grid.isHidden())
        self.assertTrue(self.window.manual_generation_panel.isHidden())
        self.assertIsNone(self.controller.job_id)
        self.assertTrue(self.window.preprocessor_panel.footer_widget.isVisible())
        result = self.wait_for_result()
        panel = self.window.preprocessor_panel
        self.assertTrue(panel.hollow_checkbox.isChecked())
        self.assertIs(panel.canvas.scene, result.scene)
        self.assertIs(self.controller.session.preview_state, PreviewState.CURRENT)
        self.assertTrue(panel.export_button.isEnabled())
        output = self.fixture.root / "export.gcode"
        with patch("cooling_tower.gui.preprocessor_panel.QFileDialog.getSaveFileName", return_value=(str(output), "")):
            panel.export_button.click()
        self.assertEqual(output.read_bytes(), result.gcode_path.read_bytes())

    def test_edit_discards_old_result_and_regenerates_from_preslice(self):
        self.window.select_generation_mode(GenerationMode.PREPROCESSOR)
        old = self.wait_for_result()
        old_path = old.gcode_path
        self.window.preprocessor_panel.inputs["target_layer_time_s"].setValue(25)
        self.assertFalse(old_path.exists())
        self.assertFalse(self.window.preprocessor_panel.export_button.isEnabled())
        QTest.qWait(750)
        self.assertIsNone(self.controller.job_id)
        self.assertIsNone(self.controller.session.preview)
        new = self.wait_for_result()
        self.assertGreater(new.total_wait_s, old.total_wait_s)
        self.assertTrue(self.request.prepared_source.matches_analysis_gcode())

    def test_method_switch_retains_result_but_source_invalidation_discards_it(self):
        self.window.select_generation_mode(GenerationMode.PREPROCESSOR)
        result = self.wait_for_result()
        self.window.select_generation_mode(GenerationMode.AUTOMATIC)
        self.assertTrue(self.window.preprocessor_panel.isHidden())
        self.window.select_generation_mode(GenerationMode.PREPROCESSOR)
        self.assertIs(self.controller.session.preview, result)
        self.controller.invalidate()
        self.assertFalse(result.gcode_path.exists())
        self.assertIsNone(self.window.preprocessor_panel.canvas.scene)
        self.assertFalse(self.window.preprocessor_panel.export_button.isEnabled())

    def test_manual_dimensions_enable_independently_and_reset(self):
        panel = self.window.preprocessor_panel
        for flag, name in (("automatic_height", "height_mm"), ("automatic_base", "base_width_mm"),
                ("automatic_diameter", "diameter_mm"), ("automatic_position", "center_x_mm"),
                ("automatic_wait_position", "wait_x_mm")):
            self.assertFalse(panel.inputs[name].isEnabled())
            panel.automatic[flag].setChecked(False)
            self.assertTrue(panel.inputs[name].isEnabled())
        self.assertTrue(panel.inputs["center_y_mm"].isEnabled())
        self.assertTrue(panel.inputs["wait_y_mm"].isEnabled())
        panel.hollow_checkbox.setChecked(False)
        panel.reset()
        self.assertTrue(panel.hollow_checkbox.isChecked())
        self.assertTrue(all(checkbox.isChecked() for checkbox in panel.automatic.values()))

    def test_cancel_prevents_export_and_all_navigation_while_busy(self):
        self.window.select_generation_mode(GenerationMode.PREPROCESSOR)
        self.controller.generate()
        self.window._refresh_workflow_navigation_actions()
        self.assertFalse(self.window.preprocessor_method_button.isEnabled())
        self.assertFalse(self.window.automatic_method_button.isEnabled())
        self.controller.cancel()
        end = time.monotonic() + 10
        while self.controller.job_id is not None and time.monotonic() < end:
            self.app.processEvents()
            QTest.qWait(20)
        self.assertIsNone(self.controller.job_id)
        self.assertIsNone(self.controller.session.preview)
        self.assertFalse(self.window.preprocessor_panel.export_button.isEnabled())

    def test_critical_placement_error_is_visible_and_blocks_export(self):
        self.window.select_generation_mode(GenerationMode.PREPROCESSOR)
        self.wait_for_result()
        panel = self.window.preprocessor_panel
        panel.automatic["automatic_position"].setChecked(False)
        panel.inputs["center_x_mm"].setValue(105)
        panel.inputs["center_y_mm"].setValue(105)
        self.controller.generate()
        end = time.monotonic() + 10
        while self.controller.job_id is not None and time.monotonic() < end:
            self.app.processEvents()
            QTest.qWait(20)
        self.assertTrue(panel.error_label.isVisible())
        self.assertIn("Export gesperrt", panel.error_label.text())
        self.assertFalse(panel.export_button.isEnabled())
        self.assertIsNone(self.controller.session.preview)

    def test_changed_preslice_during_export_removes_export_permission(self):
        self.window.select_generation_mode(GenerationMode.PREPROCESSOR)
        self.wait_for_result()
        self.request.prepared_source.analysis_gcode_path.write_text("changed")
        with patch("cooling_tower.gui.preprocessor_panel.QFileDialog.getSaveFileName", return_value=(str(self.fixture.root / "invalid.gcode"), "")):
            self.window.preprocessor_panel.export_button.click()
        self.assertTrue(self.window.preprocessor_panel.error_label.isVisible())
        self.assertFalse(self.window.preprocessor_panel.export_button.isEnabled())

    def test_top_view_preserves_x_right_and_y_up(self):
        self.window.select_generation_mode(GenerationMode.PREPROCESSOR)
        self.wait_for_result()
        panel = self.window.preprocessor_panel
        panel.top_view()
        from cooling_tower.preview import Point3D
        origin = panel.canvas._raw_project(Point3D(0, 0, 0))
        x = panel.canvas._raw_project(Point3D(10, 0, 0))
        y = panel.canvas._raw_project(Point3D(0, 10, 0))
        self.assertGreater(x[0], origin[0])
        self.assertLess(y[1], origin[1])

    def test_preview_travel_toggle_keeps_generated_gcode_and_marks_free_park(self):
        self.window.select_generation_mode(GenerationMode.PREPROCESSOR)
        result = self.wait_for_result()
        panel = self.window.preprocessor_panel
        self.assertIsNotNone(result.scene.wait_position_xy_mm)
        self.assertTrue(result.scene.travel_segments)
        self.assertTrue(panel.canvas._prepare_line_frame().travel_blocks)
        panel.show_travel_checkbox.setChecked(False)
        self.assertFalse(panel.canvas._prepare_line_frame().travel_blocks)
        self.assertIs(self.controller.session.preview, result)
        self.assertIsNone(self.controller.job_id)
        self.assertTrue(panel.export_button.isEnabled())
        panel.show_travel_checkbox.setChecked(True)
        self.assertTrue(panel.canvas._prepare_line_frame().travel_blocks)

    def test_switch_from_automatic_dimensions_adopts_calculated_values(self):
        self.window.select_generation_mode(GenerationMode.PREPROCESSOR)
        result = self.wait_for_result()
        panel = self.window.preprocessor_panel
        self.assertAlmostEqual(panel.inputs["height_mm"].value(), result.height_mm, places=2)
        panel.automatic["automatic_height"].setChecked(False)
        self.assertAlmostEqual(panel.settings().height_mm, result.height_mm, places=2)

    def test_footer_actions_and_reset_hints_follow_requested_states(self):
        panel = self.window.preprocessor_panel
        self.window.resize(1600, 1100)
        self.window.select_generation_mode(GenerationMode.PREPROCESSOR)
        self.app.processEvents()
        self.assertTrue(panel.footer_widget.isVisible())
        self.assertTrue(panel.columns.is_two_column())
        self.assertTrue(panel.footer_columns.is_two_column())
        self.assertFalse(panel.cancel_button.isVisible())
        self.assertFalse(panel.export_button.isVisible())
        self.assertTrue(panel.generate_button.isVisible())
        self.assertEqual(panel.generate_button.objectName(), "previewButton")
        self.assertEqual(panel.export_button.objectName(), "exportButton")
        for name, info in panel.info_buttons.items():
            self.assertEqual(info.objectName(), "settingInfoButton")
            self.assertIn("<b>", info.toolTip(), name)
            self.assertIn("&#8226;", info.toolTip(), name)
            self.assertEqual(panel.reset_buttons[name].objectName(), "settingResetButton")
        panel.automatic["automatic_base"].setChecked(False)
        panel.inputs["base_width_mm"].setValue(60)
        row = panel.rows["base_width_mm"]
        self.assertGreater(row.layout().getItemPosition(row.layout().indexOf(row.reset_button))[1],
            row.layout().getItemPosition(row.layout().indexOf(panel.automatic["automatic_base"]))[1])
        self.assertTrue(row.reset_button.isEnabled())
        row.reset_button.click()
        self.assertTrue(panel.automatic["automatic_base"].isChecked())
        self.assertEqual(panel.settings().base_width_mm, 25)
        self.assertIsNone(self.controller.job_id)
        self.assertEqual(set(panel.camera_buttons), {"three_quarter", "front", "side", "top", "fit"})
        result = self.wait_for_result()
        self.app.processEvents()
        self.assertTrue(panel.export_button.isVisible())
        self.assertFalse(panel.cancel_button.isVisible())
        self.assertLess(panel.generate_button.x(), panel.export_button.x())
        self.assertIs(self.controller.session.preview, result)

    def test_basic_advanced_and_view_resets_do_not_start_generation(self):
        panel = self.window.preprocessor_panel
        self.window.select_generation_mode(GenerationMode.PREPROCESSOR)
        panel.advanced_group.setChecked(True)
        self.app.processEvents()
        self.app.processEvents()
        for row in panel.rows.values():
            self.assertGreaterEqual(row.height(), row.editor.height())
        visible_rows = [panel.rows[name] for name in ("wall_count", "edge_clearance_mm", "wait_clearance_mm", "print_speed_mm_s")]
        for first, second in zip(visible_rows, visible_rows[1:]):
            self.assertGreaterEqual(second.y(), first.y()+first.height())
        panel.hollow_checkbox.setChecked(False)
        panel.reset_buttons["hollow_tower"].click()
        self.assertTrue(panel.hollow_checkbox.isChecked())
        panel.wall_count_spin.setValue(5)
        panel.reset_buttons["wall_count"].click()
        self.assertEqual(panel.wall_count_spin.value(), 2)
        panel.inputs["z_hop_mm"].setValue(2)
        panel.reset_buttons["z_hop_mm"].click()
        self.assertEqual(panel.inputs["z_hop_mm"].value(), .6)
        panel.show_travel_checkbox.setChecked(False)
        panel.reset_buttons["show_travel"].click()
        self.assertTrue(panel.show_travel_checkbox.isChecked())
        self.assertIsNone(self.controller.job_id)
        self.window.resize(760, 850)
        self.app.processEvents()
        self.assertFalse(panel.columns.is_two_column())
        self.assertFalse(panel.footer_columns.is_two_column())

    def test_request_freezes_selected_profile_without_mutating_the_original(self):
        from cooling_tower.slicers import EffectiveProfile
        from types import SimpleNamespace
        self.request_patch.stop()
        profile = EffectiveProfile(self.request.profile.installation, None, None, (), effective_values={"nested": [1]})
        self.window.profile_match_result = SimpleNamespace(selected=SimpleNamespace(effective_profile=profile), user_confirmed=True)
        self.window.prepared_analysis_source = self.request.prepared_source
        self.window.analysis_snapshot = self.request.snapshot
        request = self.controller.request()
        profile.effective_values["nested"].append(2)
        self.assertEqual(request.profile.effective_values["nested"], [1])
        self.window.profile_match_result = None


if __name__ == "__main__":
    unittest.main()
