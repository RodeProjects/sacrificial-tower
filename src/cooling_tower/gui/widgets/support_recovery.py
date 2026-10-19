"""Actionable first-layer advice, separate from untrusted plain error text."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class SupportRecoveryHint(QWidget):
    activate_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.label = QLabel(
            'Bei fehlender oder zu kleiner Auflagefläche in der ersten Schicht '
            'aktivieren Sie <b>Stützen für STL-Objekt simulieren</b> '
            'und starten Sie die Generierung erneut.'
        )
        self.label.setTextFormat(Qt.TextFormat.RichText)
        self.label.setWordWrap(True)
        self.button = QPushButton("Funktion jetzt aktivieren")
        self.button.clicked.connect(self.activate_requested)
        layout.addWidget(self.label, 1)
        layout.addWidget(
            self.button,
            0,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        self.hide()

    def refresh(self, message: str, *, available: bool, checked: bool, busy: bool):
        text = message.casefold()
        first_layer = any(marker in text for marker in (
            "erste schicht", "ersten schicht", "auflagefläche", "first layer", "initial layer",
        ))
        self.setVisible(available and not checked and first_layer)
        self.button.setEnabled(not busy)
