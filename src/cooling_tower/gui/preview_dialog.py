from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from cooling_tower.gui.widgets import PreviewCanvas
from cooling_tower.gui.user_messages import german_user_message
from cooling_tower.preview import PreviewResult, PreviewState


class PreviewDialog(QDialog):
    update_requested = Signal()
    export_requested = Signal()
    closed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("previewDialog")
        self.setWindowTitle("Objekt- und Kühlturmvorschau")
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.resize(920, 720)
        self.state = PreviewState.EMPTY

        layout = QVBoxLayout(self)
        self.state_label = QLabel("Vorschau wurde noch nicht erstellt.")
        self.state_label.setObjectName("previewStateLabel")
        self.state_label.setWordWrap(True)
        layout.addWidget(self.state_label)
        self.canvas = PreviewCanvas()
        layout.addWidget(self.canvas, 1)

        legend_layout = QHBoxLayout()
        legend_title = QLabel("Farben:")
        legend_title.setObjectName("previewLegendTitle")
        legend_layout.addWidget(legend_title)
        self.object_legend = QLabel("■ Objekt")
        self.object_legend.setObjectName("objectLegend")
        self.object_legend.setStyleSheet(f"color: {PreviewCanvas.OBJECT_COLOR};")
        self.tower_legend = QLabel("■ Kühlturm")
        self.tower_legend.setObjectName("towerLegend")
        self.tower_legend.setStyleSheet(f"color: {PreviewCanvas.TOWER_COLOR};")
        self.bed_legend = QLabel("■ Druckplatte")
        self.bed_legend.setObjectName("bedLegend")
        self.bed_legend.setStyleSheet(f"color: {PreviewCanvas.BED_COLOR};")
        legend_layout.addWidget(self.object_legend)
        legend_layout.addWidget(self.tower_legend)
        legend_layout.addWidget(self.bed_legend)
        legend_layout.addStretch(1)
        layout.addLayout(legend_layout)

        camera_layout = QGridLayout()
        self.reset_camera_button = QPushButton("Standardansicht")
        self.fit_objects_button = QPushButton("Objekt und Kühlturm einpassen")
        self.fit_button = QPushButton("Gesamte Druckplatte anzeigen")
        self.front_button = QPushButton("Vorderansicht")
        self.side_button = QPushButton("Seitenansicht")
        self.top_button = QPushButton("Draufsicht")
        self.reset_camera_button.clicked.connect(self.canvas.reset_camera)
        self.fit_objects_button.clicked.connect(self.canvas.fit_objects)
        self.fit_button.clicked.connect(self.canvas.fit_scene)
        self.front_button.clicked.connect(self.canvas.front_view)
        self.side_button.clicked.connect(self.canvas.side_view)
        self.top_button.clicked.connect(self.canvas.top_view)
        for index, button in enumerate((
            self.reset_camera_button,
            self.fit_objects_button,
            self.fit_button,
            self.front_button,
            self.side_button,
            self.top_button,
        )):
            button.setSizePolicy(
                QSizePolicy.Policy.Ignored,
                QSizePolicy.Policy.Fixed,
            )
            button.setToolTip(button.text())
            camera_layout.addWidget(button, index // 3, index % 3)
        for column in range(3):
            camera_layout.setColumnStretch(column, 1)
        camera_layout.setColumnStretch(3, 1)
        layout.addLayout(camera_layout)
        navigation_hint = QLabel(
            "Maussteuerung: links ziehen zum Drehen · rechts ziehen zum Verschieben · "
            "Mausrad zum Zoomen"
        )
        navigation_hint.setObjectName("helpText")
        navigation_hint.setWordWrap(True)
        layout.addWidget(navigation_hint)

        self.details_label = QLabel()
        self.details_label.setObjectName("previewDetailsLabel")
        self.details_label.setWordWrap(True)
        layout.addWidget(self.details_label)
        self.progress = QProgressBar()
        self.progress.setObjectName("previewProgressBar")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("%p %")
        self.progress.hide()
        layout.addWidget(self.progress)
        self.progress_status_label = QLabel()
        self.progress_status_label.setObjectName("previewProgressStatusLabel")
        self.progress_status_label.setWordWrap(True)
        self.progress_status_icon = QLabel("⏳")
        self.progress_status_icon.setObjectName("progressStatusIcon")
        progress_status_layout = QHBoxLayout()
        progress_status_layout.setContentsMargins(0, 0, 0, 0)
        progress_status_layout.addWidget(
            self.progress_status_icon,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )
        progress_status_layout.addWidget(
            self.progress_status_label,
            1,
            Qt.AlignmentFlag.AlignVCenter,
        )
        self.progress_status_widget = QWidget()
        self.progress_status_widget.setLayout(progress_status_layout)
        self.progress_status_widget.hide()
        layout.addWidget(self.progress_status_widget)

        action_layout = QHBoxLayout()
        action_layout.addStretch(1)
        self.update_button = QPushButton("Vorschau erstellen")
        self.update_button.setObjectName("previewUpdateButton")
        self.update_button.clicked.connect(self.update_requested)
        action_layout.addWidget(self.update_button)
        self.export_button = QPushButton("Kühlturm exportieren")
        self.export_button.setObjectName("primaryButton")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export_requested)
        action_layout.addWidget(self.export_button)
        layout.addLayout(action_layout)

    def set_building(self, status: str) -> None:
        self.state = PreviewState.BUILDING
        self.state_label.setText("⏳ Vorschau wird erstellt …")
        self.state_label.setProperty("state", "building")
        self._refresh_state_style()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.show()
        self.progress_status_label.setText(german_user_message(status))
        self.progress_status_widget.show()
        self.update_button.setText("Vorschau wird erstellt...")
        self.update_button.setEnabled(False)
        self.export_button.setEnabled(False)

    def set_progress(self, percent: int, status: str) -> None:
        self.progress_status_label.setText(german_user_message(status))
        self.progress_status_widget.show()
        self.progress.setRange(0, 100)
        self.progress.setValue(max(0, min(100, percent)))

    def set_preview(self, result: PreviewResult) -> None:
        self.state = PreviewState.CURRENT
        first_scene = self.canvas.scene is None
        self.canvas.set_scene(result.scene)
        if first_scene:
            self.canvas.side_view()
        self.state_label.setText("✓ Vorschau ist aktuell")
        self.state_label.setProperty("state", "current")
        self._refresh_state_style()
        calibration = (
            "Slicer-gestützte Schätzung"
            if result.calibrated or result.slicer_optimized
            else "analytischer STL-Fallback"
        )
        self.details_label.setText(
            f"Ausgabe: {result.output_mode.value.upper()} · {calibration} · "
            f"Turmhöhe: {result.scene.tower_height_mm:.2f} mm"
        )
        self.progress.hide()
        self.progress_status_widget.hide()
        self.update_button.setText("Vorschau aktualisieren")
        self.update_button.setEnabled(True)
        self.export_button.setEnabled(True)

    def mark_stale(self) -> None:
        if self.canvas.scene is None:
            self.state = PreviewState.EMPTY
            self.state_label.setText("Vorschau wurde noch nicht erstellt.")
            self.state_label.setProperty("state", "empty")
            self.update_button.setText("Vorschau erstellen")
        else:
            self.state = PreviewState.STALE
            self.state_label.setText(
                "⚠ Vorschau nicht mehr aktuell"
            )
            self.state_label.setProperty("state", "stale")
            self.update_button.setText("Vorschau aktualisieren")
        self._refresh_state_style()
        self.progress.hide()
        self.progress_status_widget.hide()
        self.update_button.setEnabled(True)
        self.export_button.setEnabled(self.canvas.scene is not None)

    def set_failed(self, message: str) -> None:
        self.state = PreviewState.FAILED
        self.state_label.setText(
            f"✕ Vorschau fehlgeschlagen: {german_user_message(message)}"
        )
        self.state_label.setProperty("state", "error")
        self._refresh_state_style()
        self.progress.hide()
        self.progress_status_widget.hide()
        self.update_button.setText(
            "Vorschau aktualisieren"
            if self.canvas.scene is not None
            else "Vorschau erneut erstellen"
        )
        self.update_button.setEnabled(True)
        self.export_button.setEnabled(self.canvas.scene is not None)

    def set_export_enabled(self, enabled: bool, reason: str | None = None) -> None:
        self.export_button.setEnabled(enabled)
        self.export_button.setToolTip("" if enabled else (reason or "Export derzeit nicht möglich."))

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self.closed.emit()
        super().closeEvent(event)

    def _refresh_state_style(self) -> None:
        style = self.state_label.style()
        style.unpolish(self.state_label)
        style.polish(self.state_label)
