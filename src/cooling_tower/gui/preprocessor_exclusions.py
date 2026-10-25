"""Bed-coordinate rectangle editing with zoom, pan, handles, undo and cancel."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from cooling_tower.preprocessor_safety import ExclusionRect


class ExclusionCanvas(QWidget):
    changed = Signal()

    def __init__(self, geometry, zones=(), segments=(), parent=None, *, head_radius_mm=0):
        super().__init__(parent)
        self.bed_geometry, self.zones, self.segments = geometry, tuple(zones), tuple(segments)
        self.selected = -1
        self.head_radius_mm = head_radius_mm
        self.zoom = 1.0
        self.pan = QPointF()
        self._drag = None
        self._history = []
        self._before = self.zones
        self.setMinimumSize(400, 350)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAccessibleName("Druckbett: links Rechteck zeichnen oder verschieben, Eckpunkte ziehen; Mausrad zoomt, rechts verschiebt")

    def transform(self):
        bed = self.bed_geometry.bounds
        scale = max(.01, min((self.width() - 64) / (bed.maximum_x_mm - bed.minimum_x_mm),
            (self.height() - 64) / (bed.maximum_y_mm - bed.minimum_y_mm))) * self.zoom
        return scale, (bed.minimum_x_mm + bed.maximum_x_mm) / 2, (bed.minimum_y_mm + bed.maximum_y_mm) / 2

    def screen(self, point):
        scale, cx, cy = self.transform()
        return QPointF(self.width() / 2 + self.pan.x() + (point[0] - cx) * scale,
            self.height() / 2 + self.pan.y() - (point[1] - cy) * scale)

    def world(self, point):
        scale, cx, cy = self.transform()
        bed = self.bed_geometry.bounds
        return (max(bed.minimum_x_mm, min(bed.maximum_x_mm, cx + (point.x() - self.width() / 2 - self.pan.x()) / scale)),
            max(bed.minimum_y_mm, min(bed.maximum_y_mm, cy - (point.y() - self.height() / 2 - self.pan.y()) / scale)))

    def zone_rect(self, zone):
        return QRectF(self.screen((zone.x0, zone.y1)), self.screen((zone.x1, zone.y0))).normalized()

    def fit(self):
        self.zoom, self.pan = 1.0, QPointF()
        self.update()

    def undo(self):
        if self._history:
            self.zones = self._history.pop()
            self.selected = -1
            self.changed.emit()
            self.update()

    def delete_selected(self):
        if 0 <= self.selected < len(self.zones):
            self._history.append(self.zones)
            self.zones = self.zones[:self.selected] + self.zones[self.selected + 1:]
            self.selected = -1
            self.changed.emit()
            self.update()

    def clear(self):
        if self.zones:
            self._history.append(self.zones)
            self.zones = ()
            self.selected = -1
            self.changed.emit()
            self.update()

    def mousePressEvent(self, event):  # noqa: N802
        self.setFocus()
        self._start_screen = event.position()
        self._start = self.world(event.position())
        self._before = self.zones
        if event.button() in (Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton):
            self._drag = "pan"
            self._start_pan = QPointF(self.pan)
        elif event.button() == Qt.MouseButton.LeftButton:
            if 0 <= self.selected < len(self.zones):
                zone = self.zones[self.selected]
                corners = ((zone.x0, zone.y0), (zone.x0, zone.y1), (zone.x1, zone.y0), (zone.x1, zone.y1))
                for i, point in enumerate(corners):
                    if (self.screen(point) - event.position()).manhattanLength() <= 12:
                        self._drag, self._corner = "resize", i
                        return
            self.selected = next((i for i in reversed(range(len(self.zones)))
                if self.zone_rect(self.zones[i]).contains(event.position())), -1)
            self._drag = "move" if self.selected >= 0 else "new"
            self._draft = None
            self.update()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._drag == "pan":
            self.pan = self._start_pan + event.position() - self._start_screen
        elif self._drag:
            x, y = self.world(event.position())
            if self._drag == "new":
                if len(self.zones) < 64 and abs(x - self._start[0]) >= .2 and abs(y - self._start[1]) >= .2:
                    self._draft = ExclusionRect(min(x, self._start[0]), min(y, self._start[1]),
                        max(x, self._start[0]), max(y, self._start[1]))
                else:
                    self._draft = None
            else:
                original = self._before[self.selected]
                if self._drag == "move":
                    bed = self.bed_geometry.bounds
                    dx = max(bed.minimum_x_mm - original.x0, min(bed.maximum_x_mm - original.x1, x - self._start[0]))
                    dy = max(bed.minimum_y_mm - original.y0, min(bed.maximum_y_mm - original.y1, y - self._start[1]))
                    zone = ExclusionRect(original.x0 + dx, original.y0 + dy, original.x1 + dx, original.y1 + dy)
                else:
                    opposite_x = original.x1 if self._corner < 2 else original.x0
                    opposite_y = original.y1 if self._corner % 2 == 0 else original.y0
                    if abs(x - opposite_x) < .2 or abs(y - opposite_y) < .2:
                        return
                    zone = ExclusionRect(min(x, opposite_x), min(y, opposite_y), max(x, opposite_x), max(y, opposite_y))
                self.zones = self._before[:self.selected] + (zone,) + self._before[self.selected + 1:]
        else:
            cursor = Qt.CursorShape.CrossCursor
            for i, zone in enumerate(self.zones):
                if self.zone_rect(zone).contains(event.position()):
                    cursor = Qt.CursorShape.SizeAllCursor
                if i == self.selected:
                    for part, point in enumerate(((zone.x0, zone.y0), (zone.x0, zone.y1), (zone.x1, zone.y0), (zone.x1, zone.y1))):
                        if (self.screen(point) - event.position()).manhattanLength() <= 12:
                            cursor = Qt.CursorShape.SizeBDiagCursor if part in (0, 3) else Qt.CursorShape.SizeFDiagCursor
            self.setCursor(cursor)
        self.update()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._drag == "new" and self._draft is not None:
            self.zones += (self._draft,)
            self.selected = len(self.zones) - 1
        if self.zones != self._before:
            self._history.append(self._before)
        self._drag = None
        self._draft = None
        self.changed.emit()
        self.update()

    def wheelEvent(self, event):  # noqa: N802
        self.zoom = max(.25, min(12.0, self.zoom * 1.15 ** (event.angleDelta().y() / 120)))
        self.update()
        event.accept()

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selected()
        elif event.key() == Qt.Key.Key_Z and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.undo()
        elif event.key() == Qt.Key.Key_Escape and self._drag:
            self.zones, self._drag, self._draft = self._before, None, None
            self.update()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#e6ecf2"))
        polygon = QPolygonF([self.screen(point) for point in self.bed_geometry.printable_polygon])
        painter.setPen(QPen(QColor("#8195a5"), 1))
        painter.setBrush(QColor("#ffffff"))
        painter.drawPolygon(polygon)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#64acbd"), 1))
        for segment in self.segments[::max(1, len(self.segments) // 12000)]:
            painter.drawLine(self.screen((segment.start.x, segment.start.y)), self.screen((segment.end.x, segment.end.y)))
        for polygon in self.bed_geometry.excluded_polygons:
            painter.setPen(QPen(QColor("#b95148"), 1))
            painter.setBrush(QColor(185, 80, 70, 70))
            painter.drawPolygon(QPolygonF([self.screen(point) for point in polygon]))
        zones = self.zones + ((self._draft,) if getattr(self, "_draft", None) is not None and self._drag == "new" else ())
        for i, zone in enumerate(zones):
            painter.setPen(QPen(QColor("#b26617"), 2 if i == self.selected else 1))
            painter.setBrush(QColor(240, 161, 67, 80))
            rect = self.zone_rect(zone)
            painter.drawRect(rect)
            painter.drawText(rect.adjusted(4, 4, -4, -4), Qt.AlignmentFlag.AlignTop, str(i + 1))
            if i == self.selected:
                margin = self.head_radius_mm * self.transform()[0]
                if margin:
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.setPen(QPen(QColor("#bd8d55"), 1, Qt.PenStyle.DashLine))
                    painter.drawRoundedRect(rect.adjusted(-margin, -margin, margin, margin), margin, margin)
                for point in (rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight()):
                    painter.fillRect(QRectF(point.x() - 4, point.y() - 4, 8, 8), QColor("#b26617"))
        painter.setPen(QColor("#344e64"))
        painter.drawText(12, 20, "Draufsicht · X → · Y ↑ · Maße in mm")
        if 0 <= self.selected < len(self.zones):
            z = self.zones[self.selected]
            painter.drawText(12, self.height() - 14, f"Sperrfläche {self.selected + 1}: X {z.x0:.1f}–{z.x1:.1f} · Y {z.y0:.1f}–{z.y1:.1f} mm")


class PreprocessorExclusionDialog(QDialog):
    def __init__(self, geometry, zones=(), segments=(), parent=None, *, head_radius_mm=0):
        super().__init__(parent)
        self.setWindowTitle("Eigene Druckbett-Sperrflächen")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.resize(1050, 800)
        layout = QVBoxLayout(self)
        help_text = QLabel("Links ziehen: Rechteck zeichnen. Fläche ziehen: verschieben. Eckpunkte ziehen: Größe ändern. "
            "Mausrad: zoomen. Rechts oder mit dem Mausrad ziehen: Ansicht verschieben. Entf: ausgewählte Fläche löschen. "
            "Rote Profilflächen bleiben geschützt. Eigene orange Flächen gelten für diese Quelle. "
            f"Zusätzlich gilt ein Druckkopf-Abstand von {head_radius_mm:g} mm; die gestrichelte Kontur zeigt ihn für die Auswahl.")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        self.canvas = ExclusionCanvas(geometry, zones, segments, head_radius_mm=head_radius_mm)
        layout.addWidget(self.canvas, 1)
        tools = QHBoxLayout()
        for title, action in (("Einpassen", self.canvas.fit), ("Rückgängig", self.canvas.undo),
                ("Auswahl löschen", self.canvas.delete_selected), ("Eigene Flächen leeren", self.canvas.clear)):
            button = QPushButton(title)
            button.clicked.connect(action)
            tools.addWidget(button)
        layout.addLayout(tools)
        self.count_label = QLabel()
        layout.addWidget(self.count_label)
        self.canvas.changed.connect(lambda: self.count_label.setText(f"{len(self.canvas.zones)} eigene Sperrflächen · maximal 64"))
        self.canvas.changed.emit()
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Übernehmen")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Abbrechen")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
