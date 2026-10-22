"""Persistent generation controls and candidate feedback beside the preview."""
from __future__ import annotations

from html import escape
from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QFrame, QSizePolicy,
)
from cooling_tower.calibration.candidate_evaluation import minimum_combined_layer_time

from cooling_tower.gui.generation_progress_dialog import (
    MINIMUM_JOINT_SLICES_BEFORE_ACCEPT,
    TowerImageProgress,
)
from cooling_tower.gui.widgets.generation_result_actions import GenerationResultActions
from cooling_tower.gui.widgets.animated_generation_title import AnimatedGenerationTitle
from cooling_tower.gui.widgets.generation_metrics_layout import GenerationMetricsLayout


RESULT_REACHED_TEXT = "Zielzeit erreicht"
RESULT_PENDING_TEXT = "Gemeinsame Prüfung ausstehend"
RESULT_UNAVAILABLE_TEXT = "Zeitbewertung nicht möglich"
RESULT_DEVIATION_TEXTS = {
    (degree, direction): f"Zielzeit {degree}{direction}"
    for degree in ("", "leicht ", "stärker ")
    for direction in ("überschritten", "unterschritten")
}
RESULT_SUMMARY_TEXTS = (RESULT_REACHED_TEXT, RESULT_PENDING_TEXT, RESULT_UNAVAILABLE_TEXT,
                        *RESULT_DEVIATION_TEXTS.values())


def result_description(deviation: float, tolerance: float) -> str:
    excess = abs(deviation) - tolerance
    if excess <= 1e-9:
        return RESULT_REACHED_TEXT
    degree = "leicht " if excess <= 0.5 + 1e-9 else "stärker " if excess > 1.0 + 1e-9 else ""
    direction = "überschritten" if deviation > 0 else "unterschritten"
    return RESULT_DEVIATION_TEXTS[degree, direction]


