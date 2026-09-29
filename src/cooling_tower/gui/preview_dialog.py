from __future__ import annotations

from collections import Counter
import math

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
from cooling_tower.preview import PreviewResult, PreviewScene, PreviewState


class PreviewDialog(QDialog):
    closed = Signal()
    layout_changed = Signal()

    def __init__(self, parent=None, *, embedded: bool = False) -> None:
        super().__init__(parent)
        self.embedded = bool(embedded)
        self.setObjectName("embeddedPreviewPanel" if embedded else "previewDialog")
        if embedded:
            # A QDialog with widget flags participates in the parent layout and
            # can never become a separate top-level preview window.
            self.setWindowFlags(Qt.WindowType.Widget)
            self.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Preferred,
            )
        else:
            self.setWindowTitle("Objekt- und Kühlturmvorschau")
            self.setWindowModality(Qt.WindowModality.NonModal)
            self.resize(920, 720)
        self.state = PreviewState.EMPTY
        self._scene_before_build: PreviewScene | None = None
        self._intermediate_scene_active = False

        layout = QVBoxLayout(self)
        if embedded:
            # The surrounding Prognose card already provides its inner inset.
            # A zero-margin panel therefore reaches that inset on both sides
            # without introducing a second, visually uneven padding layer.
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        if embedded:
            section_title = QLabel("3D-Vorschau")
            section_title.setObjectName("embeddedPreviewTitle")
            self.preview_title_widget = QWidget(self)
            self.preview_title_widget.setObjectName("embeddedPreviewTitleRow")
            self.preview_title_widget.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )
            title_row = QHBoxLayout(self.preview_title_widget)
            title_row.setContentsMargins(0, 0, 0, 0)
            title_row.addWidget(section_title)
            layout.addWidget(self.preview_title_widget)
        self.state_label = QLabel("Vorschau wurde noch nicht erstellt.")
        self.state_label.setObjectName("previewStateLabel")
        self.state_label.setWordWrap(True)
        if embedded:
            title_row.addWidget(self.state_label)
            title_row.addStretch()
        else:
            layout.addWidget(self.state_label)
        if embedded:
            # The empty canvas already carries the initial explanatory text.
            # Avoid repeating the same information directly above it.
            self.state_label.hide()
        self.canvas = PreviewCanvas()
        if embedded:
            self.canvas.setMinimumWidth(0)
            self.canvas.setFixedHeight(420)
            self.canvas.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )

        self.preview_frame = QWidget()
        self.preview_frame.setObjectName("previewFrame")
        if embedded:
            # Header, canvas and legend have deterministic heights. Keeping
            # their host fixed prevents a transient parent relayout from
            # assigning surplus height below the legend while an intermediate
            # joint-slice scene replaces the previous one.
            self.preview_frame.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )
        preview_frame_layout = QVBoxLayout(self.preview_frame)
        preview_frame_layout.setContentsMargins(0, 0, 0, 0)
        preview_frame_layout.setSpacing(0)

        self.preview_info_header = QWidget()
        self.preview_info_header.setObjectName("previewInfoHeader")
        preview_info_layout = QGridLayout(self.preview_info_header)
        preview_info_layout.setContentsMargins(12, 7, 12, 7)
        preview_info_layout.setHorizontalSpacing(18)
        preview_info_layout.setVerticalSpacing(4)
        self.segments_info_label = self._preview_info_label(
            "previewSegmentsInfo"
        )
        self.height_info_label = self._preview_info_label(
            "previewHeightInfo"
        )
        self.tower_circle_segments_info_label = self._preview_info_label(
            "previewTowerCircleSegmentsInfo"
        )
        self.layers_info_label = self._preview_info_label(
            "previewLayersInfo"
        )
        self.bed_info_label = self._preview_info_label("previewBedInfo")
        preview_info_layout.addWidget(self.segments_info_label, 0, 0)
        preview_info_layout.addWidget(self.height_info_label, 0, 1)
        preview_info_layout.addWidget(self.layers_info_label, 1, 0)
        preview_info_layout.addWidget(self.bed_info_label, 1, 1)
        previous_header_height = self.preview_info_header.sizeHint().height()
        preview_info_layout.removeWidget(self.height_info_label)
        preview_info_layout.removeWidget(self.bed_info_label)
        # Three compact right-side lines fit into the old two-line header.
        # The canvas keeps its position; navigation overlays its top edge.
        preview_info_layout.setContentsMargins(12, 1, 12, 1)
        preview_info_layout.setVerticalSpacing(0)
        preview_info_layout.addWidget(self.tower_circle_segments_info_label, 0, 1)
        preview_info_layout.addWidget(self.height_info_label, 1, 1)
        preview_info_layout.addWidget(self.bed_info_label, 2, 1)
        self.preview_info_header.setFixedHeight(previous_header_height)
        preview_info_layout.setColumnStretch(0, 1)
        preview_info_layout.setColumnStretch(1, 0)
        preview_frame_layout.addWidget(self.preview_info_header)
        preview_frame_layout.addWidget(self.canvas, 1)
        self.canvas.set_navigation_overlay_parent(
            self.preview_frame,
            upward_offset=self.layers_info_label.fontMetrics().lineSpacing(),
        )

        self.legend_widget = QWidget()
        self.legend_widget.setObjectName("previewLegendBar")
        legend_layout = QHBoxLayout()
        legend_layout.setContentsMargins(12, 7, 12, 7)
        legend_layout.setSpacing(6)
        self.legend_widget.setLayout(legend_layout)
        self.legend_title = QLabel("Legende:")
        self.legend_title.setObjectName("previewLegendTitle")
        legend_layout.addWidget(self.legend_title)
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
        preview_frame_layout.addWidget(self.legend_widget)

        camera_layout = QHBoxLayout()
        camera_layout.setContentsMargins(0, 0, 0, 0)
        camera_layout.setSpacing(6)
        self.three_quarter_button = QPushButton("3/4-Ansicht")
        self.front_button = QPushButton("Vorderansicht")
        self.side_button = QPushButton("Seitenansicht")
        self.top_button = QPushButton("Draufsicht")
        self.three_quarter_button.clicked.connect(
            self.canvas.three_quarter_view
        )
        self.front_button.clicked.connect(self.canvas.front_view)
        self.side_button.clicked.connect(self.canvas.side_view)
        self.top_button.clicked.connect(self.canvas.top_view)
        for button in (
            self.three_quarter_button,
            self.front_button,
            self.side_button,
            self.top_button,
        ):
            button.setObjectName("previewCameraButton")
            font = button.font()
            font.setPointSizeF(10.5)
            button.setFont(font)
            button.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )
            button.setMinimumWidth(
                button.fontMetrics().horizontalAdvance(button.text()) + 18
            )
            button.setToolTip(button.text())
            camera_layout.addWidget(button, 1)
        layout.addLayout(camera_layout)
        # The embedded frame has a deterministic height. Giving its layout
        # cell vertical stretch would let transient surplus space shift the
        # frame (or previously enlarge it) during scene replacement.
        layout.addWidget(self.preview_frame, 0 if embedded else 1)
        self.navigation_hint = QLabel(
            "Interaktive Maussteuerung über die Schaltfläche oben links in der "
            "Vorschau aktivieren."
        )
        self.navigation_hint.setObjectName("helpText")
        self.navigation_hint.setWordWrap(True)
        layout.addWidget(self.navigation_hint)

        self.details_label = QLabel()
        self.details_label.setObjectName("previewDetailsLabel")
        self.details_label.setWordWrap(True)
        layout.addWidget(self.details_label)
        self.details_label.setVisible(not embedded)

        self.quality_widget = QWidget()
        self.quality_widget.setObjectName("predictionQualityPanel")
        quality_layout = QVBoxLayout(self.quality_widget)
        quality_layout.setContentsMargins(0, 0, 0, 0)
        quality_layout.setSpacing(3)
        self.quality_label = QLabel()
        self.quality_label.setObjectName("previewQualityLabel")
        self.quality_label.setWordWrap(True)
        self.quality_label.setMaximumHeight(260)
        self.quality_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Maximum,
        )
        self.quality_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.quality_label.hide()
        self._last_quality_text = ""
        self._last_quality_state = "neutral"
        quality_layout.addWidget(self.quality_label)
        self.quality_details_toggle = QPushButton(
            "Prüfdetails anzeigen ▸"
        )
        self.quality_details_toggle.setObjectName(
            "previewQualityDetailsToggle"
        )
        self.quality_details_toggle.setCheckable(True)
        self.quality_details_toggle.setFlat(True)
        self.quality_details_toggle.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.quality_details_toggle.toggled.connect(
            self._toggle_quality_details
        )
        self.quality_details_toggle.hide()
        quality_layout.addWidget(self.quality_details_toggle)
        self.quality_details_label = QLabel()
        self.quality_details_label.setObjectName(
            "previewQualityDetailsLabel"
        )
        self.quality_details_label.setWordWrap(True)
        self.quality_details_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.quality_details_label.hide()
        quality_layout.addWidget(self.quality_details_label)
        if not embedded:
            layout.addWidget(self.quality_widget)
        self.progress = QProgressBar()
        self.progress.setObjectName("previewProgressBar")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("%p %")
        self.progress.hide()
        if not embedded:
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
        if not embedded:
            layout.addWidget(self.progress_status_widget)

        self._preview_only_controls = (
            self.preview_info_header,
            self.legend_widget,
            self.three_quarter_button,
            self.front_button,
            self.side_button,
            self.top_button,
            self.navigation_hint,
            self.details_label,
        )
        self._preview_controls_visible = True
        self._set_preview_controls_visible(False)

    @staticmethod
    def _preview_info_label(object_name: str) -> QLabel:
        label = QLabel()
        label.setObjectName(object_name)
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        return label

    def set_building(self, status: str) -> None:
        if self.state is PreviewState.BUILDING:
            self._restore_scene_before_build()
        self._scene_before_build = self.canvas.scene
        self._intermediate_scene_active = False
        self.state = PreviewState.BUILDING
        self.canvas.set_navigation_enabled(False)
        retained_scene = self.canvas.scene is not None
        retained_tower = bool(retained_scene and self.canvas.scene.tower_segments)
        self.state_label.setText(
            "⚠ Bisherige Vorschau veraltet – neue Vorschau wird erstellt …"
            if retained_tower else "⏳ Vorschau wird erstellt …"
        )
        self.state_label.setProperty("state", "stale" if retained_tower else "building")
        self.state_label.setVisible(not self.embedded or self.canvas.scene is not None)
        self._refresh_state_style()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(not self.embedded)
        self.progress_status_label.setText(german_user_message(status))
        self.progress_status_widget.setVisible(not self.embedded)
        self._set_quality_text(
            "Prüfstatus der Prognose\n"
            "… Wird mit der neuen Vorschau aktualisiert.",
            "building",
        )
        self._set_quality_details("")
        self._set_preview_controls_visible(self.canvas.scene is not None)

    def set_intermediate_scene(self, scene: PreviewScene) -> None:
        """Show the latest measured tower shape without granting result controls."""

        if self.state is not PreviewState.BUILDING:
            return
        self._intermediate_scene_active = True
        self.canvas.set_scene(scene)
        self.tower_legend.setVisible(bool(scene.tower_segments))
        self.canvas.side_view()
        bed = scene.bed_bounds
        self._set_scene_information(
            scene,
            bed_width_mm=bed.maximum_x_mm - bed.minimum_x_mm,
            bed_depth_mm=bed.maximum_y_mm - bed.minimum_y_mm,
        )
        self._set_preview_controls_visible(True)

    def set_original_object(self, scene: PreviewScene) -> None:
        """Display the analyzed source without presenting it as a tower result."""
        self._intermediate_scene_active = False
        self._scene_before_build = None
        self.state = PreviewState.EMPTY
        self.canvas.set_scene(scene)
        self.canvas.three_quarter_view()
        self.state_label.setText("Originalobjekt aus dem Pre-Slice · noch kein Kühlturm")
        self.state_label.setProperty("state", "empty")
        self.state_label.show()
        self._refresh_state_style()
        self._set_scene_information(
            scene,
            bed_width_mm=scene.bed_bounds.maximum_x_mm - scene.bed_bounds.minimum_x_mm,
            bed_depth_mm=scene.bed_bounds.maximum_y_mm - scene.bed_bounds.minimum_y_mm,
        )
        self.tower_legend.hide()
        self.progress.hide()
        self.progress_status_widget.hide()
        self._set_preview_controls_visible(True)

    def _restore_scene_before_build(self) -> None:
        if self._intermediate_scene_active:
            self.canvas.set_scene(self._scene_before_build)
            self.tower_legend.setVisible(bool(
                self._scene_before_build is not None
                and self._scene_before_build.tower_segments
            ))
            if self._scene_before_build is not None:
                bed = self._scene_before_build.bed_bounds
                self._set_scene_information(
                    self._scene_before_build,
                    bed_width_mm=bed.maximum_x_mm - bed.minimum_x_mm,
                    bed_depth_mm=bed.maximum_y_mm - bed.minimum_y_mm,
                )
        self._intermediate_scene_active = False
        self._scene_before_build = None

    def set_progress(self, percent: int, status: str) -> None:
        self.progress_status_label.setText(german_user_message(status))
        self.progress_status_widget.setVisible(not self.embedded)
        self.progress.setRange(0, 100)
        self.progress.setValue(max(0, min(100, percent)))

    def set_preview(self, result: PreviewResult) -> None:
        self._intermediate_scene_active = False
        self._scene_before_build = None
        self.state = PreviewState.CURRENT
        # The first completed joint slice already selected the side view.
        # Completing, accepting, exporting or resuming a result must not
        # replace the user's current camera choice.
        self.canvas.set_scene(result.scene, preserve_view=True)
        self.tower_legend.show()
        self.state_label.setText("✓ Vorschau ist aktuell")
        self.state_label.setProperty("state", "current")
        self.state_label.show()
        self._refresh_state_style()
        calibration = "Slicer-gestützte Schätzung"
        bed = result.scene.bed_bounds
        bed_width_mm = bed.maximum_x_mm - bed.minimum_x_mm
        bed_depth_mm = bed.maximum_y_mm - bed.minimum_y_mm
        self.bed_legend.setText("■ Druckplatte")
        self._set_scene_information(
            result.scene,
            bed_width_mm=bed_width_mm,
            bed_depth_mm=bed_depth_mm,
        )
        if not self.embedded:
            self.details_label.setText(
                f"Ausgabe: {result.output_mode.value.upper()} · {calibration} · "
                f"Turmhöhe: {result.scene.tower_height_mm:.2f} mm"
            )
        quality_text, quality_state = self._quality_summary(
            result,
            compact=self.embedded,
        )
        self._last_quality_text = quality_text
        self._last_quality_state = quality_state
        self._set_quality_text(quality_text, quality_state)
        self._set_quality_details(self._last_iteration_summary(result))
        self.progress.hide()
        self.progress_status_widget.hide()
        self._set_preview_controls_visible(True)

    @staticmethod
    def _format_dimension(value_mm: float) -> str:
        """Format a bed dimension compactly with the German decimal mark."""

        return f"{value_mm:.2f}".rstrip("0").rstrip(".").replace(".", ",")

    @staticmethod
    def _segment_height(segments: object) -> float:
        z_values = tuple(
            point.z
            for segment in tuple(segments or ())
            for point in (segment.start, segment.end)
        )
        return max(z_values) - min(z_values) if z_values else 0.0

    @staticmethod
    def _segment_layer_count(segments: object) -> int:
        return len(
            {
                round(point.z, 6)
                for segment in tuple(segments or ())
                for point in (segment.start, segment.end)
                if point.z > 0.0
            }
        )

    @staticmethod
    def _format_count(value: int) -> str:
        return f"{max(0, int(value)):,}".replace(",", ".")

    @staticmethod
    def _colored_value(value: str, color: str) -> str:
        return f'<span style="color:{color};">{value}</span>'

    def _set_scene_information(
        self,
        scene: object,
        *,
        bed_width_mm: float,
        bed_depth_mm: float,
    ) -> None:
        object_segments = tuple(getattr(scene, "object_segments", ()) or ())
        tower_segments = tuple(getattr(scene, "tower_segments", ()) or ())
        object_height = getattr(scene, "object_height_mm", None)
        if object_height is None:
            object_height = self._segment_height(object_segments)
        object_layers = getattr(scene, "object_layer_count", None)
        if object_layers is None:
            object_layers = self._segment_layer_count(object_segments)
        tower_layers = getattr(scene, "tower_layer_count", None)
        if tower_layers is None:
            tower_layers = self._segment_layer_count(tower_segments)

        object_color = PreviewCanvas.OBJECT_COLOR
        tower_color = PreviewCanvas.TOWER_COLOR
        bed_color = PreviewCanvas.BED_COLOR
        self.segments_info_label.setText(
            "Segmente: "
            + self._colored_value(
                self._format_count(
                    getattr(scene, "source_segment_count", len(object_segments))
                ),
                object_color,
            )
            + " / "
            + self._colored_value(
                self._format_count(len(tower_segments)), tower_color
            )
        )
        circle_segments = getattr(scene, "tower_circle_segments", None)
        self.tower_circle_segments_info_label.setText(
            "Turm-Kreissegmente: "
            + self._colored_value(
                self._format_count(int(circle_segments))
                if circle_segments is not None else "–",
                tower_color,
            )
        )
        self.height_info_label.setText(
            "Höhe: "
            + self._colored_value(
                f"{self._format_dimension(float(object_height))} mm",
                object_color,
            )
            + " / "
            + self._colored_value(
                f"{self._format_dimension(float(scene.tower_height_mm))} mm",
                tower_color,
            )
        )
        self.layers_info_label.setText(
            "Layer: "
            + self._colored_value(
                self._format_count(int(object_layers)), object_color
            )
            + " / "
            + self._colored_value(
                self._format_count(int(tower_layers)), tower_color
            )
        )
        self.bed_info_label.setText(
            "Druckplatte: "
            + self._colored_value(
                f"{self._format_dimension(bed_width_mm)} x "
                f"{self._format_dimension(bed_depth_mm)} mm",
                bed_color,
            )
        )

    def mark_stale(self) -> None:
        if self.state is PreviewState.BUILDING:
            self._restore_scene_before_build()
        if self.canvas.scene is None:
            self.state = PreviewState.EMPTY
            self.state_label.setText("Vorschau wurde noch nicht erstellt.")
            self.state_label.setProperty("state", "empty")
            self.state_label.setVisible(not self.embedded)
        elif not self.canvas.scene.tower_segments:
            self.state = PreviewState.EMPTY
            self.state_label.setText("Originalobjekt aus dem Pre-Slice · noch kein Kühlturm")
            self.state_label.setProperty("state", "empty")
            self.state_label.setVisible(not self.embedded)
        else:
            self.state = PreviewState.STALE
            self.state_label.setText(
                "⚠ Vorschau veraltet – Einstellungen geändert; vor dem "
                "Export aktualisieren."
            )
            self.state_label.setProperty("state", "stale")
            self.state_label.show()
        self._refresh_state_style()
        self.progress.hide()
        self.progress_status_widget.hide()
        self._set_preview_controls_visible(self.canvas.scene is not None)

    def mark_current(self) -> None:
        """Revalidate the retained scene after restoring its exact request."""

        if self.canvas.scene is None:
            self.mark_stale()
            return
        self.state = PreviewState.CURRENT
        self.state_label.setText("✓ Vorschau ist aktuell")
        self.state_label.setProperty("state", "current")
        self.state_label.show()
        if self._last_quality_text:
            self._set_quality_text(
                self._last_quality_text,
                self._last_quality_state,
            )
        self._refresh_state_style()
        self.progress.hide()
        self.progress_status_widget.hide()
        self._set_preview_controls_visible(True)

    def set_failed(self, message: str) -> None:
        self._restore_scene_before_build()
        self.state = PreviewState.FAILED
        self.state_label.setText(
            f"✕ Vorschau fehlgeschlagen: {german_user_message(message)}"
        )
        self.state_label.setProperty("state", "error")
        self.state_label.show()
        self._refresh_state_style()
        if self.canvas.scene is None:
            self._last_quality_text = ""
            self._last_quality_state = "neutral"
        self._set_quality_details("")
        self._set_quality_text(
            "Prüfstatus der Prognose\n"
            "✕ Keine aktuelle Prüfung verfügbar, da die Vorschau nicht "
            "erstellt werden konnte.",
            "error",
        )
        self.progress.hide()
        self.progress_status_widget.hide()
        self._set_preview_controls_visible(self.canvas.scene is not None)

    def set_cancelled(self) -> None:
        self._restore_scene_before_build()
        self.canvas.set_scene(None)
        self._last_quality_text = ""
        self._last_quality_state = "neutral"
        self._set_quality_details("")
        self._set_quality_text("Prüfstatus der Prognose\nKeine aktuelle Vorschau.", "neutral")
        self.state = PreviewState.EMPTY
        self.state_label.setText("Generierung abgebrochen. Kein Kühlturm vorhanden.")
        self.state_label.setProperty("state", "empty")
        self.state_label.show()
        self._refresh_state_style()
        self.progress.hide()
        self.progress_status_widget.hide()
        self._set_preview_controls_visible(False)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self.closed.emit()
        super().closeEvent(event)

    def _refresh_state_style(self) -> None:
        if self.embedded:
            full_text = self.state_label.text()
            self.state_label.setToolTip(full_text)
            retained_tower = bool(
                self._scene_before_build is not None
                and self._scene_before_build.tower_segments
            )
            captions = {PreviewState.CURRENT: "✓ Aktuell", PreviewState.STALE: "⚠ Veraltet", PreviewState.BUILDING: "⚠ Veraltet" if retained_tower else "◷ Wird erstellt", PreviewState.FAILED: "✕ Fehlgeschlagen", PreviewState.EMPTY: ""}
            self.state_label.setText(captions.get(self.state, full_text))
            self.state_label.setVisible(
                self.state not in {PreviewState.EMPTY, PreviewState.FAILED}
            )
        style = self.state_label.style()
        style.unpolish(self.state_label)
        style.polish(self.state_label)
        self.state_label.updateGeometry()
        if self.embedded:
            own_layout = self.layout()
            if own_layout is not None:
                own_layout.invalidate()
                own_layout.activate()

    def _set_preview_controls_visible(self, visible: bool) -> None:
        """Keep camera buttons visible but locked while a scene is building."""

        visible = bool(visible)
        building = self.state is PreviewState.BUILDING
        changed = (
            visible != self._preview_controls_visible
            or building != getattr(self, "_preview_controls_building", False)
        )
        self._preview_controls_visible = visible
        self._preview_controls_building = building
        for widget in self._preview_only_controls:
            widget.setVisible(visible)
        camera_buttons = (
            self.three_quarter_button,
            self.front_button,
            self.side_button,
            self.top_button,
        )
        for button in camera_buttons:
            button.setVisible(visible or building)
            button.setEnabled(visible and not building)
        interactive = visible and not building
        self.canvas.navigation_toggle.setVisible(interactive)
        self.canvas.navigation_status_label.setVisible(interactive)
        self.navigation_hint.setVisible(interactive)
        if self.embedded:
            frame_height = self.canvas.minimumHeight()
            if visible:
                frame_height += (
                    # The header is intentionally fixed to its original
                    # three-row height. Rich-text width changes may alter its
                    # size hint, but must not move the canvas during refresh.
                    self.preview_info_header.minimumHeight()
                    + self.legend_widget.sizeHint().height()
                )
            self.preview_frame.setFixedHeight(frame_height + 2)
        if visible:
            self.details_label.setVisible(not self.embedded)
            self.quality_label.setVisible(bool(self.quality_label.text().strip()))
            has_details = bool(self.quality_details_label.text().strip())
            self.quality_details_toggle.setVisible(has_details)
            self.quality_details_label.setVisible(
                has_details and self.quality_details_toggle.isChecked()
            )
        if self.embedded:
            # During generation a scene update and its slice result arrive in
            # the same event-loop turn. Do not let the parent card stretch this
            # panel to a stale height before its own layout catches up.
            old_minimum_height = self.minimumHeight()
            old_maximum_height = self.maximumHeight()
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
            own_layout = self.layout()
            if own_layout is not None:
                own_layout.invalidate()
                own_layout.activate()
            if building:
                self.setFixedHeight(self.sizeHint().height())
            changed = changed or (
                self.minimumHeight() != old_minimum_height
                or self.maximumHeight() != old_maximum_height
            )
        if changed:
            own_layout = self.layout()
            if own_layout is not None:
                own_layout.invalidate()
                own_layout.activate()
            self.updateGeometry()
            parent = self.parentWidget()
            if parent is not None:
                parent.updateGeometry()
            self.layout_changed.emit()

    def _set_quality_text(self, text: str, state: str) -> None:
        self.quality_label.setText(text)
        self.quality_label.setProperty("state", state)
        style = self.quality_label.style()
        style.unpolish(self.quality_label)
        style.polish(self.quality_label)
        self.quality_label.show()

    def _set_quality_details(self, text: str) -> None:
        text = text.strip()
        self.quality_details_toggle.setChecked(False)
        self.quality_details_label.setText(text)
        self.quality_details_label.hide()
        self.quality_details_toggle.setVisible(bool(text))

    def _toggle_quality_details(self, expanded: bool) -> None:
        self.quality_details_toggle.setText(
            "Prüfdetails ausblenden ▾"
            if expanded
            else "Prüfdetails anzeigen ▸"
        )
        self.quality_details_label.setVisible(
            expanded and bool(self.quality_details_label.text().strip())
        )

    @staticmethod
    def _quality_summary(
        result: PreviewResult,
        *,
        compact: bool = False,
    ) -> tuple[str, str]:
        calibration = getattr(result, "calibration", None)
        if calibration is None:
            return (
                "Prüfstatus der Prognose\n"
                "— Noch keine slicergestützte Prüfung verfügbar.",
                "neutral",
            )

        configured_iterations = max(
            0,
            int(getattr(calibration, "configured_iteration_count", 0) or 0),
        )
        iterations = tuple(getattr(calibration, "iterations", ()) or ())
        calibrated = bool(getattr(result, "calibrated", False))
        joint_sliced = bool(getattr(result, "joint_sliced", False))
        if joint_sliced:
            joint_iterations = tuple(
                item
                for item in iterations
                if bool(getattr(item, "joint_slice", False))
            )
            completed = max(
                len(joint_iterations),
                int(
                    getattr(result, "completed_joint_slice_count", 0)
                    or 0
                ),
            )
            configured = max(
                completed,
                int(
                    getattr(result, "configured_joint_slice_count", 0)
                    or 0
                ),
            )
            run_count_label = (
                f"Gemeinsame Slices: {completed} von maximal {configured}"
            )
        else:
            completed = len(iterations)
            configured = configured_iterations
            run_count_label = (
                f"Prüfdurchläufe: {completed} von maximal {configured}"
            )
        slicer_optimized = bool(getattr(result, "slicer_optimized", False))
        time_tolerance = float(
            getattr(result, "calibration_time_tolerance_s", 0.2)
        )
        target_time = getattr(result, "target_layer_time_s", None)
        minimum_time = getattr(result, "minimum_verified_layer_time_s", None)
        difference = (
            float(minimum_time) - float(target_time)
            if PreviewDialog._is_finite(target_time)
            and PreviewDialog._is_finite(minimum_time)
            else None
        )
        target_time_confirmed = bool(
            difference is not None
            and abs(difference) <= time_tolerance
        )
        if target_time_confirmed and calibrated:
            headline = (
                "✓ Prognose bestätigt: Die Mindest-Layerzeit liegt innerhalb "
                "der zulässigen Abweichung."
                if compact
                else (
                    "✓ Prognose bestätigt: Mindest-Layerzeit innerhalb der "
                    "zulässigen Abweichung "
                    f"(Abweichung: {difference:+.3f} s; zulässig: "
                    f"±{time_tolerance:.3f} s)"
                )
            )
            state = "success"
        elif target_time_confirmed:
            headline = (
                "⚠ Mindest-Layerzeit erreicht, aber die Prognose ist noch "
                "nicht stabil bestätigt."
            )
            state = "warning"
        elif calibrated and configured == 1:
            headline = (
                "✓ Prognose bestätigt: Der einzelne Prüfdurchlauf war "
                "erfolgreich."
            )
            state = "success"
        elif calibrated:
            headline = (
                "✓ Prognose bestätigt: Die Prüfdurchläufe liefern ein "
                "stabiles Ergebnis."
            )
            state = "success"
        elif slicer_optimized:
            headline = (
                "⚠ Prognose noch nicht bestätigt: Der beste geprüfte "
                "Zwischenstand wird angezeigt."
            )
            state = "warning"
        else:
            headline = "✕ Die Prognose konnte nicht bestätigt werden."
            state = "error"

        lines = [
            "Prüfstatus der Prognose",
            headline,
            run_count_label,
        ]
        if difference is not None and not compact:
            relation = (
                "innerhalb der Toleranz"
                if abs(difference) <= time_tolerance
                else f"um {abs(difference) - time_tolerance:.3f} s außerhalb der Toleranz"
            )
            lines.append(
                (
                    "Kleinste gemessene Layerzeit des getrennt "
                    "geslicten Kandidaten: "
                    if not joint_sliced
                    else "Kleinste geprüfte Layerzeit des gemeinsam "
                    "geslicten Kandidaten: "
                )
                +
                f"{float(minimum_time):.3f} s bei {float(target_time):.3f} s "
                f"Ziel ({difference:+.3f} s; {relation})"
            )

        return "\n".join(lines), state

    @staticmethod
    def _last_iteration_summary(result: PreviewResult) -> str:
        """Return only unresolved findings from the current verification."""

        calibration = getattr(result, "calibration", None)
        iterations = tuple(
            getattr(calibration, "iterations", ()) or ()
            if calibration is not None
            else ()
        )
        if not iterations:
            return ""
        last = iterations[-1]
        time_tolerance = float(
            getattr(result, "calibration_time_tolerance_s", 0.2)
        )
        slicer_result_tolerance = float(
            getattr(
                result,
                "calibration_slicer_result_tolerance_s",
                0.25,
            )
        )
        profile_tolerance = float(
            getattr(result, "calibration_profile_tolerance_mm", 0.1)
        )
        metadata_tolerance = float(
            getattr(result, "calibration_metadata_tolerance_s", 0.75)
        )
        deficient_count = max(
            0,
            int(getattr(last, "deficient_layer_count", 0) or 0),
        )
        lines: list[str] = []

        def add_exceeded(
            label: str,
            value: object,
            tolerance: float,
            unit: str,
            *,
            suffix: str = "",
            force: bool = False,
        ) -> None:
            if not PreviewDialog._is_finite(value):
                return
            if force or float(value) > tolerance:
                lines.append(
                    PreviewDialog._maximum_value_assessment(
                        label,
                        value,
                        tolerance,
                        unit,
                        suffix=suffix,
                    )
                )

        add_exceeded(
            "Mindest-Layerzeit unterschritten",
            getattr(last, "maximum_remaining_deficit_s", None),
            time_tolerance,
            "s",
            suffix=f"; {deficient_count} betroffene Layer",
            force=deficient_count > 0,
        )
        add_exceeded(
            "Slicer-Ergebnis noch nicht stabil",
            getattr(last, "maximum_slicer_result_change_s", None),
            slicer_result_tolerance,
            "s",
        )
        add_exceeded(
            "Geometrieprofil noch nicht stabil",
            getattr(last, "maximum_profile_change_mm", None),
            profile_tolerance,
            "mm",
        )
        failures = tuple(getattr(calibration, "failures", ()) or ())
        failure_details = (
            PreviewDialog._summarized_failures(failures)
            if not bool(getattr(result, "calibrated", False))
            else ()
        )
        if failure_details:
            lines.append("Offene Prüfgründe:")
            lines.extend(failure_details)
        metadata_difference = getattr(
            getattr(last, "evaluation", None),
            "maximum_metadata_difference_s",
            None,
        )
        add_exceeded(
            "Slicer-Zeitangaben widersprechen sich",
            metadata_difference,
            metadata_tolerance,
            "s",
        )
        joint_deviation = getattr(
            last,
            "maximum_target_deviation_s",
            None,
        )
        add_exceeded(
            "Zielabweichung im gemeinsamen Slice",
            joint_deviation,
            time_tolerance,
            "s",
        )
        return "\n".join(lines)

    @staticmethod
    def _summarized_failures(
        failures: tuple[object, ...],
        *,
        maximum_unique_reasons: int = 3,
        maximum_reason_length: int = 180,
    ) -> tuple[str, ...]:
        """Deduplicate calibration failures into a bounded result summary."""

        messages = tuple(
            " ".join(str(getattr(failure, "message", "")).split())
            for failure in failures
            if str(getattr(failure, "message", "")).strip()
        )
        if not messages:
            return ()
        counts = Counter(messages)
        summarized: list[str] = []
        displayed_occurrences = 0
        for message, count in counts.most_common(maximum_unique_reasons):
            compact = (
                message
                if len(message) <= maximum_reason_length
                else message[: maximum_reason_length - 1].rstrip() + "…"
            )
            occurrence = f" ({count}×)" if count > 1 else ""
            summarized.append(f"Grund{occurrence}: {compact}")
            displayed_occurrences += count
        omitted_unique = max(0, len(counts) - len(summarized))
        omitted_occurrences = max(0, len(messages) - displayed_occurrences)
        if omitted_unique:
            summarized.append(
                f"Weitere {omitted_unique} unterschiedliche Gründe "
                f"({omitted_occurrences} Meldungen) sind im Protokoll gebündelt."
            )
        return tuple(summarized)

    @staticmethod
    def _maximum_value_assessment(
        label: str,
        value: object,
        tolerance: float,
        unit: str,
        *,
        suffix: str = "",
    ) -> str:
        if not PreviewDialog._is_finite(value):
            return f"— {label}: nicht vergleichbar{suffix}"
        numeric = float(value)
        if numeric <= tolerance:
            return (
                f"✓ {label}: {numeric:.3f} {unit} ≤ "
                f"{tolerance:.3f} {unit}{suffix}"
            )
        return (
            f"✕ {label}: {numeric:.3f} {unit} > {tolerance:.3f} {unit} "
            f"(um {numeric - tolerance:.3f} {unit} überschritten){suffix}"
        )

    @staticmethod
    def _is_finite(value: object) -> bool:
        try:
            return math.isfinite(float(value))
        except (TypeError, ValueError):
            return False
