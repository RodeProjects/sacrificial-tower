"""Two-column preview help with font-sized, paintable color bullets."""
from PySide6.QtCore import QEvent,QPointF,QSize,Qt
from PySide6.QtGui import QColor,QPainter,QPolygonF
from PySide6.QtWidgets import QWidget,QLabel,QVBoxLayout,QHBoxLayout,QGridLayout,QSizePolicy,QFrame
from cooling_tower.gui.design_tokens import ORIGINAL_OBJECT_BLUE, PREVIEW_SEAM_COLOR, PREVIEW_SEAM_BORDER_COLOR


class LegendSwatch(QWidget):
    def __init__(self,color,parent=None):
        super().__init__(parent)
        self.color = color
        self.border_color = PREVIEW_SEAM_BORDER_COLOR if color == PREVIEW_SEAM_COLOR else None
        self.split = False
        self._fit_font()

    def _fit_font(self):
        size = max(8,round(self.fontMetrics().height()*.72))
        self.setFixedSize(size,size)

    def changeEvent(self,event):
        super().changeEvent(event)
        if event.type() in {QEvent.Type.FontChange,QEvent.Type.StyleChange}:
            self._fit_font()

    def paintEvent(self,event):
        painter = QPainter(self)
        painter.setPen(Qt.PenStyle.NoPen)
        if self.split:
            width,height = self.width(),self.height()
            painter.fillRect(self.rect(),QColor("#41a878"))
            painter.setBrush(QColor("#e5484d"))
            painter.drawPolygon(QPolygonF([QPointF(0,0),QPointF(width,0),QPointF(0,height)]))
        else:
            painter.fillRect(self.rect(),QColor(self.color))
        if self.border_color:
            painter.setPen(QColor(self.border_color))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.rect().adjusted(0,0,-1,-1))
        painter.end()


class ManualPreviewInformation(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(14)
        self.legend = QWidget()
        legend = QVBoxLayout(self.legend)
        legend.setContentsMargins(0,0,0,0)
        legend.setSpacing(1)
        self.legend_title = QLabel("<b>Legende</b>")
        legend.addWidget(self.legend_title)
        self.legend_entries = QWidget()
        self.legend_grid = QGridLayout(self.legend_entries)
        self.legend_grid.setContentsMargins(0,0,0,0)
        self.legend_grid.setHorizontalSpacing(14)
        self.legend_grid.setVerticalSpacing(1)
        self.legend_rows = []
        self.legend_labels = []
        self.legend_columns = 1
        legend.addWidget(self.legend_entries)
        self.swatches = {}
        for key,text,color in (("tower","Turm","#e99032"),("object","Originalobjekt",ORIGINAL_OBJECT_BLUE),
                               ("foot","Fuß / Fußhöhe / Fußgrenze","#7952ba"),("base","Grunddurchmesser / Höhe / Grenze","#2476ca"),
                               ("top_width","Spitzenbreite","#d43b48"),("free","Freie Profilpunkte","#16856b"),
                               ("control","Bézier-Kontrollgriffe","#536980"),("profile","Profilkante","#ba299d")):
            row_widget = QWidget()
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(0,0,0,0)
            row.setSpacing(6)
            swatch = LegendSwatch(color)
            label = QLabel(text)
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignTop)
            row.addWidget(swatch,0,Qt.AlignmentFlag.AlignTop)
            row.addWidget(label,1)
            self.legend_rows.append(row_widget)
            self.legend_labels.append(label)
            self.legend_grid.addWidget(row_widget,len(self.legend_rows)-1,0,Qt.AlignmentFlag.AlignTop)
            self.swatches[key] = swatch
        legend.addStretch()
        self.controls = QWidget()
        controls = QVBoxLayout(self.controls)
        controls.setContentsMargins(0,0,0,0)
        controls.setSpacing(1)
        self.controls_title = QLabel("<b>Bedienung</b>")
        controls.addWidget(self.controls_title)
        self.instructions = QLabel()
        self.instructions.setWordWrap(True)
        self.instructions.setTextFormat(Qt.TextFormat.PlainText)
        controls.addWidget(self.instructions)
        controls.addStretch()
        layout.addWidget(self.legend,1)
        self.separator = QFrame()
        self.separator.setFrameShape(QFrame.Shape.VLine)
        self.separator.setFixedWidth(1)
        self.separator.setStyleSheet("background: #bdc5ce; border: none;")
        layout.addWidget(self.separator)
        layout.addWidget(self.controls,1)

    def set_state(self,view,critical):
        self.swatches["object"].split = critical
        self.swatches["object"].update()
        items = (["Punkt/Ankerpunkt ziehen: Turmform ändern","Doppelklick auf Turmprofil: Punkt hinzufügen",
                  "Doppelklick auf Punkt: Bézierkurven zurücksetzen","Rechtsklick auf manuellen Punkt: Punkt entfernen"]
                 if view in {"side","front"} else
                 ["Punkt ziehen: Spitzenbreite ändern"] if view == "top" else
                 ["Punkt ziehen: Fußbreite ändern"] if view == "bottom" else
                 ["Linke Maustaste: Ansicht drehen"])
        if view in {"side","front"}:
            items.insert(1,"Shift + Ziehen: Punkt nur waagerecht/senkrecht verschieben")
        items += ["Strg+Z: rückgängig · Strg+Y: wiederholen",
                  "Mittlere Maustaste + Ziehen: Ansicht verschieben","Mausrad: Zoom"]
        self.instructions.setText('\n'.join(f"• {item}" for item in items))

    def _set_legend_columns(self,width):
        # Four entries per column, sized by the actual font and longest label.
        widths = [label.fontMetrics().horizontalAdvance(label.text())+row.layout().spacing()+row.layout().itemAt(0).widget().width()
                  for row,label in zip(self.legend_rows,self.legend_labels)]
        needed = max(widths[:4])+max(widths[4:])+self.legend_grid.horizontalSpacing()
        columns = 2 if width >= needed else 1
        if columns == self.legend_columns:
            return
        self.legend_columns = columns
        for row in self.legend_rows:
            self.legend_grid.removeWidget(row)
        for i,row in enumerate(self.legend_rows):
            self.legend_grid.addWidget(row,i%4 if columns == 2 else i,i//4 if columns == 2 else 0,Qt.AlignmentFlag.AlignTop)
        self.legend_grid.setColumnStretch(0,1)
        self.legend_grid.setColumnStretch(1,1 if columns == 2 else 0)
        self.updateGeometry()

    def resizeEvent(self,event):
        self._set_legend_columns(self.legend.width())
        super().resizeEvent(event)

    def changeEvent(self,event):
        super().changeEvent(event)
        if event.type() in {QEvent.Type.FontChange,QEvent.Type.StyleChange} and hasattr(self,"legend_rows"):
            self._set_legend_columns(self.legend.width())

    def heightForWidth(self,width):
        self._set_legend_columns(max(0,(width-29)//2))
        return self.layout().totalHeightForWidth(width)
