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
        self.accept_button = QPushButton("Bestes bisheriges\nErgebnis übernehmen")
        self.continue_button.setObjectName("generationContinueButton")
        self.export_button.setObjectName("generationExportButton")
        self.accept_button.setObjectName("generationAcceptButton")
        self.row = GenerationResultActions(self.continue_button, self.export_button, self.accept_button)
        self.row.setStyleSheet((ROOT / "src/cooling_tower/gui/styles.qss").read_text(encoding="utf-8"))
        self.addCleanup(dispose_test_widget, self.row)
        self.accept_button.hide()
        self.row.set_offer_visible(True)
        self.row.show()

    def resize_row(self, width):
        self.row.setFixedWidth(width)
        for _ in range(4):
            self.app.processEvents()
            self.row.resize(width, self.row.sizeHint().height())

    def presentation(self):
        if self.row.title_label.isHidden():
            return "buttons"
        if self.row.description_label.isHidden():
            return "wrapped"
        if "nach deinen Vorstellungen." in self.row.description_label.text():
            return "full"
        return "short"

    def assert_buttons_fit(self):
        buttons = [button for button in (self.continue_button, self.row.manual_button, self.export_button)
                   if not button.isHidden()]
        previous_right = -1
        bottoms = []
        for button in buttons:
            top_left = button.mapTo(self.row, QPoint())
            self.assertGreater(top_left.x(), previous_right)
            self.assertGreaterEqual(top_left.x(), 0)
            previous_right = top_left.x() + button.width() - 1
            self.assertLess(previous_right, self.row.width())
            self.assertGreaterEqual(button.width(), button.fontMetrics().horizontalAdvance(button.text()) + 8)
            bottoms.append(top_left.y() + button.height())
        self.assertLessEqual(max(bottoms) - min(bottoms), 1)

    def test_hint_shortens_in_order_and_restores_when_growing(self):
        self.resize_row(1400)
        minimum_width = sum(button.width() for button in (
            self.continue_button, self.row.manual_button, self.export_button,
        )) + 2 * self.row.layout().spacing() - 48
        stages = []
        for width in range(1400, minimum_width - 1, -5):
            self.resize_row(width)
            stage = self.presentation()
            if not stages or stages[-1] != stage:
                stages.append(stage)
            self.assert_buttons_fit()
            if stage == "wrapped":
                self.assertEqual(self.row.title_label.text().count("\n"), 1)
            for label in (self.row.title_label, self.row.description_label):
                if not label.isHidden():
                    for line in label.text().split("\n"):
                        self.assertLessEqual(label.fontMetrics().horizontalAdvance(line), label.width())
        self.assertEqual(stages, ["full", "short", "wrapped", "buttons"])
        self.resize_row(1400)
        self.assertEqual(self.presentation(), "full")

    def test_buttons_reduce_padding_only_after_both_texts_are_hidden(self):
        self.resize_row(1400)
        buttons = (self.continue_button, self.row.manual_button, self.export_button)
        normal_widths = [button.width() for button in buttons]
        normal_required = sum(normal_widths) + 2 * self.row.layout().spacing()
        for deficit in (0, 12, 36, 48):
            self.resize_row(normal_required - deficit)
            self.assert_buttons_fit()
            if deficit:
                self.assertTrue(self.row.title_label.isHidden())
                self.assertTrue(self.row.description_label.isHidden())
                for button, normal in zip(buttons, normal_widths):
                    self.assertLess(button.width(), normal)
        self.resize_row(1400)
        self.assertEqual([button.width() for button in buttons], normal_widths)

    def test_offer_uses_released_space_when_continue_is_absent(self):
        self.resize_row(1400)
        self.assertEqual(self.presentation(), "full")
        for width in range(1400, 600, -10):
            self.resize_row(width)
            if self.presentation() == "short":
                break
        self.assertEqual(self.presentation(), "short")
        self.continue_button.hide()
        self.resize_row(width)
        self.assertEqual(self.presentation(), "full")
        self.assert_buttons_fit()
        self.continue_button.show()
        self.resize_row(width)
        self.assertEqual(self.presentation(), "short")

    def test_keyboard_focus_follows_button_order_without_changing_widths(self):
        self.resize_row(1400)
        buttons = (self.continue_button, self.row.manual_button, self.export_button)
        widths = [button.width() for button in buttons]
        self.continue_button.setFocus()
        for before, after in zip(buttons, buttons[1:]):
            QTest.keyClick(before, Qt.Key.Key_Tab)
            self.app.processEvents()
            self.assertTrue(after.hasFocus())
            self.assertEqual([button.width() for button in buttons], widths)


if __name__ == "__main__":
    unittest.main()
