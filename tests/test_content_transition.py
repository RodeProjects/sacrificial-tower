from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from cooling_tower.gui.widgets.content_transition import ContentTransition
from gui_lifecycle import dispose_test_widget


class ContentTransitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = QWidget()
        layout = QVBoxLayout(self.window)
        self.outside = QPushButton("Outside")
        layout.addWidget(self.outside)
        self.stack = QStackedWidget()
        self.stack.setStyleSheet("QStackedWidget { background: #ffffff; }")
        layout.addWidget(self.stack)
        self.pages = []
        self.buttons = []
        self.edits = []
        for name, color in (("outgoing", "#d32f2f"), ("incoming", "#1e64c8")):
            page = QWidget()
            page.setObjectName(name)
            page.setStyleSheet(f"QWidget#{name} {{ background: {color}; }} "
                              f"QWidget#{name}:disabled {{ background: #777777; }}")
            controls = QVBoxLayout(page)
            controls.setContentsMargins(30,30,30,30)
            button = QPushButton("Change")
            edit = QLineEdit("Original")
            controls.addWidget(button)
            controls.addWidget(edit)
            self.pages.append(page)
            self.buttons.append(button)
            self.edits.append(edit)
            self.stack.addWidget(page)
        self.window.resize(400,300)
        self.window.show()
        self.app.processEvents()
        self.transition = ContentTransition(self.stack,duration_ms=10000,pause_ms=100)
        self.addCleanup(dispose_test_widget,self.window)
        self.addCleanup(self.transition.cancel)

    def color(self):
        return self.stack.grab().toImage().pixelColor(5,5).getRgb()[:3]

    def finish_outgoing(self):
        animation = self.transition._animation
        animation.setCurrentTime(animation.duration())

    def finish_pause(self):
        pause = self.transition._animation
        pause.setCurrentTime(pause.duration())

    def test_both_fades_preserve_colours_and_only_interpolate_opacity(self) -> None:
        self.assertEqual(self.color(),(211,47,47))
        self.transition.run(lambda: self.stack.setCurrentIndex(1))
        self.assertTrue(self.stack.isEnabled())
        self.assertTrue(self.transition._overlay.isEnabled())
        self.assertEqual(self.color(),(211,47,47))
        self.transition._animation.setCurrentTime(2500)
        # InOutCubic has opacity 0.5 halfway through each fade. Every RGB
        # channel must blend the unchanged colour onto the white background.
        for actual,source in zip(self.color(),(211,47,47)):
            self.assertAlmostEqual(actual,(source+255)/2,delta=2)
        self.finish_outgoing()
        self.assertEqual(self.color(),(255,255,255))
        self.assertEqual(self.stack.currentIndex(),0)
        self.finish_pause()
        self.assertEqual(self.stack.currentIndex(),1)
        self.assertTrue(self.pages[1].isEnabled())
        self.transition._animation.setCurrentTime(2500)
        for actual,source in zip(self.color(),(30,100,200)):
            self.assertAlmostEqual(actual,(source+255)/2,delta=2)
        self.transition._animation.setCurrentTime(5000)
        self.assertEqual(self.color(),(30,100,200))
        self.assertFalse(self.transition._input_blocked)

    def test_input_is_blocked_during_fades_and_pause_but_other_content_stays_usable(self) -> None:
        clicks = [Mock(),Mock()]
        for button,clicked in zip(self.buttons,clicks):
            button.clicked.connect(clicked)
        outside_clicked = Mock()
        self.outside.clicked.connect(outside_clicked)
        self.edits[0].setFocus()
        self.transition.run(lambda: self.stack.setCurrentIndex(1))
        for stage,index in (("out",0),("pause",0),("in",1)):
            with self.subTest(stage=stage):
                self.edits[index].setFocus()
                QTest.keyClicks(self.edits[index],"Changed")
                QTest.mouseClick(self.buttons[index],Qt.MouseButton.LeftButton)
                self.assertEqual(self.edits[index].text(),"Original")
                clicks[index].assert_not_called()
                QTest.mouseClick(self.outside,Qt.MouseButton.LeftButton)
            if stage == "out":
                self.finish_outgoing()
            elif stage == "pause":
                self.finish_pause()
        self.assertEqual(outside_clicked.call_count,3)
        self.transition._animation.setCurrentTime(5000)
        QTest.keyClicks(self.edits[1],"Changed")
        QTest.mouseClick(self.buttons[1],Qt.MouseButton.LeftButton)
        self.assertIn("Changed",self.edits[1].text())
        clicks[1].assert_called_once()

    def test_cancel_restores_input_and_removes_effects_in_every_phase(self) -> None:
        for stage in ("out","pause","in"):
            with self.subTest(stage=stage):
                self.stack.setCurrentIndex(0)
                change = Mock(side_effect=lambda: self.stack.setCurrentIndex(1))
                self.transition.run(change)
                if stage in {"pause","in"}:
                    self.finish_outgoing()
                if stage == "in":
                    self.finish_pause()
                self.transition.cancel()
                self.assertIsNone(self.transition._animation)
                self.assertIsNone(self.transition._overlay)
                self.assertFalse(self.transition._input_blocked)
                self.assertTrue(all(page.graphicsEffect() is None for page in self.pages))
                clicked = Mock()
                button = self.buttons[self.stack.currentIndex()]
                button.clicked.connect(clicked)
                QTest.mouseClick(button,Qt.MouseButton.LeftButton)
                button.clicked.disconnect(clicked)
                clicked.assert_called_once()
                self.assertEqual(change.call_count,int(stage == "in"))
        self.stack.setEnabled(False)
        self.transition.run(lambda: self.stack.setCurrentIndex(1))
        self.transition.cancel()
        self.assertFalse(self.stack.isEnabled())


if __name__ == "__main__":
    unittest.main()
