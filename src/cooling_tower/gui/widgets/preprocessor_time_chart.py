"""Dependency-free, keyboard-accessible layer timing inspection."""
from __future__ import annotations

import math
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class PreprocessorTimeChart(QWidget):
    layer_selected = Signal(int)
    COLORS = ("#53a9b8", "#ec963e", "#9b7fd5")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(0)
        self.setFixedHeight(200)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Schichtzeiten: Schicht mit Mausklick oder Pfeiltasten auswählen")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.original, self.motion, self.waits, self.heights = (), (), (), ()
        self.target = 0
        self.selected = 1

    def set_data(self, original=(), motion=(), waits=(), heights=(), target=0):
        if not (len(original) == len(motion) == len(waits) == len(heights)):
            raise ValueError("Schichtzeiten und Höhen müssen dieselbe Länge besitzen.")
        if any(not math.isfinite(v) for seq in (original, motion, waits, heights) for v in seq):
            raise ValueError("Schichtdaten müssen endlich sein.")
        self.original, self.motion, self.waits, self.heights = map(tuple, (original, motion, waits, heights))
        self.target, self.selected = target, 1
        self.setEnabled(bool(original))
        self.update()

    def plot_rect(self):
        return QRectF(46, 12, max(1, self.width() - 58), self.height() - 40)

    def select_layer(self, layer):
        if self.original:
            self.selected = max(1, min(len(self.original), int(layer)))
            self.update()

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.original:
            rect = self.plot_rect()
            fraction = (event.position().x() - rect.left()) / rect.width()
            self.select_layer(1 + min(len(self.original) - 1, max(0, int(fraction * len(self.original)))))
            self.layer_selected.emit(self.selected)
            event.accept()
        else:
            super().mousePressEvent(event)

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Home, Qt.Key.Key_End) and self.original:
            layer = (1 if event.key() == Qt.Key.Key_Home else len(self.original) if event.key() == Qt.Key.Key_End
                else self.selected + (1 if event.key() == Qt.Key.Key_Right else -1))
            self.select_layer(layer)
            self.layer_selected.emit(self.selected)
            event.accept()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#f7f9fc"))
        if not self.original:
            painter.setPen(QColor("#627486"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Schichtzeiten nach der Erzeugung verfügbar")
            return
        rect = self.plot_rect()
        maximum = max(self.target, *(max(0, a + b) + c for a, b, c in zip(self.original, self.motion, self.waits))) * 1.08 or 1
        painter.setPen(QColor("#cbd5df"))
        for part in range(5):
            y = rect.bottom() - rect.height() * part / 4
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            painter.setPen(QColor("#526b7e"))
            painter.drawText(QRectF(0, y - 9, 40, 18), Qt.AlignmentFlag.AlignRight, f"{maximum * part / 4:.0f} s")
            painter.setPen(QColor("#cbd5df"))
        # One aggregate per screen column keeps huge models responsive. The
        # representative with the greatest wait preserves critical deficits.
        bins = min(len(self.original), max(1, int(rect.width() / 2)))
        bar_width = rect.width() / bins
        for column in range(bins):
            lo, hi = column * len(self.original) // bins, (column + 1) * len(self.original) // bins
            index = max(range(lo, hi), key=lambda i: self.waits[i])
            bottom = rect.bottom()
            for value, color in zip((self.original[index], max(0, self.motion[index]), self.waits[index]), self.COLORS):
                height = max(0, value) / maximum * rect.height()
                painter.fillRect(QRectF(rect.left() + column * bar_width, bottom - height, max(1, bar_width), height), QColor(color))
                bottom -= height
        painter.setPen(QPen(QColor("#2a754e"), 1, Qt.PenStyle.DashLine))
        target_y = rect.bottom() - self.target / maximum * rect.height()
        painter.drawLine(QPointF(rect.left(), target_y), QPointF(rect.right(), target_y))
        x = rect.left() + (self.selected - .5) / len(self.original) * rect.width()
        painter.setPen(QPen(QColor("#1c405e"), 2))
        painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
        painter.drawText(QRectF(rect.left(), rect.bottom() + 5, rect.width(), 22), Qt.AlignmentFlag.AlignCenter,
            f"Schicht 1 bis {len(self.original)} · Auswahl {self.selected}")
