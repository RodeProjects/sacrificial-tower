from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, QSize, QTimer, Qt
from PySide6.QtGui import QPainter, QPalette, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QSizePolicy, QWidget


ACTIVITY_FRAMES = ("◐", "◓", "◑", "◒")
ACTIVITY_FRAME_INTERVAL_MS = 140


class _ActivityIndicator(QLabel):
    """Paint circular activity frames without relying on font glyph geometry."""

    def __init__(self, text_label: QLabel) -> None:
        super().__init__()
        self._text_label = text_label
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        text_label.installEventFilter(self)

    def text_height(self) -> int:
        """Match the visible letters, including descenders, beside the circle."""
        return max(1, self._text_label.fontMetrics().tightBoundingRect(
            self._text_label.text() or "0 %"
        ).height())

    def sizeHint(self) -> QSize:  # noqa: N802
        side = self.text_height() + 4
        return QSize(side, side)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if event.type() in {QEvent.Type.FontChange, QEvent.Type.StyleChange}:
            self.updateGeometry()
            self.update()
        return super().eventFilter(watched, event)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        # Short progress bars must be able to shrink the indicator's height.
        return QSize(0, 0)

    def paintEvent(self, event) -> None:  # noqa: N802
        if self.text() not in ACTIVITY_FRAMES:
            super().paintEvent(event)
            return
        available = QRectF(self.contentsRect())
        outer_diameter = min(self.text_height(), min(available.width(), available.height()) - 4)
        if outer_diameter <= 0:
            return
        pen_width = max(1.0, outer_diameter / 12)
        diameter = outer_diameter - pen_width
        circle = QRectF(available.center().x() - diameter / 2,
                        available.center().y() - diameter / 2, diameter, diameter)
        color = self.palette().color(QPalette.ColorRole.WindowText)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        start_angle = 90 - ACTIVITY_FRAMES.index(self.text()) * 90
        painter.drawPie(circle, start_angle * 16, 180 * 16)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(color, pen_width))
        painter.drawEllipse(circle)
        painter.end()


class ActivityProgressBar(QProgressBar):
    """Keep progress text and a rotating semicircle together inside the bar."""

    def __init__(self, parent: QWidget | None = None, *, compact: bool = True) -> None:
        super().__init__(parent)
        self.setTextVisible(False)
        self._automatic_activity = True
        self._activity_frame_index = -1
        self._activity_timer = QTimer(self)
        self._activity_timer.setInterval(ACTIVITY_FRAME_INTERVAL_MS)
        self._activity_timer.timeout.connect(self._advance_activity_frame)

        self.overlay = QWidget(self)
        self.overlay.setObjectName("progressBarOverlay" if compact else "profileConfirmationProgressOverlay")
        self.overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        overlay_layout = QHBoxLayout(self.overlay)
        overlay_layout.setContentsMargins(8, 0, 8, 0)
        overlay_layout.setSpacing(6)
        overlay_layout.addStretch(1)
        self.text_label = QLabel()
        self.text_label.setObjectName("progressBarText" if compact else "profileConfirmationProgressText")
        self.text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.activity_label = _ActivityIndicator(self.text_label)
        self.activity_label.setObjectName("progressBarActivity" if compact else "profileConfirmationActivity")
        self.activity_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        overlay_layout.addWidget(self.text_label)
        overlay_layout.addWidget(self.activity_label)
        overlay_layout.addStretch(1)
        self.activity_label.hide()
        self.valueChanged.connect(self._progress_changed)
        self._sync_overlay_text()

    def setFormat(self, text: str) -> None:  # noqa: N802
        super().setFormat(text)
        self._sync_overlay_text()

    def resetFormat(self) -> None:  # noqa: N802
        super().resetFormat()
        self._sync_overlay_text()

    def setRange(self, minimum: int, maximum: int) -> None:  # noqa: N802
        super().setRange(minimum, maximum)
        self._progress_changed()

    def setMinimum(self, minimum: int) -> None:  # noqa: N802
        super().setMinimum(minimum)
        self._progress_changed()

    def setMaximum(self, maximum: int) -> None:  # noqa: N802
        super().setMaximum(maximum)
        self._progress_changed()

    def reset(self) -> None:
        super().reset()
        self._progress_changed()

    def set_automatic_activity(self, enabled: bool) -> None:
        """Allow an existing task controller to supply its own activity frames."""
        self._automatic_activity = enabled
        self._sync_activity()

    def set_activity_frame(self, frame: str) -> None:
        self.activity_label.setText(str(frame))
        self.activity_label.setVisible(bool(frame))
        self.activity_label.update()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.overlay.setGeometry(self.rect())

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.overlay.setGeometry(self.rect())
        self._sync_overlay_text()
        self._sync_activity()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._activity_timer.stop()
        self._activity_frame_index = -1
        self.set_activity_frame("")
        super().hideEvent(event)

    def _progress_changed(self, *_args) -> None:
        self._sync_overlay_text()
        self._sync_activity()

    def _sync_overlay_text(self) -> None:
        text = self.text()
        if self.minimum() == self.maximum():
            # Indeterminate bars can still carry a useful status message.
            text = self.format()
            if any(token in text for token in ("%p", "%v", "%m")):
                text = ""
        self.text_label.setText(text)
        self.text_label.setVisible(bool(text))
        self.activity_label.updateGeometry()
        self.activity_label.update()

    def _sync_activity(self) -> None:
        if not self._automatic_activity:
            self._activity_timer.stop()
            return
        running = self.isVisible() and (
            self.minimum() == self.maximum() or self.value() < self.maximum()
        )
        if running:
            if not self._activity_timer.isActive():
                self._activity_frame_index = -1
                self._advance_activity_frame()
                self._activity_timer.start()
        else:
            self._activity_timer.stop()
            self._activity_frame_index = -1
            self.set_activity_frame("")

    def _advance_activity_frame(self) -> None:
        self._activity_frame_index = (self._activity_frame_index + 1) % len(ACTIVITY_FRAMES)
        self.set_activity_frame(ACTIVITY_FRAMES[self._activity_frame_index])
