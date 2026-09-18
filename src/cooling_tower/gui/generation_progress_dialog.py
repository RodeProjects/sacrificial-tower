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
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from cooling_tower.gui.widgets.info_tool_button import InfoToolButton


DEFAULT_MAXIMUM_JOINT_SLICES = 10
GENERATION_DIALOG_WIDTH_PX = 610
JOINT_SLICE_HINT = (
    "Die Angleichung endet spätestens nach dieser Anzahl gemeinsamer Slices – "
    "oder früher bei höchstens ±0,1 s Zielabweichung, manueller Übernahme "
    "oder ausbleibender Verbesserung."
)


class TowerImageProgress(QWidget):
    """Render a proportional image fill and a short completion pulse."""

    def __init__(self, image_path: str | Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("towerImageProgress")
        self._pixmap = QPixmap(str(image_path))
        self._fill = 0.0
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
            (self.width() - 209.0) / 2.0,
            (self.height() - 239.5) / 2.0,
            209.0,
            239.5,
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
        if self._fill > 0.0:
            filled_height = target.height() * self._fill
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
            "angeglichen. Sind Sie mit dem bisher besten Ergebnis zufrieden, "
            "können Sie das bisher beste Ergebnis jederzeit übernehmen und "
            "anschließend exportieren."
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

    def begin(self, target_s: float, tolerance_s: float, completed: int, maximum: int) -> None:
        # A newly created owned dialog can briefly inherit the maximized
        # native state of its main window on Windows.  Clear that state before
        # its first show so the reveal filter only ever exposes the natural
        # content-sized geometry.
        self.setWindowState(Qt.WindowState.WindowNoState)
        self._running = True
        self._allow_close = False
        self._tolerance_s = max(0.0, float(tolerance_s))
        self._best_deviation_s = None
        self.target_value.setText(
            f"{target_s:.2f} s (± {tolerance_s:.2f} s Toleranz)"
        )
        self.counter_label.setText(
            f"{completed} von {maximum} gemeinsamen Slices abgeschlossen"
        )
        self.image_progress.set_fill(0.0)
        self._set_best_metrics_visible(False)
        self._primary_mode = "accept"
        self.accept_button.setEnabled(completed > 0)
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
        QTimer.singleShot(0, self._fit_and_center)
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
        self.counter_label.setText(
            f"{completed} von {maximum} gemeinsamen Slices abgeschlossen"
        )
        self.image_progress.animate_fill(1.0, pulse_when_finished=True)
        self.accept_button.setEnabled(True)
        timings = tuple(
            getattr(getattr(best_iteration, "evaluation", None), "layer_timings", ())
        )
        values = [
            float(item.combined_layer_time_s)
            for item in timings
            if getattr(item, "combined_layer_time_s", None) is not None
        ]
        if values:
            minimum = min(values)
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
        self.accept_button.setEnabled(True)
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

    def __init__(self, value: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("jointSliceSettingsDialog")
        self.setWindowTitle("Allgemeine Einstellungen")
        self.setModal(True)
        self.setMinimumWidth(650)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)
        title = QLabel("Allgemeine Einstellungen")
        title.setObjectName("dialogTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        row = QHBoxLayout()
        self.info_button = InfoToolButton(
            JOINT_SLICE_HINT,
            self,
            accessible_name="Informationen zur maximalen Anzahl gemeinsamer Slices",
            object_name="settingInfoButton",
            diameter_px=24,
        )
        row.addWidget(self.info_button)
        self.maximum_joint_slices_label = QLabel("Max. gemeinsame Slices:")
        row.addWidget(self.maximum_joint_slices_label)
        self.spin_box = QSpinBox()
        self.spin_box.setObjectName("maximumJointSlicesSpin")
        self.spin_box.setRange(5, 25)
        self.spin_box.setValue(max(5, min(25, int(value))))
        self.spin_box.setSuffix(" Slices")
        self.spin_box.lineEdit().returnPressed.connect(self.accept)
        row.addStretch(1)
        row.addWidget(self.spin_box)
        self.reset_button = QPushButton("↺")
        self.reset_button.setObjectName("settingResetButton")
        self.reset_button.setAccessibleName(
            "Gemeinsame Slices auf den Standardwert 10 zurücksetzen"
        )
        self.reset_button.setToolTip("Auf Standardwert 10 zurücksetzen")
        self.reset_button.clicked.connect(
            lambda: self.spin_box.setValue(DEFAULT_MAXIMUM_JOINT_SLICES)
        )
        self.spin_box.valueChanged.connect(self._refresh_reset_button)
        row.addWidget(self.reset_button)
        self.settings_row_layout = row
        layout.addLayout(row)
        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton("Abbrechen")
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        apply_button = QPushButton("Übernehmen")
        apply_button.setObjectName("primaryButton")
        apply_button.setDefault(True)
        apply_button.setAutoDefault(True)
        apply_button.clicked.connect(self.accept)
        actions.addWidget(apply_button)
        layout.addLayout(actions)
        self.apply_button = apply_button
        self._refresh_reset_button()

    def accept(self) -> None:
        self.value_applied.emit(self.spin_box.value())
        super().accept()

    def _refresh_reset_button(self) -> None:
        modified = self.spin_box.value() != DEFAULT_MAXIMUM_JOINT_SLICES
        self.reset_button.setEnabled(modified)
        self.reset_button.setProperty("modified", modified)
        style = self.reset_button.style()
        style.unpolish(self.reset_button)
        style.polish(self.reset_button)
