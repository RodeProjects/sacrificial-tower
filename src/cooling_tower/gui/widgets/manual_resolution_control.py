"""Resolution stage marks and a heading that hides side hints before overlap."""
from PySide6.QtCore import QSize,Qt
from PySide6.QtGui import QColor,QPainter,QPen
from PySide6.QtWidgets import QLabel,QSlider,QStyle,QStyleOptionSlider,QWidget


class ResolutionSlider(QSlider):
    def __init__(self,parent=None):
        super().__init__(Qt.Orientation.Horizontal,parent)

    def paintEvent(self,event):
        super().paintEvent(event)
        option=QStyleOptionSlider()
        self.initStyleOption(option)
        style=self.style()
        groove=style.subControlRect(QStyle.ComplexControl.CC_Slider,option,QStyle.SubControl.SC_SliderGroove,self)
        handle=style.subControlRect(QStyle.ComplexControl.CC_Slider,option,QStyle.SubControl.SC_SliderHandle,self)
        span=max(0,groove.width()-handle.width())
        painter=QPainter(self)
        painter.setPen(QPen(QColor("#82929f"),1))
        y=min(self.height()-5,groove.bottom()+5)
        for stage in range(self.minimum(),self.maximum()+1):
            x=groove.left()+handle.width()//2+QStyle.sliderPositionFromValue(
                self.minimum(),self.maximum(),stage,span,option.upsideDown)
            painter.drawLine(x,y,x,y+3)
        painter.end()


class ResolutionHeading(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.title=QLabel("Auflösung (STL)",self)
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setStyleSheet("font-size: 8pt; padding: 0;")
        self.faster=QLabel("performance",self)
        self.precise=QLabel("optik",self)
        for hint in (self.faster,self.precise):
            hint.setStyleSheet("font-size: 8pt; color: #74808c; padding: 0;")
        self.setMinimumWidth(self.title.sizeHint().width()+8)

    def sizeHint(self):
        return QSize(self.minimumWidth(),self.title.sizeHint().height())

    def resizeEvent(self,event):
        self.title.setGeometry(self.rect())
        hint_width=max(self.faster.sizeHint().width(),self.precise.sizeHint().width())
        visible=self.width() >= self.title.sizeHint().width()+2*hint_width+16
        for hint in (self.faster,self.precise):
            hint.setVisible(visible)
            hint.resize(hint.sizeHint().width(),self.height())
        self.faster.move(0,0)
        self.precise.move(self.width()-self.precise.width(),0)
        super().resizeEvent(event)
