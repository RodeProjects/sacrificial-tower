"""Compact profile-angle subline which does not participate in the form grid."""
from decimal import Decimal
from PySide6.QtCore import QEvent, QPoint, QPointF, QSignalBlocker, Qt
from PySide6.QtGui import QFont, QPainter, QPalette, QPen, QPolygonF
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QWidget

from cooling_tower.angles import ProfileAngleBinding
from cooling_tower.gui.widgets.hint_popover import hide_window_hint, show_window_hint


PROFILE_ANGLE_HINT = (
    '<p><b>Grenzwinkel aus dem Slicer-Profil</b></p>'
    '<p>• Übernimmt den ausdrücklich gespeicherten Schwellenwinkel des '
    'bestätigten Prozessprofils, gemessen zur Horizontalen. Die Eingabe wird '
    'gesperrt und zeigt diesen Wert weiterhin an.<br>'
    '• Der Turm darf sich dadurch nicht flacher aufweiten als diese Grenze. '
    'Im manuellen Modus wird zugleich die Aufweitungsbegrenzung aktiviert.<br>'
    '• Nach dem Ausschalten steht der vorherige freie Winkel wieder bereit.<br>'
    '• Automatische Schwellen (0°), fehlende oder ungültige Profilwerte können '
    'nicht übernommen werden. Die Einstellung wartet dann auf ein geeignetes Profil.</p>'
)


def set_angle_editor_precision(editor, profile_angle=None, *, minimum=1):
    """Show fractional profile angles without rounding the copied limit."""
    decimals = minimum if profile_angle is None else max(
        minimum, min(12, -Decimal(str(profile_angle)).as_tuple().exponent))
    if getattr(editor, '_display_decimals', None) == decimals:
        return
    editor.set_display_decimals(decimals)
    with QSignalBlocker(editor.lineEdit()):
        editor.lineEdit().setText(editor.prefix()+editor.textFromValue(editor.value())+editor.suffix())


class _ThresholdHint(QLabel):
    def __init__(self, parent):
        super().__init__('Threshold-angle', parent)
        font = self.font()
        font.setUnderline(True)
        self.setFont(font)
        self.setStyleSheet('color: #104b7d;')
        self.setAccessibleDescription(PROFILE_ANGLE_HINT)
        self.hint = PROFILE_ANGLE_HINT

    def enterEvent(self, event):
        self.setStyleSheet('color: #2784c5;')
        show_window_hint(self, self.hint, duration_ms=15_000)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setStyleSheet('color: #104b7d;')
        hide_window_hint(self)
        super().leaveEvent(event)


