"""Resolution stage marks, heading and end labels that hide before overlap."""
from PySide6.QtCore import QEvent,QSize,Qt
from PySide6.QtGui import QColor,QFont,QFontMetrics,QPainter,QPen
from PySide6.QtWidgets import QLabel,QSlider,QStyle,QStyleOptionSlider,QWidget
from cooling_tower.gui.widgets.info_tool_button import InfoToolButton


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
            painter.setPen(QPen(QColor("#8dc9f4" if stage == self.minimum() else "#82929f"),1))
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
        self.info_button=InfoToolButton(
            "Diese Einstellung betrifft nur die Darstellung des Originalobjekts in der Vorschau.\n"
            "0 % zeigt die Originalsilhouette. Alle Stufen darüber wählen die Netzqualität automatisch.\n"
            "Der Prozentwert gewichtet Performance und Optik; er ist kein Anteil der Originalflächen.\n"
            "Kleine Objekte behalten ihr Originalnetz. Unklare Bereiche bleiben geschützt.\n"
            "Bei großen Objekten zeigen niedrige Stufen glatte Flächen, hohe Stufen mehr Netzdetails.\n"
            "Beim Export wird das Originalobjekt immer in voller Originalqualität exportiert.",self,
            accessible_name="Informationen zur STL-Vorschauauflösung",
            object_name="settingInfoButton",
            diameter_px=self.title.fontMetrics().height())
        self.info_button.setStyleSheet("font-size: 8pt; padding: 0;")
        self._fit_heading()

    def _fit_heading(self):
        self.title.ensurePolished()
        diameter=self.title.fontMetrics().height()
        self.info_button.setFixedSize(diameter,diameter)
        self.setMinimumWidth(self.title.sizeHint().width()+diameter+12)

    def changeEvent(self,event):
        super().changeEvent(event)
        if event.type() in {QEvent.Type.FontChange,QEvent.Type.StyleChange} and hasattr(self,"info_button"):
            self._fit_heading()
            self._position_heading()

    def sizeHint(self):
        return QSize(self.minimumWidth(),self.title.sizeHint().height())

    def resizeEvent(self,event):
        self._fit_heading()
        self._position_heading()
        super().resizeEvent(event)

    def _position_heading(self):
        title_width=self.title.sizeHint().width()
        group_width=title_width+self.info_button.width()+4
        left=(self.width()-group_width)//2
        self.info_button.move(left,(self.height()-self.info_button.height())//2)
        self.title.setGeometry(left+self.info_button.width()+4,0,title_width,self.height())


class ResolutionEndLabels(QWidget):
    """Keep the slider ends readable on their own line, with a real gap."""
    MINIMUM_GAP_PX=12

    def __init__(self,parent=None):
        super().__init__(parent)
        self.faster=QLabel("Performance",self)
        self.precise=QLabel("Optik",self)
        for hint in (self.faster,self.precise):
            hint.setStyleSheet("font-size: 7.5pt; color: #74808c; padding: 0;")
            hint.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self._fit_font()

    def _fit_font(self):
        # Preserve the old 8 pt line height while slightly reducing the glyphs.
        font=QFont(self.font());font.setPointSizeF(8)
        self.setFixedHeight(QFontMetrics(font).height())

    def sizeHint(self):
        return QSize(self.faster.sizeHint().width()+self.precise.sizeHint().width()+self.MINIMUM_GAP_PX,
                     self.height())

    def changeEvent(self,event):
        super().changeEvent(event)
        if event.type() in {QEvent.Type.FontChange,QEvent.Type.StyleChange} and hasattr(self,"faster"):
            self._fit_font()
            self._position_labels()

    def resizeEvent(self,event):
        self._position_labels()
        super().resizeEvent(event)

    def _position_labels(self):
        visible=self.width() >= self.sizeHint().width()
        for hint in (self.faster,self.precise):
            hint.setVisible(visible)
            hint.resize(hint.sizeHint().width(),self.height())
        self.faster.move(0,0)
        self.precise.move(self.width()-self.precise.width(),0)
