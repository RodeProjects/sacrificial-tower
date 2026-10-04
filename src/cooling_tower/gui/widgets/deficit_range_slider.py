from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from PySide6.QtCore import QPointF, QRectF, QSize, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QSlider, QSizePolicy, QWidget

from cooling_tower.gui.widgets.layer_range_canvas import LayerRangeCanvas


def round_deficit(value):
    return float(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


class _DeficitHandle(QSlider):
    """A native accessible slider, positioned on the shared gradient track."""

    def __init__(self, owner, *, lower):
        super().__init__(Qt.Orientation.Horizontal, owner)
        self.lower = lower
        self.setRange(0 if lower else 1, owner.MAXIMUM_TICKS - 1 if lower else owner.MAXIMUM_TICKS)
        self.setSingleStep(1)
        self.setPageStep(5)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Grün bis Defizit" if lower else "Rot ab Defizit")
        self._drag_offset = 0

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(LayerRangeCanvas.OBJECT_COLOR if self.lower else LayerRangeCanvas.CRITICAL_COLOR)
        painter.setPen(QPen(color, 2 if self.hasFocus() or self.isSliderDown() else 1))
        painter.setBrush(QColor("#ffffff"))
        points = [(1, 1), (15, 1), (15, 10), (8, 15), (1, 10)]
        if not self.lower:
            points = [(x, 16 - y) for x, y in points]
        painter.drawPolygon(QPolygonF([QPointF(x, y) for x, y in points]))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.position().x() - self.width() / 2
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.setSliderDown(True)
            event.accept()
        else:
            event.ignore()

    def mouseMoveEvent(self, event):
        if self.isSliderDown():
            x = self.parentWidget().mapFromGlobal(event.globalPosition().toPoint()).x()
            self.setValue(self.parentWidget().value_at(x - self._drag_offset))
            event.accept()
        else:
            event.ignore()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.isSliderDown():
            self.mouseMoveEvent(event)
            self.setSliderDown(False)
            self.update()
            event.accept()
        else:
            event.ignore()

    def wheelEvent(self, event):
        event.ignore()


class DeficitRangeSlider(QWidget):
    start_changed = Signal(float)
    full_changed = Signal(float)
    MAXIMUM_SECONDS = 2.0
    MAXIMUM_TICKS = int(MAXIMUM_SECONDS * 10)
    DEFAULT_FULL_SECONDS = 1.0
    HANDLE_WIDTH = 16

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(32)
        self.setAccessibleName("Defizit-Einfärbung von 0 bis 2 Sekunden")
        self.start_handle = _DeficitHandle(self, lower=True)
        self.full_handle = _DeficitHandle(self, lower=False)
        self.start_handle.valueChanged.connect(lambda value: self._handle_changed(True, value))
        self.full_handle.valueChanged.connect(lambda value: self._handle_changed(False, value))
        self._active_handle = None
        self.set_thresholds(0, self.DEFAULT_FULL_SECONDS)

    def sizeHint(self):
        return QSize(180, 32)

    def minimumSizeHint(self):
        return QSize(80, 32)

    def track_rect(self):
        return QRectF(self.HANDLE_WIDTH / 2, 12,
                      max(1, self.width() - self.HANDLE_WIDTH), 8)

    def x_for_value(self, value):
        track = self.track_rect()
        return track.left() + track.width() * value / self.MAXIMUM_TICKS

    def value_at(self, x):
        track = self.track_rect()
        seconds = (x - track.left()) * self.MAXIMUM_SECONDS / track.width()
        return max(0, min(self.MAXIMUM_TICKS, round(round_deficit(seconds) * 10)))

    def set_thresholds(self, start, full):
        with QSignalBlocker(self.start_handle), QSignalBlocker(self.full_handle):
            self.start_handle.setValue(round(round_deficit(start) * 10))
            self.full_handle.setValue(round(round_deficit(full) * 10))
        self._refresh_handles()

    def _handle_changed(self, lower, value):
        self._refresh_handles()
        (self.start_changed if lower else self.full_changed).emit(value / 10)

    def _refresh_handles(self):
        start_x = self.x_for_value(self.start_handle.value())
        full_x = self.x_for_value(self.full_handle.value())
        # Close bounds remain independently clickable using opposite sides
        # of the track, including the minimum 0.1 s gap.
        close = full_x - start_x < self.HANDLE_WIDTH
        for handle, x, y in ((self.start_handle, start_x, 0 if close else 4),
                             (self.full_handle, full_x, 16 if close else 12)):
            handle.setGeometry(round(x - self.HANDLE_WIDTH / 2), y, self.HANDLE_WIDTH, 16)
            number = f"{handle.value() / 10:.1f}".replace(".", ",")
            handle.setToolTip(f"{'Grün bis' if handle.lower else 'Rot ab'} {number} s Defizit")
            handle.setAccessibleDescription(handle.toolTip())
            handle.update()
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_handles()

    def paintEvent(self, event):
        painter = QPainter(self)
        track = self.track_rect()
        gradient = QLinearGradient(track.left(), 0, track.right(), 0)
        green, red = QColor(LayerRangeCanvas.OBJECT_COLOR), QColor(LayerRangeCanvas.CRITICAL_COLOR)
        start, full = self.start_handle.value() / self.MAXIMUM_TICKS, self.full_handle.value() / self.MAXIMUM_TICKS
        gradient.setColorAt(0, green)
        gradient.setColorAt(start, green)
        gradient.setColorAt(full, red)
        gradient.setColorAt(1, red)
        painter.fillRect(track, gradient)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            x = event.position().x()
            self._active_handle = min((self.start_handle, self.full_handle),
                key=lambda handle: abs(self.x_for_value(handle.value()) - x))
            self._active_handle.setFocus(Qt.FocusReason.MouseFocusReason)
            self._active_handle.setSliderDown(True)
            self._active_handle.setValue(self.value_at(x))
            event.accept()
        else:
            event.ignore()

    def mouseMoveEvent(self, event):
        if self._active_handle is not None:
            self._active_handle.setValue(self.value_at(event.position().x()))
            event.accept()
        else:
            event.ignore()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._active_handle is not None:
            self.mouseMoveEvent(event)
            self._active_handle.setSliderDown(False)
            self._active_handle.update()
            self._active_handle = None
            event.accept()
        else:
            event.ignore()
