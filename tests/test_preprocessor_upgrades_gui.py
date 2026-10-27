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
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QStyle, QStyleOptionFrame
from cooling_tower.gui.generation_session import GenerationMode
from cooling_tower.preprocessor_safety import ExclusionRect


class PreprocessorUpgradeGuiTests(unittest.TestCase):
    def test_reorganized_settings_use_auto_and_two_millimetre_brim(self):
        panel = self.panel
        self.assertEqual(panel.settings().tower_brim_width_mm, 2)
        for name in ("wall_count", "wait_clearance_mm"):
            self.assertTrue(panel.input_group.isAncestorOf(panel.rows[name]))
        for name in ("tower_brim_width_mm", "tower_brim_gap_mm"):
            self.assertTrue(panel.advanced_group.isAncestorOf(panel.rows[name]))
        self.assertEqual(panel.rows["z_hop_mm"].label.text(), "Z-Hop")
        for flag, checkbox in panel.automatic.items():
            if flag in ("automatic_position", "automatic_wait_position"):
                continue
            row = checkbox.parentWidget()
            self.assertEqual(row.layout().itemAtPosition(0, 2).widget().text(), "Auto")
        self.assertEqual(panel.positions_button.parentWidget().layout().itemAt(3).widget().text(), "Auto")

    def test_numeric_fields_share_content_width_and_preserve_uncommitted_drafts(self):
        self.window._apply_style()
        panel = self.panel
        panel.advanced_group.set_expanded(True)
        QTest.qWait(40)
        widths = {row.editor.width() for row in panel.rows.values()}
        self.assertEqual(len(widths), 1)
        initial = widths.pop()
        editor = panel.inputs["target_layer_time_s"]
        editor.setFocus()
        editor.selectAll()
        QTest.keyClicks(editor, "1234,56")
        QTest.qWait(40)
        self.assertEqual(editor.lineEdit().text(), "1234,56")
        self.assertEqual(editor.value(), 10)
        self.assertGreater(editor.width(), initial)
        self.assertEqual({row.editor.width() for row in panel.rows.values()}, {editor.width()})
        for row in panel.rows.values():
            line = row.editor.lineEdit()
            option = QStyleOptionFrame()
            option.initFrom(line)
            contents = line.style().subElementRect(QStyle.SubElement.SE_LineEditContents, option, line)
            self.assertGreaterEqual(contents.width(), line.fontMetrics().horizontalAdvance(line.text())+4)
            self.assertGreaterEqual(row.unit_label.width(), row.unit_label.fontMetrics().horizontalAdvance(row.unit_label.text()))
            self.assertGreaterEqual(row.unit_label.width(), row.unit_label.minimumSizeHint().width())
        editor.selectAll()
        QTest.keyClicks(editor, "10")
        QTest.keyClick(editor, Qt.Key.Key_Return)
        QTest.qWait(40)
        self.assertEqual(editor.width(), initial)

    def test_unit_padding_is_funded_by_both_value_gaps_without_widening_fields(self):
        panel = self.panel
        panel.advanced_group.set_expanded(True)
        QTest.qWait(40)
        initial = panel.inputs["travel_speed_mm_s"].width()
        for row in panel.rows.values():
            row.unit_label.setMargin(1)
        panel.refresh_layout()
        self.assertEqual({row.editor.width() for row in panel.rows.values()}, {initial})
        for row in panel.rows.values():
            self.assertGreaterEqual(row.unit_label.width(), row.unit_label.minimumSizeHint().width())
            line = row.editor.lineEdit()
            option = QStyleOptionFrame()
            option.initFrom(line)
            contents = line.style().subElementRect(QStyle.SubElement.SE_LineEditContents, option, line)
            self.assertGreaterEqual(contents.width(), line.fontMetrics().horizontalAdvance(line.text())+4)

    def test_preview_renders_blue_positive_z_axis(self):
        self.harness.wait_for_result()
        canvas = self.panel.canvas
        self.assertIsNotNone(canvas.scene.bed_geometry)
        canvas.fit_scene(emit=False)
        canvas.grab()
        image = canvas._rendered_frame.toImage()
        from cooling_tower.preview import Point3D
        length = min(30, (canvas.scene.bed_bounds.maximum_x_mm-canvas.scene.bed_bounds.minimum_x_mm)/8)
        point = canvas._project(Point3D(0, 0, length*.6), canvas._fit_parameters())
        ratio = canvas.devicePixelRatioF()
        expected = QColor(canvas.Z_AXIS_COLOR)
        pixels = [image.pixelColor(round(point.x()*ratio)+dx, round(point.y()*ratio)+dy)
            for dx in (-1, 0, 1) for dy in (-1, 0, 1)]
        self.assertLess(min(abs(p.red()-expected.red())+abs(p.green()-expected.green())+
            abs(p.blue()-expected.blue()) for p in pixels), 150)

    def test_preview_legend_wraps_entries_in_reading_order_and_uses_full_width(self):
        legend = self.panel.legend
        legend.ensurePolished()
        legend.setMinimumHeight(0)
        legend.setMaximumHeight(16777215)
        entries = legend.entries
        widths = [entry.sizeHint().width() for entry in entries]
        gap = legend.layout().spacing()
        full = sum(widths)+(len(entries)-1)*gap
        distributions = set()
        for width in range(full, max(widths)-1, -1):
            height = legend.heightForWidth(width)
            legend.resize(width, height)
            legend.layout().setGeometry(legend.rect())
            rows = {}
            for entry in entries:
                self.assertTrue(legend.rect().contains(entry.geometry()))
                rows.setdefault(entry.y(), []).append(entry)
            distributions.add(tuple(len(row) for row in rows.values()))
            for row in rows.values():
                self.assertEqual(row[0].x(), 0)
                for first, second in zip(row, row[1:]):
                    self.assertEqual(second.x()-first.geometry().right()-1, gap)
        self.assertIn((6,), distributions)
        self.assertIn((5, 1), distributions)
        self.assertIn((1, 1, 1, 1, 1, 1), distributions)
        self.assertTrue(any(len(rows) >= 3 for rows in distributions))
        self.assertFalse(hasattr(self.panel, 'view_controls'))
        self.assertFalse(hasattr(self.panel, 'view_checkboxes'))

    def test_clearance_display_is_removed_without_changing_safety_metadata(self):
        result = self.harness.wait_for_result()
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
        self.assertEqual(layout.indexOf(row), layout.indexOf(panel.logarithmic_scale.parentWidget())+1)
        self.assertEqual(panel.logarithmic_info.objectName(), "settingInfoButton")
        self.assertEqual(panel.logarithmic_info.width(), panel.normalization_info.width())
        self.assertIn("lineare Zeitskala", panel.logarithmic_info.toolTip())
        self.assertLess(panel.logarithmic_info.x(), panel.logarithmic_scale.x())
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

    def test_chart_sits_right_of_complete_preview_and_full_width_legend(self):
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
        self.assertEqual(panel.legend.width(), panel.canvas.width())
        chart, legend = panel.time_chart, panel.time_legend
        self.assertGreater(legend.y(), chart.geometry().bottom())
        self.assertFalse(hasattr(panel, "summary"))
        self.assertFalse(hasattr(panel, "layer_slider"))
        self.assertEqual(panel.timing_panel.height(), panel.preview_view.height())
        self.assertIs(panel.legend.parentWidget(), panel.preview_view)
        entries = panel.legend.entries
        self.assertEqual(len({entry.y() for entry in entries}), 1)
        for first, second in zip(entries, entries[1:]):
            self.assertEqual(second.x()-first.geometry().right()-1, 15)
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
        self.panel.transparency_toggle.setChecked(False)
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
        self.assertTrue(self.panel.transparency_toggle.isChecked())

    def test_transparency_button_matches_chart_and_restores_opaque_rendering(self):
        result = self.harness.wait_for_result()
        panel, canvas = self.panel, self.panel.canvas
        QTest.qWait(100)
        camera = canvas.camera_state()
        gcode = result.gcode_path.read_bytes()

        def rendered_image():
            canvas.grab()
            return canvas._rendered_frame.toImage()

        panel.transparency_toggle.click()
        opaque = rendered_image()
        self.assertIsNone(canvas._layer_z)
        panel.transparency_toggle.click()
        transparent = rendered_image()
        self.assertNotEqual(transparent, opaque)
        self.assertIsNotNone(canvas._prepare_line_frame().lower_layers)
        panel.transparency_toggle.click()
        self.assertEqual(rendered_image(), opaque)

        # Choosing the same last layer in the chart must produce exactly the
        # same scene as activating transparency without a prior layer choice.
        QTest.keyClick(panel.time_chart, Qt.Key.Key_End)
        self.assertTrue(panel.transparency_toggle.isChecked())
        self.assertEqual(panel.transparency_toggle.text(), "Transparenz aktiv")
        self.assertEqual(rendered_image(), transparent)

        panel.transparency_toggle.click()
        chart = panel.time_chart
        x = round(chart.plot_rect().right())
        start = QPoint(x, round(chart.layer_y(chart.selected)))
        end = QPoint(x, round(chart.layer_y(3)))
        QTest.mousePress(chart, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(chart, end)
        QTest.mouseRelease(chart, Qt.MouseButton.LeftButton, pos=end)
        self.assertTrue(panel.transparency_toggle.isChecked())
        selected_transparent = rendered_image()
        panel.transparency_toggle.click()
        self.assertEqual(panel.transparency_toggle.text(), "Transparenz inaktiv")
        self.assertNotEqual(rendered_image(), selected_transparent)
        self.assertEqual(canvas._layer_z, result.layer_heights_mm[2])
        self.assertEqual(canvas.camera_state(), camera)
        panel.layer_reset.click()
        self.assertFalse(panel.transparency_toggle.isChecked())
        self.assertEqual(rendered_image(), opaque)
        self.assertEqual(result.gcode_path.read_bytes(), gcode)
        self.assertIsNone(self.controller.job_id)

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

    def test_transparency_layer_and_preview_resets_preserve_generated_result(self):
        panel, canvas = self.panel, self.panel.canvas
        self.assertEqual(panel.travel_visibility_button.width(), panel.travel_mode_toggle.width())
        result = self.harness.wait_for_result()
        self.assertEqual(panel.preview_reset.width(), panel.transparency_toggle.width())
        settings = panel.settings()
        self.assertEqual(panel.layer_spin.value(), panel.layer_spin.maximum())
        self.assertEqual(panel.time_chart.selected, panel.layer_spin.maximum())
        self.assertTrue(panel.travel_visibility_button.isChecked())
        panel.select_layer(3)
        self.assertTrue(canvas._wait_travel_visible)
        self.assertTrue(canvas._tower_travel_visible)
        self.assertFalse(canvas._cumulative_travel)
        frame = canvas._prepare_line_frame()
        self.assertIsNotNone(frame.lower_layers)
        camera = canvas.camera_state()
        self.assertEqual(panel.transparency_toggle.text(), "Transparenz aktiv")
        panel.transparency_toggle.click()
        self.assertEqual(panel.transparency_toggle.text(), "Transparenz inaktiv")
        self.assertFalse(canvas._layer_colours_highlight)
        self.assertEqual(canvas.camera_state(), camera)
        self.assertEqual(canvas._layer_z, result.layer_heights_mm[2])
        self.assertEqual(canvas._travel_layer_z, result.layer_heights_mm[2])
        canvas._prepare_line_frame()
        self.assertEqual([source[1].name() for source in canvas._lower_layer_frames.sources],
            [canvas.OBJECT_COLOR, canvas.BRIM_COLOR, canvas.TOWER_COLOR])
        # A narrow window starts with scrolling enabled instead of camera
        # navigation. Opt in before testing a deliberate camera gesture.
        canvas.set_navigation_enabled(True)
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
        self.assertTrue(panel.transparency_toggle.isChecked())
        panel.transparency_toggle.click()
        self.assertFalse(canvas._layer_colours_highlight)
        panel.transparency_toggle.click()
        self.assertTrue(canvas._layer_colours_highlight)
        self.assertEqual(panel.transparency_toggle.text(), "Transparenz aktiv")
        panel.logarithmic_scale.setChecked(False)
        canvas.set_wait_position_visible(False)
        canvas.set_navigation_enabled(False)
        panel.preview_reset.click()
        self.assertIs(panel.preview_reset.parentWidget(), canvas)
        self.assertEqual(panel.preview_reset.x(), 0)
        self.assertEqual(canvas.height()-panel.preview_reset.geometry().bottom()-1, 0)
        self.assertEqual(panel.transparency_toggle.x(), 0)
        self.assertEqual(panel.transparency_toggle.geometry().bottom()+1, panel.preview_reset.y())
        self.assertEqual(canvas.width()-panel.travel_mode_toggle.geometry().right()-1, 0)
        self.assertEqual(canvas.height()-panel.travel_mode_toggle.geometry().bottom()-1, 0)
        self.assertEqual(panel.travel_visibility_button.geometry().bottom()+1, panel.travel_mode_toggle.y())
        self.assertEqual(panel.layer_spin.value(), panel.layer_spin.maximum())
        self.assertEqual(canvas._layer_z, result.layer_heights_mm[-1])
        self.assertFalse(canvas._cumulative_travel)
        self.assertTrue(canvas._wait_travel_visible)
        self.assertTrue(canvas._tower_travel_visible)
        self.assertTrue(canvas._wait_position_visible)
        self.assertTrue(panel.logarithmic_scale.isChecked())
        self.assertTrue(canvas.navigation_enabled)
        self.assertEqual((canvas.yaw_deg, canvas.pitch_deg), (canvas.separated_yaw(), -28))
        self.assertEqual((canvas.pan_x, canvas.pan_y, canvas.zoom), (0, 0, 1))
        self.assertEqual(panel.settings(), settings)
        self.assertIs(self.harness.controller.session.preview, result)
        self.assertIsNone(self.harness.controller.job_id)

    def test_travel_visibility_controls_both_routes_and_preserves_layer_and_mode(self):
        result = self.harness.wait_for_result()
        panel, canvas = self.panel, self.panel.canvas
        panel.select_layer(2)
        self.assertEqual(panel.travel_visibility_button.text(), 'Fahrwege anzeigen')
        self.assertTrue(panel.travel_visibility_button.isChecked())
        self.assertFalse(panel.travel_mode_toggle.isChecked())
        self.assertTrue(canvas._wait_position_visible)
        panel.travel_mode_toggle.click()
        self.assertTrue(canvas._all_travel_visible)
        for visible in (False, True, False):
            panel.travel_visibility_button.click()
            self.assertEqual(panel.travel_visibility_button.isChecked(), visible)
            self.assertEqual(canvas._wait_travel_visible, visible)
            self.assertEqual(canvas._tower_travel_visible, visible)
            self.assertTrue(canvas._wait_position_visible)
            self.assertTrue(canvas._all_travel_visible)
            self.assertEqual(canvas._layer_z, result.layer_heights_mm[1])
        panel.preview_reset.click()
        self.assertTrue(panel.travel_visibility_button.isChecked())
        self.assertFalse(panel.travel_mode_toggle.isChecked())
        self.assertTrue(canvas._wait_travel_visible)
        self.assertTrue(canvas._tower_travel_visible)

    def test_travel_mode_in_preview_preserves_enabled_groups_and_resets(self):
        panel, canvas = self.panel, self.panel.canvas
        self.assertFalse(panel.travel_mode_toggle.isEnabled())
        result = self.harness.wait_for_result()
        self.assertTrue(panel.travel_mode_toggle.isEnabled())
        self.assertFalse(panel.travel_mode_toggle.isChecked())
        self.assertIs(panel.travel_mode_toggle.parentWidget(), canvas)
        self.assertEqual(panel.travel_mode_toggle.width(), panel.travel_visibility_button.width())
        panel.select_layer(3)
        camera = canvas.camera_state()
        gcode = result.gcode_path.read_bytes()
        for all_layers in (True, False, True):
            panel.travel_mode_toggle.click()
            self.assertEqual(canvas._all_travel_visible, all_layers)
            self.assertTrue(canvas._wait_travel_visible)
            self.assertTrue(canvas._tower_travel_visible)
            frame = canvas._prepare_line_frame()
            self.assertTrue(frame.tower_travel_blocks)
            self.assertEqual(len(canvas._lower_layer_frames.sources), 5 if all_layers else 3)
            self.assertEqual(canvas.camera_state(), camera)
            self.assertEqual(canvas._layer_z, result.layer_heights_mm[2])
        self.assertEqual(result.gcode_path.read_bytes(), gcode)
        self.assertIsNone(self.controller.job_id)
        panel.preview_reset.click()
        self.assertFalse(panel.travel_mode_toggle.isChecked())
        self.assertFalse(canvas._all_travel_visible)
        panel.travel_mode_toggle.setChecked(True)
        panel.reset()
        self.assertFalse(panel.travel_mode_toggle.isChecked())
        self.assertFalse(canvas._all_travel_visible)
        panel.clear_timing()
        self.assertFalse(panel.travel_mode_toggle.isEnabled())

    def test_all_travel_follows_time_chart_scrubber_and_layer_reset(self):
        result = self.harness.wait_for_result()
        panel, canvas = self.panel, self.panel.canvas
        gcode = result.gcode_path.read_bytes()
        panel.travel_mode_toggle.setChecked(True)
        chart = panel.time_chart
        x = round(chart.plot_rect().right())
        start = QPoint(x, round(chart.layer_y(chart.selected)))
        end = QPoint(x, round(chart.layer_y(2)))
        QTest.mousePress(chart, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(chart, end)
        QTest.mouseRelease(chart, Qt.MouseButton.LeftButton, pos=end)
        self.assertEqual(panel.layer_spin.value(), 2)
        self.assertEqual(canvas._layer_z, result.layer_heights_mm[1])
        frame = canvas._prepare_line_frame()
        for segments, indices, blocks in (
                (result.scene.wait_travel_segments, result.scene.wait_travel_layer_indices, frame.wait_travel_blocks),
                (result.scene.tower_travel_segments, result.scene.tower_travel_layer_indices, frame.tower_travel_blocks)):
            expected = tuple(canvas._line_blocks(tuple(s for s, i in zip(segments, indices) if i == 1),
                canvas._fit_parameters(), canvas._projection_context()))
            self.assertEqual(blocks, expected)
        self.assertIsNotNone(frame.lower_layers)
        panel.layer_reset.click()
        frame = canvas._prepare_line_frame()
        self.assertTrue(panel.travel_visibility_button.isChecked())
        self.assertIsNotNone(frame.lower_layers)
        for source, blocks, segments in zip(canvas._lower_layer_frames.sources[-2:],
                (frame.wait_travel_blocks, frame.tower_travel_blocks),
                (result.scene.wait_travel_segments, result.scene.tower_travel_segments)):
            lower = sum(len(lines) for z, lines in source[0].items() if z < result.layer_heights_mm[-1]-.001)
            self.assertEqual(lower+sum(map(len, blocks)), len(segments))
        self.assertEqual(result.gcode_path.read_bytes(), gcode)
        self.assertIsNone(self.controller.job_id)

    def test_time_chart_has_compact_width_and_one_column_legend(self):
        self.harness.wait_for_result()
        self.window.resize(2400, 1100)
        QTest.qWait(100)
        compact_width = max(210, self.panel.timing_panel.minimumSizeHint().width())
        self.assertEqual(self.panel.timing_panel.width(), compact_width)
        self.assertEqual(self.panel.timing_panel.maximumWidth(), compact_width)
        layout = self.panel.time_legend.layout()
        self.assertEqual(layout.columnCount(), 1)
        self.assertEqual(layout.rowCount(), 4)
        self.assertLessEqual(self.panel.time_chart.width(), compact_width)

    def test_travel_mode_reveal_clips_at_preview_edge_and_reverses_continuously(self):
        from PySide6.QtCore import QAbstractAnimation
        panel, canvas = self.panel, self.panel.canvas
        self.assertTrue(panel.travel_visibility_button.isChecked())
        self.assertTrue(panel.travel_mode_toggle.isHidden())
        result = self.harness.wait_for_result()
        QTest.qWait(80)
        button, toggle = panel.travel_visibility_button, panel.travel_mode_toggle
        animation = panel._travel_reveal_animation
        camera, gcode = canvas.camera_state(), result.gcode_path.read_bytes()
        self.assertTrue(toggle.isVisible())
        self.assertFalse(toggle.isChecked())
        panel.travel_visibility_button.click()
        self.assertEqual(animation.state(), QAbstractAnimation.State.Running)
        self.assertFalse(toggle.isEnabled())
        animation.setCurrentTime(animation.duration()//2)
        self.assertGreater(toggle.y(), canvas.height()-toggle.height())
        self.assertLess(toggle.y(), canvas.height())
        self.assertEqual(button.geometry().bottom()+1, toggle.y())
        self.assertTrue(canvas.rect().contains(button.geometry()))
        self.assertLess(toggle.visibleRegion().boundingRect().height(), toggle.height())
        animation.setCurrentTime(animation.duration())
        self.assertTrue(toggle.isHidden())
        self.assertEqual(button.geometry().bottom()+1, canvas.height())
        button.click()
        self.assertTrue(toggle.isVisible())
        self.assertTrue(toggle.isEnabled())
        self.assertEqual(toggle.y(), canvas.height())
        animation.setCurrentTime(animation.duration()//2)
        middle = panel._travel_reveal
        button.click()
        self.assertAlmostEqual(panel._travel_reveal, middle)
        animation.setCurrentTime(animation.duration()//2)
        animation.pause()
        self.window.resize(1100, 1000)
        QTest.qWait(50)
        self.assertEqual(button.geometry().right()+1, canvas.width())
        self.assertEqual(toggle.geometry().right()+1, canvas.width())
        self.assertEqual(button.geometry().bottom()+1, toggle.y())
        panel.clear_timing()
        self.assertEqual(animation.state(), QAbstractAnimation.State.Stopped)
        self.assertTrue(toggle.isHidden())
        self.assertEqual(button.geometry().bottom()+1, canvas.height())
        self.assertEqual(canvas.camera_state(), camera)
        self.assertEqual(result.gcode_path.read_bytes(), gcode)

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
