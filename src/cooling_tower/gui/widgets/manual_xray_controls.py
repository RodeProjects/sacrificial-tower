"""X-ray controls shrink only after their neighboring tools reach minimum width."""
import math

from PySide6.QtCore import QSize,Qt,Signal,QSignalBlocker
from PySide6.QtGui import QColor,QFont,QFontMetrics
from PySide6.QtWidgets import QWidget,QLabel,QPushButton,QButtonGroup,QVBoxLayout,QHBoxLayout,QSizePolicy,QLayout
from cooling_tower.gui.design_tokens import ORIGINAL_OBJECT_BLUE


def xray_button_style(choice):
    """Share the manual editor's raised/inset X-Ray treatment."""
    light,dark,selected_light,selected_dark,accent = {
        "tower": ("#fff6eb","#f5ddbc","#ffecd1","#efbc75","#a85d18"),
        "object": ("#f0f8fb","#cce5ee","#e0f6fc",ORIGINAL_OBJECT_BLUE,"#216d86"),
    }[choice]
    gradient=lambda start,end:f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {start}, stop:1 {end})"
    raised_light=QColor(light).lighter(104).name()
    raised_dark=QColor(dark).darker(120).name()
    inset_dark=QColor(selected_dark).darker(125).name()
    return (
        f"QPushButton {{ background: {gradient(light,dark)}; font-size: 8pt; padding: 0 5px; "
        "min-height: 0; border: 1px solid #a3b1c0; border-radius: 3px; color: #536980; } "
        f"QPushButton {{ border-top-color: {raised_light}; border-left-color: {raised_light}; "
        f"border-bottom-color: {raised_dark}; border-right-color: {raised_dark}; }} "
        f"QPushButton:hover {{ color: {accent}; }} "
        f"QPushButton:pressed, QPushButton:checked {{ background: {gradient(selected_dark,selected_light)}; "
        f"border-top-color: {inset_dark}; border-left-color: {inset_dark}; "
        f"border-bottom-color: {selected_light}; border-right-color: {selected_light}; padding: 1px 4px 0 6px; }} "
        f"QPushButton:checked {{ background: {gradient(selected_dark,selected_light)}; "
        f"color: {accent}; font-weight: bold; }}")


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
        self.group.setExclusive(False)
        self.buttons={}
        for choice,text in (("tower","Turm"),("object","STL")):
            button=QPushButton(text)
            button.setCheckable(True)
            button.setStyleSheet(xray_button_style(choice))
            button.setToolTip({"tower":"Transparenz des Turms ein-/ausschalten",
                               "object":"Transparenz des Original-STL ein-/ausschalten"}[choice])
            button.toggled.connect(self._emit_choice)
            self.group.addButton(button)
            self.buttons[choice]=button
            row.addWidget(button)
        layout.addLayout(row)
        # Reserve the checked font in every button so selection never changes
        # their equal widths. Add 20% to the previous preferred button width.
        button=self.buttons["tower"]
        button.ensurePolished()
        bold=QFont(button.font());bold.setBold(True)
        metrics=QFontMetrics(bold)
        self.minimum_button_width=max(metrics.horizontalAdvance(b.text()) for b in self.buttons.values())+12
        old_width=max(metrics.horizontalAdvance(text) for text in ("Turm","Beide","Objekt"))+12
        self.preferred_button_width=math.ceil(max(self.minimum_button_width,math.ceil(old_width*4/3))*6/5)
        self.minimum_width=2*self.minimum_button_width+3
        self.preferred_width=max(2*self.preferred_button_width+3,self.title.sizeHint().width())
        self.setFixedWidth(self.preferred_width)
        self._resize_buttons()

    def _resize_buttons(self):
        self.title.set_compact(self.width() < self.preferred_width)
        width=max(self.minimum_button_width,(self.width()-3)//2)
        for button in self.buttons.values():button.setFixedWidth(width)

    def _emit_choice(self):
        tower,original=(self.buttons[name].isChecked() for name in ("tower","object"))
        self.choice_changed.emit("all" if tower and original else "tower" if tower else "object" if original else "both")

    def set_choice(self,choice):
        for name,button in self.buttons.items():
            with QSignalBlocker(button):
                button.setChecked(choice in {name,"all"})

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
        row.addWidget(xray,alignment=Qt.AlignmentFlag.AlignTop)
        row.addWidget(resolution,1,Qt.AlignmentFlag.AlignTop)
        row.addWidget(rotation,2,Qt.AlignmentFlag.AlignTop)
        row.addStretch()

    def _other_minimum_width(self):
        return sum(max(widget.minimumWidth(),widget.minimumSizeHint().width())
                   for widget in (self.resolution,self.rotation) if not widget.isHidden())+sum(not widget.isHidden() for widget in (self.resolution,self.rotation))*self.layout().spacing()

    def minimumSizeHint(self):
        return QSize(self.xray.minimum_width+self._other_minimum_width(),
                     max(widget.minimumSizeHint().height() for widget in (self.xray,self.resolution,self.rotation)))

    def resizeEvent(self,event):
        available=self.width()-self._other_minimum_width()
        self.xray.setFixedWidth(max(self.xray.minimum_width,min(self.xray.preferred_width,available)))
        super().resizeEvent(event)
