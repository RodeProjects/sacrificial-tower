"""Buttons with an optically centered disclosure chevron at the right edge."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics, QPainter, QResizeEvent
from PySide6.QtWidgets import QLabel, QPushButton, QWidget


class _CenteredChevron(QLabel):
    def paintEvent(self, event) -> None:  # noqa: N802
        glyph = self.text()
        bounds = QFontMetrics(self.font()).tightBoundingRect(glyph)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(
            round((self.width() - bounds.width()) / 2 - bounds.left()),
            round((self.height() - bounds.height()) / 2 - bounds.top()),
            glyph,
        )


class ChevronButton(QPushButton):
    """Expose the same centered up/down glyph for collapsible controls."""

    def __init__(self, caption: str, parent: QWidget | None = None) -> None:
        super().__init__(caption, parent)
        self.chevron_label = _CenteredChevron("⌄", self)
        self.chevron_label.setObjectName("disclosureChevron")
        self.chevron_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.chevron_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )

    def set_opened(self, opened: bool) -> None:
        self.chevron_label.setText("⌃" if opened else "⌄")

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.chevron_label.setGeometry(self.width() - 31, 0, 24, self.height())
