from pathlib import Path
from dataclasses import replace
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import test_preprocessor_gui as fixture_module
from test_preprocessor import make_gcode
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtGui import QFont
from cooling_tower.gui.generation_session import GenerationMode
from cooling_tower.preprocessor_safety import ExclusionRect


class PreprocessorUpgradeGuiTests(unittest.TestCase):
    def test_clearance_display_is_removed_without_changing_safety_metadata(self):
        result = self.harness.wait_for_result()
        self.assertNotIn("show_clearance", self.panel.view_checkboxes)
        self.assertFalse(hasattr(self.panel.canvas, "set_clearance_visible"))
        self.assertGreater(result.printhead.radius_mm, 0)
        self.assertTrue(result.collision_notes)

    @classmethod
    def setUpClass(cls):
        fixture_module.PreprocessorGuiTests.setUpClass()
        cls.app = fixture_module.PreprocessorGuiTests.app

    def setUp(self):
        self.harness = fixture_module.PreprocessorGuiTests()
        self.harness.setUp()
        self.window = self.harness.window
        self.panel = self.window.preprocessor_panel
        self.controller = self.window.preprocessor_controller
        self.window.resize(1700, 1100)
        self.window.select_generation_mode(GenerationMode.PREPROCESSOR)
        self.app.processEvents()

    def tearDown(self):
        self.harness.tearDown()

    def test_profile_automatic_values_and_manual_adoption(self):
        self.assertFalse(self.panel.timing_panel.isVisible())
        self.panel.automatic["automatic_target_time"].setChecked(True)
        self.harness.request.profile.effective_values.update({"slow_down_layer_time": 18,
            "outer_wall_speed": 40, "travel_speed": 150, "retraction_length": 1.2, "retraction_speed": 32})
        self.panel.set_profile_values(self.harness.request.profile.effective_values)
        result = self.harness.wait_for_result()
        self.assertTrue(self.panel.timing_panel.isVisible())
        self.assertEqual(result.effective_settings.target_layer_time_s, 18)
        for name in ("target_layer_time_s", "print_speed_mm_s", "travel_speed_mm_s", "retract_mm", "retract_speed_mm_s"):
            self.assertFalse(self.panel.inputs[name].isEnabled())
            self.assertNotEqual(self.panel.inputs[name].lineEdit().text(), "—")
        self.panel.automatic["automatic_target_time"].setChecked(False)
        self.assertEqual(self.panel.settings().target_layer_time_s, 18)
        self.assertIsNone(self.controller.session.preview)
        self.assertFalse(self.panel.time_chart.isEnabled())
        self.assertFalse(self.panel.timing_panel.isVisible())
        self.panel.reset_field("target_layer_time_s")
        self.assertFalse(self.panel.automatic["automatic_target_time"].isChecked())
        self.assertEqual(self.panel.settings().target_layer_time_s, 10)

    def test_scale_normalization_control_preserves_layer_data_and_resets_to_dynamic_default(self):
        result = self.harness.wait_for_result()
        panel, chart = self.panel, self.panel.time_chart
        count = len(result.layer_times_s)
        original = (200,)+(2,)*(count-1)
        zero = (0,)*count
        synthetic = replace(result, layer_times_s=original, original_layer_times_s=original,
            added_motion_times_s=zero, layer_waits_s=zero)
        gcode = result.gcode_path.read_bytes()
        panel.show_timing(synthetic)
        self.assertTrue(panel.normalized_scale.isChecked())
        self.assertTrue(chart.normalized)
        self.assertEqual(chart.original, original)
        self.assertAlmostEqual(chart._maximum, 10*1.05)
        layout = panel.timing_panel.layout()
        row = panel.normalized_scale.parentWidget()
        self.assertEqual(layout.indexOf(row), layout.indexOf(panel.logarithmic_scale)+1)
        self.assertEqual(panel.normalization_info.objectName(), "settingInfoButton")
        self.assertIn("<b>Zeitskala normalisieren</b>", panel.normalization_info.toolTip())
        self.assertIn("Layer 1", panel.normalization_info.toolTip())
        panel.select_layer(1)
        self.assertEqual(chart.selected, 1)
        self.assertIn("200.00 s", panel.layer_details.text())
        panel.normalized_scale.setChecked(False)
        self.assertFalse(chart.normalized)
        self.assertAlmostEqual(chart._maximum, 200*1.05)
        panel.logarithmic_scale.setChecked(False)
        panel.preview_reset.click()
        self.assertTrue(panel.normalized_scale.isChecked())
        self.assertTrue(chart.normalized)
        self.assertTrue(panel.logarithmic_scale.isChecked())
        later_peak = (2, 200)+(2,)*(count-2)
        panel.show_timing(replace(synthetic, layer_times_s=later_peak, original_layer_times_s=later_peak))
        self.assertFalse(panel.normalized_scale.isChecked())
        panel.normalized_scale.setChecked(True)
        panel.preview_reset.click()
        self.assertFalse(panel.normalized_scale.isChecked())
        self.assertFalse(chart.normalized)
        self.assertEqual(result.gcode_path.read_bytes(), gcode)
        self.assertIs(self.controller.session.preview, result)
        self.assertIsNone(self.controller.job_id)

    def test_positions_share_one_automatic_control_and_editor_button(self):
        panel = self.panel
        self.assertTrue(panel.positions_automatic.isChecked())
        self.assertFalse(panel.positions_button.isEnabled())
        self.assertEqual(panel.positions_button.height(), 36)
        self.assertEqual(panel.positions_button.text(), "Positionen bearbeiten")
        row = panel.positions_button.parentWidget()
        self.assertTrue(row.isAncestorOf(panel.positions_automatic))
        layout = row.layout()
        label, auto_label = layout.itemAt(1).widget(), layout.itemAt(3).widget()
        self.assertEqual(label.text(), "Turm- und Warteposition")
        self.assertGreaterEqual(auto_label.x()-label.x()-label.fontMetrics().horizontalAdvance(label.text()), 30)
        self.assertLess(auto_label.geometry().right(), panel.positions_automatic.x())
        self.assertLess(panel.positions_automatic.geometry().right(), panel.positions_button.x())
        panel.positions_automatic.setChecked(False)
        self.assertTrue(panel.positions_button.isEnabled())
        self.assertFalse(panel.settings().automatic_position)
        self.assertFalse(panel.settings().automatic_wait_position)
        self.assertIn("Warteplatz", panel.info_buttons["positions"].toolTip())
        QTest.mouseClick(panel.positions_button, Qt.MouseButton.LeftButton)
        self.assertIsNotNone(self.controller.position_dialog)
        self.controller.position_dialog.reject()
        panel.positions_automatic.setChecked(True)
        self.assertTrue(panel.settings().automatic_position)
        self.assertTrue(panel.settings().automatic_wait_position)
        self.assertFalse(panel.positions_button.isEnabled())
        for name in ("center_x_mm", "center_y_mm", "wait_x_mm", "wait_y_mm"):
            self.assertTrue(panel.inputs[name].isHidden())
            self.assertNotIn(name, panel.rows)

    def test_reenabling_position_automation_restores_compact_row_spacing(self):
        panel = self.panel
        for width in (1900, 850):
            self.window.resize(width, 1000)
            for _ in range(8):
                self.app.processEvents()
            row = panel.positions_button.parentWidget()
            original_geometry = row.geometry()
            for _ in range(2):
                panel.positions_automatic.setChecked(False)
                for _ in range(8):
                    self.app.processEvents()
                self.assertEqual(row.geometry(), original_geometry)
                panel.positions_automatic.setChecked(True)
                for _ in range(8):
                    self.app.processEvents()
                self.assertEqual(row.geometry(), original_geometry)

    def test_unknown_head_warning_survives_error_and_new_bed_clears_zones(self):
        values = dict(self.harness.request.profile.effective_values)
        values.pop("extruder_clearance_height")
        values["bed_exclude_area"] = ["190x10", "200x10", "200x20", "190x20"]
        self.panel.set_profile_values(values)
        self.assertIn("unvollständig", self.panel.safety_hint.text())
        self.controller.critical_error("Kein sicherer Platz")
        self.assertIn("unvollständig", self.panel.safety_hint.text())
        profile, prepared = self.harness.request.profile, self.harness.request.prepared_source
        self.controller._sync_context(profile, prepared)
        self.panel.exclusions = (ExclusionRect(150, 20, 170, 40),)
        profile.effective_values["bed_shape"] = ["0x0", "250x0", "250x250", "0x250"]
        self.controller._sync_context(profile, prepared)
        self.assertEqual(self.panel.exclusions, ())

    def test_layer_times_use_flat_panel_and_remain_reachable_after_toggling(self):
        self.harness.wait_for_result()
        panel, scroll = self.panel, self.window.settings_scroll
        for width in (1794, 1384, 850):
            with self.subTest(width=width):
                self.window.resize(width, 900)
                panel.timing_toggle.setChecked(False)
                QTest.qWait(80)
                panel.timing_toggle.setChecked(True)
                QTest.qWait(80)
                opened_range = scroll.verticalScrollBar().maximum()
                self.assertEqual(panel.timing_panel.height(), panel.preview_view.height())
                required_bottom = panel.mapTo(scroll.widget(), QPoint(0, panel.minimumSizeHint().height())).y()
                self.assertGreaterEqual(scroll.widget().height(), required_bottom)
                for widget in (panel.time_chart, panel.time_legend, panel.layer_spin, panel.layer_details):
                    # QAbstractSpinBox proxies focus to its inner line edit;
                    # ensureWidgetVisible may expose only that editor. Check
                    # the complete control rectangle against the scroll range.
                    bottom = widget.mapTo(scroll.widget(), QPoint(0, widget.height()))
                    scroll.ensureVisible(bottom.x(), bottom.y(), 0, 0)
                    top_point = widget.mapTo(scroll.widget(), QPoint())
                    scroll.ensureVisible(top_point.x(), top_point.y(), 0, 0)
                    self.app.processEvents()
                    top = widget.mapTo(scroll.viewport(), QPoint()).y()
                    self.assertGreaterEqual(top, 0)
                    self.assertLessEqual(top + widget.height(), scroll.viewport().height())
                panel.timing_toggle.setChecked(False)
                QTest.qWait(80)
                self.assertFalse(panel.time_chart.isVisible())

    def test_chart_sits_right_of_complete_preview_and_legend_has_compact_columns(self):
        self.window.resize(2400, 1200)
        panel = self.panel
        QTest.qWait(80)
        initial_width = panel.canvas.width()
        self.harness.wait_for_result()
        self.assertTrue(panel.timing_toggle.isChecked())
        panel.timing_toggle.setChecked(True)
        QTest.qWait(100)
        self.assertLess(panel.canvas.width(), initial_width)
        self.assertGreater(panel.timing_panel.x(), panel.preview_view.geometry().right())
        self.assertLess(panel.view_controls.geometry().right(), panel.legend.x())
        chart, legend = panel.time_chart, panel.time_legend
        self.assertGreater(legend.y(), chart.geometry().bottom())
        self.assertFalse(hasattr(panel, "summary"))
        self.assertFalse(hasattr(panel, "layer_slider"))
        self.assertEqual(panel.timing_panel.height(), panel.preview_view.height())
        self.assertTrue(panel.preview_view.isAncestorOf(panel.preview_details))
        labels = panel.legend.labels[:3]
        points = [label.mapTo(panel.legend, QPoint()) for label in labels]
        self.assertEqual(len({point.x() for point in points}), 1)
        self.assertEqual([point.y() for point in points], sorted(point.y() for point in points))
        second = [label.mapTo(panel.legend, QPoint()) for label in panel.legend.labels[3:]]
        self.assertEqual([point.y() for point in points], [point.y() for point in second])
        first_right = max(label.mapTo(panel.legend, QPoint()).x()+label.width() for label in panel.legend.labels[:3])
        self.assertEqual(panel.legend.swatches[3].mapTo(panel.legend, QPoint()).x()-first_right, 15)
        self.assertFalse(hasattr(panel, "all_layers"))
        self.assertFalse(hasattr(panel.timing_panel, "header"))
        self.assertEqual(panel.timing_toggle.width(), panel.timing_toggle.height())
        self.assertEqual(panel.timing_toggle.height(), panel.camera_buttons["fit"].height())
        self.assertGreater(panel.timing_toggle.x(), panel.camera_buttons["fit"].geometry().right())
        panel.clear_timing()
        QTest.qWait(80)
        self.assertFalse(panel.timing_panel.isVisible())
        self.assertGreater(panel.canvas.width(), initial_width-20)

    def test_chart_axis_handle_and_keyboard_filter_exact_layer_and_travels(self):
        result = self.harness.wait_for_result()
        panel, canvas = self.panel, self.panel.canvas
        panel.timing_toggle.setChecked(True)
        QTest.qWait(100)
        camera, fit = canvas.camera_state(), canvas._fit_parameters()
        rect = panel.time_chart.plot_rect()
        pos = QPointF(rect.right(), panel.time_chart.layer_y(3)).toPoint()
        QTest.mouseClick(panel.time_chart, Qt.MouseButton.LeftButton, pos=pos)
        self.assertEqual(panel.layer_spin.value(), 3)
        self.assertEqual(canvas._layer_z, result.layer_heights_mm[2])
        selected = canvas._layer_segments(result.scene.object_segments)
        self.assertTrue(selected)
        self.assertTrue(all(abs(segment.end.z - result.layer_heights_mm[2]) < .001 for segment in selected))
        selected_travels = canvas._layer_segments(result.scene.wait_travel_segments, result.scene.wait_travel_layer_indices)
        self.assertTrue(selected_travels)
        self.assertLess(len(selected_travels), len(result.scene.wait_travel_segments))
        self.assertEqual(canvas.camera_state(), camera)
        self.assertEqual(canvas._fit_parameters(), fit)
        self.assertIn("Original", panel.layer_details.toolTip())
        QTest.keyClick(panel.time_chart, Qt.Key.Key_Up)
        self.assertEqual(panel.layer_spin.value(), 4)
        panel.layer_spin.setValue(2)
        self.assertEqual(panel.layer_spin.value(), 2)
        self.assertIsNotNone(canvas._prepare_line_frame().lower_layers)
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.rect().center())
        self.assertEqual(canvas._layer_z, result.layer_heights_mm[1])
        self.assertIsNotNone(canvas._prepare_line_frame().lower_layers)
        self.assertEqual(panel.layer_spin.value(), 2)

    def test_axis_drag_reuses_plot_and_coalesces_preview_updates(self):
        self.harness.request = self.harness.fixture.request(make_gcode(layers=120))
        result = self.harness.wait_for_result()
        QTest.qWait(100)
        chart, canvas = self.panel.time_chart, self.panel.canvas
        chart.grab()
        x = chart.plot_rect().right()
        with patch.object(chart, "_paint_plot", wraps=chart._paint_plot) as plotted, \
                patch.object(canvas, "set_layer_height", wraps=canvas.set_layer_height) as displayed:
            QTest.mousePress(chart, Qt.MouseButton.LeftButton, pos=QPointF(x, chart.layer_y(1)).toPoint())
            for layer in range(2, 101):
                QTest.mouseMove(chart, QPointF(x, chart.layer_y(layer)).toPoint(), delay=0)
            QTest.mouseRelease(chart, Qt.MouseButton.LeftButton, pos=QPointF(x, chart.layer_y(100)).toPoint())
            self.assertEqual(self.panel.layer_spin.value(), 100)
            self.assertEqual(canvas._layer_z, result.layer_heights_mm[99])
            self.assertLess(displayed.call_count, 25)
            self.assertEqual(plotted.call_count, 0)

    def test_layer_number_fits_its_digits_and_remains_within_object_layer_range(self):
        self.harness.request = self.harness.fixture.request(make_gcode(layers=123))
        self.harness.wait_for_result()
        spin = self.panel.layer_spin
        self.assertEqual((spin.minimum(), spin.maximum()), (1, 123))
        spin.setValue(1)
        self.app.processEvents()
        narrow = spin.width()
        spin.setValue(123)
        self.app.processEvents()
        self.assertGreater(spin.width(), narrow)
        self.assertGreaterEqual(spin.lineEdit().width(), spin.fontMetrics().horizontalAdvance(spin.text())+4)
        spin.setValue(0)
        self.assertEqual(spin.value(), 1)
        spin.setValue(124)
        self.assertEqual(spin.value(), 123)

    def test_large_layer_number_remains_visible_with_native_arrows_and_changed_fonts(self):
        self.harness.request = self.harness.fixture.request(make_gcode(layers=544))
        self.harness.wait_for_result()
        spin = self.panel.layer_spin
        for size in (9, 10, 12):
            spin.setFont(QFont("Segoe UI", size))
            for value in (1, 9, 10, 99, 100, 455, 544):
                spin.setValue(value)
                self.app.processEvents()
                edit = spin.lineEdit()
                margins = edit.textMargins()
                available = edit.contentsRect().width()-margins.left()-margins.right()
                self.assertGreaterEqual(available, edit.fontMetrics().horizontalAdvance(spin.text())+6,
                    (size, value, spin.width(), available))

    def test_camera_toolbar_ends_at_canvas_and_leaves_top_of_chart_column_free(self):
        self.window.resize(2400, 1200)
        self.assertFalse(self.panel.timing_toggle.isVisible())
        self.harness.wait_for_result()
        self.assertTrue(self.panel.timing_toggle.isVisible())
        QTest.qWait(100)
        panel = self.panel
        self.assertIs(panel.timing_toggle.parentWidget(), panel.preview_view)
        for shown in (False, True):
            panel.timing_toggle.setChecked(shown)
            QTest.qWait(80)
            for button in (*panel.camera_buttons.values(), panel.timing_toggle):
                self.assertGreaterEqual(button.x(), panel.canvas.x())
                self.assertLessEqual(button.geometry().right(), panel.canvas.geometry().right())
            self.assertEqual(panel.timing_toggle.geometry().right(), panel.canvas.geometry().right())
            if shown:
                self.assertEqual(panel.timing_panel.y(), panel.preview_view.y())
                self.assertGreater(panel.timing_panel.x(), panel.preview_view.geometry().right())
        panel.clear_timing()
        self.assertFalse(panel.timing_toggle.isVisible())

    def test_single_column_navigation_disables_once_and_restores_manual_choice(self):
        self.window.resize(2400, 1200)
        self.harness.wait_for_result()
        QTest.qWait(80)
        panel, canvas = self.panel, self.panel.canvas
        self.assertTrue(panel.columns.is_two_column())
        self.assertTrue(canvas.navigation_enabled)
        for _ in range(2):
            self.window.resize(1100, 1000)
            QTest.qWait(100)
            self.assertFalse(panel.columns.is_two_column())
            self.assertFalse(canvas.navigation_enabled)
            scroller = panel._preview_viewport.parentWidget()
            scrollbar = scroller.verticalScrollBar()
            self.assertGreater(scrollbar.maximum(), 0)
            scrollbar.setValue(0)
            zoom = canvas.zoom
            point = canvas.rect().center()
            QTest.wheelEvent(self.window.windowHandle(), self.window.mapFromGlobal(canvas.mapToGlobal(point)), QPoint(0, -120))
            QTest.qWait(40)
            self.assertEqual(canvas.zoom, zoom)
            self.assertGreater(scrollbar.value(), 0)
            scrollbar.setValue(0)
            canvas.navigation_toggle.click()
            self.assertTrue(canvas.navigation_enabled)
            QTest.wheelEvent(self.window.windowHandle(), self.window.mapFromGlobal(canvas.mapToGlobal(point)), QPoint(0, 120))
            self.assertGreater(canvas.zoom, zoom)
            self.assertEqual(scrollbar.value(), 0)
            for _ in range(3):
                panel.refresh_layout()
            self.assertTrue(canvas.navigation_enabled)
            self.window.resize(2400, 1200)
            QTest.qWait(100)
            self.assertTrue(panel.columns.is_two_column())
            self.assertTrue(canvas.navigation_enabled)
        # Preserve an explicitly disabled wide-view state as well.
        canvas.navigation_toggle.click()
        self.assertFalse(canvas.navigation_enabled)
        self.window.resize(1100, 1000)
        QTest.qWait(100)
        self.window.resize(2400, 1200)
        QTest.qWait(100)
        self.assertFalse(canvas.navigation_enabled)
        # An activation in the narrow view also wins over that disabled state.
        self.window.resize(1100, 1000)
        QTest.qWait(100)
        canvas.navigation_toggle.click()
        self.window.resize(2400, 1200)
        QTest.qWait(100)
        self.assertTrue(canvas.navigation_enabled)

    def test_colour_layer_and_preview_resets_preserve_generated_result(self):
        panel, canvas = self.panel, self.panel.canvas
        self.assertEqual(panel.all_travel.width(), panel.colour_reset.width())
        result = self.harness.wait_for_result()
        self.assertEqual(panel.all_travel.width(), panel.colour_reset.width())
        settings = panel.settings()
        self.assertEqual(panel.layer_spin.value(), panel.layer_spin.maximum())
        self.assertEqual(panel.time_chart.selected, panel.layer_spin.maximum())
        self.assertFalse(panel.all_travel.isChecked())
        panel.select_layer(3)
        panel.view_checkboxes["show_wait_travel"].setChecked(True)
        panel.view_checkboxes["show_tower_travel"].setChecked(True)
        self.assertTrue(canvas._wait_travel_visible)
        self.assertTrue(canvas._tower_travel_visible)
        self.assertFalse(canvas._cumulative_travel)
        frame = canvas._prepare_line_frame()
        self.assertIsNotNone(frame.lower_layers)
        camera = canvas.camera_state()
        panel.colour_reset.click()
        self.assertFalse(canvas._layer_colours_highlight)
        self.assertEqual(canvas.camera_state(), camera)
        self.assertEqual(canvas._layer_z, result.layer_heights_mm[2])
        self.assertEqual(canvas._travel_layer_z, result.layer_heights_mm[2])
        canvas._prepare_line_frame()
        self.assertEqual([source[1].name() for source in canvas._lower_layer_frames.sources],
            [canvas.OBJECT_COLOR, canvas.BRIM_COLOR, canvas.TOWER_COLOR])
        centre = canvas.rect().center()
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=centre)
        QTest.mouseMove(canvas, centre+QPoint(15, 8))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=centre+QPoint(15, 8))
        self.assertNotEqual(canvas.camera_state(), camera)
        self.assertEqual(canvas._layer_z, result.layer_heights_mm[2])
        self.assertEqual(panel.layer_spin.value(), 3)
        self.assertFalse(canvas._layer_colours_highlight)
        panel.layer_reset.click()
        self.assertEqual(panel.layer_spin.value(), len(result.layer_times_s))
        self.assertEqual(panel.time_chart.selected, len(result.layer_times_s))
        self.assertIsNone(canvas._layer_z)
        last_routes = canvas._travel_segments(result.scene.wait_travel_segments, result.scene.wait_travel_layer_indices)
        self.assertLess(len(last_routes), len(result.scene.wait_travel_segments))
        self.assertTrue(all(abs(result.scene.layer_z_mm[i]-result.layer_heights_mm[-1]) < .001
            for s, i in zip(result.scene.wait_travel_segments, result.scene.wait_travel_layer_indices) if s in last_routes))
        panel.select_layer(2)
        self.assertTrue(canvas._layer_colours_highlight)
        panel.logarithmic_scale.setChecked(False)
        panel.view_checkboxes["show_wait_position"].setChecked(False)
        canvas.set_navigation_enabled(False)
        panel.preview_reset.click()
        self.assertIs(panel.preview_reset.parentWidget(), canvas)
        self.assertEqual(panel.preview_reset.x(), 0)
        self.assertEqual(canvas.height()-panel.preview_reset.geometry().bottom()-1, 0)
        self.assertEqual(canvas.width()-panel.colour_reset.geometry().right()-1, 0)
        self.assertEqual(canvas.height()-panel.colour_reset.geometry().bottom()-1, 0)
        self.assertEqual(panel.layer_spin.value(), panel.layer_spin.maximum())
        self.assertIsNone(canvas._layer_z)
        self.assertFalse(canvas._cumulative_travel)
        self.assertFalse(canvas._wait_travel_visible)
        self.assertFalse(canvas._tower_travel_visible)
        self.assertTrue(canvas._wait_position_visible)
        self.assertTrue(panel.logarithmic_scale.isChecked())
        self.assertTrue(canvas.navigation_enabled)
        self.assertEqual((canvas.yaw_deg, canvas.pitch_deg), (canvas.separated_yaw(), -28))
        self.assertEqual((canvas.pan_x, canvas.pan_y, canvas.zoom), (0, 0, 1))
        self.assertEqual(panel.settings(), settings)
        self.assertIs(self.harness.controller.session.preview, result)
        self.assertIsNone(self.harness.controller.job_id)

    def test_individual_travel_toggles_are_independent_and_keep_layer(self):
        result = self.harness.wait_for_result()
        panel, canvas = self.panel, self.panel.canvas
        panel.select_layer(2)
        panel.view_checkboxes["show_tower_travel"].setChecked(True)
        self.assertFalse(canvas._cumulative_travel)
        self.assertFalse(canvas._wait_travel_visible)
        self.assertTrue(canvas._tower_travel_visible)
        self.assertEqual(canvas._layer_z, result.layer_heights_mm[1])
        panel.all_travel.click()
        self.assertTrue(panel.view_checkboxes["show_wait_travel"].isChecked())
        self.assertTrue(panel.view_checkboxes["show_tower_travel"].isChecked())
        self.assertTrue(canvas._wait_travel_visible)
        self.assertTrue(canvas._tower_travel_visible)
        self.assertTrue(canvas._all_travel_visible)
        panel.all_travel.click()
        self.assertFalse(panel.view_checkboxes["show_wait_travel"].isChecked())
        self.assertFalse(panel.view_checkboxes["show_tower_travel"].isChecked())
        self.assertFalse(canvas._wait_travel_visible)
        self.assertFalse(canvas._tower_travel_visible)
        self.assertFalse(canvas._all_travel_visible)
        self.assertEqual(canvas._layer_z, result.layer_heights_mm[1])

    def test_time_chart_has_compact_width_and_one_column_legend(self):
        self.harness.wait_for_result()
        self.window.resize(2000, 1100)
        QTest.qWait(100)
        self.assertEqual(self.panel.timing_panel.width(), 210)
        layout = self.panel.time_legend.layout()
        self.assertEqual(layout.columnCount(), 1)
        self.assertEqual(layout.rowCount(), 4)
        self.assertLessEqual(self.panel.time_chart.width(), 210)

    def test_preview_function_rows_have_fixed_spacing_and_minimum_reset_gap(self):
        self.harness.wait_for_result()
        QTest.qWait(100)
        panel = self.panel
        rows = [box.parentWidget() for box in panel.view_checkboxes.values()]
        for first, second in zip(rows, rows[1:]):
            self.assertEqual(second.y()-first.geometry().bottom()-1, 6)
            self.assertEqual(first.height(), first.minimumHeight())
            self.assertEqual(first.minimumHeight(), first.maximumHeight())
        gaps = []
        for name, box in panel.view_checkboxes.items():
            gaps.append(panel.reset_buttons[name].x()-box.geometry().right()-1)
        self.assertEqual(min(gaps), 30)
        self.assertEqual(panel.view_controls.width(), panel.view_controls.layout().minimumSize().width())

    def test_layer_above_tower_does_not_invent_wait_position_or_tower_paths(self):
        lines, z = [], 0
        for line in make_gcode(layers=6).splitlines():
            if line.startswith(";Z:"):
                z = float(line[3:])
            if z >= .8 and " E" in line and " X" in line:
                line = line.replace("F1200", "F6")
            lines.append(line)
        text = "\n".join(lines) + "\n"
        self.harness.request = self.harness.fixture.request(text)
        result = self.harness.wait_for_result()
        self.assertLess(result.scene.tower_layer_count, len(result.layer_times_s))
        self.panel.select_layer(6)
        self.assertIsNone(self.panel.canvas._wait_marker_position())
        self.assertFalse(self.panel.canvas._layer_segments(result.scene.tower_segments))
        self.assertFalse(self.panel.canvas._layer_segments(result.scene.wait_travel_segments, result.scene.wait_travel_layer_indices))

if __name__ == "__main__":
    unittest.main()
