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
from cooling_tower.models import SourceKind
from cooling_tower.services import SourceRecognitionError, recognize_source


class SourceDropZone(QFrame):
    """Unified drag-and-drop and file-dialog input for one STL or G-code."""

    EMPTY_MINIMUM_HEIGHT_PX = 184
    EMPTY_PROMPT = (
        "STL oder G-Code hier ablegen\n"
        "oder über den Dialog auswählen"
    )
    REJECTED_PROMPT = (
        "Andere STL oder G-Code hier ablegen\n"
        "Die bisherige Datei wird ersetzt und direkt neu geprüft"
    )

    file_selected = Signal(str)
    source_selected = Signal(str, str)
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
        self._selected_kind: SourceKind | None = None
        self._display_state = "empty"

        self.root_layout = QVBoxLayout(self)
        self.prompt_label = QLabel(self.EMPTY_PROMPT)
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
        self.file_type_label = QLabel("–")
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
            self.file_type_label,
        ):
            # Kurze Werte bleiben einzeilig. Nur der Pfad darf umbrechen,
            # wenn die tatsächlich verfügbare Breite nicht ausreicht.
            value_label.setWordWrap(False)
        for row, (caption, value_label) in enumerate(
            (
                ("Status", self.status_value_label),
                ("Dateityp", self.file_type_label),
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
        self.file_info_label = QLabel("", self)
        self.file_info_label.hide()
        # These controls change visibility while the drop zone is still being
        # constructed.  Giving them an owner immediately prevents Qt from
        # treating them as temporary top-level windows before the action layout
        # reparents them.
        self.browse_button = QPushButton("STL oder G-Code auswählen …", self)
        self.browse_button.clicked.connect(self.select_file)
        self.remove_button = QPushButton("G-Code entfernen", self)
        self.remove_button.setObjectName("removeGcodeButton")
        self.remove_button.setEnabled(False)
        self.remove_button.clicked.connect(self.remove_requested)
        self.reload_button = QPushButton("G-Code neu einlesen", self)
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

    @property
    def selected_kind(self) -> SourceKind | None:
        return self._selected_kind

    def select_file(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "STL oder G-Code auswählen",
            str(self._selected_path.parent if self._selected_path else Path.home()),
            "Unterstützte Dateien (*.gcode *.stl);;G-Code (*.gcode);;STL (*.stl)",
        )
        if selected:
            self.set_file(selected)

    def set_file(self, path: str | Path) -> bool:
        try:
            recognized = recognize_source(path)
        except (OSError, SourceRecognitionError, ValueError) as error:
            self.file_rejected.emit(str(error))
            return False
        self._selected_path = recognized.path
        self._selected_kind = recognized.source_kind
        self.setProperty("loaded", True)
        size = recognized.size_bytes
        if recognized.source_kind is SourceKind.STL:
            self.status_value_label.setText(
                "STL-Modell erkannt – Geometrie wird geprüft"
            )
            self.remove_button.setText("STL entfernen")
            self.reload_button.setText("STL neu einlesen")
            self.browse_button.setText("Andere Datei auswählen")
        else:
            # The owner immediately replaces this established compatibility
            # status with its detailed running status.
            self.status_value_label.setText("Analyse wird vorbereitet")
            self.remove_button.setText("G-Code entfernen")
            self.reload_button.setText("G-Code neu einlesen")
            self.browse_button.setText("Andere Datei auswählen")
        self.file_type_label.setText(recognized.format_description)
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
        self.source_selected.emit(
            str(self._selected_path), recognized.source_kind.value
        )
        return True

    def set_status(self, status: str) -> None:
        self.status_value_label.setText(status)

    def set_analysis_state(self, state: str) -> None:
        """Switch between the empty, analyzing, failed and ready presentations."""

        if state not in {
            "empty",
            "analyzing",
            "failed",
            "preslice_failed",
            "rejected",
            "ready",
        }:
            raise ValueError(f"Unbekannter Quellen-Anzeigestatus: {state}")
        self._apply_display_state(state)

    def clear_file(self) -> None:
        self._selected_path = None
        self._selected_kind = None
        self.setProperty("loaded", False)
        self.status_value_label.setText("Keine Datei ausgewählt")
        self.file_name_label.setText("–")
        self.file_size_label.setText("–")
        self.file_type_label.setText("–")
        self.file_path_label.setText("–")
        self.file_info_label.clear()
        self.browse_button.setText("STL oder G-Code auswählen …")
        self.remove_button.setText("G-Code entfernen")
        self.reload_button.setText("G-Code neu einlesen")
        self._apply_display_state("empty")
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._single_supported_url(event.mimeData().urls()) is not None:
            event.acceptProposedAction()
            self._set_drag_active(True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._set_drag_active(False)
        event.accept()

    def dropEvent(self, event) -> None:  # noqa: N802
        self._set_drag_active(False)
        urls = event.mimeData().urls()
        path = self._single_supported_url(urls)
        if path is None:
            self.file_rejected.emit(
                "Bitte genau eine vorhandene STL- oder G-Code-Datei ablegen."
            )
            event.ignore()
            return
        if self.set_file(path):
            event.acceptProposedAction()

    @staticmethod
    def _single_supported_url(urls) -> Path | None:
        supported: list[Path] = []
        for url in urls:
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if path.suffix.casefold() in {".gcode", ".stl"} and path.is_file():
                supported.append(path)
        return supported[0] if len(supported) == 1 and len(urls) == 1 else None

    # Compatibility for earlier tests and extensions.
    _first_valid_url = _single_supported_url

    def _set_drag_active(self, active: bool) -> None:
        self.setProperty("dragActive", active)
        self.style().unpolish(self)
        self.style().polish(self)

    def _apply_display_state(self, state: str) -> None:
        self._display_state = state
        empty = state == "empty"
        ready = state == "ready"
        failed = state == "failed"
        preslice_failed = state == "preslice_failed"
        rejected = state == "rejected"
        actions_ready = ready or preslice_failed or rejected
        self.prompt_label.setText(
            self.REJECTED_PROMPT if rejected else self.EMPTY_PROMPT
        )
        self.prompt_label.setVisible(empty or rejected)
        self.info_widget.setVisible(not empty and not rejected)
        self.actions_widget.show()
        self.browse_button.show()
        self.reload_button.setVisible(actions_ready)
        self.remove_button.setVisible(actions_ready)
        self.reload_button.setEnabled(actions_ready)
        self.remove_button.setEnabled(actions_ready)

        while self.actions_layout.count():
            self.actions_layout.takeAt(0)
        for column in range(3):
            self.actions_layout.setColumnStretch(column, 0)
        if actions_ready:
            self.actions_layout.addWidget(self.browse_button, 0, 0)
            self.actions_layout.addWidget(self.reload_button, 0, 1)
            self.actions_layout.addWidget(self.remove_button, 0, 2)
            for column in range(3):
                self.actions_layout.setColumnStretch(column, 1)
        elif failed:
            self.actions_layout.addWidget(self.browse_button, 0, 0)
            self.actions_layout.addWidget(self.reload_button, 0, 1)
            self.reload_button.show()
            self.reload_button.setEnabled(True)
            self.actions_layout.setColumnStretch(0, 1)
            self.actions_layout.setColumnStretch(1, 1)
        elif empty:
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


# Public compatibility alias. New code should use SourceDropZone.
GCodeDropZone = SourceDropZone
