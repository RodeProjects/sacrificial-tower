"""Wheel-safe numeric editors that report attempts hidden by Qt hard bounds."""
from PySide6.QtCore import QTimer,Signal
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
