from __future__ import annotations

from html import escape

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QGridLayout, QLabel, QSizePolicy, QWidget


class _InformationMark(QWidget):
    """Draw a true circle rather than relying on a font's enclosed-i glyph."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(17, 17)
        self.setAccessibleName("Hinweis")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(ProfilePreparationHint.COLOR)
        painter.setPen(QPen(color, 1.2))
        painter.drawEllipse(QRectF(1.5, 1.5, 14, 14))
        painter.setPen(QPen(color, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(8, 8, 8, 12)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(QRectF(7.2, 4.4, 1.6, 1.6))


class ProfilePreparationHint(QWidget):
    COLOR = "#06449c"
    SENTENCES = (
        "Wähle dieselben Profile und Einstellungen, mit denen du das Objekt tatsächlich drucken würdest.",
        "Nur die gespeicherten globalen Einstellungen der gewählten Profile werden berücksichtigt.",
        "Niedrigere Druckgeschwindigkeiten können den benötigten Kühlturm "
        "verkleinern und Material sparen.",
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"color: {self.COLOR}; background: transparent;")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QGridLayout(self)
        # The field-title text inset plus 3 px extra breathing room on both
        # sides of the blue text; the shared outer divider gaps stay unchanged.
        layout.setContentsMargins(0, 6, 0, 6)
        layout.setHorizontalSpacing(9)
        layout.setVerticalSpacing(0)
        # Prevent surplus height from stretching the heading away from the body.
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setColumnStretch(1, 1)
        self.icon = _InformationMark(self)
        self.title = QLabel("Die Profilauswahl entscheidet über das Ergebnis.")
        self.title.setWordWrap(True)
        font = self.title.font()
        font.setWeight(QFont.Weight.Bold)
        font.setUnderline(True)
        font.setPointSizeF(font.pointSizeF() + 0.5)
        self.title.setFont(font)
        # A local style also retains the heading weight under the app's
        # generic QLabel font rule.
        self.title.setStyleSheet(f"font-weight: 700; font-size: {font.pointSizeF():g}pt;")
        layout.addWidget(self.icon, 0, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.title, 0, 1)
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.body, 1, 1)
        self._sentence_breaks = None
        self._update_text()

    def _update_text(self):
        # At narrow widths normal wrapping avoids many short sentence lines.
        breaks = self.width() >= self.fontMetrics().horizontalAdvance("M") * 48
        if breaks != self._sentence_breaks:
            self._sentence_breaks = breaks
            self.body.setText(("<br>" if breaks else " ").join(map(escape, self.SENTENCES)))

    def resizeEvent(self, event):
        self._update_text()
        super().resizeEvent(event)

    def minimumSizeHint(self):
        return QSize(0, super().minimumSizeHint().height())
