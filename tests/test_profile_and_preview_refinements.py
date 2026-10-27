"""Profile hint, neighbour alignment and actual joint-support preview regressions."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("COOLING_TOWER_DISABLE_SLICER_DISCOVERY", "1")
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from cooling_tower.file_integrity import sha256_file
from cooling_tower.gui.widgets.profile_preparation_hint import ProfilePreparationHint
from cooling_tower.gui.widgets.indicator_only_checkbox import IndicatorOnlyCheckBox
from cooling_tower.gui.texts import SOURCE_SUPPORT_HINT_HTML
from cooling_tower.preview.joint_source_toolpath import analyze_joint_source_toolpaths
from cooling_tower.preview.toolpath import PreviewCancelled
from cooling_tower.preview.service import PreviewService
from cooling_tower.models import GenerationSettings
import test_october_editor_changes as editor_fixtures
from test_manual_gui import preview_test_application, restore_preview_test_application
import test_preview_source_cache as preview_fixtures


def joint_gcode(style):
    lines = ["G90", "M83", "G1 Z0.2 F600"]
    for layer in range(2):
        for name, label, x in (("Source_object", 47, 5), ("Cooling_tower", 58, 80)):
            if style == "orca_named":
                name = name.replace("_", " ")
            if style == "bambu":
                lines.append(f"; start printing object, unique label id: {label}")
            elif style == "exclude":
                lines.append(f"EXCLUDE_OBJECT_START NAME={name}")
            else:
                lines.append(f"; printing object {name}")
            lines.extend((f"G1 X{x} Y2 F1200", ";TYPE:Support", f"G1 X{x+1} Y2 E0.4 F900",
                          ";TYPE:Outer wall", f"G1 X{x+1} Y10 E0.4"))
            lines.append("EXCLUDE_OBJECT_END" if style == "exclude" else "; stop printing object")
        lines.append("G1 Z0.4 F600")
    return "\n".join(lines)+"\n"


class JointSourceToolpathTests(unittest.TestCase):
    def test_original_supports_are_kept_and_tower_excluded_for_all_marker_styles(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"joint.gcode"
            for style in ("bambu", "exclude", "named", "orca_named"):
                with self.subTest(style=style):
                    path.write_text(joint_gcode(style), encoding="utf-8")
                    before = sha256_file(path)
                    result = analyze_joint_source_toolpaths(path, tower_center_xy_mm=(80.5,6), expected_layer_count=2)
                    self.assertEqual(result.source_segment_count, 4)
                    self.assertEqual(len(result.object_segments), 4)
                    self.assertTrue(any(s.end.y == 2 for s in result.object_segments))
                    self.assertTrue(all(s.end.x == 6 for s in result.object_segments))
                    self.assertEqual(result.occupied_bounds.minimum_x_mm, 5)
                    self.assertEqual(sha256_file(path), before)

    def test_excluded_objects_still_update_absolute_extrusion_and_position(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"joint.gcode"
            text = joint_gcode("named").replace("M83", "M82")
            counter = 0
            lines = []
            for line in text.splitlines():
                if "E0.4" in line:
                    counter += 1
                    line = line.replace("E0.4", f"E{counter*.4:.3f}")
                lines.append(line)
            path.write_text("\n".join(lines), encoding="utf-8")
            result = analyze_joint_source_toolpaths(path, tower_center_xy_mm=(80.5,6), expected_layer_count=2)
            self.assertEqual(result.source_segment_count, 4)

    def test_cancellation_and_ambiguous_labels_are_not_silently_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"joint.gcode"
            path.write_text(joint_gcode("bambu"), encoding="utf-8")
            event = Event(); event.set()
            with self.assertRaises(PreviewCancelled):
                analyze_joint_source_toolpaths(path, tower_center_xy_mm=(80.5,6), expected_layer_count=2,
                                               cancellation_event=event)
            with self.assertRaisesRegex(ValueError, "nicht eindeutig"):
                analyze_joint_source_toolpaths(path, tower_center_xy_mm=(43,6), expected_layer_count=2)


class RefinedPreviewServiceTests(unittest.TestCase):
    def test_successful_isolated_slice_cannot_claim_complete_stl_project(self):
        from cooling_tower.models import SourceArtifact
        from cooling_tower.preview import PreviewBuildError

        fixture = preview_fixtures.PreviewSourceCacheIntegrationTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        original = fixture.root / "original.stl"
        original.write_bytes(b"solid original\nendsolid original\n")
        request = fixture.request(source_artifact=SourceArtifact.capture(original))
        calibrator = preview_fixtures.SyntheticSuccessfulCalibrator()
        with self.assertRaisesRegex(PreviewBuildError, "kein vollständiger gemeinsamer.*Slice"):
            PreviewService(calibrator).prepare(request)

    @staticmethod
    def calibrator():
        basic = preview_fixtures.SyntheticSuccessfulCalibrator()

        def calibrate(snapshot, settings, **kwargs):
            result = basic.calibrate(snapshot, settings, **kwargs)
            path = Path(kwargs["output_directory"])/"joint.gcode"
            path.write_text(joint_gcode("named"), encoding="utf-8")
            result.project_path = path.with_suffix(".3mf")
            result.project_path.write_bytes(b"project")
            result.best_iteration = SimpleNamespace(number=1,evaluation=SimpleNamespace(gcode_path=path),
                final_combined_gcode_path=path)
            progress = SimpleNamespace(best_profile=result.profile, placement=result.placement,
                                       best_iteration=result.best_iteration)
            if kwargs["joint_progress_callback"] is not None:
                kwargs["joint_progress_callback"](progress)
                kwargs["joint_progress_callback"](progress)
            result.gcode_path = path.with_name("retained.gcode")
            result.gcode_path.write_bytes(path.read_bytes())
            path.unlink()  # The real calibration releases its iteration workspace.
            return result
        return SimpleNamespace(calibrate=calibrate)

    def test_best_joint_source_is_used_in_live_and_final_scene_and_read_once(self):
        fixture = preview_fixtures.PreviewSourceCacheIntegrationTests()
        fixture.setUp(); self.addCleanup(fixture.tearDown)
        service = PreviewService(self.calibrator())
        scenes = []
        request = fixture.request(settings=GenerationSettings(simulate_source_supports=True))
        with patch("cooling_tower.preview.service.analyze_joint_source_toolpaths",
                   wraps=analyze_joint_source_toolpaths) as analyze:
            result = service.prepare(request, joint_scene_callback=scenes.append)
            self.addCleanup(result.dispose)
            self.assertEqual(analyze.call_count, 1)
        self.assertEqual(len(scenes), 2)
        self.assertTrue(all(not scene.seam_points for scene in scenes))
        self.assertEqual(result.scene.seam_points, ())
        self.assertEqual(result.scene.object_segments, scenes[-1].object_segments)
        self.assertTrue(all(s.end.x == 6 for s in result.scene.object_segments))
        self.assertEqual(result.scene.source_segment_count, 4)

    def test_retained_gcode_is_used_after_workspace_cleanup_without_live_preview(self):
        fixture = preview_fixtures.PreviewSourceCacheIntegrationTests()
        fixture.setUp(); self.addCleanup(fixture.tearDown)
        request = fixture.request(settings=GenerationSettings(simulate_source_supports=True))
        result = PreviewService(self.calibrator()).prepare(request)
        self.addCleanup(result.dispose)
        self.assertTrue(all(s.end.x == 6 for s in result.scene.object_segments))

    def test_unselected_support_simulation_keeps_existing_fast_preview_path(self):
        fixture = preview_fixtures.PreviewSourceCacheIntegrationTests()
        fixture.setUp(); self.addCleanup(fixture.tearDown)
        with patch("cooling_tower.preview.service.analyze_joint_source_toolpaths") as analyze:
            result = PreviewService(preview_fixtures.SyntheticSuccessfulCalibrator()).prepare(fixture.request())
            self.addCleanup(result.dispose)
            analyze.assert_not_called()


class RefinedEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app, cls.previous_font, cls.font_id = preview_test_application()

    @classmethod
    def tearDownClass(cls):
        restore_preview_test_application(cls.app, cls.previous_font, cls.font_id)

    panel = editor_fixtures.EditorChangesTests.panel
    window = editor_fixtures.EditorChangesTests.window

    def test_hint_sentence_breaks_follow_width_and_round_icon_is_square(self):
        hint = ProfilePreparationHint()
        self.addCleanup(hint.close)
        hint.resize(760, 220); hint.show(); self.app.processEvents()
        self.assertEqual(hint.body.text().count("<br>"), 2)
        self.assertTrue(hint.title.font().underline())
        self.assertEqual(hint.layout().verticalSpacing(), 0)
        self.assertEqual(hint.icon.width(), hint.icon.height())
        self.assertGreater(hint.title.font().pointSizeF(), hint.body.font().pointSizeF())
        self.assertGreater(hint.title.font().weight(), hint.body.font().weight())
        self.assertEqual(hint.title.geometry().left(), hint.body.geometry().left())
        self.assertLess(hint.icon.geometry().right(), hint.body.geometry().left())
        hint.resize(360, 220); self.app.processEvents()
        self.assertNotIn("<br>", hint.body.text())
        for sentence in hint.SENTENCES:
            self.assertIn(sentence, hint.body.text())

    def checklist_panel(self):
        window = self.window()
        panel = window.preparation_slicer_requirements
        panel.setParent(None)
        panel.setStyleSheet(window.styleSheet())
        self.addCleanup(panel.close)
        rows = tuple(window.preparation_requirement_rows[key] for key in (
            "slicer_detected", "profiles_loaded", "profiles_confirmed", "preslice_completed"
        ))
        panel.show()
        return panel, rows

    def test_checklist_columns_preserve_reading_order_and_never_wrap_wide_text(self):
        panel, rows = self.checklist_panel()
        seen_modes = set()
        for width in range(260, 1001, 40):
            panel.resize(width, 240)
            self.app.processEvents()
            labels = tuple(label for _icon, label in rows)
            for label in labels:
                self.assertGreaterEqual(label.height(), label.heightForWidth(label.width()))
            two_column = labels[2].x() > labels[0].x()
            seen_modes.add(two_column)
            if two_column:
                self.assertEqual(labels[0].x(), labels[1].x())
                self.assertEqual(labels[2].x(), labels[3].x())
                self.assertEqual(labels[0].y(), labels[2].y())
                self.assertEqual(labels[1].y(), labels[3].y())
                self.assertLess(labels[0].y(), labels[1].y())
                for label in labels:
                    self.assertGreaterEqual(
                        label.contentsRect().width(),
                        label.fontMetrics().horizontalAdvance(label.text()),
                    )
            else:
                self.assertEqual(len({label.x() for label in labels}), 1)
                self.assertTrue(all(first.y() < second.y()
                                    for first, second in zip(labels, labels[1:])))
        self.assertEqual(seen_modes, {False, True})
        wide_height = panel.layout().heightForWidth(1000)
        panel.resize(260, 240)
        self.app.processEvents()
        self.assertGreater(panel.layout().heightForWidth(260), wide_height)

    def test_checklist_breakpoint_tracks_the_rendered_font(self):
        panel, rows = self.checklist_panel()
        panel.resize(800, 240)
        self.app.processEvents()
        self.assertGreater(rows[2][1].x(), rows[0][1].x())
        for _icon, label in rows:
            label.setStyleSheet("font-size: 20pt;")
        panel.resize(801, 300)
        self.app.processEvents()
        self.assertEqual(rows[2][1].x(), rows[0][1].x())
        for _icon, label in rows:
            self.assertGreaterEqual(label.height(), label.heightForWidth(label.width()))
        panel.resize(1800, 300)
        self.app.processEvents()
        self.assertGreater(rows[2][1].x(), rows[0][1].x())

    def test_hidden_analysis_still_blocks_finishing_preparation(self):
        from dataclasses import replace
        from cooling_tower.gui.widgets.preparation_controls import _PreparationState

        window = self.window()
        state = _PreparationState(
            source_selected=True, source_accepted=True, slicer_detected=True,
            profiles_loaded=True, profiles_confirmed=True,
            preslice_completed=True, model_analyzed=False,
        )
        self.assertNotIn("model_analyzed", window.preparation_requirement_rows)
        with patch.object(window, "_current_preparation_state", return_value=state):
            window._update_preparation_requirements()
            self.assertFalse(window.preparation_finish_button.isEnabled())
            self.assertLess(window.preparation_progress_bar.value(), 100)
        with patch.object(window, "_current_preparation_state",
                          return_value=replace(state, model_analyzed=True)):
            window._update_preparation_requirements()
            self.assertTrue(window.preparation_finish_button.isEnabled())
            self.assertEqual(window.preparation_progress_bar.value(), 100)

    def test_filter_info_matches_setting_info_and_support_copy_is_updated(self):
        window = self.window()
        panel, _ = self.panel()
        self.assertEqual(window.show_all_profiles_checkbox.text(), "Filter deaktivieren / alle Profile anzeigen")
        self.assertEqual(window.show_all_profiles_checkbox.layoutDirection(),Qt.LayoutDirection.RightToLeft)
        panel.setStyleSheet(window.styleSheet()); self.app.processEvents()
        window.show_all_profiles_info_button.ensurePolished()
        panel.source_support_option.info.ensurePolished()
        self.assertEqual(window.show_all_profiles_info_button.objectName(), panel.source_support_option.info.objectName())
        self.assertEqual(window.show_all_profiles_info_button.font().pointSizeF(), panel.source_support_option.info.font().pointSizeF())
        self.assertIn("Stützen simulieren</b>", SOURCE_SUPPORT_HINT_HTML)
        self.assertIn("OrcaSlicer: „Baum (automatisch)“", SOURCE_SUPPORT_HINT_HTML)
        self.assertIn("Stil „Organisch“", SOURCE_SUPPORT_HINT_HTML)
        self.assertIn("übrigen Stützparameter des gewählten Prozessprofils bleiben unverändert erhalten", SOURCE_SUPPORT_HINT_HTML)
        self.assertIn("Stützen anpassen</b>", SOURCE_SUPPORT_HINT_HTML)
        self.assertIn("Speichere das Profil und lies die Profile in Sacrificial Tower erneut ein", SOURCE_SUPPORT_HINT_HTML)
        self.assertIn("angepassten Stützparameter werden dann für die Simulation übernommen", SOURCE_SUPPORT_HINT_HTML)
        self.assertIn("Originalprofile bleiben unverändert", SOURCE_SUPPORT_HINT_HTML)

    def filter_checkbox(self):
        box = IndicatorOnlyCheckBox("Filter deaktivieren / alle Profile anzeigen")
        box.setObjectName("showAllProfilesCheckBox")
        box.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        window = self.window()
        box.setStyleSheet(window.styleSheet())
        box.ensurePolished(); box.resize(box.sizeHint()); box.show()
        self.addCleanup(box.close)
        self.app.processEvents()
        return box

    def test_filter_only_toggles_when_mouse_press_and_release_hit_indicator(self):
        box = self.filter_checkbox()
        label = QPoint(10,box.height()//2)
        indicator = box.indicator_rect().center()
        QTest.mouseClick(box,Qt.MouseButton.LeftButton,pos=label)
        self.assertFalse(box.isChecked())
        QTest.mousePress(box,Qt.MouseButton.LeftButton,pos=label)
        QTest.mouseRelease(box,Qt.MouseButton.LeftButton,pos=indicator)
        self.assertFalse(box.isChecked())
        QTest.mouseClick(box,Qt.MouseButton.LeftButton,pos=indicator)
        self.assertTrue(box.isChecked())
        QTest.mousePress(box,Qt.MouseButton.LeftButton,pos=indicator)
        QTest.mouseRelease(box,Qt.MouseButton.LeftButton,pos=label)
        self.assertTrue(box.isChecked())
        box.setFocus()
        QTest.keyClick(box,Qt.Key.Key_Space)
        self.assertFalse(box.isChecked())

    def test_filter_hover_changes_only_indicator_pixels_in_both_check_states(self):
        box = self.filter_checkbox()
        indicator = box.indicator_rect()
        label = QPoint(10,box.height()//2)
        for checked in (False,True):
            box.setChecked(checked); box.clearFocus()
            QTest.mouseMove(box,QPoint(-10,-10)); self.app.processEvents()
            idle = box.grab().toImage()
            QTest.mouseMove(box,label); self.app.processEvents()
            text_hover = box.grab().toImage()
            self.assertEqual(idle,text_hover)
            QTest.mouseMove(box,indicator.center()); self.app.processEvents()
            indicator_hover = box.grab().toImage()
            self.assertNotEqual(text_hover.copy(indicator),indicator_hover.copy(indicator))
            # Qt antialiases the indicator's border one pixel beyond its rect.
            painted_indicator = indicator.adjusted(-1,-1,1,1)
            self.assertTrue(all(text_hover.pixel(x,y)==indicator_hover.pixel(x,y)
                for y in range(box.height()) for x in range(box.width()) if not painted_indicator.contains(x,y)))

    def test_free_point_snaps_exactly_to_fixed_neighbors_including_off_grid_values(self):
        p, _ = self.panel()
        p.move("base",12.37,8)
        p.insert(12); identity = p.selected
        p.move(identity,16,12)
        p.move(identity,12.5,12,diameter_snap=True)
        point = next(q for q in p.draft.points if q.identity == identity)
        self.assertAlmostEqual(point.position.diameter_mm,12.37)
        self.assertEqual(point.position.z_mm,12)

    def test_only_direct_neighbors_are_candidates_and_controls_are_excluded(self):
        p, _ = self.panel()
        p.move("base",12.37,8)
        p.insert(11); first = p.selected
        p.insert(15); second = p.selected
        p.move(second,20,15)
        p.move("top_width",23,20)
        candidates = p.canvas.neighbor_diameter_snaps(first,23)
        self.assertNotIn("top", {key for key, value in candidates})
        self.assertEqual(p.canvas.neighbor_diameter_snaps("control:1:1",12.37), ())
        p.move(first,20.2,11,diameter_snap=True)
        self.assertEqual(next(q for q in p.draft.points if q.identity == first).position.diameter_mm,20)

    def test_mouse_drag_aligns_neighbors_preserves_height_and_undoes_as_one_action(self):
        p, _ = self.panel()
        p.move("base",12.37,8)
        p.insert(12); identity = p.selected
        p.move(identity,18,12)
        canvas = p.canvas
        canvas.set_view("side"); canvas.fit_scene(); self.app.processEvents()
        before = p.draft
        position = next(pos for key,pos,_ in canvas.handles() if key == identity).toPoint()
        target = canvas.profile_to_screen(12.37/2,12).toPoint()+QPoint(3,0)
        QTest.mousePress(canvas,Qt.MouseButton.LeftButton,pos=position)
        QTest.mouseMove(canvas,target)
        QTest.mouseRelease(canvas,Qt.MouseButton.LeftButton,pos=target)
        point = next(q for q in p.draft.points if q.identity == identity)
        self.assertAlmostEqual(point.position.diameter_mm,12.37)
        self.assertEqual(point.position.z_mm,12)
        p.undo()
        self.assertEqual(p.draft,before)

    def test_following_top_does_not_hold_base_at_its_drag_start_width(self):
        p, _ = self.panel()
        self.assertTrue(p.draft.top_follows_base)
        self.assertNotIn("top", {key for key,value in p.canvas.neighbor_diameter_snaps(
            "base",p.draft.points[1].position.diameter_mm)})

    def test_manual_joint_time_source_remains_in_report_without_generic_warning(self):
        p, (_, service, _, request, _) = self.panel()
        result = service.prepare(request)
        self.addCleanup(result.dispose)
        self.assertEqual(result.manual_evaluation.time_source,"gcode")
        self.assertFalse(any("native Slicer-Layerzeiten" in warning for warning in result.warnings))


if __name__ == "__main__":
    unittest.main()
