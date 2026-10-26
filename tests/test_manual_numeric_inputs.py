"""Manual settings: compact widths, tolerant decimal input and visible bounds."""
import unittest
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QStyle,QStyleOptionSpinBox
import test_manual_gui as gui


class ManualNumericInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app,cls.font,cls.font_id=gui.preview_test_application()

    @classmethod
    def tearDownClass(cls):gui.restore_preview_test_application(cls.app,cls.font,cls.font_id)

    def setUp(self):
        gui.ManualGuiTests.setUp(self)
        self.panel.setStyleSheet((Path(__file__).resolve().parents[1]/"src/cooling_tower/gui/styles.qss").read_text(encoding="utf-8"))
        self.app.processEvents()

    def enter(self,spin,text):
        spin.setFocus();spin.selectAll();QTest.keyClicks(spin,text)
        QTest.keyClick(spin,Qt.Key.Key_Return);self.app.processEvents()

    def test_segments_clamp_typed_values_and_report_both_boundaries(self):
        p=self.panel;spin=p.editors["circle_segments"];row=p.rows["circle_segments"]
        self.enter(spin,"999")
        self.assertEqual(p.settings.circle_segments,256)
        self.assertEqual(spin.value(),256)
        self.assertEqual(row.message_label.text(),"Max. Segmente = 256")
        self.assertTrue(row.message_label.isVisible())
        row._feedback_animation.setCurrentTime(1999)
        self.assertTrue(row.message_label.isVisible())
        self.enter(spin,"2")
        self.assertEqual(p.settings.circle_segments,12)
        self.assertEqual(row.message_label.text(),"Min. Segmente = 12")
        self.enter(spin,"64")
        self.assertEqual(p.settings.circle_segments,64)
        self.assertFalse(row.message_label.isVisible())

    def test_mouse_arrows_report_attempts_even_when_already_at_a_bound(self):
        spin=self.panel.editors["circle_segments"];row=self.panel.rows["circle_segments"]
        for maximum,control in ((True,QStyle.SubControl.SC_SpinBoxUp),(False,QStyle.SubControl.SC_SpinBoxDown)):
            spin.setValue(spin.maximum() if maximum else spin.minimum())
            option=QStyleOptionSpinBox();spin.initStyleOption(option)
            rect=spin.style().subControlRect(QStyle.ComplexControl.CC_SpinBox,option,control,spin)
            QTest.mouseClick(spin,Qt.MouseButton.LeftButton,pos=rect.center());self.app.processEvents()
            self.assertTrue(row.message_label.isVisible())
            self.assertIn("Max." if maximum else "Min.",row.message_label.text())
            row._feedback_animation.setCurrentTime(row._feedback_animation.duration())
            self.assertFalse(row.message_label.isVisible())

    def test_invalid_letters_and_fractional_segments_have_explanations(self):
        spin=self.panel.editors["circle_segments"];row=self.panel.rows["circle_segments"]
        previous=self.panel.settings.circle_segments
        spin.setFocus();spin.selectAll();QTest.keyClicks(spin,"abc");self.app.processEvents()
        self.assertTrue(row.message_label.isVisible())
        self.assertIn("gültige Zahl",row.message_label.text())
        self.assertEqual(self.panel.settings.circle_segments,previous)
        self.enter(spin,"30,5")
        self.assertIn("ganze Zahl",row.message_label.text())
        self.assertEqual(self.panel.settings.circle_segments,previous)
        self.assertEqual(spin.value(),previous)

    def test_dots_and_commas_produce_the_same_number_and_comma_display(self):
        self.panel.profile_angle_limit.checkbox.setChecked(False)
        spin=self.panel.editors["expansion_angle_deg"]
        for text in ("22.5","22,5"):
            self.enter(spin,text)
            self.assertEqual(self.panel.settings.expansion_angle_deg,67.5)
            self.assertIn("22,50",spin.text())
            self.assertNotIn(".",spin.text())

    def test_pasted_invalid_text_reports_error_and_valid_paste_clears_it(self):
        self.panel.profile_angle_limit.checkbox.setChecked(False)
        spin=self.panel.editors["expansion_angle_deg"]
        row=self.panel.rows["expansion_angle_deg"]
        spin.setFocus();spin.selectAll()
        QApplication.clipboard().setText("abc")
        QTest.keyClick(spin,Qt.Key.Key_V,Qt.KeyboardModifier.ControlModifier);self.app.processEvents()
        self.assertTrue(row.message_label.isVisible())
        QApplication.clipboard().setText("25.25")
        QTest.keyClick(spin,Qt.Key.Key_V,Qt.KeyboardModifier.ControlModifier)
        QTest.keyClick(spin,Qt.Key.Key_Return);self.app.processEvents()
        self.assertEqual(spin.value(),25.25)
        self.assertFalse(row.message_label.isVisible())

    def test_reset_to_valid_value_clears_the_corresponding_notice(self):
        p=self.panel;row=p.rows["circle_segments"]
        self.enter(row.editor,"999")
        row.reset_button.click()
        self.assertFalse(row.message_label.isVisible())

    def test_arrow_attempt_at_curve_geometry_limit_keeps_its_new_notice(self):
        p=self.panel;p.select("control:0:2")
        spin=p.editors["control_height_mm"]
        spin.setValue(1000)
        spin.stepUp();self.app.processEvents()
        self.assertTrue(p.rows["control_height_mm"].message_label.isVisible())
        self.assertLess(spin.value(),1000)

    def test_all_left_inputs_share_a_measured_width_with_room_for_suffixes(self):
        from cooling_tower.gui.widgets.manual_inputs import compact_manual_width
        p=self.panel
        spins=tuple(p.editors.values())
        widths={spin.width() for spin in spins}
        self.assertEqual(len(widths),1)
        self.assertLess(next(iter(widths)),150)
        self.assertEqual(next(iter(widths)),compact_manual_width(spins))
        for spin in spins:
            self.assertLess(spin.lineEdit().fontMetrics().horizontalAdvance(spin.text()),spin.lineEdit().width())

    def test_scale_is_compact_and_clamps_to_three_with_ordered_color_boundaries(self):
        p=self.panel;p.color_enabled_checkbox.click();self.app.processEvents()
        self.assertLess(p.color_scale_spin.width(),p.editors["circle_segments"].width())
        self.enter(p.color_scale_spin,"2")
        self.assertEqual(p.settings.color_scale_max_time_s,3)
        self.assertEqual((p.settings.color_red_time_s,p.settings.color_reference_time_s),(3,3))
        self.assertTrue(p.layer_time_controls.notice_label.isVisible())


if __name__=="__main__":unittest.main()
