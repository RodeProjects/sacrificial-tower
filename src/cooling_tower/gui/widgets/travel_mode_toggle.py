"""Animated choice between cumulative and single-layer preview routes."""
from PySide6.QtCore import QEasingCurve, QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QSizePolicy


class TravelModeToggle(QAbstractButton):
    ANIMATION_DURATION_MS = 220

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("travelModeToggle")
        self.setText("Alle / Einzeln")
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumSize(160, 32)
        self.setAccessibleName("Fahrwege anzeigen: Alle oder Einzeln")
        self.setToolTip("Alle: Fahrwege bis zum gewählten Layer.\n"
            "Einzeln: Fahrwege nur für den gewählten Layer.")
        self._show_keyboard_focus = False
        self._position = 1.0
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(self.ANIMATION_DURATION_MS)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._animation.valueChanged.connect(self._set_position)
        self.toggled.connect(self._mode_changed)
        self._mode_changed(False)

    def sizeHint(self):
        return QSize(max(160, 2*self.fontMetrics().horizontalAdvance("Einzeln")+48), 32)

    def _set_position(self, position):
        self._position = float(position)
        self.update()

    def _mode_changed(self, all_layers):
        self.setAccessibleDescription("Alle Fahrwege bis zum gewählten Layer" if all_layers
            else "Fahrwege nur für den gewählten Layer")
        self._animation.stop()
        target = 0.0 if all_layers else 1.0
        if not self.isVisible():
            self._set_position(target)
            return
        self._animation.setStartValue(self._position)
        self._animation.setEndValue(target)
        self._animation.start()

    def hideEvent(self, event):  # noqa: N802
        self._animation.stop()
        self._set_position(0.0 if self.isChecked() else 1.0)
        super().hideEvent(event)

    def keyPressEvent(self, event):  # noqa: N802
        self._show_keyboard_focus = True
        self.update()
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Home, Qt.Key.Key_End):
            self.setChecked(event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Home))
            event.accept()
        else:
            super().keyPressEvent(event)

    def focusInEvent(self, event):  # noqa: N802
        self._show_keyboard_focus = event.reason() != Qt.FocusReason.MouseFocusReason
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event):  # noqa: N802
        self._show_keyboard_focus = False
        super().focusOutEvent(event)
        self.update()

    def mousePressEvent(self, event):  # noqa: N802
        self._show_keyboard_focus = False
        self.update()
        super().mousePressEvent(event)

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(.45)
        track = QRectF(self.rect())
        painter.fillRect(track, QColor("#243344"))
        inside = track.adjusted(3, 3, -3, -3)
        half = inside.width()/2
        thumb = QRectF(inside.left()+self._position*half, inside.top(), half, inside.height())
        path = QPainterPath()
        path.addRect(thumb)
        painter.fillPath(path, QColor("#1d4c35" if self.isDown() else "#244436"))
        labels = ((QRectF(inside.left(), inside.top(), half, inside.height()), "Alle"),
            (QRectF(inside.left()+half, inside.top(), half, inside.height()), "Einzeln"))
        painter.setPen(QColor("#a7b9c8"))
        for rect, text in labels:
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.setClipPath(path)
        painter.setPen(QColor("#dbe8f2"))
        for rect, text in labels:
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        if self.hasFocus() and self._show_keyboard_focus:
            painter.setClipping(False)
            painter.setPen(QPen(QColor("#7ba98e"), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(track.adjusted(.5, .5, -.5, -.5))
