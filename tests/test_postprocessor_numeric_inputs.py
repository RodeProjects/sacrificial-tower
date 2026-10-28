"""Postprocessor numeric edits commit on completion, never on each digit."""
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from cooling_tower.gui.postprocessor_controls import PostprocessorPanel
from cooling_tower.gui.widgets.committed_numeric_inputs import CommittedDoubleSpinBox
from cooling_tower.gui.widgets.postprocessor_widgets import LayerNumberSpinBox
from gui_lifecycle import dispose_test_widget


class PostprocessorNumericInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.panel = PostprocessorPanel()
        self.panel.footer_widget.setParent(self.panel)
        self.panel.resize(1400, 1000)
        self.panel.show()
        self.panel.automatic["automatic_target_time"].setChecked(False)
        self.spin = self.panel.inputs["target_layer_time_s"]
        self.app.processEvents()

    def tearDown(self):
        dispose_test_widget(self.panel)

    def draft(self, editor, text):
        editor.setFocus()
        editor.selectAll()
        QTest.keyClick(editor, Qt.Key.Key_Backspace)
        QTest.keyClicks(editor, text)
        self.app.processEvents()

    def test_z_hop_auto_profile_manual_precision_steps_and_reset(self):
        auto = self.panel.automatic["automatic_z_hop"]
        editor = self.panel.inputs["z_hop_mm"]
        self.assertTrue(auto.isChecked())
        self.assertFalse(editor.isEnabled())
        self.assertEqual(editor.lineEdit().text(), "0,20")
        self.panel.set_profile_values({"z_hop": ["0.455"]})
        self.assertEqual(editor.value(), .46)
        self.assertEqual(editor.lineEdit().text(), "0,46")
        auto.setChecked(False)
        self.assertTrue(editor.isEnabled())
        self.assertEqual(editor.value(), .46)
        self.panel.advanced_group.set_expanded(True)
        self.app.processEvents()
        self.draft(editor, "0.125")
        QTest.keyClick(editor, Qt.Key.Key_Return)
        self.assertEqual(editor.value(), .13)
        self.assertEqual(editor.lineEdit().text(), "0,13")
        editor.stepUp()
        self.assertEqual(editor.value(), .23)
        editor.stepDown()
        self.assertEqual(editor.value(), .13)
        self.draft(editor, "0")
        QTest.keyClick(editor, Qt.Key.Key_Return)
        self.assertEqual(editor.lineEdit().text(), "0,00")
        self.assertEqual(self.panel.settings().z_hop_mm, 0)
        self.panel.set_profile_values({"z_hop": ["2"]})
        self.assertEqual(editor.value(), 0)
        self.panel.reset_buttons["z_hop_mm"].click()
        self.assertTrue(auto.isChecked())
        self.assertEqual(editor.lineEdit().text(), "2,00")
        self.panel.set_profile_values({"z_hop": ["0"]})
        self.assertEqual(editor.lineEdit().text(), "0,20")

    def test_each_digit_preserves_draft_cursor_and_previous_setting(self):
        changed = QSignalSpy(self.panel.changed)
        editor = self.spin
        old = editor.value()
        editor.setFocus()
        editor.selectAll()
        typed = ""
        for character in "20.3450":
            typed += character
            QTest.keyClicks(editor, character)
            self.app.processEvents()
            self.assertEqual(editor.lineEdit().text(), typed)
            self.assertEqual(editor.lineEdit().cursorPosition(), len(typed))
            self.assertEqual(editor.value(), old)
            self.assertEqual(changed.count(), 0)
        # Layout/profile refreshes must not erase a partially entered value.
        self.panel._sync_automatic()
        self.assertEqual(editor.lineEdit().text(), typed)
        QTest.keyClick(editor, Qt.Key.Key_Return)
        self.assertEqual(editor.value(), 20.35)
        self.assertEqual(editor.lineEdit().text(), "20,35")
        self.assertEqual(changed.count(), 1)

    def test_enter_tab_and_click_commit_and_normalize_identically(self):
        for action in ("enter", "tab", "click"):
            with self.subTest(action=action):
                self.draft(self.spin, "00020.5000")
                self.assertEqual(self.spin.lineEdit().text(), "00020.5000")
                if action == "click":
                    QTest.mouseClick(self.panel.inputs["clearance_mm"], Qt.MouseButton.LeftButton)
                else:
                    QTest.keyClick(self.spin, Qt.Key.Key_Return if action == "enter" else Qt.Key.Key_Tab)
                self.app.processEvents()
                self.assertEqual(self.spin.value(), 20.5)
                self.assertEqual(self.spin.lineEdit().text(), "20,5")
                self.assertFalse(self.spin.input_pending)

    def test_decimal_input_rounding_and_trimming_wait_for_commit(self):
        for text, value, display in (("2", 2, "2"), ("20", 20, "20"), ("2,345", 2.35, "2,35"),
                ("2.344", 2.34, "2,34"), ("2,5000", 2.5, "2,5"), (".1", .1, "0,1")):
            with self.subTest(text=text):
                old = self.spin.value()
                self.draft(self.spin, text)
                self.assertEqual(self.spin.lineEdit().text(), text)
                self.assertEqual(self.spin.value(), old)
                QTest.keyClick(self.spin, Qt.Key.Key_Return)
                self.assertEqual(self.spin.value(), value)
                self.assertEqual(self.spin.lineEdit().text(), display)

    def test_empty_incomplete_and_out_of_range_drafts_are_safe_on_commit(self):
        for text, value in (("", 9), ("-", 9), ("0", .1), ("-2", .1), ("99999", 3600)):
            with self.subTest(text=text):
                self.spin.setValue(9)
                self.draft(self.spin, text)
                self.assertEqual(self.spin.lineEdit().text(), text)
                self.assertEqual(self.spin.value(), 9)
                QTest.keyClick(self.spin, Qt.Key.Key_Return)
                self.assertEqual(self.spin.value(), value)
                self.assertTrue(self.spin.hasAcceptableInput())

    def test_replacing_selection_and_editing_in_middle_do_not_move_cursor(self):
        self.draft(self.spin, "20.5")
        edit = self.spin.lineEdit()
        edit.setSelection(0, 2)
        QTest.keyClicks(edit, "12")
        self.assertEqual(edit.text(), "12.5")
        self.assertEqual(edit.cursorPosition(), 2)
        edit.setCursorPosition(4)
        QTest.keyClicks(edit, "34")
        self.assertEqual(edit.text(), "12.534")
        QTest.keyClick(self.spin, Qt.Key.Key_Return)
        self.assertEqual(self.spin.lineEdit().text(), "12,53")

    def test_coordinate_units_negative_rounding_and_step_are_preserved(self):
        editor = CommittedDoubleSpinBox(self.panel)
        editor.setRange(-2000, 2000)
        editor.setDecimals(2)
        editor.setSuffix(" mm")
        editor.show()
        self.draft(editor, "-2.345")
        self.assertEqual(editor.cleanText(), "-2.345")
        QTest.keyClick(editor, Qt.Key.Key_Return)
        self.assertEqual(editor.value(), -2.35)
        self.assertEqual(editor.text(), "-2,35 mm")
        self.draft(editor, "-0.00001")
        QTest.keyClick(editor, Qt.Key.Key_Return)
        self.assertEqual(editor.text(), "0 mm")
        self.draft(editor, "2.5")
        editor.stepUp()
        self.assertEqual(editor.value(), 3.5)
        self.assertFalse(editor.input_pending)

    def test_pasted_decimal_is_preserved_until_commit(self):
        previous = self.app.clipboard().text()
        try:
            self.app.clipboard().setText("20.3450")
            self.spin.setFocus()
            self.spin.selectAll()
            QTest.keyClick(self.spin, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(self.spin.lineEdit().text(), "20.3450")
            self.assertEqual(self.spin.value(), 10)
            QTest.keyClick(self.spin, Qt.Key.Key_Return)
            self.assertEqual(self.spin.value(), 20.35)
        finally:
            self.app.clipboard().setText(previous)

    def test_manual_ten_second_default_and_both_reset_paths_survive_profile_changes(self):
        panel, editor = self.panel, self.spin
        automatic = panel.automatic["automatic_target_time"]
        reset = panel.reset_buttons["target_layer_time_s"]
        self.assertEqual(editor.value(), 10)
        self.assertFalse(automatic.isChecked())
        self.assertTrue(editor.isEnabled())
        self.assertFalse(reset.isEnabled())
        panel.set_profile_values({"slow_down_layer_time": 18})
        self.assertEqual(editor.value(), 10)
        automatic.setChecked(True)
        self.assertEqual(editor.value(), 18)
        self.assertFalse(editor.isEnabled())
        self.assertTrue(reset.isEnabled())
        reset.click()
        self.assertFalse(automatic.isChecked())
        self.assertEqual(editor.value(), 10)
        self.assertTrue(editor.isEnabled())
        self.assertFalse(reset.isEnabled())
        editor.setValue(22)
        self.assertTrue(reset.isEnabled())
        reset.click()
        self.assertEqual(editor.value(), 10)
        automatic.setChecked(True)
        panel.reset()
        self.assertFalse(automatic.isChecked())
        self.assertEqual(editor.value(), 10)
        self.assertFalse(reset.isEnabled())

    def test_integer_and_layer_values_commit_once_and_remain_in_bounds(self):
        self.panel.advanced_group.setChecked(True)
        layer = LayerNumberSpinBox()
        layer.setParent(self.panel)
        layer.setRange(1, 544)
        layer.setValue(544)
        layer.show()
        try:
            for editor, text, expected in ((self.panel.wall_count_spin, "20", 3),
                    (layer, "12", 12), (layer, "9999", 544), (layer, "0", 1)):
                with self.subTest(editor=type(editor).__name__, text=text):
                    old = editor.value()
                    self.draft(editor, text)
                    self.assertEqual(editor.lineEdit().text(), text)
                    self.assertEqual(editor.value(), old)
                    QTest.keyClick(editor, Qt.Key.Key_Return)
                    self.assertEqual(editor.value(), expected)
        finally:
            dispose_test_widget(layer)


if __name__ == "__main__":
    unittest.main()
