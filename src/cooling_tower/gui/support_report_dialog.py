from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from cooling_tower.support_report import SupportReportService
from cooling_tower.version import APP_NAME


class SupportReportDialog(QDialog):
    """Collect a local problem report and create a diagnostic ZIP bundle."""

    def __init__(
        self,
        service: SupportReportService,
        *,
        application_context_provider: Callable[[], Mapping[str, Any]],
        open_directory: Callable[[str | Path], None],
        asset_root: Path,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self._application_context_provider = application_context_provider
        self._open_directory = open_directory
        self._asset_root = Path(asset_root)
        self.last_bundle_path: Path | None = None

        self.setObjectName("supportReportDialog")
        self.setWindowTitle("Support & Diagnose")
        self.setModal(False)
        self.setMinimumSize(620, 590)
        self.resize(700, 670)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        title = QLabel("Problembericht und Diagnosepaket")
        title.setObjectName("supportReportTitle")
        layout.addWidget(title)

        introduction = QLabel(
            "Beschreiben Sie kurz das Problem. Das Programm erstellt daraus "
            "und aus technischen Diagnosedaten eine ZIP-Datei. Sie bleibt "
            "lokal und wird nicht automatisch übertragen."
        )
        introduction.setObjectName("supportReportIntroduction")
        introduction.setWordWrap(True)
        layout.addWidget(introduction)

        self.summary_edit = QLineEdit()
        self.summary_edit.setObjectName("supportReportSummary")
        self.summary_edit.setPlaceholderText(
            "Kurze Zusammenfassung, z. B. „Slicer wird nicht erkannt“"
        )
        self.summary_edit.setAccessibleName("Zusammenfassung des Problems")
        summary_label = QLabel("Kurze Zusammenfassung")
        summary_label.setBuddy(self.summary_edit)
        layout.addWidget(summary_label)
        layout.addWidget(self.summary_edit)

        self.description_edit = QTextEdit()
        self.description_edit.setObjectName("supportReportDescription")
        self.description_edit.setAcceptRichText(False)
        self.description_edit.setPlaceholderText(
            "Was ist passiert?\n"
            "Welche Schritte führten zu dem Problem?\n"
            "Was wurde erwartet und was ist stattdessen geschehen?"
        )
        self.description_edit.setAccessibleName("Ausführliche Problembeschreibung")
        description_label = QLabel("Problembeschreibung")
        description_label.setBuddy(self.description_edit)
        layout.addWidget(description_label)
        layout.addWidget(self.description_edit, 1)

        privacy_frame = QFrame()
        privacy_frame.setObjectName("supportReportPrivacy")
        privacy_layout = QHBoxLayout(privacy_frame)
        privacy_layout.setContentsMargins(12, 9, 12, 9)
        privacy_layout.setSpacing(9)
        privacy_icon = QLabel()
        privacy_icon.setPixmap(
            QIcon(str(self._asset_root / "privacy.svg")).pixmap(20, 20)
        )
        privacy_icon.setAccessibleName("Datenschutzhinweis")
        privacy_layout.addWidget(privacy_icon, 0, Qt.AlignmentFlag.AlignTop)
        privacy_text = QLabel(
            "Wichtig: Zusammenfassung und Beschreibung werden unverändert im "
            "Klartext gespeichert. Geben Sie dort keine persönlichen oder "
            "sensiblen Daten ein.\n\n"
            "Technische Diagnosedaten werden gefiltert. Rohlogs, Pfade, "
            "Dateinamen, Zugangsdaten sowie G-Code-, STL-, Slicer- und "
            "Konfigurationsdateien werden nicht beigefügt. Prüfen Sie die ZIP "
            "vor der Weitergabe."
        )
        privacy_text.setObjectName("supportReportPrivacyText")
        privacy_text.setWordWrap(True)
        privacy_layout.addWidget(privacy_text, 1)
        layout.addWidget(privacy_frame)

        self.result_label = QLabel("Noch kein Diagnosepaket erstellt.")
        self.result_label.setObjectName("supportReportResult")
        self.result_label.setWordWrap(True)
        self.result_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.result_label)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.create_button = QPushButton("Diagnosepaket erstellen")
        self.create_button.setObjectName("primaryButton")
        self.create_button.setIcon(
            QIcon(str(self._asset_root / "document.svg"))
        )
        self.create_button.setIconSize(QSize(18, 18))
        self.create_button.clicked.connect(self.create_bundle)
        actions.addWidget(self.create_button)

        self.open_folder_button = QPushButton("Ordner öffnen")
        self.open_folder_button.setObjectName("supportReportOpenFolder")
        self.open_folder_button.setIcon(
            QIcon(str(self._asset_root / "folder.svg"))
        )
        self.open_folder_button.setIconSize(QSize(18, 18))
        self.open_folder_button.clicked.connect(self.open_report_folder)
        actions.addWidget(self.open_folder_button)
        actions.addStretch(1)

        close_button = QPushButton("Schließen")
        close_button.setIcon(QIcon(str(self._asset_root / "close.svg")))
        close_button.setIconSize(QSize(18, 18))
        close_button.clicked.connect(self.close)
        actions.addWidget(close_button)
        layout.addLayout(actions)

        self.summary_edit.textChanged.connect(self._clear_validation_state)
        self.description_edit.textChanged.connect(self._clear_validation_state)

    def create_bundle(self) -> None:
        title = self.summary_edit.text().strip()
        description = self.description_edit.toPlainText().strip()
        self.summary_edit.setProperty("invalid", not bool(title))
        self.description_edit.setProperty("invalid", not bool(description))
        self._refresh_input_style(self.summary_edit)
        self._refresh_input_style(self.description_edit)
        if not title or not description:
            self.result_label.setProperty("state", "error")
            self.result_label.setText(
                "Bitte füllen Sie die Zusammenfassung und die "
                "Problembeschreibung aus."
            )
            self._refresh_input_style(self.result_label)
            (self.summary_edit if not title else self.description_edit).setFocus()
            return

        self.create_button.setEnabled(False)
        self.result_label.setProperty("state", "working")
        self.result_label.setText("Diagnosepaket wird erstellt …")
        self._refresh_input_style(self.result_label)
        try:
            bundle = self.service.create_bundle(
                title=title,
                description=description,
                application_context=self._application_context_provider(),
            )
        except Exception as error:  # GUI boundary: keep report failures visible
            self.result_label.setProperty("state", "error")
            self.result_label.setText(
                "Das Diagnosepaket konnte nicht erstellt werden: "
                f"{error}"
            )
            self._refresh_input_style(self.result_label)
            return
        finally:
            self.create_button.setEnabled(True)

        self.last_bundle_path = bundle.path
        self.result_label.setProperty("state", "success")
        self.result_label.setText(
            "Diagnosepaket erfolgreich erstellt:\n"
            f"{bundle.path.name}\n\n"
            f"Bericht-ID: {bundle.report_id}"
        )
        self._refresh_input_style(self.result_label)

    def open_report_folder(self) -> None:
        try:
            directory = self.service.ensure_output_directory()
            self._open_directory(directory)
        except OSError as error:
            self.result_label.setProperty("state", "error")
            self.result_label.setText(
                "Der Ordner konnte nicht geöffnet werden: " f"{error}"
            )
            self._refresh_input_style(self.result_label)

    def _clear_validation_state(self) -> None:
        for editor in (self.summary_edit, self.description_edit):
            if editor.property("invalid"):
                editor.setProperty("invalid", False)
                self._refresh_input_style(editor)

    @staticmethod
    def _refresh_input_style(widget) -> None:  # type: ignore[no-untyped-def]
        widget.style().unpolish(widget)
        widget.style().polish(widget)
