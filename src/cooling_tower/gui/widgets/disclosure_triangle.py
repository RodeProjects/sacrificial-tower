"""Shared filled disclosure symbol for section headers and action buttons."""
from PySide6.QtCore import QPointF, QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPolygonF


def draw_disclosure_triangle(
    painter: QPainter, rect: QRect, *, opened: bool, colour: QColor
) -> None:
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(colour)
    painter.translate(rect.x() + rect.width() / 2, rect.y() + rect.height() / 2)
    if opened:
        painter.rotate(180)
    painter.drawPolygon(QPolygonF([
        QPointF(-6, -4), QPointF(6, -4), QPointF(0, 4),
    ]))
    painter.restore()
