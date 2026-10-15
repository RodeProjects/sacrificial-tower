from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QPalette
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
        text = option.text
        text_rect = self.style().subElementRect(
            QStyle.SubElement.SE_CheckBoxContents, option, self
        )
        indicator = self.style().subElementRect(
            QStyle.SubElement.SE_CheckBoxIndicator, option, self
        )
        option.text = ""
        painter = QStylePainter(self)
        painter.drawControl(QStyle.ControlElement.CE_CheckBox, option)
        # Center the visible glyphs on the indicator, not the font's line box.
        metrics = painter.fontMetrics()
        bounds = metrics.tightBoundingRect(text)
        baseline = int(
            indicator.y() + (indicator.height() - 1) / 2
            - (bounds.top() + bounds.bottom()) / 2
        ) + 1
        x = (
            text_rect.right() + 1 - metrics.horizontalAdvance(text)
            if self.layoutDirection() == Qt.LayoutDirection.RightToLeft
            else text_rect.left()
        )
        group = (
            QPalette.ColorGroup.Active
            if self.isEnabled()
            else QPalette.ColorGroup.Disabled
        )
        painter.setPen(option.palette.color(group, QPalette.ColorRole.WindowText))
        painter.drawText(QPoint(x, baseline), text)
