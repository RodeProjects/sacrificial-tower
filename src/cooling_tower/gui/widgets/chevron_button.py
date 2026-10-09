"""Buttons with the shared filled disclosure triangle at the right edge."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QResizeEvent
from PySide6.QtWidgets import QLabel, QPushButton, QWidget
from cooling_tower.gui.widgets.disclosure_triangle import draw_disclosure_triangle


class _CenteredChevron(QLabel):
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        draw_disclosure_triangle(
            painter, self.rect(), opened=self.text() == "▲",
            colour=self.palette().color(self.foregroundRole()),
        )


class ChevronButton(QPushButton):
    """Expose the same centered up/down triangle as the section headers."""

    def __init__(self, caption: str, parent: QWidget | None = None) -> None:
        super().__init__(caption, parent)
        self.chevron_label = _CenteredChevron("▼", self)
        self.chevron_label.setObjectName("disclosureChevron")
        self.chevron_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.chevron_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )

    def set_opened(self, opened: bool) -> None:
        self.chevron_label.setText("▲" if opened else "▼")

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.chevron_label.setGeometry(self.width() - 31, 0, 24, self.height())
