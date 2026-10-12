"""Small, persistent coordinate editor next to the selected manual handle."""
from dataclasses import dataclass
import math

from PySide6.QtCore import Qt,Signal,QVariantAnimation,QSize,QRectF
from PySide6.QtGui import QColor,QPainter,QPainterPath,QPen,QPixmap,QIcon
from PySide6.QtWidgets import QWidget,QLabel,QLineEdit,QPushButton,QHBoxLayout,QVBoxLayout,QScrollArea,QLayout
from cooling_tower.gui.design_tokens import COLORS,BOUNDARY_FEEDBACK_HOLD_MS,BOUNDARY_FEEDBACK_FADE_MS


@dataclass(frozen=True,slots=True)
class PointField:
    name: str
    label: str
    value: float
    default: float | None
    description: str


def format_value(value):
    return f"{value:.2f}".replace(".",",")


def reset_icon():
    """Draw a compact return arrow independently of font glyph availability."""
    icon=QIcon()
    for mode,color in ((QIcon.Mode.Normal,"#1769aa"),(QIcon.Mode.Disabled,"#91a1af")):
        pixmap=QPixmap(32,32);pixmap.setDevicePixelRatio(2);pixmap.fill(Qt.GlobalColor.transparent)
        painter=QPainter(pixmap);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(color),1.6,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
        path=QPainterPath();path.moveTo(4.4,4.5)
        path.cubicTo(6.5,2.2,11,2.8,12.5,5.3)
        path.cubicTo(15.2,9.5,11,14.2,6.7,12.6)
        path.cubicTo(3.7,11.6,2.8,8.2,4.2,5.4)
        painter.drawPath(path)
        arrow=QPainterPath();arrow.moveTo(3.9,2.2);arrow.lineTo(3.9,5.6);arrow.lineTo(7.3,5.6)
        painter.drawPath(arrow);painter.end();icon.addPixmap(pixmap,mode)
    return icon


