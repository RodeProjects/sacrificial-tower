"""X-ray controls shrink only after their neighboring tools reach minimum width."""
import math

from PySide6.QtCore import QSize,Qt,Signal
from PySide6.QtGui import QFont,QFontMetrics
from PySide6.QtWidgets import QWidget,QLabel,QPushButton,QButtonGroup,QVBoxLayout,QHBoxLayout,QSizePolicy,QLayout


class XRayTitle(QLabel):
    FULL_TEXT = "X-Ray (Transparenz)"
    SHORT_TEXT = "X-Ray"

    def __init__(self,parent=None):
        super().__init__(self.FULL_TEXT,parent)
        self.compact=False
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("font-size: 8pt; padding: 0;")
        self.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)

    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self.FULL_TEXT),self.fontMetrics().height())

    def minimumSizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self.SHORT_TEXT),self.fontMetrics().height())

    def resizeEvent(self,event):
        self._refresh_text()
        super().resizeEvent(event)

    def set_compact(self,compact):
        self.compact=compact
        self._refresh_text()

    def _refresh_text(self):
        self.setText(self.FULL_TEXT if not self.compact and self.width() >= self.sizeHint().width() else self.SHORT_TEXT)


class XRayControls(QWidget):
    choice_changed = Signal(str)

    def __init__(self,parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Fixed,QSizePolicy.Policy.Fixed)
        layout=QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(1)
        self.title=XRayTitle()
        layout.addWidget(self.title)
        row=QHBoxLayout()
        row.setSpacing(3)
        row.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.group=QButtonGroup(self)
        self.buttons={}
        for choice,text,light,dark,selected_light,selected_dark,accent in (
                ("tower","Turm","#fff6eb","#f5ddbc","#ffecd1","#efbc75","#a85d18"),
                ("both","Keine","#f6f0fc","#e1d3f0","#eadffc","#c9b4e7","#69439d"),
                ("object","STL","#f0f8fb","#cce5ee","#e0f6fc","#93cee0","#216d86")):
            button=QPushButton(text)
            button.setCheckable(True)
            gradient=lambda start,end:f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {start}, stop:1 {end})"
            button.setStyleSheet(
                f"QPushButton {{ background: {gradient(light,dark)}; font-size: 8pt; padding: 0 5px; "
                "min-height: 0; border: 1px solid #a3b1c0; border-radius: 3px; } "
                f"QPushButton:hover {{ border-color: {accent}; }} "
                f"QPushButton:pressed {{ background: {gradient(dark,light)}; }} "
                f"QPushButton:checked {{ background: {gradient(selected_light,selected_dark)}; "
                f"border-color: {accent}; color: {accent}; font-weight: bold; }}")
            button.setToolTip({"tower":"Turm transparent darstellen","both":"Beide Objekte normal darstellen",
                               "object":"Original-STL transparent darstellen"}[choice])
            button.clicked.connect(lambda checked,c=choice:self.choice_changed.emit(c))
            self.group.addButton(button)
            self.buttons[choice]=button
            row.addWidget(button)
        self.buttons["both"].setChecked(True)
        layout.addLayout(row)
        # Reserve the checked font in every button so selection never changes
        # their equal widths. Preferred width is about 4/3 of the old buttons.
        button=self.buttons["tower"]
        button.ensurePolished()
        bold=QFont(button.font());bold.setBold(True)
        metrics=QFontMetrics(bold)
        self.minimum_button_width=max(metrics.horizontalAdvance(b.text()) for b in self.buttons.values())+12
        old_width=max(metrics.horizontalAdvance(text) for text in ("Turm","Beide","Objekt"))+12
        self.preferred_button_width=max(self.minimum_button_width,math.ceil(old_width*4/3))
        self.minimum_width=3*self.minimum_button_width+6
        self.preferred_width=max(3*self.preferred_button_width+6,self.title.sizeHint().width())
        self.setFixedWidth(self.preferred_width)
        self._resize_buttons()

    def _resize_buttons(self):
        self.title.set_compact(self.width() < self.preferred_width)
        width=max(self.minimum_button_width,(self.width()-6)//3)
        for button in self.buttons.values():button.setFixedWidth(width)

    def resizeEvent(self,event):
        self._resize_buttons()
        super().resizeEvent(event)


class PreviewToolsRow(QWidget):
    def __init__(self,xray,resolution,rotation,parent=None):
        super().__init__(parent)
        self.xray,self.resolution,self.rotation=xray,resolution,rotation
        self.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
        row=QHBoxLayout(self)
        row.setContentsMargins(0,0,0,0)
        row.setSpacing(8)
        row.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        row.addWidget(xray)
        row.addWidget(resolution,1)
        row.addWidget(rotation,2)

    def _other_minimum_width(self):
        return sum(max(widget.minimumWidth(),widget.minimumSizeHint().width())
                   for widget in (self.resolution,self.rotation))+2*self.layout().spacing()

    def minimumSizeHint(self):
        return QSize(self.xray.minimum_width+self._other_minimum_width(),
                     max(widget.minimumSizeHint().height() for widget in (self.xray,self.resolution,self.rotation)))

    def resizeEvent(self,event):
        available=self.width()-self._other_minimum_width()
        self.xray.setFixedWidth(max(self.xray.minimum_width,min(self.xray.preferred_width,available)))
        super().resizeEvent(event)
