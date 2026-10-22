"""Keep result actions on one row while progressively shortening their hint."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLayout, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)


class GenerationResultActions(QWidget):
    layout_changed = Signal()

    TITLE = "Noch nicht das gewünschte Ergebnis?"
    WRAPPED_TITLE = "Noch nicht das\ngewünschte Ergebnis?"
    DESCRIPTION = "Gestalte deinen Turm im manuellen Modus nach deinen Vorstellungen."
    SHORT_DESCRIPTION = "Gestalte deinen Turm im manuellen Modus."
    NORMAL_PADDING = 13
    MINIMUM_PADDING = 4

    def __init__(self, continue_button, export_button, accept_button, parent=None):
        super().__init__(parent)
        self.setObjectName("generationResultActions")
        self._refreshing = False
        self._presentation = None
        self._padding_reduction = None
        self.continue_button = continue_button
        self.export_button = export_button
        self.accept_button = accept_button
        self.actions_layout = QHBoxLayout(self)
        self.actions_layout.setContentsMargins(0, 0, 0, 0)
        self.actions_layout.setSpacing(10)
        self.actions_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)

        self.manual_offer = QWidget(self)
        self.manual_offer.setObjectName("manualCreationOffer")
        self.manual_offer.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        offer_layout = QVBoxLayout(self.manual_offer)
        offer_layout.setContentsMargins(0, 0, 0, 0)
        offer_layout.setSpacing(5)
        self.title_label = QLabel(self.TITLE)
        self.title_label.setObjectName("manualCreationOfferTitle")
        self.description_label = QLabel(self.DESCRIPTION)
        self.description_label.setObjectName("manualCreationOfferText")
        for label in (self.title_label, self.description_label):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            offer_layout.addWidget(label)
        self.manual_button = QPushButton("Manuell gestalten →")
        self.manual_button.setObjectName("generationManualButton")
        self.manual_button.setCursor(Qt.CursorShape.PointingHandCursor)
        offer_layout.addWidget(self.manual_button, 0, Qt.AlignmentFlag.AlignHCenter)

        self.actions_layout.addWidget(continue_button, 0, Qt.AlignmentFlag.AlignBottom)
        self.actions_layout.addStretch(1)
        self.actions_layout.addWidget(self.manual_offer, 1)
        self.actions_layout.addWidget(export_button, 0, Qt.AlignmentFlag.AlignBottom)
        self.actions_layout.addWidget(accept_button, 0, Qt.AlignmentFlag.AlignBottom)
        self._managed_buttons = (continue_button, self.manual_button, export_button)
        self._normal_paddings = {
            continue_button: self.NORMAL_PADDING,
            self.manual_button: self.NORMAL_PADDING,
            export_button: 25,
        }
        self._set_padding_reduction(0)
        QWidget.setTabOrder(continue_button, self.manual_button)
        QWidget.setTabOrder(self.manual_button, export_button)
        QWidget.setTabOrder(export_button, accept_button)
        self.manual_offer.hide()

    def minimumSizeHint(self):  # noqa: N802
        # Full hint text must never prevent the containing grid from stacking.
        return QSize(0, super().minimumSizeHint().height())

    def set_offer_visible(self, visible):
        self.manual_offer.setVisible(visible)
        self.refresh_layout()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self.refresh_layout()

    def event(self, event):
        result = super().event(event)
        if event.type() in (QEvent.Type.LayoutRequest, QEvent.Type.StyleChange, QEvent.Type.FontChange):
            if hasattr(self, "_managed_buttons"):
                self.refresh_layout()
        return result

    @staticmethod
    def _text_width(label, text):
        return max(label.fontMetrics().horizontalAdvance(line) for line in text.split("\n"))

    def _normal_button_width(self, button):
        button.ensurePolished()
        removed = min(self._padding_reduction, self._normal_paddings[button] - self.MINIMUM_PADDING)
        return button.sizeHint().width() + 2 * removed

    def _set_padding_reduction(self, reduction):
        if reduction == self._padding_reduction:
            return
        self._padding_reduction = reduction
        for button in self._managed_buttons:
            padding = max(self.MINIMUM_PADDING, self._normal_paddings[button] - reduction)
            button.setStyleSheet(f"padding-left: {padding}px; padding-right: {padding}px;")

    def refresh_layout(self):
        if self._refreshing:
            return
        self._refreshing = True
        try:
            visible = not self.manual_offer.isHidden()
            self.actions_layout.setStretch(1, 0 if visible else 1)
            mode, reduction = "hidden", 0
            if visible:
                self.title_label.ensurePolished()
                self.description_label.ensurePolished()
                sides = [button for button in (self.continue_button, self.export_button)
                         if not button.isHidden()]
                side_width = sum(self._normal_button_width(button) for button in sides)
                gaps = self.actions_layout.spacing() * len(sides)
                manual_width = self._normal_button_width(self.manual_button)
                width = self.contentsRect().width()
                mode = "buttons"
                for candidate, title, description in (
                    ("full", self.TITLE, self.DESCRIPTION),
                    ("short", self.TITLE, self.SHORT_DESCRIPTION),
                    ("wrapped", self.WRAPPED_TITLE, ""),
                    ("buttons", "", ""),
                ):
                    hint_width = max(manual_width, self._text_width(self.title_label, title),
                                     self._text_width(self.description_label, description))
                    if side_width + gaps + hint_width <= width:
                        mode = candidate
                        break
                if mode == "buttons":
                    overflow = max(0, side_width + gaps + manual_width - width)
                    buttons = sides + [self.manual_button]
                    maximum = max(self._normal_paddings.values()) - self.MINIMUM_PADDING
                    for reduction in range(maximum + 1):
                        saved = sum(2 * min(reduction, self._normal_paddings[button] - self.MINIMUM_PADDING)
                                    for button in buttons)
                        if saved >= overflow:
                            break
            state = (mode, reduction)
            if state == self._presentation:
                return
            self._presentation = state
            self.title_label.setText(self.WRAPPED_TITLE if mode == "wrapped" else self.TITLE)
            self.title_label.setVisible(mode in ("full", "short", "wrapped"))
            self.description_label.setText(self.SHORT_DESCRIPTION if mode == "short" else self.DESCRIPTION)
            self.description_label.setVisible(mode in ("full", "short"))
            self._set_padding_reduction(reduction)
            self.actions_layout.invalidate()
            self.updateGeometry()
            self.layout_changed.emit()
        finally:
            self._refreshing = False
