from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QRectF,
    QSize,
    QTimer,
    Qt,
    QPropertyAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QCloseEvent, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QLineEdit,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from cooling_tower.gui.design_tokens import METRICS
from cooling_tower.gui.widgets.info_tool_button import InfoToolButton
from cooling_tower.gui.texts import SETTING_INFO_TEXTS


DEFAULT_MAXIMUM_JOINT_SLICES = 12
DEFAULT_MAXIMUM_SEPARATE_SLICES = 6
MINIMUM_JOINT_SLICES_BEFORE_ACCEPT = 3
GENERATION_DIALOG_WIDTH_PX = 610
GENERAL_SETTINGS_DIALOG_WIDTH_PX = 707
GENERAL_SETTINGS_NUMBER_WIDTH_PX = 165
JOINT_SLICE_HINT = """
<p align="left" style="margin-top:0; margin-bottom:0px;"><b>Was wird begrenzt?</b></p>
<p style="margin-top:0; margin-bottom:10px;">Die maximale Anzahl gemeinsamer Slices mit Objekt und Kühlturm. Dabei wird die Layerzeit an den Zielwert angeglichen. Nach den ersten drei gemeinsamen Slices kann die Generierung bei höchstens ±0,09 s Zielabweichung, ausbleibender Verbesserung oder manueller Übernahme früher enden.</p>
<p align="left" style="margin-top:0; margin-bottom:0px;"><b>Welcher Wert ist sinnvoll?</b></p>
<p style="margin-top:0; margin-bottom:10px;">Standard: 12 Slices (einstellbar von 5 bis 20). Dieser Wert reicht in den meisten Fällen aus.</p>
<p align="left" style="margin-top:0; margin-bottom:0px;"><b>Was bewirkt eine Änderung?</b></p>
<p style="margin-top:0; margin-bottom:0px;">Weniger als der Standardwert kann die Ergebnisqualität schneller spürbar verringern, als mehr Slices sie verbessern. Ein höherer Wert gibt der Angleichung bei schwierigen Fällen mehr Versuche. Mit jedem zusätzlichen Slice kann die Generierung länger dauern.</p>
""".strip()
JOINT_SLICE_HINT_ACCESSIBLE = (
    "Maximale Anzahl gemeinsamer Slices mit Objekt und Kühlturm zur Angleichung "
    "der Layerzeit. Standard: 12, einstellbar von 5 bis 20. In den meisten "
    "Fällen reicht der Standardwert. Weniger Slices können die Ergebnisqualität "
    "schneller verringern, als mehr Slices sie verbessern. Ein höherer Wert "
    "ermöglicht zusätzliche Versuche, verlängert aber möglicherweise die "
    "Generierung. Nach drei gemeinsamen Slices kann sie bei höchstens "
    "plus oder minus 0,09 Sekunden Zielabweichung, ausbleibender Verbesserung "
    "oder manueller Übernahme "
    "früher enden."
)
from cooling_tower.calibration.candidate_evaluation import minimum_combined_layer_time
SEPARATE_SLICE_HINT = """
<p align="left" style="margin-top:0; margin-bottom:0px;"><b>Was wird begrenzt?</b></p>
<p style="margin-top:0; margin-bottom:10px;">Die maximale Anzahl getrennter Slices, mit denen die Turmgeometrie vorbereitet wird. Danach folgen die gemeinsamen Slices mit Objekt und Kühlturm.</p>
<p align="left" style="margin-top:0; margin-bottom:0px;"><b>Welcher Wert ist sinnvoll?</b></p>
<p style="margin-top:0; margin-bottom:10px;">Standard: 6 Slices (einstellbar von 1 bis 15). Dieser Wert reicht in den meisten Fällen aus.</p>
<p align="left" style="margin-top:0; margin-bottom:0px;"><b>Was bewirkt eine Änderung?</b></p>
<p style="margin-top:0; margin-bottom:0px;">Weniger Slices können Zeit sparen, aber die Turmform merklich verschlechtern. Zusätzliche Slices können bei schwierigen Modellen noch Verbesserungen bringen; dieser Gewinn fällt oft kleiner aus. Jeder tatsächlich berechnete zusätzliche Slice verlängert die Generierung etwas.</p>
""".strip()
SEPARATE_SLICE_HINT_ACCESSIBLE = (
    "Maximale Anzahl getrennter Slices zur Vorbereitung der Turmgeometrie. "
    "Danach folgen gemeinsame Slices mit Objekt und Kühlturm. Standard: 6, "
    "einstellbar von 1 bis 15. In den meisten Fällen reicht der Standardwert. "
    "Weniger Slices können Zeit sparen, aber die Turmform merklich "
    "verschlechtern. Zusätzliche Slices können die Turmform bei schwierigen "
    "Modellen weiter verbessern; dieser Gewinn fällt oft kleiner aus. Jeder tatsächlich "
    "berechnete zusätzliche Slice verlängert die Generierung etwas."
)


