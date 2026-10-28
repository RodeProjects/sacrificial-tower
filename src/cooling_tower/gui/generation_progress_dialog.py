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
    QFileDialog,
    QLineEdit,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cooling_tower.gui.design_tokens import METRICS
from cooling_tower.export_paths import EXPORT_METHOD_LABELS, normalize_export_roots, default_export_roots as export_root_defaults


DEFAULT_MAXIMUM_JOINT_SLICES = 12
DEFAULT_MAXIMUM_SEPARATE_SLICES = 6
MINIMUM_JOINT_SLICES_BEFORE_ACCEPT = 3
GENERATION_DIALOG_WIDTH_PX = 610
GENERAL_SETTINGS_DIALOG_WIDTH_PX = 707
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
    """Edit export folders; generation settings are part of the main form."""

    output_root_applied = Signal(str)
    export_roots_applied = Signal(dict)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        output_root: str = "",
        default_output_root: str = "",
        export_roots: dict[str, str] | None = None,
        default_export_roots: dict[str, str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("jointSliceSettingsDialog")
        self.setWindowTitle("Allgemeine Einstellungen")
        self.setModal(True)
        self.setMinimumWidth(GENERAL_SETTINGS_DIALOG_WIDTH_PX)
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
        self.export_root_edits = {}
        self.export_reset_buttons = {}
        self.export_browse_buttons = {}
        self._default_export_roots = normalize_export_roots(default_export_roots)
        roots = normalize_export_roots(export_roots)
        # Preserve the dialog's existing automatic-folder API for other callers.
        self._default_export_roots.setdefault("automatic", default_output_root or export_root_defaults("output")["automatic"])
        roots.setdefault("automatic", output_root or self._default_export_roots["automatic"])
        for method, label in EXPORT_METHOD_LABELS.items():
            default = self._default_export_roots.get(method,
                export_root_defaults(Path(self._default_export_roots["automatic"]).parent)[method])
            self._default_export_roots[method] = default
            export_row = QHBoxLayout()
            folder_label = QLabel(f"Exportordner · {label}")
            folder_label.setFixedWidth(185)
            export_row.addWidget(folder_label)
            edit = QLineEdit(roots.get(method, default))
            edit.setMinimumWidth(0)
            folder_label.setBuddy(edit)
            edit.setObjectName("generalSettingsOutputRoot" if method == "automatic" else f"{method}ExportRoot")
            edit.setProperty("methodExportRoot", True)
            edit.setAccessibleName(f"Exportordner {label}")
            edit.setFixedHeight(METRICS.form_control_height_px)
            export_row.addWidget(edit, 1, Qt.AlignmentFlag.AlignVCenter)
            browse = QPushButton("Auswählen …")
            browse.setObjectName("generalSettingsBrowseButton")
            browse.setAccessibleName(f"Exportordner {label} auswählen")
            browse.setFixedHeight(METRICS.form_control_height_px)
            browse.clicked.connect(lambda _checked=False, key=method: self._select_export_root(key))
            export_row.addWidget(browse, 0, Qt.AlignmentFlag.AlignVCenter)
            reset = QPushButton("↺")
            reset.setObjectName("settingResetButton")
            reset.setFixedSize(METRICS.reset_button_size_px, METRICS.reset_button_size_px)
            reset.setToolTip(f"Exportordner {label} auf Standardwert zurücksetzen")
            reset.setAccessibleName(f"Exportordner {label} auf Standardwert zurücksetzen")
            reset.clicked.connect(lambda _checked=False, key=method: self.export_root_edits[key].setText(self._default_export_roots[key]))
            edit.textChanged.connect(self._refresh_output_reset_button)
            export_row.addWidget(reset, 0, Qt.AlignmentFlag.AlignVCenter)
            layout.addLayout(export_row)
            self.export_root_edits[method] = edit
            self.export_reset_buttons[method] = reset
            self.export_browse_buttons[method] = browse
        self.output_root_edit = self.export_root_edits["automatic"]
        self.output_reset_button = self.export_reset_buttons["automatic"]
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
        for edit in self.export_root_edits.values():
            edit.textChanged.connect(self._refresh_general_reset_button)
        self._refresh_output_reset_button()
        self._refresh_general_reset_button()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def _reset_general_settings(self) -> None:
        for method, edit in self.export_root_edits.items():
            edit.setText(self._default_export_roots[method])

    def _refresh_general_reset_button(self) -> None:
        self.general_reset_button.setEnabled(any(
            edit.text() != self._default_export_roots[method]
            for method, edit in self.export_root_edits.items()
        ))

    def accept(self) -> None:
        for edit in self.export_root_edits.values():
            text = edit.text()
            if not text.strip() or any(ord(char) < 32 for char in text):
                edit.setFocus()
                return
        self.export_roots_applied.emit({method: edit.text().strip() for method, edit in self.export_root_edits.items()})
        self.output_root_applied.emit(self.output_root_edit.text().strip())
        super().accept()

    def _select_export_root(self, method: str) -> None:
        edit = self.export_root_edits[method]
        selected = QFileDialog.getExistingDirectory(self, "Exportordner auswählen", edit.text())
        if selected:
            edit.setText(selected)

    def _refresh_output_reset_button(self) -> None:
        for method, edit in self.export_root_edits.items():
            button = self.export_reset_buttons[method]
            modified = edit.text() != self._default_export_roots[method]
            button.setEnabled(modified)
            button.setProperty("modified", modified)
            button.style().unpolish(button)
            button.style().polish(button)
