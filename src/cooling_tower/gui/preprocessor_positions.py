"""Top-view position editing with cancelable, authoritative placement checks."""
from dataclasses import replace
from copy import deepcopy
from collections import OrderedDict
from itertools import count
import math
import time
import traceback

from PySide6.QtCore import QLineF, QPointF, QRectF, QSignalBlocker, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPainterPathStroker, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from cooling_tower.gui.background_jobs import JobKind
from cooling_tower.gui.worker_contract import CancelableWorker
from cooling_tower.gui.widgets.preview_canvas import PreviewCanvas
from cooling_tower.gui.widgets.preprocessor_widgets import ColourLegend, CoordinatePair
from cooling_tower.gui.widgets.committed_numeric_inputs import CommittedDoubleSpinBox
from cooling_tower.gui.widgets.preview_busy_overlay import PreviewBusyOverlay
from cooling_tower.gui.widgets.activity_progress_bar import ActivityProgressBar
from cooling_tower.gui.preprocessor_position_regions import PositionDragWorker, PositionRegionWorker
from cooling_tower.gui.design_tokens import METRICS
from cooling_tower.preprocessor import PreprocessorSettings
from cooling_tower.preview.toolpath import PreviewCancelled


POSITION_FIELDS = ("automatic_position", "center_x_mm", "center_y_mm", "automatic_wait_position", "wait_x_mm", "wait_y_mm", "edge_clearance_mm")
_JOB_IDS = count(-2_000_000, -1)


def position_solution_key(settings):
    return (settings.edge_clearance_mm, settings.automatic_position,
        None if settings.automatic_position else (settings.center_x_mm, settings.center_y_mm),
        settings.automatic_wait_position, None if settings.automatic_wait_position else (settings.wait_x_mm, settings.wait_y_mm))


