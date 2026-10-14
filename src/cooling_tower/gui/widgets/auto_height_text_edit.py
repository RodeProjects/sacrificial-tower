from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QSizePolicy, QTextEdit


class AutoHeightTextEdit(QTextEdit):
    """Read-only text block that grows with content up to a compact limit."""

    def __init__(
        self,
        parent=None,
        *,
        minimum_height: int = 24,
        maximum_height: int = 112,
    ) -> None:
        super().__init__(parent)
        self._minimum_content_height = minimum_height
        self._maximum_content_height = maximum_height
        self.setReadOnly(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.document().contentsChanged.connect(self.schedule_height_update)
        self.schedule_height_update()

    def schedule_height_update(self) -> None:
        QTimer.singleShot(0, self, self.fit_to_document)

    def fit_to_document(self) -> None:
        viewport_width = max(120, self.viewport().width())
        self.document().setTextWidth(viewport_width)
        frame = 2 * self.frameWidth()
        margins = self.contentsMargins()
        natural = int(self.document().size().height()) + frame
        natural += margins.top() + margins.bottom() + 2
        height = max(
            self._minimum_content_height,
            min(self._maximum_content_height, natural),
        )
        self.setFixedHeight(height)
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
            if natural > self._maximum_content_height
            else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.schedule_height_update()
