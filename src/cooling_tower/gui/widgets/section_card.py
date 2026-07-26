from __future__ import annotations

from enum import Enum
from html import escape

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cooling_tower.gui.design_tokens import METRICS


class SectionState(str, Enum):
    NEUTRAL = "neutral"
    ACTIVE = "active"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    PREVIEW = "preview"


_STATE_ICONS = {
    SectionState.NEUTRAL: "",
    SectionState.ACTIVE: "⇧",
    SectionState.SUCCESS: "✓",
    SectionState.WARNING: "!",
    SectionState.ERROR: "×",
    SectionState.PREVIEW: "◆",
}

class _ClickableHeader(QFrame):
    activated = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sectionCardHeader")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.activated.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.activated.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class SectionCard(QFrame):
    """Reusable modern section with header, status, summary and optional body.

    The public check-state API intentionally mirrors the former collapsible
    ``QGroupBox`` implementation.  Existing window code can therefore move to
    the common card foundation without losing keyboard or test compatibility.
    """

    toggled = Signal(bool)
    transition_starting = Signal(bool)
    transition_progressed = Signal()
    transition_finished = Signal(bool)

    def __init__(
        self,
        title: str,
        *,
        summary: str = "",
        collapsible: bool = False,
        expanded: bool = True,
        state: SectionState | str = SectionState.NEUTRAL,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._base_title = title
        self._summary = summary
        self._collapsible = collapsible
        self._expanded = bool(expanded) if collapsible else True
        self._state = SectionState(state)
        # Compatibility markers: transitions no longer exist and therefore
        # always remain ``None``.
        self._transition = None
        self._state_transition = None
        self._summary_note = ""
        self._summary_note_severity = "success"
        self._summary_details: tuple[str, ...] = ()
        self._summary_html: str | None = None
        self._compact_summary_rows: tuple[tuple[str, str], ...] = ()

        self.setObjectName("sectionCard")
        self.setProperty("collapsible", collapsible)
        self.setProperty("expanded", self._expanded)
        self.setProperty("state", self._state.value)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.header = _ClickableHeader(self)
        self.header.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.header.setFixedHeight(METRICS.card_header_height_px)
        self.header_layout = QHBoxLayout(self.header)
        self.header_layout.setContentsMargins(
            METRICS.card_header_horizontal_padding_px,
            METRICS.card_header_vertical_padding_px,
            METRICS.card_header_horizontal_padding_px,
            METRICS.card_header_vertical_padding_px,
        )
        self.header_layout.setSpacing(8)

        self.header_left = QWidget(self.header)
        self.header_left.setObjectName("sectionCardHeaderLeft")
        self.header_left.setSizePolicy(
            QSizePolicy.Policy.Maximum,
            QSizePolicy.Policy.Preferred,
        )
        left_layout = QHBoxLayout(self.header_left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)
        left_layout.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )

        self.status_icon = QLabel(self.header_left)
        self.status_icon.setObjectName("sectionCardStatusIcon")
        self.status_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_icon.setFixedWidth(18)
        left_layout.addWidget(
            self.status_icon,
            0,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )

        self.title_label = QLabel(title, self.header_left)
        self.title_label.setObjectName("sectionCardTitle")
        self.title_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.title_label.setSizePolicy(
            QSizePolicy.Policy.Maximum,
            QSizePolicy.Policy.Preferred,
        )
        left_layout.addWidget(
            self.title_label,
            0,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )

        self.title_note_label = QLabel("", self.header_left)
        self.title_note_label.setObjectName("sectionCardTitleNote")
        self.title_note_label.setProperty("severity", "success")
        self.title_note_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.title_note_label.setSizePolicy(
            QSizePolicy.Policy.Maximum,
            QSizePolicy.Policy.Preferred,
        )
        self.title_note_label.hide()
        left_layout.addWidget(
            self.title_note_label,
            0,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        self.header_layout.addWidget(self.header_left, 0)
        self.header_layout.addSpacing(METRICS.card_header_summary_gap_px)

        self.summary_label = QLabel(summary, self.header)
        self.summary_label.setObjectName("sectionCardSummary")
        self.summary_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.summary_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.summary_label.setMinimumWidth(0)
        self.header_layout.addWidget(self.summary_label, 1)

        self.summary_note_label = QLabel("", self.header)
        self.summary_note_label.setObjectName("sectionCardSummaryNote")
        self.summary_note_label.setProperty("severity", "success")
        self.summary_note_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.summary_note_label.setSizePolicy(
            QSizePolicy.Policy.Maximum,
            QSizePolicy.Policy.Preferred,
        )
        self.summary_note_label.hide()
        self.header_layout.addWidget(self.summary_note_label)

        self.badge_label = QLabel("", self.header)
        self.badge_label.setObjectName("sectionCardBadge")
        self.badge_label.setProperty("severity", "neutral")
        self.badge_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge_label.setSizePolicy(
            QSizePolicy.Policy.Maximum,
            QSizePolicy.Policy.Fixed,
        )
        self.badge_label.setFixedHeight(METRICS.card_badge_height_px)
        self.header_layout.addWidget(self.badge_label)

        self.toggle_button = QToolButton(self.header)
        self.toggle_button.setObjectName("sectionCardToggle")
        self.toggle_button.setAutoRaise(True)
        self.toggle_button.setToolTip("Bereich ein- oder ausklappen")
        self.toggle_button.clicked.connect(self.toggle)
        self.header_layout.addWidget(self.toggle_button)

        self.content_widget = QFrame(self)
        self.content_widget.setObjectName("sectionCardBody")
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(
            METRICS.card_body_horizontal_padding_px,
            METRICS.card_body_vertical_padding_px,
            METRICS.card_body_horizontal_padding_px,
            METRICS.card_body_vertical_padding_px,
        )
        self.content_layout.setSpacing(6)
        self.content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.body_divider = QFrame(self)
        self.body_divider.setObjectName("sectionCardBodyDivider")
        self.body_divider.setFixedHeight(1)

        root.addWidget(self.header)
        root.addWidget(self.body_divider)
        root.addWidget(self.content_widget)

        self.header.activated.connect(self.toggle)
        self._sync_visual_state()

    @property
    def base_title(self) -> str:
        return self._base_title

    def title(self) -> str:
        return self._base_title

    def setTitle(self, title: str) -> None:  # noqa: N802 - Qt compatibility
        self._base_title = title
        self.title_label.setText(title)

    def summary(self) -> str:
        return self._summary

    def set_summary(self, summary: str | None) -> None:
        self._summary = (summary or "").strip()
        self._summary_details = ()
        self._summary_html = None
        self._compact_summary_rows = ()
        self._render_summary()

    def set_summary_details(self, details: tuple[str, ...] | list[str]) -> None:
        """Add right-aligned lines below a card's primary summary.

        Cards without details retain their compact header. Cards such as the
        Slicer summary grow only by the space required for their extra lines.
        """

        self._summary_details = tuple(
            line.strip() for line in details if line and line.strip()
        )
        self._summary_html = None
        self._compact_summary_rows = ()
        self._render_summary()

    def summary_details(self) -> tuple[str, ...]:
        return self._summary_details

    def set_summary_html(self, html: str | None) -> None:
        """Optionally render the current summary as trusted rich text."""

        self._summary_html = (html or "").strip() or None
        self._compact_summary_rows = ()
        self._render_summary()

    def set_summary_alignment(self, alignment: Qt.AlignmentFlag) -> None:
        self.summary_label.setAlignment(alignment)

    def set_title_note(
        self,
        text: str | None,
        *,
        severity: str = "success",
    ) -> None:
        """Show a compact qualifier directly beside the card title."""

        note = (text or "").strip()
        self.title_note_label.setText(note)
        self.title_note_label.setProperty("severity", severity)
        self.title_note_label.setVisible(bool(note))
        self._repolish(self.title_note_label)
        self.header.updateGeometry()
        self.updateGeometry()

    def set_compact_summary_column(self, enabled: bool = True) -> None:
        """Use compact key and value columns after an expanding title column."""

        if enabled:
            if not hasattr(self, "summary_key_label"):
                self.header_layout.removeWidget(self.summary_label)
                self.header_layout.removeWidget(self.summary_note_label)
                self.summary_key_label = QLabel("", self.header)
                self.summary_key_label.setObjectName(
                    "sectionCardSummaryKey"
                )
                self.summary_key_label.setTextFormat(
                    Qt.TextFormat.RichText
                )
                self.summary_key_label.setAlignment(
                    Qt.AlignmentFlag.AlignRight
                    | Qt.AlignmentFlag.AlignVCenter
                )
                self.summary_key_label.setSizePolicy(
                    QSizePolicy.Policy.Maximum,
                    QSizePolicy.Policy.Preferred,
                )
                self.header_layout.insertWidget(
                    2,
                    self.summary_key_label,
                )
                self.header_layout.insertWidget(
                    3,
                    self.summary_label,
                )
                self.summary_note_label.hide()
            self.header_left.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Preferred,
            )
            self.summary_label.setSizePolicy(
                QSizePolicy.Policy.Maximum,
                QSizePolicy.Policy.Preferred,
            )
            self.summary_label.setAlignment(
                Qt.AlignmentFlag.AlignLeft
                | Qt.AlignmentFlag.AlignVCenter
            )
            self.header_layout.setStretch(0, 1)
            self.header_layout.setStretch(2, 0)
            self.header_layout.setStretch(3, 0)
            self.header.setMaximumHeight(16777215)
        else:
            if hasattr(self, "summary_key_label"):
                self.header_layout.removeWidget(self.summary_key_label)
                self.header_layout.removeWidget(self.summary_label)
                self.summary_label.setParent(self.header)
                self.summary_note_label.setParent(self.header)
                self.header_layout.insertWidget(2, self.summary_label, 1)
                self.header_layout.insertWidget(3, self.summary_note_label)
                self.summary_key_label.deleteLater()
                del self.summary_key_label
            self.header_left.setSizePolicy(
                QSizePolicy.Policy.Maximum,
                QSizePolicy.Policy.Preferred,
            )
            self.summary_label.setSizePolicy(
                QSizePolicy.Policy.Ignored,
                QSizePolicy.Policy.Preferred,
            )
            self.header_layout.setStretch(0, 0)
            self.header_layout.setStretch(2, 1)
            self.header_layout.setStretch(3, 0)
            self.header.setFixedHeight(METRICS.card_header_height_px)
        self._render_summary()
        self.header.updateGeometry()
        self.updateGeometry()

    def set_compact_summary_rows(
        self,
        rows: tuple[tuple[str, str], ...] | list[tuple[str, str]],
    ) -> None:
        """Render aligned key/value rows in the compact header columns."""

        self._compact_summary_rows = tuple(
            (str(key).strip(), str(value).strip())
            for key, value in rows
            if str(key).strip()
        )
        if self._compact_summary_rows:
            self._summary = self._compact_summary_rows[0][1]
            self._summary_details = tuple(
                f"{key}: {value}"
                for key, value in self._compact_summary_rows[1:]
            )
            self._summary_html = None
        else:
            self._summary = ""
            self._summary_details = ()
            self._summary_html = None
        self._render_summary()

    def _render_summary(self) -> None:
        lines = (self._summary, *self._summary_details)
        if (
            hasattr(self, "summary_key_label")
            and self._compact_summary_rows
        ):
            self._render_compact_summary_rows()
        elif self._summary_html is None:
            self.summary_label.setTextFormat(Qt.TextFormat.PlainText)
            display_text = "\n".join(line for line in lines if line)
            self.summary_label.setText(display_text)
        else:
            self.summary_label.setTextFormat(Qt.TextFormat.RichText)
            self.summary_label.setText(self._summary_html)
        if hasattr(self, "summary_key_label") and not self._compact_summary_rows:
            self.summary_key_label.clear()
            self.summary_key_label.hide()
        self.summary_label.setAccessibleDescription(
            "; ".join(line for line in lines if line)
        )
        # The zero-minimum stretch slot keeps the chevron at the far right even
        # when there is no summary, while still yielding all spare space to a
        # long right-aligned summary.
        self.summary_label.setVisible(True)
        self.summary_label.updateGeometry()
        if hasattr(self, "summary_key_label"):
            self.header.setMinimumHeight(METRICS.card_header_height_px)
            self.header_layout.invalidate()
            self.header_layout.activate()
            self.header.setMinimumHeight(
                max(
                    METRICS.card_header_height_px,
                    self.header_layout.sizeHint().height(),
                )
            )
        self.header.updateGeometry()
        self.updateGeometry()

    def _render_compact_summary_rows(self) -> None:
        labels = tuple(key for key, _value in self._compact_summary_rows)
        values = tuple(value for _key, value in self._compact_summary_rows)
        self.summary_key_label.setText(
            "<br>".join(f"<b>{escape(label)}:</b>" for label in labels)
        )
        self.summary_key_label.show()

        note_colour = (
            "#8a4b08"
            if self._summary_note_severity == "warning"
            else "#176b45"
        )
        rendered_values: list[str] = []
        for index, value in enumerate(values):
            suffix = ""
            if index == 0 and self._summary_note:
                suffix = (
                    f' <span style="color:{note_colour};'
                    f'font-weight:600;">{escape(self._summary_note)}</span>'
                )
            rendered_values.append(f"{escape(value)}{suffix}")
        self.summary_label.setTextFormat(Qt.TextFormat.RichText)
        self.summary_label.setText("<br>".join(rendered_values))
        self.summary_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )

        normal_metrics = QFontMetrics(self.summary_label.font())
        bold_font = self.summary_key_label.font()
        bold_font.setBold(True)
        bold_metrics = QFontMetrics(bold_font)
        key_width = max(
            bold_metrics.horizontalAdvance(f"{label}:")
            for label in labels
        )
        value_widths = [
            normal_metrics.horizontalAdvance(value)
            for value in values
        ]
        if self._summary_note:
            value_widths[0] += (
                normal_metrics.horizontalAdvance(f" {self._summary_note}")
                + 2
            )
        self.summary_key_label.setMaximumWidth(key_width + 4)
        self.summary_label.setMaximumWidth(max(value_widths) + 6)

    def set_summary_note(
        self,
        text: str | None,
        *,
        severity: str = "success",
    ) -> None:
        """Show a short, coloured qualifier after the right-hand summary."""

        self._summary_note = (text or "").strip()
        self._summary_note_severity = severity
        self.summary_note_label.setText(self._summary_note)
        self.summary_note_label.setProperty("severity", severity)
        self.summary_note_label.setVisible(
            bool(self._summary_note)
            and not hasattr(self, "summary_key_label")
        )
        self._repolish(self.summary_note_label)
        self._render_summary()

    def set_state(
        self,
        state: SectionState | str,
        *,
        icon: str | None = None,
        animated: bool = False,
        duration_ms: int = METRICS.animation_duration_ms,
    ) -> None:
        target = SectionState(state)
        self._state = target
        self.setProperty("state", self._state.value)
        self.status_icon.setProperty("state", self._state.value)
        self.status_icon.setText(_STATE_ICONS[self._state] if icon is None else icon)
        self.status_icon.setVisible(bool(self.status_icon.text()))
        self._repolish(self)
        self._repolish(self.status_icon)
        # Header colours depend on the card's dynamic state property. Hidden
        # workflow cards may change state before their first paint, so the
        # direct child must be repolished explicitly as well.
        self._repolish(self.header)

    def state(self) -> SectionState:
        return self._state

    def set_badge(self, text: str | None, *, severity: str = "neutral") -> None:
        badge = (text or "").strip()
        self.badge_label.setText(badge)
        self.badge_label.setProperty("severity", severity)
        self.badge_label.setVisible(bool(badge))
        self._repolish(self.badge_label)

    def set_summary_badge(self, text: str | None) -> None:
        badge = (text or "").strip()
        severity = "error" if "fehler" in badge.lower() else "neutral"
        self.set_badge(badge, severity=severity)

    def setCheckable(self, checkable: bool) -> None:  # noqa: N802
        self._collapsible = bool(checkable)
        self.setProperty("collapsible", self._collapsible)
        if not self._collapsible:
            self._expanded = True
        self._sync_visual_state()

    def isCheckable(self) -> bool:  # noqa: N802
        return self._collapsible

    def setChecked(self, checked: bool) -> None:  # noqa: N802
        expanded = bool(checked) if self._collapsible else True
        if expanded == self._expanded:
            self._sync_visual_state()
            return
        self._expanded = expanded
        self._sync_visual_state()
        self.toggled.emit(expanded)

    def set_expanded(
        self,
        expanded: bool,
        *,
        animated: bool = False,
        duration_ms: int = METRICS.animation_duration_ms,
        on_finished: Callable[[], None] | None = None,
    ) -> None:
        """Set the body state immediately.

        ``animated`` and ``duration_ms`` remain accepted for source
        compatibility, but intentionally have no visual or timing effect.
        """

        target = bool(expanded) if self._collapsible else True
        changed = target != self._expanded
        if changed:
            self.transition_starting.emit(target)
        self.setChecked(target)
        if changed:
            self.transition_progressed.emit()
            self.transition_finished.emit(target)
        if on_finished is not None:
            on_finished()

    def isChecked(self) -> bool:  # noqa: N802
        return self._expanded

    def toggle(self) -> None:
        if self._collapsible:
            self.set_expanded(not self._expanded)

    def refresh_collapsed_state(self) -> None:
        self._sync_visual_state()

    def _sync_visual_state(self) -> None:
        self.content_widget.setVisible(self._expanded)
        self.body_divider.setVisible(self._expanded)
        self.toggle_button.setVisible(self._collapsible)
        self.toggle_button.setText("⌃" if self._expanded else "⌄")
        self.toggle_button.setAccessibleName(
            f"{self._base_title} {'einklappen' if self._expanded else 'ausklappen'}"
        )
        self.header.setCursor(
            Qt.CursorShape.PointingHandCursor if self._collapsible else Qt.CursorShape.ArrowCursor
        )
        self.header.setFocusPolicy(
            Qt.FocusPolicy.StrongFocus if self._collapsible else Qt.FocusPolicy.NoFocus
        )
        self.setProperty("expanded", self._expanded)
        self._render_summary()
        self.set_state(self._state)
        self.badge_label.setVisible(bool(self.badge_label.text()))
        self.updateGeometry()

    @staticmethod
    def _repolish(widget: QWidget | None = None) -> None:
        if widget is None:
            return
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()
