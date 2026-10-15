from PySide6.QtWidgets import QCheckBox, QStyle, QStyleOptionButton, QStylePainter


class IndicatorOnlyCheckBox(QCheckBox):
    """Keep the label passive and limit mouse feedback to the indicator."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setMouseTracking(True)
        self._indicator_hovered = False

    def indicator_rect(self):
        option = QStyleOptionButton()
        self.initStyleOption(option)
        return self.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, option, self)

    def hitButton(self, position):
        return self.indicator_rect().contains(position)

    def _set_hover_position(self, position):
        hovered = self.indicator_rect().contains(position)
        if hovered != self._indicator_hovered:
            self._indicator_hovered = hovered
            self.update()

    def enterEvent(self, event):
        self._set_hover_position(event.position().toPoint())
        super().enterEvent(event)

    def mouseMoveEvent(self, event):
        self._set_hover_position(event.position().toPoint())
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._indicator_hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        option = QStyleOptionButton()
        self.initStyleOption(option)
        if not self._indicator_hovered:
            option.state &= ~QStyle.StateFlag.State_MouseOver
        painter = QStylePainter(self)
        painter.drawControl(QStyle.ControlElement.CE_CheckBox, option)
