from __future__ import annotations

from pathlib import Path
import csv

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
from cooling_tower.gui.update_transaction import suspended_widget_updates
from cooling_tower.gui.native_project.styles import NATIVE_DROP_STYLE


GUIDE_HTML = ('<b>Vollständiges Projekt speichern</b><br>'
    'Im erzeugenden Slicer <b>Datei → Projekt speichern als</b> wählen und als <b>.3mf</b> speichern. '
    'Drucker-, Material- und Prozesseinstellungen müssen enthalten sein.<br><br>'
    'Anycubic Slicer Next <span style="font-size:small;color:#7b8a99">(2.0.0.3)</span><br>'
    'Bambu Studio <span style="font-size:small;color:#7b8a99">(02.08.02.61)</span><br>'
    'PrusaSlicer <span style="font-size:small;color:#7b8a99">(2.9.6)</span><br>'
    'OrcaSlicer <span style="font-size:small;color:#7b8a99">(Engine 2.4.2 · Paket 2.4.3.0)</span>')


class NativeProjectDropZone(QFrame):
    """Independent project handover; content validation runs in the worker."""

    EMPTY_MINIMUM_HEIGHT_PX = 260
    EMPTY_PROMPT = "3MF-Projektdatei hier ablegen\noder über den Dialog auswählen"

    open_requested = Signal()
    source_selected = Signal(str, str)
    file_rejected = Signal(str)
    reload_requested = Signal()
    remove_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("nativeProjectDropZone")
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
        self.browse_button = QPushButton("3MF-Projekt auswählen …", self)
        self.browse_button.setObjectName("sourcePrimaryActionButton")
        self.browse_button.clicked.connect(self.select_file)
        self.remove_button = QPushButton("Projekt entfernen", self)
        self.remove_button.setObjectName("removeSourceButton")
        self.remove_button.setEnabled(False)
        self.remove_button.clicked.connect(self.remove_requested)
        self.reload_button = QPushButton("Projekt neu einlesen", self)
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

        self.setStyleSheet(NATIVE_DROP_STYLE)
        self.status_value_label.setWordWrap(True)
        self.file_name_label.setWordWrap(True)
        self.project_fields = {}
        grid = self.info_widget.layout()
        for row,key in enumerate(('Slicer','Erzeugerversion','Drucker','Maschinenprofil','Düse','Material',
                                  'Filamentprofile','Prozessprofil','Druckplatten'),5):
            caption,value = QLabel(key),QLabel('–')
            caption.setObjectName('sourceInfoCaption')
            value.setTextFormat(Qt.TextFormat.PlainText)
            value.setWordWrap(True)
            grid.addWidget(caption,row,0,Qt.AlignmentFlag.AlignTop)
            grid.addWidget(value,row,1)
            caption.hide(); value.hide()
            self.project_fields[key] = caption,value
        self.notice_label = QLabel()
        self.notice_label.setTextFormat(Qt.TextFormat.PlainText)
        self.notice_label.setWordWrap(True)
        self.notice_label.hide()
        self.add_notice_widget(self.notice_label)
        self.guide_label = QLabel(GUIDE_HTML)
        self.guide_label.setTextFormat(Qt.TextFormat.RichText)
        self.guide_label.setWordWrap(True)
        self.guide_label.hide()
        self.add_notice_widget(self.guide_label)
        self.notice_widget.hide()
        self.open_button = QPushButton('Projekt bearbeiten',self)
        self.open_button.setObjectName('primaryButton')
        self.open_button.clicked.connect(self.open_requested)
        self.open_button.hide()
        self.file_rejected.connect(lambda message:self.show_problem(message,None))


    @property
    def selected_path(self) -> Path | None:
        return self._selected_path

    @property
    def selected_kind(self) -> SourceKind | None:
        return self._selected_kind

    def select_file(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "STL oder natives 3MF-Projekt auswählen",
            str(self._selected_path.parent if self._selected_path else Path.home()),
            "Modelle und Projekte (*.stl *.3mf);;STL-Modelle (*.stl);;3MF-Projekte (*.3mf)",
        )
        if selected:
            self.set_file(selected)

    def set_file(self, path):
        try:
            candidate = Path(path).expanduser().resolve(strict=True)
            if candidate.suffix.casefold() == '.stl' and candidate.is_file():
                self.source_selected.emit(str(candidate),SourceKind.STL.value)
                return True
            if candidate.suffix.casefold() != '.3mf' or not candidate.is_file():
                raise ValueError('Bitte eine native 3MF-Projektdatei auswählen.')
            size = candidate.stat().st_size
        except (OSError,ValueError) as error:
            self.file_rejected.emit(str(error))
            return False
        with suspended_widget_updates(self.window()):
            self._selected_path = candidate
            self._selected_kind = SourceKind.NATIVE_3MF
            self.setProperty('loaded',True)
            self.setProperty('completed',False)
            self.file_name_label.setText(candidate.name)
            self.file_type_label.setText('Natives 3MF-Projekt')
            self.file_size_label.setText(_format_size(size))
            self.file_path_label.setText(str(candidate))
            self.browse_button.setText('Andere Datei auswählen')
            self.status_value_label.setText('Projekt wird eingelesen – eingebettete Einstellungen werden geprüft')
            self.notice_label.hide(); self.guide_label.hide(); self.notice_widget.hide()
            for caption,value in self.project_fields.values():
                caption.hide(); value.hide()
            self.set_analysis_state('analyzing')
            self.source_selected.emit(str(candidate),SourceKind.NATIVE_3MF.value)
        return True




    def set_status(self, status: str) -> None:
        self.status_value_label.setText(status)

    def add_notice_widget(self, widget: QWidget) -> None:
        """Place a source notice directly below the compact file facts."""

        self.notice_layout.addWidget(widget)
        self.notice_widget.show()
        if self._display_state != "empty":
            self._reserve_loaded_content_height()

    def add_details_widget(self, widget: QWidget) -> None:
        """Keep technical disclosures as the final block of the drop zone."""

        self.details_layout.addWidget(widget)
        self.details_widget.show()
        if self._display_state != "empty":
            self._reserve_loaded_content_height()

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
        if self._display_state != "empty":
            self._reserve_loaded_content_height()

    def _clear_native_file(self) -> None:
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
        self.browse_button.setText("3MF-Projekt auswählen …")
        self.remove_button.setText("Projekt entfernen")
        self.reload_button.setText("Projekt neu einlesen")
        self._apply_display_state("empty")

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._single_supported_url(event.mimeData().urls()) is not None:
            event.acceptProposedAction()
            self._set_drag_active(True)
        else:
            self._set_drag_active(False)
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        """Keep the visual drop target active for the complete drag gesture."""

        if self._single_supported_url(event.mimeData().urls()) is not None:
            event.acceptProposedAction()
            self._set_drag_active(True)
        else:
            self._set_drag_active(False)
            event.ignore()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._sync_prompt_presentation()
        if self._display_state != "empty":
            self._reserve_loaded_content_height(event.size().width())

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._set_drag_active(False)
        event.accept()

    def dropEvent(self, event) -> None:  # noqa: N802
        self._set_drag_active(False)
        urls = event.mimeData().urls()
        path = self._single_supported_url(urls)
        if path is None:
            self.file_rejected.emit(
                "Bitte genau eine vorhandene STL- oder 3MF-Datei ablegen."
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
            if path.suffix.casefold() in {'.stl','.3mf'} and path.is_file():
                supported.append(path)
        return supported[0] if len(supported) == 1 and len(urls) == 1 else None

    # Compatibility for earlier tests and extensions.
    _first_valid_url = _single_supported_url

    def _set_drag_active(self, active: bool) -> None:
        active = bool(active)
        if bool(self.property("dragActive")) == active:
            return
        reserved_minimum_height = self.minimumHeight()
        self.setProperty("dragActive", active)
        self.style().unpolish(self)
        self.style().polish(self)
        if (
            self._display_state != "empty"
            and self.minimumHeight() != reserved_minimum_height
        ):
            # Hover changes only the paint state. Re-polishing must neither
            # recalculate nor discard the already published content height.
            self.setMinimumHeight(reserved_minimum_height)
        self.update()

    def _reserve_loaded_content_height(self, width: int | None = None) -> None:
        """Reserve every visible loaded-state row, including wrapped paths."""

        self.root_layout.invalidate()
        self.root_layout.activate()
        frame_height = self.frameWidth() * 2
        layout_width = max(
            1,
            int(self.width() if width is None else width)
            - self.frameWidth() * 2,
        )
        if not self.info_widget.isHidden() and self.info_widget.hasHeightForWidth():
            margins = self.root_layout.contentsMargins()
            info_width = max(1, layout_width - margins.left() - margins.right())
            # AlignTop otherwise caps this child at its unconstrained sizeHint,
            # while the parent reserves the wrapped path's larger height.
            # Publish the measured height so both layouts use the same rows.
            self.info_widget.setFixedHeight(self.info_widget.heightForWidth(info_width))
            self.root_layout.invalidate()
        required_height = max(
            0,
            self.root_layout.minimumSize().height(),
        )
        if self.root_layout.hasHeightForWidth():
            # The unconstrained size hint may assume another wrapped path
            # line even when the real width fits it. Use the measured width
            # instead, otherwise that phantom line becomes bottom padding.
            required_height = max(
                required_height,
                self.root_layout.heightForWidth(layout_width),
            )
        else:
            required_height = max(required_height, self.root_layout.sizeHint().height())
        required_height += frame_height
        if self.minimumHeight() != required_height or self.maximumHeight() != required_height:
            # A minimum alone lets the former empty-state allocation survive
            # for a frame. Qt then distributes that surplus above/below the
            # facts until the parent card catches up with the loaded content.
            self.setFixedHeight(required_height)
            self.updateGeometry()
        self.root_layout.setGeometry(self.contentsRect())

    def _apply_native_display_state(self, state: str) -> None:
        self._display_state = state
        empty = state == "empty"
        ready = state == "ready"
        failed = state == "failed"
        preslice_failed = state == "preslice_failed"
        rejected = state == "rejected"
        actions_ready = ready or preslice_failed or rejected
        self.setMinimumHeight(self.EMPTY_MINIMUM_HEIGHT_PX if empty else 0)
        self.setMaximumHeight(16777215)
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
        self.root_layout.setAlignment(Qt.Alignment() if empty else Qt.AlignmentFlag.AlignTop)
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
        if not empty:
            # Every loaded state must publish the complete preferred height.
            # In particular, the ready state contains three actions and may
            # wrap the file path; a stylesheet-only 96 px minimum would let
            # the parent card compress those rows into each other.
            self._reserve_loaded_content_height()
        self.updateGeometry()

    def _sync_prompt_presentation(self) -> None:
        empty = self._display_state == "empty"
        self.prompt_label.setText(self.EMPTY_PROMPT)
        self.prompt_label.setProperty("replacementHint", False)
        self.prompt_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Maximum,
        )
        self.root_layout.setStretch(
            self.root_layout.indexOf(self.prompt_label),
            0,
        )
        self.prompt_label.setVisible(empty)
        style = self.prompt_label.style()
        style.unpolish(self.prompt_label)
        style.polish(self.prompt_label)



    def show_imported(self, imported):
        context = imported.session.context
        product = (imported.installation.display_name if imported.installation else
            {'anycubic_slicer_next':'Anycubic Slicer Next','bambu_studio':'Bambu Studio',
             'prusa_slicer':'PrusaSlicer','orca_slicer':'OrcaSlicer'}[context.adapter_id])
        def profile_text(key,fallback):
            value = context.settings.get(key)
            if key == 'filament_settings_id' and context.adapter_id == 'prusa_slicer' and isinstance(value,str):
                try:
                    value = next(csv.reader([value],delimiter=';',escapechar='\\'))
                except csv.Error:
                    pass
            if isinstance(value,(list,tuple)):
                return '\n'.join(str(item) for item in value if item) or fallback
            return str(value) if value else fallback
        values = {'Slicer':product,'Erzeugerversion':context.producer_version,'Drucker':context.printer,
            'Maschinenprofil':profile_text('printer_settings_id',context.printer),
            'Filamentprofile':profile_text('filament_settings_id','\n'.join(context.materials)),
            'Prozessprofil':profile_text('print_settings_id',profile_text('process_settings_id','Eingebettete Projekteinstellungen')),
            'Düse':', '.join(f'{value:g} mm' for value in context.nozzle_diameters),
            'Material':', '.join(context.materials),
            'Druckplatten':'\n'.join(f'{plate.name} ({plate.object_count} '
                f'{"Objektinstanz" if plate.object_count == 1 else "Objektinstanzen"})' for plate in context.plates)}
        for key,text in values.items():
            caption,value = self.project_fields[key]
            value.setText(text)
            caption.show(); value.show()
        self.set_status('Projekt erfolgreich eingelesen · eingebettete Einstellungen werden verwendet')
        self.set_analysis_state('ready')
        self.notice_label.setText('Die Verarbeitung verwendet eine unveränderte Eingangskopie. Originaldatei und Slicerprofile bleiben erhalten.')
        self.notice_label.show()
        self.notice_widget.show()
        self._reserve_loaded_content_height()

    def show_problem(self, message, problem):
        from cooling_tower.native_project.context import ProjectProblem
        self.set_status('Projekt konnte nicht vollständig eingelesen werden')
        self.set_analysis_state('rejected')
        self.notice_label.setText(message)
        self.notice_label.show()
        self.notice_widget.show()
        self.guide_label.setVisible(problem is ProjectProblem.INCOMPLETE)
        self.open_button.hide()
        self._reserve_loaded_content_height()

    def _apply_display_state(self,state):
        self._apply_native_display_state(state)
        if hasattr(self,'open_button'):
            self.open_button.setVisible(state=='ready')
            if state=='ready':
                self.actions_layout.addWidget(self.open_button,1,0,1,3)
            if state!='empty':
                self._reserve_loaded_content_height()

    def clear_file(self):
        self._clear_native_file()
        self.notice_label.hide()
        self.guide_label.hide()
        self.notice_widget.hide()
        for caption,value in self.project_fields.values():
            caption.hide(); value.hide()


def _format_size(size_bytes: int) -> str:
    value = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024.0 or unit == "GB":
            decimals = 0 if unit == "B" else 1
            return f"{value:.{decimals}f} {unit}"
        value /= 1024.0
    return f"{size_bytes} B"
