from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)
from cooling_tower.models import SourceKind
from cooling_tower.services import SourceRecognitionError, recognize_source


class SourceDropZone(QFrame):
    """Drag-and-drop and file-dialog input for one STL model."""

    EMPTY_MINIMUM_HEIGHT_PX = 260
    LOADED_REPLACEMENT_HINT_MIN_HEIGHT_PX = 330
    EMPTY_PROMPT = "STL hier ablegen\noder über den Dialog auswählen"
    REJECTED_PROMPT = (
        "Andere STL hier ablegen\n"
        "Die bisherige Datei wird ersetzt und direkt neu geprüft"
    )

    REPLACEMENT_PROMPT = (
        "Andere STL hier ablegen.\n"
        "Die bisherige Datei wird dadurch ersetzt"
    )

    source_selected = Signal(str, str)
    file_rejected = Signal(str)
    reload_requested = Signal()
    remove_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("sourceDropZone")
        self.setAcceptDrops(True)
        self.setProperty("dragActive", False)
        self.setProperty("loaded", False)
        self.setProperty("completed", False)
        self._selected_path: Path | None = None
        self._selected_kind: SourceKind | None = None
        self._display_state = "empty"

        self.root_layout = QVBoxLayout(self)
        self.empty_top_spacer = QSpacerItem(
            0,
            0,
            QSizePolicy.Policy.Minimum,
            QSizePolicy.Policy.Expanding,
        )
        self.root_layout.addSpacerItem(self.empty_top_spacer)
        self.prompt_label = QLabel(self.EMPTY_PROMPT)
        self.prompt_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.root_layout.addWidget(self.prompt_label)

        info_layout = QGridLayout()
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setColumnStretch(1, 1)
        info_layout.setHorizontalSpacing(12)
        info_layout.setVerticalSpacing(7)
        info_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.status_value_label = QLabel("Keine Datei ausgewählt")
        self.status_value_label.setObjectName("sourceStatusValue")
        self.file_name_label = QLabel("–")
        self.file_name_label.setObjectName("dropFileName")
        self.file_size_label = QLabel("–")
        self.file_type_label = QLabel("–")
        self.file_path_label = QLabel("–")
        self.file_path_label.setObjectName("sourceFilePath")
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
            caption_label.setObjectName("sourceInfoCaption")
            info_layout.addWidget(caption_label, row, 0, Qt.AlignmentFlag.AlignTop)
            info_layout.addWidget(value_label, row, 1)
        self.info_widget = QWidget(self)
        self.info_widget.setObjectName("sourceFileInformation")
        self.info_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Maximum,
        )
        self.info_widget.setLayout(info_layout)
        self.root_layout.addWidget(self.info_widget)

        self.notice_widget = QWidget(self)
        self.notice_widget.setObjectName("sourceNotices")
        self.notice_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Maximum,
        )
        self.notice_layout = QVBoxLayout(self.notice_widget)
        self.notice_layout.setContentsMargins(0, 0, 0, 0)
        self.notice_layout.setSpacing(6)
        self.notice_widget.hide()
        self.root_layout.addWidget(self.notice_widget)

        # Compatibility for callers that previously read the combined info
        # label.  The visible UI uses the four dedicated rows above.
        self.file_info_label = QLabel("", self)
        self.file_info_label.hide()
        # These controls change visibility while the drop zone is still being
        # constructed.  Giving them an owner immediately prevents Qt from
        # treating them as temporary top-level windows before the action layout
        # reparents them.
        self.browse_button = QPushButton("STL auswählen …", self)
        self.browse_button.setObjectName("sourcePrimaryActionButton")
        self.browse_button.clicked.connect(self.select_file)
        self.remove_button = QPushButton("STL entfernen", self)
        self.remove_button.setObjectName("removeSourceButton")
        self.remove_button.setEnabled(False)
        self.remove_button.clicked.connect(self.remove_requested)
        self.reload_button = QPushButton("STL neu einlesen", self)
        self.reload_button.setObjectName("reloadSourceButton")
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
        self.actions_widget.setObjectName("sourceActions")
        self.actions_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Maximum,
        )
        self.actions_widget.setLayout(self.actions_layout)
        self.root_layout.addWidget(self.actions_widget)

        self.details_widget = QWidget(self)
        self.details_widget.setObjectName("sourceTechnicalDetails")
        self.details_layout = QVBoxLayout(self.details_widget)
        self.details_layout.setContentsMargins(0, 0, 0, 0)
        self.details_layout.setSpacing(6)
        self.details_widget.hide()
        self.root_layout.addWidget(self.details_widget)
        self.empty_bottom_spacer = QSpacerItem(
            0,
            0,
            QSizePolicy.Policy.Minimum,
            QSizePolicy.Policy.Expanding,
        )
        self.root_layout.addSpacerItem(self.empty_bottom_spacer)
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
            "STL auswählen",
            str(self._selected_path.parent if self._selected_path else Path.home()),
            "STL-Modelldateien (*.stl)",
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
        self.status_value_label.setText(
            "STL-Modell erkannt – Geometrie wird geprüft"
        )
        self.remove_button.setText("STL entfernen")
        self.reload_button.setText("STL neu einlesen")
        self.browse_button.setText("Andere STL auswählen")
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
        self.source_selected.emit(
            str(self._selected_path), recognized.source_kind.value
        )
        return True

    def set_status(self, status: str) -> None:
        self.status_value_label.setText(status)

    def add_notice_widget(self, widget: QWidget) -> None:
        """Place a source notice directly below the compact file facts."""

        self.notice_layout.addWidget(widget)
        self.notice_widget.show()

    def add_details_widget(self, widget: QWidget) -> None:
        """Keep technical disclosures as the final block of the drop zone."""

        self.details_layout.addWidget(widget)
        self.details_widget.show()

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

    def set_completed(self, completed: bool) -> None:
        """Tint the drop area only after its complete workflow has finished."""

        self.setProperty("completed", bool(completed))
        self.style().unpolish(self)
        self.style().polish(self)

    def clear_file(self) -> None:
        self._selected_path = None
        self._selected_kind = None
        self.setProperty("loaded", False)
        self.setProperty("completed", False)
        self.status_value_label.setText("Keine Datei ausgewählt")
        self.file_name_label.setText("–")
        self.file_size_label.setText("–")
        self.file_type_label.setText("–")
        self.file_path_label.setText("–")
        self.file_info_label.clear()
        self.browse_button.setText("STL auswählen …")
        self.remove_button.setText("STL entfernen")
        self.reload_button.setText("STL neu einlesen")
        self._apply_display_state("empty")
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._single_supported_url(event.mimeData().urls()) is not None:
            event.acceptProposedAction()
            self._set_drag_active(True)
        else:
            event.ignore()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._sync_prompt_presentation()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._set_drag_active(False)
        event.accept()

    def dropEvent(self, event) -> None:  # noqa: N802
        self._set_drag_active(False)
        urls = event.mimeData().urls()
        path = self._single_supported_url(urls)
        if path is None:
            self.file_rejected.emit(
                "Bitte genau eine vorhandene STL-Datei ablegen."
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
            if path.suffix.casefold() == ".stl" and path.is_file():
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
        self.setMinimumHeight(self.EMPTY_MINIMUM_HEIGHT_PX if empty else 0)
        spacer_policy = (
            QSizePolicy.Policy.Expanding
            if empty
            else QSizePolicy.Policy.Fixed
        )
        self.empty_top_spacer.changeSize(
            0,
            0,
            QSizePolicy.Policy.Minimum,
            spacer_policy,
        )
        self.empty_bottom_spacer.changeSize(
            0,
            0,
            QSizePolicy.Policy.Minimum,
            spacer_policy,
        )
        self.root_layout.setSpacing(18 if empty else 6)
        self.setProperty("completed", ready)
        self._sync_prompt_presentation()
        self.info_widget.setVisible(not empty)
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
        self.root_layout.invalidate()
        self.style().unpolish(self)
        self.style().polish(self)

    def _sync_prompt_presentation(self) -> None:
        empty = self._display_state == "empty"
        replacement = not empty
        self.prompt_label.setText(
            self.REPLACEMENT_PROMPT if replacement else self.EMPTY_PROMPT
        )
        self.prompt_label.setProperty("replacementHint", replacement)
        self.prompt_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Maximum,
        )
        self.root_layout.setStretch(
            self.root_layout.indexOf(self.prompt_label),
            0,
        )
        must_offer_replacement = self._display_state in {
            "failed",
            "preslice_failed",
            "rejected",
        }
        self.prompt_label.setVisible(
            empty
            or must_offer_replacement
            or (
                self._display_state == "analyzing"
                and self.height()
                >= self.LOADED_REPLACEMENT_HINT_MIN_HEIGHT_PX
            )
        )
        style = self.prompt_label.style()
        style.unpolish(self.prompt_label)
        style.polish(self.prompt_label)


def _format_size(size_bytes: int) -> str:
    value = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024.0 or unit == "GB":
            decimals = 0 if unit == "B" else 1
            return f"{value:.{decimals}f} {unit}"
        value /= 1024.0
    return f"{size_bytes} B"
