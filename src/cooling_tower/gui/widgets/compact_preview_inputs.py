"""Compact numeric inputs shared by preview settings."""
from PySide6.QtCore import QRect, QSize
from PySide6.QtWidgets import QPushButton, QSizePolicy, QStyle, QStyleOptionFrame, QStyleOptionSpinBox
from cooling_tower.gui.design_tokens import METRICS
from cooling_tower.gui.widgets.wheel_safe_inputs import WheelSafeDoubleSpinBox, WheelSafeSpinBox
from cooling_tower.gui.widgets.deficit_range_slider import round_deficit


class _CompactSpin:
    """Reserve a value sample plus room for one additional digit."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setProperty("rangeCompactInput", True)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.valueChanged.connect(lambda _value: self.updateGeometry())
        # Track uncommitted typed text as well as the numeric value.
        self.lineEdit().textChanged.connect(lambda _text: self.updateGeometry())

    def setValue(self, value):
        super().setValue(value)
        # Qt suppresses the editor's text signal during programmatic updates.
        # Recompute width even when the caller blocks valueChanged as well.
        self.updateGeometry()

    def sizeHint(self):
        hint = super().sizeHint()
        line_edit = self.lineEdit()
        metrics = line_edit.fontMetrics()
        option = QStyleOptionSpinBox()
        self.initStyleOption(option)
        option.rect = QRect(0, 0, 1000, hint.height())
        editor = self.style().subControlRect(QStyle.ComplexControl.CC_SpinBox, option,
                                            QStyle.SubControl.SC_SpinBoxEditField, self)
        line_option = QStyleOptionFrame()
        line_edit.initStyleOption(line_option)
        line_option.rect = QRect(0, 0, 1000, hint.height())
        contents = line_edit.style().subElementRect(QStyle.SubElement.SE_LineEditContents,
                                                   line_option, line_edit)
        margins = line_edit.textMargins()
        # Include native text insets and caret space, as well as one spare digit.
        overhead = 1000 - editor.width() + 1000 - contents.width() + margins.left() + margins.right() + 4
        text = self._width_sample()
        text_width = max(metrics.horizontalAdvance(text), metrics.boundingRect(text).width())
        hint.setWidth(overhead + text_width + metrics.horizontalAdvance("0"))
        return hint

    def _width_sample(self):
        return self.lineEdit().displayText()

    def minimumSizeHint(self):
        return self.sizeHint()


class _CompactDoubleSpin(_CompactSpin, WheelSafeDoubleSpinBox):
    pass


class _CompactLayerSpin(_CompactSpin, WheelSafeSpinBox):
    def _width_sample(self):
        # Layer edits share a fixed digit budget for this object's full range.
        # Font/style changes still remeasure it; moving a range does not.
        metrics = self.lineEdit().fontMetrics()
        digit = max("0123456789", key=metrics.horizontalAdvance)
        return digit * len(str(self.maximum()))


class _DeficitSpin(_CompactDoubleSpin):
    def textFromValue(self, value):
        return self.locale().toString(round_deficit(value), "f", 1)

    def valueFromText(self, text):
        return round_deficit(super().valueFromText(text))

    def setValue(self, value):
        super().setValue(round_deficit(value))


class _InputResetButton(QPushButton):
    def __init__(self, editor):
        super().__init__("↺")
        self.setProperty("rangeCompactReset", True)
        self.editor = editor
        self.setFixedWidth(METRICS.reset_button_size_px)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def sizeHint(self):
        return QSize(METRICS.reset_button_size_px, self.editor.sizeHint().height())

    def minimumSizeHint(self):
        return self.sizeHint()
