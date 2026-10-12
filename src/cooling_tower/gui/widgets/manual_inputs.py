"""Wheel-safe numeric editors that report attempts hidden by Qt hard bounds."""
from PySide6.QtCore import QTimer,Signal,QVariantAnimation
from PySide6.QtGui import QColor,QPalette
from cooling_tower.gui.design_tokens import SETTING_BOUNDARY_FEEDBACK_HOLD_MS,BOUNDARY_FEEDBACK_FADE_MS,COLORS
from cooling_tower.gui.widgets.numeric_setting import NumericSettingWidget
from cooling_tower.gui.widgets.wheel_safe_inputs import WheelSafeDoubleSpinBox,WheelSafeSpinBox


class _AttemptAware:
    def _inspect_attempt(self,text):
        value,valid = self.locale().toDouble(text.strip())
        if valid and self.hasFocus() and (value < self.minimum() or value > self.maximum()):
            if not getattr(self,"_attempt_pending",False):
                self._attempt_pending = True
                self._attempt_value = value
                QTimer.singleShot(0,self._emit_attempt)

    def _emit_attempt(self):
        self._attempt_pending = False
        self.limit_attempted.emit(self._attempt_value)

    def stepBy(self,steps):
        attempted = self.value()+steps*self.singleStep()
        super().stepBy(steps)
        if attempted < self.minimum() or attempted > self.maximum():
            self._attempt_value = attempted
            if not getattr(self,"_attempt_pending",False):
                self._attempt_pending = True
                QTimer.singleShot(0,self._emit_attempt)


class ManualDoubleSpinBox(_AttemptAware,WheelSafeDoubleSpinBox):
    limit_attempted = Signal(float)
    def validate(self,text,position):
        self._inspect_attempt(text)
        return super().validate(text,position)


class ManualSpinBox(_AttemptAware,WheelSafeSpinBox):
    limit_attempted = Signal(float)
    def validate(self,text,position):
        self._inspect_attempt(text)
        return super().validate(text,position)


class ManualNumericSettingWidget(NumericSettingWidget):
    """Pulse only the label and input border; keep the form's geometry fixed."""
    error_feedback_finished = Signal()

    def __init__(self,**kwargs):
        super().__init__(**kwargs)
        duration=SETTING_BOUNDARY_FEEDBACK_HOLD_MS+BOUNDARY_FEEDBACK_FADE_MS
        self._feedback_animation=QVariantAnimation(self)
        self._feedback_animation.setDuration(duration)
        self._feedback_animation.setStartValue(1.)
        self._feedback_animation.setKeyValueAt(SETTING_BOUNDARY_FEEDBACK_HOLD_MS/duration,1.)
        self._feedback_animation.setEndValue(0.)
        self._feedback_animation.valueChanged.connect(self._set_feedback_amount)
        self._feedback_animation.finished.connect(lambda:self.set_error(None))
        self._feedback_message=None
        self._feedback_amount=0.

    def _update_reset_metadata(self):
        available = self.default_provider() is not None
        self.reset_button.setVisible(available)
        if available:
            super()._update_reset_metadata()

    def _update_modified_state(self,_value=None):
        if self.default_provider() is None:
            self.reset_button.setEnabled(False)
            self.reset_button.setProperty("modified",False)
            return
        super()._update_modified_state(_value)

    def set_error(self,message):
        if not message:
            if self._feedback_message is None:return False
            self._feedback_animation.stop()
            self.label.setStyleSheet(self._normal_label_style)
            self.editor.setStyleSheet(self._normal_editor_style)
            self.editor.setAccessibleDescription(self._normal_description)
            self._feedback_message=None
            self._feedback_amount=0.
            self.error_feedback_finished.emit()
            return True
        if self._feedback_animation.state() == QVariantAnimation.State.Running:
            return False
        self.label.ensurePolished()
        self._normal_label_style=self.label.styleSheet()
        self._normal_editor_style=self.editor.styleSheet()
        self._normal_label_color=self.label.palette().color(QPalette.ColorRole.WindowText)
        self._normal_description=self.editor.accessibleDescription()
        self._feedback_message=str(message)
        self.editor.setAccessibleDescription(str(message))
        self._set_feedback_amount(1.)
        self._feedback_animation.start()
        return True

    def _set_feedback_amount(self,value):
        self._feedback_amount=float(value)
        red=QColor(COLORS["error"])
        def blend(normal):
            return QColor(*(round(a+(b-a)*self._feedback_amount)
                for a,b in zip(normal.getRgb()[:3],red.getRgb()[:3]))).name()
        self.label.setStyleSheet(self._normal_label_style+f" QLabel {{ color: {blend(self._normal_label_color)}; }}")
        border=blend(QColor("#b8c5d1"))
        self.editor.setStyleSheet(self._normal_editor_style+
            f" QAbstractSpinBox, QAbstractSpinBox:hover, QAbstractSpinBox:focus {{ border-color: {border}; }}")
