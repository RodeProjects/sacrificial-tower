"""Shared checkbox with a hover explanation for object-specific simulations."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QHBoxLayout, QCheckBox
from cooling_tower.gui.design_tokens import METRICS
from cooling_tower.gui.widgets.info_tool_button import InfoToolButton


class SimulationOption(QWidget):
    def __init__(self, text, hint, parent=None, *, accessible_hint=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(METRICS.setting_info_text_gap_px)
        self.info = InfoToolButton(hint, self, accessible_name=text + ": Informationen",
                                   accessible_hint=accessible_hint, object_name="settingInfoButton",
                                   diameter_px=METRICS.setting_info_diameter_px)
        self.checkbox = QCheckBox(text)
        self.checkbox.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        layout.addWidget(self.info)
        layout.addWidget(self.checkbox)
        layout.addStretch(1)
