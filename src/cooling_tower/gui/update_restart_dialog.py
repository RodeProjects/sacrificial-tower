from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QDialog, QMessageBox, QWidget


class UpdateRestartCountdownDialog(QMessageBox):
    """Show the verified-download countdown before handing off to Setup."""

    def __init__(self, parent: QWidget | None = None, *, seconds: int = 10) -> None:
        if seconds < 1:
            raise ValueError("Der Update-Neustart benötigt mindestens eine Sekunde.")
        super().__init__(parent)
        self.remaining_seconds = seconds
        self.setObjectName("updateRestartCountdownDialog")
        self.setWindowTitle("Sacrificial-Tower-Update")
        self.setIcon(QMessageBox.Icon.Information)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setStandardButtons(QMessageBox.StandardButton.NoButton)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        self.cancel_button = self.addButton(
            "Abbrechen", QMessageBox.ButtonRole.RejectRole
        )
        self.cancel_button.setObjectName("updateRestartCancelButton")

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._advance_countdown)
        self._refresh_message()

    def exec_countdown(self) -> int:
        self._timer.start()
        try:
            result = self.exec()
            return (
                QDialog.DialogCode.Rejected
                if self.clickedButton() is self.cancel_button
                else result
            )
        finally:
            self._timer.stop()

    def _refresh_message(self) -> None:
        unit = "Sekunde" if self.remaining_seconds == 1 else "Sekunden"
        self.setText(
            "Update erfolgreich heruntergeladen und geprüft.\n\n"
            f"Das Programm wird in {self.remaining_seconds} {unit} für die "
            "Installation beendet und bei erfolgreicher Installation automatisch "
            "neu gestartet."
        )

    def _advance_countdown(self) -> None:
        self.remaining_seconds -= 1
        if self.remaining_seconds <= 0:
            self._timer.stop()
            self.accept()
            return
        self._refresh_message()
