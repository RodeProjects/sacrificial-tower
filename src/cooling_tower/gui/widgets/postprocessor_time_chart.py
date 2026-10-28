"""Vertical layer timing plot with an integrated, keyboard-accessible scrubber."""
from __future__ import annotations

import math
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget


class PostprocessorTimeChart(QWidget):
    layer_selected = Signal(int)
    drag_finished = Signal(int)
    COLORS = ("#53a9b8", "#ec963e", "#9b7fd5")
    TARGET_COLOR = "#2a754e"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(0, 160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setToolTipDuration(2200)
        self.setAccessibleName("Layerachse: Greifer ziehen oder Layer mit Auf/Ab auswählen")
        self.original, self.motion, self.waits, self.heights = (), (), (), ()
        self.target, self.selected = 0, 1
        self.logarithmic = True
        self.normalized = False
        self._totals = ()
        self._maximum = 1
        self._dragging = False
        self._frame = self._frame_key = None

    def set_data(self, original=(), motion=(), waits=(), heights=(), target=0):
        if not (len(original) == len(motion) == len(waits) == len(heights)):
            raise ValueError("Schichtzeiten und Höhen müssen dieselbe Länge besitzen.")
        if any(not math.isfinite(v) for seq in (original, motion, waits, heights) for v in seq):
            raise ValueError("Schichtdaten müssen endlich sein.")
        self.original, self.motion, self.waits, self.heights = map(tuple, (original, motion, waits, heights))
        self.target, self.selected = target, 1
        self._totals = tuple(sum(self._parts(i)) for i in range(len(original)))
        self.normalized = self.default_normalization()
        self._update_time_scale()
        self.setEnabled(bool(original))

    def default_normalization(self):
        return len(self._totals) > 1 and self._totals[0] > max(self._totals[1:])

    def set_normalized(self, enabled):
        self.normalized = bool(enabled)
        self._update_time_scale()

    def _update_time_scale(self):
        self.setToolTip("")
        visible_times = self._totals[1:] if self.normalized else self._totals
        self._maximum = max(1, max(visible_times, default=0), self.target)*1.05
        self._frame_key = None
        self.update()

    def set_logarithmic(self, enabled):
        self.logarithmic = bool(enabled)
        self.setToolTip("")
        self._frame_key = None
        self.update()

    def plot_rect(self):
        return QRectF(12, 28, max(1, self.width()-90), max(1, self.height()-60))

    def layer_y(self, layer):
        rect = self.plot_rect()
        return rect.bottom()-(layer-.5)/max(1, len(self.original))*rect.height()

    def layer_at(self, y):
        rect = self.plot_rect()
        fraction = (rect.bottom()-y)/rect.height()
        return 1+min(len(self.original)-1, max(0, int(fraction*len(self.original))))

    def time_fraction(self, seconds):
        return (math.log1p(max(0, seconds))/math.log1p(self._maximum) if self.logarithmic
            else max(0, seconds)/self._maximum)

    def target_marker(self):
        rect = self.plot_rect()
        x, y = rect.left()+self.time_fraction(self.target)*rect.width(), rect.bottom()+1
        path = QPainterPath(QPointF(x, y))
        path.lineTo(x-4, y+7)
        path.lineTo(x+4, y+7)
        path.closeSubpath()
        return path

    def _parts(self, index):
        return tuple(max(0, seq[index]) for seq in (self.original, self.motion, self.waits))

    def select_layer(self, layer):
        if self.original:
            self.selected = max(1, min(len(self.original), int(layer)))
            self.update()

    def _choose(self, y, *, force=False):
        selected = self.layer_at(y)
        if force or selected != self.selected:
            self.select_layer(selected)
            self.layer_selected.emit(self.selected)

    def mousePressEvent(self, event):  # noqa: N802
        if (event.button() == Qt.MouseButton.LeftButton and self.original
                and not self.target_marker().boundingRect().adjusted(-3, -2, 3, 2).contains(event.position())):
            self._dragging = True
            self.setToolTip("")
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self._choose(event.position().y(), force=True)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        if not self.original:
            return super().mouseMoveEvent(event)
        if self._dragging:
            self._choose(event.position().y())
            event.accept()
            return
        marker_hover = self.target_marker().boundingRect().adjusted(-3, -2, 3, 2).contains(event.position())
        self.setToolTip(f"Eingestellte Mindest-Layerzeit: {self.target:.2f} s" if marker_hover else "")
        self.setCursor(Qt.CursorShape.ArrowCursor if marker_hover else Qt.CursorShape.OpenHandCursor
            if abs(event.position().x()-self.plot_rect().right()) < 18 else Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            self._choose(event.position().y())
            self._dragging = False
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self.drag_finished.emit(self.selected)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):  # noqa: N802
        keys = (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Home, Qt.Key.Key_End)
        if event.key() in keys and self.original:
            layer = (1 if event.key() == Qt.Key.Key_Home else len(self.original) if event.key() == Qt.Key.Key_End
                else self.selected+(1 if event.key() == Qt.Key.Key_Up else -1))
            self.select_layer(layer)
            self.layer_selected.emit(self.selected)
            event.accept()
        else:
            super().keyPressEvent(event)

    def _draw_bars(self, painter, index, y, height):
        if self.normalized and index == 0:
            return
        rect, previous, seconds = self.plot_rect(), 0.0, 0.0
        if self.normalized:
            # A screen bin can contain layer 1 and later layers together.
            # Leave layer 1's band empty even in that aggregated overview.
            height = max(0, min(y+height, rect.bottom()-rect.height()/len(self.original))-y)
        for value, color in zip(self._parts(index), self.COLORS):
            seconds += value
            end = self.time_fraction(seconds)*rect.width()
            painter.fillRect(QRectF(rect.left()+previous, y, max(0, end-previous), height), QColor(color))
            previous = end

    def _paint_plot(self, painter):
        rect = self.plot_rect()
        painter.setPen(QColor("#526b7e"))
        painter.drawText(QRectF(rect.left(), 0, rect.width(), 24), Qt.AlignmentFlag.AlignCenter, "Zeit (s)")
        divisions = min(4, max(1, int(rect.width()/60)))
        for part in range(divisions+1):
            fraction = part/divisions
            x = rect.left()+rect.width()*fraction
            seconds = math.expm1(math.log1p(self._maximum)*fraction) if self.logarithmic else self._maximum*fraction
            painter.setPen(QColor("#dce4ec"))
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            painter.setPen(QColor("#526b7e"))
            text = f"{seconds:.1f}" if 0 < seconds < 10 else f"{seconds:.0f}"
            painter.drawText(QRectF(x-25, rect.bottom()+5, 50, 20), Qt.AlignmentFlag.AlignCenter, text)
        # Aggregate by screen row, preserving waits and large totals. The
        # selected layer is drawn exactly above this cached overview.
        bins = min(len(self.original), max(1, int(rect.height()/2)))
        height = rect.height()/bins
        for row in range(bins):
            lo, hi = row*len(self.original)//bins, (row+1)*len(self.original)//bins
            if self.normalized:
                lo = max(1, lo)
            if lo >= hi:
                continue
            index = max(range(lo, hi), key=lambda i: (self.waits[i], self._totals[i]))
            self._draw_bars(painter, index, rect.bottom()-(row+1)*height, max(1, height))
        painter.setPen(QPen(QColor(self.TARGET_COLOR), 1, Qt.PenStyle.DashLine))
        x = rect.left()+self.time_fraction(self.target)*rect.width()
        painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
        painter.setBrush(QColor(self.TARGET_COLOR))
        painter.setPen(QPen(QColor(self.TARGET_COLOR), 1))
        painter.drawPath(self.target_marker())
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#71859a"), 1))
        painter.drawLine(rect.topRight(), rect.bottomRight())
        count = len(self.original)
        for layer in sorted({1+round((count-1)*part/4) for part in range(5)}):
            y = self.layer_y(layer)
            painter.drawLine(QPointF(rect.right(), y), QPointF(rect.right()+4, y))
            painter.drawText(QRectF(rect.right()+16, y-10, 38, 20), Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter, str(layer))
        # Rotate only the axis name. Layer numbers remain horizontal.
        painter.save()
        painter.translate(self.width()-8, rect.center().y())
        painter.rotate(-90)
        painter.drawText(QRectF(-rect.height()/2, -14, rect.height(), 20), Qt.AlignmentFlag.AlignCenter, "Layer")
        painter.restore()

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#f7f9fc"))
        if not self.original:
            return
        key = (self.width(), self.height(), self.devicePixelRatioF(), self.font().key(), self.logarithmic, self.normalized,
            id(self.original), id(self.motion), id(self.waits), self.target)
        if self._frame_key != key:
            ratio = self.devicePixelRatioF()
            self._frame = QPixmap(round(self.width()*ratio), round(self.height()*ratio))
            self._frame.setDevicePixelRatio(ratio)
            self._frame.fill(QColor("#f7f9fc"))
            frame_painter = QPainter(self._frame)
            self._paint_plot(frame_painter)
            frame_painter.end()
            self._frame_key = key
        painter.drawPixmap(0, 0, self._frame)
        rect, y = self.plot_rect(), self.layer_y(self.selected)
        self._draw_bars(painter, self.selected-1, y-1, 2)
        painter.setPen(QPen(QColor("#246aa6"), 1))
        painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        handle = QPainterPath(QPointF(rect.right()-3, y))
        for x, dy in ((4, -7), (12, -7), (12, 7), (4, 7)):
            handle.lineTo(rect.right()+x, y+dy)
        handle.closeSubpath()
        painter.setBrush(QColor("#246aa6"))
        painter.drawPath(handle)
