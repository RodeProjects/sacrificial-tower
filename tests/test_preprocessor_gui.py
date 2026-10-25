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
        self.window.export_roots["preprocessor"] = str(self.fixture.root / "exports" / "preprocessor")
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
        panel.export_button.click()
        exported = self.controller.session.export_result
        self.assertIsNotNone(exported, panel.status.text())
        self.assertEqual(exported.output_path.read_bytes(), result.gcode_path.read_bytes())
        self.assertEqual(exported.run_directory.parent, self.window.export_directory(GenerationMode.PREPROCESSOR))
        self.assertTrue(exported.report_path.is_file())
        self.assertTrue(exported.user_report_path.is_file())
        self.assertTrue(panel.export_actions.isVisible())
        self.assertTrue(self.window.export_success_dialog.isVisible())
        self.assertIn("G-Code", self.window.export_success_usage_label.text())
        self.assertNotIn("Turm-STL manuell", self.window.export_success_usage_label.text())
        with patch("cooling_tower.gui.main_window.open_directory") as opened:
            panel.open_output_button.click()
            opened.assert_called_with(self.window.export_directory(GenerationMode.PREPROCESSOR).resolve())
            panel.open_last_button.click()
            opened.assert_called_with(exported.run_directory)
        self.window.export_success_dialog.close()
        panel.open_report_button.click()
        self.assertTrue(self.window.export_success_dialog.isVisible())
        self.window.export_success_dialog.close()
        from PySide6.QtCore import QPoint
        for width in (1600, 1200, 1100, 900, 760):
            self.window.resize(width, 1000)
            QTest.qWait(30)
            buttons = (panel.open_output_button, panel.open_last_button, panel.open_report_button,
                panel.generate_button, panel.export_button)
            for button in buttons:
                self.assertLessEqual(button.mapTo(self.window, QPoint(button.width(), 0)).x(), self.window.width())
        self.window.select_generation_mode(GenerationMode.AUTOMATIC)
        self.assertIsNone(self.window._last_export_report_result)
        self.window.select_generation_mode(GenerationMode.PREPROCESSOR)
        self.assertIs(self.window._last_export_report_result, exported)

    def test_edit_discards_old_result_and_regenerates_from_preslice(self):
        self.window.select_generation_mode(GenerationMode.PREPROCESSOR)
        old = self.wait_for_result()
        old_path = old.gcode_path
        self.window.preprocessor_panel.automatic["automatic_target_time"].setChecked(False)
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

    def test_automatic_controls_precede_editors_and_hollow_label_precedes_checkbox(self):
        panel = self.window.preprocessor_panel
        self.window.resize(1600, 1000)
        self.window.select_generation_mode(GenerationMode.PREPROCESSOR)
        panel.advanced_group.setChecked(True)
        panel.automatic["automatic_position"].setChecked(False)
        panel.automatic["automatic_wait_position"].setChecked(False)
        self.app.processEvents()
        for flag, name in (("automatic_height", "height_mm"), ("automatic_diameter", "diameter_mm"),
                ("automatic_base", "base_width_mm"), ("automatic_position", "center_x_mm"),
                ("automatic_wait_position", "wait_x_mm")):
            row = panel.rows[name]
            grid = row.layout()
            checkbox = panel.automatic[flag]
            self.assertEqual(checkbox.text(), "")
            auto_label = grid.itemAtPosition(0, 2).widget()
            self.assertEqual(auto_label.text(), "Automatisch")
            self.assertLess(row.label.geometry().right(), auto_label.x())
            self.assertLess(auto_label.geometry().right(), checkbox.x())
            self.assertLess(checkbox.geometry().right(), row.editor.x())
            self.assertLess(row.editor.geometry().right(), row.reset_button.x())
        hollow_row = panel.hollow_checkbox.parentWidget()
        layout = hollow_row.layout()
        label = layout.itemAt(1).widget()
        self.assertEqual(label.text(), "Hohler Turm")
        self.assertLess(label.geometry().right(), panel.hollow_checkbox.x())
        self.assertGreater(panel.reset_buttons["hollow_tower"].x(), panel.hollow_checkbox.x())

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
        from itertools import product
        self.window.select_generation_mode(GenerationMode.PREPROCESSOR)
        result = self.wait_for_result()
        panel = self.window.preprocessor_panel
        self.assertIsNotNone(result.scene.wait_position_xy_mm)
        self.assertTrue(result.scene.wait_travel_segments)
        self.assertTrue(result.scene.tower_travel_segments)
        initial = panel.canvas._prepare_line_frame()
        self.assertFalse(initial.travel_blocks)
        self.assertIsNotNone(initial.wait_position)
        gcode = result.gcode_path.read_bytes()
        keys = set()
        for marker, wait, tower in product((False, True), repeat=3):
            panel.view_checkboxes["show_wait_position"].setChecked(marker)
            panel.view_checkboxes["show_wait_travel"].setChecked(wait)
            panel.view_checkboxes["show_tower_travel"].setChecked(tower)
            frame = panel.canvas._prepare_line_frame()
            keys.add(frame.key)
            self.assertEqual(frame.wait_position is not None, marker)
            self.assertEqual(bool(frame.wait_travel_blocks), wait)
            self.assertEqual(bool(frame.tower_travel_blocks), tower)
            self.assertEqual(frame.object_blocks, initial.object_blocks)
            self.assertEqual(frame.tower_blocks, initial.tower_blocks)
            self.assertTrue(all(panel.preview_group.isAncestorOf(box) for box in panel.view_checkboxes.values()))
        self.assertEqual(len(keys), 8)
        self.assertEqual(result.gcode_path.read_bytes(), gcode)
        self.assertIs(self.controller.session.preview, result)
        self.assertIsNone(self.controller.job_id)
        self.assertTrue(panel.export_button.isEnabled())
        # Camera fitting stays stable in the object-focused view as well.
        panel.three_quarter_view()
        before = panel.canvas._fit_parameters()
        panel.view_checkboxes["show_wait_position"].setChecked(False)
        panel.view_checkboxes["show_wait_travel"].setChecked(False)
        panel.view_checkboxes["show_tower_travel"].setChecked(False)
        self.assertEqual(panel.canvas._fit_parameters(), before)

    def test_switch_from_automatic_dimensions_adopts_calculated_values(self):
        self.window.select_generation_mode(GenerationMode.PREPROCESSOR)
        result = self.wait_for_result()
        panel = self.window.preprocessor_panel
        self.assertAlmostEqual(panel.inputs["height_mm"].value(), result.height_mm, places=2)
        panel.automatic["automatic_height"].setChecked(False)
        self.assertAlmostEqual(panel.settings().height_mm, result.height_mm, places=2)

    def test_automatic_fields_are_disabled_and_show_only_current_calculated_values(self):
        self.window.select_generation_mode(GenerationMode.PREPROCESSOR)
        panel = self.window.preprocessor_panel
        fields = ("height_mm", "diameter_mm", "base_width_mm", "center_x_mm", "center_y_mm", "wait_x_mm", "wait_y_mm")
        for name in fields:
            self.assertFalse(panel.inputs[name].isEnabled())
            self.assertEqual(panel.inputs[name].lineEdit().text(), "—")
        result = self.wait_for_result()
        values = {"height_mm": result.height_mm, "diameter_mm": result.diameter_mm,
            "base_width_mm": result.base_width_mm,
            "center_x_mm": result.scene.tower_center_xy_mm[0], "center_y_mm": result.scene.tower_center_xy_mm[1],
            "wait_x_mm": result.scene.wait_position_xy_mm[0], "wait_y_mm": result.scene.wait_position_xy_mm[1]}
        for name, value in values.items():
            spin = panel.inputs[name]
            self.assertFalse(spin.isEnabled())
            self.assertEqual(spin.lineEdit().text(), spin.locale().toString(value, "f", 2))
        panel.inputs["target_layer_time_s"].setValue(25)
        self.assertIsNone(self.controller.session.preview)
        for name in fields:
            self.assertEqual(panel.inputs[name].lineEdit().text(), "—")
        panel.automatic["automatic_diameter"].setChecked(False)
        self.assertTrue(panel.inputs["diameter_mm"].isEnabled())
        self.assertNotEqual(panel.inputs["diameter_mm"].lineEdit().text(), "—")

    def test_no_tower_displays_zero_dimensions_and_no_invented_wait_position(self):
        self.window.select_generation_mode(GenerationMode.PREPROCESSOR)
        panel = self.window.preprocessor_panel
        panel.automatic["automatic_target_time"].setChecked(False)
        panel.inputs["target_layer_time_s"].setValue(.1)
        result = self.wait_for_result()
        self.assertEqual(result.height_mm, 0)
        for name in ("height_mm", "diameter_mm", "base_width_mm"):
            self.assertEqual(panel.inputs[name].lineEdit().text(), "0,00")
            self.assertFalse(panel.inputs[name].isEnabled())
        for name in ("center_x_mm", "center_y_mm", "wait_x_mm", "wait_y_mm"):
            self.assertEqual(panel.inputs[name].lineEdit().text(), "—")

    def test_footer_actions_and_reset_hints_follow_requested_states(self):
        panel = self.window.preprocessor_panel
        self.window.resize(2200, 1100)
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
        panel.wall_count_spin.setValue(3)
        panel.reset_buttons["wall_count"].click()
        self.assertEqual(panel.wall_count_spin.value(), 2)
        panel.inputs["z_hop_mm"].setValue(2)
        panel.reset_buttons["z_hop_mm"].click()
        self.assertEqual(panel.inputs["z_hop_mm"].value(), .6)
        for name, default in (("show_wait_position", True), ("show_wait_travel", False), ("show_tower_travel", False)):
            panel.view_checkboxes[name].setChecked(not default)
            self.assertTrue(panel.reset_buttons[name].isEnabled())
            panel.reset_buttons[name].click()
            self.assertEqual(panel.view_checkboxes[name].isChecked(), default)
            self.assertFalse(panel.reset_buttons[name].isEnabled())
        self.assertIsNone(self.controller.job_id)
        self.window.resize(760, 850)
        self.app.processEvents()
        self.assertFalse(panel.columns.is_two_column())
        self.assertFalse(panel.footer_columns.is_two_column())

    def test_preprocessor_has_edge_attached_cards_and_draggable_resizing_preview(self):
        from PySide6.QtCore import QPoint, Qt
        self.window.resize(2000, 1100)
        self.window.select_generation_mode(GenerationMode.PREPROCESSOR)
        panel = self.window.preprocessor_panel
        for _ in range(5):
            self.app.processEvents()
        self.assertEqual(self.window.content_layout.contentsMargins().left(), 0)
        self.assertEqual(self.window.content_layout.contentsMargins().right(), 0)
        self.assertEqual(panel.settings_column.layout().spacing(), 0)
        for card in (panel.input_group, panel.advanced_group, panel.preview_group):
            self.assertTrue(card.property("edgeAttached"))
        splitter = panel.columns.splitter
        handle = splitter.handle(1)
        self.assertEqual(handle.cursor().shape(), Qt.CursorShape.SplitHCursor)
        before = panel.canvas.width()
        before_height = panel.canvas.height()
        start = handle.rect().center()
        QTest.mousePress(handle, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(handle, start - QPoint(120, 0), delay=20)
        QTest.mouseRelease(handle, Qt.MouseButton.LeftButton, pos=start - QPoint(120, 0))
        for _ in range(4):
            self.app.processEvents()
        self.assertGreater(panel.canvas.width(), before + 50)
        self.assertGreater(panel.canvas.height(), before_height + 30)
        ratio = splitter.sizes()[0] / sum(splitter.sizes())
        self.window.resize(760, 850)
        for _ in range(4):
            self.app.processEvents()
        self.assertFalse(panel.columns.is_two_column())
        self.window.resize(2000, 1100)
        for _ in range(4):
            self.app.processEvents()
        self.assertTrue(panel.columns.is_two_column())
        self.assertAlmostEqual(splitter.sizes()[0] / sum(splitter.sizes()), ratio, delta=.02)
        QTest.mouseDClick(splitter.handle(1), Qt.MouseButton.LeftButton)
        for _ in range(6):
            self.app.processEvents()
        self.assertLessEqual(abs(splitter.sizes()[0] - splitter.sizes()[1]), 1)
        self.assertEqual(panel.columns._ratio, .5)
        for width in (1999, 2001, 2000):
            self.window.resize(width, 1100)
            for _ in range(6):
                self.app.processEvents()
            handle = splitter.handle(1)
            self.assertEqual(handle.x() + handle.rect().center().x(), splitter.rect().center().x())
            self.assertEqual(panel.columns._ratio, .5)
        self.assertIsNone(self.controller.job_id)

    def test_wall_count_defaults_range_and_solid_disables_wall_control(self):
        self.window.select_generation_mode(GenerationMode.PREPROCESSOR)
        panel = self.window.preprocessor_panel
        self.assertEqual((panel.wall_count_spin.minimum(), panel.wall_count_spin.maximum(), panel.wall_count_spin.value()), (1, 3, 2))
        panel.hollow_checkbox.setChecked(False)
        self.assertFalse(panel.wall_count_spin.isEnabled())
        panel.hollow_checkbox.setChecked(True)
        self.assertTrue(panel.wall_count_spin.isEnabled())

    def test_splitter_stops_before_settings_labels_or_preview_controls_wrap(self):
        self.window.resize(2400, 1100)
        self.window.select_generation_mode(GenerationMode.PREPROCESSOR)
        panel = self.window.preprocessor_panel
        panel.advanced_group.setChecked(True)
        for _ in range(6):
            self.app.processEvents()
        self.assertTrue(panel.columns.is_two_column())
        splitter = panel.columns.splitter
        for position in (0, splitter.width()):
            splitter.moveSplitter(position, 1)
            for _ in range(6):
                self.app.processEvents()
            self.assertGreaterEqual(splitter.sizes()[0], panel.settings_column.minimumSizeHint().width())
            self.assertGreaterEqual(splitter.sizes()[1], panel.preview_group.minimumSizeHint().width())
            for row in (row for row in panel.rows.values() if row.isVisible()):
                self.assertFalse(row.label.wordWrap())
                self.assertGreaterEqual(row.label.width(), row.label.fontMetrics().horizontalAdvance(row.label.text()))
            for button in panel.camera_buttons.values():
                self.assertGreaterEqual(button.width(), button.minimumSizeHint().width())
        panel.columns.center_columns()
        for _ in range(6):
            self.app.processEvents()
        handle = splitter.handle(1)
        self.assertEqual(handle.x() + handle.rect().center().x(), splitter.rect().center().x())

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