def position_cache_key(request):
    """Bind in-memory results to immutable inputs and current file identities."""
    try:
        signatures = []
        for path in (request.prepared_source.analysis_gcode_path, request.prepared_source.source_artifact.original_path):
            stat = path.stat()
            signatures.append((stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
    except OSError:
        return None
    defaults = PreprocessorSettings()
    base = replace(request.settings, **{name: getattr(defaults, name) for name in POSITION_FIELDS})
    return (request.prepared_source, request.snapshot, deepcopy(request.profile), base, tuple(signatures))


class PositionCache:
    def __init__(self, key, context=None):
        self.key, self.context = key, context
        self.solutions = OrderedDict()
        self._automatic_key = None
        self.requested_key = None

    def matches(self, request):
        return self.key is not None and self.key == position_cache_key(request)

    def remember(self, settings, solution, error):
        key = position_solution_key(settings)
        if self._automatic_key is None and settings.automatic_position and settings.automatic_wait_position:
            self._automatic_key = key
        self.solutions[key] = (solution, error)
        self.solutions.move_to_end(key)
        while len(self.solutions) > 24:
            oldest = next(k for k in self.solutions if k not in (self._automatic_key, self.requested_key))
            del self.solutions[oldest]


class PositionCanvas(QWidget):
    moved = Signal(str, object)
    drag_started = Signal(str)
    drag_finished = Signal(str)
    EDGE_COLOR = "#62cfc5"

    def __init__(self, geometry, parent=None):
        super().__init__(parent)
        self.bed_geometry = geometry
        self.segments = ()
        self.positions = {}
        self.drag_enabled = True
        self.routes = ()
        self.base_width_mm = 0
        self.brim_width_mm = self.brim_gap_mm = 0.0
        self.zoom, self.pan = 1.0, QPointF()
        self._drag = None
        self._drag_valid = None
        self.valid = False
        self.pending = False
        self.region_map = None
        self._region_image = None
        self._scene_frame = None
        self._scene_frame_key = None
        self._static_frame_key = None
        self._bed_frame = self._model_frame = None
        self.edge_clearance_mm = 5
        self.fit_button = QPushButton("Druckbett einpassen", self)
        self.fit_button.setObjectName("layerRangeFitButton")
        self.fit_button.setAutoDefault(False)
        self.fit_button.setFixedHeight(34)
        self.fit_button.setStyleSheet("QPushButton { min-height: 32px; max-height: 32px; padding: 0 10px; }")
        self.fit_button.clicked.connect(self.fit)
        self.reset_button = QPushButton("Positionen zurücksetzen", self)
        self.reset_button.setAutoDefault(False)
        self.reset_button.setFixedHeight(34)
        self.reset_button.setStyleSheet("QPushButton { min-height: 32px; max-height: 32px; padding: 0 10px; }")
        self.reset_button.setEnabled(False)
        self.busy_overlay = PreviewBusyOverlay(self)
        self.setMinimumSize(360, 300)
        self.setMouseTracking(True)
        self.setAccessibleName("Druckbett-Draufsicht: Turm oder Warteposition ziehen; Mausrad zoomt, rechts ziehen verschiebt die Ansicht")

    def transform(self):
        b = self.bed_geometry.bounds
        scale = max(.01, min((self.width()-90)/(b.maximum_x_mm-b.minimum_x_mm),
            (self.height()-90)/(b.maximum_y_mm-b.minimum_y_mm))) * self.zoom
        return scale, (b.maximum_x_mm+b.minimum_x_mm)/2, (b.maximum_y_mm+b.minimum_y_mm)/2

    def screen(self, xy):
        scale, cx, cy = self.transform()
        return QPointF(self.width()/2+self.pan.x()+(xy[0]-cx)*scale,
            self.height()/2+self.pan.y()-(xy[1]-cy)*scale)

    def world(self, point):
        scale, cx, cy = self.transform()
        return (cx+(point.x()-self.width()/2-self.pan.x())/scale,
            cy-(point.y()-self.height()/2-self.pan.y())/scale)

    def fit(self):
        self.zoom, self.pan = 1.0, QPointF()
        self._update_fit_button()
        self.update()
        self.busy_overlay.refresh_background()

    def _update_fit_button(self):
        needs_fit = abs(self.zoom-1) > 1e-9 or abs(self.pan.x()) > 1e-9 or abs(self.pan.y()) > 1e-9
        if self.fit_button.property("needsFit") != needs_fit:
            self.fit_button.setProperty("needsFit", needs_fit)
            self.fit_button.style().unpolish(self.fit_button)
            self.fit_button.style().polish(self.fit_button)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self.fit_button.adjustSize()
        self.reset_button.adjustSize()
        self.fit_button.move(max(8, self.width()-self.fit_button.width()-10), 10)
        self.reset_button.move(10, max(8, self.height()-self.reset_button.height()-10))

    def fit_positions(self):
        """Keep small models and their drag handles legible on large beds."""
        points = [xy for xy in self.positions.values()]
        points.extend((p.x, p.y) for segment in self.segments for p in (segment.start, segment.end))
        if not points:
            return
        lo = (min(p[0] for p in points), min(p[1] for p in points))
        hi = (max(p[0] for p in points), max(p[1] for p in points))
        margin = max(12, self.base_width_mm/2+self.brim_width_mm+self.brim_gap_mm+8)
        self.fit()
        scale, _, _ = self.transform()
        self.zoom = max(1, min(8, (self.width()-90)/((hi[0]-lo[0]+2*margin)*scale),
            (self.height()-90)/((hi[1]-lo[1]+2*margin)*scale)))
        centre = self.screen(((lo[0]+hi[0])/2, (lo[1]+hi[1])/2))
        self.pan += QPointF(self.width()/2, self.height()/2)-centre
        self._update_fit_button()
        self.update()
        self.busy_overlay.refresh_background()

    def hit(self, point):
        if not self.drag_enabled:
            return None
        for name in ("wait", "tower"):
            if name in self.positions:
                p = self.screen(self.positions[name])
                radius = max(12, self.base_width_mm*self.transform()[0]/2) if name == "tower" else 12
                if math.hypot(point.x()-p.x(), point.y()-p.y()) <= radius:
                    return name
        return None

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() in (Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton):
            self._drag = "pan"
            self._start, self._pan_start = event.position(), QPointF(self.pan)
        elif event.button() == Qt.MouseButton.LeftButton:
            self._drag = self.hit(event.position())
            if self._drag:
                self._drag_valid = None
                xy = self.world(event.position())
                p = self.positions[self._drag]
                self._offset = (p[0]-xy[0], p[1]-xy[1])
                self.drag_started.emit(self._drag)
        if self._drag:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._drag == "pan":
            self.pan = self._pan_start + event.position() - self._start
            self._update_fit_button()
            self.update()
            self.busy_overlay.refresh_background()
        elif self._drag:
            x, y = self.world(event.position())
            xy = (round(max(-2000, min(2000, x+self._offset[0])), 2),
                round(max(-2000, min(2000, y+self._offset[1])), 2))
            if xy != self.positions[self._drag]:
                self.positions[self._drag] = xy
                self._drag_valid = self.region_valid(xy)
                self.moved.emit(self._drag, xy)
                self.update()
        else:
            self.setCursor(Qt.CursorShape.OpenHandCursor if self.hit(event.position()) else Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event):  # noqa: N802
        kind = self._drag
        self._drag = None
        self._drag_valid = None
        if kind in ("tower", "wait"):
            self.drag_finished.emit(kind)
        self.setCursor(Qt.CursorShape.OpenHandCursor if self.hit(event.position()) else Qt.CursorShape.ArrowCursor)
        event.accept()

    def wheelEvent(self, event):  # noqa: N802
        before = self.world(event.position())
        self.zoom = max(.3, min(10, self.zoom * 1.15**(event.angleDelta().y()/120)))
        self.pan += event.position()-self.screen(before)
        self._update_fit_button()
        self.update()
        self.busy_overlay.refresh_background()
        event.accept()

    def bed_path(self):
        path = QPainterPath()
        path.addPolygon(QPolygonF([self.screen(xy) for xy in self.bed_geometry.printable_polygon]))
        path.closeSubpath()
        return path

    def set_regions(self, regions):
        self.region_map = regions
        if regions is None:
            self._region_image = None
        else:
            colours = (bytes((218, 87, 90, 23)), bytes((53, 183, 106, 38)), bytes((0, 0, 0, 0)))
            pixels = b"".join(colours[state] for state in regions.states)
            self._region_image = QImage(pixels, regions.columns, regions.rows, regions.columns*4,
                QImage.Format.Format_RGBA8888).copy()
            if self._drag in self.positions and self._drag_valid is None:
                self._drag_valid = self.region_valid(self.positions[self._drag])
        self.update()

    def region_valid(self, xy):
        regions = self.region_map
        if regions is None:
            return None
        b = regions.bounds
        x = math.floor((xy[0]-b.minimum_x_mm)/(b.maximum_x_mm-b.minimum_x_mm)*regions.columns)
        y = math.floor((b.maximum_y_mm-xy[1])/(b.maximum_y_mm-b.minimum_y_mm)*regions.rows)
        if not 0 <= x < regions.columns or not 0 <= y < regions.rows:
            return False
        state = regions.states[y*regions.columns+x]
        return None if state == 2 else bool(state)

    def paintEvent(self, event):  # noqa: N802
        # Transparent animation repaints propagate to this parent. Reuse the
        # unchanged scene instead of projecting thousands of model paths again.
        ratio = max(1., self.devicePixelRatioF())
        key = (self.width(), self.height(), ratio, self.font().key(), id(self.bed_geometry), id(self.segments),
            tuple(sorted(self.positions.items())), id(self.routes), self.base_width_mm,
            self.brim_width_mm, self.brim_gap_mm,
            self.edge_clearance_mm, self.zoom, self.pan.x(), self.pan.y(), self.valid, self.pending,
            id(self.region_map), self._drag, self._drag_valid)
        if key != self._scene_frame_key:
            frame = QPixmap(max(1, round(self.width()*ratio)), max(1, round(self.height()*ratio)))
            frame.setDevicePixelRatio(ratio)
            painter = QPainter(frame)
            self._paint_scene(painter)
            painter.end()
            self._scene_frame, self._scene_frame_key = frame, key
        p = QPainter(self)
        p.drawPixmap(0, 0, self._scene_frame)

    def _paint_scene(self, p):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        key = (self.width(), self.height(), self.devicePixelRatioF(), id(self.bed_geometry),
            id(self.segments), self.edge_clearance_mm, self.zoom, self.pan.x(), self.pan.y())
        if key != self._static_frame_key:
            self._bed_frame = self._static_frame(self._paint_bed)
            self._model_frame = self._static_frame(self._paint_model)
            self._static_frame_key = key
        p.drawPixmap(0, 0, self._bed_frame)
        if self._region_image is not None:
            b = self.region_map.bounds
            p.save()
            p.setClipPath(self.bed_path())
            p.drawImage(QRectF(self.screen((b.minimum_x_mm, b.maximum_y_mm)),
                self.screen((b.maximum_x_mm, b.minimum_y_mm))), self._region_image)
            p.restore()
        p.drawPixmap(0, 0, self._model_frame)
        self._paint_positions(p)

    def _static_frame(self, paint):
        ratio = max(1., self.devicePixelRatioF())
        frame = QPixmap(max(1, round(self.width()*ratio)), max(1, round(self.height()*ratio)))
        frame.setDevicePixelRatio(ratio)
        frame.fill(Qt.GlobalColor.transparent)
        painter = QPainter(frame)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint(painter)
        painter.end()
        return frame

    def _paint_bed(self, p):
        p.fillRect(self.rect(), QColor("#171a20"))
        p.setPen(QPen(QColor(PreviewCanvas.BED_COLOR), 1))
        p.setBrush(QColor("#242a32"))
        bed = self.bed_path()
        p.drawPath(bed)
        stroker = QPainterPathStroker()
        stroker.setWidth(2*self.edge_clearance_mm*self.transform()[0])
        stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        inner = bed.subtracted(stroker.createStroke(bed))
        p.setPen(QPen(QColor(self.EDGE_COLOR), 1.5, Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(inner)
        p.setPen(QPen(QColor("#ed756c"), 1))
        p.setBrush(QColor(185, 80, 70, 95))
        for polygon in self.bed_geometry.excluded_polygons:
            p.drawPolygon(QPolygonF([self.screen(xy) for xy in polygon]))
    def _paint_model(self, p):
        # A drag only composites this raster. Thousands of individual native
        # drawLine calls can each hand the GIL to a busy validation worker.
        scale, cx, cy = self.transform()
        ox, oy = self.width()/2+self.pan.x()-cx*scale, self.height()/2+self.pan.y()+cy*scale
        p.setPen(QPen(QColor(PreviewCanvas.OBJECT_COLOR), 1))
        segments = self.segments[::max(1, len(self.segments)//18000)]
        for start in range(0, len(segments), 4096):
            p.drawLines([QLineF(ox+s.start.x*scale, oy-s.start.y*scale,
                ox+s.end.x*scale, oy-s.end.y*scale) for s in segments[start:start+4096]])

    def _paint_positions(self, p):
        for routes in self.routes[::max(1, len(self.routes)//64)]:
            for index, route in enumerate(routes):
                p.setPen(QPen(QColor(PreviewCanvas.WAIT_TRAVEL_COLOR if routes[0] and index < 2 else PreviewCanvas.TOWER_TRAVEL_COLOR),
                    1, Qt.PenStyle.DashLine))
                p.drawLines([QLineF(self.screen(a), self.screen(b)) for a, b in zip(route, route[1:])])
        for name, xy in self.positions.items():
            centre = self.screen(xy)
            active_colour = (QColor("#43d98a" if self._drag_valid else "#ff746e")
                if name == self._drag and self._drag_valid is not None else None)
            if name == "tower" and self.brim_width_mm:
                scale = self.transform()[0]
                path = QPainterPath()
                outer = (self.base_width_mm/2+self.brim_gap_mm+self.brim_width_mm)*scale
                inner_radius = (self.base_width_mm/2+self.brim_gap_mm)*scale
                path.addEllipse(centre, outer, outer)
                hole = QPainterPath()
                hole.addEllipse(centre, inner_radius, inner_radius)
                brim_colour = QColor(PreviewCanvas.BRIM_COLOR)
                brim_colour.setAlpha(100)
                p.fillPath(path.subtracted(hole), brim_colour)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(active_colour or QColor(PreviewCanvas.BRIM_COLOR), 3 if active_colour else 1))
                p.drawEllipse(centre, outer, outer)
            colour = QColor(PreviewCanvas.TOWER_COLOR if name == "tower" else PreviewCanvas.WAIT_POSITION_COLOR)
            outline = colour if self.valid or self.pending else QColor("#ed756c")
            if active_colour is not None:
                outline = active_colour
            p.setPen(QPen(outline, 3 if name == self._drag else 2))
            fill = QColor(colour)
            fill.setAlpha(65)
            p.setBrush(fill)
            radius = self.base_width_mm*self.transform()[0]/2 if name == "tower" else 7
            p.drawEllipse(centre, radius, radius)
            p.drawLine(centre+QPointF(-5, 0), centre+QPointF(5, 0))
            p.drawLine(centre+QPointF(0, -5), centre+QPointF(0, 5))
            p.setPen(colour)
            if name == "tower":
                p.drawText(centre+QPointF(-radius-8-p.fontMetrics().horizontalAdvance("Turm"), 16), "Turm")
            else:
                p.drawText(centre+QPointF(radius+8, -8), "Warten")
        origin = self.screen((0, 0))
        for title, colour, offset in (("X", PreviewCanvas.X_AXIS_COLOR, QPointF(36, 0)),
                ("Y", PreviewCanvas.Y_AXIS_COLOR, QPointF(0, -36))):
            p.setPen(QPen(QColor(colour), 2))
            p.drawLine(origin, origin+offset)
            p.drawText(origin+offset+QPointF(5, -4), title)


class PositionWorker(CancelableWorker):
    progress = Signal(int, int, str)
    succeeded = Signal(int, object)
    failed = Signal(int, str, str)
    finished = Signal(int)

    def __init__(self, revision, service, request, context=None, settings=None):
        super().__init__()
        self.revision, self.service, self.request = revision, service, request
        self.context, self.settings = context, settings
        self._last_progress = 0
        self._progress_floor = 0

    def _report(self, percent, step):
        now = time.monotonic()
        if not self._last_progress or now-self._last_progress >= .08:
            self._last_progress = now
            self._progress_floor = max(self._progress_floor, percent)
            self.progress.emit(self.revision, self._progress_floor, step)

    @Slot()
    def run(self):
        try:
            context = self.context or self.service.placement_context(self.request, cancellation_event=self.cancellation_event,
                progress_callback=lambda p, s: self._report(min(45, p), s))
            settings = self.settings or replace(context.settings, automatic_position=True, automatic_wait_position=True)
            try:
                solution, error = context.resolve(settings, event=self.cancellation_event,
                    progress_callback=self._report), ""
            except ValueError as invalid:
                solution, error = None, getattr(invalid, "reason", str(invalid))
            if context.height_mm and self.context is None:
                self._report(99, "Ablagebereiche zum Verschieben vorbereiten …")
                if solution is not None:
                    centre, wait, _ = solution
                    region_settings = replace(settings, center_x_mm=round(centre[0], 2), center_y_mm=round(centre[1], 2),
                        wait_x_mm=round(wait[0], 2), wait_y_mm=round(wait[1], 2))
                    for kind in ("tower", "wait"):
                        context.regions.regions(kind, region_settings, event=self.cancellation_event)
            if not self.cancellation_requested():
                self.succeeded.emit(self.revision, (context, solution, error))
        except PreviewCancelled:
            pass
        except Exception as error:
            if not self.cancellation_requested():
                self.failed.emit(self.revision, str(error), traceback.format_exc())
        finally:
            self.finished.emit(self.revision)


class PreprocessorPositionDialog(QDialog):
    def __init__(self, request, service, manager, geometry, manual_edits=(), parent=None, *, cache=None):
        super().__init__(parent)
        self.setWindowTitle("Turm- und Warteposition")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.resize(1000, 800)
        self.request, self.service, self.manager = request, service, manager
        self.cache = cache or PositionCache(position_cache_key(request))
        self.context, self.job_id = self.cache.context, None
        self.revision, self._closing = 0, False
        self._seed_manual = set(manual_edits)
        self._valid_revision = None
        self._pending = False
        self._dragging = None
        self._region_job_id = None
        self._region_token = None
        self._region_cache = OrderedDict()
        self._warm_job_id = self._warm_token = None
        self._warm_pending = False
        self._point_worker = self._point_job_id = self._point_token = None
        self.settings = request.settings
        layout = QVBoxLayout(self)
        self.canvas = PositionCanvas(geometry)
        self.canvas.edge_clearance_mm = request.settings.edge_clearance_mm
        self.canvas.moved.connect(self.move_position)
        self.canvas.drag_started.connect(self._begin_drag)
        self.canvas.drag_finished.connect(self._end_drag)
        self.canvas.reset_button.clicked.connect(self.reset_positions)
        layout.addWidget(self.canvas, 1)
        controls = QHBoxLayout()
        controls.setSpacing(22)
        self.editors, self.automatic, self.reset_buttons = {}, {}, {}
        self.control_columns = []
        for key, title, flag, fields in (("tower", "Turmmitte", "automatic_position", ("center_x_mm", "center_y_mm")),
                ("wait", "Warteposition", "automatic_wait_position", ("wait_x_mm", "wait_y_mm"))):
            column_widget = QWidget()
            column = QVBoxLayout(column_widget)
            column.setContentsMargins(0, 0, 0, 0)
            column.setAlignment(Qt.AlignmentFlag.AlignTop)
            column.addWidget(QLabel("<b>"+title+"</b>"))
            automatic_row = QHBoxLayout()
            automatic_row.setContentsMargins(0, 0, 0, 0)
            automatic = QCheckBox("Automatisch")
            automatic.setChecked(getattr(request.settings, flag))
            self.automatic[key] = automatic
            automatic_row.addWidget(automatic)
            automatic_row.addStretch(1)
            reset = QPushButton("↺")
            reset.setObjectName("settingResetButton")
            reset.setAutoDefault(False)
            reset.setFixedSize(METRICS.reset_button_size_px, METRICS.reset_button_size_px)
            reset.setAccessibleName(title+" zurücksetzen")
            reset.setToolTip(title+" automatisch berechnen")
            reset.clicked.connect(lambda _checked=False, k=key: self.reset_positions(k))
            self.reset_buttons[key] = reset
            automatic_row.addWidget(reset)
            column.addLayout(automatic_row)
            editors = [CommittedDoubleSpinBox(), CommittedDoubleSpinBox()]
            for axis, editor, field in zip(("X", "Y"), editors, fields):
                editor.setRange(-2000, 2000)
                editor.setDecimals(2)
                editor.setValue(getattr(request.settings, field))
                editor.setAccessibleName(title+" "+axis)
            self.editors[key] = editors
            column.addWidget(CoordinatePair(*editors))
            controls.addWidget(column_widget, 0, Qt.AlignmentFlag.AlignTop)
            self.control_columns.append(column_widget)
            automatic.toggled.connect(lambda _checked, k=key: self.edit_position(k))
            for editor in editors:
                editor.valueChanged.connect(lambda _value, k=key: self.edit_position(k))
                editor.lineEdit().textEdited.connect(lambda _text, k=key: self.edit_position(k))
                editor.editingFinished.connect(lambda k=key: self.edit_position(k))
        legend_column = QWidget()
        legend_layout = QVBoxLayout(legend_column)
        legend_layout.setContentsMargins(0, 0, 0, 0)
        legend_layout.addWidget(QLabel("<b>Farben</b>"))
        self.legend = ColourLegend((("Modell", PreviewCanvas.OBJECT_COLOR), ("Turm", PreviewCanvas.TOWER_COLOR),
            ("Warteposition", PreviewCanvas.WAIT_POSITION_COLOR),
            ("Brim", PreviewCanvas.BRIM_COLOR),
            ("Sicherer Randabstand", PositionCanvas.EDGE_COLOR)), columns=1)
        legend_layout.addWidget(self.legend)
        controls.addWidget(legend_column, 0, Qt.AlignmentFlag.AlignTop)
        self.control_columns.append(legend_column)
        instructions_column = QWidget()
        instructions_layout = QVBoxLayout(instructions_column)
        instructions_layout.setContentsMargins(0, 0, 0, 0)
        instructions_layout.addWidget(QLabel("<b>Bedienung</b>"))
        instructions = QLabel("• Turm / Wartepunkt ziehen: Position ändern\n"
            "• Verschieben schaltet Automatisch aus\n• Rechts / mittig ziehen: Ansicht verschieben\n• Mausrad: Zoom\n• Beim Ziehen: Grün gültig / Rot gesperrt")
        instructions.setWordWrap(True)
        instructions_layout.addWidget(instructions)
        edge_row = QHBoxLayout()
        edge_row.addWidget(QLabel("Randabstand"))
        self.edge_spin = CommittedDoubleSpinBox()
        self.edge_spin.setObjectName("positionEdgeClearance")
        self.edge_spin.setRange(5, 100)
        self.edge_spin.setDecimals(2)
        self.edge_spin.setSuffix(" mm")
        self.edge_spin.setValue(request.settings.edge_clearance_mm)
        self.edge_spin.setFixedWidth(115)
        self.edge_spin.setStyleSheet("QDoubleSpinBox { padding: 0 3px; }")
        self.edge_spin.setAccessibleName("Sicherheitsabstand zur Druckbettkante")
        self.edge_spin.setToolTip("Mindestens 5 mm Abstand zu den äußeren Druckbettkanten. Die Linie zeigt die nutzbare innere Grenze.")
        self.edge_spin.valueChanged.connect(self._edge_changed)
        self.edge_spin.lineEdit().textEdited.connect(lambda _: self._edge_changed())
        self.edge_spin.editingFinished.connect(self._edge_changed)
        edge_row.addWidget(self.edge_spin)
        edge_row.addStretch(1)
        instructions_layout.addLayout(edge_row)
        instructions_layout.addStretch(1)
        controls.addWidget(instructions_column, 1, Qt.AlignmentFlag.AlignTop)
        self.control_columns.append(instructions_column)
        layout.addLayout(controls)
        self.status = QLabel("Automatische Ausgangspositionen und Fahrwege werden berechnet …")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(self.status.fontMetrics().lineSpacing()*2)
        status_row = QHBoxLayout()
        status_row.addWidget(self.status, 1)
        self.validation_progress = ActivityProgressBar()
        self.validation_progress.setObjectName("mainProgressBar")
        self.validation_progress.setFixedSize(140, 18)
        self.validation_progress.hide()
        status_row.addWidget(self.validation_progress)
        layout.addLayout(status_row)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.apply_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.apply_button.setText("Übernehmen")
        self.apply_button.setDefault(False)
        self.apply_button.setEnabled(False)
        self.apply_button.setStyleSheet("QPushButton { background: #176b45; color: white; border: 1px solid #176b45; }"
            "QPushButton:disabled { background: #e3e8ed; color: #89949f; border-color: #cdd5de; }")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Abbrechen")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setStyleSheet(
            "QPushButton { background: #fff1f0; color: #b42318; border: 1px solid #e4aaa6; }")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._start_check)
        self.manager.job_released.connect(self._released)
        self._set_controls_enabled(self.context is not None and bool(self.context.height_mm))
        self.finished.connect(self._finish)
        if self.context is not None:
            automatic_settings = replace(self.context.settings, automatic_position=True, automatic_wait_position=True,
                edge_clearance_mm=request.settings.edge_clearance_mm)
            automatic_result = self.cache.solutions.get(position_solution_key(automatic_settings))
            if automatic_result and automatic_result[0] and not automatic_result[1]:
                for key, flag, xy in (("tower", "automatic_position", automatic_result[0][0]),
                        ("wait", "automatic_wait_position", automatic_result[0][1])):
                    if xy is not None and (getattr(request.settings, flag) or flag not in self._seed_manual):
                        for editor, value in zip(self.editors[key], xy):
                            with QSignalBlocker(editor):
                                editor.setValue(value)
        self.cache.requested_key = position_solution_key(self.current_settings() if self.context else request.settings)
        cached = self.cache.solutions.get(self.cache.requested_key)
        if self.context is not None and cached is not None:
            self._checked(self.revision, (self.context, *cached))
            self.canvas.fit()
        elif self.context is not None:
            self.canvas.segments = self.context.object_segments
            self._display_positions({key: tuple(editor.value() for editor in editors) for key, editors in self.editors.items()})
            self.canvas.fit()
            self.edit_position("tower")
        else:
            self.canvas.busy_overlay.set_busy(True, step="Originalquelle und Druckprofil prüfen …", title="Positionen werden berechnet")
            self._start_check()

    def _set_controls_enabled(self, enabled):
        self.edge_spin.setEnabled(enabled)
        self.canvas.fit_button.setEnabled(enabled)
        for key, editors in self.editors.items():
            self.automatic[key].setEnabled(enabled)
            self.reset_buttons[key].setEnabled(enabled and not self.automatic[key].isChecked())
            for editor in editors:
                editor.setEnabled(enabled and not self.automatic[key].isChecked())
        self.canvas.reset_button.setEnabled(enabled and any(not box.isChecked() for box in self.automatic.values()))

    def reset_positions(self, key=None):
        if self.context is None:
            return
        for name in (key,) if key in self.automatic else self.automatic:
            with QSignalBlocker(self.automatic[name]):
                self.automatic[name].setChecked(True)
        self.edit_position("tower")

    def _edge_changed(self):
        self.canvas.edge_clearance_mm = self.edge_spin.value()
        self.canvas.update()
        self.edit_position("tower")

    def _display_positions(self, positions):
        for key, xy in positions.items():
            self.canvas.positions[key] = xy
            for editor, value in zip(self.editors[key], xy):
                with QSignalBlocker(editor):
                    editor.setValue(value)
        self.canvas.update()

    def move_position(self, key, xy):
        with QSignalBlocker(self.automatic[key]):
            self.automatic[key].setChecked(False)
        self._display_positions({key: xy})
        self.edit_position(key)
        if self._dragging == key and self._point_worker is not None:
            self._point_worker.request(xy)

    def _begin_drag(self, kind):
        if self.context is None:
            return
        self._dragging = kind
        self.revision += 1
        self._valid_revision = None
        self.apply_button.setEnabled(False)
        self.canvas.pending = True
        self.canvas.routes = ()
        self._timer.stop()
        if self.job_id:
            self.manager.cancel_job(self.job_id, reason="position_drag_started")
        self.canvas.busy_overlay.set_busy(False)
        settings = replace(self.current_settings(), automatic_position=False, automatic_wait_position=False)
        self._point_token = next(_JOB_IDS)
        self._point_worker = PositionDragWorker(self._point_token, self.context, settings, kind)
        self._point_worker.checked.connect(self._drag_point_checked)
        self._point_worker.failed.connect(self._region_failed)
        self._point_worker.request(self.canvas.positions[kind])
        self._point_job_id = self.manager.start_job(kind=JobKind.MANUAL_VIEW, request_id=self._point_token,
            worker=self._point_worker, parent_operation_id="preprocessor-position-drag")
        other = (settings.wait_x_mm, settings.wait_y_mm) if kind == "tower" else (settings.center_x_mm, settings.center_y_mm)
        self._region_cache_key = kind, other, settings.edge_clearance_mm
        cached = self._region_cache.get(self._region_cache_key) or self.context.regions.immediate_regions(kind, settings)
        self.canvas.set_regions(cached)
        self.status.setText("Grün: gültig · Rot: gesperrt · Bereiche gelten für die angezeigte Gegenposition.")
        self.canvas.setToolTip("Die Farbflächen sind eine vorsichtige Orientierung. Der grüne oder rote Umriss zeigt "
            "die Prüfung der aktuellen Position; nach dem Ablegen werden alle Fahrwege vollständig geprüft.")
        if cached is not None:
            self.validation_progress.hide()
            return
        if self._region_job_id:
            self.manager.cancel_job(self._region_job_id, reason="position_region_changed")
        self._region_token = next(_JOB_IDS)
        worker = PositionRegionWorker(self._region_token, self.context, settings, kind)
        worker.updated.connect(self._region_updated)
        worker.failed.connect(self._region_failed)
        self.validation_progress.setValue(0)
        self.validation_progress.show()
        self._region_job_id = self.manager.start_job(kind=JobKind.MANUAL_VIEW, request_id=self._region_token,
            worker=worker, parent_operation_id="preprocessor-position-regions")

    def _warm_regions(self):
        """Prepare both handle maps before the next mouse press, off the UI thread."""
        if self._warm_job_id:
            # Position changes do not invalidate the expensive source fields.
            # Let their one preparation finish, then update the two cheap masks.
            self._warm_pending = True
            return
        self._warm_pending = False
        settings = replace(self.current_settings(), automatic_position=False, automatic_wait_position=False)
        for kind in ("tower", "wait"):
            self.context.regions.immediate_regions(kind, settings)
        if self._regions_ready(settings):
            self.canvas.drag_enabled = True
            self._finish_region_preparation()
            return
        self.canvas.drag_enabled = False
        self.validation_progress.setValue(99)
        self.validation_progress.show()
        if self._valid_revision == self.revision:
            self.status.setText("Ablagebereiche zum Verschieben vorbereiten …")
            self.status.setStyleSheet("color: #526b7e;")
        self._warm_settings = settings
        self._warm_token = next(_JOB_IDS)
        worker = PositionRegionWorker(self._warm_token, self.context, settings)
        worker.updated.connect(self._regions_warmed)
        worker.failed.connect(self._regions_warm_failed)
        self._warm_job_id = self.manager.start_job(kind=JobKind.MANUAL_VIEW, request_id=self._warm_token,
            worker=worker, parent_operation_id="preprocessor-position-region-preparation")

    def _regions_warmed(self, token, maps):
        if self._closing or token != self._warm_token:
            return
        settings = self._warm_settings
        for kind, regions in maps.items():
            other = (settings.wait_x_mm, settings.wait_y_mm) if kind == "tower" else (settings.center_x_mm, settings.center_y_mm)
            key = kind, other, settings.edge_clearance_mm
            self._remember_regions(key, regions)
            if self._dragging == kind and self._region_cache_key == key and self.canvas.region_map is None:
                self.canvas.set_regions(regions)
                self.validation_progress.hide()
        if self._dragging is None and self._regions_ready(self.current_settings()):
            self.canvas.drag_enabled = True
            self._finish_region_preparation()

    def _finish_region_preparation(self):
        if getattr(self, "_checked_revision", None) == self.revision:
            self.canvas.busy_overlay.set_busy(False)
            self.validation_progress.hide()
            self.status.setText(self._position_status[0])
            self.status.setStyleSheet(self._position_status[1])

    def _regions_ready(self, settings):
        return all(self.context.regions.cached_regions(kind, settings) is not None for kind in ("tower", "wait"))

    def _remember_regions(self, key, regions):
        self._region_cache[key] = regions
        self._region_cache.move_to_end(key)
        while len(self._region_cache) > 6:
            self._region_cache.popitem(last=False)

    def _regions_warm_failed(self, token, message, _details):
        if not self._closing and token == self._warm_token:
            self.status.setText("Ablagebereiche konnten nicht vorbereitet werden: "+message)
            self.canvas.busy_overlay.set_busy(False)
            self.validation_progress.hide()

    def _region_updated(self, token, regions):
        if self._closing or token != self._region_token or self._dragging is None:
            return
        if self.canvas.region_map != regions:
            self.canvas.set_regions(regions)
        self.validation_progress.setValue(round(100*(len(regions.states)-regions.states.count(2))/len(regions.states)))
        if 2 not in regions.states:
            self._remember_regions(self._region_cache_key, regions)
            self.validation_progress.hide()

    def _region_failed(self, token, message, _details):
        if not self._closing and token in (self._region_token, self._point_token) and self._dragging is not None:
            self.status.setText("Ablagebereiche konnten nicht vollständig geprüft werden: "+message)
            self.validation_progress.hide()

    def _drag_point_checked(self, token, point, valid):
        if (not self._closing and token == self._point_token and self._dragging is not None
                and point == self.canvas.positions[self._dragging]):
            self.canvas._drag_valid = valid
            self.canvas.update()

    def _end_drag(self, kind):
        self._dragging = None
        self._point_worker = self._point_token = None
        if self._point_job_id:
            self.manager.cancel_job(self._point_job_id, reason="position_drag_finished")
        self._region_token = None
        self.canvas.set_regions(None)
        self.canvas.setToolTip("")
        if self._region_job_id:
            self.manager.cancel_job(self._region_job_id, reason="position_drag_finished")
        self.edit_position(kind)

    def edit_position(self, key):
        if self.context is None:
            return
        self.canvas.positions[key] = tuple(editor.value() for editor in self.editors[key])
        self.revision += 1
        self._valid_revision = None
        self.apply_button.setEnabled(False)
        self.canvas.valid, self.canvas.routes = False, ()
        self.canvas.pending = True
        self.canvas.busy_overlay.invalidate_background()
        self.canvas.update()
        self._set_controls_enabled(True)
        self.status.setText("Positionen und sämtliche Fahrwege werden geprüft …")
        self.status.setStyleSheet("color: #526b7e;")
        if self._dragging is not None:
            self.status.setText("Grün: gültig · Rot: gesperrt · Bereiche gelten für die angezeigte Gegenposition.")
            self._timer.stop()
            return
        self._pending = not self._drafts_pending()
        if self.job_id:
            self.manager.cancel_job(self.job_id, reason="position_changed")
        if not self._pending:
            self._timer.stop()
            self.canvas.busy_overlay.set_busy(False)
            self.validation_progress.hide()
            self.status.setText("Eingabe mit Enter oder durch Verlassen des Feldes bestätigen."
                if all(editor.hasAcceptableInput() for editors in self.editors.values() for editor in editors)
                else "Bitte für X und Y gültige Koordinaten eingeben.")
            return
        self._show_check_progress(0, self.status.text())
        self._timer.start(180)

    def _drafts_pending(self):
        return self.edge_spin.input_pending or any(editor.input_pending
            for key, editors in self.editors.items() if not self.automatic[key].isChecked() for editor in editors)

    def current_settings(self):
        return replace(self.context.settings, automatic_position=self.automatic["tower"].isChecked(),
            automatic_wait_position=self.automatic["wait"].isChecked(),
            center_x_mm=self.editors["tower"][0].value(), center_y_mm=self.editors["tower"][1].value(),
            wait_x_mm=self.editors["wait"][0].value(), wait_y_mm=self.editors["wait"][1].value(),
            edge_clearance_mm=self.edge_spin.value())

    def _start_check(self):
        if self._closing or self._dragging is not None:
            return
        if self.context and self._drafts_pending():
            return
        if self.job_id is not None:
            self._pending = True
            return
        self._pending = False
        if self.context and not self.edge_spin.hasAcceptableInput():
            self.status.setText("Bitte einen Randabstand zwischen 5 und 100 mm eingeben.")
            self.canvas.busy_overlay.set_busy(False)
            self.validation_progress.hide()
            return
        if self.context and any(not editor.hasAcceptableInput() for key, editors in self.editors.items()
                if not self.automatic[key].isChecked() for editor in editors):
            self.status.setText("Bitte für X und Y gültige Koordinaten eingeben.")
            self.canvas.busy_overlay.set_busy(False)
            self.validation_progress.hide()
            return
        self._check_settings = self.current_settings() if self.context else None
        worker = PositionWorker(self.revision, self.service, self.request, self.context,
            self._check_settings)
        worker.succeeded.connect(self._checked)
        worker.failed.connect(self._failed)
        worker.progress.connect(self._progress)
        self.job_id = self.manager.start_job(kind=JobKind.MANUAL_VIEW, request_id=next(_JOB_IDS),
            worker=worker, parent_operation_id="preprocessor-position")

    def _progress(self, revision, percent, step):
        if not self._closing and revision == self.revision and self._dragging is None:
            self._show_check_progress(percent, step)

    def _show_check_progress(self, percent, step):
        subsequent = self.context is not None
        self.validation_progress.setVisible(subsequent)
        self.validation_progress.setValue(percent)
        if subsequent:
            self.status.setText(step)
        self.canvas.busy_overlay.set_busy(True, percent=percent, step=step, title="Positionen werden berechnet",
            subdued=subsequent, protected_region=self.canvas.bed_path if subsequent else None)

    def _checked(self, revision, data):
        if self._closing or revision != self.revision or self._dragging is not None:
            return
        context, solution, error = data
        initial = self.context is None
        checked_settings = (replace(context.settings, automatic_position=True, automatic_wait_position=True) if initial
            else getattr(self, "_check_settings", None) or self.current_settings())
        self.context = context
        self.cache.context = context
        self.cache.remember(checked_settings, solution, error)
        self.canvas.bed_geometry = context.geometry
        self.canvas.busy_overlay.set_busy(False)
        self.validation_progress.hide()
        self.canvas.segments, self.canvas.base_width_mm = context.object_segments, context.base_width_mm
        self.canvas.brim_width_mm, self.canvas.brim_gap_mm = context.brim_width_mm, context.brim_gap_mm
        if not context.height_mm:
            self.status.setText("Alle Schichten erreichen die Zielzeit. Es sind kein Turm und keine Warteposition erforderlich.")
            self._set_controls_enabled(False)
            return
        self._set_controls_enabled(True)
        if solution is not None:
            centre, wait, routes = solution
            positions = {"tower": centre, "wait": wait}
            if initial:
                for key, flag, x, y in (("tower", "automatic_position", "center_x_mm", "center_y_mm"),
                        ("wait", "automatic_wait_position", "wait_x_mm", "wait_y_mm")):
                    if flag in self._seed_manual and not getattr(self.request.settings, flag):
                        positions[key] = (getattr(self.request.settings, x), getattr(self.request.settings, y))
            self._display_positions(positions)
            if initial:
                self.canvas.fit()
                if not all(box.isChecked() for box in self.automatic.values()):
                    self.edit_position("tower")
                    return
            self.canvas.routes = routes
        else:
            self._display_positions({key: tuple(editor.value() for editor in editors) for key, editors in self.editors.items()})
        self.canvas.valid = not error
        self.canvas.pending = False
        self.canvas.update()
        self._valid_revision = revision if not error else None
        self.apply_button.setEnabled(not error)
        self.status.setText(error or "Turm, Warteposition und alle Fahrwege sind gültig.")
        self.status.setStyleSheet("color: #b42318;" if error else "color: #176b45;")
        self._checked_revision = revision
        self._position_status = self.status.text(), self.status.styleSheet()
        self._warm_regions()

    def _failed(self, revision, message, _details):
        if not self._closing and revision == self.revision:
            self.status.setText(message)
            self.canvas.busy_overlay.set_busy(False)
            self.validation_progress.hide()
            self.status.setStyleSheet("color: #b42318;")
            self.apply_button.setEnabled(False)

    def _released(self, job):
        if job.job_id == self._point_job_id:
            self._point_job_id = None
        if job.job_id == self._warm_job_id:
            self._warm_job_id = None
            if self._warm_pending and not self._closing:
                self._warm_regions()
        if job.job_id == self._region_job_id:
            self._region_job_id = None
        if job.job_id == self.job_id:
            self.job_id = None
            if self._pending and not self._closing and self._dragging is None:
                self._timer.start(0)

    def accept(self):
        if not self.edge_spin.hasAcceptableInput():
            self.apply_button.setEnabled(False)
            self.status.setText("Bitte einen Randabstand zwischen 5 und 100 mm eingeben.")
            self.status.setStyleSheet("color: #b42318;")
            return
        for key, editors in self.editors.items():
            if self.automatic[key].isChecked():
                continue
            for editor in editors:
                if not editor.hasAcceptableInput():
                    self.apply_button.setEnabled(False)
                    self.status.setText("Bitte für X und Y gültige Koordinaten eingeben.")
                    self.status.setStyleSheet("color: #b42318;")
                    return
                editor.interpretText()
        if self._valid_revision != self.revision or not self.apply_button.isEnabled():
            return
        try:
            self.request.validate_source()
        except (ValueError, OSError) as error:
            self.apply_button.setEnabled(False)
            self.status.setText(str(error))
            self.status.setStyleSheet("color: #b42318;")
            return
        self.settings = self.current_settings()
        super().accept()

    def _finish(self, _result):
        self._closing = True
        self._timer.stop()
        self.canvas.busy_overlay.set_busy(False)
        self.validation_progress.hide()
        if self.job_id:
            self.manager.cancel_job(self.job_id, reason="position_editor_closed")
        if self._region_job_id:
            self.manager.cancel_job(self._region_job_id, reason="position_editor_closed")
        if self._warm_job_id:
            self.manager.cancel_job(self._warm_job_id, reason="position_editor_closed")
        if self._point_job_id:
            self.manager.cancel_job(self._point_job_id, reason="position_editor_closed")
