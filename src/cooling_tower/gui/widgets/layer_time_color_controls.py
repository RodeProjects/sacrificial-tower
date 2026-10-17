"""Shared layer-time coloring: two grab points and an editable scale end."""
from PySide6.QtCore import QTimer,Qt,Signal
from PySide6.QtWidgets import QCheckBox,QHBoxLayout,QLabel,QVBoxLayout,QWidget

from cooling_tower.gui.design_tokens import COLORS,METRICS
from cooling_tower.gui.widgets.info_tool_button import InfoToolButton
from cooling_tower.gui.widgets.layer_time_range_slider import LayerTimeRangeSlider
from cooling_tower.gui.widgets.manual_inputs import boundary_message
from cooling_tower.manual.geometry import DEFAULT_COLOR_SCALE_LIMIT_S


class LayerTimeColorControls(QWidget):
    times_changed=Signal(float,float)
    scale_changed=Signal(float,float,float)
    interaction_started=Signal()
    interaction_finished=Signal()

    def __init__(self,parent=None):
        super().__init__(parent)
        self.setObjectName("layerTimeColorControls")
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(8)
        header=QHBoxLayout();header.setSpacing(METRICS.setting_info_text_gap_px)
        self.color_info_button=InfoToolButton(
            "Färbt das Original nach seinen Layerzeiten:\n"
            "• Bis zur Rot-Grenze: rot.\n"
            "• Dazwischen: fließender Übergang.\n"
            "• Ab der Grün-Grenze: grün.",
            accessible_name="Informationen zur Layerzeit-Einfärbung",object_name="settingInfoButton",
            diameter_px=METRICS.setting_info_diameter_px)
        header.addWidget(self.color_info_button)
        self.color_enabled_checkbox=QCheckBox("Layerzeit-Einfärbungen aktivieren")
        self.color_enabled_checkbox.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        header.addWidget(self.color_enabled_checkbox);header.addStretch()
        layout.addLayout(header)
        self.color_settings=QWidget()
        settings=QVBoxLayout(self.color_settings);settings.setContentsMargins(0,0,0,0);settings.setSpacing(3)
        self.range_slider=LayerTimeRangeSlider()
        self.scale_spin=self.range_slider.end_spin
        settings.addWidget(self.range_slider)
        self.notice_label=QLabel();self.notice_label.setWordWrap(True)
        self.notice_label.setStyleSheet(f"color: {COLORS['error']}; font-size: 8pt; padding: 0;")
        self.notice_label.hide();settings.addWidget(self.notice_label)
        self.notice_timer=QTimer(self);self.notice_timer.setSingleShot(True);self.notice_timer.setInterval(2000)
        self.notice_timer.timeout.connect(self.clear_notice)
        self.range_slider.times_changed.connect(self.times_changed)
        self.range_slider.scale_changed.connect(self.scale_changed)
        self.range_slider.interaction_started.connect(self.interaction_started)
        self.range_slider.interaction_finished.connect(self.interaction_finished)
        self.scale_spin.limit_attempted.connect(lambda value:self.show_notice(boundary_message(self.scale_spin,value,"Skalenende")))
        self.scale_spin.input_rejected.connect(self.show_notice)
        self.scale_spin.valid_input_edited.connect(self.clear_notice)
        self.color_enabled_checkbox.toggled.connect(self.color_settings.setVisible)
        layout.addWidget(self.color_settings);self.color_settings.hide()

    def set_times(self,reference,deficit,maximum=14.,*,scale_limit=DEFAULT_COLOR_SCALE_LIMIT_S,original_minimum=None):
        self.range_slider.set_original_minimum(original_minimum)
        self.range_slider.set_values(reference-deficit,reference,maximum,limit=scale_limit)

    def show_notice(self,text):
        self.notice_label.setText(text);self.notice_label.show();self.notice_timer.start()

    def clear_notice(self):
        self.notice_timer.stop();self.notice_label.clear();self.notice_label.hide()
