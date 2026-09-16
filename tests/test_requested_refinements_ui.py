from __future__ import annotations

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

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from cooling_tower.gui.main_window import MainWindow
from cooling_tower.gui.preview_dialog import PreviewDialog
from cooling_tower.gui.settings_store import UserSettingsStore
from cooling_tower.gui.widgets.preview_canvas import PreviewCanvas
from cooling_tower.gui.widgets.preparation_controls import _PreparationState
from cooling_tower.legal_documents import DOCUMENTS, render_legal_document
from cooling_tower.models import GenerationSettings
from cooling_tower.preview import PreviewState, OutputMode
from test_phase17 import preview_scene


class RequestedRefinementsUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_status_text_and_icon_toggle_the_same_navigation_state(self):
        canvas = PreviewCanvas()
        canvas.set_scene(preview_scene())
        canvas.show()
        self.app.processEvents()
        QTest.mouseClick(canvas.navigation_status_label, Qt.MouseButton.LeftButton)
        self.assertTrue(canvas.navigation_enabled)
        self.assertTrue(canvas.navigation_toggle.isChecked())
        QTest.mouseClick(canvas.navigation_toggle, Qt.MouseButton.LeftButton)
        self.assertFalse(canvas.navigation_enabled)
        canvas.navigation_status_label.setFocus()
        QTest.keyClick(canvas.navigation_status_label, Qt.Key.Key_Space)
        self.assertTrue(canvas.navigation_enabled)
        self.assertEqual(canvas.navigation_status_label.text(), "Navigation aktiviert")
        canvas.close()

    def test_front_and_side_are_orthogonal_for_different_placements(self):
        canvas = PreviewCanvas()
        scene = preview_scene()
        for center in ((20, 20), (0, 30), (40, 0)):
            canvas.set_scene(replace(scene, tower_center_xy_mm=center))
            canvas.side_view()
            side = canvas.yaw_deg
            canvas.front_view()
            self.assertAlmostEqual(abs(side - canvas.yaw_deg), 90)
            self.assertEqual(canvas.pitch_deg, 0)
        canvas.close()

    def test_each_completed_generation_restores_side_and_correct_layer_labels(self):
        dialog = PreviewDialog()
        scene = replace(preview_scene(), object_height_mm=0.65, tower_height_mm=0.65,
                        object_layer_count=3, tower_layer_count=3)
        result = SimpleNamespace(scene=scene, output_mode=OutputMode.STL)
        with patch.object(dialog, "_quality_summary", return_value=("", "current")), \
             patch.object(dialog, "_last_iteration_summary", return_value=""):
            for _ in range(2):
                dialog.canvas.three_quarter_view()
                dialog.canvas.zoom = 3
                dialog.set_preview(result)
                self.assertEqual(dialog.canvas.yaw_deg, dialog.canvas._side_by_side_yaw_deg())
                self.assertEqual(dialog.canvas.zoom, dialog.canvas.SIDE_VIEW_ZOOM)
                self.assertFalse(dialog.canvas.navigation_enabled)
        self.assertIn(">3</span>", dialog.layers_info_label.text())
        self.assertEqual(dialog.layers_info_label.text().count(">3</span>"), 2)
        self.assertIn("0,65 mm", dialog.height_info_label.text())
        self.assertEqual(dialog.height_info_label.text().count("0,65 mm"), 2)
        dialog.close()

    def test_abort_palette_matches_remove_and_returns_to_blue(self):
        with tempfile.TemporaryDirectory() as temporary:
            window = MainWindow(user_settings_path=Path(temporary) / "settings.json",
                                enable_update_check=False, enable_startup_slicer_discovery=False)
            window.drop_zone.remove_button.setEnabled(True)
            window.preview_button.setEnabled(True)
            window.preview_state = PreviewState.BUILDING
            window._update_responsive_action_labels()
            for widget in (window.preview_button, window.preslice_cancel_button,
                           window.drop_zone.remove_button):
                widget.ensurePolished()
            for role in (QPalette.ColorRole.Button, QPalette.ColorRole.ButtonText):
                expected = window.drop_zone.remove_button.palette().color(role)
                self.assertEqual(window.preview_button.palette().color(role), expected)
                self.assertEqual(window.preslice_cancel_button.palette().color(role), expected)
            window.preview_state = PreviewState.EMPTY
            window._update_responsive_action_labels()
            self.assertFalse(window.preview_button.property("cancelAction"))
            self.assertEqual(window.preview_button.palette().color(QPalette.ColorRole.Button).name(), "#1769aa")
            window.close()

    def test_preslice_is_a_separate_required_completion(self):
        state = _PreparationState(True, True, True, True, True, True)
        self.assertFalse(state.preparation_completed)
        self.assertFalse(state.requirements()["preslice_completed"])
        self.assertTrue(replace(state, preslice_completed=True).preparation_completed)

    def test_default_window_is_51_and_explicit_saved_value_is_preserved(self):
        self.assertEqual(GenerationSettings().local_reference_window, 51)
        with tempfile.TemporaryDirectory() as temporary:
            store = UserSettingsStore(Path(temporary) / "user.json", ROOT / "config/default_settings.json")
            self.assertEqual(store.load()[0].local_reference_window, 51)
            store.save(GenerationSettings(local_reference_window=5), output_root=temporary,
                       window_width=900, window_height=700)
            self.assertEqual(store.load()[0].local_reference_window, 5)

    def test_legal_documents_keep_user_rights_without_internal_release_checklists(self):
        for title in DOCUMENTS:
            rendered = render_legal_document(title)
            self.assertNotIn("release_legal_review", rendered)
            self.assertNotIn("Gesamtprüfung:", rendered)
            self.assertNotIn("Noch offene Freigabe", rendered)
        third_party = render_legal_document("Drittanbieter-Lizenzen")
        self.assertIn("LGPLv3", third_party)
        self.assertIn("source_build_notes.md", third_party)
        self.assertNotIn("Eine Sicherung der Installation", third_party)
        self.assertIn("Reverse Engineering", third_party)


if __name__ == "__main__":
    unittest.main()
