from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("COOLING_TOWER_DISABLE_SLICER_DISCOVERY", "1")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from cooling_tower.calibration.gcode_integration import (
    GCodeIntegrationError,
    propose_tower_placement,
)
from cooling_tower.gui.main_window import MainWindow
from cooling_tower.gui.preview_dialog import PreviewDialog
from cooling_tower.gui.settings_store import UserSettingsStore
from cooling_tower.models import BedBounds, OccupiedBounds
from cooling_tower.preview import (
    LineSegment3D,
    OutputMode,
    Point3D,
    PreviewScene,
    PreviewState,
)
from cooling_tower.tower.mesh_generator import automatic_mesh_segments
from cooling_tower.config import SETTINGS_SCHEMA_VERSION


class AutomaticGeometryTests(unittest.TestCase):
    def test_segments_follow_current_widest_diameter(self) -> None:
        for diameter, expected in ((10, 30), (25, 30), (30, 30), (30.2, 31), (150, 150)):
            with self.subTest(diameter=diameter):
                profile = SimpleNamespace(points=(SimpleNamespace(radius_mm=diameter / 2),))
                self.assertEqual(automatic_mesh_segments(profile), expected)
                solid = SimpleNamespace(points=(SimpleNamespace(outer_radius_mm=diameter / 2),))
                self.assertEqual(automatic_mesh_segments(solid), expected)

    def test_placement_uses_midpoint_of_farthest_usable_side(self) -> None:
        placement = propose_tower_placement(
            BedBounds(0, 200, 0, 100),
            OccupiedBounds(20, 60, 20, 80),
            tower_radius_mm=30,
            object_clearance_mm=0,
            edge_clearance_mm=0,
        )
        self.assertEqual((placement.center_x_mm, placement.center_y_mm), (130, 50))
        self.assertGreaterEqual(placement.center_x_mm - 30 - 60, 5)
        self.assertGreaterEqual(200 - placement.center_x_mm - 30, 5)
        self.assertEqual(placement.clearance_mm, 5)

    def test_placement_rejects_maximum_radius_without_five_mm_clearance(self) -> None:
        with self.assertRaises(GCodeIntegrationError):
            propose_tower_placement(
                BedBounds(0, 100, 0, 100),
                OccupiedBounds(45, 55, 45, 55),
                tower_radius_mm=18,
                object_clearance_mm=0,
                edge_clearance_mm=0,
            )

    def test_placement_clamps_cross_axis_when_object_touches_bed_edge(self) -> None:
        placement = propose_tower_placement(
            BedBounds(0, 250, 0, 250),
            OccupiedBounds(0, 13, 0, 10),
            tower_radius_mm=5,
            object_clearance_mm=5,
            edge_clearance_mm=5,
        )
        self.assertEqual(placement.center_x_mm, 10)
        self.assertEqual(placement.center_y_mm, 130)


class GenerationUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.window = MainWindow(
            user_settings_path=Path(self.temp.name) / "settings.json",
            enable_update_check=False,
            enable_startup_slicer_discovery=False,
        )
        self.addCleanup(self.window.close)

    def _ready(self) -> None:
        window = self.window
        window.resize(800, 900)
        window.show()
        window.workflow.set_slicer_step_visible(True)
        window.workflow.source_validation_succeeded("STL", analysis_complete=True)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        self.app.processEvents()

    def test_footer_actions_fit_and_height_shrinks_after_resizing(self) -> None:
        self._ready()
        window = self.window
        window.open_run_button.show()
        narrow_height = None
        for width in (1360, 1194, 1024, 760, 1360):
            with self.subTest(width=width):
                window.resize(width, 900)
                window._update_responsive_action_labels()
                window._fit_footer_height()
                self.app.processEvents()
                window._fit_footer_height()
                self.app.processEvents()
                self.assertEqual(window.footer.height(), window.footer.minimumHeight())
                self.assertEqual(window.footer.height(), window.footer.maximumHeight())
                self.assertIs(window.reset_button.parentWidget(), window.footer_reset_host)
                self.assertTrue(window.footer_message_area.isAncestorOf(window.reset_button))
                self.assertLessEqual(
                    window.reset_button.mapTo(window.footer, QPoint(0, 0)).x(),
                    window.open_output_button.mapTo(window.footer, QPoint(0, 0)).x(),
                )
                self.assertNotIn("\n", window.open_run_button.text())
                if width == 760:
                    narrow_height = window.footer.height()
                elif narrow_height is not None:
                    self.assertLess(window.footer.height(), narrow_height)
                buttons = [
                    button for button in (
                        window.open_output_button,
                        window.open_stl_button,
                        window.open_run_button,
                        window.preview_action_control,
                    ) if button.isVisible()
                ]
                rects = [
                    button.geometry().translated(
                        button.parentWidget().mapTo(window.footer, QPoint(0, 0))
                    ) for button in buttons
                ]
                for rect in rects:
                    self.assertTrue(window.footer.rect().contains(rect))
                for i, first in enumerate(rects):
                    for second in rects[i + 1:]:
                        self.assertFalse(first.intersects(second))

    def test_manual_row_and_messages_expand_then_shrink_geometry(self) -> None:
        self._ready()
        window = self.window
        original_height = window.geometry_settings_group.height()
        window.automatic_base_checkbox.setChecked(False)
        self.app.processEvents()
        self.assertTrue(window._setting_widgets["manual_base_width_mm"].isVisible())
        self.assertTrue(window.manual_base_width_spin.isEnabled())
        self.assertEqual(window.geometry_settings_group.height(), original_height)

        window.target_time_spin.setValue(100)
        window.manual_base_width_spin.setValue(20)
        window.maximum_expansion_angle_spin.setValue(27)
        window.validate_form()
        for _ in range(3):
            self.app.processEvents()
        expanded_height = window.geometry_settings_group.height()
        self.assertTrue(window._setting_widgets["target_layer_time_s"].message_label.isVisible())
        self.assertTrue(window.maximum_expansion_angle_setting.message_label.isVisible())

        for first, second in (
            ("manual_base_width_mm", "maximum_expansion_angle_deg"),
            ("maximum_expansion_angle_deg", "maximum_contraction_angle_deg"),
        ):
            upper = window._setting_widgets[first]
            lower = window._setting_widgets[second]
            upper_top = upper.mapTo(window, QPoint(0, 0)).y()
            lower_top = lower.mapTo(window, QPoint(0, 0)).y()
            self.assertLessEqual(upper_top + upper.height(), lower_top, first)
            message = upper.message_label
            if message.isVisible():
                message_top = message.mapTo(window, QPoint(0, 0)).y()
                self.assertLessEqual(message_top + message.height(), lower_top, first)

        window.target_time_spin.setValue(9)
        window.manual_base_width_spin.setValue(20)
        window.maximum_expansion_angle_spin.setValue(40)
        window.automatic_base_checkbox.setChecked(True)
        for _ in range(3):
            self.app.processEvents()
        self.assertTrue(window._setting_widgets["manual_base_width_mm"].isVisible())
        self.assertFalse(window.manual_base_width_spin.isEnabled())
        self.assertLess(window.geometry_settings_group.height(), expanded_height)
        self.assertEqual(
            window.geometry_settings_group.height(),
            window.geometry_settings_group.sizeHint().height(),
        )

    def test_feedback_reserves_space_and_keeps_lower_controls_clickable(self) -> None:
        self._ready()
        window = self.window
        window.automatic_base_checkbox.setChecked(False)
        window.target_time_spin.setValue(100)
        window.manual_base_width_spin.setValue(19)
        window.maximum_expansion_angle_spin.setValue(27)
        window.validate_form()

        for width, height in ((800, 900), (1952, 1279)):
            window.resize(width, height)
            for _ in range(3):
                self.app.processEvents()
            for first, second in (
                ("manual_base_width_mm", "maximum_expansion_angle_deg"),
                ("maximum_expansion_angle_deg", "maximum_contraction_angle_deg"),
            ):
                upper = window._setting_widgets[first]
                lower = window._setting_widgets[second]
                self.assertLessEqual(
                    upper.mapTo(window, QPoint(0, upper.height())).y(),
                    lower.mapTo(window, QPoint(0, 0)).y(),
                    (width, first),
                )
                self.assertLessEqual(
                    upper.message_container.geometry().bottom() + 1,
                    upper.height(),
                    (width, first),
                )

        row = window._setting_widgets["manual_base_width_mm"]
        for control in (row.editor, row.reset_button, row.info_button):
            point = control.mapTo(
                window, QPoint(control.width() - 7, control.height() - 7)
            )
            self.assertIs(window.childAt(point), control)

        QTest.mouseClick(
            row.editor,
            Qt.MouseButton.LeftButton,
            pos=QPoint(row.editor.width() - 7, row.editor.height() - 7),
        )
        self.app.processEvents()
        self.assertEqual(window.manual_base_width_spin.value(), 18)
        QTest.mouseClick(
            row.reset_button,
            Qt.MouseButton.LeftButton,
            pos=QPoint(
                row.reset_button.width() - 7,
                row.reset_button.height() - 7,
            ),
        )
        self.app.processEvents()
        self.assertEqual(window.manual_base_width_spin.value(), 25)

    def test_full_infill_follows_layer_time_tolerance_without_checkbox_tooltip(self) -> None:
        self._ready()
        infill_row = next(
            self.window.timing_group.content_layout.itemAt(index).widget()
            for index in range(self.window.timing_group.content_layout.count())
            if self.window.timing_group.content_layout.itemAt(index).widget()
            and self.window.timing_group.content_layout.itemAt(index).widget().layout()
            and self.window.timing_group.content_layout.itemAt(index).widget().layout().indexOf(
                self.window.full_infill_checkbox
            ) >= 0
        )
        self.assertIs(
            infill_row.layout().itemAt(1).widget(),
            self.window.full_infill_checkbox,
        )
        self.assertEqual(self.window.automatic_base_checkbox.toolTip(), "")

    def test_many_wrapped_errors_and_warnings_reflow_every_row(self) -> None:
        self._ready()
        window = self.window
        window.automatic_base_checkbox.setChecked(False)
        self.app.processEvents()
        rows = tuple(
            row for row in window._setting_widgets.values() if row.isVisible()
        )
        for row in rows:
            row.set_error(
                "Dieser ungültige Wert überschreitet die zulässige eigene "
                "Eingabegrenze deutlich und muss korrigiert werden."
            )
            row.set_warning(
                "Zusätzlicher Hinweis zu dieser Einstellung mit einem "
                "bewusst längeren Text für den automatischen Zeilenumbruch."
            )
        for width, height in ((800, 900), (1952, 1279)):
            window.resize(width, height)
            window._refresh_geometry_section_layout(True)
            self.app.processEvents()
            for layout in (
                window.timing_group.content_layout,
                window.geometry_fields_layout,
            ):
                children = tuple(
                    layout.itemAt(index).widget()
                    for index in range(layout.count())
                    if layout.itemAt(index).widget() is not None
                    and layout.itemAt(index).widget().isVisible()
                )
                for upper, lower in zip(children, children[1:]):
                    self.assertLessEqual(
                        upper.geometry().bottom() + 1,
                        lower.geometry().top(),
                        (width, upper.objectName()),
                    )
                self.assertLessEqual(
                    children[-1].geometry().bottom() + 1,
                    layout.parentWidget().height(),
                    width,
                )
            for row in rows:
                self.assertLessEqual(
                    row.message_container.geometry().bottom() + 1,
                    row.height(),
                    (width, row.setting_name),
                )

        manual = window._setting_widgets["manual_base_width_mm"]
        manual.set_error("Erster Fehler\nZweiter Fehler\nDritter Fehler\nVierter Fehler")
        window._refresh_geometry_section_layout(True)
        manual.message_expand_button.setChecked(True)
        self.app.processEvents()
        following = window._setting_widgets["maximum_expansion_angle_deg"]
        self.assertLessEqual(
            manual.geometry().bottom() + 1,
            following.geometry().top(),
        )
        manual.message_expand_button.setChecked(False)
        self.app.processEvents()

        expanded_height = window.geometry_settings_group.height()
        for row in rows:
            row.set_error(None)
            row.set_warning(None)
        window._refresh_geometry_section_layout(True)
        self.app.processEvents()
        self.assertLess(window.geometry_settings_group.height(), expanded_height)

    def test_abort_discards_retained_candidate_and_allows_fresh_generation(self) -> None:
        self._ready()
        window = self.window
        previous = SimpleNamespace(dispose=Mock())
        window.current_preview = previous
        window.preview_state = PreviewState.BUILDING
        window._joint_resume_active = True
        window._preview_cancel_requested = True
        window._on_preview_finished(window._preview_request_id)
        self.assertIsNone(window.current_preview)
        previous.dispose.assert_called_once_with()
        self.assertEqual(window.preview_state, PreviewState.EMPTY)
        self.assertEqual(window.preview_button.text(), "Kühlturm generieren")
        self.assertEqual(
            window.generation_intro_label.text(),
            "Die Generierung wurde manuell abgebrochen.\n"
            "Der bisherige Kühlturm wurde verworfen.",
        )

    def test_abort_restores_initial_space_below_original_preview(self) -> None:
        self._ready()
        window = self.window
        window.resize(1856, 1334)
        segment = LineSegment3D(Point3D(10, 10, .2), Point3D(20, 20, .2))
        window.source_preslice_result = SimpleNamespace(cleanup=Mock(), preview_source_data=SimpleNamespace(
            object_segments=(segment,),
            occupied_bounds=OccupiedBounds(10, 20, 10, 20),
            source_segment_count=1,
        ))
        window.analysis_snapshot = SimpleNamespace(maximum_print_z_mm=.2, layer_count=1)
        window.profile_match_result = SimpleNamespace(selected=SimpleNamespace(
            effective_profile=SimpleNamespace(effective_values={})
        ))
        window._show_original_object_preview()
        self.app.processEvents()
        preview = window.preview_dialog

        def bottom_gap() -> int:
            return (
                window.prediction_frame.rect().bottom()
                - preview.mapTo(
                    window.prediction_frame, preview.rect().bottomLeft()
                ).y()
            )

        initial_gap = bottom_gap()
        window.preview_state = PreviewState.BUILDING
        preview.set_building("Gemeinsamer Slice läuft")
        panel = window.joint_generation_dialog
        panel.begin(13, .25, 0, 12)
        panel.start_slice(0, 12)
        self.app.processEvents()
        window._finish_generation_cancelled()
        self.app.processEvents()

        self.assertFalse(preview.navigation_hint.isHidden())
        self.assertLessEqual(bottom_gap(), initial_gap + 2)
        QTest.qWait(60)
        self.app.processEvents()
        self.assertLessEqual(bottom_gap(), initial_gap + 2)

    def test_original_object_stays_unstale_until_a_tower_is_shown(self) -> None:
        self._ready()
        window = self.window
        dialog = window.preview_dialog
        segment = LineSegment3D(Point3D(1, 1, 0.2), Point3D(2, 2, 0.2))
        original = PreviewScene(
            object_segments=(segment,), tower_segments=(),
            bed_bounds=BedBounds(0, 100, 0, 100),
            tower_center_xy_mm=(0, 0),
            source_segment_count=1, displayed_segment_count=1,
            tower_height_mm=0, object_height_mm=0.2,
            object_layer_count=1, tower_layer_count=0,
        )
        dialog.set_original_object(original)
        window._invalidate_preview("Eine Kühlturmeinstellung wurde geändert.")
        self.assertIs(dialog.canvas.scene, original)
        self.assertEqual(window.preview_state, PreviewState.EMPTY)
        self.assertEqual(dialog.state, PreviewState.EMPTY)
        self.assertNotIn("Veraltet", dialog.state_label.text())

        dialog.set_building("Kühlturm wird generiert")
        self.assertNotIn("Veraltet", dialog.state_label.text())
        dialog.mark_stale()
        self.assertIs(dialog.canvas.scene, original)
        self.assertEqual(dialog.state, PreviewState.EMPTY)

        dialog.canvas.set_scene(replace(
            original, tower_segments=(segment,), tower_height_mm=0.2,
            tower_layer_count=1,
        ))
        window.current_preview = SimpleNamespace(dispose=Mock())
        window._invalidate_preview("Eine Kühlturmeinstellung wurde geändert.")
        self.assertEqual(window.preview_state, PreviewState.STALE)
        self.assertEqual(dialog.state, PreviewState.STALE)
        self.assertIn("Veraltet", dialog.state_label.text())

    def test_reset_defaults_uses_the_view_for_the_visible_scene(self) -> None:
        self._ready()
        window = self.window
        dialog = window.preview_dialog
        segment = LineSegment3D(Point3D(1, 1, 0.2), Point3D(2, 2, 0.2))
        original = PreviewScene(
            object_segments=(segment,), tower_segments=(),
            bed_bounds=BedBounds(0, 100, 0, 100),
            tower_center_xy_mm=(0, 0),
            source_segment_count=1, displayed_segment_count=1,
            tower_height_mm=0, object_height_mm=0.2,
            object_layer_count=1, tower_layer_count=0,
        )
        dialog.set_original_object(original)
        self.assertEqual((dialog.canvas.yaw_deg, dialog.canvas.pitch_deg), (-38.0, 28.0))
        dialog.canvas.side_view()
        window.reset_defaults()
        self.assertEqual((dialog.canvas.yaw_deg, dialog.canvas.pitch_deg), (-38.0, 28.0))

        tower_segment = LineSegment3D(Point3D(70, 50, 0.2), Point3D(72, 52, 0.2))
        dialog.canvas.set_scene(replace(
            original, tower_segments=(tower_segment,), tower_center_xy_mm=(71, 51),
            tower_height_mm=0.2, tower_layer_count=1,
        ))
        window.current_preview = SimpleNamespace(dispose=Mock())
        dialog.canvas.three_quarter_view()
        window.reset_defaults()
        self.assertEqual((dialog.canvas.yaw_deg, dialog.canvas.pitch_deg), (-38.0, 28.0))
        self.assertEqual(dialog.canvas.zoom, 1.0)

    def test_result_precedes_simulation_and_export_is_offered_after_finish(self) -> None:
        panel = self.window.joint_generation_dialog
        result_layout = panel.result_label.parentWidget().layout()
        self.assertIs(result_layout.itemAt(0).widget(), panel.result_label)
        self.assertIs(result_layout.itemAt(1).widget(), panel.simulation_label)
        panel.begin(10, 0.25, 0, 10)
        panel.start_slice(0, 10)
        panel.mark_finished(paused=False, can_continue=False)
        self.assertFalse(panel.export_button.isHidden())


class PreviewCircleSegmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_original_object_scene_keeps_all_view_buttons_working(self) -> None:
        dialog = PreviewDialog(embedded=True)
        self.addCleanup(dialog.close)
        dialog.show()
        segment = LineSegment3D(Point3D(1, 1, 0.2), Point3D(2, 2, 0.2))
        scene = PreviewScene(
            object_segments=(segment,), tower_segments=(),
            bed_bounds=BedBounds(0, 100, 0, 100),
            tower_center_xy_mm=(0, 0),
            source_segment_count=1, displayed_segment_count=1,
            tower_height_mm=0, object_height_mm=0.2,
            object_layer_count=1, tower_layer_count=0,
        )
        dialog.set_original_object(scene)
        self.app.processEvents()
        self.assertIs(dialog.canvas.scene, scene)
        self.assertFalse(dialog.tower_legend.isVisible())
        for button in (dialog.three_quarter_button, dialog.front_button,
                       dialog.side_button, dialog.top_button):
            self.assertTrue(button.isEnabled())
            button.click()
            self.assertIs(dialog.canvas.scene, scene)

    def test_segment_count_sits_above_height_without_moving_navigation(self) -> None:
        dialog = PreviewDialog(embedded=True)
        self.addCleanup(dialog.close)
        dialog.show()
        self.app.processEvents()
        segment = LineSegment3D(Point3D(1, 1, 0.2), Point3D(2, 2, 0.2))
        scene = PreviewScene(
            object_segments=(segment,),
            tower_segments=(segment,),
            bed_bounds=BedBounds(0, 100, 0, 100),
            tower_center_xy_mm=(20, 20),
            source_segment_count=1,
            displayed_segment_count=1,
            tower_height_mm=5,
            tower_circle_segments=30,
        )
        dialog.set_preview(SimpleNamespace(scene=scene, output_mode=OutputMode.STL))
        self.app.processEvents()
        labels = (
            dialog.tower_circle_segments_info_label,
            dialog.height_info_label,
            dialog.bed_info_label,
        )
        self.assertIn("Turm-Kreissegmente: ", labels[0].text())
        self.assertIn(">30</span>", labels[0].text())
        for upper, lower in zip(labels, labels[1:]):
            self.assertLess(upper.geometry().bottom(), lower.geometry().top())
        self.assertLess(
            labels[-1].geometry().bottom(), dialog.preview_info_header.height()
        )
        canvas_y = dialog.canvas.mapTo(dialog, QPoint(0, 0)).y()
        navigation_y = dialog.canvas.navigation_toggle.mapTo(dialog, QPoint(0, 0)).y()
        dialog.set_preview(
            SimpleNamespace(
                scene=replace(scene, tower_circle_segments=64),
                output_mode=OutputMode.STL,
            )
        )
        self.app.processEvents()
        self.assertIn(">64</span>", labels[0].text())
        self.assertEqual(dialog.canvas.mapTo(dialog, QPoint(0, 0)).y(), canvas_y)
        self.assertEqual(
            dialog.canvas.navigation_toggle.mapTo(dialog, QPoint(0, 0)).y(),
            navigation_y,
        )
        self.assertIs(
            dialog.canvas.navigation_toggle.parentWidget(), dialog.preview_frame
        )
        self.assertEqual(
            navigation_y - canvas_y,
            10 - dialog.layers_info_label.fontMetrics().lineSpacing(),
        )
        toggle_center = dialog.canvas.navigation_toggle.geometry().center()
        self.assertIs(
            dialog.preview_frame.childAt(toggle_center),
            dialog.canvas.navigation_toggle,
        )

    def test_navigation_follows_canvas_after_layout_move(self) -> None:
        dialog = PreviewDialog(embedded=True)
        self.addCleanup(dialog.close)
        dialog.show()
        segment = LineSegment3D(Point3D(1, 1, 0.2), Point3D(2, 2, 0.2))
        scene = PreviewScene(
            object_segments=(segment,), tower_segments=(),
            bed_bounds=BedBounds(0, 100, 0, 100),
            tower_center_xy_mm=(0, 0),
            source_segment_count=1, displayed_segment_count=1,
            tower_height_mm=0, object_height_mm=0.2,
            object_layer_count=1, tower_layer_count=0,
        )
        dialog.set_original_object(scene)
        self.app.processEvents()
        canvas = dialog.canvas
        toggle = canvas.navigation_toggle
        before = toggle.mapTo(dialog, QPoint(0, 0)).y()
        layer_info_edge = dialog.layers_info_label.mapTo(
            dialog, QPoint(0, dialog.layers_info_label.height())
        ).y()
        layer_line_spacing = dialog.layers_info_label.fontMetrics().lineSpacing()
        # Font registration in other GUI modules changes the default fallback
        # metrics. Check separation and the canvas-relative overlay position
        # instead of estimating the visible gap from a whole text line.
        self.assertGreater(before, layer_info_edge)
        self.assertEqual(
            before - canvas.mapTo(dialog, QPoint(0, 0)).y(),
            10 - layer_line_spacing,
        )
        dialog.preview_frame.layout().setEnabled(False)
        canvas.move(canvas.x(), canvas.y() + 18)
        self.app.processEvents()
        self.assertEqual(toggle.mapTo(dialog, QPoint(0, 0)).y(), before + 18)
        self.assertEqual(
            toggle.mapTo(dialog, QPoint(0, 0)).y() - layer_info_edge,
            before - layer_info_edge + 18,
        )


class SettingsMigrationTests(unittest.TestCase):
    def test_schema_15_removes_retired_controls_with_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            user_path = Path(directory) / "settings.json"
            original = json.dumps({
                "settings_schema_version": 15,
                "generation": {
                    "safety_factor": 1.5,
                    "mesh_segments": 32,
                    "minimum_object_tower_distance_mm": 50,
                },
            }).encode("utf-8")
            user_path.write_bytes(original)
            store = UserSettingsStore(user_path, ROOT / "config" / "default_settings.json")
            settings, payload = store.load()
            self.assertEqual(payload["settings_schema_version"], SETTINGS_SCHEMA_VERSION)
            self.assertNotIn("safety_factor", payload["generation"])
            self.assertNotIn("mesh_segments", payload["generation"])
            self.assertEqual(settings.minimum_object_tower_distance_mm, 5)
            self.assertIsNotNone(store.last_migration_backup)
            self.assertEqual(store.last_migration_backup.read_bytes(), original)
