from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("COOLING_TOWER_DISABLE_SLICER_DISCOVERY", "1")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from cooling_tower.gui.background_jobs import JobKind
from cooling_tower.gui.generation_session import GenerationMode
from cooling_tower.gui.main_window import MainWindow
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

    def test_confirmation_reveals_only_method_selection(self) -> None:
        window = self.window
        self.assertTrue(window.generation_workspace.isHidden())
        window.automatic_generation_card.click()
        self.assertIsNone(window.generation_mode)
        self.finish_preparation()
        self.assertFalse(window.workflow_group.isChecked())
        self.assertTrue(window.generation_method_picker.isVisible())
        self.assertTrue(window.ready_grid.isHidden())
        self.assertTrue(window.manual_generation_placeholder.isHidden())
        self.assertTrue(window.footer.isHidden())
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
            self.assertTrue(window.manual_generation_placeholder.isVisible())
            self.assertTrue(window.ready_grid.isHidden())
            self.assertTrue(window.footer.isHidden())
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
        for session in window.generation_sessions.values():
            dispose = Mock()
            disposals.append(dispose)
            session.preview = SimpleNamespace(dispose=dispose)
            session.preview_state = PreviewState.CURRENT
        window._discard_generated_tower()
        window.workflow.reset()
        self.app.processEvents()
        self.assertIsNone(window.generation_mode)
        self.assertTrue(window.generation_workspace.isHidden())
        for session, dispose in zip(window.generation_sessions.values(), disposals):
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
                self.assertLessEqual(card.action_label.geometry().bottom(), card.height())
        card = window.automatic_generation_card
        QTest.mouseClick(card, Qt.MouseButton.LeftButton, pos=card.title_label.geometry().center())
        self.assertIs(window.generation_mode, GenerationMode.AUTOMATIC)
        window.generation_method_back_button.click()
        window.manual_generation_card.setFocus()
        QTest.keyClick(window.manual_generation_card, Qt.Key.Key_Space)
        self.assertIs(window.generation_mode, GenerationMode.MANUAL)
        self.assertTrue(window.manual_generation_placeholder.isVisible())

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


if __name__ == "__main__":
    unittest.main()
