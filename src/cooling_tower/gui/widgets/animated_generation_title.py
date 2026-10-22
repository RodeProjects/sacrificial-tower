"""Stable, wrapping generation title with a repeating text-and-dots fade."""
from PySide6.QtCore import QEasingCurve, QPointF, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPalette, QTextCharFormat, QTextLayout, QTextOption
from PySide6.QtWidgets import QLabel


class AnimatedGenerationTitle(QLabel):
    BODY = "Kühlturm wird generiert"
    RUNNING_TEXT = BODY + " ..."
    BODY_FADE_MS = 250
    DOT_FADE_MS = 500
    HOLD_MS = 250
    FADE_OUT_MS = 250
    FADE_START_MS = BODY_FADE_MS + 3 * DOT_FADE_MS + HOLD_MS
    FADE_END_MS = FADE_START_MS + FADE_OUT_MS
    CYCLE_MS = FADE_END_MS

    def __init__(self, parent=None):
        super().__init__(self.RUNNING_TEXT, parent)
        self.setWordWrap(True)
        self._generating = False
        self._elapsed_ms = 0.0
        self._cycle = QVariantAnimation(self)
        self._cycle.setDuration(round(self.CYCLE_MS))
        self._cycle.setStartValue(0.0)
        self._cycle.setEndValue(float(self.CYCLE_MS))
        self._cycle.setLoopCount(-1)
        self._cycle.setEasingCurve(QEasingCurve.Type.Linear)
        self._cycle.valueChanged.connect(self._set_elapsed)

    @classmethod
    def character_opacities(cls, elapsed_ms):
        body = cls._sweep_progress(elapsed_ms, cls.BODY_FADE_MS, len(cls.BODY))
        dots = [max(0.0, min(1.0, (elapsed_ms - cls.BODY_FADE_MS - index * cls.DOT_FADE_MS)
                                / cls.DOT_FADE_MS)) for index in range(3)]
        disappearing = cls._sweep_progress(elapsed_ms - cls.FADE_START_MS,
                                           cls.FADE_OUT_MS, len(cls.RUNNING_TEXT))
        return tuple(visible * (1 - hidden)
                     for visible, hidden in zip((*body, body[-1], *dots), disappearing))

    @staticmethod
    def _sweep_progress(elapsed_ms, duration_ms, characters):
        # Overlapping character fades keep both left-to-right sweeps fluid.
        character_fade = duration_ms * .18
        travel = duration_ms - character_fade
        return tuple(max(0.0, min(1.0, (elapsed_ms - index * travel / max(1, characters - 1))
                                      / character_fade)) for index in range(characters))

    def _set_elapsed(self, elapsed_ms):
        self._elapsed_ms = elapsed_ms
        self.update()

    def start_generating(self):
        if not self._generating:
            super().setText(self.RUNNING_TEXT)
            self._generating = True
        if self.isVisible() and self._cycle.state() != QVariantAnimation.State.Running:
            self._cycle.start()

    def setText(self, text):  # noqa: N802
        self._generating = False
        self._cycle.stop()
        super().setText(text)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if self._generating:
            self.start_generating()

    def hideEvent(self, event):  # noqa: N802
        self._cycle.stop()
        self._set_elapsed(0.0)
        super().hideEvent(event)

    def paintEvent(self, event):  # noqa: N802
        if not self._generating:
            return super().paintEvent(event)
        text_layout = QTextLayout(self.text(), self.font())
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        text_layout.setTextOption(option)
        formats = []
        for index, opacity in enumerate(self.character_opacities(self._elapsed_ms)):
            color = QColor(self.palette().color(QPalette.ColorRole.WindowText))
            color.setAlphaF(opacity)
            style = QTextCharFormat()
            style.setForeground(color)
            format_range = QTextLayout.FormatRange()
            format_range.start = index
            format_range.length = 1
            format_range.format = style
            formats.append(format_range)
        text_layout.setFormats(formats)
        rect = self.contentsRect()
        text_layout.beginLayout()
        height = 0.0
        while True:
            line = text_layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(max(1, rect.width()))
            line.setPosition(QPointF(0, height))
            height += line.height()
        text_layout.endLayout()
        painter = QPainter(self)
        painter.setClipRect(rect)
        text_layout.draw(painter, QPointF(rect.left(), rect.top() + (rect.height() - height) / 2))
