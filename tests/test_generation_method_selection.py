from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, PropertyMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("COOLING_TOWER_DISABLE_SLICER_DISCOVERY", "1")

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from cooling_tower.gui.background_jobs import JobKind
from cooling_tower.gui.generation_session import GenerationMode
from cooling_tower.gui.main_window import MainWindow
from cooling_tower.models import SourceArtifact, SourceKind
from cooling_tower.preview import PreviewState


class GenerationMethodSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.window = MainWindow(
            user_settings_path=Path(self.temporary.name) / "settings.json",
            enable_update_check=False,
            enable_startup_slicer_discovery=False,
        )
        self.window.show()
        self.app.processEvents()

    def tearDown(self) -> None:
        self.window.close()
        self.app.processEvents()
        self.temporary.cleanup()

    def finish_preparation(self) -> None:
        workflow = self.window.workflow
        workflow.set_slicer_step_visible(True)
        workflow.source_validation_succeeded("modell.stl", analysis_complete=True)
        workflow.slicer_succeeded("Testslicer")
        workflow.complete_preparation()
        self.app.processEvents()

    def test_both_methods_require_source_slicer_and_preparation_confirmation(self) -> None:
        window = self.window
        self.assertEqual(set(GenerationMode), {GenerationMode.AUTOMATIC, GenerationMode.MANUAL})
        self.assertEqual(set(window.generation_sessions), set(GenerationMode))
        workflow = window.workflow
        workflow.set_slicer_step_visible(True)
        for stage in ("empty", "source", "slicer"):
            if stage == "source":
                workflow.source_validation_succeeded("modell.stl", analysis_complete=True)
            elif stage == "slicer":
                workflow.slicer_succeeded("Testslicer")
            with self.subTest(stage=stage), patch.object(window.manual_controller, "ensure_context") as prepare:
                for mode in GenerationMode:
                    window.select_generation_mode(mode)
                    self.assertIsNone(window.generation_mode)
                window.show_generation_method_selection()
                self.app.processEvents()
                self.assertTrue(window.generation_workspace.isHidden())
                self.assertTrue(window.footer.isHidden())
                self.assertFalse(window.automatic_generation_card.isEnabled())
                self.assertFalse(window.manual_generation_card.isEnabled())
                prepare.assert_not_called()
        workflow.complete_preparation()
        self.app.processEvents()
        self.assertTrue(window.generation_method_picker.isVisible())
        for mode in GenerationMode:
            with self.subTest(mode=mode), patch.object(window.manual_controller, "ensure_context"):
                window.select_generation_mode(mode)
                self.assertIs(window.generation_mode, mode)
                self.assertFalse(window.workflow_group.isVisible())
                self.assertTrue(window.preparation_open_button.isVisible())
                self.assertIs(window.window_pages.currentWidget(), window.main_surface)
                self.assertTrue(window.footer.isVisible())
                window.show_generation_method_selection()

    def test_confirmation_reveals_only_method_selection(self) -> None:
        window = self.window
        self.assertTrue(window.generation_workspace.isHidden())
        self.assertFalse(window.automatic_generation_card.isEnabled())
        self.assertFalse(window.manual_generation_card.isEnabled())
        window.automatic_generation_card.click()
        self.assertIsNone(window.generation_mode)
        self.finish_preparation()
        self.assertTrue(window.workflow_group.isChecked())
        self.assertFalse(window.workflow_group.isCheckable())
        self.assertTrue(window.generation_method_picker.isVisible())
        self.assertTrue(window.ready_grid.isHidden())
        self.assertTrue(window.manual_generation_panel.isHidden())
        self.assertTrue(window.footer.isVisible())
        self.assertTrue(window.generation_method_navigation.isHidden())
        window.automatic_generation_card.click()
        self.app.processEvents()
        self.assertIs(window.generation_mode, GenerationMode.AUTOMATIC)
        self.assertTrue(window.ready_grid.isVisible())
        self.assertTrue(window.footer.isVisible())
        self.assertTrue(window.generation_method_picker.isHidden())
        self.assertTrue(window.generation_method_back_button.isVisible())

    def test_return_and_manual_visit_preserve_unexported_automatic_tower(self) -> None:
        window = self.window
        self.finish_preparation()
        window.automatic_generation_card.click()
        window.target_time_spin.setValue(window.target_time_spin.value() + 2)
        artifact = Path(self.temporary.name) / "automatic.stl"
        artifact.write_text("automatic tower", encoding="utf-8")
        dispose = Mock(side_effect=lambda: artifact.unlink())
        preview = SimpleNamespace(
            request_signature="automatic", artifact_sha256="auto-sha", dispose=dispose
        )
        window.current_preview = preview
        window.preview_state = PreviewState.CURRENT
        original_value = window.target_time_spin.value()
        original_request_id = window._preview_request_id
        window._joint_slices_completed = 6
        original_scene = window.preview_dialog.canvas.scene
        with patch.object(window, "_export_block_reason", return_value=None):
            window.generation_method_back_button.click()
            self.assertTrue(window.generation_method_picker.isVisible())
            window.manual_generation_card.click()
            self.assertTrue(window.manual_generation_panel.isVisible())
            self.assertTrue(window.ready_grid.isHidden())
            self.assertTrue(window.footer.isVisible())
            window.generation_method_back_button.click()
            window.automatic_generation_card.click()
            window._refresh_phase17_actions()
        self.assertIs(window.current_preview, preview)
        self.assertIs(window.preview_state, PreviewState.CURRENT)
        self.assertEqual(window.target_time_spin.value(), original_value)
        self.assertEqual(window._joint_slices_completed, 6)
        self.assertEqual(window._preview_request_id, original_request_id)
        self.assertIs(window.preview_dialog.canvas.scene, original_scene)
        self.assertTrue(window.export_button.isEnabled())
        self.assertTrue(artifact.exists())
        dispose.assert_not_called()

    def test_preparation_uses_body_and_preserves_header_footer_and_current_method(self) -> None:
        window = self.window
        self.finish_preparation()
        window.automatic_generation_card.click()
        window.target_time_spin.setValue(window.target_time_spin.value() + 2)
        original_value = window.target_time_spin.value()
        for width, height in ((1450, 1000), (700, 700), (1450, 1000)):
            window.resize(width, height)
            window.preparation_open_button.click()
            for _ in range(3):
                self.app.processEvents()
            self.assertIs(window.window_pages.currentWidget(), window.preparation_workspace)
            self.assertEqual(window.preparation_workspace.size(), window.window_pages.size())
            self.assertLess(window.preparation_workspace.height(), window.centralWidget().height())
            self.assertTrue(window.workflow_group.isVisible())
            self.assertTrue(window.main_header.isVisible())
            self.assertTrue(window.footer.isVisible())
            self.assertTrue(window.main_header.isAncestorOf(window.preparation_open_button))
            self.assertTrue(window.main_header.isAncestorOf(window.generation_method_back_button))
            self.assertLess(window.main_header.geometry().bottom(), window.window_pages.y())
            self.assertLess(window.window_pages.geometry().bottom(), window.footer.y())
            self.assertFalse(window.workflow_group.isCheckable())
            self.assertTrue(window.workflow_group.toggle_button.isHidden())
            self.assertEqual(window.preparation_workspace_scroll.horizontalScrollBar().maximum(), 0)
            window.preparation_close_button.click()
            self.app.processEvents()
            self.assertIs(window.window_pages.currentWidget(), window.main_surface)
            self.assertTrue(window.ready_grid.isVisible())
            self.assertIs(window.generation_mode, GenerationMode.AUTOMATIC)
            self.assertEqual(window.target_time_spin.value(), original_value)

    def test_method_picker_can_be_closed_without_changing_current_method(self) -> None:
        window = self.window
        self.finish_preparation()
        window.automatic_generation_card.click()
        window.generation_method_back_button.click()
        self.assertTrue(window.generation_method_picker.isVisible())
        self.assertTrue(window.main_header.isVisible())
        self.assertTrue(window.footer.isVisible())
        self.assertIs(window.generation_mode, GenerationMode.AUTOMATIC)
        window.preparation_view_button.click()
        self.assertTrue(window.workflow_group.isVisible())
        window._on_workflow_stage_changed(window.workflow.stage.value)
        self.assertTrue(window.workflow_group.isVisible())
        self.assertTrue(window.generation_method_picker.isHidden())
        window.preparation_method_button.click()
        self.assertTrue(window.generation_method_picker.isVisible())
        window.preparation_close_button.click()
        self.assertTrue(window.ready_grid.isVisible())
        self.assertIs(window.generation_mode, GenerationMode.AUTOMATIC)

    def test_header_combines_facts_and_places_actions_beside_title_before_wrapping(self) -> None:
        window = self.window
        self.finish_preparation()
        window.automatic_generation_card.click()
        window.resize(2000, 1000)
        header = window.workflow_header
        rows = (("Dateiname", "modell.stl"), ("Slicer", "Anycubic Slicer Next 2.0.0.3"),
                ("Maschinenprofil", "Anycubic Kobra 3 V2 0.4 nozzle"),
                ("Filamentprofil", "PLA - Tecbears - Schwarz (matt)"),
                ("Prozessprofil", "0.20 mm Standard @Kobra 3 V2"))
        header.set_facts(rows)
        for _ in range(3):
            self.app.processEvents()
        preparation = window.preparation_open_button
        method = window.generation_method_back_button
        prep_width = preparation.sizeHint().width()
        full_width = method.sizeHint().width()
        method.setText("Methode")
        compact_width = method.sizeHint().width()
        offset = prep_width + header.actions_layout.spacing() + 5
        inline_offset = offset + header.brand_widget.sizeHint().width() + header.grid.horizontalSpacing()
        for width, text, inline, wraps in (
            (full_width + inline_offset, "Methode auswählen", True, False),
            (compact_width + inline_offset, "Methode", True, False),
            (compact_width + offset, "Methode", False, False),
            (offset - 10, "Methode", False, True),
            (full_width + inline_offset, "Methode auswählen", True, False),
        ):
            with self.subTest(width=width):
                header.setFixedWidth(width)
                for _ in range(5):
                    self.app.processEvents()
                self.assertEqual(preparation.text(), "")
                self.assertEqual(preparation.accessibleName(), "Datei und Slicer vorbereiten")
                self.assertEqual(method.text(), text)
                self.assertEqual(preparation.status_label.text(), "✓")
                first = QRect(preparation.mapTo(header, QPoint()), preparation.size())
                second = QRect(method.mapTo(header, QPoint()), method.size())
                title = QRect(window.title_label.mapTo(header, QPoint()), window.title_label.size())
                self.assertFalse(first.intersects(second))
                self.assertLessEqual(first.right(), width - 1)
                self.assertLessEqual(second.right(), width - 1)
                self.assertTrue(preparation.isAncestorOf(header.facts_widget))
                mark = preparation.status_label
                self.assertLessEqual(abs(mark.geometry().center().y() - preparation.rect().center().y()), 1)
                self.assertLess(mark.geometry().right(), header.facts_widget.x())
                for key, value in rows:
                    self.assertTrue(header.fact_labels[key].isVisible())
                    self.assertEqual(header.fact_labels[key].text(), value)
                if wraps:
                    self.assertLess(first.bottom(), second.top())
                else:
                    self.assertLess(first.right(), second.left())
                    self.assertLessEqual(abs(first.center().y() - second.center().y()), 1)
                if inline:
                    self.assertLess(title.right(), first.left())
                    self.assertLessEqual(first.top(), title.center().y())
                    self.assertGreaterEqual(first.bottom(), title.center().y())
                else:
                    self.assertLess(title.bottom(), first.top())

    def test_entire_preparation_facts_button_opens_preparation_and_supports_keyboard(self) -> None:
        window = self.window
        self.finish_preparation()
        window.automatic_generation_card.click()
        window.resize(1450, 1000)
        header = window.workflow_header
        header.set_facts((("Dateiname", "modell.stl"), ("Slicer", "Testslicer")))
        self.app.processEvents()
        preparation = window.preparation_open_button
        for child in (preparation.status_label, header.fact_labels["Dateiname"], header.fact_labels["Slicer"]):
            point = child.mapTo(preparation, child.rect().center())
            QTest.mouseClick(preparation, Qt.MouseButton.LeftButton, pos=point)
            self.assertIs(window.window_pages.currentWidget(), window.preparation_workspace)
            self.assertTrue(window.workflow_group.isVisible())
            window.preparation_close_button.click()
        preparation.setFocus()
        QTest.keyClick(preparation, Qt.Key.Key_Space)
        self.assertIs(window.window_pages.currentWidget(), window.preparation_workspace)
        self.assertTrue(window.main_header.isVisible())
        self.assertTrue(window.footer.isVisible())

    def test_header_shows_only_currently_confirmed_file_and_profiles_independently(self) -> None:
        window = self.window
        window.current_source_path = Path(self.temporary.name) / "bestätigt.stl"
        window.current_source_path.write_text("solid test\nendsolid test\n", encoding="ascii")
        window.current_source_kind = SourceKind.STL
        window.source_artifact = SourceArtifact.capture(window.current_source_path)
        window.stl_validation_result = SimpleNamespace(valid=True)
        installation = SimpleNamespace(verified=True, display_name="Testslicer")
        for combo, text in ((window.machine_profile_combo, "Maschine"),
                            (window.filament_profile_combo, "Filament"),
                            (window.process_profile_combo, "Prozess")):
            combo.blockSignals(True)
            combo.addItem(text)
            combo.setCurrentIndex(combo.count() - 1)
            combo.blockSignals(False)
        with patch.object(type(window), "selected_slicer_installation", new_callable=PropertyMock, return_value=installation):
            for file_confirmed, profiles_confirmed in ((True, False), (True, True), (False, True), (False, False)):
                with self.subTest(file=file_confirmed, profiles=profiles_confirmed), \
                     patch.object(window, "_source_step_is_complete", return_value=file_confirmed), \
                     patch.object(window, "_catalog_selection_is_confirmed", return_value=profiles_confirmed):
                    window._refresh_preparation_header_summary(False)
                    self.app.processEvents()
                    facts = dict(window.workflow_header.facts)
                    self.assertEqual("Dateiname" in facts, file_confirmed)
                    self.assertEqual("Slicer" in facts, profiles_confirmed)
                    for key in ("Maschinenprofil", "Filamentprofil", "Prozessprofil"):
                        self.assertEqual(key in facts, profiles_confirmed)
                    self.assertEqual(window.workflow_header.facts_widget.isVisible(), file_confirmed or profiles_confirmed)
                    if file_confirmed and profiles_confirmed:
                        self.finish_preparation()
                        window.automatic_generation_card.click()
                        with patch.object(window, "_profile_matching_context", return_value=None):
                            for action in (window.show_preparation_workspace,
                                           window.show_generation_method_selection,
                                           window.close_preparation_workspace):
                                action()
                                window._update_preparation_requirements()
                                self.app.processEvents()
                                self.assertTrue(window.main_header.isVisible())
                                self.assertTrue(window.footer.isVisible())
                                self.assertEqual(dict(window.workflow_header.facts), facts)
                                self.assertTrue(all(label.isVisible() for label in window.workflow_header.fact_labels.values()))

    def test_header_wraps_long_unbroken_names_without_losing_confirmed_information(self) -> None:
        window = self.window
        self.finish_preparation()
        window.automatic_generation_card.click()
        window.resize(720, 1000)
        values = (("Dateiname", "langes_modell_" * 12 + ".stl"),
                  ("Maschinenprofil", "SehrLangerProfilname" * 12))
        header = window.workflow_header
        header.set_facts(values)
        for _ in range(6):
            self.app.processEvents()
        for key, text in values:
            label = header.fact_labels[key]
            self.assertEqual(label.text(), text)
            self.assertGreater(label.height(), label.fontMetrics().height() * 2)
            self.assertGreaterEqual(label.height(), label.heightForWidth(label.width()))
            self.assertTrue(header.facts_widget.rect().contains(label.geometry()))
            self.assertTrue(window.main_header.isVisible())
        facts_rectangle = QRect(header.facts_widget.mapTo(header, QPoint()), header.facts_widget.size())
        self.assertTrue(header.rect().contains(facts_rectangle))
        self.assertLess(window.main_header.geometry().bottom(), window.window_pages.y())

    def test_session_results_and_export_status_remain_independent(self) -> None:
        window = self.window
        self.finish_preparation()
        automatic = window.generation_sessions[GenerationMode.AUTOMATIC]
        manual = window.generation_sessions[GenerationMode.MANUAL]
        auto_preview = SimpleNamespace(
            request_signature="auto", artifact_sha256="auto-sha", dispose=Mock()
        )
        manual_preview = SimpleNamespace(
            request_signature="manual", artifact_sha256="manual-sha", dispose=Mock()
        )
        window.current_preview = auto_preview
        window.preview_state = PreviewState.CURRENT
        window._last_exported_preview_identity = ("auto", "auto-sha")
        auto_export = object()
        window.last_export_result = auto_export
        manual.preview = manual_preview
        manual.preview_state = PreviewState.STALE
        manual.exported_preview_identity = ("manual", "manual-sha")
        manual.export_result = object()
        window.manual_generation_card.click()
        self.assertIs(window.current_preview, auto_preview)
        self.assertIs(automatic.export_result, auto_export)
        self.assertIs(manual.preview, manual_preview)
        self.assertIs(manual.preview_state, PreviewState.STALE)
        with patch.object(window, "_export_block_reason", return_value=None):
            window.generation_method_back_button.click()
            window.automatic_generation_card.click()
        self.assertTrue(window._current_preview_was_exported())
        self.assertFalse(window.export_button.isEnabled())
        window.close()
        auto_preview.dispose.assert_called_once()
        manual_preview.dispose.assert_called_once()

    def test_preparation_change_resets_selection_and_invalidates_both_towers(self) -> None:
        window = self.window
        self.finish_preparation()
        window.automatic_generation_card.click()
        disposals = []
        for mode in (GenerationMode.AUTOMATIC,GenerationMode.MANUAL):
            session=window.generation_sessions[mode]
            dispose = Mock()
            disposals.append(dispose)
            session.preview = SimpleNamespace(dispose=dispose)
            session.preview_state = PreviewState.CURRENT
        window._discard_generated_tower()
        window.workflow.reset()
        self.app.processEvents()
        self.assertIsNone(window.generation_mode)
        self.assertTrue(window.generation_workspace.isHidden())
        self.assertFalse(window.automatic_generation_card.isEnabled())
        self.assertFalse(window.manual_generation_card.isEnabled())
        self.assertIs(window.window_pages.currentWidget(), window.preparation_workspace)
        self.assertTrue(window.workflow_group.isVisible())
        self.assertFalse(window.preparation_method_button.isEnabled())
        window.close_preparation_workspace()
        self.assertIs(window.window_pages.currentWidget(), window.preparation_workspace)
        for session, dispose in zip((window.generation_sessions[GenerationMode.AUTOMATIC],window.generation_sessions[GenerationMode.MANUAL]), disposals):
            self.assertIsNone(session.preview)
            self.assertIs(session.preview_state, PreviewState.EMPTY)
            dispose.assert_called_once()
        self.finish_preparation()
        self.assertTrue(window.generation_method_picker.isVisible())

    def test_switch_is_locked_while_generating_or_exporting(self) -> None:
        window = self.window
        self.finish_preparation()
        window.automatic_generation_card.click()
        for kind in (JobKind.PREVIEW, JobKind.EXPORT):
            with self.subTest(kind=kind), patch.object(
                window.background_job_manager, "has_active", side_effect=lambda queried: queried is kind
            ):
                window._refresh_phase17_actions()
                self.assertFalse(window.generation_method_back_button.isEnabled())
                self.assertFalse(window.preparation_open_button.isEnabled())
                window.show_preparation_workspace()
                self.assertIs(window.window_pages.currentWidget(), window.main_surface)
                window.show_generation_method_selection()
                window.select_generation_mode(GenerationMode.MANUAL)
                self.assertIs(window.generation_mode, GenerationMode.AUTOMATIC)
        window._refresh_phase17_actions()
        self.assertTrue(window.generation_method_back_button.isEnabled())

    def test_cards_stack_and_whole_card_supports_mouse_and_keyboard(self) -> None:
        window = self.window
        self.finish_preparation()
        for width, two_column in ((1400, True), (760, False), (1400, True)):
            window.resize(width, 850)
            self.app.processEvents()
            grid = window.generation_method_grid
            self.assertEqual(grid.is_two_column(), two_column)
            automatic_rect = window.automatic_generation_card.geometry()
            manual_rect = window.manual_generation_card.geometry()
            if two_column:
                self.assertEqual(automatic_rect.top(), manual_rect.top())
                self.assertLess(automatic_rect.right(), manual_rect.left())
            else:
                self.assertLess(automatic_rect.bottom(), manual_rect.top())
            for card in (window.automatic_generation_card, window.manual_generation_card):
                self.assertLessEqual(card.geometry().right(), grid.width())
                self.assertLessEqual(card.geometry().bottom(), grid.height() - 1)
                self.assertLessEqual(card.action_label.geometry().bottom(), card.height())
        card = window.automatic_generation_card
        QTest.mouseClick(card, Qt.MouseButton.LeftButton, pos=card.title_label.geometry().center())
        self.assertIs(window.generation_mode, GenerationMode.AUTOMATIC)
        window.generation_method_back_button.click()
        window.manual_generation_card.setFocus()
        QTest.keyClick(window.manual_generation_card, Qt.Key.Key_Space)
        self.assertIs(window.generation_mode, GenerationMode.MANUAL)
        self.assertTrue(window.manual_generation_panel.isVisible())

    def test_picker_is_centered_and_uses_side_space_before_stacking(self) -> None:
        window = self.window
        self.finish_preparation()
        heading = window.generation_method_heading
        self.assertEqual(heading.text(), "Wie soll der Kühlturm erstellt werden?")
        self.assertTrue(heading.alignment() & Qt.AlignmentFlag.AlignHCenter)
        for card in (window.automatic_generation_card, window.manual_generation_card):
            self.assertTrue(card.title_label.alignment() & Qt.AlignmentFlag.AlignHCenter)
        for width in (1800, 1400, 1060, 1000, 860, 760, 1800):
            with self.subTest(width=width):
                window.resize(width, 850)
                for _ in range(3):
                    self.app.processEvents()
                grid = window.generation_method_grid
                picker = window.generation_method_picker
                self.assertEqual(grid.width(), min(980, picker.width()))
                left_space = grid.x()
                right_space = picker.width() - grid.geometry().right() - 1
                self.assertLessEqual(abs(left_space - right_space), 1)
                self.assertEqual(grid.is_two_column(), picker.width() >= 800)
                if picker.width() <= 980:
                    self.assertEqual(left_space, 0)
                else:
                    self.assertGreater(left_space, 0)
                for card in (window.automatic_generation_card, window.manual_generation_card):
                    self.assertTrue(grid.rect().contains(card.geometry()))

    def test_every_method_description_fits_after_repeated_width_changes(self) -> None:
        from PySide6.QtCore import QRect
        window=self.window
        self.finish_preparation()
        for width in (1800,1060,860,760,950,1400,1800):
            window.resize(width,900)
            for _ in range(4):self.app.processEvents()
            for card in (window.automatic_generation_card,window.manual_generation_card):
                for label in (card.title_label,card.description_label,card.action_label):
                    with self.subTest(width=width,text=label.text()):
                        required=label.fontMetrics().boundingRect(QRect(0,0,label.width(),100000),
                            Qt.TextFlag.TextWordWrap,label.text()).height()
                        self.assertGreaterEqual(label.height(),required)
                        self.assertGreaterEqual(label.y(),0)
                        self.assertLess(label.geometry().bottom(),card.height())


if __name__ == "__main__":
    unittest.main()
