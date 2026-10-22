"""A quiet manual-mode hint beside responsive result actions."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QBoxLayout, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QWidget,
)

from cooling_tower.gui.widgets.generation_text_metrics import unwrapped_label_width


class GenerationResultActions(QWidget):
    layout_changed = Signal()
    hint_visibility_changed = Signal()
    width_requirement_changed = Signal()

    def __init__(self, continue_button, export_button, accept_button, parent=None):
        super().__init__(parent)
        self.setObjectName("generationResultActions")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._refreshing = False
        self._presentation = None
        self._hint_visible = False
        self._hint_container = None
        self._required_width = None
        self.continue_button = continue_button
        self.export_button = export_button
        self.accept_button = accept_button
        self.actions_layout = QGridLayout(self)
        self.actions_layout.setContentsMargins(0, 0, 0, 0)
        self.actions_layout.setSpacing(10)
        self.actions_layout.setColumnStretch(0, 1)

        self.manual_hint = QLabel("<b>Ergebnis nicht zufriedenstellend?</b><br>Probiere den manuellen Modus aus.")
        self.manual_hint.setObjectName("generationManualHint")
        self.manual_hint.setTextFormat(Qt.TextFormat.RichText)
        self.manual_hint.setWordWrap(True)
        self.manual_hint.setMinimumWidth(0)
        self.manual_hint.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        self.primary_actions = QWidget(self)
        self.primary_layout = QHBoxLayout(self.primary_actions)
        self.primary_layout.setContentsMargins(0, 0, 0, 0)
        self.primary_layout.setSpacing(8)
        for button in (continue_button, export_button, accept_button):
            self.primary_layout.addWidget(button)
        self.actions_layout.addWidget(self.manual_hint, 0, 0)
        self.actions_layout.addWidget(self.primary_actions, 0, 1,
                                      Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        QWidget.setTabOrder(continue_button, export_button)
        QWidget.setTabOrder(export_button, accept_button)
        self.manual_hint.hide()
        for button in (continue_button, export_button, accept_button):
            button.installEventFilter(self)
        self.refresh_layout()

    def eventFilter(self, watched, event):  # noqa: N802
        if event.type() in (QEvent.Type.ShowToParent, QEvent.Type.HideToParent):
            self.refresh_layout()
        return super().eventFilter(watched, event)

    def minimumSizeHint(self):  # noqa: N802
        return QSize(0, super().minimumSizeHint().height())

    def set_hint_visible(self, visible):
        changed = self._hint_visible != visible
        self._hint_visible = visible
        self.manual_hint.setVisible(visible)
        self.refresh_layout()
        if changed:
            self.hint_visibility_changed.emit()

    def set_hint_container(self, container=None):
        """Move the same hint into the compact metrics row, or back beside actions."""
        if container is self._hint_container:
            return
        previous = self._hint_container
        (previous.layout() if previous is not None else self.actions_layout).removeWidget(self.manual_hint)
        self._hint_container = container
        if container is None:
            self.actions_layout.addWidget(self.manual_hint, 0, 0)
        else:
            container.layout().addWidget(self.manual_hint)
        self.manual_hint.setVisible(self._hint_visible)
        self.refresh_layout()

    def minimum_unwrapped_width(self):
        """Measure the normal row even while the hint is in the compact grid."""
        buttons = [button for button in (self.continue_button, self.export_button, self.accept_button)
                   if not button.isHidden()]
        if not self._hint_visible or not buttons:
            return 0
        button_width = sum(button.sizeHint().width() for button in buttons)
        button_width += self.primary_layout.spacing() * (len(buttons) - 1)
        margins = self.actions_layout.contentsMargins()
        return (margins.left() + margins.right() + unwrapped_label_width(self.manual_hint)
                + self.actions_layout.horizontalSpacing() + button_width)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self.refresh_layout()

    def event(self, event):
        result = super().event(event)
        if event.type() in (QEvent.Type.LayoutRequest, QEvent.Type.StyleChange, QEvent.Type.FontChange):
            if hasattr(self, "primary_actions"):
                self.refresh_layout()
        return result

    def refresh_layout(self):
        if self._refreshing:
            return
        self._refreshing = True
        try:
            buttons = [button for button in (self.continue_button, self.export_button, self.accept_button)
                       if not button.isHidden()]
            primary_width = sum(button.sizeHint().width() for button in buttons)
            primary_width += self.primary_layout.spacing() * max(0, len(buttons) - 1)
            margins = self.actions_layout.contentsMargins()
            width = max(0, self.contentsRect().width() - margins.left() - margins.right())
            hint_visible = self._hint_visible and self._hint_container is None
            self.primary_actions.setVisible(bool(buttons))
            self.setVisible(hint_visible or bool(buttons))
            required_width = self.minimum_unwrapped_width()
            if required_width != self._required_width:
                self._required_width = required_width
                self.width_requirement_changed.emit()
            hint_width = unwrapped_label_width(self.manual_hint)
            stacked = hint_visible and hint_width + primary_width + self.actions_layout.horizontalSpacing() > width
            vertical = primary_width > width
            state = (hint_visible, bool(buttons), stacked, vertical)
            if state == self._presentation:
                return
            self._presentation = state
            self.primary_layout.setDirection(QBoxLayout.Direction.TopToBottom if vertical
                                             else QBoxLayout.Direction.LeftToRight)
            self.actions_layout.removeWidget(self.primary_actions)
            self.actions_layout.addWidget(self.primary_actions, 1 if stacked else 0,
                                          0 if stacked else 1, 1, 2 if stacked else 1,
                                          Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.actions_layout.invalidate()
            self.updateGeometry()
            self.layout_changed.emit()
        finally:
            self._refreshing = False
