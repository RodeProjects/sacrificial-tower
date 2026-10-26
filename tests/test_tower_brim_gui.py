"""Tower-brim input ranges, independent automation and reset behavior."""
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from cooling_tower.gui.preprocessor_controls import PreprocessorPanel
from gui_lifecycle import dispose_test_widget


class TowerBrimGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.panel = PreprocessorPanel()
        self.panel.footer_widget.setParent(self.panel)
        self.panel.resize(1400, 1000)
        self.panel.show()
        self.app.processEvents()

    def tearDown(self):
        dispose_test_widget(self.panel)

    def test_default_width_is_point_two_mm_independent_of_model_brim(self):
        panel = self.panel
        panel.set_profile_values({"brim_type": "none", "brim_width": 19, "brim_object_gap": .35})
        for field, expected in (("tower_brim_width_mm", .2), ("tower_brim_gap_mm", .35)):
            self.assertFalse(panel.inputs[field].isEnabled())
            self.assertAlmostEqual(panel.inputs[field].value(), expected)
        self.assertEqual(panel.rows["tower_brim_width_mm"].label.text(), "Turm-Brim Breite")
        self.assertEqual(panel.rows["tower_brim_gap_mm"].label.text(), "Turm-Brim Abstand")
        panel.automatic["automatic_tower_brim_width"].setChecked(False)
        panel.inputs["tower_brim_width_mm"].setValue(0)
        self.assertEqual(panel.settings().tower_brim_width_mm, 0)
        self.assertTrue(panel.automatic["automatic_tower_brim_gap"].isChecked())
        panel.automatic["automatic_tower_brim_width"].setChecked(True)
        self.assertEqual(panel.inputs["tower_brim_width_mm"].value(), .2)

    def test_manual_ranges_and_independent_resets(self):
        panel = self.panel
        self.assertEqual(panel.inputs["tower_brim_gap_mm"].singleStep(), .1)
        for flag, field, minimum, maximum, value in (
                ("automatic_tower_brim_width", "tower_brim_width_mm", 0, 20, 20),
                ("automatic_tower_brim_gap", "tower_brim_gap_mm", .1, 1, 1)):
            panel.automatic[flag].setChecked(False)
            self.assertTrue(panel.inputs[field].isEnabled())
            self.assertEqual((panel.inputs[field].minimum(), panel.inputs[field].maximum()), (minimum, maximum))
            panel.inputs[field].setValue(value)
            self.assertEqual(getattr(panel.settings(), field), value)
            self.assertTrue(panel.reset_buttons[field].isEnabled())
        panel.reset_field("tower_brim_width_mm")
        self.assertTrue(panel.settings().automatic_tower_brim_width)
        self.assertFalse(panel.settings().automatic_tower_brim_gap)
        self.assertEqual(panel.settings().tower_brim_gap_mm, 1)
        panel.reset()
        self.assertTrue(panel.settings().automatic_tower_brim_gap)
        self.assertEqual(panel.settings().tower_brim_width_mm, .2)

    def test_profile_zero_and_large_gap_are_visible_but_manual_values_stay_valid(self):
        panel = self.panel
        for gap, manual in ((0, .1), (2, 1)):
            panel.automatic["automatic_tower_brim_gap"].setChecked(True)
            panel.set_profile_values({"brim_separation": gap})
            self.assertEqual(panel.inputs["tower_brim_gap_mm"].lineEdit().text(), f"{gap},00")
            panel.automatic["automatic_tower_brim_gap"].setChecked(False)
            self.assertEqual(panel.settings().tower_brim_gap_mm, manual)

    def test_width_and_gap_stay_visible_when_calculated_geometry_is_cleared(self):
        panel = self.panel
        panel.set_profile_values({"brim_object_gap": .25})
        panel.show_automatic_values({"base_width_mm": 30, "tower_brim_width_mm": .2, "tower_brim_gap_mm": .25})
        panel.clear_automatic_values()
        self.assertEqual(panel.inputs["base_width_mm"].lineEdit().text(), "—")
        self.assertEqual(panel.inputs["tower_brim_width_mm"].lineEdit().text(), "0,20")
        self.assertEqual(panel.inputs["tower_brim_gap_mm"].lineEdit().text(), "0,25")


if __name__ == "__main__":
    unittest.main()
