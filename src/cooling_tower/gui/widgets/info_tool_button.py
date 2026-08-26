from __future__ import annotations

from PySide6.QtCore import QEvent, Signal
from PySide6.QtWidgets import QToolButton, QWidget

from cooling_tower.gui.design_tokens import METRICS
from cooling_tower.gui.widgets.hint_popover import hide_window_hint, show_window_hint


class InfoToolButton(QToolButton):
    """Circular information control whose hint follows the hover state."""

    hint_shown = Signal(str)

    def __init__(
        self,
        hint: str,
        parent: QWidget | None = None,
        *,
        accessible_name: str = "Weitere Informationen",
        accessible_hint: str | None = None,
        object_name: str = "stlInfoButton",
        diameter_px: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setText("i")
        diameter = diameter_px or METRICS.info_button_diameter_px
        self.setFixedSize(
            diameter,
            diameter,
        )
        self.setToolTipDuration(15_000)
        self.setAccessibleName(accessible_name)
        self.set_hint(hint, accessible_hint=accessible_hint)

    def set_hint(
        self,
        hint: str,
        *,
        accessible_hint: str | None = None,
    ) -> None:
        """Update the visible and accessible explanation together."""

        self.setToolTip(hint)
        self.setAccessibleDescription(accessible_hint or hint)

    def show_hint(self) -> None:
        hint = self.toolTip().strip()
        if not hint:
            return
        show_window_hint(self, hint, duration_ms=15_000)
        self.hint_shown.emit(hint)

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Enter:
            self.show_hint()
        elif event.type() == QEvent.Type.Leave:
            hide_window_hint(self)
        elif event.type() == QEvent.Type.ToolTip:
            self.show_hint()
            event.accept()
            return True
        return super().event(event)
