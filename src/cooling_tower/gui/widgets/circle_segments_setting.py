"""Automatic tessellation display with an independently retained manual value."""
from PySide6.QtCore import QEvent, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QValidator
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QLayout

from cooling_tower.gui.widgets.numeric_setting import NumericSettingWidget
from cooling_tower.gui.widgets.profile_angle_limit import _CornerArrow, SettingSubline
from cooling_tower.gui.widgets.wheel_safe_inputs import WheelSafeSpinBox


CIRCLE_SEGMENTS_HINT = (
    "<p><b>Turm-Kreissegmente</b></p>"
    "<p>Bestimmt, aus wie vielen geraden Abschnitten der Umfang des Turms besteht. "
    "Mehr Segmente ergeben einen runderen Turm und eine größere STL-Datei.</p>"
    "<p><b>Automatisch berechnen:</b> Wie bisher mindestens 30 Segmente, danach "
    "ein Segment pro Millimeter des größten Turmdurchmessers. Das gesperrte Feld "
    "zeigt die Segmentzahl des übernommenen Turms, vorher <b>auto</b>.</p>"
    "<p>Ohne Automatik sind <b>4 bis 256</b> Segmente möglich. Die Auswahl gilt "
    "für die gemeinsame Slicerprüfung, die Vorschau und den Export.</p>"
)


class CircleSegmentsSpinBox(WheelSafeSpinBox):
    _display_text = None
    input_reinterpreted = Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pending_prefix = ""
        self.lineEdit().installEventFilter(self)

    def textFromValue(self, value):  # noqa: N802
        return self._display_text if self._display_text is not None else super().textFromValue(value)

    def validate(self, text, position):
        if self._display_text is not None and text == self._display_text:
            return QValidator.State.Acceptable, text, position
        value, parsed = self.locale().toInt(text.strip())
        if parsed and not self.minimum() <= value <= self.maximum():
            return QValidator.State.Invalid, text, position
        return super().validate(text, position)

    def eventFilter(self, watched, event):  # noqa: N802
        if watched is self.lineEdit():
            if event.type() in (QEvent.Type.FocusOut, QEvent.Type.MouseButtonPress):
                self._pending_prefix = ""
            elif event.type() == QEvent.Type.KeyPress and self._handle_key_press(event):
                return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event):  # noqa: N802
        if self._handle_key_press(event):
            event.accept()
            return
        super().keyPressEvent(event)

    def _handle_key_press(self, event):
        pending, self._pending_prefix = self._pending_prefix, ""
        digit = event.text()
        if (len(digit) == 1 and "0" <= digit <= "9"
                and not event.modifiers() & (Qt.KeyboardModifier.ControlModifier
                                            | Qt.KeyboardModifier.AltModifier
                                            | Qt.KeyboardModifier.MetaModifier)):
            edit = self.lineEdit()
            start = edit.selectionStart() if edit.hasSelectedText() else edit.cursorPosition()
            end = start + len(edit.selectedText())
            candidate = pending + digit if pending else edit.text()[:start] + digit + edit.text()[end:]
            value, parsed = self.locale().toInt(candidate)
            if parsed and 0 < value < self.minimum():
                # Keep a leading 1, 2 or 3 out of the field until the next
                # digit completes a valid value such as 12, 256 or 32.
                self._pending_prefix = candidate
                return True
            if pending:
                if self.validate(candidate, len(candidate))[0] == QValidator.State.Acceptable:
                    edit.insert(candidate)
                return True
        elif pending and event.key() in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            return True
        return False

    def stepBy(self, steps):  # noqa: N802
        self._pending_prefix = ""
        super().stepBy(steps)
        self.input_reinterpreted.emit()

    def set_automatic_display(self, automatic, count=None):
        self._pending_prefix = ""
        self._display_text = (str(count) if count is not None else "auto") if automatic else None
        # Updating the presentation must not become an edit or invalidate a result.
        with QSignalBlocker(self), QSignalBlocker(self.lineEdit()):
            self.lineEdit().setText(self.textFromValue(self.value()))
        self.setEnabled(not automatic)


class CircleSegmentsAutomaticControl(SettingSubline):
    def __init__(self, row):
        super().__init__(row)
        self.setObjectName("circleSegmentsAutomaticLine")
        layout = QHBoxLayout(self)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.arrow = _CornerArrow(self)
        self.text_label = QLabel("Automatisch berechnen", self)
        self.checkbox = QCheckBox(self)
        self.checkbox.setObjectName("automaticCircleSegments")
        self.checkbox.setFixedSize(15, 15)
        self.checkbox.setAccessibleName("Turm-Kreissegmente automatisch berechnen")
        self.checkbox.setChecked(True)
        self.text_label.setBuddy(self.checkbox)
        layout.addWidget(self.arrow)
        layout.addWidget(self.text_label)
        layout.addSpacing(5)
        layout.addWidget(self.checkbox)
        layout.addStretch(1)
        self._attach_to_row(row)

    def _fit_text(self, available):
        text = "Automatisch berechnen"
        remaining = max(0, available - self.arrow.width() - self.checkbox.width() - 5)
        self.text_label.setText(self.text_label.fontMetrics().elidedText(
            text, Qt.TextElideMode.ElideRight, remaining))
        self.text_label.setToolTip(text)


class CircleSegmentsSetting(NumericSettingWidget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.accepted_count = None
        self.automatic_control = CircleSegmentsAutomaticControl(self)
        self.automatic_checkbox = self.automatic_control.checkbox
        self.automatic_checkbox.toggled.connect(self.refresh)
        self.editor.input_reinterpreted.connect(self.refresh_input_state)
        self.refresh()

    def invalid_input_message(self):
        text = self.editor.lineEdit().text().strip()
        value, parsed = self.editor.locale().toInt(text)
        if not text or (parsed and value == 0):
            return "Das Feld darf nicht leer sein!"
        minimum = self.editor.property("validationMinimum")
        maximum = self.editor.property("validationMaximum")
        return f"Turm-Kreissegmente: Erlaubt sind ganze Zahlen von {minimum} bis {maximum}."

    def refresh(self, _checked=None):
        automatic = self.automatic_checkbox.isChecked()
        self.editor.set_automatic_display(automatic, self.accepted_count)
        self.refresh_reset_state()
        self.refresh_input_state()

    def set_accepted_count(self, count):
        self.accepted_count = count
        self.refresh()

    def reset_to_default(self):
        with QSignalBlocker(self.automatic_checkbox):
            self.automatic_checkbox.setChecked(True)
        super().reset_to_default()
        self.refresh()

    def _update_modified_state(self, _value=None):
        super()._update_modified_state(_value)
        if hasattr(self, "automatic_checkbox"):
            modified = (not self.automatic_checkbox.isChecked()
                        or self.editor.value() != self.default_provider())
            self.reset_button.setProperty("modified", modified)
            self.reset_button.setEnabled(modified)
            self.reset_button.setToolTip("Automatische Berechnung und Standard-Segmentzahl wiederherstellen")
