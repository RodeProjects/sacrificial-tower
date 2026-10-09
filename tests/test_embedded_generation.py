from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("COOLING_TOWER_DISABLE_SLICER_DISCOVERY", "1")

from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QSignalSpy, QTest
from cooling_tower.gui.generation_panel import GenerationPanel, result_description
from cooling_tower.gui.widgets.chevron_button import ChevronButton
from cooling_tower.gui.main_window import MainWindow, INTERNAL_DIALOG_REVEAL_DELAY_MS
from cooling_tower.gui.settings_store import UserSettingsStore
from cooling_tower.config import SETTINGS_SCHEMA_VERSION
from cooling_tower.models import BedBounds
from cooling_tower.preview import LineSegment3D, Point3D, PreviewScene, PreviewState
from cooling_tower.persistence import ConcurrentDocumentChangeError, VersionedDocumentWriteBlockedError
from cooling_tower.settings_compatibility import SETTING_COMPATIBILITY_CATALOG, merge_compatible_setting_changes


class EmbeddedGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "settings.json"

    def window(self):
        window = MainWindow(user_settings_path=self.path, enable_update_check=False, enable_startup_slicer_discovery=False)
        self.addCleanup(window.close)
        return window

    def test_result_thresholds_both_directions(self):
        for sign in (-1, 1):
            self.assertIn("erreicht", result_description(sign * .2, .2))
            self.assertIn("leicht", result_description(sign * .7, .2))
            self.assertNotIn("leicht", result_description(sign * .71, .2))
            self.assertNotIn("stärker", result_description(sign * 1.2, .2))
            self.assertIn("stärker", result_description(sign * 1.21, .2))

    def test_panel_lifecycle_and_candidate_result(self):
        w = self.window()
        p = w.joint_generation_dialog
        self.assertFalse(p.isWindow())
        self.assertTrue(p.isHidden())
        p.set_context(("Turmfüllung: 100 %",))
        self.assertIn("<u>Simulierte Werte:</u>", p.simulation_label.text())
        p.begin(10, .2, 0, 10)
        self.assertTrue(p.result_widget.isHidden())
        self.assertTrue(p.export_button.isHidden())
        self.assertFalse(p.image_progress.isVisibleTo(p))
        p.start_slice(0, 10)
        self.assertFalse(p.result_widget.isHidden())
        self.assertTrue(p.image_progress.isVisibleTo(p))
        candidate = SimpleNamespace(evaluation=SimpleNamespace(layer_timings=(SimpleNamespace(combined_layer_time_s=8.5),)))
        p.complete_slice(2, 10, candidate, 10)
        self.assertIn("2 von 10", p.counter_label.text())
        self.assertTrue(p.accept_button.isHidden())
        p.complete_slice(3, 10, candidate, 10)
        self.assertFalse(p.accept_button.isHidden())
        self.assertFalse(p.continue_button.isHidden())
        self.assertFalse(p.continue_button.isEnabled())
        self.assertFalse(p.result_widget.isHidden())
        self.assertEqual(p.best_deviation_value.text(), "-1.50 s")
        p.mark_finished(paused=True, can_continue=True)
        self.assertFalse(p.result_widget.isHidden())
        self.assertTrue(p.continue_button.isEnabled())
        self.assertTrue(p.image_progress.isVisibleTo(p))
        self.assertEqual(p.title_label.text(), "Generierung gestoppt")
        self.assertFalse(p.continue_button.isHidden())
        self.assertFalse(p.export_button.isHidden())
        p.export_button.setEnabled(True)
        with patch.object(w, "start_export") as export:
            p.export_button.click()
            export.assert_called_once_with()
        self.assertFalse(hasattr(p, "analysis_button"))
        self.assertFalse(hasattr(p, "analysis_label"))
        p.resume_waiting()
        self.assertFalse(p.result_widget.isHidden())
        self.assertFalse(p.continue_button.isHidden())
        self.assertFalse(p.continue_button.isEnabled())
        self.assertTrue(p.export_button.isHidden())
        self.assertIn("3 von 10", p.counter_label.text())
        self.assertIn("wird generiert", p.title_label.text())
        p.set_achieved(10.15)
        p.mark_finished(paused=False, can_continue=False)
        self.assertFalse(p.result_widget.isHidden())
        self.assertTrue(p.continue_button.isHidden())
        self.assertEqual(p.title_label.text(), "Kühlturm fertig generiert")
        self.assertTrue(p.accept_button.isHidden())
        self.assertFalse(p.export_button.isHidden())
        with patch.object(w, "start_export") as export:
            w._on_main_export_clicked()
            export.assert_called_once_with()

    def test_result_values_and_fixed_image_position(self):
        w = self.window()
        w.show()
        p = w.joint_generation_dialog
        p.set_context(("Turmfüllung: 100 %",))
        p.begin(11, .25, 0, 10)
        p.start_slice(0, 10)
        self.app.processEvents()
        caption = next(
            label for label in p.result_widget.findChildren(type(p.title_label))
            if "Beste bisherige Layerzeit" in label.text()
        )
        self.assertFalse(caption.wordWrap())
        self.assertFalse(any(
            label.text() == "Slicer-gestützte Schätzung"
            for label in p.result_widget.findChildren(type(p.title_label))
        ))
        image_y = p.image_progress.mapTo(p.result_widget, p.image_progress.rect().topLeft()).y()
        p.set_achieved(9.39)
        p.mark_finished(paused=False, can_continue=False)
        achieved_html = p.best_minimum_value.text()
        self.assertIn('color:#b87900">9.39 s</span>', achieved_html)
        self.assertIn('color:#000000"> / 11.00 s (± 0.25 s Toleranz)</span>', achieved_html)
        self.assertIn("#b87900", p.best_deviation_value.styleSheet())
        self.app.processEvents()
        self.assertEqual(
            p.image_progress.mapTo(p.result_widget, p.image_progress.rect().topLeft()).y(),
            image_y,
        )
        p.set_achieved(11.05)
        self.assertIn('color:#22854b">11.05 s</span>', p.best_minimum_value.text())
        self.assertIn('color:#000000"> / 11.00 s', p.best_minimum_value.text())
        self.assertIn("#22854b", p.best_deviation_value.styleSheet())

    def test_best_layer_time_caption_uses_available_horizontal_space(self):
        panel = GenerationPanel(ROOT / "src/cooling_tower/gui/assets/tower_gen_finished.webp")
        self.addCleanup(panel.close)
        panel.resize(900, 300)
        panel.begin(11, .25, 0, 10)
        panel.start_slice(0, 10)
        self.app.processEvents()
        caption = next(
            label for label in panel.result_widget.findChildren(type(panel.title_label))
            if "Beste bisherige Layerzeit" in label.text()
        )
        self.assertFalse(caption.wordWrap())
        self.assertGreaterEqual(
            caption.width(), caption.fontMetrics().horizontalAdvance(caption.text())
        )

    def test_preview_camera_buttons_share_one_row_and_hint_points_left(self):
        w = self.window()
        w.show()
        preview = w.preview_dialog
        preview._set_preview_controls_visible(True)
        self.app.processEvents()
        buttons = (
            preview.three_quarter_button,
            preview.front_button,
            preview.side_button,
            preview.top_button,
        )
        self.assertEqual(len({button.y() for button in buttons}), 1)
        self.assertEqual([button.x() for button in buttons], sorted(button.x() for button in buttons))
        self.assertEqual([button.sizeHint().height() for button in buttons], [32] * 4)
        self.assertIn("oben links", preview.navigation_hint.text())

    def test_first_two_joint_slices_leave_no_temporary_space_below_preview(self):
        w = self.window()
        w.resize(1856, 1334)
        w.show()
        w.workflow.set_slicer_step_visible(True)
        w.workflow.source_validation_succeeded("STL", analysis_complete=True)
        w.workflow.slicer_succeeded("Slicer")
        w.workflow.complete_preparation()
        w.automatic_generation_card.click()
        self.app.processEvents()

        scene = PreviewScene(
            (LineSegment3D(Point3D(0, 0, .2), Point3D(10, 10, .2)),),
            (LineSegment3D(Point3D(20, 20, 0), Point3D(20, 20, 5)),),
            BedBounds(0, 100, 0, 100),
            (20, 20),
            1, 1, 5,
        )
        preview = w.preview_dialog
        preview.set_original_object(replace(scene, tower_segments=()))
        self.app.processEvents()
        w.preview_state = PreviewState.BUILDING
        preview.set_building("Gemeinsame Angleichung wird vorbereitet …")
        panel = w.joint_generation_dialog
        panel.set_context(())
        panel.begin(13, .25, 0, 12)
        panel.start_slice(0, 12)
        self.app.processEvents()

        candidate = SimpleNamespace(evaluation=SimpleNamespace(
            layer_timings=(SimpleNamespace(combined_layer_time_s=11.9),)
        ))
        for completed in (1, 2):
            # The worker emits the scene immediately before its progress
            # result, with no layout event between those queued signals.
            w._on_joint_scene(w._preview_request_id, scene)
            w._on_joint_progress(w._preview_request_id, SimpleNamespace(
                completed_count=completed, best_iteration=candidate
            ))
            self.app.processEvents()
            bottom_gap = (
                w.prediction_frame.rect().bottom()
                - preview.mapTo(w.prediction_frame, preview.rect().bottomLeft()).y()
            )
            self.assertLessEqual(bottom_gap, 20, f"Slice {completed}: {bottom_gap} px")
            panel.start_slice(completed, 12)
            self.app.processEvents()
        preview.set_cancelled()
        self.assertEqual(preview.maximumHeight(), 16777215)

    def test_first_preparation_step_uses_short_requirement_labels(self):
        w = self.window()
        self.assertEqual(
            w.preparation_requirement_rows["source_selected"][1].text(),
            "STL-Datei übergeben",
        )
        self.assertEqual(
            w.preparation_requirement_rows["source_validated"][1].text(),
            "STL-Geometrie geprüft",
        )

    def test_preparation_view_is_replaced_by_joint_slice_results(self):
        w = self.window()
        w.show()
        p = w.joint_generation_dialog
        p.begin(10, .2, 0, w.maximum_joint_slices)
        w._set_isolated_slice_progress_visible(True)
        self.app.processEvents()
        self.assertTrue(w.isolated_progress_widget.isVisibleTo(p))
        self.assertEqual(w.isolated_progress_title_label.text(), "Turmgenerierung wird vorbereitet...")
        self.assertFalse(p.result_widget.isVisibleTo(p))
        w._on_preview_progress(w._preview_request_id, 20, "Getrennter Slice 2/6 wird vorbereitet …")
        self.assertEqual(w.isolated_progress_bar.value(), 17)
        w._on_preview_progress(w._preview_request_id, 21, "Getrennter Kühlturm-Slice 2/6 wird ausgewertet …")
        self.assertEqual(w.isolated_progress_bar.value(), 33)
        self.assertIn("2/6", w.isolated_progress_detail_label.text())
        w._on_joint_phase_started(w._preview_request_id, 0, w.maximum_joint_slices)
        self.app.processEvents()
        self.assertEqual(w._generation_phase_transition_stage, "out")
        self.assertTrue(w.isolated_progress_widget.isVisibleTo(p))
        self.assertFalse(p.result_widget.isVisibleTo(p))
        self.assertTrue(w._generation_phase_effect.isEnabled())
        fade_out_done = QSignalSpy(w._generation_phase_fade_out.finished)
        fade_in_done = QSignalSpy(w._generation_phase_fade_in.finished)
        self.assertTrue(fade_out_done.wait(1500))
        self.assertEqual(w._generation_phase_transition_stage, "in")
        visible_panel_sections = [
            p.layout().itemAt(index).widget()
            for index in range(p.layout().count())
            if p.layout().itemAt(index).widget().isVisibleTo(p)
        ]
        self.assertEqual(visible_panel_sections, [p.result_widget])
        self.assertFalse(w.isolated_progress_widget.isVisibleTo(p))
        self.assertTrue(p.image_progress.isVisibleTo(p))
        self.assertTrue(p.best_minimum_value.isVisibleTo(p))
        self.assertFalse(p.accept_button.isVisibleTo(p))
        self.assertTrue(fade_in_done.wait(1500))
        self.assertIsNone(w._generation_phase_transition_stage)
        self.assertFalse(w._generation_phase_effect.isEnabled())
        self.assertEqual(w._generation_phase_effect.opacity(), 1.0)
        w._on_preview_progress(w._preview_request_id, 45, "Gemeinsamer Slice 1/10 wird ausgeführt …")
        candidate = SimpleNamespace(evaluation=SimpleNamespace(layer_timings=(SimpleNamespace(combined_layer_time_s=9.0),)))
        w._on_joint_progress(w._preview_request_id, SimpleNamespace(completed_count=1, best_iteration=candidate))
        self.assertIn("1 von", p.counter_label.text())
        self.assertFalse(p.result_widget.isHidden())
        p.mark_finished(paused=False, can_continue=False)
        self.assertFalse(p.result_widget.isHidden())

    def test_cancel_without_joint_candidate_shows_no_result_overview(self):
        w = self.window()
        p = w.joint_generation_dialog
        p.begin(10, .2, 0, 10)
        p.mark_finished(paused=True, can_continue=False, status_text="Vor dem ersten verwertbaren gemeinsamen Slice gestoppt.", has_result=False)
        self.assertTrue(p.result_widget.isHidden())
        self.assertTrue(p.isHidden())

    def test_failed_generation_stops_phase_fade_and_restores_opacity(self):
        w = self.window()
        w.show()
        p = w.joint_generation_dialog
        p.begin(10, .2, 0, w.maximum_joint_slices)
        w._set_isolated_slice_progress_visible(True)
        w._on_joint_phase_started(w._preview_request_id, 0, w.maximum_joint_slices)
        self.assertEqual(w._generation_phase_transition_stage, "out")
        with patch.object(w.preview_dialog, "set_failed"), patch.object(w, "_refresh_prediction"), patch.object(w, "_refresh_phase17_actions"):
            w._on_preview_failed(w._preview_request_id, "Slicerfehler", "")
        self.assertIsNone(w._generation_phase_transition_stage)
        self.assertFalse(w._generation_phase_effect.isEnabled())
        self.assertEqual(w._generation_phase_effect.opacity(), 1.0)
        self.assertTrue(w.isolated_progress_widget.isHidden())
        self.assertTrue(p.result_widget.isHidden())
        self.assertTrue(p.isHidden())
        self.assertEqual(w.status_label.text(), "Vorschau fehlgeschlagen: Slicerfehler")
        QTest.qWait(450)
        self.assertTrue(p.result_widget.isHidden())

    def test_generation_failure_appears_only_in_footer(self):
        w = self.window()
        p = w.joint_generation_dialog
        p.begin(10, .2, 0, 10)
        message = "Das gemeinsame 3MF wurde vom Slicer nicht akzeptiert. Details zur Ursache."
        with patch.object(w, "_refresh_prediction"), patch.object(w, "_refresh_phase17_actions"):
            w._on_preview_failed(w._preview_request_id, message, "")
        self.assertEqual(w.status_label.text(), f"Vorschau fehlgeschlagen: {message}")
        self.assertTrue(p.isHidden())
        self.assertTrue(w.preview_hint_label.isHidden())
        self.assertTrue(w.preview_dialog.state_label.isHidden())
        self.assertFalse(hasattr(p, "error_label"))

    def test_initial_generation_hint_and_display_precision(self):
        w = self.window()
        self.assertFalse(w.generation_intro_label.isHidden())
        self.assertIn("Noch kein Kühlturm generiert", w.generation_intro_label.text())
        self.assertTrue(w.joint_generation_dialog.isHidden())
        for editor, value, displayed in (
            (w.target_time_spin, 12.34, "12,3"),
            (w.minimum_outer_spin, 4.005, "4,0"),
            (w.maximum_outer_spin, 40.125, "40,1"),
        ):
            with self.subTest(editor=editor.objectName()):
                editor.setValue(value)
                self.assertAlmostEqual(editor.value(), value, places=3)
                self.assertEqual(editor.text(), displayed)
        self.assertEqual(w._setting_widgets["target_layer_time_s"].unit_label.text(), "Sek.")
        w.show_joint_slice_settings()
        self.assertEqual(w._joint_slice_settings_dialog.tolerance_spin_box.suffix(), " Sek.")
        w._joint_slice_settings_dialog.reject()

    def test_live_progress_keeps_best_candidate_when_next_slice_is_worse(self):
        w = self.window()
        p = w.joint_generation_dialog
        p.begin(11, .25, 0, 10)
        def iteration(seconds):
            return SimpleNamespace(evaluation=SimpleNamespace(layer_timings=(SimpleNamespace(combined_layer_time_s=seconds),)))
        first = iteration(11.39)
        w._on_joint_progress(w._preview_request_id, SimpleNamespace(completed_count=1, current_iteration=first, best_iteration=first))
        self.assertEqual(p.best_deviation_value.text(), "+0.39 s")
        w._on_joint_progress(w._preview_request_id, SimpleNamespace(completed_count=2, current_iteration=iteration(9.2), best_iteration=first))
        self.assertEqual(p.best_deviation_value.text(), "+0.39 s")
        self.assertIn("11.39 s", p.best_minimum_value.text())

    def test_limits_release_space_and_round_trip(self):
        w = self.window()
        row = w._setting_widgets["target_layer_time_s"]
        row.set_feedback_enabled(True)
        self.assertTrue(row.range_label.isHidden())
        hidden_height = row.sizeHint().height()
        w._apply_show_setting_limits(True)
        self.assertFalse(row.range_label.isHidden())
        self.assertGreater(row.sizeHint().height(), hidden_height)
        _, state = UserSettingsStore(self.path, ROOT / "config/default_settings.json").load()
        self.assertTrue(state["show_setting_limits"])
        w._apply_show_setting_limits(False)
        self.assertEqual(row.sizeHint().height(), hidden_height)

    def test_limits_resize_complete_settings_card_both_ways(self):
        w = self.window()
        w.resize(1400, 900)
        w.show()
        w.workflow.set_slicer_step_visible(True)
        w.workflow.source_validation_succeeded("STL", analysis_complete=True)
        w.workflow.slicer_succeeded("Slicer")
        w.workflow.complete_preparation()
        w.automatic_generation_card.click()
        self.app.processEvents()
        baseline = w.geometry_settings_group.height()
        w._apply_show_setting_limits(True)
        self.app.processEvents()
        expanded_height = w.geometry_settings_group.height()
        self.assertGreater(expanded_height, baseline)
        w._apply_show_setting_limits(False)
        self.app.processEvents()
        # The settings-changed footer can reduce the viewport and introduce a
        # scrollbar. Labels may then wrap at the narrower width, so compare
        # the same viewport state rather than the initial card pixel height.
        self.assertLess(w.geometry_settings_group.height(), expanded_height)
        self.assertEqual(
            w.geometry_settings_group.height(),
            w.geometry_settings_group.sizeHint().height(),
        )

    def test_about_documents_toggle_and_reset_on_reopen(self):
        w = self.window()
        w.resize(900, 900)
        w.show()
        w.show_about_dialog()
        QTest.qWait(INTERNAL_DIALOG_REVEAL_DELAY_MS + 20)
        self.app.processEvents()
        dialog = w.about_dialog
        initial_height = dialog.height()
        self.assertTrue(dialog.about_placeholder_label.isHidden())
        self.assertEqual([button.chevron_label.text() for button in dialog.about_legal_buttons], ["▼"] * 3)
        for button in dialog.about_legal_buttons:
            self.assertGreater(button.chevron_label.x(), button.width() // 2)
            self.assertEqual(button.chevron_label.height(), button.height())
            self.assertIsInstance(button, ChevronButton)
        available = dialog.screen().availableGeometry()
        dialog.move(dialog.x(), available.top() + 20)
        self.app.processEvents()
        dialog.about_legal_buttons[0].click()
        self.app.processEvents()
        self.assertFalse(dialog.about_placeholder_label.isHidden())
        self.assertEqual([button.chevron_label.text() for button in dialog.about_legal_buttons], ["▲", "▼", "▼"])
        self.assertLessEqual(dialog.height(), initial_height + w._about_expansion_allowance)
        self.assertLessEqual(dialog.frameGeometry().bottom(), available.bottom())
        dialog.about_legal_buttons[0].click()
        self.app.processEvents()
        self.assertTrue(dialog.about_placeholder_label.isHidden())
        self.assertEqual([button.chevron_label.text() for button in dialog.about_legal_buttons], ["▼"] * 3)
        self.assertEqual(dialog.height(), initial_height)
        dialog.about_legal_buttons[1].click()
        dialog.about_legal_buttons[2].click()
        self.assertEqual(dialog._shown_document_title, "Drittanbieter-Lizenzen")
        self.assertEqual([button.chevron_label.text() for button in dialog.about_legal_buttons], ["▼", "▼", "▲"])
        dialog.close()
        w.show_about_dialog()
        self.app.processEvents()
        self.assertTrue(dialog.about_placeholder_label.isHidden())
        self.assertIsNone(dialog._shown_document_title)
        self.assertEqual([button.chevron_label.text() for button in dialog.about_legal_buttons], ["▼"] * 3)

    def test_general_settings_owns_export_path_and_cancel_is_nonmutating(self):
        w = self.window()
        self.assertNotIn("Exportordner ändern", [a.text() for a in w.options_menu.actions()])
        original = w.output_root_edit.text()
        w.show_joint_slice_settings()
        dialog = w._joint_slice_settings_dialog
        dialog.output_root_edit.setText(str(Path(self.temp.name)/"cancelled"))
        dialog.reject()
        self.assertEqual(w.output_root_edit.text(), original)
        w.show_joint_slice_settings()
        dialog = w._joint_slice_settings_dialog
        selected = str(Path(self.temp.name)/"export")
        dialog.output_root_edit.setText(selected)
        dialog.accept()
        self.assertEqual(w.output_root_edit.text(), selected)

    def test_geometry_has_two_sections_with_ordered_fields(self):
        w = self.window()
        self.assertEqual(w.geometry_split_layout.count(), 2)
        layout = w.geometry_group.content_layout
        ordered = [w._setting_widgets[n] for n in ("minimum_outer_diameter_mm", "maximum_outer_diameter_mm", "manual_base_width_mm", "maximum_expansion_angle_deg", "maximum_contraction_angle_deg")]
        indices = [layout.indexOf(x) for x in ordered]
        self.assertEqual(indices, sorted(indices))
        self.assertTrue(all(i >= 0 for i in indices))
        self.assertTrue(w.automatic_base_width_label.isHidden())

    def test_export_enablement_does_not_depend_on_panel_visibility(self):
        w = self.window()
        w.current_preview = SimpleNamespace(dispose=lambda: None)
        w.preview_state = PreviewState.CURRENT
        with patch.object(w, "_export_block_reason", return_value=None), patch.object(w, "_current_preview_was_exported", return_value=False):
            for visible in (True, False):
                w.joint_generation_dialog.setVisible(visible)
                w._refresh_phase17_actions()
                self.assertTrue(w.export_button.isEnabled())
                self.assertTrue(w.joint_generation_dialog.export_button.isEnabled())

    def test_setting_change_interrupts_heading_and_disables_resume(self):
        w = self.window()
        p = w.joint_generation_dialog
        p.begin(10, .2, 1, 10)
        p.set_achieved(8)
        w._invalidate_preview("Parameter geändert")
        self.assertEqual(p.title_label.text(), "Generierung gestoppt")
        self.assertTrue(p.continue_button.isHidden())
        self.assertFalse(w.export_button.isEnabled())
        self.assertFalse(p.export_button.isEnabled())

    def test_stop_always_cancels_even_with_safe_candidate(self):
        w = self.window()
        w._joint_phase_active = True
        w._joint_slices_completed = 5
        with patch.object(w, "_accept_joint_candidate") as accept, patch.object(w.background_job_manager, "cancel_jobs", return_value=("job",)) as cancel:
            w.cancel_generation()
            accept.assert_not_called()
            cancel.assert_called_once()

    def test_stop_before_three_joint_slices_cancels_without_acceptance(self):
        w = self.window()
        w._joint_phase_active = True
        w._joint_slices_completed = 2
        with patch.object(w, "_accept_joint_candidate") as accept, patch.object(
            w.background_job_manager, "cancel_jobs", return_value=("job",)
        ) as cancel:
            w.cancel_generation()
            accept.assert_not_called()
            cancel.assert_called_once()

    def test_paused_candidate_keeps_export_and_can_be_aborted(self):
        w = self.window()
        w.workflow.set_slicer_step_visible(True)
        w.workflow.source_validation_succeeded("STL", analysis_complete=True)
        w.workflow.slicer_succeeded("Testslicer")
        w.workflow.complete_preparation()
        w.automatic_generation_card.click()
        w.resize(2600, 900)
        w.show()
        self.app.processEvents()
        disposed = []
        w.current_preview = SimpleNamespace(
            dispose=lambda: disposed.append(True)
        )
        w.preview_state = PreviewState.CURRENT
        w._joint_generation_paused = True
        w._joint_slices_completed = 3
        with patch.object(w, "_export_block_reason", return_value=None), patch.object(
            w, "_current_preview_was_exported", return_value=False
        ):
            w._refresh_phase17_actions()
            self.assertFalse(w.preview_action_control.isHidden())
            self.assertFalse(w.export_button.isHidden())
            self.assertEqual(w.preview_button.text(), "Generierung abbrechen")
            self.assertTrue(w.preview_button.isEnabled())
            self.assertTrue(w.export_button.isEnabled())
            with patch.object(w.background_job_manager, "cancel_jobs") as cancel:
                w.preview_button.click()
                cancel.assert_not_called()
            self.assertEqual(disposed, [True])
            self.assertIsNone(w.current_preview)
            self.assertEqual(w.preview_state, PreviewState.EMPTY)
            self.assertFalse(w._joint_generation_paused)
            self.assertEqual(w._joint_slices_completed, 0)
            self.assertTrue(w.export_button.isHidden())
            self.assertEqual(w.status_label.text(), "Generierung abgebrochen")
            w.current_preview = SimpleNamespace(dispose=lambda: None)
            w.preview_state = PreviewState.CURRENT
            w._refresh_phase17_actions()
            self.assertTrue(w.preview_action_control.isHidden())
            self.assertFalse(w.export_button.isHidden())

    def test_resumed_generation_abort_does_not_accept_another_candidate(self):
        w = self.window()
        p = w.joint_generation_dialog
        p.begin(15, .25, 5, 10)
        p.resume_waiting()
        retained = SimpleNamespace(dispose=lambda: None)
        w.current_preview = retained
        w.preview_state = PreviewState.BUILDING
        w._joint_resume_active = True
        w._joint_phase_active = True
        w._joint_slice_offset = 5
        w._joint_slices_completed = 6
        w._joint_resume_accept_seed_only = True
        w._joint_accept_requested = True
        w._update_responsive_action_labels()
        self.assertEqual(w.preview_button.text(), "Generierung abbrechen")

        with patch.object(w.background_job_manager, "cancel_jobs", return_value=("job",)) as cancel, \
             patch.object(w, "_accept_joint_candidate") as accept, \
             patch.object(w.preview_dialog, "set_cancelled") as discard_scene, \
             patch.object(w, "_refresh_prediction"), \
             patch.object(w, "_refresh_phase17_actions"):
            w.cancel_generation()
            cancel.assert_called_once()
            accept.assert_not_called()
            self.assertFalse(p.accept_button.isEnabled())
            self.assertTrue(w._preview_cancel_requested)
            self.assertFalse(w._joint_resume_accept_seed_only)
            self.assertFalse(w._joint_accept_requested)
            w._on_preview_finished(w._preview_request_id)
            discard_scene.assert_called_once_with()

        self.assertIsNone(w.current_preview)
        self.assertEqual(w.preview_state, PreviewState.EMPTY)
        self.assertFalse(w._joint_resume_active)
        self.assertFalse(w._joint_generation_paused)
        self.assertFalse(w._preview_cancel_requested)
        self.assertEqual(w._joint_slices_completed, 0)
        self.assertTrue(p.isHidden())
        self.assertEqual(w.status_label.text(), "Generierung abgebrochen")

    def test_resumed_slice_progress_uses_total_joint_count_in_footer(self):
        w = self.window()
        w._joint_resume_active = True
        w._joint_phase_active = True
        w._joint_slice_offset = 5
        w._on_preview_progress(
            w._preview_request_id,
            55,
            "Gemeinsamer Slice 1/5 wird ausgewertet …",
        )
        self.assertEqual(
            w.status_label.text(),
            "Gemeinsamer Slice 6/12 wird ausgewertet …",
        )

    def test_main_action_stays_abort_after_third_joint_slice(self):
        w = self.window()
        w.preview_state = PreviewState.BUILDING
        w._joint_phase_active = True
        w._joint_slices_completed = 2
        w._update_responsive_action_labels()
        self.assertEqual(w.preview_button.text(), "Generierung abbrechen")
        self.assertTrue(w.preview_action_control.property("cancelAction"))
        progress = SimpleNamespace(
            completed_count=3,
            best_iteration=SimpleNamespace(evaluation=SimpleNamespace(layer_timings=())),
        )
        w._on_joint_progress(w._preview_request_id, progress)
        self.assertEqual(w.preview_button.text(), "Generierung abbrechen")
        self.assertTrue(w.preview_action_control.property("cancelAction"))
        self.assertFalse(w.preview_action_control.property("acceptAction"))
        self.assertFalse(w.joint_generation_dialog.accept_button.isHidden())

    def test_failed_resume_displays_retained_exportable_result(self):
        w = self.window()
        p = w.joint_generation_dialog
        p.begin(10, .2, 1, 10)
        p.set_achieved(6)
        w._joint_resume_active = True
        w.current_preview = SimpleNamespace(calibration=None, minimum_verified_layer_time_s=9, dispose=lambda: None)
        with patch.object(w.preview_dialog, "set_preview"), patch.object(w, "_refresh_prediction"), patch.object(w, "_refresh_phase17_actions"):
            w._on_preview_failed(w._preview_request_id, "Slicer konnte den nächsten Kandidaten nicht prüfen.", "")
        self.assertEqual(p.best_deviation_value.text(), "-1.00 s")
        self.assertEqual(w.preview_state, PreviewState.CURRENT)
        self.assertFalse(p.continue_button.isHidden())
        self.assertEqual(
            w.status_label.text(),
            "Vorschau fehlgeschlagen: Slicer konnte den nächsten Kandidaten nicht prüfen.",
        )
        self.assertTrue(w.preview_hint_label.isHidden())

    def test_accepting_seed_before_resumed_slice_restores_continue(self):
        w = self.window()
        p = w.joint_generation_dialog
        p.begin(10, .2, 5, 10)
        p.set_achieved(9)
        p.mark_finished(paused=True, can_continue=True)
        old_preview = SimpleNamespace(minimum_verified_layer_time_s=9, dispose=lambda: None)
        w.current_preview = old_preview
        w.preview_state = PreviewState.CURRENT
        w._joint_slices_completed = 5
        p.continue_button.setEnabled(True)
        active = [False]
        with patch.object(w.background_job_manager, "has_active", side_effect=lambda *_: active[0]), \
             patch.object(w.background_job_manager, "cancel_jobs", return_value=("job",)) as cancel, \
             patch.object(w.background_job_manager, "start_job"), \
             patch.object(w, "_current_preview_request", return_value=object()) as build_request, \
             patch.object(w.preview_dialog, "set_preview"), \
             patch.object(w, "_refresh_prediction"), \
             patch.object(w, "_refresh_phase17_actions"):
            p.continue_button.click()
            self.assertTrue(w._joint_resume_active)
            self.assertFalse(p.continue_button.isHidden())
            self.assertFalse(p.continue_button.isEnabled())
            self.assertEqual(w._joint_slice_offset, 5)
            config = build_request.call_args.kwargs["calibration_config"]
            self.assertEqual(config.minimum_joint_slices, 3)
            self.assertEqual(config.completed_joint_slices_before_run, 5)
            self.assertEqual(w.preview_state, PreviewState.BUILDING)
            active[0] = True
            with patch.object(w._active_preview_worker, "accept_current") as accept:
                p.accept_button.click()
                cancel.assert_called_once()
                accept.assert_not_called()
                self.assertTrue(w._joint_resume_accept_seed_only)
                w._on_preview_finished(w._preview_request_id)
        self.assertIs(w.current_preview, old_preview)
        self.assertEqual(w.preview_state, PreviewState.CURRENT)
        self.assertEqual(w._joint_slices_completed, 5)
        self.assertFalse(p.continue_button.isHidden())
        self.assertTrue(p.accept_button.isHidden())
        self.assertFalse(w._joint_resume_active)

    def test_failed_resume_does_not_count_unexported_candidate(self):
        w = self.window()
        p = w.joint_generation_dialog
        p.begin(10, .2, 5, 10)
        w._joint_resume_active = True
        w._joint_slice_offset = 5
        w._joint_slices_completed = 6
        w.current_preview = SimpleNamespace(minimum_verified_layer_time_s=9, dispose=lambda: None)
        with patch.object(w.preview_dialog, "set_preview"), \
             patch.object(w, "_refresh_prediction"), \
             patch.object(w, "_refresh_phase17_actions"):
            w._on_preview_failed(w._preview_request_id, "Slicerfehler", "")
        self.assertEqual(w._joint_slices_completed, 5)
        self.assertFalse(p.continue_button.isHidden())

    def test_continue_waits_for_previous_worker_release(self):
        w = self.window()
        p = w.joint_generation_dialog
        p.begin(10, .2, 2, 10)
        p.mark_finished(paused=True, can_continue=True)
        w.current_preview = SimpleNamespace(dispose=lambda: None)
        w.preview_state = PreviewState.CURRENT
        request_id = w._preview_request_id
        active = [True]
        with patch.object(w.background_job_manager, "has_active", side_effect=lambda *_: active[0]), \
             patch.object(w, "_export_block_reason", return_value=None), \
             patch.object(w, "_current_preview_was_exported", return_value=False):
            w._refresh_phase17_actions()
            self.assertFalse(p.continue_button.isEnabled())
            w._continue_joint_generation()
            self.assertEqual(w._preview_request_id, request_id)
            active[0] = False
            w._refresh_phase17_actions()
            self.assertTrue(p.continue_button.isEnabled())


class LimitsMigrationTests(unittest.TestCase):
    def test_direct_and_multistep_migration_backup_and_atomic_save(self):
        for source_version in (0, 13, 14):
            with self.subTest(source_version=source_version), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)/"settings.json"
                original = json.dumps({"settings_schema_version": source_version, "generation": {"target_layer_time_s": 12}}).encode()
                path.write_bytes(original)
                store = UserSettingsStore(path, ROOT / "config/default_settings.json")
                settings, state = store.load()
                self.assertFalse(state["show_setting_limits"])
                self.assertEqual(store.last_migration_backup.read_bytes(), original)
                store.save(settings, output_root="output", window_width=1000, window_height=800, show_setting_limits=True)
                payload = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(payload["settings_schema_version"], SETTINGS_SCHEMA_VERSION)
                self.assertTrue(payload["show_setting_limits"])
                self.assertFalse(list(Path(tmp).glob("*.tmp")))

    def test_downgrade_rejects_non_boolean_and_changed_semantics(self):
        payload = {"settings_schema_version": SETTINGS_SCHEMA_VERSION, "show_setting_limits": True, "setting_compatibility": dict(SETTING_COMPATIBILITY_CATALOG)}
        for value, token in (("false", "numeric-limits-visibility-v1"), (1, "numeric-limits-visibility-v1"), (False, "other-units-v2")):
            result = merge_compatible_setting_changes(payload, {"show_setting_limits": {"token": token, "value": value}})
            self.assertTrue(result.payload["show_setting_limits"])

    def test_future_and_corrupt_originals_remain_unchanged(self):
        for original in (b"not json", json.dumps({"settings_schema_version": SETTINGS_SCHEMA_VERSION + 1, "show_setting_limits": True}).encode()):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)/"settings.json"
                path.write_bytes(original)
                store = UserSettingsStore(path, ROOT / "config/default_settings.json")
                settings, _ = store.load()
                try:
                    store.save(settings, output_root="output", window_width=1000, window_height=800, show_setting_limits=False)
                except VersionedDocumentWriteBlockedError:
                    pass
                self.assertEqual(path.read_bytes(), original)

    def test_external_edit_and_recovery_preserve_originals(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"settings.json"
            path.write_text(json.dumps({"settings_schema_version": 14, "generation": {}}), encoding="utf-8")
            store = UserSettingsStore(path, ROOT / "config/default_settings.json")
            settings, _ = store.load()
            external = path.read_bytes() + b"\n"
            path.write_bytes(external)
            with self.assertRaises(ConcurrentDocumentChangeError):
                store.save(settings, output_root="output", window_width=1000, window_height=800, show_setting_limits=True)
            self.assertEqual(path.read_bytes(), external)
            path.write_bytes(b"broken")
            recovery = UserSettingsStore(path, ROOT / "config/default_settings.json")
            settings, _ = recovery.load()
            recovery.recover(settings, output_root="output", window_width=1000, window_height=800, show_setting_limits=True)
            self.assertTrue(json.loads(path.read_text(encoding="utf-8"))["show_setting_limits"])
            self.assertTrue(any(p.read_bytes() == b"broken" for p in Path(tmp).glob("*backup*")))


if __name__ == "__main__":
    unittest.main()
