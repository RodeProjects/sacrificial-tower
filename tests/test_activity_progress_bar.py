from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFont, QImage, QRegion
from PySide6.QtWidgets import QApplication, QWidget

from cooling_tower.gui.widgets.activity_progress_bar import ACTIVITY_FRAMES, ActivityProgressBar


class ActivityProgressBarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.stylesheet = (ROOT / "src/cooling_tower/gui/styles.qss").read_text(encoding="utf-8")

    def assert_round_frame(self, indicator, scale):
        image = QImage(round(indicator.width() * scale), round(indicator.height() * scale),
                       QImage.Format.Format_ARGB32)
        image.setDevicePixelRatio(scale)
        image.fill(Qt.GlobalColor.transparent)
        indicator.render(image, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
        pixels = [(x, y) for y in range(image.height()) for x in range(image.width())
                  if image.pixelColor(x, y).alpha() > 32]
        self.assertTrue(pixels, "The activity frame must be visible")
        left = min(x for x, _ in pixels)
        right = max(x for x, _ in pixels)
        top = min(y for _, y in pixels)
        bottom = max(y for _, y in pixels)
        self.assertLessEqual(abs((right - left) - (bottom - top)), 1,
                             "The painted circle must have equal width and height")
        self.assertGreater(left, 0)
        self.assertGreater(top, 0)
        self.assertLess(right, image.width() - 1)
        self.assertLess(bottom, image.height() - 1)

    def test_all_progress_styles_render_round_unclipped_frames_at_multiple_scales(self):
        # Every use of the shared bar: source, slicer, main, isolated slice,
        # preview dialog, manual preview, and the larger profile confirmation.
        styles = ("sourceValidationProgressBar", "slicerDiscoveryProgressBar", "mainProgressBar",
                  "preparationProgressBar", "previewProgressBar", "", "profileConfirmationProgress")
        for name in styles:
            bar = ActivityProgressBar(compact=name != "profileConfirmationProgress")
            bar.setObjectName(name)
            bar.setStyleSheet(self.stylesheet)
            bar.set_automatic_activity(False)
            bar.setValue(17)
            bar.resize(500, bar.sizeHint().height())
            bar.show()
            try:
                for stretch in (50, 200):
                    font = QFont(bar.activity_label.font())
                    font.setStretch(stretch)
                    bar.activity_label.setFont(font)
                    for frame in ACTIVITY_FRAMES:
                        bar.set_activity_frame(frame)
                        self.app.processEvents()
                        for scale in (1.0, 1.25, 1.5, 2.0):
                            with self.subTest(bar=name, stretch=stretch, frame=frame, scale=scale):
                                self.assert_round_frame(bar.activity_label, scale)
            finally:
                bar.close()

    def test_short_indicator_shrinks_uniformly_instead_of_clipping(self):
        bar = ActivityProgressBar()
        indicator = bar.activity_label
        indicator.setFixedHeight(9)
        indicator.resize(20, 9)
        for frame in ACTIVITY_FRAMES:
            indicator.setText(frame)
            with self.subTest(frame=frame):
                self.assert_round_frame(indicator, 2.0)


if __name__ == "__main__":
    unittest.main()