class GenerationPanel(QWidget):
    accept_requested = Signal()
    continue_requested = Signal()
    export_requested = Signal()
    layout_changed = Signal()

    def __init__(self, image_path, parent=None):
        super().__init__(parent)
        self.setObjectName("generationPanel")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
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
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.result_widget = QFrame(self)
        self.result_widget.setObjectName("generationResultCard")
        result_layout_outer = QVBoxLayout(self.result_widget)
        result_layout_outer.setContentsMargins(0, 0, 0, 0)
        result_layout_outer.setSpacing(0)
        hero = QFrame(self.result_widget)
        hero.setObjectName("generationResultHero")
        header = QHBoxLayout(hero)
        header.setContentsMargins(12, 8, 14, 8)
        header.setSpacing(16)
        self.image_progress = TowerImageProgress(image_path, hero)
        self.image_progress.setFixedSize(84, 96)
        header.addWidget(self.image_progress, 0, Qt.AlignmentFlag.AlignVCenter)
        heading = QVBoxLayout()
        heading.setSpacing(5)
        eyebrow = QLabel("GEMEINSAME SLICERPRÜFUNG")
        eyebrow.setObjectName("generationResultEyebrow")
        self.title_label = AnimatedGenerationTitle()
        self.title_label.setObjectName("towerGenerationTitle")
        self.title_label.setWordWrap(True)
        self.counter_label = QLabel()
        self.counter_label.setObjectName("generationSliceCounter")
        self.counter_label.setWordWrap(True)
        heading.addWidget(eyebrow)
        heading.addWidget(self.title_label)
        heading.addWidget(self.counter_label)
        header.addLayout(heading, 1)
        result_layout_outer.addWidget(hero)

        self.best_minimum_value = QLabel("Noch kein gemeinsamer Slice abgeschlossen.")
        self.best_minimum_value.setTextFormat(Qt.TextFormat.RichText)
        self.best_minimum_value.setObjectName("generationLayerTimeValue")
        self.target_label = QLabel()
        self.target_label.setObjectName("generationMetricHint")
        self.best_deviation_value = QLabel("–")
        self.best_deviation_value.setObjectName("generationDeviationValue")
        self.deviation_hint = QLabel("Zur gewünschten Layerzeit")
        self.deviation_hint.setObjectName("generationMetricHint")
        self.metrics_group = QFrame(self.result_widget)
        self.metrics_group.setObjectName("generationMetricsGroup")
        self.metrics_group.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.metric_cards = []
        for caption, value, hint, role in (
            ("Beste gemeinsame Layerzeit", self.best_minimum_value, self.target_label, "time"),
            ("Abweichung", self.best_deviation_value, self.deviation_hint, "deviation"),
        ):
            card = QFrame(self.metrics_group)
            card.setObjectName("generationMetricCard")
            card.setProperty("metric", role)
            card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            column = QVBoxLayout(card)
            column.setContentsMargins(12, 10, 12, 10)
            column.setSpacing(4)
            label = QLabel(caption)
            label.setObjectName("generationMetricCaption")
            for item in (label, value, hint):
                item.setWordWrap(True)
                item.setMinimumWidth(0)
                column.addWidget(item)
            column.addStretch(1)
            self.metric_cards.append(card)
        self.result_summary = QFrame(self.result_widget)
        self.result_summary.setObjectName("generationResultSummary")
        self.result_summary.setProperty("resultState", "pending")
        self.result_summary.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        result_layout = QVBoxLayout(self.result_summary)
        result_layout.setContentsMargins(12, 9, 12, 9)
        result_layout.setSpacing(7)
        self.result_label = QLabel()
        self.result_label.setObjectName("generationResultDescription")
        self.simulation_label = QLabel()
        self.simulation_label.setObjectName("generationSimulationContext")
        self.simulation_label.setTextFormat(Qt.TextFormat.RichText)
        for label in (self.result_label, self.simulation_label):
            label.setWordWrap(True)
            result_layout.addWidget(label)
        self.manual_hint_cell = QFrame(self.result_widget)
        self.manual_hint_cell.setObjectName("generationManualHintCell")
        self.manual_hint_cell.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        hint_layout = QVBoxLayout(self.manual_hint_cell)
        hint_layout.setContentsMargins(12, 9, 12, 9)
        hint_layout.setSpacing(0)
        self.manual_hint_cell.hide()
        result_layout_outer.addWidget(self.metrics_group)
        self.continue_button = QPushButton("Angleichen fortsetzen")
        self.continue_button.setObjectName("generationContinueButton")
        self.continue_button.clicked.connect(self.continue_requested)
        self.continue_button.hide()
        self.accept_button = QPushButton("Bisheriges Ergebnis übernehmen")
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
        self.result_actions.layout().setContentsMargins(10, 12, 10, 12)
        self.manual_mode_hint = self.result_actions.manual_hint
        self.metrics_layout = GenerationMetricsLayout(
            self.metric_cards, self.result_summary, self.manual_hint_cell,
            self.result_actions, self.metrics_group,
            summary_text_variants={self.result_label: RESULT_SUMMARY_TEXTS},
        )
        self.metrics_layout.layout_changed.connect(self.layout_changed)
        self.result_actions.layout_changed.connect(self.layout_changed)
        self.result_actions.hint_visibility_changed.connect(self._refresh_metrics_layout)
        self.result_actions.width_requirement_changed.connect(self._refresh_metrics_layout)
        result_layout_outer.addWidget(self.result_actions)
        layout.addWidget(self.result_widget)
        self._refresh_metrics_layout()
        self.result_widget.hide()
        self.hide()

    def set_context(self, simulations=()):
        items = "<br>".join(escape(f"• {item}") for item in simulations)
        self.simulation_label.setText(
            "<b>Simulationen</b><br>" + items if items else "Keine zusätzlichen Simulationen"
        )
        self._refresh_metrics_layout()

    def begin(
        self,
        target_s,
        tolerance_s,
        completed,
        maximum,
        minimum_joint_slices=MINIMUM_JOINT_SLICES_BEFORE_ACCEPT,
    ):
        self._target, self._tolerance = target_s, tolerance_s
        self.target_label.setText(f"Ziel {target_s:.2f} s · Toleranz ± {tolerance_s:.2f} s")
        self._set_result_state("pending")
        self._minimum_joint_slices = minimum_joint_slices
        self._has_result = False
        self.best_minimum_value.setText("Noch kein gemeinsamer Slice abgeschlossen.")
        self.best_minimum_value.setStyleSheet("")
        self.best_deviation_value.setText("–")
        self.best_deviation_value.setStyleSheet("")
        self.result_label.setText(RESULT_PENDING_TEXT)
        self._running = True
        self._completed, self._maximum = completed, maximum
        self.image_progress.set_display_complete(False)
        self.image_progress.set_fill(0.0)
        self.result_widget.hide()
        self.continue_button.hide()
        self.continue_button.setEnabled(False)
        self.export_button.hide()
        self.accept_button.setText("Bisheriges Ergebnis übernehmen")
        self.accept_button.setVisible(completed >= minimum_joint_slices)
        self.accept_button.setEnabled(completed >= minimum_joint_slices)
        self._refresh_manual_mode_hint()
        self._refresh_metrics_layout()
        self.show()
        self.layout_changed.emit()

    def start_slice(self, completed, maximum):
        self._running = True
        self.result_actions.set_hint_visible(True)
        self.image_progress.set_display_complete(False)
        self._completed, self._maximum = completed, maximum
        self.title_label.start_generating()
        self.counter_label.setText(f"{completed} von {maximum} gemeinsamen Slices abgeschlossen · Slice {completed + 1} läuft")
        self.image_progress.set_fill(0.0)
        self.image_progress.animate_fill(0.12)
        self.continue_button.setEnabled(False)
        self._refresh_metrics_layout()
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
            self._set_result_state("pending")
            self.best_deviation_value.setStyleSheet("")
            self.result_label.setText(RESULT_UNAVAILABLE_TEXT)
            self._refresh_metrics_layout()
            return
        deviation = minimum - self._target
        outside = abs(deviation) > self._tolerance + 1e-9
        value_color = "#b87900" if outside else "#22854b"
        self.best_minimum_value.setText(f'<span style="color:{value_color}">{minimum:.2f} s</span>')
        self._set_result_state("outside" if outside else "within")
        self.best_deviation_value.setText(f"{deviation:+.2f} s")
        self.best_deviation_value.setStyleSheet(f"color: {value_color};")
        self.result_label.setText(result_description(deviation, self._tolerance))
        self._refresh_metrics_layout()
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
        self._refresh_manual_mode_hint()
        self.layout_changed.emit()

    def resume_waiting(self):
        self._running = True
        self._refresh_manual_mode_hint()
        self.image_progress.set_display_complete(False)
        self.title_label.start_generating()
        self.counter_label.setText(f"{self._completed} von {self._maximum} gemeinsamen Slices abgeschlossen · Fortsetzung wird vorbereitet")
        self.result_widget.show()
        self.continue_button.setVisible(
            self._completed >= self._minimum_joint_slices
            and self._completed < self._maximum
        )
        self.continue_button.setEnabled(False)
        self.export_button.hide()
        self.accept_button.setText("Bisheriges Ergebnis übernehmen")
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
        self._refresh_manual_mode_hint()
        self.setVisible(self._has_result)
        self.layout_changed.emit()

    def mark_interrupted(self, reason):
        self._running = False
        self._has_result = False
        self._refresh_manual_mode_hint()
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

    def _refresh_manual_mode_hint(self):
        self.result_actions.set_hint_visible(self._has_result and not self._running)

    def _set_result_state(self, state):
        for widget in (self.result_summary, self.best_minimum_value, *self.metric_cards):
            widget.setProperty("resultState", state)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._refresh_metrics_layout()

    def event(self, event):
        result = super().event(event)
        if event.type() in (QEvent.Type.StyleChange, QEvent.Type.FontChange):
            self._refresh_metrics_layout()
        return result

    def _refresh_metrics_layout(self):
        if not hasattr(self, "metrics_layout"):
            return
        self.metrics_layout.flexible_columns = (
            self._completed == 0 and self.best_minimum_value.property("resultState") == "pending"
        )
        self.metrics_layout.invalidate()
        self.metrics_group.updateGeometry()