class PointValueEdit(QLineEdit):
    submitted = Signal()

    def __init__(self):
        super().__init__()
        font=self.font();font.setPointSizeF(8);self.setFont(font)
        self.unit=QLabel("mm",self)
        self.unit.setFont(font)
        self.unit.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,True)
        self.unit.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
        self.unit.setFixedWidth(self.unit.fontMetrics().horizontalAdvance(self.unit.text()))
        self.setTextMargins(0,0,self.unit.width()+3,0)
        self.unit.show()

    def required_width(self):
        # Border/padding, Qt's internal text margins, suffix gap and caret.
        return self.fontMetrics().horizontalAdvance(self.text())+self.unit.width()+16

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self.unit.setGeometry(self.width()-4-self.unit.width(),0,self.unit.width(),self.height())

    def keyPressEvent(self,event):
        if event.key() in {Qt.Key.Key_Return,Qt.Key.Key_Enter}:
            self.submitted.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class PointEditorRow(QWidget):
    def __init__(self,field,owner):
        super().__init__(owner.fields_host)
        self.owner=owner;self.field=field;self.dirty=False;self.invalid=False
        self.label=QLabel(field.label)
        self.editor=PointValueEdit()
        self.editor.setAccessibleName(field.description)
        self.editor.setToolTip(field.description+" · Mit Enter übernehmen")
        self.editor.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.editor.setFixedHeight(22)
        self.reset=QPushButton()
        self.reset.setIcon(reset_icon());self.reset.setIconSize(QSize(14,14))
        self.reset.setFixedSize(20,20)
        self.reset.setAccessibleName(field.description+" zurücksetzen")
        self.reset.setToolTip("Standardwert wiederherstellen")
        self.reset.setStyleSheet("QPushButton { padding: 0; min-height: 0; border: 1px solid #b8c5d1; "
            "border-radius: 4px; background: #edf4f9; color: #1769aa; } "
            "QPushButton:disabled { color: #91a1af; background: #e9eef2; }")
        row=QHBoxLayout(self);row.setContentsMargins(0,1,0,1);row.setSpacing(3)
        row.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        row.addWidget(self.label);row.addWidget(self.editor);row.addWidget(self.reset)
        self.setFixedHeight(24)
        self.setStyleSheet("PointEditorRow { background: transparent; } "
            "QLabel { color: #536980; font-size: 7.5pt; padding: 0; background: transparent; }")
        self.amount=0.;self.pulse_color=QColor(COLORS["success"])
        duration=BOUNDARY_FEEDBACK_HOLD_MS+BOUNDARY_FEEDBACK_FADE_MS
        self.animation=QVariantAnimation(self)
        self.animation.setDuration(duration);self.animation.setStartValue(1.)
        self.animation.setKeyValueAt(BOUNDARY_FEEDBACK_HOLD_MS/duration,1.)
        self.animation.setEndValue(0.)
        self.animation.valueChanged.connect(self._pulse_amount)
        self.editor.textEdited.connect(self._edited)
        self.editor.textChanged.connect(owner.reflow)
        self.editor.submitted.connect(self.submit)
        self.reset.clicked.connect(self.reset_value)
        self.update_field(field,force=True)

    def update_field(self,field,*,force=False):
        self.field=field
        self.reset.setVisible(field.default is not None)
        self.reset.setEnabled(field.default is not None and not math.isclose(field.value,field.default,rel_tol=0,abs_tol=1e-9))
        if field.default is not None:
            self.reset.setToolTip(f"Standard: {format_value(field.default)} mm")
        if force or not self.dirty:
            self.editor.setText(format_value(field.value));self.dirty=False
        self._validate()

    def _parsed(self):
        text=self.editor.text().strip()
        # Rounded display text must not change or invalidate the precise model
        # value when the user has not edited it (or confirms an empty field).
        if not self.dirty or not text:return self.field.value,None
        try:value=float(text.replace(",","."))
        except ValueError:return None,"Eine gültige Zahl eingeben."
        if not math.isfinite(value):return None,"Eine endliche Zahl eingeben."
        return value,None

    def _validate(self):
        value,error=self._parsed()
        if error is None and self.editor.text().strip():
            error=self.owner.validate_value(self.field.name,value)
        self.invalid=bool(error)
        self.editor.setAccessibleDescription(error or "Mit Enter übernehmen")
        self.editor.setToolTip(error or self.field.description+" · Mit Enter übernehmen")
        self._style()
        return value,error

    def _edited(self):
        self.dirty=True;self.animation.stop();self.amount=0.;self._validate()

    def submit(self):
        value,error=self._validate()
        if error is not None:
            self.pulse(False);return
        if not self.dirty or not self.editor.text().strip() or value == self.field.value:
            self.editor.setText(format_value(self.field.value));self.dirty=False;self._validate();self.pulse(True)
            return
        self.dirty=False
        accepted=self.owner.apply_value(self.field.name,value)
        if not accepted:self.dirty=True
        self._validate();self.pulse(accepted)

    def reset_value(self):
        if self.field.default is None:return
        self.dirty=False
        accepted=self.owner.apply_value(self.field.name,self.field.default)
        self.update_field(self.field,force=True);self.pulse(accepted)

    def pulse(self,accepted):
        self.animation.stop();self.pulse_color=QColor(COLORS["success" if accepted else "error"])
        self._pulse_amount(1.);self.animation.start()

    def _pulse_amount(self,value):
        self.amount=float(value);self._style()

    def _style(self):
        def blend(normal):
            normal=QColor(normal)
            return QColor(*(round(a+(b-a)*self.amount) for a,b in
                zip(normal.getRgb()[:3],self.pulse_color.getRgb()[:3]))).name()
        text=COLORS["error"] if self.invalid else blend("#536980")
        self.editor.setStyleSheet("QLineEdit { min-height: 0; font-size: 8pt; padding: 1px 3px; "
            f"border: 1px solid {blend('#b8c5d1')}; border-radius: 4px; background: #f8fbfd; color: {text}; }}")
        self.editor.unit.setStyleSheet("QLabel { font-size: 8pt; padding: 0; border: none; "
            f"background: transparent; color: {text}; }}")


