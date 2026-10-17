"""Absolute layer-time bounds with separate, collision-safe grab points."""
import math

from PySide6.QtCore import QEvent,QPointF,QRectF,QSize,QSignalBlocker,Qt,Signal
from PySide6.QtGui import QColor,QLinearGradient,QPainter,QPen,QRegion,QPolygonF
from PySide6.QtWidgets import QLabel,QSlider,QSizePolicy,QWidget

from cooling_tower.gui.widgets.layer_range_canvas import LayerRangeCanvas
from cooling_tower.gui.widgets.manual_inputs import ManualDoubleSpinBox
from cooling_tower.gui.widgets.compact_preview_inputs import _CompactSpin
from cooling_tower.gui.widgets.deficit_range_slider import round_deficit
from cooling_tower.gui.widgets.info_tool_button import InfoToolButton
from cooling_tower.gui.widgets.hint_popover import hide_window_hint
from cooling_tower.manual.geometry import DEFAULT_COLOR_SCALE_LIMIT_S


def time_text(value):
    return f"{value:g}".replace(".",",")+" s"


class _ScaleSpin(_CompactSpin,ManualDoubleSpinBox):
    pass


class _OriginalMinimumMarker(InfoToolButton):
    """An information target, visually distinct from the draggable bounds."""
    def __init__(self,parent):
        super().__init__("",parent,object_name="originalMinimumMarker",diameter_px=20)
        self.setFixedSize(12,12)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.snapped=False
        self._hint_open=False
        self.clicked.connect(self.show_hint)

    def show_hint(self):
        super().show_hint();self._hint_open=True

    def hideEvent(self,event):
        if self._hint_open:
            hide_window_hint(self);self._hint_open=False
        super().hideEvent(event)

    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#ffffff"),1) if self.snapped else Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#1769aa" if self.snapped or self.underMouse() or self.hasFocus() else "#71869a"))
        painter.drawPolygon(QPolygonF([QPointF(6,3),QPointF(1,10),QPointF(11,10)]))


class _TimeHandle(QSlider):
    """Native keyboard/accessibility semantics; only paint the grab point."""
    def __init__(self,owner,kind):
        super().__init__(Qt.Orientation.Horizontal,owner)
        self.owner,self.kind=owner,kind
        self.hovered=False
        self.setRange(0,36000)
        self.setSingleStep(1);self.setPageStep(10)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self.setAccessibleName("Vollständig rot bis" if kind=="red" else "Vollständig grün ab")
        self._units_per_second=10.
        self.valueChanged.connect(lambda value:owner.request_value(kind,value/self._units_per_second))

    def active(self):
        return self.hovered or self.hasFocus() or self.isSliderDown()

    def _refresh(self):
        self.update();self.owner.update()

    def enterEvent(self,event):
        self.hovered=True;self._refresh();super().enterEvent(event)

    def leaveEvent(self,event):
        self.hovered=False;self._refresh();super().leaveEvent(event)

    def focusInEvent(self,event):
        super().focusInEvent(event);self._refresh()

    def focusOutEvent(self,event):
        super().focusOutEvent(event);self._refresh()

    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center=QPointF(self.width()/2,self.height()/2)
        if self.active():
            painter.setPen(Qt.PenStyle.NoPen);painter.setBrush(QColor("#d9eafb"))
            painter.drawEllipse(center,10,10)
        if self.owner.snapped_kind==self.kind:
            painter.setBrush(Qt.BrushStyle.NoBrush);painter.setPen(QPen(QColor("#1769aa"),1.5))
            painter.drawEllipse(center,9,9)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#1769aa" if self.active() else "#263747"))
        painter.drawEllipse(center,6 if self.active() else 5,6 if self.active() else 5)

    def mousePressEvent(self,event):
        if event.button()!=Qt.MouseButton.LeftButton:
            event.ignore();return
        self._press_x=event.globalPosition().x()
        self._press_value=self.owner.threshold(self.kind)
        self._last_drag_value=self._press_value
        self.owner.end_snap()
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self.setSliderDown(True)
        self.owner.interaction_started.emit()
        self._refresh();event.accept()

    def mouseMoveEvent(self,event):
        if not self.isSliderDown():event.ignore();return
        delta=event.globalPosition().x()-self._press_x
        attempted=self._press_value+delta*self.owner.maximum_time/self.owner.track_rect().width()
        if not math.isclose(attempted,self._last_drag_value,rel_tol=0,abs_tol=1e-12):
            previous=self._last_drag_value;self._last_drag_value=attempted
            self.owner.request_value(self.kind,attempted,pointer=True,previous=previous)
        event.accept()

    def mouseReleaseEvent(self,event):
        if event.button()!=Qt.MouseButton.LeftButton or not self.isSliderDown():event.ignore();return
        self.mouseMoveEvent(event)
        self.setSliderDown(False);self.owner.end_snap();self.owner.interaction_finished.emit()
        self._refresh();event.accept()

    def keyPressEvent(self,event):
        direction={Qt.Key.Key_Left:-.1,Qt.Key.Key_Down:-.1,Qt.Key.Key_Right:.1,Qt.Key.Key_Up:.1,
                   Qt.Key.Key_PageDown:-1.,Qt.Key.Key_PageUp:1.}
        if event.key() in direction:
            self.owner.request_value(self.kind,self.owner.threshold(self.kind)+direction[event.key()])
        elif event.key() in {Qt.Key.Key_Home,Qt.Key.Key_End}:
            self.owner.request_value(self.kind,0 if event.key()==Qt.Key.Key_Home else self.owner.maximum_time)
        else:super().keyPressEvent(event);return
        event.accept()

    def wheelEvent(self,event):event.ignore()


