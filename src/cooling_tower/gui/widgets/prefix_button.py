"""Native push button with an emphasized prefix and a plain accessible label."""
from PySide6.QtCore import QPointF, QRectF
from math import ceil, floor

from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPalette
from PySide6.QtWidgets import QPushButton, QStyle, QStyleOptionButton, QStylePainter


class PrefixButton(QPushButton):
    def __init__(self, prefix, text, parent=None):
        super().__init__(prefix + text, parent)
        self.prefix = prefix
        self._label_cache = None

    def _label_image(self, text_color):
        """Crop to actual rendered ink: font bounds vary with Windows hinting."""
        dpr = self.devicePixelRatioF()
        prefix_font = self._prefix_font()
        prefix_color = QColor("#176b45") if self.isEnabled() else text_color
        key = (self.text(), self.font().key(), dpr, prefix_color.rgba(), text_color.rgba())
        if self._label_cache is not None and self._label_cache[0] == key:
            return self._label_cache[1]
        rest = self.text()[len(self.prefix):]
        prefix_metrics = QFontMetricsF(prefix_font)
        rest_metrics = QFontMetricsF(self.font())
        prefix_width = prefix_metrics.horizontalAdvance(self.prefix)
        width = ceil((prefix_width + rest_metrics.horizontalAdvance(rest) + 8) * dpr)
        height = ceil((max(prefix_metrics.height(), rest_metrics.height()) + 8) * dpr)
        label = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        label.setDevicePixelRatio(dpr)
        label.fill(0)
        baseline = 4 + max(prefix_metrics.ascent(), rest_metrics.ascent())
        painter = QPainter(label)
        painter.setFont(prefix_font)
        painter.setPen(prefix_color)
        painter.drawText(QPointF(4, baseline), self.prefix)
        painter.setFont(self.font())
        painter.setPen(text_color)
        painter.drawText(QPointF(4 + prefix_width, baseline), rest)
        painter.end()
        ink_rows = [y for y in range(height)
                    if any(label.pixel(x, y) >> 24 for x in range(width))]
        if ink_rows:
            label = label.copy(0, ink_rows[0], width, ink_rows[-1] - ink_rows[0] + 1)
        self._label_cache = (key, label)
        return label

    def _prefix_font(self):
        font = QFont(self.font())
        font.setWeight(QFont.Weight.DemiBold)
        return font

    def sizeHint(self):  # noqa: N802
        hint = super().sizeHint()
        extra = (QFontMetricsF(self._prefix_font()).horizontalAdvance(self.prefix)
                 - QFontMetricsF(self.font()).horizontalAdvance(self.prefix))
        hint.setWidth(hint.width() + round(extra))
        return hint

    def paintEvent(self, event):  # noqa: N802
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.text = ""
        painter = QStylePainter(self)
        painter.drawControl(QStyle.ControlElement.CE_PushButton, option)
        rect = QRectF(self.style().subElementRect(
            QStyle.SubElement.SE_PushButtonContents, option, self))
        if self.isDown():
            rect.translate(self.style().pixelMetric(QStyle.PixelMetric.PM_ButtonShiftHorizontal),
                           self.style().pixelMetric(QStyle.PixelMetric.PM_ButtonShiftVertical))
        group = QPalette.ColorGroup.Active if self.isEnabled() else QPalette.ColorGroup.Disabled
        text_color = option.palette.color(group, QPalette.ColorRole.ButtonText)
        label = self._label_image(text_color)
        dpr = label.devicePixelRatio()
        origin = QPointF(rect.center().x() - label.width() / (2 * dpr),
                         floor(rect.center().y() * dpr - label.height() / 2 + .5) / dpr + 1)
        painter.drawImage(origin, label)
