"""Persistent generation controls and candidate feedback beside the preview."""
from __future__ import annotations

from html import escape
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QGridLayout,
)
from cooling_tower.calibration.candidate_evaluation import minimum_combined_layer_time

from cooling_tower.gui.generation_progress_dialog import (
    MINIMUM_JOINT_SLICES_BEFORE_ACCEPT,
    TowerImageProgress,
)
from cooling_tower.gui.widgets.generation_result_actions import GenerationResultActions


def result_description(deviation: float, tolerance: float) -> str:
    excess = abs(deviation) - tolerance
    if excess <= 1e-9:
        return "Zielzeit erreicht (innerhalb der Toleranz)"
    degree = "leicht " if excess <= 0.5 + 1e-9 else "stärker " if excess > 1.0 + 1e-9 else ""
    direction = "überschritten" if deviation > 0 else "unterschritten"
    return f"Zielzeit {degree}{direction}"


class GenerationPanel(QWidget):
    accept_requested = Signal()
    continue_requested = Signal()
    export_requested = Signal()
    manual_creation_requested = Signal()
    layout_changed = Signal()

    def __init__(self, image_path, parent=None):
        super().__init__(parent)
        self.setObjectName("generationPanel")
        self._target = 0.0
        self._tolerance = 0.0
        self._completed = 0
        self._maximum = 0
        self._minimum_joint_slices = MINIMUM_JOINT_SLICES_BEFORE_ACCEPT
        self._running = False
        self._has_result = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.result_widget = QWidget(self)
        result_layout_outer = QVBoxLayout(self.result_widget)
        result_layout_outer.setContentsMargins(0, 0, 0, 0)
        result_layout_outer.setSpacing(10)
        header = QHBoxLayout()
        self.image_progress = TowerImageProgress(image_path, self)
        self.image_progress.setFixedSize(112, 128)
        header.addWidget(self.image_progress, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        heading = QVBoxLayout()
        self.title_label = QLabel("Kühlturm wird generiert …")
        self.title_label.setObjectName("towerGenerationTitle")
        self.title_label.setWordWrap(True)
        self.counter_label = QLabel()
        self.counter_label.setWordWrap(True)
        heading.addWidget(self.title_label)
        heading.addWidget(self.counter_label)
        header.addLayout(heading, 1)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)
        self.best_minimum_value = QLabel("Noch kein gemeinsamer Slice abgeschlossen.")
        self.best_minimum_value.setTextFormat(Qt.TextFormat.RichText)
        self.best_deviation_value = QLabel("–")
        self.result_label = QLabel()
        self.result_label.setObjectName("generationResultDescription")
        self.simulation_label = QLabel()
        self.simulation_label.setTextFormat(Qt.TextFormat.RichText)
        result = QWidget()
        result_layout = QVBoxLayout(result)
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_layout.addWidget(self.result_label)
        result_layout.addWidget(self.simulation_label)
        result_layout.setSpacing(10)
        for row, (caption, value) in enumerate((
            ("◷  Beste bisherige Layerzeit", self.best_minimum_value),
            ("↔  Abweichung", self.best_deviation_value),
            ("✓  Ergebnis", result),
        )):
            label = QLabel(caption)
            label.setWordWrap(row != 0)
            grid.addWidget(label, row, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(value, row, 1)
        for label in (self.best_minimum_value, self.best_deviation_value, self.simulation_label, self.result_label):
            label.setWordWrap(True)
        heading.addLayout(grid)
        result_layout_outer.addLayout(header)
        self.continue_button = QPushButton("Angleichung fortsetzen")
        self.continue_button.setObjectName("generationContinueButton")
        self.continue_button.clicked.connect(self.continue_requested)
        self.continue_button.hide()
        self.accept_button = QPushButton("Bestes bisheriges\nErgebnis übernehmen")
        self.accept_button.setObjectName("generationAcceptButton")
        self.accept_button.clicked.connect(self.accept_requested)
        self.export_button = QPushButton("Kühlturm exportieren")
        self.export_button.setObjectName("generationExportButton")
        self.export_button.clicked.connect(self.export_requested)
        self.export_button.setEnabled(False)
        self.export_button.hide()
        self.result_actions = GenerationResultActions(
            self.continue_button, self.export_button, self.accept_button, self.result_widget,
        )
        self.manual_creation_offer = self.result_actions.manual_offer
        self.manual_creation_title = self.result_actions.title_label
        self.manual_creation_description = self.result_actions.description_label
        self.manual_creation_button = self.result_actions.manual_button
        self.manual_creation_button.clicked.connect(self.manual_creation_requested)
        self.result_actions.layout_changed.connect(self.layout_changed)
        result_layout_outer.addWidget(self.result_actions)
        layout.addWidget(self.result_widget)
        self.result_widget.hide()
        self.hide()

    def set_context(self, simulations=()):
        items = "<br>".join(escape(f"• {item}") for item in simulations)
        self.simulation_label.setText(
            "<u>Simulierte Werte:</u><br>" + (items or "• Keine zusätzlichen Simulationen")
        )

    def begin(
        self,
        target_s,
        tolerance_s,
        completed,
        maximum,
        minimum_joint_slices=MINIMUM_JOINT_SLICES_BEFORE_ACCEPT,
    ):
        self._target, self._tolerance = target_s, tolerance_s
        self._minimum_joint_slices = minimum_joint_slices
        self._has_result = False
        self.best_minimum_value.setText("Noch kein gemeinsamer Slice abgeschlossen.")
        self.best_minimum_value.setStyleSheet("")
        self.best_deviation_value.setText("–")
        self.best_deviation_value.setStyleSheet("")
        self.result_label.setText("Gemeinsame Prüfung ausstehend")
        self._running = True
        self._completed, self._maximum = completed, maximum
        self.image_progress.set_display_complete(False)
        self.image_progress.set_fill(0.0)
        self.result_widget.hide()
        self.continue_button.hide()
        self.continue_button.setEnabled(False)
        self.export_button.hide()
        self.accept_button.setText("Bestes bisheriges\nErgebnis übernehmen")
        self.accept_button.setVisible(completed >= minimum_joint_slices)
        self.accept_button.setEnabled(completed >= minimum_joint_slices)
        self._refresh_manual_creation_offer()
        self.show()
        self.layout_changed.emit()

    def start_slice(self, completed, maximum):
        self._running = True
        self._refresh_manual_creation_offer()
        self.image_progress.set_display_complete(False)
        self._completed, self._maximum = completed, maximum
        self.title_label.setText("Kühlturm wird generiert …")
        self.counter_label.setText(f"{completed} von {maximum} gemeinsamen Slices abgeschlossen · Slice {completed + 1} läuft")
        self.image_progress.set_fill(0.0)
        self.image_progress.animate_fill(0.12)
        self.continue_button.setEnabled(False)
        self.result_widget.show()
        self.layout_changed.emit()

    def set_slice_progress(self, value):
        if self._running and not self.result_widget.isHidden():
            self.image_progress.animate_fill(value)

    def complete_slice(self, completed, maximum, best_iteration, target_s):
        self._completed, self._maximum = completed, maximum
        self.counter_label.setText(f"{completed} von {maximum} gemeinsamen Slices abgeschlossen")
        self.image_progress.animate_fill(1.0, pulse_when_finished=True)
        self.accept_button.setVisible(completed >= self._minimum_joint_slices)
        self.accept_button.setEnabled(completed >= self._minimum_joint_slices)
        self.continue_button.setVisible(
            completed >= self._minimum_joint_slices and completed < maximum
        )
        self.continue_button.setEnabled(False)
        self.set_achieved(minimum_combined_layer_time(
            getattr(best_iteration, "evaluation", None)
        ))

    def set_achieved(self, minimum):
        if minimum is None:
            self.best_minimum_value.setText("Keine belastbare gemeinsame Layerzeit verfügbar")
            self.best_deviation_value.setText("–")
            self.best_deviation_value.setStyleSheet("")
            self.result_label.setText("Zeitbewertung nicht möglich")
            return
        deviation = minimum - self._target
        outside = abs(deviation) > self._tolerance + 1e-9
        value_color = "#b87900" if outside else "#22854b"
        self.best_minimum_value.setText(
            f'<span style="color:{value_color}">{minimum:.2f} s</span>'
            f'<span style="color:#000000"> / {self._target:.2f} s '
            f'(± {self._tolerance:.2f} s Toleranz)</span>'
        )
        self.best_deviation_value.setText(f"{deviation:+.2f} s")
        self.best_deviation_value.setStyleSheet(f"color: {value_color};")
        self.result_label.setText(result_description(deviation, self._tolerance))
        self.layout_changed.emit()

    def mark_finished(self, *, paused, can_continue, status_text=None, has_result=True):
        self._running = False
        self._has_result = has_result
        self.title_label.setText("Generierung gestoppt" if paused else "Kühlturm fertig generiert")
        self.counter_label.setText(status_text or f"{self._completed} von {self._maximum} gemeinsamen Slices abgeschlossen")
        self.image_progress.set_display_complete(True)
        self.result_widget.setVisible(has_result)
        if not has_result:
            self.hide()
        self.accept_button.hide()
        self.export_button.setVisible(has_result)
        self.continue_button.setVisible(has_result and paused and can_continue)
        self.continue_button.setEnabled(has_result and paused and can_continue)
        self._refresh_manual_creation_offer()
        self.layout_changed.emit()

    def resume_waiting(self):
        self._running = True
        self._refresh_manual_creation_offer()
        self.image_progress.set_display_complete(False)
        self.title_label.setText("Kühlturm wird generiert …")
        self.counter_label.setText(f"{self._completed} von {self._maximum} gemeinsamen Slices abgeschlossen · Fortsetzung wird vorbereitet")
        self.result_widget.show()
        self.continue_button.setVisible(
            self._completed >= self._minimum_joint_slices
            and self._completed < self._maximum
        )
        self.continue_button.setEnabled(False)
        self.export_button.hide()
        self.accept_button.setText("Bestes bisheriges\nErgebnis übernehmen")
        self.accept_button.setVisible(
            self._completed >= self._minimum_joint_slices
        )
        self.accept_button.setEnabled(
            self._completed >= self._minimum_joint_slices
        )
        self.layout_changed.emit()

    def show_error(self, _message, *, retain_result=False, can_continue=False):
        """Keep safe result controls; the caller reports the error in the footer."""
        self._running = False
        self._has_result = retain_result
        self.image_progress.set_display_complete(True)
        self.title_label.setText("Generierung nicht abgeschlossen")
        self.result_widget.setVisible(self._has_result)
        self.accept_button.hide()
        self.export_button.setVisible(self._has_result)
        self.continue_button.setVisible(self._has_result and can_continue)
        self.continue_button.setEnabled(self._has_result and can_continue)
        self._refresh_manual_creation_offer()
        self.setVisible(self._has_result)
        self.layout_changed.emit()

    def mark_interrupted(self, reason):
        self._running = False
        self._has_result = False
        self._refresh_manual_creation_offer()
        self.title_label.setText("Generierung gestoppt")
        self.counter_label.setText(reason)
        self.result_widget.hide()
        self.accept_button.hide()
        self.export_button.hide()
        self.continue_button.hide()
        self.hide()
        self.layout_changed.emit()

    def allow_programmatic_close(self):
        pass

    def _refresh_manual_creation_offer(self):
        self.result_actions.set_offer_visible(self._has_result and not self._running)