class TowerImageProgress(QWidget):
    """Render a proportional image fill and a short completion pulse."""

    def __init__(self, image_path: str | Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("towerImageProgress")
        self._pixmap = QPixmap(str(image_path))
        self._fill = 0.0
        self._display_complete = False
        self._pulse = 0.0
        self._pulse_after_fill = False
        # The unpulsed artwork occupies roughly 209 x 240 px. The widget keeps
        # a small surrounding margin so the requested 3% pulse is never cut.
        self.setFixedSize(225, 255)
        self._animation = QPropertyAnimation(self, b"pulse", self)
        self._animation.setDuration(500)
        self._animation.setStartValue(0.0)
        self._animation.setKeyValueAt(0.5, 1.0)
        self._animation.setEndValue(0.0)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._fill_animation = QPropertyAnimation(self, b"fill", self)
        self._fill_animation.setDuration(340)
        self._fill_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._fill_animation.finished.connect(
            self._finish_animated_fill
        )

    def set_fill(self, value: float) -> None:
        self._fill = max(0.0, min(1.0, float(value)))
        self.update()

    def set_display_complete(self, complete: bool) -> None:
        self._display_complete = complete
        if complete:
            self._fill_animation.stop()
        self.update()

    def animate_fill(
        self,
        value: float,
        *,
        pulse_when_finished: bool = False,
    ) -> None:
        target = max(0.0, min(1.0, float(value)))
        self._fill_animation.stop()
        self._pulse_after_fill = pulse_when_finished
        if abs(target - self._fill) <= 1e-6:
            self.set_fill(target)
            self._finish_animated_fill()
            return
        self._fill_animation.setStartValue(self._fill)
        self._fill_animation.setEndValue(target)
        self._fill_animation.start()

    def _finish_animated_fill(self) -> None:
        if not self._pulse_after_fill:
            return
        self._pulse_after_fill = False
        self.play_success()

    def play_success(self) -> None:
        self._animation.stop()
        self._animation.start()

    def _get_pulse(self) -> float:
        return self._pulse

    def _set_pulse(self, value: float) -> None:
        self._pulse = max(0.0, min(1.0, float(value)))
        self.update()

    pulse = Property(float, _get_pulse, _set_pulse)
    fill = Property(float, lambda self: self._fill, set_fill)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(225, 255)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def paintEvent(self, _event) -> None:  # noqa: N802
        if self._pixmap.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        scale = 1.0 + 0.03 * self._pulse
        available = QRectF(
            self.width() * 0.035,
            self.height() * 0.03,
            self.width() * 0.93,
            self.height() * 0.94,
        )
        source_size = self._pixmap.size()
        ratio = min(
            available.width() / source_size.width(),
            available.height() / source_size.height(),
        ) * scale
        width = source_size.width() * ratio
        height = source_size.height() * ratio
        target = QRectF(
            (self.width() - width) / 2.0,
            (self.height() - height) / 2.0,
            width,
            height,
        )
        if self._pulse > 0.0:
            glow = target.adjusted(-8, -8, 8, 8)
            painter.setOpacity(0.18 * self._pulse)
            painter.drawPixmap(glow, self._pixmap, QRectF(self._pixmap.rect()))
        painter.setOpacity(0.2 + 0.08 * self._pulse)
        painter.drawPixmap(target, self._pixmap, QRectF(self._pixmap.rect()))
        displayed_fill = 1.0 if self._display_complete else self._fill
        if displayed_fill > 0.0:
            filled_height = target.height() * displayed_fill
            painter.save()
            painter.setClipRect(
                QRectF(
                    target.left(),
                    target.bottom() - filled_height,
                    target.width(),
                    filled_height,
                )
            )
            painter.setOpacity(1.0)
            painter.drawPixmap(target, self._pixmap, QRectF(self._pixmap.rect()))
            painter.restore()


class TowerGenerationDialog(QDialog):
    accept_requested = Signal()
    export_requested = Signal()
    abort_requested = Signal()
    continue_requested = Signal()

    def __init__(self, image_path: str | Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("towerGenerationDialog")
        self.setWindowTitle("Kühlturm wird generiert")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setFixedWidth(GENERATION_DIALOG_WIDTH_PX)
        self._running = False
        self._allow_close = False
        self._primary_mode = "accept"
        self._tolerance_s = 0.0
        self._best_deviation_s: float | None = None
        self._minimum_joint_slices = MINIMUM_JOINT_SLICES_BEFORE_ACCEPT
        self._completed_joint_slices = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 22, 26, 22)
        layout.setSpacing(12)
        self.title_label = QLabel("Kühlturm wird generiert …")
        self.title_label.setObjectName("towerGenerationTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title_label)

        self.explanation_label = QLabel(
            "Objekt und Kühlturm werden jetzt gemeinsam geslicet; weil sich dabei "
            "Geschwindigkeiten, Beschleunigungen und Kühlzeiten gegenseitig "
            "beeinflussen, wird die Turmform schrittweise an Ihre Zielzeit "
            "angeglichen. Die ersten drei gemeinsamen Slices sind Pflicht. "
            "Danach können Sie das bisher beste Ergebnis übernehmen und anschließend "
            "exportieren."
        )
        self.explanation_label.setObjectName("towerGenerationExplanation")
        self.explanation_label.setWordWrap(True)
        self.explanation_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.explanation_label)

        self.image_progress = TowerImageProgress(image_path, self)
        layout.addWidget(
            self.image_progress,
            0,
            Qt.AlignmentFlag.AlignHCenter,
        )

        self.counter_label = QLabel()
        self.counter_label.setObjectName("towerGenerationCounter")
        self.counter_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.counter_label)

        self.summary_frame = QFrame()
        self.summary_frame.setObjectName("towerGenerationSummary")
        summary_layout = QGridLayout(self.summary_frame)
        summary_layout.setContentsMargins(14, 10, 14, 10)
        summary_layout.setHorizontalSpacing(6)
        summary_layout.setVerticalSpacing(7)
        summary_layout.addWidget(QLabel("Gewünschte Layerzeit"), 0, 0)
        self.target_value = QLabel("–")
        self.target_value.setObjectName("towerGenerationMetric")
        self.target_value.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        summary_layout.addWidget(self.target_value, 0, 1, 1, 2)
        best_title = QLabel("Bisher bestes Ergebnis")
        best_title.setObjectName("towerGenerationSummaryLabel")
        self.best_title_label = best_title
        summary_layout.addWidget(best_title, 1, 0)
        self.best_minimum_value = QLabel(
            "Noch kein gemeinsamer Slice abgeschlossen."
        )
        self.best_minimum_value.setObjectName("towerGenerationMetric")
        self.best_minimum_value.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.best_deviation_value = QLabel()
        self.best_deviation_value.setObjectName("towerGenerationDeviation")
        self.best_deviation_value.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.best_deviation_value.hide()
        self.best_values_widget = QWidget()
        best_values_layout = QHBoxLayout(self.best_values_widget)
        best_values_layout.setContentsMargins(0, 0, 0, 0)
        best_values_layout.setSpacing(
            self.best_minimum_value.fontMetrics().horizontalAdvance(" ")
        )
        best_values_layout.addWidget(self.best_minimum_value)
        best_values_layout.addWidget(self.best_deviation_value)
        self.best_values_layout = best_values_layout
        summary_layout.addWidget(
            self.best_values_widget,
            1,
            1,
            1,
            2,
            Qt.AlignmentFlag.AlignRight,
        )
        summary_layout.setColumnStretch(0, 1)
        layout.addWidget(self.summary_frame)

        self.stop_reason_divider = QFrame()
        self.stop_reason_divider.setObjectName(
            "towerGenerationStopReasonDivider"
        )
        self.stop_reason_divider.setFrameShape(QFrame.Shape.HLine)
        self.stop_reason_label = QLabel()
        self.stop_reason_label.setObjectName("towerGenerationStopReason")
        self.stop_reason_label.setWordWrap(True)
        self.stop_reason_divider.hide()
        self.stop_reason_label.hide()
        layout.addWidget(self.stop_reason_divider)
        layout.addWidget(self.stop_reason_label)

        self.error_divider = QFrame()
        self.error_divider.setObjectName("towerGenerationErrorDivider")
        self.error_divider.setFrameShape(QFrame.Shape.HLine)
        self.error_label = QLabel()
        self.error_label.setObjectName("towerGenerationError")
        self.error_label.setWordWrap(True)
        self.error_divider.hide()
        self.error_label.hide()
        layout.addWidget(self.error_divider)
        layout.addWidget(self.error_label)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)
        self.abort_button = QPushButton("Generierung abbrechen")
        self.abort_button.setObjectName("towerGenerationAbortButton")
        self.abort_button.clicked.connect(self._abort)
        actions.addWidget(self.abort_button)
        self.continue_button = QPushButton("Angleichung fortsetzen")
        self.continue_button.setObjectName("towerGenerationContinueButton")
        self.continue_button.clicked.connect(self.continue_requested)
        self.continue_button.hide()
        actions.addWidget(self.continue_button)
        self.accept_button = QPushButton("Bestes Ergebnis übernehmen")
        self.accept_button.setObjectName("towerGenerationAcceptButton")
        self.accept_button.clicked.connect(self._activate_primary_action)
        self.accept_button.setEnabled(False)
        actions.addWidget(self.accept_button)
        layout.addLayout(actions)
        layout.activate()
        self._fit_and_center()

    def begin(
        self,
        target_s: float,
        tolerance_s: float,
        completed: int,
        maximum: int,
        minimum_joint_slices: int = MINIMUM_JOINT_SLICES_BEFORE_ACCEPT,
    ) -> None:
        # A newly created owned dialog can briefly inherit the maximized
        # native state of its main window on Windows.  Clear that state before
        # its first show so the reveal filter only ever exposes the natural
        # content-sized geometry.
        self.setWindowState(Qt.WindowState.WindowNoState)
        self._running = True
        self._allow_close = False
        self._tolerance_s = max(0.0, float(tolerance_s))
        self._best_deviation_s = None
        self._minimum_joint_slices = minimum_joint_slices
        self._completed_joint_slices = completed
        self.target_value.setText(
            f"{target_s:.2f} s (± {tolerance_s:.2f} s Toleranz)"
        )
        self.counter_label.setText(
            f"{completed} von {maximum} gemeinsamen Slices abgeschlossen"
        )
        self.image_progress.set_fill(0.0)
        self._set_best_metrics_visible(False)
        self._primary_mode = "accept"
        self.accept_button.setVisible(completed >= minimum_joint_slices)
        self.accept_button.setEnabled(completed >= minimum_joint_slices)
        self.accept_button.setText("Bestes Ergebnis übernehmen")
        self.abort_button.setText("Generierung abbrechen")
        self.continue_button.hide()
        self.error_divider.hide()
        self.error_label.hide()
        self.stop_reason_divider.hide()
        self.stop_reason_label.hide()
        self._fit_and_center()
        self.showNormal()
        self._fit_and_center()
        QTimer.singleShot(0, self, self._fit_and_center)
        self.raise_()
        self.activateWindow()

    def start_slice(self, completed: int, maximum: int) -> None:
        self._running = True
        self.counter_label.setText(
            f"{completed} von {maximum} gemeinsamen Slices abgeschlossen · "
            f"Slice {completed + 1} läuft"
        )
        self.image_progress.set_fill(0.0)
        self.image_progress.animate_fill(0.12)

    def set_slice_progress(self, value: float) -> None:
        if self._running:
            self.image_progress.animate_fill(value)

    def complete_slice(
        self,
        completed: int,
        maximum: int,
        best_iteration: object,
        target_s: float,
    ) -> None:
        self._completed_joint_slices = completed
        self.counter_label.setText(
            f"{completed} von {maximum} gemeinsamen Slices abgeschlossen"
        )
        self.image_progress.animate_fill(1.0, pulse_when_finished=True)
        self.accept_button.setVisible(completed >= self._minimum_joint_slices)
        self.accept_button.setEnabled(completed >= self._minimum_joint_slices)
        minimum = minimum_combined_layer_time(
            getattr(best_iteration, "evaluation", None)
        )
        if minimum is not None:
            deviation = minimum - target_s
            sign = "+" if deviation >= 0.0 else "−"
            self._best_deviation_s = deviation
            self._set_best_metrics_visible(True)
            self.best_minimum_value.setText(f"{minimum:.2f} s")
            self.best_deviation_value.setText(
                f"({sign}{abs(deviation):.2f} s)"
            )
            deviation_state = (
                "within"
                if abs(deviation) <= self._tolerance_s + 1e-9
                else "outside"
            )
            self._set_result_state(
                self.best_deviation_value,
                deviation_state,
            )
        else:
            self._best_deviation_s = None
            self._set_best_metrics_visible(False)
            self.best_minimum_value.setText(
                "Der Kandidat wurde geprüft, es liegen jedoch keine "
                "darstellbaren gemeinsamen Layerzeiten vor."
            )
        self._fit_and_center()

    def mark_finished(
        self,
        *,
        paused: bool,
        can_continue: bool,
        status_text: str | None = None,
        stop_reason: str | None = None,
    ) -> None:
        self._running = False
        self._allow_close = True
        self.continue_button.setVisible(paused and can_continue)
        self._primary_mode = "export"
        self.accept_button.setText("Kühlturm exportieren")
        self.accept_button.show()
        self.accept_button.setEnabled(True)
        self.abort_button.setText("Schließen")
        if status_text:
            self.counter_label.setText(status_text)
        self.stop_reason_label.setText(stop_reason or "")
        stop_reason_state = (
            "within"
            if self._best_deviation_s is not None
            and abs(self._best_deviation_s) <= self._tolerance_s + 1e-9
            else "outside"
        )
        self._set_result_state(
            self.stop_reason_label,
            stop_reason_state,
        )
        self.stop_reason_divider.setVisible(bool(stop_reason))
        self.stop_reason_label.setVisible(bool(stop_reason))
        self._fit_and_center()

    def resume_waiting(self) -> None:
        self._running = True
        self._allow_close = False
        self._primary_mode = "accept"
        self.continue_button.hide()
        self.stop_reason_divider.hide()
        self.stop_reason_label.hide()
        self.accept_button.setText("Bestes Ergebnis übernehmen")
        self.accept_button.setVisible(
            self._completed_joint_slices >= self._minimum_joint_slices
        )
        self.accept_button.setEnabled(
            self._completed_joint_slices >= self._minimum_joint_slices
        )
        self.abort_button.setText("Generierung abbrechen")
        self._fit_and_center()

    def show_error(self, message: str) -> None:
        self._running = False
        self._allow_close = True
        self.error_label.setText(message)
        self.error_divider.show()
        self.error_label.show()
        self.continue_button.hide()
        self.stop_reason_divider.hide()
        self.stop_reason_label.hide()
        self._primary_mode = "accept"
        self.accept_button.hide()
        self.accept_button.setEnabled(False)
        self.abort_button.setText("Schließen")
        self._fit_and_center()

    def allow_programmatic_close(self) -> None:
        self._allow_close = True

    def _set_best_metrics_visible(self, visible: bool) -> None:
        self.best_deviation_value.setVisible(visible)
        if not visible:
            self.best_minimum_value.setText(
                "Noch kein gemeinsamer Slice abgeschlossen."
            )

    @staticmethod
    def _set_result_state(widget: QWidget, state: str) -> None:
        widget.setProperty("resultState", state)
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)

    def _fit_and_center(self) -> None:
        """Apply deterministic content geometry and keep the dialog centered."""

        layout = self.layout()
        self.setMinimumHeight(0)
        self.setMaximumHeight(16_777_215)
        layout.invalidate()
        layout.activate()
        target_height = max(
            layout.minimumSize().height(),
            layout.totalHeightForWidth(GENERATION_DIALOG_WIDTH_PX),
        )
        self.setFixedSize(GENERATION_DIALOG_WIDTH_PX, target_height)
        layout.activate()
        required_counter_top = self.image_progress.geometry().bottom() + 12
        missing_height = required_counter_top - self.counter_label.geometry().top()
        if missing_height > 0:
            self.setFixedHeight(self.height() + missing_height)
            layout.activate()

        parent = self.parentWidget()
        if parent is None:
            return
        parent_window = parent.window()
        target_frame = self.frameGeometry()
        target_frame.moveCenter(parent_window.frameGeometry().center())
        screen = self.screen() or parent_window.screen()
        if screen is not None:
            available = screen.availableGeometry()
            target_frame.moveLeft(
                max(
                    available.left(),
                    min(
                        target_frame.left(),
                        available.right() - target_frame.width() + 1,
                    ),
                )
            )
            target_frame.moveTop(
                max(
                    available.top(),
                    min(
                        target_frame.top(),
                        available.bottom() - target_frame.height() + 1,
                    ),
                )
            )
        self.move(target_frame.topLeft())

    def _activate_primary_action(self) -> None:
        if self._primary_mode == "export":
            self.export_requested.emit()
        else:
            self.accept_requested.emit()

    def _abort(self) -> None:
        if self._running:
            self.abort_requested.emit()
        self._allow_close = True
        self.reject()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._running and not self._allow_close:
            self.abort_requested.emit()
        self._allow_close = True
        super().closeEvent(event)


