"""Aligned preview sliders, resolution heading and compact end labels."""
from PySide6.QtCore import QEvent,QSize,Qt
from PySide6.QtGui import QColor,QFont,QFontMetrics,QMouseEvent,QPainter,QPen
from PySide6.QtWidgets import QLabel,QSlider,QStyle,QStyleOptionSlider,QWidget,QStyleFactory
from cooling_tower.gui.widgets.info_tool_button import InfoToolButton

SLIDER_GROOVE_OFFSET_PX=3
SLIDER_GROOVE_OFFSET_STYLE=f"margin: -{SLIDER_GROOVE_OFFSET_PX}px 0 {SLIDER_GROOVE_OFFSET_PX}px; "
SLIDER_VALUE_STYLE=f"font-size: 8pt; padding: 0 0 {2*SLIDER_GROOVE_OFFSET_PX}px 0;"

def slider_handle_style(groove_height):
    """Use the same 15-by-13 px white grip on tracks of different heights."""
    extra=13-groove_height
    above=extra//2
    below=extra-above
    return (f"QSlider::handle:horizontal {{ width: 11px; margin: -{above}px 0 -{below}px; "
            "border: 2px solid #000000; border-radius: 3px; background: #ffffff; }")


class ResolutionSlider(QSlider):
    def __init__(self,parent=None):
        super().__init__(Qt.Orientation.Horizontal,parent)

    def tick_mark_top(self):
        return self.height()-6

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
        y=self.tick_mark_top()
        for stage in range(self.minimum(),self.maximum()+1):
            painter.setPen(QPen(QColor("#8dc9f4" if stage == self.minimum() else "#82929f"),1))
            x=groove.left()+handle.width()//2+QStyle.sliderPositionFromValue(
                self.minimum(),self.maximum(),stage,span,option.upsideDown)
            painter.drawLine(x,y,x,y+4)
        painter.end()


class RotationSlider(QSlider):
    """Classic blue track and white grip, independent of the Windows theme."""

    def __init__(self,parent=None):
        super().__init__(Qt.Orientation.Horizontal,parent)
        self._rotation_style=QStyleFactory.create("Fusion")
        self._rotation_style.setParent(self)
        self.setStyle(self._rotation_style)
        self.setPalette(self._rotation_style.standardPalette())
        self.setStyleSheet(
            "QSlider::groove:horizontal { height: 5px; border: 1px solid #000000; "
            +SLIDER_GROOVE_OFFSET_STYLE+
            "border-radius: 3px; background: qlineargradient(x1:0,y1:0,x2:0,y2:1, "
            "stop:0 #dddddd,stop:1 #ffffff); } "
            "QSlider::sub-page:horizontal { border: 1px solid #000000; border-radius: 3px; "
            +SLIDER_GROOVE_OFFSET_STYLE+
            "background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #55acd8,stop:1 #3496c9); } "
            +slider_handle_style(5))

    def mousePressEvent(self,event):
        if event.button() == Qt.MouseButton.LeftButton:
            option=QStyleOptionSlider()
            self.initStyleOption(option)
            handle=self.style().subControlRect(
                QStyle.ComplexControl.CC_Slider,option,
                QStyle.SubControl.SC_SliderHandle,self)
            if not handle.contains(event.position().toPoint()):
                # Fusion already implements an absolute track press for the
                # middle button. Reuse that native drag state for left clicks
                # without introducing a Python-owned proxy style.
                absolute=QMouseEvent(
                    event.type(),event.position(),event.scenePosition(),event.globalPosition(),
                    Qt.MouseButton.MiddleButton,
                    (event.buttons() & ~Qt.MouseButton.LeftButton) | Qt.MouseButton.MiddleButton,
                    event.modifiers(),event.pointingDevice())
                super().mousePressEvent(absolute)
                event.setAccepted(absolute.isAccepted())
                return
        super().mousePressEvent(event)

    def tick_mark_top(self):
        return self.height()-6

    def snap_positions(self,width=None):
        """Share the handle-centre positions between ticks and angle captions."""
        option=QStyleOptionSlider()
        self.initStyleOption(option)
        if width is not None:option.rect.setWidth(width)
        style=self.style()
        groove=style.subControlRect(QStyle.ComplexControl.CC_Slider,option,QStyle.SubControl.SC_SliderGroove,self)
        handle=style.subControlRect(QStyle.ComplexControl.CC_Slider,option,QStyle.SubControl.SC_SliderHandle,self)
        span=max(0,groove.width()-handle.width())
        return {angle:groove.left()+handle.width()//2+QStyle.sliderPositionFromValue(
                    self.minimum(),self.maximum(),angle,span,option.upsideDown)
                for angle in range(self.minimum(),self.maximum()+1,max(1,self.tickInterval()))}

    def paintEvent(self,event):
        super().paintEvent(event)
        painter=QPainter(self)
        painter.setPen(QPen(QColor("#82929f"),1))
        y=self.tick_mark_top()
        for x in self.snap_positions().values():
            painter.drawLine(x,y,x,y+4)
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


class RotationEndLabels(ResolutionEndLabels):
    """Thin angle captions in whole groups before their reading gaps close."""

    def __init__(self,slider,parent=None):
        super().__init__(parent)
        self.slider=slider
        self.left,self.right=self.faster,self.precise
        self.left.setText("-180°")
        self.right.setText("180°")
        self.middle=QLabel("0°",self)
        self.middle.setStyleSheet(self.left.styleSheet())
        self.middle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.labels={-180:self.left,0:self.middle,180:self.right}
        for angle in (-135,-90,-45,45,90,135):
            label=QLabel(f"{angle}°",self)
            label.setStyleSheet(self.left.styleSheet())
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.labels[angle]=label
        self._position_labels()

    def sizeHint(self):
        if not hasattr(self,"middle"):return super().sizeHint()
        edge=max(self.left.sizeHint().width(),self.right.sizeHint().width())
        return QSize(2*edge+self.middle.sizeHint().width()+2*self.MINIMUM_GAP_PX,self.height())

    def _position_labels(self):
        if not hasattr(self,"labels"):return super()._position_labels()
        positions=self.slider.snap_positions(self.width())
        rectangles={}
        for angle,label in self.labels.items():
            label.resize(label.sizeHint().width(),self.height())
            left=max(0,min(self.width()-label.width(),positions[angle]-label.width()//2))
            label.move(left,0)
            rectangles[angle]=(left,left+label.width())
        visible_angles=set()
        for step in (45,90,180):
            angles={angle for angle in self.labels if angle % step == 0}
            bounds=sorted(rectangles[angle] for angle in angles)
            if (all(right<=self.width() for left,right in bounds) and
                    all(next_left-right>=self.MINIMUM_GAP_PX
                        for (_,right),(next_left,_) in zip(bounds,bounds[1:]))):
                visible_angles=angles
                break
        for angle,label in self.labels.items():label.setVisible(angle in visible_angles)
