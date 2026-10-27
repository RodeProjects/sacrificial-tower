from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
from threading import Event
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QPoint, QPointF, Qt, QTimer
from PySide6.QtTest import QTest

import test_preprocessor as fixture
import test_preprocessor_gui as gui_fixture
from cooling_tower.gui.generation_session import GenerationMode
from cooling_tower.gui.preprocessor_positions import PositionCanvas
from cooling_tower.gui.widgets.preview_canvas import PreviewCanvas
from cooling_tower.calibration.gcode_integration import parse_bed_geometry
from cooling_tower.preprocessor_placement import OriginalMotionIndex
from cooling_tower.preview.toolpath import PreviewCancelled
from cooling_tower.preprocessor_travel import safe_travel_path
from cooling_tower.gcode.parser import iter_parsed_gcode_lines


class PlacementContextTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.PreprocessorTests()
        self.fixture.setUp()
        self.request = self.fixture.request()

    def tearDown(self):
        self.fixture.tearDown()

    def test_editor_and_generation_share_exact_positions_without_writing_source(self):
        source = self.request.prepared_source.analysis_gcode_path
        original = source.read_bytes()
        with patch("cooling_tower.preprocessor.iter_parsed_gcode_lines", wraps=iter_parsed_gcode_lines) as capture:
            context = self.fixture.service.placement_context(self.request)
            centre, wait, routes = context.resolve()
            manual = replace(context.settings, automatic_position=False, automatic_wait_position=False,
                center_x_mm=centre[0], center_y_mm=centre[1], wait_x_mm=wait[0], wait_y_mm=wait[1])
            self.assertEqual(context.resolve(manual), (centre, wait, routes))
            self.assertEqual(capture.call_count, 1)
        self.assertFalse(self.fixture.service.temporary_root.exists())
        result = self.fixture.prepare(replace(self.request, settings=manual))
        self.assertEqual(result.scene.tower_center_xy_mm, centre)
        self.assertEqual(result.scene.wait_position_xy_mm, wait)
        self.assertEqual(source.read_bytes(), original)

    def test_manual_errors_identify_model_bed_and_tower_clearances(self):
        context = self.fixture.service.placement_context(self.request)
        centre, wait, _ = context.resolve()
        manual = replace(context.settings, automatic_position=False, automatic_wait_position=False,
            center_x_mm=centre[0], center_y_mm=centre[1], wait_x_mm=wait[0], wait_y_mm=wait[1])
        for settings, reason in (
            (replace(manual, center_x_mm=105, center_y_mm=105), "Turmquerschnitt und Modell"),
            (replace(manual, center_x_mm=-10), "Druckbettkante"),
            (replace(manual, wait_x_mm=105, wait_y_mm=105), "Warteposition: Der Abstand zum Modell"),
            (replace(manual, wait_x_mm=centre[0], wait_y_mm=centre[1]), "vollständigen Turmfuß"),
            (replace(manual, wait_x_mm=-10), "Warteposition: Der Abstand zur Druckbettkante"),
        ):
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                context.resolve(settings)

    def test_every_route_is_checked_and_cancellation_can_be_replaced(self):
        context = self.fixture.service.placement_context(self.request)
        centre, wait, _ = context.resolve()
        context = self.fixture.service.placement_context(self.request)
        with patch("cooling_tower.preprocessor.safe_travel_path", side_effect=ValueError("Hindernis blockiert den Weg")):
            with self.assertRaisesRegex(ValueError, "Fahrweg: Hindernis"):
                context.resolve(replace(context.settings, automatic_position=False, automatic_wait_position=False,
                    center_x_mm=centre[0], center_y_mm=centre[1], wait_x_mm=wait[0], wait_y_mm=wait[1]))
        cancelled = Event()
        cancelled.set()
        with self.assertRaises(PreviewCancelled):
            context.resolve(event=cancelled)
        self.assertIsNotNone(context.resolve(event=Event())[1])
        with self.assertRaisesRegex(ValueError, "Platzierungsgrundlage"):
            context.resolve(replace(context.settings, clearance_mm=15))

    def test_shared_context_serializes_checks_and_cancels_waiting_call(self):
        context = self.fixture.service.placement_context(self.request)
        centre, wait, _ = context.resolve()
        context = self.fixture.service.placement_context(self.request)
        manual = replace(context.settings, automatic_position=False, automatic_wait_position=False,
            center_x_mm=centre[0], center_y_mm=centre[1], wait_x_mm=wait[0], wait_y_mm=wait[1])
        entered, release, cancelled = Event(), Event(), Event()
        def blocked_route(*args, **kwargs):
            entered.set()
            release.wait(3)
            return safe_travel_path(*args, **kwargs)
        with ThreadPoolExecutor(max_workers=2) as pool, patch("cooling_tower.preprocessor.safe_travel_path", side_effect=blocked_route):
            first = pool.submit(context.resolve, manual, event=Event())
            try:
                self.assertTrue(entered.wait(2))
                second = pool.submit(context.resolve, manual, event=cancelled)
                cancelled.set()
                with self.assertRaises(PreviewCancelled):
                    second.result(timeout=2)
            finally:
                release.set()
            self.assertEqual(first.result(timeout=2)[0], centre)

    def test_region_point_checks_agree_with_full_placement_validation(self):
        context = self.fixture.service.placement_context(self.request)
        centre, wait, _ = context.resolve()
        settings = replace(context.settings, automatic_position=False, automatic_wait_position=False,
            center_x_mm=centre[0], center_y_mm=centre[1], wait_x_mm=wait[0], wait_y_mm=wait[1])
        for kind in ("tower", "wait"):
            for point in ((5, 5), (30, 30), (105, 105), (200, 190), (-5, 30), centre, wait):
                with self.subTest(kind=kind, point=point):
                    names = ("center_x_mm", "center_y_mm") if kind == "tower" else ("wait_x_mm", "wait_y_mm")
                    manual = replace(settings, **dict(zip(names, point)))
                    try:
                        context.resolve(manual)
                    except ValueError:
                        expected = False
                    else:
                        expected = True
                    self.assertEqual(context.position_valid(kind, point, settings), expected)


class PositionEditorGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        gui_fixture.PreprocessorGuiTests.setUpClass()
        cls.app = gui_fixture.PreprocessorGuiTests.app

    def setUp(self):
        self.harness = gui_fixture.PreprocessorGuiTests()
        self.harness.setUp()
        self.window, self.controller = self.harness.window, self.harness.controller
        self.panel = self.window.preprocessor_panel
        self.window.resize(1900, 1000)
        self.window.select_generation_mode(GenerationMode.PREPROCESSOR)

    def tearDown(self):
        self.harness.tearDown()

    def settle(self, predicate, timeout=10):
        end = time.monotonic()+timeout
        while not predicate() and time.monotonic() < end:
            self.app.processEvents()
            QTest.qWait(10)
        self.assertTrue(predicate(), "Der Positionseditor hat die Prüfung nicht abgeschlossen.")

    def open_editor(self):
        self.controller.open_position_editor()
        dialog = self.controller.position_dialog
        self.assertIsNotNone(dialog)
        self.settle(lambda: dialog.job_id is None and not dialog._timer.isActive())
        return dialog

    def test_automatic_seed_drag_both_positions_validate_and_apply_atomically(self):
        before = self.panel.settings()
        source = self.harness.request.prepared_source.analysis_gcode_path
        original = source.read_bytes()
        dialog = self.open_editor()
        self.assertTrue(dialog.apply_button.isEnabled(), dialog.status.text())
        self.assertNotEqual(dialog.canvas.positions["tower"], (before.center_x_mm, before.center_y_mm))
        for key in ("tower", "wait"):
            xy = dialog.canvas.positions[key]
            target = (30, 30) if key == "tower" else (30, 55)
            canvas = dialog.canvas
            start = canvas.screen(xy).toPoint()
            end = canvas.screen(target).toPoint()
            QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
            QTest.mouseMove(canvas, end, delay=20)
            QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
            self.assertFalse(dialog.apply_button.isEnabled())
            self.assertFalse(dialog.automatic[key].isChecked())
            self.settle(lambda: dialog.apply_button.isEnabled() and dialog.job_id is None)
        self.assertEqual(self.panel.settings(), before)
        positions = dict(dialog.canvas.positions)
        dialog.accept()
        self.app.processEvents()
        after = self.panel.settings()
        self.assertFalse(after.automatic_position)
        self.assertFalse(after.automatic_wait_position)
        self.assertAlmostEqual(after.center_x_mm, positions["tower"][0], places=2)
        self.assertAlmostEqual(after.wait_y_mm, positions["wait"][1], places=2)
        self.assertEqual(source.read_bytes(), original)
        self.assertIsNone(self.controller.job_id)

    def test_invalid_move_blocks_apply_cancel_keeps_existing_result(self):
        result = self.harness.wait_for_result()
        before = self.panel.settings()
        dialog = self.open_editor()
        dialog.move_position("tower", (105, 105))
        self.settle(lambda: dialog.job_id is None and not dialog._timer.isActive())
        self.assertFalse(dialog.apply_button.isEnabled())
        self.assertIn("Modell", dialog.status.text())
        dialog.accept()
        self.assertTrue(dialog.isVisible())
        self.assertIs(self.controller.session.preview, result)
        dialog.reject()
        self.app.processEvents()
        self.assertEqual(self.panel.settings(), before)
        self.assertIs(self.controller.session.preview, result)

    def test_stale_check_cannot_enable_apply_and_source_change_is_rejected(self):
        dialog = self.open_editor()
        context = dialog.context
        revision = dialog.revision
        solution = context.resolve()
        dialog.move_position("tower", (105, 105))
        dialog._checked(revision, (context, solution, ""))
        self.assertFalse(dialog.apply_button.isEnabled())
        self.assertEqual(dialog.canvas.positions["tower"], (105, 105))
        dialog.move_position("tower", (30, 30))
        self.settle(lambda: dialog.apply_button.isEnabled() and dialog.job_id is None)
        self.harness.request.prepared_source.analysis_gcode_path.write_text("changed")
        dialog.accept()
        self.assertTrue(dialog.isVisible())
        self.assertFalse(dialog.apply_button.isEnabled())
        self.assertIn("verändert", dialog.status.text())
        dialog.reject()

    def test_close_during_initial_check_cancels_managed_worker(self):
        started = Event()
        def wait_for_cancel(request, *, cancellation_event, progress_callback=None):
            progress_callback(18, "Modellbahnen rekonstruieren …")
            started.set()
            cancellation_event.wait(5)
            raise PreviewCancelled()
        with patch.object(self.controller.service, "placement_context", side_effect=wait_for_cancel):
            self.controller.open_position_editor()
            dialog = self.controller.position_dialog
            self.settle(started.is_set)
            self.settle(lambda: dialog.canvas.busy_overlay.progress.value() == 18)
            self.assertTrue(dialog.canvas.busy_overlay.isVisible())
            self.assertIn("Modellbahnen", dialog.canvas.busy_overlay.step.text())
            self.assertTrue(dialog.canvas.busy_overlay.surface.renderer().isAnimationEnabled())
            job_id = dialog.job_id
            dialog.reject()
            self.settle(lambda: not any(job.job_id == job_id for job in self.window.background_job_manager.active_jobs()))
        self.assertIsNone(self.controller.position_dialog)

    def test_generation_and_reopened_editor_reuse_exact_cached_positions(self):
        result = self.harness.wait_for_result()
        with patch.object(self.controller.service, "placement_context", side_effect=AssertionError("Neuberechnung")):
            self.controller.open_position_editor()
            dialog = self.controller.position_dialog
            self.assertIsNone(dialog.job_id)
            self.assertTrue(dialog.apply_button.isEnabled())
            self.assertEqual(dialog.canvas.positions["tower"], result.scene.tower_center_xy_mm)
            self.assertEqual(dialog.canvas.positions["wait"], result.scene.wait_position_xy_mm)
            self.assertFalse(dialog.canvas.busy_overlay.isVisible())
            dialog.reject()

    def test_reopened_unedited_manual_positions_reuse_automatic_seed_immediately(self):
        self.panel.automatic["automatic_position"].setChecked(False)
        self.panel.automatic["automatic_wait_position"].setChecked(False)
        dialog = self.open_editor()
        positions = dict(dialog.canvas.positions)
        dialog.reject()
        self.app.processEvents()
        with patch.object(self.controller.service, "placement_context", side_effect=AssertionError("Neuberechnung")):
            self.controller.open_position_editor()
            dialog = self.controller.position_dialog
            self.assertIsNone(dialog.job_id)
            self.assertTrue(dialog.apply_button.isEnabled())
            self.assertEqual(dialog.canvas.positions, positions)
            dialog.reject()
            self.app.processEvents()
            self.controller.open_position_editor()
            dialog = self.controller.position_dialog
            self.assertIsNone(dialog.job_id)
            self.assertTrue(dialog.apply_button.isEnabled())
            dialog.reject()

    def test_reopened_invalid_manual_position_keeps_marker_and_cached_error(self):
        self.panel.automatic["automatic_position"].setChecked(False)
        self.panel.inputs["center_x_mm"].setValue(105)
        self.panel.inputs["center_y_mm"].setValue(105)
        dialog = self.open_editor()
        self.assertFalse(dialog.apply_button.isEnabled())
        self.assertEqual(dialog.canvas.positions["tower"], (105, 105))
        message = dialog.status.text()
        dialog.reject()
        self.app.processEvents()
        self.controller.open_position_editor()
        dialog = self.controller.position_dialog
        self.assertIsNone(dialog.job_id)
        self.assertEqual(dialog.canvas.positions["tower"], (105, 105))
        self.assertEqual(dialog.status.text(), message)
        self.assertFalse(dialog.apply_button.isEnabled())
        dialog.reject()

    def test_editor_cache_reuses_cancelled_edits_only_for_matching_settings_and_sources(self):
        dialog = self.open_editor()
        original = dict(dialog.canvas.positions)
        dialog.move_position("tower", (30, 30))
        self.settle(lambda: dialog.apply_button.isEnabled() and dialog.job_id is None)
        dialog.reject()
        self.app.processEvents()
        cache = self.controller._position_cache
        with patch.object(self.controller.service, "placement_context", side_effect=AssertionError("Neuberechnung")):
            self.controller.open_position_editor()
            dialog = self.controller.position_dialog
            self.assertEqual(dialog.canvas.positions, original)
            self.assertIsNone(dialog.job_id)
            dialog.reject()
        self.app.processEvents()
        self.panel.automatic["automatic_diameter"].setChecked(False)
        self.panel.inputs["diameter_mm"].setValue(20)
        dialog = self.open_editor()
        self.assertIsNot(self.controller._position_cache, cache)
        self.assertTrue(dialog.apply_button.isEnabled())
        dialog.reject()
        self.app.processEvents()
        cache = self.controller._position_cache
        self.harness.request.profile.effective_values["extruder_clearance_radius"] = 13
        dialog = self.open_editor()
        self.assertIsNot(self.controller._position_cache, cache)
        self.assertEqual(dialog.context.printhead.radius_mm, 13)
        dialog.reject()
        self.app.processEvents()
        cache = self.controller._position_cache
        self.harness.request.prepared_source.analysis_gcode_path.write_text("changed")
        self.controller.open_position_editor()
        dialog = self.controller.position_dialog
        self.assertIsNot(self.controller._position_cache, cache)
        self.settle(lambda: dialog.job_id is None)
        self.assertFalse(dialog.apply_button.isEnabled())
        self.assertIn("verändert", dialog.status.text())
        dialog.reject()

    def test_edge_clearance_is_validated_and_applied_with_shared_setting(self):
        dialog = self.open_editor()
        self.assertEqual(dialog.edge_spin.value(), 5)
        dialog.edge_spin.setValue(100)
        self.settle(lambda: dialog.job_id is None and not dialog._timer.isActive())
        self.assertFalse(dialog.apply_button.isEnabled())
        dialog.edge_spin.setValue(8)
        self.settle(lambda: dialog.apply_button.isEnabled() and dialog.job_id is None)
        self.assertEqual(dialog.canvas.edge_clearance_mm, 8)
        dialog.accept()
        self.app.processEvents()
        self.assertEqual(self.panel.settings().edge_clearance_mm, 8)
        with patch.object(self.controller.service, "placement_context", side_effect=AssertionError("Neuberechnung")):
            self.controller.open_position_editor()
            dialog = self.controller.position_dialog
            self.assertIsNone(dialog.job_id)
            self.assertEqual(dialog.edge_spin.value(), 8)
            dialog.reject()

    def test_embedded_controls_reset_each_position_and_both_with_fit_feedback(self):
        dialog = self.open_editor()
        canvas = dialog.canvas
        self.assertIs(canvas.fit_button.parentWidget(), canvas)
        self.assertIs(canvas.reset_button.parentWidget(), canvas)
        self.assertFalse(canvas.reset_button.isEnabled())
        self.assertFalse(canvas.fit_button.property("needsFit"))
        start = QPoint(100, 100)
        QTest.mousePress(canvas, Qt.MouseButton.RightButton, pos=start)
        QTest.mouseMove(canvas, start+QPoint(25, 15))
        QTest.mouseRelease(canvas, Qt.MouseButton.RightButton, pos=start+QPoint(25, 15))
        self.assertTrue(canvas.fit_button.property("needsFit"))
        canvas.fit_button.click()
        self.assertEqual(canvas.pan, QPointF())
        self.assertFalse(canvas.fit_button.property("needsFit"))
        for key, xy in (("tower", (30, 30)), ("wait", (30, 55))):
            dialog.move_position(key, xy)
            self.settle(lambda: dialog.apply_button.isEnabled() and dialog.job_id is None)
        self.assertTrue(canvas.reset_button.isEnabled())
        dialog.reset_buttons["tower"].click()
        self.settle(lambda: dialog.apply_button.isEnabled() and dialog.job_id is None)
        self.assertTrue(dialog.automatic["tower"].isChecked())
        self.assertFalse(dialog.automatic["wait"].isChecked())
        self.assertEqual(tuple(e.value() for e in dialog.editors["wait"]), (30, 55))
        canvas.reset_button.click()
        self.settle(lambda: dialog.apply_button.isEnabled() and dialog.job_id is None)
        self.assertTrue(all(box.isChecked() for box in dialog.automatic.values()))
        self.assertFalse(canvas.reset_button.isEnabled())
        self.assertFalse(hasattr(canvas, "printhead"))
        self.assertEqual(len(dialog.legend.labels), 5)
        self.assertEqual([column.x() for column in dialog.control_columns], sorted(column.x() for column in dialog.control_columns))
        dialog.reject()

    def test_gcode_preview_busy_overlay_reports_steps_and_stops_after_cancel(self):
        started = Event()
        def waiting_prepare(request, *, cancellation_event, progress_callback):
            progress_callback(24, "Originalfahrten erfassen …")
            started.set()
            cancellation_event.wait(5)
            raise PreviewCancelled()
        with patch.object(self.controller.service, "prepare", side_effect=waiting_prepare):
            self.controller.generate()
            self.settle(started.is_set)
            overlay = self.panel.canvas.busy_overlay
            self.settle(lambda: overlay.progress.value() == 24)
            self.assertTrue(overlay.isVisible())
            self.assertIn("Originalfahrten", overlay.step.text())
            frame = overlay.grab().toImage()
            QTest.qWait(160)
            self.assertEqual(overlay.progress.value(), 24)
            self.assertNotEqual(overlay.grab().toImage(), frame)
            animation_start = overlay._clock.msecsSinceReference()
            self.controller.progress(self.controller.request_id, 60, "Fahrwege prüfen …")
            self.assertEqual(overlay._clock.msecsSinceReference(), animation_start)
            self.assertEqual(overlay.progress.value(), 60)
            self.controller.cancel()
            self.settle(lambda: self.controller.job_id is None)
            self.assertFalse(overlay.isVisible())
            self.assertFalse(overlay.surface.renderer().isAnimationEnabled())

    def test_position_recheck_preserves_scene_and_does_not_redraw_model_each_animation_frame(self):
        dialog = self.open_editor()
        canvas = dialog.canvas
        with patch.object(canvas, "_paint_scene", wraps=canvas._paint_scene) as painted:
            dialog.move_position("tower", (30, 30))
            dialog._timer.stop()
            self.app.processEvents()
            self.assertTrue(canvas.busy_overlay._subdued)
            self.assertFalse(canvas.busy_overlay.panel.isVisible())
            self.assertTrue(dialog.validation_progress.isVisible())
            self.assertTrue(canvas.busy_overlay._protected_region().contains(canvas.screen((110, 110))))
            first = canvas.grab().toImage()
            draws = painted.call_count
            QTest.qWait(160)
            self.assertNotEqual(canvas.grab().toImage(), first)
            self.assertEqual(painted.call_count, draws)
            dialog.move_position("tower", (35, 35))
            dialog._timer.stop()
            self.app.processEvents()
            self.assertGreater(painted.call_count, draws)
            self.assertEqual(canvas.positions["tower"], (35, 35))
        dialog.reject()

    def test_drag_regions_only_show_for_active_target_and_clear_on_release(self):
        dialog = self.open_editor()
        canvas = dialog.canvas
        start = canvas.screen(canvas.positions["tower"]).toPoint()
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
        self.settle(lambda: canvas.region_map is not None and 2 not in canvas.region_map.states, timeout=20)
        self.assertEqual(dialog._dragging, "tower")
        self.assertIn(0, canvas.region_map.states)
        self.assertIn(1, canvas.region_map.states)
        regions = canvas.region_map
        index = regions.states.index(1)
        x, y = index % regions.columns, index // regions.columns
        b = regions.bounds
        point = (b.minimum_x_mm+(x+.5)*(b.maximum_x_mm-b.minimum_x_mm)/regions.columns,
            b.maximum_y_mm-(y+.5)*(b.maximum_y_mm-b.minimum_y_mm)/regions.rows)
        settings = dialog.current_settings()
        settings = replace(settings, automatic_position=False, automatic_wait_position=False,
            center_x_mm=point[0], center_y_mm=point[1])
        self.assertIsNotNone(dialog.context.resolve(settings))
        target = canvas.screen((30, 30)).toPoint()
        QTest.mouseMove(canvas, target)
        self.assertIs(canvas.region_map, regions)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=target)
        self.assertIsNone(canvas.region_map)
        self.assertIsNone(dialog._dragging)
        self.settle(lambda: dialog.apply_button.isEnabled() and dialog.job_id is None)
        self.assertFalse(hasattr(canvas, "printhead"))
        dialog.reject()

    def test_dense_model_continuous_drag_reuses_drawing_and_regions_without_stalling(self):
        dialog = self.open_editor()
        self.settle(lambda: dialog._warm_job_id is None)
        canvas = dialog.canvas
        # Display complexity must not multiply the work for every mouse move.
        canvas.segments = tuple(canvas.segments)*1200
        dialog.context = replace(dialog.context, object_segments=canvas.segments)
        canvas.repaint()
        intervals, moves = [], []
        last = [time.monotonic()]
        timer = QTimer()
        def beat():
            now = time.monotonic()
            intervals.append(now-last[0])
            last[0] = now
        timer.timeout.connect(beat)
        timer.start(10)
        try:
            with patch.object(canvas, "_paint_model", wraps=canvas._paint_model) as model_paints:
                for kind, target in (("tower", (30, 30)), ("wait", (30, 60))):
                    start = canvas.screen(canvas.positions[kind]).toPoint()
                    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
                    regions = canvas.region_map
                    self.assertIsNotNone(regions, "Ablageflächen müssen schon beim Ziehbeginn bereitstehen")
                    self.assertEqual(set(regions.states), {0, 1})
                    for offset in range(24):
                        point = canvas.screen((target[0]+offset*.3, target[1]+offset*.15)).toPoint()
                        before = time.monotonic()
                        QTest.mouseMove(canvas, point)
                        QTest.qWait(5)
                        moves.append(time.monotonic()-before)
                        self.assertIs(canvas.region_map, regions)
                        self.assertEqual(tuple(e.value() for e in dialog.editors[kind]), canvas.positions[kind])
                    self.assertNotEqual(canvas.screen(canvas.positions[kind]).toPoint(), start)
                    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=point)
                    self.assertIsNone(canvas.region_map)
                    self.settle(lambda: dialog.job_id is None and not dialog._timer.isActive() and dialog._warm_job_id is None)
                    self.assertTrue(dialog.apply_button.isEnabled(), dialog.status.text())
                self.assertEqual(model_paints.call_count, 0)
            self.assertLess(max(moves), .25, "Mausbewegung blockiert die Oberfläche")
            self.assertLess(max(intervals), .35, "Ereignisschleife wird beim Ziehen angehalten")
        finally:
            timer.stop()
            dialog.reject()

    def test_fast_drag_into_model_keeps_final_coordinate_and_blocks_apply(self):
        dialog = self.open_editor()
        canvas = dialog.canvas
        start = canvas.screen(canvas.positions["tower"]).toPoint()
        target = canvas.screen((105, 105)).toPoint()
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(canvas, target)
        moved = canvas.positions["tower"]
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=target)
        self.settle(lambda: dialog.job_id is None and not dialog._timer.isActive())
        self.assertEqual(canvas.positions["tower"], moved)
        self.assertFalse(dialog.apply_button.isEnabled())
        self.assertIn("Modell", dialog.status.text())
        dialog.reject()

    def test_drag_outline_checks_actual_point_and_changes_green_to_red_before_release(self):
        dialog = self.open_editor()
        canvas = dialog.canvas
        for kind in ("tower", "wait"):
            start = canvas.screen(canvas.positions[kind]).toPoint()
            QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
            target = ((dialog.context.reserved_radius_mm+dialog.edge_spin.value()+.6, 30)
                if kind == "tower" else (30, 60))
            QTest.mouseMove(canvas, canvas.screen(target).toPoint())
            self.settle(lambda: canvas._drag_valid is True)
            self.assertEqual(dialog._dragging, kind)
            self.assertFalse(dialog.apply_button.isEnabled())
            if kind == "tower":
                self.assertFalse(canvas.region_valid(canvas.positions[kind]), "Grenzzelle soll konservativ rot bleiben")
                canvas.set_regions(canvas.region_map)
                self.assertTrue(canvas._drag_valid, "Ein späteres Raster darf die genaue Punktprüfung nicht überschreiben")
            image = canvas.grab().toImage()
            centre = canvas.screen(canvas.positions[kind])
            radius = canvas.base_width_mm*canvas.transform()[0]/2 if kind == "tower" else 7
            def ring_has(red, green, blue):
                x, y = round(centre.x()+radius), round(centre.y())
                return any(abs(image.pixelColor(xx, yy).red()-red) < 12
                    and abs(image.pixelColor(xx, yy).green()-green) < 12
                    and abs(image.pixelColor(xx, yy).blue()-blue) < 12
                    for xx in range(x-2, x+3) for yy in range(y-2, y+3))
            self.assertTrue(ring_has(67, 217, 138))
            invalid = canvas.screen((105, 105)).toPoint()
            QTest.mouseMove(canvas, invalid)
            self.settle(lambda: canvas._drag_valid is False)
            centre = canvas.screen(canvas.positions[kind])
            image = canvas.grab().toImage()
            self.assertTrue(ring_has(255, 116, 110))
            QTest.mouseMove(canvas, canvas.screen(target).toPoint())
            self.settle(lambda: canvas._drag_valid is True)
            QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=canvas.screen(target).toPoint())
            self.settle(lambda: dialog.apply_button.isEnabled() and dialog.job_id is None)
        dialog.reject()

    def test_close_during_drag_cancels_worker_waiting_for_next_mouse_coordinate(self):
        dialog = self.open_editor()
        canvas = dialog.canvas
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=canvas.screen(canvas.positions["tower"]).toPoint())
        point_job = dialog._point_job_id
        self.assertIsNotNone(point_job)
        self.settle(lambda: canvas._drag_valid is not None)
        dialog.reject()
        self.settle(lambda: not any(j.job_id == point_job for j in dialog.manager.active_jobs()))

    def test_fast_drag_coalesces_checks_and_ignores_feedback_for_previous_coordinate(self):
        dialog = self.open_editor()
        canvas = dialog.canvas
        entered, release, calls = Event(), Event(), []
        original = dialog.context.position_valid
        def check(kind, point, settings, *, event):
            calls.append(point)
            if len(calls) == 1:
                entered.set()
                release.wait(3)
                return True
            return original(kind, point, settings, event=event)
        dialog.context = replace(dialog.context, position_valid=check)
        try:
            start = canvas.positions["tower"]
            QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=canvas.screen(start).toPoint())
            self.settle(entered.is_set)
            for i in range(20):
                QTest.mouseMove(canvas, canvas.screen((30+i*3, 30+i*3)).toPoint())
            invalid = canvas.screen((105, 105)).toPoint()
            QTest.mouseMove(canvas, invalid)
            self.assertFalse(canvas._drag_valid)
            dialog._drag_point_checked(dialog._point_token, start, True)
            self.assertFalse(canvas._drag_valid)
            release.set()
            self.settle(lambda: len(calls) == 2)
            self.assertEqual(calls[-1], canvas.positions["tower"])
            self.assertFalse(canvas._drag_valid)
            QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=invalid)
            self.settle(lambda: dialog.job_id is None and not dialog._timer.isActive())
            self.assertFalse(dialog.apply_button.isEnabled())
        finally:
            release.set()
            dialog.reject()

    def test_repeated_position_changes_do_not_restart_pending_field_preparation(self):
        dialog = self.open_editor()
        self.settle(lambda: dialog._warm_job_id is None)
        entered, release = Event(), Event()
        prepare = dialog.context.regions.prepare
        def delayed_prepare(*args, **kwargs):
            entered.set()
            release.wait(3)
            return prepare(*args, **kwargs)
        try:
            with patch.object(dialog.context.regions, "prepare", side_effect=delayed_prepare), \
                    patch.object(dialog.context.regions, "immediate_regions", return_value=None):
                dialog.context.regions._maps.clear()
                dialog._warm_regions()
                self.settle(entered.is_set)
                job_id = dialog._warm_job_id
                for x in (30, 31, 32):
                    dialog.move_position("tower", (x, 30))
                    dialog._warm_regions()
                    self.assertEqual(dialog._warm_job_id, job_id)
                    self.assertFalse(dialog.manager.job(job_id).cancel_requested)
                release.set()
                self.settle(lambda: dialog._warm_job_id is None and not dialog._warm_pending)
            self.settle(lambda: dialog.job_id is None and not dialog._timer.isActive())
            self.assertTrue(dialog.apply_button.isEnabled(), dialog.status.text())
        finally:
            release.set()
            dialog.reject()

    def test_close_cancels_pending_drag_field_preparation(self):
        dialog = self.open_editor()
        self.settle(lambda: dialog._warm_job_id is None)
        entered = Event()
        def wait_for_cancel(edge, *, event):
            entered.set()
            event.wait(3)
            raise PreviewCancelled()
        with patch.object(dialog.context.regions, "prepare", side_effect=wait_for_cancel), \
                patch.object(dialog.context.regions, "immediate_regions", return_value=None):
            dialog.context.regions._maps.clear()
            dialog._warm_regions()
            self.settle(entered.is_set)
            job_id = dialog._warm_job_id
            dialog.reject()
            self.settle(lambda: not any(j.job_id == job_id for j in dialog.manager.active_jobs()))

    def test_numeric_drafts_wait_for_commit_and_enter_does_not_apply_dialog(self):
        from cooling_tower.gui.preprocessor_positions import PositionWorker
        dialog = self.open_editor()
        dialog.automatic["tower"].setChecked(False)
        self.settle(lambda: dialog.apply_button.isEnabled() and dialog.job_id is None and not dialog._timer.isActive())
        editor = dialog.editors["tower"][0]
        previous = editor.value()
        text = f"{previous:.2f}000"
        with patch("cooling_tower.gui.preprocessor_positions.PositionWorker", wraps=PositionWorker) as worker:
            editor.setFocus()
            editor.selectAll()
            QTest.keyClicks(editor.lineEdit(), text)
            QTest.qWait(250)
            self.assertEqual(editor.cleanText(), text)
            self.assertEqual(editor.value(), previous)
            self.assertFalse(dialog.apply_button.isEnabled())
            self.assertIsNone(dialog.job_id)
            worker.assert_not_called()
        QTest.keyClick(editor, Qt.Key.Key_Return)
        self.settle(lambda: dialog.apply_button.isEnabled() and dialog.job_id is None)
        self.assertIs(self.controller.position_dialog, dialog)
        self.assertTrue(dialog.isVisible())
        self.assertEqual(editor.value(), previous)
        dialog.reject()

    def test_edge_clearance_draft_waits_for_focus_loss_before_rechecking(self):
        from cooling_tower.gui.preprocessor_positions import PositionWorker
        dialog = self.open_editor()
        editor = dialog.edge_spin
        with patch("cooling_tower.gui.preprocessor_positions.PositionWorker", wraps=PositionWorker) as worker:
            editor.setFocus()
            editor.selectAll()
            QTest.keyClicks(editor.lineEdit(), "8.004")
            QTest.qWait(250)
            self.assertEqual(editor.cleanText(), "8.004")
            self.assertEqual(editor.value(), 5)
            self.assertEqual(dialog.canvas.edge_clearance_mm, 5)
            self.assertFalse(dialog.apply_button.isEnabled())
            worker.assert_not_called()
        QTest.mouseClick(dialog.canvas.fit_button, Qt.MouseButton.LeftButton)
        self.settle(lambda: dialog.job_id is None and not dialog._timer.isActive())
        self.assertEqual(editor.value(), 8)
        self.assertEqual(dialog.canvas.edge_clearance_mm, 8)
        self.assertEqual(editor.text(), "8 mm")
        self.assertIs(self.controller.position_dialog, dialog)
        dialog.reject()

    def test_typed_incomplete_coordinate_blocks_apply_and_recovers(self):
        dialog = self.open_editor()
        dialog.automatic["tower"].setChecked(False)
        self.settle(lambda: dialog.apply_button.isEnabled() and dialog.job_id is None and not dialog._timer.isActive())
        editor = dialog.editors["tower"][0]
        editor.setFocus()
        editor.selectAll()
        QTest.keyClicks(editor.lineEdit(), "-")
        self.settle(lambda: dialog.job_id is None and not dialog._timer.isActive())
        self.assertFalse(dialog.apply_button.isEnabled())
        self.assertIn("gültige Koordinaten", dialog.status.text())
        editor.selectAll()
        QTest.keyClicks(editor.lineEdit(), editor.locale().toString(30., "f", 2))
        self.assertFalse(dialog.apply_button.isEnabled())
        QTest.keyClick(editor, Qt.Key.Key_Return)
        self.settle(lambda: dialog.apply_button.isEnabled() and dialog.job_id is None)
        dialog.reject()

    def test_settings_change_closes_editor_and_no_tower_disables_apply(self):
        self.open_editor()
        self.panel.inputs["clearance_mm"].setValue(15)
        self.assertIsNone(self.controller.position_dialog)
        self.panel.automatic["automatic_target_time"].setChecked(False)
        self.panel.inputs["target_layer_time_s"].setValue(.1)
        dialog = self.open_editor()
        self.assertFalse(dialog.apply_button.isEnabled())
        self.assertEqual(dialog.context.height_mm, 0)
        self.assertIn("kein Turm", dialog.status.text())
        dialog.reject()

    def test_negative_bed_origin_zoom_pan_and_outside_coordinates_remain_exact(self):
        geometry = parse_bed_geometry({"bed_shape": ["-100x-100", "100x-100", "100x100", "-100x100"]})
        canvas = PositionCanvas(geometry)
        try:
            canvas.resize(700, 600)
            canvas.zoom, canvas.pan = 2.3, QPointF(32, -17)
            for point in ((-40, -55), (0, 0), (150, -120)):
                actual = canvas.world(canvas.screen(point))
                self.assertAlmostEqual(actual[0], point[0])
                self.assertAlmostEqual(actual[1], point[1])
            origin, x, y = canvas.screen((0, 0)), canvas.screen((10, 0)), canvas.screen((0, 10))
            self.assertGreater(x.x(), origin.x())
            self.assertLess(y.y(), origin.y())
            canvas.fit()
            self.assertEqual(canvas.zoom, 1)
            self.assertEqual(canvas.pan, QPointF())
        finally:
            canvas.deleteLater()
            self.app.processEvents()

    def test_minimum_sidebar_gap_combined_fields_and_coloured_legends(self):
        self.window.resize(2400, 1100)
        self.panel.advanced_group.setChecked(True)
        for flag in ("automatic_position", "automatic_wait_position"):
            self.panel.automatic[flag].setChecked(False)
        for _ in range(8):
            self.app.processEvents()
        self.assertTrue(self.panel.columns.is_two_column())
        left_width = self.panel.columns.splitter.sizes()[0]
        self.assertLessEqual(left_width, self.panel.settings_column.minimumSizeHint().width()+1)
        for row in self.panel.rows.values():
            if not row.isVisible():
                continue
            editor = row.editor
            # The first right-hand item is the automatic label when present.
            item = row.layout().itemAtPosition(0, 2).widget()
            text_right = row.label.x()+row.label.fontMetrics().horizontalAdvance(row.label.text())
            self.assertGreaterEqual(item.x()-text_right, 30)
            self.assertEqual(row.reset_button.x()-editor.geometry().right()-1, 6)
        self.assertEqual([swatch.color for swatch in self.panel.legend.swatches], [PreviewCanvas.OBJECT_COLOR,
            PreviewCanvas.TOWER_COLOR, PreviewCanvas.WAIT_POSITION_COLOR, PreviewCanvas.WAIT_TRAVEL_COLOR,
            PreviewCanvas.TOWER_TRAVEL_COLOR, PreviewCanvas.BRIM_COLOR, PreviewCanvas.SEAM_COLOR])
        self.assertTrue(self.panel.timing_toggle.isChecked())
        self.assertFalse(self.panel.time_chart.isVisible())
        self.assertFalse(hasattr(self.panel, "summary"))

    def test_footer_grows_for_progress_and_wrapped_errors_then_shrinks(self):
        panel = self.panel
        for _ in range(8):
            self.app.processEvents()
        original_height = panel.footer_widget.height()
        panel.progress.show()
        panel.status.setText("Druckzustände werden geprüft …\n" + "Keine sichere Turm- und Warteposition gefunden. "*12)
        for _ in range(12):
            self.app.processEvents()
        self.assertGreater(panel.footer_widget.height(), original_height)
        for widget in (panel.status, panel.progress, panel.reset_button, panel.generate_button):
            bottom = widget.mapTo(panel.footer_widget, QPoint(0, widget.height())).y()
            self.assertLessEqual(bottom, panel.footer_widget.height()-8)
        panel.progress.hide()
        panel.status.setText("Bereit.")
        for _ in range(12):
            self.app.processEvents()
        self.assertLessEqual(panel.footer_widget.height(), original_height)


if __name__ == "__main__":
    unittest.main()
