"""Identical quality control for the manual preview and range editor."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QSizePolicy,QSlider
from cooling_tower.gui.design_tokens import METRICS
from cooling_tower.gui.widgets.manual_resolution_control import (ResolutionHeading,ResolutionSlider,ResolutionEndLabels,
    slider_handle_style,SLIDER_GROOVE_OFFSET_STYLE,SLIDER_VALUE_STYLE)
from cooling_tower.manual.geometry import OBJECT_RESOLUTION_STAGES,object_resolution_default


class ObjectResolutionControl(QWidget):
    percent_changed = Signal(int)

    def __init__(self,parent=None,*,title="Auflösung (STL)",show_reset=True):
        super().__init__(parent)
        self.resolution_host = self
        self.resolution_host.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
        resolution_group = QVBoxLayout(self.resolution_host)
        resolution_group.setContentsMargins(0,0,0,0)
        resolution_group.setSpacing(1)
        self.resolution_heading = ResolutionHeading()
        self.resolution_title = self.resolution_heading.title
        self.resolution_title.setText(title)
        self.resolution_heading._fit_heading()
        resolution_header = QHBoxLayout()
        resolution_header.setSpacing(3)
        resolution_header.addWidget(self.resolution_heading,1)
        resolution_group.addLayout(resolution_header)
        resolution = QHBoxLayout()
        resolution.setContentsMargins(0,0,0,0)
        resolution.setSpacing(3)
        slider_host=QWidget()
        slider_column=QVBoxLayout(slider_host)
        slider_column.setContentsMargins(0,0,0,0)
        slider_column.setSpacing(0)
        self.resolution_end_labels=ResolutionEndLabels()
        slider_column.addWidget(self.resolution_end_labels)
        self.resolution_slider = ResolutionSlider()
        self.resolution_slider.setFixedHeight(20)
        self.resolution_slider.setMinimumWidth(65)
        self.resolution_slider.setToolTip("Performance → Optik:\n"+", ".join(map(str,OBJECT_RESOLUTION_STAGES))+" %.\n"
            "0 %: hochauflösende Silhouette.\n"
            "Über 0 %: automatische Netzqualität mit geschützter Mindestqualität.\n"
            "Der Wert gewichtet Performance und Optik, nicht den Anteil der Flächen.\n"
            "Analyse und Druckdaten bleiben gleich.\n"
            "Doppelklick auf den Greifer: Standardauflösung wiederherstellen.")
        self.resolution_slider.setRange(1,len(OBJECT_RESOLUTION_STAGES))
        self.resolution_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.resolution_slider.setTickInterval(1)
        self.resolution_slider.setSingleStep(1)
        # Stop positions follow the slider stages; colors follow their real
        # percentages, keeping the many low-resolution stages predominantly green.
        colors = (QColor("#41a878"),QColor("#e5bf48"),QColor("#e5484d"))
        stops = []
        for index,percent in enumerate(OBJECT_RESOLUTION_STAGES):
            if percent == 0:
                stops.append("stop:0 #8dc9f4")
                continue
            first,last = colors[:2] if percent <= 50 else colors[1:]
            fraction = percent/50 if percent <= 50 else (percent-50)/50
            rgb = [round(a+(b-a)*fraction) for a,b in zip(first.getRgb()[:3],last.getRgb()[:3])]
            stops.append(f"stop:{index/(len(OBJECT_RESOLUTION_STAGES)-1):.6f} {QColor(*rgb).name()}")
        self.resolution_slider.setStyleSheet(
            "QSlider::groove:horizontal { height: 4px; border: 1px solid #000000; border-radius: 2px; "
            +SLIDER_GROOVE_OFFSET_STYLE+
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "+", ".join(stops)+"); } "
            "QSlider::sub-page:horizontal, QSlider::add-page:horizontal { background: transparent; border: none; } "
            +slider_handle_style(4))
        self.resolution_slider.valueChanged.connect(self._changed)
        slider_column.addWidget(self.resolution_slider)
        resolution.addWidget(slider_host,1)
        self.resolution_label = QLabel()
        self.resolution_label.setStyleSheet(SLIDER_VALUE_STYLE)
        self.resolution_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.resolution_label.setMinimumWidth(self.resolution_label.fontMetrics().horizontalAdvance("100 %"))
        resolution_group.addLayout(resolution)
        value_host=QWidget()
        value_column=QVBoxLayout(value_host)
        value_column.setContentsMargins(0,0,0,0)
        value_column.setSpacing(0)
        value_column.addSpacing(self.resolution_end_labels.height())
        value_column.addWidget(self.resolution_label,1)
        resolution.addWidget(value_host)
        self.resolution_reset = None
        if show_reset:
            self.resolution_reset = QPushButton("↺")
            self.resolution_reset.setObjectName("settingResetButton")
            self.resolution_reset.setFixedSize(METRICS.reset_button_size_px,METRICS.reset_button_size_px)
            self.resolution_reset.setAccessibleName("Auflösung des Originalobjekts zurücksetzen")
            self.resolution_reset.setToolTip("Standardauflösung des Originalobjekts wiederherstellen")
            self.resolution_reset.clicked.connect(lambda:self.set_percent(object_resolution_default()))
            resolution.addWidget(self.resolution_reset)
        resolution_header.addSpacing(self.resolution_label.minimumWidth()+
                                     (self.resolution_reset.width()+6 if show_reset else 3))
        self.set_percent(object_resolution_default())

    def set_percent(self,percent):
        self.resolution_slider.setValue(OBJECT_RESOLUTION_STAGES.index(percent)+1)
        self._refresh_value(percent)

    def _changed(self,value):
        percent=OBJECT_RESOLUTION_STAGES[value-1]
        self._refresh_value(percent)
        self.percent_changed.emit(percent)

    def _refresh_value(self,percent):
        self.resolution_label.setText(f"{percent} %")
        if self.resolution_reset is None:return
        modified=percent != object_resolution_default()
        self.resolution_reset.setProperty("modified",modified)
        self.resolution_reset.setEnabled(modified)
        self.resolution_reset.style().unpolish(self.resolution_reset)
        self.resolution_reset.style().polish(self.resolution_reset)
