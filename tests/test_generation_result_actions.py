from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton
from cooling_tower.gui.widgets.generation_result_actions import GenerationResultActions
from gui_lifecycle import dispose_test_widget


class GenerationResultActionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.font_ids = []
        for name in ("segoeui.ttf", "seguisym.ttf"):
            path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
            if path.is_file():
                font_id = QFontDatabase.addApplicationFont(str(path))
                if font_id >= 0:
                    cls.font_ids.append(font_id)

    @classmethod
    def tearDownClass(cls):
        for font_id in cls.font_ids:
            QFontDatabase.removeApplicationFont(font_id)

    def setUp(self):
        self.continue_button = QPushButton("Angleichung fortsetzen")
        self.export_button = QPushButton("Kühlturm exportieren")
        self.accept_button = QPushButton("Bisheriges Ergebnis übernehmen")
        self.continue_button.setObjectName("generationContinueButton")
        self.export_button.setObjectName("generationExportButton")
        self.accept_button.setObjectName("generationAcceptButton")
        self.row = GenerationResultActions(self.continue_button, self.export_button, self.accept_button)
        self.row.setStyleSheet((ROOT / "src/cooling_tower/gui/styles.qss").read_text(encoding="utf-8"))
        self.addCleanup(dispose_test_widget, self.row)
        self.accept_button.hide()
        self.row.set_hint_visible(True)
        self.row.show()

    def resize_row(self, width):
        self.row.setFixedWidth(width)
        for _ in range(4):
            self.app.processEvents()
            self.row.resize(width, self.row.sizeHint().height())

    def assert_buttons_fit(self):
        buttons = [button for button in (self.continue_button, self.export_button)
                   if not button.isHidden()]
        if not self.row.manual_hint.isHidden():
            self.assertGreaterEqual(self.row.manual_hint.height(),
                                    self.row.manual_hint.heightForWidth(self.row.manual_hint.width()))
            buttons.insert(0, self.row.manual_hint)
        positions = [button.mapTo(self.row, QPoint()) for button in buttons]
        for button, position in zip(buttons, positions):
            self.assertGreaterEqual(position.x(), 0)
            self.assertLessEqual(position.x() + button.width(), self.row.width())
            self.assertGreaterEqual(position.y(), 0)
            self.assertLessEqual(position.y() + button.height(), self.row.height())
        for index, (button, position) in enumerate(zip(buttons, positions)):
            rect = button.rect().translated(position)
            for other, other_position in zip(buttons[index+1:], positions[index+1:]):
                self.assertFalse(rect.intersects(other.rect().translated(other_position)))

    def test_manual_hint_is_left_and_primary_actions_are_adjacent_on_the_right(self):
        for width in (1400, 900, 680, 600):
            with self.subTest(width=width):
                self.resize_row(width)
                self.assert_buttons_fit()
                manual = self.row.manual_hint.mapTo(self.row, QPoint())
                resume = self.continue_button.mapTo(self.row, QPoint())
                export = self.export_button.mapTo(self.row, QPoint())
                self.assertEqual(manual.x(), 0)
                self.assertLessEqual(abs(manual.y() + self.row.manual_hint.height() / 2
                                         - resume.y() - self.continue_button.height() / 2), 1)
                self.assertEqual(resume.y(), export.y())
                self.assertEqual(export.x() - resume.x() - self.continue_button.width(), 8)
                self.assertEqual(export.x() + self.export_button.width(), width)

    def test_narrow_rows_stack_without_clipping_buttons(self):
        for width in (480, 360, 240, 600, 1400):
            with self.subTest(width=width):
                self.resize_row(width)
                self.assert_buttons_fit()
        self.assertLessEqual(abs(self.row.manual_hint.geometry().center().y()
                                - self.row.primary_actions.geometry().center().y()), 1)

    def test_export_remains_right_aligned_without_continue(self):
        self.continue_button.hide()
        self.resize_row(680)
        self.assert_buttons_fit()
        self.assertEqual(self.row.manual_hint.mapTo(self.row, QPoint()).x(), 0)
        export = self.export_button.mapTo(self.row, QPoint())
        self.assertEqual(export.x() + self.export_button.width(), 680)

    def test_keyboard_focus_follows_the_visible_order(self):
        self.resize_row(900)
        buttons = (self.continue_button, self.export_button)
        widths = [button.width() for button in buttons]
        self.continue_button.setFocus()
        for before, after in zip(buttons, buttons[1:]):
            QTest.keyClick(before, Qt.Key.Key_Tab)
            self.app.processEvents()
            self.assertTrue(after.hasFocus())
            self.assertEqual([button.width() for button in buttons], widths)

    def test_accept_action_fits_during_generation(self):
        self.row.set_hint_visible(False)
        self.export_button.hide()
        self.accept_button.show()
        self.resize_row(680)
        position = self.accept_button.mapTo(self.row, QPoint())
        self.assertEqual(position.x() + self.accept_button.width(), 680)


if __name__ == "__main__":
    unittest.main()