class ManualPointEditor(QWidget):
    def __init__(self,canvas,validate_value,apply_value):
        super().__init__(canvas)
        self.canvas=canvas;self.validate_value=validate_value;self.apply_value=apply_value
        self.identity="";self.rows={};self._syncing_fields=False
        self._placement_key=None
        self.fields_host=QWidget()
        self.fields_layout=QVBoxLayout(self.fields_host)
        self.fields_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.fields_layout.setContentsMargins(0,0,0,0);self.fields_layout.setSpacing(2)
        self.fields_scroll=QScrollArea(self)
        self.fields_scroll.setWidget(self.fields_host);self.fields_scroll.setWidgetResizable(True)
        self.fields_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.fields_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # The group always allocates the full height of its coordinate rows.
        # A transient scroll-area size hint must not reserve a gutter and clip
        # the compact reset buttons when a value changes its width.
        self.fields_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.fields_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; } "
            "QScrollBar:vertical { width: 7px; }")
        self.fields_scroll.viewport().setAutoFillBackground(False)
        self.fields_host.setAutoFillBackground(False)
        self.caption=QLabel(self)
        self.caption_name=QLabel("Layer:",self)
        self.caption.setFixedHeight(18)
        self.caption.setStyleSheet("QLabel { color: #536980; font-size: 7.5pt; padding: 0; background: transparent; }")
        self.caption_name.setStyleSheet(self.caption.styleSheet())
        self.hide()

    def sync_fields(self,identity,fields,caption,enabled):
        self._syncing_fields=True
        if identity!=self.identity or tuple(field.name for field in fields)!=tuple(self.rows):
            self._placement_key=None
            for row in self.rows.values():
                self.fields_layout.removeWidget(row);row.hide();row.deleteLater()
            self.rows={field.name:PointEditorRow(field,self) for field in fields}
            for row in self.rows.values():
                self.fields_layout.addWidget(row);row.show()
            self.identity=identity
        else:
            for field in fields:self.rows[field.name].update_field(field)
        # Numeric captions repeat an editable diameter/height. Layer numbers
        # are read-only context and stay above the fields instead.
        self.caption.setText(caption.partition(":")[2].strip() if caption.startswith("Layer:") else "")
        self.caption.setVisible(bool(self.caption.text()));self.caption_name.setVisible(bool(self.caption.text()))
        self.setEnabled(enabled)
        self._syncing_fields=False
        self.reflow()

    def reflow(self):
        if self._syncing_fields:return
        if not self.rows:self.hide();return
        self.label_width=max(row.label.fontMetrics().horizontalAdvance(row.field.label) for row in self.rows.values())
        if self.caption.text():self.label_width=max(self.label_width,self.caption_name.fontMetrics().horizontalAdvance("Layer:"))
        self.field_width=max(row.editor.required_width() for row in self.rows.values())
        for row in self.rows.values():
            row.label.setFixedWidth(self.label_width);row.editor.setFixedWidth(self.field_width)
            row.layout().activate()
        reset_width = 38 if any(row.field.default is not None for row in self.rows.values()) else 15
        self.content_width=max(self.label_width+self.field_width+reset_width,
            self.label_width+19+self.caption.fontMetrics().horizontalAdvance(self.caption.text()))
        self.reposition()

    def reposition(self):
        handles=self.canvas.handles()
        anchor=next((position for identity,position,_ in handles if identity==self.identity),None)
        if not self.rows or anchor is None:self.hide();return
        fields_height=len(self.rows)*26-2
        caption_height=20 if self.caption.text() else 0
        height=fields_height+caption_height+12
        top=max(self.canvas.view_controls.geometry().bottom()+6,
                min(self.canvas.height()-height-6,round(anchor.y()+18-height)))
        bottom=top+height
        width=self.content_width
        placement_key=(self.identity,anchor.x(),anchor.y(),self.canvas.width(),self.canvas.height(),width,height)
        # Keep the endpoint's box in place while a control moves. Reposition
        # only when a handle enters its clearance or its own anchor/frame changes.
        current=QRectF(self.geometry()).adjusted(-9,-9,9,9)
        obstructed=any(identity!=self.identity and current.contains(position) for identity,position,_ in handles)
        if self._placement_key==placement_key and not self.isHidden() and not obstructed:
            return
        right=max((position.x() for _,position,_ in handles
            if top-9 <= position.y() <= bottom+9),default=anchor.x())
        if self.identity=="minimum_diameter_mm":right=max(right,self.canvas.minimum_measure_label_rect().right()-6)
        x=round(right+14)
        if x+width>self.canvas.width()-6:
            left=min((position.x() for _,position,_ in handles
                if top-9<=position.y()<=bottom+9),default=anchor.x())
            x=round(left-width-14) if left-width-14>=6 else max(6,self.canvas.width()-width-6)
        self.setGeometry(x,top,width,height)
        self._placement_key=placement_key
        self.fields_host.setMinimumHeight(fields_height)
        self.fields_scroll.setGeometry(6,6+caption_height,width-12,fields_height)
        self.fields_host.resize(width-12,fields_height)
        self.caption_name.setGeometry(6,6,self.label_width,18)
        self.caption.setGeometry(6+self.label_width+3+4,6,width-self.label_width-19,18)
        self.fields_layout.activate()
        if self.isHidden():
            self.show();self.raise_()

    def mousePressEvent(self,event):event.accept()

    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(163,177,192,220),.8))
        painter.setBrush(QColor(235,240,245,242))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5,.5,-.5,-.5),7,7)
        painter.end()
