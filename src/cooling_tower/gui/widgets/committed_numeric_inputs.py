"""Numeric drafts stay untouched until Enter, focus loss or explicit stepping."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re

from PySide6.QtCore import QLocale
from PySide6.QtGui import QValidator

from cooling_tower.gui.widgets.wheel_safe_inputs import WheelSafeDoubleSpinBox, WheelSafeSpinBox


class _CommittedInput:
    _integer = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setLocale(QLocale(QLocale.Language.German, QLocale.Country.Germany))
        self.setKeyboardTracking(False)
        self.input_pending = False
        self.lineEdit().textEdited.connect(self._draft_edited)
        self.editingFinished.connect(self._draft_finished)

    def _draft_edited(self, _text):
        self.input_pending = True

    def _draft_finished(self):
        self.input_pending = False

    def setValue(self, value):  # noqa: N802
        self.input_pending = False
        super().setValue(value)

    def stepBy(self, steps):  # noqa: N802
        self.input_pending = False
        super().stepBy(steps)
        self.editingFinished.emit()

    def _number(self, text):
        text = text.strip()
        if self.prefix() and text.startswith(self.prefix()):
            text = text[len(self.prefix()):]
        if self.suffix() and text.endswith(self.suffix()):
            text = text[:-len(self.suffix())]
        return text.strip()

    def _parsed(self, text):
        number = self._number(text)
        if not re.fullmatch(r"[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)", number):
            return None
        value = Decimal(number.replace(",", "."))
        return value if value.is_finite() else None

    def validate(self, text, position):
        # Validation may classify a draft, but must never rewrite it. In
        # particular, dots and extra decimal places survive until commitment.
        if self._number(text) in {"", "-", "+", ".", ",", "-.", "-,", "+.", "+,"}:
            return QValidator.State.Intermediate, text, position
        value = self._parsed(text)
        state = (QValidator.State.Invalid if value is None else QValidator.State.Acceptable
            if Decimal(str(self.minimum())) <= value <= Decimal(str(self.maximum())) else QValidator.State.Intermediate)
        return state, text, position

    def valueFromText(self, text):  # noqa: N802
        value = self._parsed(text)
        if value is None:
            return self.value()
        value = min(Decimal(str(self.maximum())), max(Decimal(str(self.minimum())), value))
        places = 0 if self._integer else self.decimals()
        try:
            value = value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
        except InvalidOperation:
            return self.value()
        return int(value) if self._integer else float(value)

    def fixup(self, text):
        return self.prefix()+self.textFromValue(self.valueFromText(text))+self.suffix()

    def textFromValue(self, value):  # noqa: N802
        if self._integer:
            return str(int(value))
        text = f"{float(value):.{self.decimals()}f}"
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return ("0" if text == "-0" else text).replace(".", self.locale().decimalPoint())


class CommittedDoubleSpinBox(_CommittedInput, WheelSafeDoubleSpinBox):
    pass


class CommittedSpinBox(_CommittedInput, WheelSafeSpinBox):
    _integer = True
