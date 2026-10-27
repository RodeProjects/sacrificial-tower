import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QAbstractAnimation, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from cooling_tower.gui.widgets.travel_mode_toggle import TravelModeToggle
from gui_lifecycle import dispose_test_widget


class TravelModeToggleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.toggle = TravelModeToggle()
        self.addCleanup(dispose_test_widget, self.toggle)
        self.toggle.resize(210, 36)
        self.toggle.show()
        self.app.processEvents()

    def test_click_animates_horizontal_selection_and_rapid_reversal_is_continuous(self):
        toggle = self.toggle
        initial = toggle.grab().toImage()
        self.assertFalse(toggle.isChecked())
        self.assertEqual(toggle._position, 1)
        QTest.mouseClick(toggle, Qt.MouseButton.LeftButton)
        self.assertTrue(toggle.isChecked())
        self.assertEqual(toggle._animation.state(), QAbstractAnimation.State.Running)
        toggle._animation.setCurrentTime(toggle.ANIMATION_DURATION_MS//2)
        middle = toggle._position
        self.assertGreater(middle, 0)
        self.assertLess(middle, 1)
        self.assertNotEqual(toggle.grab().toImage(), initial)
        QTest.mouseClick(toggle, Qt.MouseButton.LeftButton)
        self.assertAlmostEqual(toggle._position, middle)
        toggle._animation.setCurrentTime(toggle.ANIMATION_DURATION_MS)
        self.assertFalse(toggle.isChecked())
        self.assertEqual(toggle._position, 1)
        QTest.mouseClick(toggle, Qt.MouseButton.LeftButton)
        toggle._animation.setCurrentTime(toggle.ANIMATION_DURATION_MS)
        self.assertEqual(toggle._position, 0)
        self.assertNotEqual(toggle.grab().toImage(), initial)

    def test_keyboard_and_disabled_state(self):
        toggle = self.toggle
        QTest.keyClick(toggle, Qt.Key.Key_Left)
        self.assertTrue(toggle.isChecked())
        self.assertIn("Alle", toggle.accessibleDescription())
        QTest.keyClick(toggle, Qt.Key.Key_Right)
        self.assertFalse(toggle.isChecked())
        QTest.keyClick(toggle, Qt.Key.Key_Space)
        self.assertTrue(toggle.isChecked())
        toggle.setEnabled(False)
        QTest.mouseClick(toggle, Qt.MouseButton.LeftButton)
        self.assertTrue(toggle.isChecked())

    def test_focus_frame_is_hidden_after_mouse_click_and_shown_for_keyboard_input(self):
        toggle = self.toggle
        toggle.setFocus(Qt.FocusReason.TabFocusReason)
        self.app.processEvents()
        self.assertTrue(toggle._show_keyboard_focus)

        QTest.mouseClick(toggle, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertTrue(toggle.hasFocus())
        self.assertFalse(toggle._show_keyboard_focus)

        QTest.keyClick(toggle, Qt.Key.Key_Right)
        self.assertTrue(toggle._show_keyboard_focus)

    def test_hidden_changes_finish_at_selected_position_without_running_animation(self):
        toggle = self.toggle
        toggle.click()
        toggle.hide()
        self.assertEqual(toggle._position, 0)
        self.assertEqual(toggle._animation.state(), QAbstractAnimation.State.Stopped)
        toggle.setChecked(False)
        self.assertEqual(toggle._position, 1)
        self.assertEqual(toggle._animation.state(), QAbstractAnimation.State.Stopped)


if __name__ == "__main__":
    unittest.main()
