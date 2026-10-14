from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QWidget


class HeaderUpdateControls(QWidget):
    """A compact update strip whose cancel action shares the available width."""

    HEIGHT = 26

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("headerUpdateControls")
        self.setFixedHeight(self.HEIGHT)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.button = QPushButton("Aktualisieren")
        self.button.setObjectName("updateButton")
        self.button.setAccessibleName("Programm aktualisieren")
        self.button.setToolTip("Die neueste Programmversion herunterladen und installieren")
        self.button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.cancel_button = QPushButton()
        self.cancel_button.setObjectName("updateCancelButton")
        self.cancel_button.setAccessibleName("Aktualisierung abbrechen")
        self.cancel_button.setToolTip("Download abbrechen")
        self.cancel_button.setIcon(QIcon(str(Path(__file__).parents[1] / "assets/update_cancel.svg")))
        self.cancel_button.setIconSize(QSize(16, 16))
        for button in (self.button, self.cancel_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedHeight(self.HEIGHT)
            layout.addWidget(button)
        self.cancel_button.setFixedWidth(self.HEIGHT)
        self.cancel_button.hide()
        self.button.hide()
        self.hide()

    def preferred_width(self) -> int:
        for button in (self.button, self.cancel_button):
            button.ensurePolished()
            button.setFixedHeight(self.HEIGHT)
        self.cancel_button.setFixedWidth(self.HEIGHT)
        # Reserve the complete download pair from the outset. Progress changes
        # and revealing the X then leave the method selector in the same place.
        text_width = self.button.fontMetrics().horizontalAdvance("Lädt... 100%")
        return max(
            self.button.sizeHint().width() + self.cancel_width(),
            text_width + 18 + self.HEIGHT,
        )

    def cancel_width(self) -> int:
        return 0 if self.cancel_button.isHidden() else self.HEIGHT
