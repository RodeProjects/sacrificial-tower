import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QAbstractAnimation
from PySide6.QtWidgets import QApplication
from cooling_tower.gui.widgets.animated_generation_title import AnimatedGenerationTitle
from gui_lifecycle import dispose_test_widget


class AnimatedGenerationTitleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_left_to_right_fade_then_three_individual_dots(self):
        title = AnimatedGenerationTitle
        body_length = len(title.BODY)
        initial = title.character_opacities(0)
        self.assertEqual(initial[:body_length], (0.0,) * body_length)
        halfway = title.character_opacities(125)
        self.assertEqual(halfway[0], 1)
        self.assertEqual(halfway[body_length - 1], 0)
        self.assertTrue(all(left >= right for left, right in zip(halfway[:body_length - 1],
                                                               halfway[1:body_length])))
        self.assertEqual(title.character_opacities(250)[:body_length], (1.0,) * body_length)
        self.assertEqual(title.character_opacities(250)[-3:], (0.0,) * 3)
        for index in range(3):
            values = title.character_opacities(250 + (index + .5) * 500)[-3:]
            self.assertEqual(values[:index], (1.0,) * index)
            self.assertAlmostEqual(values[index], .5)
            self.assertEqual(values[index + 1:], (0.0,) * (2 - index))

    def test_hold_then_left_to_right_fade_out_without_a_pause(self):
        title = AnimatedGenerationTitle
        for elapsed in (1750, 1875, 2000):
            self.assertTrue(all(abs(value - 1) < 1e-9 for value in title.character_opacities(elapsed)))
        for elapsed in (2062.5, 2125, 2187.5):
            values = title.character_opacities(elapsed)
            self.assertEqual(values[0], 0)
            self.assertEqual(values[-1], 1)
            self.assertTrue(all(left <= right for left, right in zip(values, values[1:])))
            self.assertTrue(any(0 < value < 1 for value in values))
        for elapsed in (title.FADE_END_MS, title.CYCLE_MS):
            self.assertEqual(title.character_opacities(elapsed), (0.0,) * len(title.RUNNING_TEXT))
        self.assertEqual(title.CYCLE_MS, 250 + 3 * 500 + 250 + 250)

    def test_cycle_restarts_immediately_after_the_last_dot_fades_out(self):
        title = AnimatedGenerationTitle()
        self.addCleanup(dispose_test_widget, title)
        title.show()
        title.start_generating()
        title._cycle.pause()
        self.assertEqual(title._cycle.duration(), 2250)
        title._cycle.setCurrentTime(2250)
        self.assertEqual(title._cycle.currentLoop(), 1)
        self.assertEqual(title._elapsed_ms, 0)
        title._cycle.setCurrentTime(2250 + 125)
        self.assertEqual(title._elapsed_ms, 125)
        values = title.character_opacities(title._elapsed_ms)
        self.assertEqual(values[0], 1)
        self.assertEqual(values[len(title.BODY) - 1], 0)

    def test_animation_only_runs_while_generating_and_visible(self):
        title = AnimatedGenerationTitle()
        self.addCleanup(dispose_test_widget, title)
        title.start_generating()
        self.assertEqual(title._cycle.state(), QAbstractAnimation.State.Stopped)
        title.show()
        self.app.processEvents()
        self.assertEqual(title._cycle.state(), QAbstractAnimation.State.Running)
        title._cycle.setCurrentTime(1234)
        title.start_generating()
        self.assertEqual(title._cycle.currentTime(), 1234)
        title.hide()
        self.assertEqual(title._cycle.state(), QAbstractAnimation.State.Stopped)
        title.show()
        self.assertEqual(title._cycle.state(), QAbstractAnimation.State.Running)
        title.setText("Kühlturm fertig generiert")
        self.assertEqual(title._cycle.state(), QAbstractAnimation.State.Stopped)
        self.assertEqual(title.text(), "Kühlturm fertig generiert")