class LayerTimeRangeSlider(QWidget):
    times_changed=Signal(float,float)
    scale_changed=Signal(float,float,float)
    interaction_started=Signal()
    interaction_finished=Signal()
    HANDLE_SIZE=24
    SNAP_DISTANCE_PX=6
    SNAP_RELEASE_DISTANCE_PX=10

    def __init__(self,parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
        self.red_time,self.green_time,self.maximum_time=6.,10.,14.
        self.snapped_kind=None
        self.scale_limit=DEFAULT_COLOR_SCALE_LIMIT_S
        self.end_spin=_ScaleSpin(self)
        self.end_spin.setDecimals(1);self.end_spin.setRange(3,self.scale_limit)
        self.end_spin.setSingleStep(.1);self.end_spin.setSuffix(" s")
        self.end_spin.setValue(14);self.end_spin.setKeyboardTracking(False)
        self.end_spin.setFixedHeight(28)
        self.end_spin.setStyleSheet("QDoubleSpinBox { min-height: 0; padding: 0 4px; }")
        self.end_spin.setAccessibleName("Endwert der Layerzeit-Farbskala")
        self.end_spin.setToolTip("Skalenende: mindestens 3 s, höchstens 60 s oder die längste Layerzeit des Originals. "
                                "Darüber liegende Farbgrenzen werden ans neue Ende verschoben.")
        self.end_spin.valueChanged.connect(self._scale_edited)
        self.red_handle=_TimeHandle(self,"red")
        self.green_handle=_TimeHandle(self,"green")
        QWidget.setTabOrder(self.red_handle,self.green_handle)
        QWidget.setTabOrder(self.green_handle,self.end_spin)
        self.zero_label=self._label("0 s")
        self.red_label=self._label("6 s")
        self.green_label=self._label("10 s")
        self.zone_labels=[self._label(text) for text in ("Rot","Übergang","Grün")]
        self.original_minimum_time=None
        self.minimum_marker=_OriginalMinimumMarker(self)
        self.minimum_information=self._label("")
        self.minimum_information.setWordWrap(True)
        self.minimum_information.setAlignment(Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter)
        self.minimum_information.setStyleSheet("color: #526c80; font-size: 8pt; padding: 0; background: transparent;")
        QWidget.setTabOrder(self.green_handle,self.minimum_marker)
        QWidget.setTabOrder(self.minimum_marker,self.end_spin)
        self._positioning=False
        self.set_values(6,10,14)

    def _label(self,text):
        result=QLabel(text,self)
        result.setAlignment(Qt.AlignmentFlag.AlignCenter)
        result.setStyleSheet("color: #263e50; padding: 0; background: transparent;")
        result.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,True)
        return result

    def sizeHint(self):return QSize(320,130)

    def minimumSizeHint(self):return QSize(220,self.height())

    def track_rect(self):
        return QRectF(12,self.fontMetrics().height()+9,max(1,self.width()-24),20)

    def x_for_time(self,value):
        track=self.track_rect()
        return track.left()+track.width()*(value/self.maximum_time)

    def threshold(self,kind):return self.red_time if kind=="red" else self.green_time

    def set_original_minimum(self,value):
        valid=isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>=0
        value=value if valid else None
        if value==self.original_minimum_time:return
        self._set_snapped_kind(None)
        self.original_minimum_time=value
        self._layout_parts();self.update()

    def set_values(self,red,green,maximum,*,limit=None):
        if limit is not None:self.scale_limit=limit
        self.red_time,self.green_time,self.maximum_time=red,green,min(maximum,self.scale_limit)
        if self.snapped_kind is not None:
            snap=self.minimum_snap_time()
            if snap is None or not math.isclose(self.threshold(self.snapped_kind),snap,abs_tol=1e-8):
                self._set_snapped_kind(None)
        for handle,value in ((self.red_handle,red),(self.green_handle,green)):
            handle._units_per_second=min(10.,2147483647/self.scale_limit)
            with QSignalBlocker(handle):
                handle.setMaximum(round(self.scale_limit*handle._units_per_second))
                handle.setValue(round(value*handle._units_per_second))
            handle.setAccessibleDescription(handle.accessibleName()+" "+time_text(value)+". Pfeiltasten ändern um 0,1 s.")
        with QSignalBlocker(self.end_spin):
            self.end_spin.setMaximum(self.scale_limit)
            self.end_spin.setValue(self.maximum_time)
        self._layout_parts();self.update()

    def minimum_snap_time(self):
        minimum=self.original_minimum_time
        if minimum is None or not 0<=minimum<=self.maximum_time:return None
        # Decimal rounding is unambiguous at half-tenths. Very large floats
        # already have a spacing greater than 0.1 s and need no quantization.
        return round_deficit(minimum) if minimum<1e14 else minimum

    def _set_snapped_kind(self,kind):
        if kind==self.snapped_kind:return
        self.snapped_kind=kind
        self.minimum_marker.snapped=kind is not None
        self.minimum_marker.update()
        color="#1769aa" if kind is not None else "#526c80"
        self.minimum_information.setStyleSheet(f"color: {color}; font-size: 8pt; padding: 0; background: transparent;")
        self.red_handle.update();self.green_handle.update();self.update()

    def end_snap(self):
        self._set_snapped_kind(None)
        self._layout_parts()

    def request_value(self,kind,attempted,*,pointer=False,previous=None):
        if not self.isEnabled():return
        low=0. if kind=="red" else max(3.,self.red_time)
        high=self.green_time if kind=="red" else self.maximum_time
        snap=self.minimum_snap_time() if pointer else None
        distance=(abs(attempted-self.original_minimum_time)*self.track_rect().width()/self.maximum_time
                  if snap is not None else math.inf)
        radius=self.SNAP_RELEASE_DISTANCE_PX if self.snapped_kind==kind else self.SNAP_DISTANCE_PX
        approaching=(snap is not None and (previous is None or
            abs(attempted-self.original_minimum_time)<abs(previous-self.original_minimum_time) or
            min(previous,attempted)<=self.original_minimum_time<=max(previous,attempted)))
        snapped=snap is not None and low<=snap<=high and distance<=radius and (self.snapped_kind==kind or approaching)
        self._set_snapped_kind(kind if snapped else None)
        attempted=snap if snapped else round(attempted,1)
        value=round(min(high,max(low,attempted)),6)
        changed=not math.isclose(value,self.threshold(kind),abs_tol=1e-8)
        red=value if kind=="red" else self.red_time
        green=value if kind=="green" else self.green_time
        self.set_values(red,green,self.maximum_time)
        if changed:self.times_changed.emit(green,round(green-red,6))

    def _scale_edited(self,value):
        self._set_snapped_kind(None)
        green=min(self.green_time,value)
        red=min(self.red_time,green)
        self.set_values(red,green,value)
        # Commit all dependent values together, including a single undo entry.
        self.scale_changed.emit(value,green,round(green-red,6))

    def _layout_parts(self):
        if self._positioning:return
        self._positioning=True
        try:
            track=self.track_rect();dot_y=track.bottom()+16
            labels=(self.red_label,self.green_label)
            for item,value in zip(labels,(self.red_time,self.green_time)):
                item.setText(time_text(value));item.adjustSize()
                item.resize(item.width()+8,item.height()+2)
            actual=[self.x_for_time(self.red_time),self.x_for_time(self.green_time)]
            separation=max(self.HANDLE_SIZE+4,(labels[0].width()+labels[1].width())/2+6)
            centers=actual.copy()
            if centers[1]-centers[0]<separation:
                midpoint=sum(centers)/2;centers=[midpoint-separation/2,midpoint+separation/2]
            shift=max(0,self.HANDLE_SIZE/2-centers[0])-max(0,centers[1]-(self.width()-self.HANDLE_SIZE/2))
            centers=[x+shift for x in centers]
            for handle,x in zip((self.red_handle,self.green_handle),centers):
                handle.setGeometry(round(x-self.HANDLE_SIZE/2),round(dot_y-self.HANDLE_SIZE/2),self.HANDLE_SIZE,self.HANDLE_SIZE)
            value_y=round(dot_y+12)
            self.end_spin.setFixedWidth(max(72,self.end_spin.sizeHint().width()))
            self.end_spin.move(self.width()-self.end_spin.width(),value_y-3)
            self.zero_label.adjustSize();self.zero_label.move(0,value_y+2)
            label_x=[max(0,min(self.width()-item.width(),x-item.width()/2)) for x,item in zip(centers,labels)]
            label_x[1]=max(label_x[1],label_x[0]+labels[0].width()+6)
            if label_x[1]+labels[1].width()>self.width():
                label_x[1]=self.width()-labels[1].width()
                label_x[0]=min(label_x[0],label_x[1]-6-labels[0].width())
            rectangles=[QRectF(x,value_y,item.width(),item.height()) for x,item in zip(label_x,labels)]
            for item,rect in zip(labels,rectangles):
                item.move(round(rect.left()),value_y)
            # Keep threshold values beside their grab points; only the colliding
            # axis endpoint moves to a second row, independently on each side.
            row_shift=max(self.end_spin.height(),*(item.height() for item in labels))+10
            self._axis_guides=[]
            for item,x in ((self.zero_label,track.left()),(self.end_spin,track.right())):
                bound=QRectF(item.geometry()).adjusted(-4,0,4,0)
                collision=any(rect.intersects(bound) for rect in rectangles)
                if collision:item.move(item.x(),item.y()+row_shift)
                end=item.y()-4 if collision else track.bottom()+17
                self._axis_guides.append((x,end))
            red_zone,transition,green_zone=self.zone_labels
            red_zone.adjustSize();green_zone.adjustSize()
            red_zone.move(round(track.left()),0)
            green_zone.move(round(track.right()-green_zone.width()),0)
            center=sum(actual)/2
            space=math.floor(2*min(center-(red_zone.x()+red_zone.width()+8),green_zone.x()-8-center))
            # Keep both end labels fixed, even for tiny fades near either edge.
            text=transition.fontMetrics().elidedText("Übergang",Qt.TextElideMode.ElideRight,max(0,space))
            transition.setText(text);transition.adjustSize();transition.setVisible(bool(text.strip("….")) and self.red_time<self.green_time)
            transition.move(round(center-transition.width()/2),0)
            bottom=max(value_y+28,*(item.y()+item.height() for item in (*labels,self.zero_label,self.end_spin)))
            bottom=self._layout_minimum(track,actual,centers,bottom)
            self.setFixedHeight(bottom+4)
        finally:self._positioning=False

    def _layout_minimum(self,track,actual,centers,bottom):
        minimum=self.original_minimum_time
        if minimum is None:
            self.minimum_marker.hide();self.minimum_information.hide()
            return bottom
        text="Min. Layerzeit der STL: "+time_text(minimum)
        self.minimum_marker.setAccessibleName(text)
        snap=self.minimum_snap_time()
        self.minimum_marker.set_hint(text+("\nRastpunkt für Farbgrenzen: "+time_text(snap) if snap is not None else ""))
        self.minimum_information.setText(text)
        in_range=0<=minimum<=self.maximum_time
        if in_range:
            x=self.x_for_time(minimum)
            self.minimum_marker.move(round(x-self.minimum_marker.width()/2),round(track.bottom()+1))
        # Judge the painted triangle, not the empty margins of its widget.
        target=QRectF(self.minimum_marker.geometry()).adjusted(1,3,-1,-2)
        handles=(self.red_handle,self.green_handle)
        # A snapped boundary deliberately shares the minimum marker. Its blue
        # triangle is drawn above the connector; the grab dot remains below it.
        shared=[snap is not None and self.snapped_kind is not None and math.isclose(self.threshold(handle.kind),snap,abs_tol=1e-8)
                for handle in handles]
        blocked=[QRectF(item.geometry()).adjusted(-2,-2,2,2) for item in
                 (*[handle for handle,overlaid in zip(handles,shared) if not overlaid],
                  self.red_label,self.green_label,self.zero_label,self.end_spin)]
        # Include the actual-to-fanned-out connections, not just the grab dots.
        blocked.extend(QRectF(min(a,c)-3,track.bottom()+1,abs(a-c)+6,19)
                       for a,c,overlaid in zip(actual,centers,shared) if not overlaid)
        blocked.extend(QRectF(a-2,track.bottom()+1,4,end-track.bottom()) for a,end in self._axis_guides)
        fits=(in_range and target.left()>=track.left() and target.right()<=track.right()
              and not any(target.intersects(rect) for rect in blocked))
        self.minimum_marker.setVisible(fits)
        self.minimum_information.setVisible(not fits)
        if not fits:
            height=max(self.minimum_information.fontMetrics().height()+2,self.minimum_information.heightForWidth(self.width()))
            self.minimum_information.setGeometry(0,round(bottom+1),self.width(),height)
            bottom=self.minimum_information.y()+height
        return bottom

    def resizeEvent(self,event):
        super().resizeEvent(event);self._layout_parts()

    def changeEvent(self,event):
        super().changeEvent(event)
        if event.type()==QEvent.Type.EnabledChange and not self.isEnabled() and hasattr(self,"minimum_marker"):
            self.end_snap()

    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track=self.track_rect()
        red_x,green_x=self.x_for_time(self.red_time),self.x_for_time(self.green_time)
        painter.fillRect(QRectF(track.left(),track.top(),red_x-track.left(),track.height()),QColor(LayerRangeCanvas.CRITICAL_COLOR))
        if green_x>red_x:
            gradient=QLinearGradient(red_x,0,green_x,0)
            gradient.setColorAt(0,QColor(LayerRangeCanvas.CRITICAL_COLOR));gradient.setColorAt(1,QColor(LayerRangeCanvas.OBJECT_COLOR))
            painter.fillRect(QRectF(red_x,track.top(),green_x-red_x,track.height()),gradient)
        painter.fillRect(QRectF(green_x,track.top(),track.right()-green_x,track.height()),QColor(LayerRangeCanvas.OBJECT_COLOR))
        # Leave gaps at foreground values and grab points rather than drawing
        # an extended axis guide through their text or hover area.
        painter.save()
        region=QRegion(self.rect())
        for item in (self.red_label,self.green_label,self.red_handle,self.green_handle):
            region=region.subtracted(QRegion(item.geometry().adjusted(-2,-2,2,2)))
        painter.setClipRegion(region)
        painter.setPen(QPen(QColor("#71869a"),1))
        for x,end in self._axis_guides:
            painter.drawLine(QPointF(x,track.bottom()+3),QPointF(x,end))
        painter.restore()
        for handle,x in sorted(((self.red_handle,red_x),(self.green_handle,green_x)),key=lambda item:item[0].active()):
            painter.setPen(QPen(QColor("#1769aa" if handle.active() else "#182734"),3 if handle.active() else 1.5))
            center=handle.geometry().center()
            painter.drawPolyline([QPointF(x,track.top()+2),QPointF(x,track.bottom()+5),QPointF(center.x()+.5,center.y()+.5)])
