from pathlib import Path
import sys
from threading import Event, Thread
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtGui import QPainterPath
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtSvgWidgets import QSvgWidget
from cooling_tower.gui.widgets.preview_busy_overlay import PreviewBusyOverlay


class NativeBusyAnimationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.root = QWidget()
        self.root.resize(650, 450)
        self.canvas = QWidget(self.root)
        self.canvas.setGeometry(10, 10, 620, 420)
        self.canvas.setStyleSheet("background: #242a32;")
        self.overlay = PreviewBusyOverlay(self.canvas)
        self.root.show()
        self.app.processEvents()

    def tearDown(self):
        self.overlay.set_busy(False)
        self.root.close()
        self.root.deleteLater()
        self.app.processEvents()

    def test_native_frames_continue_under_cpu_load_and_stop_when_hidden(self):
        overlay = self.overlay
        path = QPainterPath()
        path.addRect(150, 80, 300, 260)
        overlay.set_busy(True, subdued=True, protected_region=lambda: path)
        renderer = overlay.surface.renderer()
        self.assertIs(type(overlay.surface), QSvgWidget)
        self.assertTrue(renderer.animated())
        self.assertEqual(renderer.framesPerSecond(), 60)
        frames = QSignalSpy(renderer.repaintNeeded)
        stop = Event()
        def calculate():
            value = 0
            while not stop.is_set():
                value = (value+1) % 1000003
        worker = Thread(target=calculate)
        first = overlay.surface.grab().toImage()
        worker.start()
        try:
            QTest.qWait(600)
        finally:
            stop.set()
            worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertGreaterEqual(frames.count(), 15)
        self.assertNotEqual(first, overlay.surface.grab().toImage())
        self.root.hide()
        self.app.processEvents()
        self.assertFalse(renderer.isAnimationEnabled())

    def test_progress_changes_never_reload_or_restart_the_animation(self):
        overlay = self.overlay
        with patch.object(overlay.surface, "load", wraps=overlay.surface.load) as loaded:
            overlay.set_busy(True, percent=1, step="Modell lesen")
            started = overlay._clock.msecsSinceReference()
            for percent in (12, 30, 55, 80):
                overlay.set_busy(True, percent=percent, step="Fahrwege prüfen")
            self.assertEqual(loaded.call_count, 1)
            self.assertEqual(overlay._clock.msecsSinceReference(), started)
            self.assertEqual(overlay.progress.value(), 80)
        overlay.set_busy(False)
        self.assertFalse(overlay.surface.renderer().isAnimationEnabled())


if __name__ == "__main__":
    unittest.main()
