from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import test_preprocessor_gui as fixture_module
from test_preprocessor import make_gcode
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from cooling_tower.gui.generation_session import GenerationMode
from cooling_tower.gui.preprocessor_exclusions import ExclusionCanvas
from cooling_tower.calibration.gcode_integration import parse_bed_geometry
from cooling_tower.preprocessor_safety import ExclusionRect


class PreprocessorUpgradeGuiTests(unittest.TestCase):
    def test_clearance_overlay_tracks_layer_and_does_not_change_gcode_or_camera(self):
        result = self.harness.wait_for_result()
        canvas, panel = self.panel.canvas, self.panel
        before = result.gcode_path.read_bytes()
        camera = canvas.camera_state()
        panel.view_checkboxes["show_clearance"].setChecked(True)
        panel.select_layer(2)
        segments = canvas._clearance_segments()
        self.assertTrue(segments)
        self.assertAlmostEqual(min(segment.start.z for segment in segments),
            result.layer_heights_mm[1] + result.effective_z_hop_mm)
        self.assertEqual(canvas.camera_state(), camera)
        self.assertFalse(canvas.grab().isNull())
        self.assertIn("keine vermessene", panel.safety_hint.toolTip())
        self.assertEqual(result.gcode_path.read_bytes(), before)
        canvas.set_layer_height(result.height_mm+10)
        self.assertEqual(canvas._clearance_segments(), ())

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
        self.harness.request.profile.effective_values.update({"slow_down_layer_time": 18,
            "outer_wall_speed": 40, "travel_speed": 150, "retraction_length": 1.2, "retraction_speed": 32})
        self.panel.set_profile_values(self.harness.request.profile.effective_values)
        result = self.harness.wait_for_result()
        self.assertEqual(result.effective_settings.target_layer_time_s, 18)
        for name in ("target_layer_time_s", "print_speed_mm_s", "travel_speed_mm_s", "retract_mm", "retract_speed_mm_s"):
            self.assertFalse(self.panel.inputs[name].isEnabled())
            self.assertNotEqual(self.panel.inputs[name].lineEdit().text(), "—")
        self.panel.automatic["automatic_target_time"].setChecked(False)
        self.assertEqual(self.panel.settings().target_layer_time_s, 18)
        self.assertIsNone(self.controller.session.preview)
        self.assertFalse(self.panel.time_chart.isEnabled())
        self.panel.reset_field("target_layer_time_s")
        self.panel.automatic["automatic_target_time"].setChecked(False)
        self.assertEqual(self.panel.settings().target_layer_time_s, 18)

    def test_position_coordinates_open_only_in_manual_mode(self):
        for flag, x, y in (("automatic_position", "center_x_mm", "center_y_mm"),
                ("automatic_wait_position", "wait_x_mm", "wait_y_mm")):
            self.assertTrue(self.panel.inputs[x].isHidden())
            self.assertTrue(self.panel.rows[y].isHidden())
            self.panel.automatic[flag].setChecked(False)
            self.app.processEvents()
            self.assertFalse(self.panel.inputs[x].isHidden())
            self.assertFalse(self.panel.rows[y].isHidden())
            self.assertTrue(self.panel.inputs[x].isEnabled())
            self.panel.automatic[flag].setChecked(True)
            self.assertTrue(self.panel.rows[y].isHidden())

    def test_unknown_head_warning_survives_error_and_new_bed_clears_zones_with_notice(self):
        values = dict(self.harness.request.profile.effective_values)
        values.pop("extruder_clearance_height")
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
        self.assertIn("Sperrflächen wurden zurückgesetzt", self.panel.status.text())

    def test_chart_click_slider_and_keyboard_filter_exact_layer_and_travels(self):
        result = self.harness.wait_for_result()
        panel, canvas = self.panel, self.panel.canvas
        camera, fit = canvas.camera_state(), canvas._fit_parameters()
        rect = panel.time_chart.plot_rect()
        pos = QPointF(rect.left() + rect.width() * 2.5 / len(result.layer_times_s), rect.center().y()).toPoint()
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
        self.assertIn("Original", panel.layer_details.text())
        QTest.keyClick(panel.time_chart, Qt.Key.Key_Right)
        self.assertEqual(panel.layer_spin.value(), 4)
        panel.layer_slider.setValue(2)
        self.assertEqual(panel.layer_spin.value(), 2)
        panel.all_layers.setChecked(True)
        self.assertIsNone(canvas._layer_z)

    def test_exclusion_dialog_cancel_keeps_settings_and_apply_invalidates_only_result(self):
        original_source = self.harness.request.prepared_source.analysis_gcode_path.read_bytes()
        self.controller.open_exclusion_editor()
        dialog = self.controller.exclusion_dialog
        self.assertIsNotNone(dialog)
        dialog.canvas.zones = (ExclusionRect(150, 20, 170, 40),)
        dialog.reject()
        self.app.processEvents()
        self.assertEqual(self.panel.exclusions, ())
        self.controller.open_exclusion_editor()
        dialog = self.controller.exclusion_dialog
        zone = ExclusionRect(150, 20, 170, 40)
        dialog.canvas.zones = (zone,)
        dialog.accept()
        self.app.processEvents()
        self.assertEqual(self.panel.settings().exclusions, (zone,))
        self.assertIn("(1)", self.panel.exclusions_button.text())
        self.assertIsNone(self.controller.job_id)
        self.assertEqual(self.harness.request.prepared_source.analysis_gcode_path.read_bytes(), original_source)

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

    def test_exclusion_draw_move_resize_undo_delete_and_zoom_with_negative_origin(self):
        geometry = parse_bed_geometry({"bed_shape": ["-100x-100", "100x-100", "100x100", "-100x100"]})
        canvas = ExclusionCanvas(geometry)
        canvas.resize(700, 650)
        canvas.show()
        self.app.processEvents()
        try:
            a, b = canvas.screen((-60, -40)).toPoint(), canvas.screen((-20, -10)).toPoint()
            QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=a)
            QTest.mouseMove(canvas, b)
            QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=b)
            self.assertEqual(len(canvas.zones), 1)
            zone = canvas.zones[0]
            self.assertAlmostEqual(zone.x0, -60, delta=.5)
            self.assertAlmostEqual(zone.y0, -40, delta=.5)
            start, end = canvas.screen((-40, -25)).toPoint(), canvas.screen((-25, -10)).toPoint()
            QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
            QTest.mouseMove(canvas, end)
            QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
            self.assertGreater(canvas.zones[0].x0, zone.x0 + 10)
            moved = canvas.zones[0]
            start = canvas.screen((moved.x1, moved.y1)).toPoint()
            end = canvas.screen((moved.x1 + 10, moved.y1 + 10)).toPoint()
            QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
            QTest.mouseMove(canvas, end)
            QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
            self.assertGreater(canvas.zones[0].x1, moved.x1 + 5)
            canvas.undo()
            self.assertEqual(canvas.zones, (moved,))
            canvas.selected = 0
            QTest.keyClick(canvas, Qt.Key.Key_Delete)
            self.assertEqual(canvas.zones, ())
            canvas.undo()
            self.assertEqual(canvas.zones, (moved,))
            canvas.zoom, canvas.pan = 2.0, QPointF(30, -20)
            point = canvas.world(canvas.screen((-30, 20)))
            self.assertAlmostEqual(point[0], -30)
            self.assertAlmostEqual(point[1], 20)
            canvas.fit()
            self.assertEqual(canvas.zoom, 1)
        finally:
            canvas.close()
            canvas.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