class _CornerArrow(QWidget):
    """Draw the corner arrow without relying on optional font glyphs."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedWidth(18)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = self.palette().color(QPalette.ColorRole.WindowText)
        painter.setPen(QPen(color, 1.0))
        y = self.height()/2
        leg = min(y-1, (self.width()-5)*3/4)
        tip = QPointF(2+leg*4/3, y)
        painter.drawPolyline([QPointF(2, y-leg), QPointF(2, y), tip])
        painter.setBrush(color)
        painter.drawPolygon(QPolygonF([tip, QPointF(tip.x()-3, y-2.5), QPointF(tip.x()-3, y+2.5)]))


class ProfileAngleLimitControl(QWidget):
    """Overlay the unused space below the label, preserving every grid cell."""
    def __init__(self, row, *, compact=False):
        super().__init__(row)
        self.row = row
        self._row_alive = True
        self._fit_key = None
        self._suffix_text = ' begrenzen' if compact else ' des Slicer-Profils begrenzen'
        self._label_text = 'Auf Threshold-angle'+self._suffix_text
        self.state = ProfileAngleBinding()
        self.setObjectName('profileAngleLimit')
        font = QFont(row.label.font())
        font.setPointSizeF(max(7.0, font.pointSizeF()-1.5))
        self._base_point_size = font.pointSizeF()
        self.setFont(font)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.arrow = _CornerArrow(self)
        self.prefix = QLabel('Auf ', self)
        self.threshold_hint = _ThresholdHint(self)
        self.suffix = QLabel(self._suffix_text, self)
        self.checkbox = QCheckBox(self)
        self.checkbox.setObjectName('limitExpansionToProfile')
        self.checkbox.setStyleSheet('QCheckBox::indicator { width: 12px; height: 12px; }')
        self.checkbox.setFixedSize(15, 15)
        self.checkbox.setAccessibleName(self._label_text)
        self.checkbox.setToolTip(PROFILE_ANGLE_HINT)
        for child in (self.arrow, self.prefix, self.threshold_hint, self.suffix):
            layout.addWidget(child)
        layout.addSpacing(5)
        layout.addWidget(self.checkbox)
        layout.addStretch(1)
        row.installEventFilter(self)
        row.label.installEventFilter(self)
        row.destroyed.connect(self.deleteLater)
        row.destroyed.connect(self._row_destroyed)
        row.label.destroyed.connect(self._row_destroyed)
        # Feedback is already an expanding block. Keep its first line clear of
        # this subline without adding height to the ordinary numeric row.
        row.message_container.layout().setContentsMargins(0, 8, 0, 0)
        self._position()

    def refresh(self, current, requested, threshold, *, minimum=None):
        with QSignalBlocker(self.checkbox):
            self.checkbox.setChecked(requested)
        self.checkbox.setEnabled(threshold is not None)
        self.applied_threshold = max(minimum, threshold) if threshold is not None and minimum is not None else threshold
        effective = self.state.resolve(current, requested, self.applied_threshold)
        extra = (f'<p>• Im automatischen Modus gilt mindestens {minimum:g}° zur Horizontalen. '
                 'Flachere Profilwerte werden deshalb auf diese sichere Grenze begrenzt.</p>' if minimum is not None else '')
        if threshold is not None and self.applied_threshold != threshold:
            extra += f'<p>Profilwert: {threshold:g}°. Angewendeter Winkel: {self.applied_threshold:g}°.</p>'
        self.threshold_hint.hint = PROFILE_ANGLE_HINT+extra
        self.threshold_hint.setAccessibleDescription(self.threshold_hint.hint)
        self.checkbox.setToolTip(self.threshold_hint.hint)
        self.checkbox.setAccessibleDescription(
            (f'Profilwinkel: {threshold:g} Grad. Angewendeter Winkel: '
             f'{self.applied_threshold:g} Grad zur Horizontalen.') if threshold is not None
            else 'Kein ausdrücklich gespeicherter, gültiger Profilwinkel verfügbar.'
        )
        self._position()
        return effective

    def eventFilter(self, watched, event):
        if self._row_alive and event.type() in {QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.Show,
                            QEvent.Type.Hide, QEvent.Type.ParentChange,
                            QEvent.Type.FontChange, QEvent.Type.LayoutRequest, QEvent.Type.EnabledChange}:
            self._position()
        return False

    def _row_destroyed(self):
        self._row_alive = False

    def _position(self):
        if not self._row_alive:
            return
        label = self.row.label
        parent = self.row.parentWidget()
        if parent is None:
            return
        if self.parentWidget() is not parent:
            self.setParent(parent)
        self.setEnabled(self.row.isEnabled())
        self.setVisible(not self.row.isHidden() and not label.isHidden())
        available = max(1, label.width())
        fit_key = (available, label.font().toString())
        if fit_key != self._fit_key:
            self._fit_key = fit_key
            self._fit_text(available)
        height = max(self.fontMetrics().height(), self.checkbox.height())
        origin = label.mapTo(parent, QPoint())
        text_bottom = origin.y()+(label.height()+label.fontMetrics().height())//2
        self.setGeometry(origin.x(), text_bottom, available, height)
        self.raise_()

    def _fit_text(self, available):
        # Elide only the trailing explanation on narrow forms. The full wording
        # remains accessible; neither the editor nor the following row moves.
        self.suffix.setText(self._suffix_text)
        point_size = max(7.0, self.row.label.font().pointSizeF()-1.5)
        while True:
            font = QFont(self.font())
            font.setPointSizeF(point_size)
            self.setFont(font)
            link_font = QFont(font)
            link_font.setUnderline(True)
            self.threshold_hint.setFont(link_font)
            self.layout().invalidate()
            if self.layout().sizeHint().width() <= available or point_size <= 7.0:
                break
            point_size = max(7.0, point_size-0.5)
        natural = self.layout().sizeHint()
        if natural.width() > available:
            remaining = max(0, available-natural.width()+self.suffix.sizeHint().width())
            self.suffix.setText(self.suffix.fontMetrics().elidedText(
                self._suffix_text, Qt.TextElideMode.ElideRight, remaining))
            self.suffix.setToolTip(self._label_text)
