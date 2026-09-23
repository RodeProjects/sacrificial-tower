from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QLocale, Qt, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cooling_tower.gui.design_tokens import METRICS
from cooling_tower.gui.widgets.info_tool_button import InfoToolButton


NumericEditor = QDoubleSpinBox | QSpinBox
LABEL_INFO_SAFETY_GAP_PX = 30


class NumericSettingWidget(QWidget):
    """One accessible numeric setting row with reset and inline feedback."""

    reset_performed = Signal(str)
    input_state_changed = Signal(str, bool)

    def __init__(
        self,
        *,
        setting_name: str,
        label: str,
        editor: NumericEditor,
        default_provider: Callable[[], int | float],
        unit: str = "",
        helper_text: str = "",
        info_text: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("numericSettingRow")
        self.setting_name = setting_name
        self.editor = editor
        self.default_provider = default_provider
        self.editor.setLocale(
            QLocale(
                QLocale.Language.German,
                QLocale.Country.Germany,
            )
        )

        layout = QGridLayout(self)
        layout.setContentsMargins(
            0,
            METRICS.form_row_vertical_padding_px,
            0,
            METRICS.form_row_vertical_padding_px + 2,
        )
        layout.setHorizontalSpacing(METRICS.form_control_gap_px)
        layout.setVerticalSpacing(1)

        self.label = QLabel(label)
        self.label.setWordWrap(True)
        self.label.setMinimumWidth(150)
        self.label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self.label.setBuddy(editor)
        editor.setAccessibleName(
            f"{label}, Einheit {unit}" if unit else label
        )
        editor.setFixedSize(
            METRICS.form_editor_width_px,
            METRICS.form_control_height_px,
        )
        editor.setKeyboardTracking(True)
        self.unit_label = QLabel(unit, editor)
        self.unit_label.setObjectName("numericEditorUnit")
        self.unit_label.setFixedWidth(METRICS.form_unit_width_px)
        self.unit_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.unit_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            True,
        )
        self.unit_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.unit_label.setAccessibleName(
            f"Einheit {unit}" if unit else "Keine Einheit"
        )
        editor.installEventFilter(self)

        self.info_button = InfoToolButton(
            info_text,
            self,
            accessible_name=f"Informationen zu {label}",
            object_name="settingInfoButton",
            diameter_px=24,
        )
        self.info_button.setVisible(bool(info_text))
        self.info_slot = QWidget(self)
        self.info_slot.setFixedSize(
            LABEL_INFO_SAFETY_GAP_PX + 24,
            METRICS.form_control_height_px,
        )
        info_layout = QHBoxLayout(self.info_slot)
        info_layout.setContentsMargins(
            LABEL_INFO_SAFETY_GAP_PX,
            0,
            0,
            0,
        )
        info_layout.setSpacing(0)
        info_layout.addWidget(
            self.info_button,
            0,
            Qt.AlignmentFlag.AlignCenter,
        )
        self.info_slot.setVisible(bool(info_text))

        self.reset_button = QPushButton("↺")
        self.reset_button.setObjectName("settingResetButton")
        self.reset_button.setFixedSize(
            METRICS.reset_button_size_px,
            METRICS.reset_button_size_px,
        )
        self.reset_button.setToolTip("Auf den Standardwert zurücksetzen")
        self.reset_button.setAccessibleName(
            f"{label} auf Standardwert zurücksetzen"
        )
        self.reset_button.clicked.connect(self.reset_to_default)

        self.message_label = QLabel()
        self.message_label.setObjectName("settingMessage")
        self.message_label.setWordWrap(True)
        self.message_label.setProperty("error", False)
        self.message_label.setProperty("warning", False)
        self.message_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self.message_label.hide()
        self.secondary_message_label = QLabel()
        self.secondary_message_label.setObjectName("settingMessage")
        self.secondary_message_label.setWordWrap(True)
        self.secondary_message_label.setProperty("error", False)
        self.secondary_message_label.setProperty("warning", True)
        self.secondary_message_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self.secondary_message_label.hide()
        self.message_details_label = QLabel()
        self.message_details_label.setObjectName("settingMessageDetails")
        self.message_details_label.setWordWrap(True)
        self.message_details_label.hide()
        self.message_expand_button = QToolButton()
        self.message_expand_button.setObjectName("settingMessageExpand")
        self.message_expand_button.setText("⌄")
        self.message_expand_button.setCheckable(True)
        self.message_expand_button.setAccessibleName(
            "Weitere Hinweise zu diesem Wert anzeigen"
        )
        self.message_expand_button.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.message_expand_button.hide()
        self.message_expand_button.toggled.connect(
            self._set_message_details_expanded
        )
        self.message_container = QWidget()
        self.message_container.setObjectName("settingMessageContainer")
        message_layout = QVBoxLayout(self.message_container)
        message_layout.setContentsMargins(0, 0, 0, 0)
        message_layout.setSpacing(2)
        message_layout.addWidget(self.message_label)
        message_layout.addWidget(self.secondary_message_label)
        message_layout.addWidget(self.message_details_label)
        message_layout.addWidget(self.message_expand_button)
        self.message_container.hide()
        self._helper_text = helper_text
        self._error_messages: tuple[str, ...] = ()
        self._warning_messages: tuple[str, ...] = self._message_lines(helper_text)
        self._feedback_enabled = True
        self._limits_visible = False

        # The range text is made visible immediately below, before the layout
        # gets a chance to reparent it.  Without this owner Qt briefly exposes
        # every range label as an independent native window during startup.
        self.range_label = QLabel(self)
        self.range_label.setObjectName("numericRangeHint")
        self.range_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.range_label.setFixedWidth(METRICS.form_editor_width_px)
        self.range_label.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        self._refresh_range_label()

        layout.addWidget(self.label, 0, 0)
        layout.addWidget(
            self.info_slot,
            0,
            1,
            Qt.AlignmentFlag.AlignBottom,
        )
        layout.addWidget(
            editor,
            0,
            2,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
        )
        layout.addWidget(
            self.reset_button,
            0,
            3,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
        )
        layout.addWidget(
            self.range_label,
            1,
            2,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
        )
        layout.addWidget(self.message_container, 2, 0, 1, 4)
        # The label consumes all available width up to the fixed 30 px safety
        # gap before the centered information control.
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 0)
        layout.setColumnStretch(2, 0)
        layout.setColumnStretch(3, 0)

        line_edit = editor.lineEdit()
        if line_edit is not None:
            line_edit.installEventFilter(self)
            line_edit.textChanged.connect(self._on_text_changed)
        editor.valueChanged.connect(self._update_modified_state)
        self._position_unit_label()
        self._render_messages()
        self._update_reset_metadata()
        self._update_modified_state()

    def eventFilter(self, watched, event) -> bool:  # type: ignore[no-untyped-def]
        result = super().eventFilter(watched, event)
        if watched is self.editor or watched is self.editor.lineEdit():
            if event.type() in {
                QEvent.Type.FocusIn,
                QEvent.Type.Resize,
                QEvent.Type.Show,
                QEvent.Type.StyleChange,
            }:
                self._position_unit_label()
        return result

    def _position_unit_label(self) -> None:
        """Keep the persistent unit area clear of the spin arrow buttons."""

        x = (
            self.editor.width()
            - METRICS.form_spin_button_width_px
            - METRICS.form_unit_width_px
        )
        self.unit_label.setGeometry(
            max(0, x),
            1,
            METRICS.form_unit_width_px,
            max(0, self.editor.height() - 2),
        )
        self.unit_label.raise_()

    def reset_to_default(self) -> None:
        self.editor.setValue(self.default_provider())
        self.editor.selectAll()
        self.reset_performed.emit(self.setting_name)

    def refresh_reset_state(self) -> None:
        """Re-evaluate reset availability after signal-blocked bulk loading."""

        self._update_reset_metadata()
        self._update_modified_state()

    def set_error(self, message: str | None) -> bool:
        """Apply error messages and report whether their state changed."""

        error_messages = self._message_lines(message or "")
        if error_messages == self._error_messages:
            return False
        self._error_messages = error_messages
        self._sync_editor_feedback_properties()
        self._render_messages()
        return True

    def set_helper_text(self, message: str) -> None:
        self._helper_text = message
        self._warning_messages = self._message_lines(message)
        self._sync_editor_feedback_properties()
        self._render_messages()

    def set_feedback_enabled(self, enabled: bool) -> None:
        """Show validation/help feedback only after workflow prerequisites."""

        enabled = bool(enabled)
        if enabled == self._feedback_enabled:
            return
        self._feedback_enabled = enabled
        self._sync_editor_feedback_properties()
        self._refresh_range_label()
        self._render_messages()

    def _sync_editor_feedback_properties(self) -> None:
        invalid = self._feedback_enabled and bool(self._error_messages)
        warning = self._feedback_enabled and bool(self._warning_messages)
        if (
            self.editor.property("invalid") is not None
            and bool(self.editor.property("invalid")) == invalid
            and self.editor.property("warning") is not None
            and bool(self.editor.property("warning")) == warning
        ):
            return
        self.editor.setProperty("invalid", invalid)
        self.editor.setProperty("warning", warning)
        self.editor.style().unpolish(self.editor)
        self.editor.style().polish(self.editor)

    def set_limits_visible(self, visible: bool) -> None:
        self._limits_visible = bool(visible)
        self._refresh_range_label()
        self.updateGeometry()

    def _refresh_range_label(self) -> None:
        maximum = self.editor.property("validationMaximum")
        parts: list[str] = []
        if maximum is not None:
            parts.append(f"Max. {self._format_bound(maximum)}")
        text = "  ·  ".join(parts)
        unit = self.unit_label.text().strip()
        if (
            text
            and unit
            and not bool(self.editor.property("rangeLabelHideUnit"))
        ):
            text += f" {unit}"
        self.range_label.setText(text)
        self.range_label.setToolTip(text)
        self.range_label.setVisible(self._feedback_enabled and self._limits_visible and bool(text))

    def _format_bound(self, value: object) -> str:
        if isinstance(self.editor, QDoubleSpinBox):
            decimals = self.editor.property("rangeLabelDecimals")
            if decimals is not None:
                return self.editor.locale().toString(
                    float(value),
                    "f",
                    int(decimals),
                )
            formatter = getattr(
                self.editor, "stored_text_from_value", self.editor.textFromValue
            )
            return formatter(float(value))
        return str(int(float(value)))

    def refresh_range_state(self) -> None:
        """Refresh a range line after a data-dependent bound changed."""

        self._refresh_range_label()
        self.updateGeometry()

    def set_warning(self, message: str | None) -> None:
        """Show a non-blocking warning below any higher-priority error."""

        self.set_helper_text(message or "")

    @staticmethod
    def _message_lines(message: str) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                line.strip()
                for line in str(message).splitlines()
                if line.strip()
            )
        )

    @staticmethod
    def _format_message_lines(lines: list[str]) -> str:
        """Render multiple field messages as a readable vertical list."""

        if not lines:
            return ""
        if len(lines) == 1:
            return lines[0]
        return "\n".join(
            f"• {line.lstrip('• ').strip()}"
            for line in lines
        )

    def _render_messages(self) -> None:
        """Render at most three compact lines before the expansion control."""

        if not self._feedback_enabled:
            self.message_label.hide()
            self.secondary_message_label.hide()
            self.message_details_label.hide()
            self.message_expand_button.hide()
            self.message_container.hide()
            self.message_container.updateGeometry()
            self.updateGeometry()
            return

        # Field-specific errors stay directly below their editor.  They are
        # ordered before non-blocking warnings so red feedback keeps priority
        # over yellow feedback when both apply to the same value.
        ordered = (
            tuple(("error", line) for line in self._error_messages)
            + tuple(("warning", line) for line in self._warning_messages)
        )
        visible = ordered[:3]
        hidden = ordered[3:]
        visible_errors = [text for severity, text in visible if severity == "error"]
        visible_warnings = [
            text for severity, text in visible if severity == "warning"
        ]

        # Keep message_label as the public primary label used by accessibility
        # code and integrations.  With no error it owns the warning text.
        primary_is_error = bool(visible_errors)
        primary_lines = visible_errors if primary_is_error else visible_warnings
        secondary_lines = visible_warnings if primary_is_error else []
        self.message_label.setText(self._format_message_lines(primary_lines))
        self.message_label.setProperty("error", primary_is_error)
        self.message_label.setProperty(
            "warning", bool(primary_lines) and not primary_is_error
        )
        self.message_label.setVisible(bool(primary_lines))
        self.secondary_message_label.setText(
            self._format_message_lines(secondary_lines)
        )
        self.secondary_message_label.setVisible(bool(secondary_lines))
        for label in (self.message_label, self.secondary_message_label):
            label.style().unpolish(label)
            label.style().polish(label)

        self.message_details_label.setText(
            self._format_message_lines(
                [text for _severity, text in hidden]
            )
        )
        has_details = bool(hidden)
        self.message_expand_button.setVisible(has_details)
        self.message_details_label.setVisible(
            has_details and self.message_expand_button.isChecked()
        )
        self.message_container.setVisible(bool(visible or hidden))
        self.message_container.updateGeometry()
        self.updateGeometry()

    def _set_message_details_expanded(self, expanded: bool) -> None:
        self.message_details_label.setVisible(
            expanded and bool(self.message_details_label.text())
        )
        self.message_expand_button.setText("⌃" if expanded else "⌄")
        self.message_expand_button.setAccessibleName(
            "Weitere Hinweise zu diesem Wert ausblenden"
            if expanded
            else "Weitere Hinweise zu diesem Wert anzeigen"
        )
        self.message_container.updateGeometry()
        self.updateGeometry()

    def set_info_text(self, message: str) -> None:
        self.info_button.set_hint(message)
        self.info_button.setVisible(bool(message))
        self.info_slot.setVisible(bool(message))
        self.info_button.updateGeometry()
        self.updateGeometry()

    def invalid_input_message(self) -> str:
        """Describe an invalid edit, including the editor's hard limits."""

        line_edit = self.editor.lineEdit()
        text = line_edit.text().strip() if line_edit is not None else ""
        if text:
            prefix = self.editor.prefix()
            suffix = self.editor.suffix()
            numeric_text = text
            if prefix and numeric_text.startswith(prefix):
                numeric_text = numeric_text[len(prefix):]
            if suffix and numeric_text.endswith(suffix):
                numeric_text = numeric_text[:-len(suffix)]
            locale = self.editor.locale()
            if isinstance(self.editor, QDoubleSpinBox):
                entered, parsed = locale.toDouble(numeric_text.strip())
            else:
                entered, parsed = locale.toInt(numeric_text.strip())
            validation_minimum = self.editor.property("validationMinimum")
            validation_maximum = self.editor.property("validationMaximum")
            minimum_value = (
                self.editor.minimum()
                if validation_minimum is None
                else float(validation_minimum)
            )
            maximum_value = (
                self.editor.maximum()
                if validation_maximum is None
                else float(validation_maximum)
            )
            if parsed and (
                entered < minimum_value
                or entered > maximum_value
            ):
                if isinstance(self.editor, QDoubleSpinBox):
                    formatter = getattr(
                        self.editor, "stored_text_from_value", self.editor.textFromValue
                    )
                    minimum = formatter(
                        float(minimum_value)
                    )
                    maximum = formatter(
                        float(maximum_value)
                    )
                else:
                    minimum = str(int(minimum_value))
                    maximum = str(int(maximum_value))
                return (
                    f"Gültiger Wertebereich: {minimum} bis {maximum}."
                )
        return "Der Zahlenwert ist unvollständig oder ungültig."

    def _on_text_changed(self, _text: str) -> None:
        self.input_state_changed.emit(
            self.setting_name,
            self.editor.hasAcceptableInput(),
        )

    def _update_reset_metadata(self) -> None:
        value = self.default_provider()
        if isinstance(self.editor, QDoubleSpinBox):
            rendered = self.editor.textFromValue(float(value))
        else:
            rendered = str(int(value))
        self.reset_button.setToolTip(
            f"Auf Standardwert {rendered} zurücksetzen"
        )

    def _update_modified_state(self, _value=None) -> None:
        default = self.default_provider()
        current = self.editor.value()
        tolerance = 1e-9 if isinstance(self.editor, QDoubleSpinBox) else 0
        modified = abs(float(current) - float(default)) > tolerance
        self.reset_button.setProperty("modified", modified)
        self.reset_button.setEnabled(modified)
        self.reset_button.style().unpolish(self.reset_button)
        self.reset_button.style().polish(self.reset_button)
