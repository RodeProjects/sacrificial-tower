from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("COOLING_TOWER_DISABLE_SLICER_DISCOVERY", "1")

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication
from cooling_tower.gui.generation_session import GenerationMode
from cooling_tower.gui.main_window import MainWindow
from gui_lifecycle import dispose_test_widget


class ExportPathsGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.path = self.root / "settings.json"
        self.window = MainWindow(user_settings_path=self.path,
            enable_update_check=False, enable_startup_slicer_discovery=False)

    def tearDown(self):
        dispose_test_widget(self.window)
        self.temporary.cleanup()

    def dialog(self):
        self.window.show_joint_slice_settings()
        return self.window._joint_slice_settings_dialog

    def test_defaults_are_separate_and_single_resets_restore_only_their_method(self):
        defaults = self.window.default_export_roots
        self.assertEqual(len(set(defaults.values())), 3)
        for method, path in defaults.items():
            self.assertEqual(Path(path).name, method)
        dialog = self.dialog()
        for method, edit in dialog.export_root_edits.items():
            edit.setText(str(self.root / method))
        dialog.export_reset_buttons["manual"].click()
        self.assertEqual(dialog.export_root_edits["manual"].text(), defaults["manual"])
        self.assertEqual(dialog.export_root_edits["automatic"].text(), str(self.root / "automatic"))
        self.assertEqual(dialog.export_root_edits["preprocessor"].text(), str(self.root / "preprocessor"))
        for method, edit in dialog.export_root_edits.items():
            with patch("cooling_tower.gui.generation_progress_dialog.QFileDialog.getExistingDirectory",
                    return_value=str(self.root / (method + "-selected"))):
                dialog.export_browse_buttons[method].click()
            self.assertEqual(edit.text(), str(self.root / (method + "-selected")))
        dialog.accept()
        dispose_test_widget(self.window)
        self.window = MainWindow(user_settings_path=self.path,
            enable_update_check=False, enable_startup_slicer_discovery=False)
        for mode in GenerationMode:
            self.assertEqual(self.window.export_directory(mode), self.root / (mode.value + "-selected"))

    def test_cancel_preserves_all_paths_and_empty_values_prevent_apply(self):
        before = dict(self.window.export_roots)
        dialog = self.dialog()
        dialog.export_root_edits["manual"].setText(" ")
        dialog.accept()
        self.assertTrue(dialog.isVisible())
        self.assertEqual(self.window.export_roots, before)
        dialog.reject()
        self.assertEqual(self.window.export_roots, before)

    def test_general_reset_restores_each_method_and_rows_fit_dialog(self):
        workflow = self.window.workflow
        workflow.set_slicer_step_visible(True)
        workflow.source_validation_succeeded("model.stl", analysis_complete=True)
        workflow.slicer_succeeded("Testslicer")
        workflow.complete_preparation()
        dialog = self.dialog()
        for method, edit in dialog.export_root_edits.items():
            edit.setText(str(self.root / method))
        self.assertTrue(dialog.general_reset_button.isEnabled())
        dialog.general_reset_button.click()
        for method, edit in dialog.export_root_edits.items():
            self.assertEqual(edit.text(), self.window.default_export_roots[method])
            self.assertFalse(dialog.export_reset_buttons[method].isEnabled())
        self.app.processEvents()
        for method, edit in dialog.export_root_edits.items():
            widgets = (edit, dialog.export_browse_buttons[method], dialog.export_reset_buttons[method])
            self.assertEqual(len({w.mapTo(dialog, QPoint()).y() for w in widgets}), 1)
            self.assertTrue(all(w.mapTo(dialog, QPoint(w.width(), 0)).x() < dialog.width() for w in widgets))

    def test_manual_export_worker_uses_manual_folder(self):
        controller = self.window.manual_controller
        controller.session.preview = SimpleNamespace(request_signature="a", artifact_sha256="b", dispose=lambda: None)
        controller.session.successful_request = object()
        self.window.export_roots["manual"] = str(self.root / "manual")
        with patch.object(controller, "_context_current", return_value=True), patch.object(controller, "_start") as start:
            controller.export()
        self.assertEqual(start.call_args.args[0].output_root, self.root / "manual")

    def test_opening_output_folder_respects_active_method_and_protected_slicer_paths(self):
        self.window.generation_mode = GenerationMode.PREPROCESSOR
        self.window.export_roots["preprocessor"] = str(self.root / "preprocessor")
        with patch("cooling_tower.gui.main_window.open_directory") as opened:
            self.window.open_output_directory()
            opened.assert_called_once_with((self.root / "preprocessor").resolve())
        protected = self.root / "slicer-profiles"
        installation = SimpleNamespace(executable_path=self.root / "slicer-installation/slicer.exe",
            profile_roots=(protected,))
        self.window.profile_match_result = SimpleNamespace(
            selected=SimpleNamespace(effective_profile=SimpleNamespace(installation=installation)))
        self.window.export_roots["preprocessor"] = str(protected / "outputs")
        with patch("cooling_tower.gui.main_window.open_directory") as opened:
            self.window.open_output_directory()
            opened.assert_not_called()
        self.assertFalse(protected.exists())
        self.assertIn("nicht geöffnet", self.window.preprocessor_panel.status.text())
        self.window.profile_match_result = None

    def test_empty_automatic_directory_never_opens_working_directory(self):
        self.window.output_root_edit.setText("")
        self.assertFalse(self.window.open_output_button.isEnabled())
        with patch("cooling_tower.gui.main_window.open_directory") as opened:
            self.window.open_output_directory()
            opened.assert_not_called()


if __name__ == "__main__":
    unittest.main()
