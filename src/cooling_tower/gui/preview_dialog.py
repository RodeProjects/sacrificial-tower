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
        layout.addWidget(self.quality_label)
        self.quality_details_toggle = QPushButton(
            "Messwerte des letzten Durchlaufs anzeigen ▸"
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
        layout.addWidget(self.quality_details_toggle)
        self.quality_details_label = QLabel()
        self.quality_details_label.setObjectName(
            "previewQualityDetailsLabel"
        )
        self.quality_details_label.setWordWrap(True)
        self.quality_details_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.quality_details_label.hide()
        layout.addWidget(self.quality_details_label)
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
        self._set_quality_text(
            "Qualitätsprüfung wird für die neue Vorschau aktualisiert …",
            "building",
        )
        self._set_quality_details("")
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
        self.canvas.set_scene(
            result.scene,
            preserve_view=not first_scene,
        )
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
        bed = result.scene.bed_bounds
        bed_width_mm = bed.maximum_x_mm - bed.minimum_x_mm
        bed_depth_mm = bed.maximum_y_mm - bed.minimum_y_mm
        self.bed_legend.setText(
            "■ Druckplatte "
            f"({self._format_dimension(bed_width_mm)} × "
            f"{self._format_dimension(bed_depth_mm)} mm)"
        )
        self.details_label.setText(
            f"Ausgabe: {result.output_mode.value.upper()} · {calibration} · "
            f"Turmhöhe: {result.scene.tower_height_mm:.2f} mm"
        )
        quality_text, quality_state = self._quality_summary(result)
        self._last_quality_text = quality_text
        self._set_quality_text(quality_text, quality_state)
        self._set_quality_details(self._last_iteration_summary(result))
        self.progress.hide()
        self.progress_status_widget.hide()
        self.update_button.setText("Vorschau aktualisieren")
        self.update_button.setEnabled(True)
        self.export_button.setEnabled(True)

    @staticmethod
    def _format_dimension(value_mm: float) -> str:
        """Format a bed dimension compactly with the German decimal mark."""

        return f"{value_mm:.2f}".rstrip("0").rstrip(".").replace(".", ",")

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
            if self._last_quality_text:
                self._set_quality_text(
                    "Diese Qualitätsauswertung gehört zur nicht mehr aktuellen "
                    f"Vorschau.\n{self._last_quality_text}",
                    "stale",
                )
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
        self._last_quality_text = ""
        self._set_quality_details("")
        self._set_quality_text(
            "Für die fehlgeschlagene neue Vorschau liegt keine aktuelle "
            "Qualitätsauswertung vor.",
            "error",
        )
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
            "Messwerte des letzten Durchlaufs ausblenden ▾"
            if expanded
            else "Messwerte des letzten Durchlaufs anzeigen ▸"
        )
        self.quality_details_label.setVisible(
            expanded and bool(self.quality_details_label.text().strip())
        )

    @staticmethod
    def _quality_summary(result: PreviewResult) -> tuple[str, str]:
        calibration = getattr(result, "calibration", None)
        if calibration is None:
            return (
                "Qualitätsprüfung\n"
                "— Keine slicerbasierte Kalibrierung durchgeführt; eine "
                "wiederholte Messung wurde nicht durchgeführt.",
                "neutral",
            )

        configured = max(
            0,
            int(getattr(calibration, "configured_iteration_count", 0) or 0),
        )
        iterations = tuple(getattr(calibration, "iterations", ()) or ())
        completed = len(iterations)
        calibrated = bool(getattr(result, "calibrated", False))
        slicer_optimized = bool(getattr(result, "slicer_optimized", False))
        if calibrated and configured == 1:
            headline = (
                "✓ Ein Durchlauf abgeschlossen – eine Wiederholungsstabilität "
                "kann damit nicht geprüft werden"
            )
            state = "success"
        elif calibrated:
            headline = f"✓ Ergebnis nach {completed} Durchläufen bestätigt"
            state = "success"
        elif slicer_optimized:
            headline = (
                "⚠ Ergebnis noch nicht bestätigt – bester gemessener "
                "Zwischenstand wird angezeigt"
            )
            state = "warning"
        else:
            headline = "✕ Slicerprüfung nicht erfolgreich abgeschlossen"
            state = "error"

        lines = [
            "Qualitätsprüfung",
            headline,
            f"Ausgeführt: {completed} von {configured} eingestellten Durchläufen",
        ]
        time_tolerance = float(
            getattr(result, "calibration_time_tolerance_s", 0.15)
        )
        target_time = getattr(result, "target_layer_time_s", None)
        minimum_time = getattr(result, "minimum_verified_layer_time_s", None)
        if PreviewDialog._is_finite(target_time) and PreviewDialog._is_finite(
            minimum_time
        ):
            difference = float(minimum_time) - float(target_time)
            relation = (
                "innerhalb der Toleranz"
                if difference >= -time_tolerance
                else f"um {-difference - time_tolerance:.3f} s außerhalb der Toleranz"
            )
            lines.append(
                "Kleinste geprüfte Layerzeit des besten Messkandidaten: "
                f"{float(minimum_time):.3f} s bei {float(target_time):.3f} s "
                f"Ziel ({difference:+.3f} s; {relation})"
            )

        failures = tuple(getattr(calibration, "failures", ()) or ())
        lines.extend(PreviewDialog._summarized_failures(failures))
        return "\n".join(lines), state

    @staticmethod
    def _last_iteration_summary(result: PreviewResult) -> str:
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
            getattr(result, "calibration_time_tolerance_s", 0.15)
        )
        profile_tolerance = float(
            getattr(result, "calibration_profile_tolerance_mm", 0.03)
        )
        metadata_tolerance = float(
            getattr(result, "calibration_metadata_tolerance_s", 0.75)
        )
        deficient_count = max(
            0,
            int(getattr(last, "deficient_layer_count", 0) or 0),
        )
        lines = [
            PreviewDialog._maximum_value_assessment(
                "Zielzeit-Unterschreitung",
                getattr(last, "maximum_remaining_deficit_s", None),
                time_tolerance,
                "s",
                suffix=(
                    f"; {deficient_count} Layer außerhalb der Toleranz"
                ),
            ),
            PreviewDialog._maximum_value_assessment(
                "Änderung zum vorherigen Slicer-Durchlauf",
                getattr(last, "maximum_slicer_result_change_s", None),
                time_tolerance,
                "s",
            ),
            PreviewDialog._maximum_value_assessment(
                "Änderung des Geometrieprofils",
                getattr(last, "maximum_profile_change_mm", None),
                profile_tolerance,
                "mm",
            ),
        ]
        metadata_difference = getattr(
            getattr(last, "evaluation", None),
            "maximum_metadata_difference_s",
            None,
        )
        if metadata_difference is not None:
            lines.append(
                PreviewDialog._maximum_value_assessment(
                    "Slicer-Metadatenabweichung",
                    metadata_difference,
                    metadata_tolerance,
                    "s",
                )
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
