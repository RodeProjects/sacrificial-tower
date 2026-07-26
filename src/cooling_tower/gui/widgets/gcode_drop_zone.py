from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class GCodeDropZone(QFrame):
    """Reusable drag-and-drop and file-dialog input for one .gcode file."""

    EMPTY_MINIMUM_HEIGHT_PX = 184

    file_selected = Signal(str)
    file_rejected = Signal(str)
    reload_requested = Signal()
    remove_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("gcodeDropZone")
        self.setAcceptDrops(True)
        self.setProperty("dragActive", False)
        self.setProperty("loaded", False)
        self._selected_path: Path | None = None
        self._display_state = "empty"

        self.root_layout = QVBoxLayout(self)
        self.prompt_label = QLabel(
            "G-Code hier ablegen\noder über den Dialog auswählen"
        )
        self.prompt_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.root_layout.addWidget(self.prompt_label, 1)

        info_layout = QGridLayout()
        info_layout.setColumnStretch(1, 1)
        info_layout.setHorizontalSpacing(12)
        self.status_value_label = QLabel("Keine Datei ausgewählt")
        self.status_value_label.setObjectName("gcodeStatusValue")
        self.file_name_label = QLabel("–")
        self.file_name_label.setObjectName("dropFileName")
        self.file_size_label = QLabel("–")
        self.file_path_label = QLabel("–")
        self.file_path_label.setObjectName("gcodeFilePath")
        self.file_path_label.setWordWrap(True)
        self.file_path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        for value_label in (
            self.status_value_label,
            self.file_name_label,
            self.file_size_label,
        ):
            # Kurze Werte bleiben einzeilig. Nur der Pfad darf umbrechen,
            # wenn die tatsächlich verfügbare Breite nicht ausreicht.
            value_label.setWordWrap(False)
        for row, (caption, value_label) in enumerate(
            (
                ("Status", self.status_value_label),
                ("Dateiname", self.file_name_label),
                ("Dateigröße", self.file_size_label),
                ("Dateipfad", self.file_path_label),
            )
        ):
            caption_label = QLabel(caption)
            caption_label.setObjectName("gcodeInfoCaption")
            info_layout.addWidget(caption_label, row, 0, Qt.AlignmentFlag.AlignTop)
            info_layout.addWidget(value_label, row, 1)
        self.info_widget = QWidget(self)
        self.info_widget.setObjectName("gcodeFileInformation")
        self.info_widget.setLayout(info_layout)
        self.root_layout.addWidget(self.info_widget)

        # Compatibility for callers that previously read the combined info
        # label.  The visible UI uses the four dedicated rows above.
        self.file_info_label = QLabel("")
        self.file_info_label.hide()
        self.browse_button = QPushButton("G-Code auswählen …")
        self.browse_button.clicked.connect(self.select_file)
        self.remove_button = QPushButton("G-Code entfernen")
        self.remove_button.setObjectName("removeGcodeButton")
        self.remove_button.setEnabled(False)
        self.remove_button.clicked.connect(self.remove_requested)
        self.reload_button = QPushButton("G-Code neu einlesen")
        self.reload_button.setObjectName("reloadGcodeButton")
        self.reload_button.setEnabled(False)
        self.reload_button.setToolTip(
            "Die ausgewählte Datei erneut vom Datenträger analysieren"
        )
        self.reload_button.clicked.connect(self.reload_requested)

        self.actions_layout = QGridLayout()
        self.actions_layout.setContentsMargins(0, 0, 0, 0)
        self.actions_layout.setHorizontalSpacing(8)
        self.actions_layout.setVerticalSpacing(6)
        self.actions_widget = QWidget(self)
        self.actions_widget.setObjectName("gcodeActions")
        self.actions_widget.setLayout(self.actions_layout)
        self.root_layout.addWidget(self.actions_widget)
        self.setMinimumHeight(self.EMPTY_MINIMUM_HEIGHT_PX)
        self._apply_display_state("empty")

    @property
    def selected_path(self) -> Path | None:
        return self._selected_path

    def select_file(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Referenz-G-Code auswählen",
            str(self._selected_path.parent if self._selected_path else Path.home()),
            "G-Code-Dateien (*.gcode);;Alle Dateien (*.*)",
        )
        if selected:
            self.set_file(selected)

    def set_file(self, path: str | Path) -> bool:
        candidate = Path(path).expanduser()
        if (
            candidate.suffix.lower() != ".gcode"
            or not candidate.exists()
            or not candidate.is_file()
        ):
            message = "Bitte eine vorhandene .gcode-Datei auswählen."
            self.file_rejected.emit(message)
            return False
        self._selected_path = candidate.resolve()
        self.setProperty("loaded", True)
        size = self._selected_path.stat().st_size
        self.status_value_label.setText("Analyse wird vorbereitet")
        self.file_name_label.setText(self._selected_path.name)
        self.file_size_label.setText(_format_size(size))
        self.file_path_label.setText(str(self._selected_path))
        self.file_info_label.setText(
            f"Größe: {_format_size(size)}\nPfad: {self._selected_path}"
        )
        self._apply_display_state("analyzing")
        self.style().unpolish(self)
        self.style().polish(self)
        self.file_selected.emit(str(self._selected_path))
        return True

    def set_status(self, status: str) -> None:
        self.status_value_label.setText(status)

    def set_analysis_state(self, state: str) -> None:
        """Switch between the empty, analyzing, failed and ready presentations."""

        if state not in {"empty", "analyzing", "failed", "ready"}:
            raise ValueError(f"Unbekannter G-Code-Anzeigestatus: {state}")
        self._apply_display_state(state)

    def clear_file(self) -> None:
        self._selected_path = None
        self.setProperty("loaded", False)
        self.status_value_label.setText("Keine Datei ausgewählt")
        self.file_name_label.setText("–")
        self.file_size_label.setText("–")
        self.file_path_label.setText("–")
        self.file_info_label.clear()
        self._apply_display_state("empty")
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._first_valid_url(event.mimeData().urls()) is not None:
            event.acceptProposedAction()
            self._set_drag_active(True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._set_drag_active(False)
        event.accept()

    def dropEvent(self, event) -> None:  # noqa: N802
        self._set_drag_active(False)
        path = self._first_valid_url(event.mimeData().urls())
        if path is None:
            self.file_rejected.emit(
                "Im Drop-Inhalt wurde keine gültige .gcode-Datei gefunden."
            )
            event.ignore()
            return
        if self.set_file(path):
            event.acceptProposedAction()

    @staticmethod
    def _first_valid_url(urls) -> Path | None:
        for url in urls:
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if path.suffix.lower() == ".gcode" and path.is_file():
                return path
        return None

    def _set_drag_active(self, active: bool) -> None:
        self.setProperty("dragActive", active)
        self.style().unpolish(self)
        self.style().polish(self)

    def _apply_display_state(self, state: str) -> None:
        self._display_state = state
        empty = state == "empty"
        ready = state == "ready"
        failed = state == "failed"
        self.prompt_label.setVisible(empty)
        self.info_widget.setVisible(not empty)
        self.actions_widget.show()
        self.browse_button.show()
        self.reload_button.setVisible(ready)
        self.remove_button.setVisible(ready)
        self.reload_button.setEnabled(ready)
        self.remove_button.setEnabled(ready)

        while self.actions_layout.count():
            self.actions_layout.takeAt(0)
        for column in range(3):
            self.actions_layout.setColumnStretch(column, 0)
        if ready:
            self.actions_layout.addWidget(self.browse_button, 0, 0)
            self.actions_layout.addWidget(self.reload_button, 0, 1)
            self.actions_layout.addWidget(self.remove_button, 0, 2)
            for column in range(3):
                self.actions_layout.setColumnStretch(column, 1)
        elif empty or failed:
            self.actions_layout.addWidget(
                self.browse_button,
                0,
                1,
                Qt.AlignmentFlag.AlignHCenter,
            )
            self.actions_layout.setColumnStretch(0, 1)
            self.actions_layout.setColumnStretch(2, 1)
        else:
            # During analysis the information rows use the full lower area;
            # controls return only after a successful analysis.
            self.actions_widget.hide()


def _format_size(size_bytes: int) -> str:
    value = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024.0 or unit == "GB":
            decimals = 0 if unit == "B" else 1
            return f"{value:.{decimals}f} {unit}"
        value /= 1024.0
    return f"{size_bytes} B"
