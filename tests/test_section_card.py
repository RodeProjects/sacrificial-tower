from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage, QPainter, QTransform
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from cooling_tower.gui.widgets import SectionCard


class SectionCardTriangleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.card = SectionCard("Testbereich", collapsible=True)
        self.card.setStyleSheet(
            (PROJECT_ROOT / "src/cooling_tower/gui/styles.qss").read_text(encoding="utf-8")
        )
        self.card.resize(400, 150)
        self.card.show()
        self.app.processEvents()
        self.addCleanup(self.card.close)

    def triangle_image(self) -> QImage:
        button = self.card.toggle_button
        image = QImage(button.size(), QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        button.render(painter, QPoint(), renderFlags=QWidget.RenderFlag.DrawChildren)
        painter.end()
        return image

    def test_rotated_triangles_keep_identical_centred_bounds(self) -> None:
        button = self.card.toggle_button
        images = []
        for expanded in (False, True):
            self.card.setChecked(expanded)
            self.app.processEvents()
            image = self.triangle_image()
            pixels = [
                (x, y) for y in range(image.height()) for x in range(image.width())
                if image.pixelColor(x, y).alpha()
            ]
            self.assertTrue(pixels)
            self.assertEqual((image.width(), image.height()), (28, 28))
            xs, ys = zip(*pixels)
            self.assertEqual((min(xs), max(xs)), (8, 19))
            self.assertEqual((min(ys), max(ys)), (10, 17))
            self.assertLessEqual(
                abs(button.geometry().center().y() - self.card.header.rect().center().y()),
                1,
            )
            self.assertIn("einklappen" if expanded else "ausklappen", button.accessibleName())
            images.append(image)
        self.assertEqual(images[0].transformed(QTransform().rotate(180)), images[1])

    def test_hover_and_press_add_no_decoration_and_click_toggles_once(self) -> None:
        button = self.card.toggle_button
        idle = self.triangle_image()
        QTest.mouseMove(button, button.rect().center())
        self.app.processEvents()
        self.assertEqual(self.triangle_image(), idle)
        QTest.mousePress(button, Qt.MouseButton.LeftButton)
        self.assertEqual(self.triangle_image(), idle)
        QTest.mouseRelease(button, Qt.MouseButton.LeftButton)
        self.assertFalse(self.card.isChecked())
        self.assertTrue(self.card.content_widget.isHidden())
        QTest.keyClick(self.card.header, Qt.Key.Key_Space)
        self.assertTrue(self.card.isChecked())
        self.assertFalse(self.card.content_widget.isHidden())


if __name__ == "__main__":
    unittest.main()
