from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics, QWheelEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QSpinBox,
)


class WheelSafeComboBox(QComboBox):
    """Ignore wheel changes while closed; an open popup still scrolls normally."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setMaxVisibleItems(10)
        self.view().setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.view().setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerItem
        )

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        # The popup has its own viewport and therefore keeps its regular wheel
        # scrolling. A wheel event reaching the combo itself must never
        # silently select another item.
        event.ignore()

    def showPopup(self) -> None:  # noqa: N802
        """Give long entries enough popup width without leaving the window."""

        metrics = QFontMetrics(self.font())
        content_width = max(
            (metrics.horizontalAdvance(self.itemText(index)) for index in range(self.count())),
            default=self.width(),
        ) + 48
        owner = self.window()
        maximum = max(self.width(), owner.width() - 24)
        self.view().setMinimumWidth(max(self.width(), min(content_width, maximum)))
        super().showPopup()


class WheelSafeSpinBox(QSpinBox):
    """Keep numeric values stable when the surrounding form is scrolled."""

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        event.ignore()


class WheelSafeDoubleSpinBox(QDoubleSpinBox):
    """Keep decimal values stable when the surrounding form is scrolled."""

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        event.ignore()