class JointSliceSettingsDialog(QDialog):
    value_applied = Signal(int)
    separate_value_applied = Signal(int)
    output_root_applied = Signal(str)
    local_window_applied = Signal(int)
    layer_time_tolerance_applied = Signal(float)

    def __init__(
        self,
        value: int,
        parent: QWidget | None = None,
        *,
        output_root: str = "",
        default_output_root: str = "",
        maximum_separate_slices: int = DEFAULT_MAXIMUM_SEPARATE_SLICES,
        default_maximum_separate_slices: int = DEFAULT_MAXIMUM_SEPARATE_SLICES,
        default_maximum_joint_slices: int = DEFAULT_MAXIMUM_JOINT_SLICES,
        local_reference_window: int = 51,
        default_local_reference_window: int = 51,
        maximum_local_reference_window: int = 999,
        layer_time_tolerance_s: float = 0.25,
        default_layer_time_tolerance_s: float = 0.25,
        preparation_ready: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("jointSliceSettingsDialog")
        self.setWindowTitle("Allgemeine Einstellungen")
        self.setModal(True)
        self.setMinimumWidth(GENERAL_SETTINGS_DIALOG_WIDTH_PX)
        self.default_maximum_joint_slices = max(
            5, min(20, int(default_maximum_joint_slices))
        )
        self.default_maximum_separate_slices = max(
            1, min(15, int(default_maximum_separate_slices))
        )
        self._preparation_ready = bool(preparation_ready)
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)
        content = QWidget(self)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(8)
        outer_layout.addWidget(content)
        title = QLabel("Allgemeine Einstellungen")
        title.setObjectName("dialogTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        self.preparation_hint = QLabel(
            "Diese Einstellungen sind nach erfolgreichem Abschluss der "
            "Vorbereitungen verfügbar."
        )
        self.preparation_hint.setObjectName("generalSettingsPreparationHint")
        self.preparation_hint.setWordWrap(True)
        self.preparation_hint.setVisible(not preparation_ready)
        layout.addWidget(self.preparation_hint)
        self.settings_panel = QWidget(content)
        self.settings_panel.setObjectName("generalSettingsPanel")
        settings_panel_layout = QVBoxLayout(self.settings_panel)
        settings_panel_layout.setContentsMargins(0, 0, 0, 0)
        settings_panel_layout.setSpacing(8)
        layout.addWidget(self.settings_panel)
        separate_row = QHBoxLayout()
        separate_row.setSpacing(METRICS.setting_info_text_gap_px)
        self.separate_info_button = InfoToolButton(
            SEPARATE_SLICE_HINT,
            self,
            accessible_name="Informationen zur maximalen Anzahl getrennter Slices",
            accessible_hint=SEPARATE_SLICE_HINT_ACCESSIBLE,
            object_name="settingInfoButton",
            diameter_px=METRICS.setting_info_diameter_px,
        )
        separate_row.addWidget(
            self.separate_info_button, 0, Qt.AlignmentFlag.AlignVCenter
        )
        self.maximum_separate_slices_label = QLabel("Max. getrennte Slices:")
        self.maximum_separate_slices_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        separate_row.addWidget(
            self.maximum_separate_slices_label,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )
        self.separate_spin_box = QSpinBox()
        self.separate_spin_box.setObjectName("maximumSeparateSlicesSpin")
        self.separate_spin_box.setRange(1, 15)
        self.separate_spin_box.setValue(
            max(1, min(15, int(maximum_separate_slices)))
        )
        self.separate_spin_box.setSuffix(" Slices")
        self.separate_spin_box.setFixedWidth(GENERAL_SETTINGS_NUMBER_WIDTH_PX)
        self.separate_spin_box.lineEdit().returnPressed.connect(self.accept)
        separate_row.addStretch(1)
        separate_row.addWidget(self.separate_spin_box)
        self.separate_reset_button = QPushButton("↺")
        self.separate_reset_button.setObjectName("settingResetButton")
        self.separate_reset_button.setFixedSize(
            METRICS.reset_button_size_px,
            METRICS.reset_button_size_px,
        )
        self.separate_reset_button.setAccessibleName(
            "Getrennte Slices auf den Standardwert "
            f"{self.default_maximum_separate_slices} zurücksetzen"
        )
        self.separate_reset_button.setToolTip(
            "Auf Standardwert "
            f"{self.default_maximum_separate_slices} zurücksetzen"
        )
        self.separate_reset_button.clicked.connect(
            lambda: self.separate_spin_box.setValue(
                self.default_maximum_separate_slices
            )
        )
        self.separate_spin_box.valueChanged.connect(
            self._refresh_separate_reset_button
        )
        separate_row.addWidget(self.separate_reset_button)
        self.separate_settings_row_layout = separate_row
        settings_panel_layout.addLayout(separate_row)
        row = QHBoxLayout()
        row.setSpacing(METRICS.setting_info_text_gap_px)
        self.info_button = InfoToolButton(
            JOINT_SLICE_HINT,
            self,
            accessible_name="Informationen zur maximalen Anzahl gemeinsamer Slices",
            accessible_hint=JOINT_SLICE_HINT_ACCESSIBLE,
            object_name="settingInfoButton",
            diameter_px=METRICS.setting_info_diameter_px,
        )
        row.addWidget(self.info_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.maximum_joint_slices_label = QLabel("Max. gemeinsame Slices:")
        self.maximum_joint_slices_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        row.addWidget(
            self.maximum_joint_slices_label,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )
        self.spin_box = QSpinBox()
        self.spin_box.setObjectName("maximumJointSlicesSpin")
        self.spin_box.setRange(5, 20)
        self.spin_box.setValue(max(5, min(20, int(value))))
        self.spin_box.setSuffix(" Slices")
        self.spin_box.setFixedWidth(GENERAL_SETTINGS_NUMBER_WIDTH_PX)
        self.spin_box.lineEdit().returnPressed.connect(self.accept)
        row.addStretch(1)
        row.addWidget(self.spin_box)
        self.reset_button = QPushButton("↺")
        self.reset_button.setObjectName("settingResetButton")
        self.reset_button.setFixedSize(
            METRICS.reset_button_size_px,
            METRICS.reset_button_size_px,
        )
        self.reset_button.setAccessibleName(
            "Gemeinsame Slices auf den Standardwert "
            f"{self.default_maximum_joint_slices} zurücksetzen"
        )
        self.reset_button.setToolTip(
            f"Auf Standardwert {self.default_maximum_joint_slices} zurücksetzen"
        )
        self.reset_button.clicked.connect(
            lambda: self.spin_box.setValue(self.default_maximum_joint_slices)
        )
        self.spin_box.valueChanged.connect(self._refresh_reset_button)
        row.addWidget(self.reset_button)
        self.settings_row_layout = row
        settings_panel_layout.addLayout(row)
        tolerance_row = QHBoxLayout()
        tolerance_row.setSpacing(METRICS.setting_info_text_gap_px)
        self.tolerance_info_button = InfoToolButton(
            SETTING_INFO_TEXTS["layer_time_tolerance_s"],
            self,
            accessible_name="Informationen zur Layerzeit-Toleranz",
            accessible_hint=(
                "Layerzeit-Toleranz. Dieser Wert bestimmt, wie weit die erreichte "
                "Layerzeit von der gewünschten Layerzeit abweichen darf, damit "
                "das Ergebnis noch als zufriedenstellend gilt. "
                "Bereich: 0,1 bis 3 Sekunden. Standard: 0,25 Sekunden. "
                "Eine kleinere Toleranz kann mehr Kalibrierungsdurchläufe erfordern."
            ),
            object_name="settingInfoButton",
            diameter_px=METRICS.setting_info_diameter_px,
        )
        tolerance_row.addWidget(
            self.tolerance_info_button, 0, Qt.AlignmentFlag.AlignVCenter
        )
        self.tolerance_label = QLabel("Layerzeit-Toleranz (±):")
        self.tolerance_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        tolerance_row.addWidget(
            self.tolerance_label, 0, Qt.AlignmentFlag.AlignVCenter
        )
        tolerance_row.addStretch(1)
        self.tolerance_spin_box = QDoubleSpinBox()
        self.tolerance_spin_box.setObjectName("layerTimeTolerance")
        self.tolerance_spin_box.setRange(0.1, 3.0)
        self.tolerance_spin_box.setDecimals(2)
        self.tolerance_spin_box.setSingleStep(0.01)
        self.tolerance_spin_box.setSuffix(" Sek.")
        self.tolerance_spin_box.setFixedWidth(GENERAL_SETTINGS_NUMBER_WIDTH_PX)
        self.tolerance_spin_box.setValue(layer_time_tolerance_s)
        self.tolerance_spin_box.lineEdit().returnPressed.connect(self.accept)
        tolerance_row.addWidget(self.tolerance_spin_box)
        self.default_layer_time_tolerance_s = max(
            0.1, min(3.0, float(default_layer_time_tolerance_s))
        )
        self.tolerance_reset_button = QPushButton("↺")
        self.tolerance_reset_button.setObjectName("settingResetButton")
        self.tolerance_reset_button.setFixedSize(
            METRICS.reset_button_size_px, METRICS.reset_button_size_px
        )
        self.tolerance_reset_button.setAccessibleName(
            "Layerzeit-Toleranz auf den Standardwert zurücksetzen"
        )
        self.tolerance_reset_button.setToolTip(
            "Auf Standardwert "
            f"{self.default_layer_time_tolerance_s:g}".replace(".", ",")
            + " Sek. zurücksetzen"
        )
        self.tolerance_reset_button.clicked.connect(
            lambda: self.tolerance_spin_box.setValue(self.default_layer_time_tolerance_s)
        )
        self.tolerance_spin_box.valueChanged.connect(
            self._refresh_tolerance_reset_button
        )
        tolerance_row.addWidget(self.tolerance_reset_button)
        self.tolerance_settings_row_layout = tolerance_row
        settings_panel_layout.insertLayout(0, tolerance_row)
        local_row = QHBoxLayout()
        local_row.setSpacing(METRICS.setting_info_text_gap_px)
        self.local_window_info_button = InfoToolButton(
            SETTING_INFO_TEXTS["local_reference_window"],
            self,
            accessible_name="Informationen zum lokalen Zeitfenster",
            object_name="settingInfoButton",
            diameter_px=METRICS.setting_info_diameter_px,
        )
        local_row.addWidget(self.local_window_info_button)
        self.local_window_label = QLabel("Layer im lokalen Zeitfenster:")
        local_row.addWidget(self.local_window_label)
        local_row.addStretch(1)
        self.local_window_spin_box = QSpinBox()
        self.local_window_spin_box.setObjectName("localReferenceWindow")
        maximum_window = max(1, min(999, int(maximum_local_reference_window)))
        self.local_window_spin_box.setRange(1, maximum_window)
        self.local_window_spin_box.setSingleStep(2)
        self.local_window_spin_box.setValue(
            max(1, min(maximum_window, int(local_reference_window)))
        )
        self.local_window_spin_box.setSuffix(" Layer")
        self.local_window_spin_box.setFixedWidth(GENERAL_SETTINGS_NUMBER_WIDTH_PX)
        local_row.addWidget(self.local_window_spin_box)
        self.default_local_reference_window = max(
            1, min(maximum_window, int(default_local_reference_window))
        )
        if self.default_local_reference_window % 2 == 0:
            self.default_local_reference_window -= 1
        self.local_window_reset_button = QPushButton("↺")
        self.local_window_reset_button.setObjectName("settingResetButton")
        self.local_window_reset_button.setFixedSize(
            METRICS.reset_button_size_px, METRICS.reset_button_size_px
        )
        self.local_window_reset_button.setAccessibleName(
            "Lokales Zeitfenster auf den Standardwert zurücksetzen"
        )
        self.local_window_reset_button.setToolTip(
            f"Auf Standardwert {self.default_local_reference_window} zurücksetzen"
        )
        self.local_window_reset_button.clicked.connect(
            lambda: self.local_window_spin_box.setValue(self.default_local_reference_window)
        )
        self.local_window_spin_box.valueChanged.connect(
            self._refresh_local_window_reset_button
        )
        local_row.addWidget(self.local_window_reset_button)
        settings_panel_layout.addLayout(local_row)
        layout.addWidget(QLabel("Exportordner"))
        export_row = QHBoxLayout()
        self.output_root_edit = QLineEdit(output_root)
        self.output_root_edit.setObjectName("generalSettingsOutputRoot")
        self.output_root_edit.setAccessibleName("Exportordner")
        self.output_root_edit.setFixedHeight(METRICS.form_control_height_px)
        export_row.addWidget(self.output_root_edit, 1, Qt.AlignmentFlag.AlignVCenter)
        browse = QPushButton("Auswählen …")
        browse.setObjectName("generalSettingsBrowseButton")
        browse.setFixedHeight(METRICS.form_control_height_px)
        def select_output():
            selected = QFileDialog.getExistingDirectory(self, "Exportordner auswählen", self.output_root_edit.text())
            if selected:
                self.output_root_edit.setText(selected)
        browse.clicked.connect(select_output)
        export_row.addWidget(browse, 0, Qt.AlignmentFlag.AlignVCenter)
        self.output_reset_button = QPushButton("↺")
        self.output_reset_button.setObjectName("settingResetButton")
        self.output_reset_button.setFixedSize(
            METRICS.reset_button_size_px,
            METRICS.reset_button_size_px,
        )
        self.output_reset_button.setToolTip(
            "Exportordner auf Standardwert zurücksetzen"
        )
        self.output_reset_button.setAccessibleName(
            "Exportordner auf Standardwert zurücksetzen"
        )
        self.output_reset_button.clicked.connect(
            lambda: self.output_root_edit.setText(default_output_root)
        )
        self.output_root_edit.textChanged.connect(
            self._refresh_output_reset_button
        )
        export_row.addWidget(self.output_reset_button, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(export_row)
        self.footer_divider = QFrame(self)
        self.footer_divider.setObjectName("generalSettingsFooterDivider")
        self.footer_divider.setFrameShape(QFrame.Shape.HLine)
        self.footer_divider.setFixedHeight(1)
        outer_layout.addWidget(self.footer_divider)
        footer = QWidget(self)
        footer.setObjectName("generalSettingsFooter")
        actions = QHBoxLayout(footer)
        actions.setContentsMargins(22, 20, 22, 20)
        self.general_reset_button = QPushButton("Standardwerte wiederherstellen")
        self.general_reset_button.setObjectName("generalSettingsResetButton")
        self.general_reset_button.setAccessibleName(
            "Allgemeine Einstellungen auf Standardwerte zurücksetzen"
        )
        self.general_reset_button.setToolTip(
            "Alle allgemeinen Einstellungen auf Standardwerte zurücksetzen"
        )
        self.general_reset_button.setEnabled(preparation_ready)
        self.general_reset_button.clicked.connect(self._reset_general_settings)
        self.general_reset_button.setFixedHeight(METRICS.info_button_diameter_px)
        actions.addWidget(self.general_reset_button)
        actions.addStretch(1)
        cancel = QPushButton("Abbrechen")
        cancel.setFixedHeight(METRICS.info_button_diameter_px)
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        apply_button = QPushButton("Übernehmen")
        apply_button.setFixedHeight(METRICS.info_button_diameter_px)
        apply_button.setObjectName("primaryButton")
        apply_button.setDefault(True)
        apply_button.setAutoDefault(True)
        apply_button.clicked.connect(self.accept)
        actions.addWidget(apply_button)
        outer_layout.addWidget(footer)
        self.apply_button = apply_button
        self._default_output_root = default_output_root
        for signal in (
            self.separate_spin_box.valueChanged,
            self.spin_box.valueChanged,
            self.tolerance_spin_box.valueChanged,
            self.local_window_spin_box.valueChanged,
            self.output_root_edit.textChanged,
        ):
            signal.connect(self._refresh_general_reset_button)
        self._refresh_separate_reset_button()
        self._refresh_reset_button()
        self._refresh_tolerance_reset_button()
        self._refresh_local_window_reset_button()
        self._refresh_output_reset_button()
        self._refresh_general_reset_button()
        # Keep the information controls active while their settings are unavailable.
        for widget in (
            self.tolerance_label,
            self.tolerance_spin_box,
            self.maximum_separate_slices_label,
            self.separate_spin_box,
            self.maximum_joint_slices_label,
            self.spin_box,
            self.local_window_label,
            self.local_window_spin_box,
        ):
            widget.setEnabled(self._preparation_ready)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def _reset_general_settings(self) -> None:
        self.separate_spin_box.setValue(self.default_maximum_separate_slices)
        self.spin_box.setValue(self.default_maximum_joint_slices)
        self.tolerance_spin_box.setValue(self.default_layer_time_tolerance_s)
        self.local_window_spin_box.setValue(self.default_local_reference_window)
        self.output_root_edit.setText(self._default_output_root)

    def _refresh_general_reset_button(self) -> None:
        self.general_reset_button.setEnabled(
            self._preparation_ready
            and (
                self.separate_spin_box.value() != self.default_maximum_separate_slices
                or self.spin_box.value() != self.default_maximum_joint_slices
                or self.tolerance_spin_box.value()
                != self.default_layer_time_tolerance_s
                or self.local_window_spin_box.value()
                != self.default_local_reference_window
                or self.output_root_edit.text() != self._default_output_root
            )
        )

    def accept(self) -> None:
        if not self.output_root_edit.text().strip() and self.output_root_edit.text() != "":
            self.output_root_edit.setFocus()
            return
        self.output_root_applied.emit(self.output_root_edit.text().strip())
        self.layer_time_tolerance_applied.emit(self.tolerance_spin_box.value())
        self.separate_value_applied.emit(self.separate_spin_box.value())
        self.local_window_applied.emit(self.local_window_spin_box.value())
        self.value_applied.emit(self.spin_box.value())
        super().accept()

    def _refresh_reset_button(self) -> None:
        modified = self.spin_box.value() != self.default_maximum_joint_slices
        self.reset_button.setEnabled(self._preparation_ready and modified)
        self.reset_button.setProperty("modified", modified)
        style = self.reset_button.style()
        style.unpolish(self.reset_button)
        style.polish(self.reset_button)

    def _refresh_separate_reset_button(self) -> None:
        modified = (
            self.separate_spin_box.value()
            != self.default_maximum_separate_slices
        )
        self.separate_reset_button.setEnabled(self._preparation_ready and modified)
        self.separate_reset_button.setProperty("modified", modified)
        style = self.separate_reset_button.style()
        style.unpolish(self.separate_reset_button)
        style.polish(self.separate_reset_button)

    def _refresh_output_reset_button(self) -> None:
        modified = self.output_root_edit.text() != self._default_output_root
        self.output_reset_button.setEnabled(modified)
        self.output_reset_button.setProperty("modified", modified)
        style = self.output_reset_button.style()
        style.unpolish(self.output_reset_button)
        style.polish(self.output_reset_button)

    def _refresh_local_window_reset_button(self) -> None:
        modified = (
            self.local_window_spin_box.value()
            != self.default_local_reference_window
        )
        self.local_window_reset_button.setEnabled(self._preparation_ready and modified)
        self.local_window_reset_button.setProperty("modified", modified)
        style = self.local_window_reset_button.style()
        style.unpolish(self.local_window_reset_button)
        style.polish(self.local_window_reset_button)

    def _refresh_tolerance_reset_button(self) -> None:
        modified = self.tolerance_spin_box.value() != self.default_layer_time_tolerance_s
        self.tolerance_reset_button.setEnabled(self._preparation_ready and modified)
        self.tolerance_reset_button.setProperty("modified", modified)
        style = self.tolerance_reset_button.style()
        style.unpolish(self.tolerance_reset_button)
        style.polish(self.tolerance_reset_button)
