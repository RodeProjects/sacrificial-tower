"""Software-rendered manual editor with one reversible physical transform."""
from __future__ import annotations

import math
from collections import defaultdict
from bisect import bisect_left

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QLineF, QSize, Qt, Signal,QTimer,Slot
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QWidget

from cooling_tower.gui.widgets.layer_range_canvas import LayerRangeCanvas
from cooling_tower.manual.geometry import tessellate, roots
from cooling_tower.gui.background_jobs import JobKind
from cooling_tower.gui.manual_view_worker import SpatialFrame,ManualViewWorker


class ManualCanvas(QWidget):
    HEIGHT_SNAP_DISTANCE_PX = 14.0
    HEIGHT_SNAP_GUIDE_DURATION_MS = 850
    selection_changed = Signal(str)
    move_requested = Signal(str, float, float)
    control_requested = Signal(int, int, float, float)
    insert_requested = Signal(float)
    remove_requested = Signal(str)
    interaction_started = Signal()
    interaction_finished = Signal()
    view_changed = Signal(str)
    OBJECT_COLOR = "#429baa"
    TOWER_COLOR = "#e99032"
    COLORS = {"foot": "#7952ba", "base": "#2476ca", "top": "#2476ca", "free": "#16856b", "control": "#536980"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("manualTowerCanvas")
        self.setMinimumSize(300, 360)
        self.setSizePolicy(self.sizePolicy().Policy.Expanding, self.sizePolicy().Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAccessibleName("Manuelles Turmprofil: Greifer ziehen, Profil doppelklicken, Mausrad zoomt")
        self.draft = self.reference = None
        self.selected = "base"
        self.hovered = None
        self.view = "side"
        self.zoom = 1.0
        self.pan = QPointF()
        self.yaw_deg, self.pitch_deg = -35.0, 25.0
        self.object_rotation = 0
        self.highlight = "both"
        self.editing_enabled = True
        self._drag = None
        self._drag_height_z = None
        self._height_snap_active = False
        self._height_snap_z = None
        self._height_snap_timer = QTimer(self)
        self._height_snap_timer.setSingleShot(True)
        self._height_snap_timer.setInterval(self.HEIGHT_SNAP_GUIDE_DURATION_MS)
        self._height_snap_timer.timeout.connect(self._hide_height_snap_guide)
        self._object_cache = None
        self._interval_helper = None
        self._object_array = np.empty((0, 2, 3))
        self._rings = ()
        self._fit_width, self._fit_height = 100.0, 100.0
        self._static_object_center = 40.0
        self._world_origin = (0.0, 0.0)
        self._spatial_center = (0.0,0.0)
        self._render_manager = None
        self._render_job = None
        self._view_request_id = 0
        self._render_desired = None
        self._render_proxy = False
        self._render_active_key = None
        self._render_failure_key = None
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(100)
        self._render_timer.timeout.connect(self._start_spatial_render)

    def set_render_manager(self,manager):
        self._render_manager = manager
        manager.job_released.connect(self._spatial_released)

    def invalidate_reference(self):
        self._drag_height_z = None
        self._set_height_snap_feedback(None)
        self._render_timer.stop()
        self._render_desired = None
        self._view_request_id += 1
        self._render_proxy = False
        self._render_failure_key = None
        if self._render_job and self._render_manager:
            self._render_manager.cancel_job(self._render_job,reason="manual_view_context_changed")
        self.reference = None
        self._object_cache = None

    def _spatial_frame(self):
        return SpatialFrame(self.width(),self.height(),self.transform()[0],(self.pan.x(),self.pan.y()),
                            self.yaw_deg,self.pitch_deg,self._world_origin,self._spatial_center,self._object_center,
                            self.object_rotation,self.highlight)

    def _spatial_key(self):
        if self.reference is None or self.draft is None or self.view in {"side","front"}:return None
        s = self.draft.settings
        return (self.reference.context.key,self._spatial_frame(),s.target_layer_time_s,s.critical_layers_enabled,
                s.gradient_start_deficit_s,s.gradient_full_deficit_s)

    def _queue_spatial_render(self):
        key = self._spatial_key()
        if key == self._render_failure_key:
            self._render_proxy = False
            return
        if key != self._render_desired:
            self._render_failure_key = None
            self.setToolTip("")
            self._render_desired = key
            if self._render_job:self._render_manager.cancel_job(self._render_job,reason="manual_view_replaced")
            self._render_timer.start()
        self._render_proxy = True

    def _start_spatial_render(self):
        if self._render_job or self._spatial_key() is None or self._render_manager is None:return
        if getattr(self._render_manager.parent(), "_closing", False):return
        self._view_request_id += 1
        key = self._spatial_key()
        self._render_desired = key
        self._render_active_key = key
        worker = ManualViewWorker(self._view_request_id,self.reference,self._spatial_frame(),self.draft.settings,key)
        worker.succeeded.connect(self._spatial_succeeded)
        worker.failed.connect(self._spatial_failed)
        self._render_job = self._render_manager.start_job(kind=JobKind.MANUAL_VIEW,request_id=self._view_request_id,
                                                         worker=worker,parent_operation_id="manual-object-view")

    @Slot(int,object)
    def _spatial_succeeded(self,request_id,result):
        key,img = result
        if request_id == self._view_request_id and key == self._spatial_key():
            self._object_cache = QPixmap.fromImage(img)
            self._render_proxy = False
            self.update()

    @Slot(int,str,str)
    def _spatial_failed(self,request_id,message,details):
        if request_id == self._view_request_id and self._render_active_key == self._spatial_key():
            self._render_proxy = False
            self._render_failure_key = self._render_active_key
            self.setToolTip("Vollständige Objektansicht konnte nicht aufgebaut werden: "+message)

    @Slot(object)
    def _spatial_released(self,job):
        if job.job_id != self._render_job:return
        self._render_job = None
        self._render_active_key = None
        if self._render_proxy and self._spatial_key() is not None and not self._render_timer.isActive():
            self._render_timer.start()

    def sizeHint(self):
        return QSize(760, 650)

    @property
    def editable(self):
        return self.editing_enabled and self.view in {"side", "front"} and self.draft is not None

    def set_reference(self, reference):
        self.invalidate_reference()
        self.reference = reference
        self._object_array = np.array([[(s.start.x, s.start.y, s.start.z), (s.end.x, s.end.y, s.end.z)]
                                       for s in reference.source_data.object_segments], dtype=float)
        bounds = reference.context.occupied_bounds
        self._object_center = ((bounds.minimum_x_mm+bounds.maximum_x_mm)/2,
                               (bounds.minimum_y_mm+bounds.maximum_y_mm)/2)
        if reference.silhouette is not None:
            if self._interval_helper is not None:
                self._interval_helper.deleteLater()
            self._interval_helper = LayerRangeCanvas(reference.context.layers, reference.source_data.object_segments,
                                                      self, silhouette=reference.silhouette)
            self._interval_helper.hide()
        self._object_cache = None

    def set_draft(self, draft):
        old = self.draft
        self.draft = draft
        if self._height_snap_z is not None and not math.isclose(draft.height_mm,self._height_snap_z,rel_tol=0,abs_tol=1e-8):
            self._set_height_snap_feedback(None)
        self._rings = tessellate(draft).points
        if self.reference is not None:
            self._placement = self.reference.context.validate(draft)
        if old is None:
            self.fit_scene()
        color_fields = ("target_layer_time_s","critical_layers_enabled","gradient_start_deficit_s","gradient_full_deficit_s")
        if old is None or any(getattr(old.settings,n) != getattr(draft.settings,n) for n in color_fields):
            self._object_cache = None
        self.update()

    def set_view(self, view):
        self._drag_height_z = None
        self._set_height_snap_feedback(None)
        self.view = view
        if self._render_job and self._render_manager:self._render_manager.cancel_job(self._render_job,reason="manual_view_changed")
        self._render_desired = None
        self._render_timer.stop()
        if view == "three_quarter":
            self.yaw_deg, self.pitch_deg = -35, 25
        elif view == "top":
            self.yaw_deg, self.pitch_deg = 0, 90
        self._object_cache = None
        self.fit_scene()
        self.view_changed.emit(view)

    def set_rotation(self, angle):
        self.object_rotation = angle
        if self._interval_helper is not None:
            self._interval_helper.set_rotation(angle + (90 if self.view == "front" else 0))
        self._object_cache = None
        self.update()

    def set_highlight(self, choice):
        self.highlight = choice
        self._object_cache = None
        self.update()

    def fit_scene(self):
        self.zoom, self.pan = 1.0, QPointF()
        if self.draft is not None and self.reference is not None:
            b = self.reference.context.occupied_bounds
            object_width = max(b.maximum_x_mm-b.minimum_x_mm, b.maximum_y_mm-b.minimum_y_mm)
            radius = self.draft.maximum_radius_mm
            self._static_object_center = 0 if self.view == "front" else radius+object_width/2+15
            self._fit_width = max(20, 2*radius, object_width)+30 if self.view == "front" else max(20, 2*radius+object_width+30)
            self._fit_height = max(self.reference.context.layers[-1].z_mm, self.draft.height_mm)*1.12
            placement = self.reference.context.validate(self.draft)
            self._placement = placement
            self._world_origin = ((b.minimum_x_mm+b.maximum_x_mm+2*placement.center_x_mm)/4,
                                  (b.minimum_y_mm+b.maximum_y_mm+2*placement.center_y_mm)/4)
            if self.view not in {"side", "front"}:
                corners = np.array([(placement.center_x_mm+dx*radius,placement.center_y_mm+dy*radius,z)
                                    for dx in (-1,1) for dy in (-1,1) for z in (0,self.draft.height_mm)])
                native = self.reference.object_triangles
                points = native.reshape(-1,3).copy() if native is not None else self._object_array.reshape(-1,3)
                if native is not None:
                    source_center = self.reference.silhouette.center_xy
                    points[:,:2] += np.asarray(self._object_center)-np.asarray(source_center)
                offset = points[:,:2]-np.asarray(self._object_center)
                angle = math.radians(self.object_rotation)
                points[:,0] = self._object_center[0]+offset[:,0]*math.cos(angle)-offset[:,1]*math.sin(angle)
                points[:,1] = self._object_center[1]+offset[:,0]*math.sin(angle)+offset[:,1]*math.cos(angle)
                raw,_ = self._raw_world(np.concatenate((points,corners)))
                low,high = raw.min(axis=0),raw.max(axis=0)
                self._spatial_center = tuple((low+high)/2)
                self._fit_width,self._fit_height = high-low+20
        self._object_cache = None
        self.update()

    def transform(self):
        scale = min(max(1,self.width()-80)/self._fit_width, max(1,self.height()-90)/self._fit_height)*self.zoom
        origin_x = self.width()/2-self._static_object_center*scale/2+self.pan.x()
        origin_y = self.height()-45+self.pan.y()
        return scale, origin_x, origin_y

    def profile_to_screen(self, radius, z):
        scale, x, y = self.transform()
        return QPointF(x+radius*scale, y-z*scale)

    def screen_to_profile(self, point):
        scale, x, y = self.transform()
        return (point.x()-x)/scale, (y-point.y())/scale

    def _raw_world(self,array):
        points = np.asarray(array, dtype=float).copy()
        points[...,0] -= self._world_origin[0]
        points[...,1] -= self._world_origin[1]
        yaw, pitch = math.radians(self.yaw_deg), math.radians(self.pitch_deg)
        horizontal = points[...,0]*math.cos(yaw)-points[...,1]*math.sin(yaw)
        depth = points[...,0]*math.sin(yaw)+points[...,1]*math.cos(yaw)
        vertical = points[...,2]*math.cos(pitch)-depth*math.sin(pitch)
        return np.stack((horizontal,vertical),axis=-1), depth*math.cos(pitch)+points[...,2]*math.sin(pitch)

    def _project_world(self,array):
        raw,depth = self._raw_world(array)
        scale = min(max(1,self.width()-80)/self._fit_width, max(1,self.height()-90)/self._fit_height)*self.zoom
        return np.stack((self.width()/2+self.pan.x()+(raw[...,0]-self._spatial_center[0])*scale,
                         self.height()/2+self.pan.y()-(raw[...,1]-self._spatial_center[1])*scale),axis=-1),depth

    def handles(self):
        if not self.editable:
            return []
        handles = []
        for p in self.draft.points:
            pos = self.profile_to_screen(p.position.radius_mm, p.position.z_mm)
            # Foot-height and base-width anchors share geometry but get distinct
            # screen offsets and explicit restricted axes.
            if p.kind == "base":
                handles.append(("foot_height", QPointF(pos.x()+22, pos.y()), "foot"))
            handles.append((p.identity, pos, p.kind))
        selected_index = next((i for i,p in enumerate(self.draft.points) if p.identity == self.selected), 1)
        if self.selected.startswith("control:"):
            indices = {int(self.selected.split(":")[1])}
        else:
            indices = {0} if self.selected in {"foot", "foot_height"} else {i for i in (selected_index-1, selected_index) if i > 0 and i < len(self.draft.curves)}
        for i in sorted(indices):
            c = self.draft.curves[i]
            if c.curved:
                for n, pos in ((1,c.control1),(2,c.control2)):
                    handles.append((f"control:{i}:{n}", self.profile_to_screen(pos.radius_mm, pos.z_mm), "control"))
        return handles

    def hit_test(self, point):
        handles = self.handles()
        handles.sort(key=lambda h: h[0] == self.selected, reverse=True)
        found = [(math.hypot(h[1].x()-point.x(),h[1].y()-point.y()), h) for h in handles]
        return min(found, key=lambda item:item[0])[1][0] if found and min(item[0] for item in found) <= 11 else None

    def _object_color(self, layer):
        settings = self.draft.settings
        if settings.critical_layers_enabled:
            return LayerRangeCanvas.layer_color(settings.target_layer_time_s, layer.total_time_s,
                                                 settings.gradient_start_deficit_s, settings.gradient_full_deficit_s)
        return QColor(self.OBJECT_COLOR)

    def _render_object(self):
        pixmap = QPixmap(self.size())
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        opacity = .28 if self.highlight == "tower" else 1
        painter.setOpacity(opacity)
        if self.view in {"side", "front"} and self._interval_helper is not None:
            angle = self.object_rotation+(90 if self.view == "front" else 0)
            self._interval_helper.set_rotation(angle)
            paths = defaultdict(QPainterPath)
            bottom = 0
            scale, _, _ = self.transform()
            for layer, intervals in zip(self.reference.context.layers, self._interval_helper._intervals):
                y = self.profile_to_screen(0, layer.z_mm).y()
                height = max(.75,(layer.z_mm-bottom)*scale+.25)
                color = self._object_color(layer)
                for a,b in intervals:
                    x = self.profile_to_screen(self._static_object_center+a, 0).x()
                    paths[color.rgb()].addRect(QRectF(x,y,max(.7,(b-a)*scale),height))
                bottom = layer.z_mm
            painter.setPen(Qt.PenStyle.NoPen)
            for color, path in paths.items():
                path.setFillRule(Qt.FillRule.WindingFill)
                painter.fillPath(path,QColor.fromRgb(color))
        else:
            native = self.reference.object_triangles
            asynchronous = self._render_manager is not None and self.view not in {"side","front"} and (
                (native is not None and len(native)>4000) or (native is None and len(self._object_array)>4000))
            if asynchronous:self._queue_spatial_render()
            if native is not None and self.view not in {"side","front"} and not asynchronous:
                mesh = native.copy()
                center = np.asarray(self.reference.silhouette.center_xy)
                x,y = mesh[...,0]-center[0],mesh[...,1]-center[1]
                angle = math.radians(self.object_rotation)
                mesh[...,0] = self._object_center[0]+x*math.cos(angle)-y*math.sin(angle)
                mesh[...,1] = self._object_center[1]+x*math.sin(angle)+y*math.cos(angle)
                projected,depth = self._project_world(mesh)
                base_color=QColor(LayerRangeCanvas.OBJECT_COLOR if self.draft.settings.critical_layers_enabled else self.OBJECT_COLOR)
                painter.setPen(QPen(base_color,.5))
                painter.setBrush(base_color)
                for triangle in projected[np.argsort(depth.mean(axis=1))]:
                    painter.drawPolygon(QPolygonF([QPointF(*p) for p in triangle]))
                if not self.draft.settings.critical_layers_enabled:
                    painter.end()
                    self._object_cache = pixmap
                    return
                # Full STL cuts provide actual original-layer annotations on
                # the complete surface, independently of sampled toolpaths.
                groups = defaultdict(list)
                for layer,section in zip(self.reference.context.layers,self.reference.silhouette.segments_xy):
                    color = self._object_color(layer)
                    if color == QColor(LayerRangeCanvas.OBJECT_COLOR): continue
                    if not len(section): continue
                    coordinates = np.empty((*section.shape[:-1],3))
                    sx,sy = section[...,0]-center[0],section[...,1]-center[1]
                    coordinates[...,0] = self._object_center[0]+sx*math.cos(angle)-sy*math.sin(angle)
                    coordinates[...,1] = self._object_center[1]+sx*math.sin(angle)+sy*math.cos(angle)
                    coordinates[...,2] = layer.z_mm
                    screens,_ = self._project_world(coordinates)
                    groups[color.rgb()].extend(QLineF(QPointF(*a),QPointF(*b)) for a,b in screens)
                for color,lines in groups.items():
                    painter.setPen(QPen(QColor.fromRgb(color),1.5))
                    painter.drawLines(lines)
                painter.end()
                self._object_cache = pixmap
                return
            array = self._object_array[::max(1,len(self._object_array)//4000)].copy() if asynchronous else self._object_array.copy()
            x, y = array[...,0]-self._object_center[0], array[...,1]-self._object_center[1]
            angle = math.radians(self.object_rotation)
            array[...,0] = self._object_center[0]+x*math.cos(angle)-y*math.sin(angle)
            array[...,1] = self._object_center[1]+x*math.sin(angle)+y*math.cos(angle)
            if self.view in {"side", "front"}:
                yaw = math.radians(90 if self.view == "front" else 0)
                horizontal = (array[...,0]-self._object_center[0])*math.cos(yaw)-(array[...,1]-self._object_center[1])*math.sin(yaw)
                scale, origin_x, origin_y = self.transform()
                projected = np.stack((origin_x+(horizontal+self._static_object_center)*scale, origin_y-array[...,2]*scale), axis=-1)
            else:
                projected, _ = self._project_world(array)
            tops = [l.z_mm for l in self.reference.context.layers]
            groups = defaultdict(list)
            for segment, screen in zip(array,projected):
                i = min(len(tops)-1,bisect_left(tops,float(segment[:,2].mean())-1e-5))
                groups[self._object_color(self.reference.context.layers[i]).rgb()].append(QLineF(QPointF(*screen[0]),QPointF(*screen[1])))
            for color, lines in groups.items():
                painter.setPen(QPen(QColor.fromRgb(color),1.2))
                painter.drawLines(lines)
        painter.end()
        self._object_cache = pixmap

    def _surface_color(self, z):
        s = self.draft.settings
        if s.overhang_enabled:
            for c in self.draft.curves:
                if c.start.z_mm <= z <= c.end.z_mm:
                    t = c.parameter_at_z(z)
                    slope = c.derivative(t,"radius_mm")/c.derivative(t,"z_mm")
                    if slope > math.tan(math.radians(s.overhang_angle_deg))+1e-9:
                        return QColor("#e5484d")
                    break
        return QColor(self.TOWER_COLOR)

    def _display_rings(self):
        if not self.draft.settings.overhang_enabled:
            return self._rings
        # Exact angle-crossing boundaries avoid losing narrow red bands.
        from cooling_tower.manual.geometry import MeshPoint
        extra = []
        slope = math.tan(math.radians(self.draft.settings.overhang_angle_deg))
        for c in self.draft.curves:
            _,ra,rb,rc = c.coefficients("radius_mm")
            _,za,zb,zc = c.coefficients("z_mm")
            for t in roots(3*(rc-slope*zc),2*(rb-slope*zb),ra-slope*za):
                p = c.at(t)
                extra.append(MeshPoint(p.radius_mm,p.z_mm))
        return tuple(sorted((*self._rings,*extra),key=lambda p:p.z_mm))

    def paintEvent(self,event):
        painter = QPainter(self)
        painter.fillRect(self.rect(),QColor("#e6ecf2"))
        if self.draft is None or self.reference is None:
            painter.setPen(QColor("#526274"))
            painter.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,"Manueller Entwurf wird vorbereitet …")
            painter.end()
            return
        if self._object_cache is None or self._object_cache.size() != self.size():
            self._render_object()
        painter.drawPixmap(0,0,self._object_cache)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(.35 if self.highlight == "object" else 1)
        rings = self._display_rings()
        if self.view in {"side","front"}:
            painter.setPen(Qt.PenStyle.NoPen)
            paths = defaultdict(QPainterPath)
            for a,b in zip(rings,rings[1:]):
                polygon = QPolygonF([self.profile_to_screen(-a.radius_mm,a.z_mm),self.profile_to_screen(a.radius_mm,a.z_mm),
                                     self.profile_to_screen(b.radius_mm,b.z_mm),self.profile_to_screen(-b.radius_mm,b.z_mm)])
                paths[self._surface_color((a.z_mm+b.z_mm)/2).rgb()].addPolygon(polygon)
            for color,path in paths.items():
                path.setFillRule(Qt.FillRule.WindingFill)
                painter.fillPath(path,QColor.fromRgb(color))
            path = QPainterPath()
            path.moveTo(self.profile_to_screen(rings[0].radius_mm,0))
            for p in rings[1:]:
                path.lineTo(self.profile_to_screen(p.radius_mm,p.z_mm))
            painter.setPen(QPen(QColor("#9c5815"),1.5))
            painter.drawPath(path)
            painter.setPen(QPen(QColor("#a3b1c0"),1))
            painter.drawLine(self.profile_to_screen(-self._fit_width,0),self.profile_to_screen(self._fit_width,0))
        else:
            # Filled, depth-sorted surface patches avoid sparse wireframe gaps.
            count = min(self.draft.settings.circle_segments,96)
            surfaces = []
            center = self._placement.center_x_mm,self._placement.center_y_mm
            arrays = [np.array([(center[0]+p.radius_mm*math.cos(math.tau*i/count),
                                center[1]+p.radius_mm*math.sin(math.tau*i/count),p.z_mm) for i in range(count)]) for p in rings]
            projected = [self._project_world(a) for a in arrays]
            for j,(a,b) in enumerate(zip(projected,projected[1:])):
                color = self._surface_color((rings[j].z_mm+rings[j+1].z_mm)/2)
                for i in range(count):
                    k = (i+1)%count
                    surfaces.append(((a[1][i]+a[1][k]+b[1][i]+b[1][k])/4,
                                     QPolygonF([QPointF(*a[0][i]),QPointF(*a[0][k]),QPointF(*b[0][k]),QPointF(*b[0][i])]),color))
            for depth,polygon,color in sorted(surfaces,key=lambda x:x[0]):
                painter.setPen(QPen(color,.5))
                painter.setBrush(color)
                painter.drawPolygon(polygon)
            painter.setBrush(self._surface_color(self.draft.height_mm))
            painter.drawPolygon(QPolygonF([QPointF(*p) for p in projected[-1][0]]))
        painter.setOpacity(1)
        if self._drag_height_z is not None and self.editable:
            y = self.profile_to_screen(0,self._drag_height_z).y()
            painter.setPen(QPen(QColor("#536980"),1.5,Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(12,y),QPointF(self.width()-12,y))
            painter.drawText(QRectF(12,y+4,self.width()-24,20),Qt.AlignmentFlag.AlignLeft,
                             f"Greiferhöhe: {self._drag_height_z:.2f} mm".replace(".",","))
        if self._height_snap_z is not None and self.view in {"side","front"}:
            y = self.profile_to_screen(0,self._height_snap_z).y()
            painter.setPen(QPen(QColor(self.COLORS["top"]),1.5,Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(12,y),QPointF(self.width()-12,y))
            painter.drawText(QRectF(12,y+4,self.width()-24,20),Qt.AlignmentFlag.AlignRight,"Objektoberkante")
        if self.editable:
            handles = self.handles()
            for identity,pos,kind in handles:
                if kind == "control":
                    _,i,n = identity.split(":")
                    curve = self.draft.curves[int(i)]
                    anchor = curve.start if n == "1" else curve.end
                    painter.setPen(QPen(QColor(self.COLORS[kind]),1,Qt.PenStyle.DashLine))
                    painter.drawLine(pos,self.profile_to_screen(anchor.radius_mm,anchor.z_mm))
            for identity,pos,kind in handles:
                active = identity == self.selected or identity == self.hovered
                painter.setPen(QPen(QColor("#ffffff"),3 if active else 1.5))
                painter.setBrush(QColor(self.COLORS[kind]))
                if kind == "control":
                    painter.drawRect(QRectF(pos.x()-5,pos.y()-5,10,10))
                else:
                    painter.drawEllipse(pos,8 if active else 6,8 if active else 6)
        painter.setPen(QColor("#526274"))
        caption = ("Referenz-Seitenansicht · Turm links, Original rechts · gleicher Maßstab" if self.view == "side" else
                   "Referenz-Vorderansicht · Turm und Original hintereinander · gleicher Maßstab" if self.view == "front" else
                   "Räumliche Prüfung · tatsächliche Druckbettanordnung")
        if self._render_proxy and self.view not in {"side","front"}:caption += " · Objektflächen werden aufgebaut …"
        elif self._render_failure_key == self._spatial_key() and self._render_failure_key is not None:
            caption += " · Vollständige Objektansicht nicht verfügbar"
        painter.drawText(QRectF(12,8,self.width()-24,36),Qt.TextFlag.TextWordWrap,caption)
        painter.end()

    def resizeEvent(self,event):
        self._object_cache = None
        super().resizeEvent(event)

    def _hide_height_snap_guide(self):
        self._height_snap_timer.stop()
        self._height_snap_z = None
        self.update()

    def _set_height_snap_feedback(self,height):
        if height is None:
            self._height_snap_active = False
            self._hide_height_snap_guide()
        elif not self._height_snap_active:
            # Flash once on entering the snap region; mouse events within it
            # must not keep restarting the timer.
            self._height_snap_active = True
            self._height_snap_z = height
            self._height_snap_timer.start()
            self.update()

    def _vertical_handle_height(self,identity):
        if identity.startswith("control:"):
            _,index,number = identity.split(":")
            return getattr(self.draft.curves[int(index)],f"control{number}").z_mm
        if identity == "foot_height":
            return self.draft.settings.foot_height_mm
        return next((p.position.z_mm for p in self.draft.points
                     if p.identity == identity and p.kind in {"free","top"}),None)

    def mousePressEvent(self,event):
        self.setFocus()
        self._drag_height_z = None
        self._set_height_snap_feedback(None)
        point = event.position()
        hit = self.hit_test(point) if event.button() == Qt.MouseButton.LeftButton else None
        if hit:
            self.selected = hit
            self.selection_changed.emit(hit)
            self.interaction_started.emit()
            self._drag = ("edit", hit, point)
        elif event.button() in {Qt.MouseButton.MiddleButton,Qt.MouseButton.LeftButton}:
            self._drag = ("pan",point,QPointF(self.pan))
        elif event.button() == Qt.MouseButton.RightButton and self.view not in {"side","front"}:
            self._drag = ("rotate",point,(self.yaw_deg,self.pitch_deg))
            self.view = "free"
            self.view_changed.emit("free")
        self.update()
        event.accept()

    def mouseMoveEvent(self,event):
        point = event.position()
        if self._drag is None:
            self.hovered = self.hit_test(point)
            self.setCursor(Qt.CursorShape.PointingHandCursor if self.hovered else Qt.CursorShape.ArrowCursor)
            if self.hovered:
                self.setToolTip("Fußhöhe: nur vertikal" if self.hovered == "foot_height" else
                                "Kontrollpunkt: Kurve formen" if self.hovered.startswith("control:") else
                                "Fuß / Grunddurchmesser: horizontal · Höhe: vertikal · freie Punkte: beide Richtungen")
            else:
                self.setToolTip("Doppelklick am Körperprofil: Punkt hinzufügen · Mausrad: Zoom · Mitteltaste: Pan")
            self.update()
            return
        action,a,b = self._drag
        if action == "pan":
            self.pan = b+point-a
            self._object_cache = None
        elif action == "rotate":
            self.yaw_deg = b[0]+(point.x()-a.x())*.5
            self.pitch_deg = max(-85,min(85,b[1]+(point.y()-a.y())*.5))
            self._object_cache = None
        elif self.editable:
            radius,z = self.screen_to_profile(point)
            snap_height = None
            if a == "top" and self.reference is not None:
                object_top = self.reference.context.layers[-1].z_mm
                if (object_top <= self.draft.maximum_height_mm and
                        abs(z-object_top)*self.transform()[0] <= self.HEIGHT_SNAP_DISTANCE_PX):
                    z = object_top
                    snap_height = object_top
            if a.startswith("control:"):
                _,i,n = a.split(":")
                self.control_requested.emit(int(i),int(n),radius*2,z)
            else:
                self.move_requested.emit(a,radius*2,z)
            if a == "top":
                self._set_height_snap_feedback(snap_height if snap_height is not None and
                                               math.isclose(self.draft.height_mm,snap_height,rel_tol=0,abs_tol=1e-8) else None)
            height = self._vertical_handle_height(a)
            if height is None:
                self._drag_height_z = None
            elif self._drag_height_z is not None or abs(point.y()-b.y())>1e-6:
                # Use the accepted model height, including geometry limits and
                # snapping, rather than the potentially rejected mouse height.
                self._drag_height_z = height
        self.update()
        event.accept()

    def mouseReleaseEvent(self,event):
        if self._drag is not None:
            editing = self._drag[0] == "edit"
            self.mouseMoveEvent(event)
            self._drag = None
            self._drag_height_z = None
            self.update()
            if editing:
                self.interaction_finished.emit()
        event.accept()

    def mouseDoubleClickEvent(self,event):
        if self.editable and event.button() == Qt.MouseButton.LeftButton:
            radius,z = self.screen_to_profile(event.position())
            if self.draft.points[1].position.z_mm < z < self.draft.height_mm:
                actual = self.draft.radius_at_z(z)
                if abs(abs(radius)-actual)*self.transform()[0] <= 16:
                    self._drag = None
                    self._drag_height_z = None
                    self.insert_requested.emit(z)
        event.accept()

    def wheelEvent(self,event):
        if self._drag is not None:
            event.accept()
            return
        old = self.zoom
        def origin():
            if self.view in {"side","front"}:
                _,x,y = self.transform()
                return QPointF(x,y)
            scale = self.transform()[0]
            return QPointF(self.width()/2+self.pan.x()-self._spatial_center[0]*scale,
                           self.height()/2+self.pan.y()+self._spatial_center[1]*scale)
        old_origin = origin()
        self.zoom = max(.25,min(80,self.zoom*1.12**(event.angleDelta().y()/120)))
        ratio = self.zoom/old
        self.pan += event.position()-(origin()+(event.position()-old_origin)*ratio)
        self._object_cache = None
        self.update()
        event.accept()

    def keyPressEvent(self,event):
        if self.editable and event.key() in {Qt.Key.Key_Delete,Qt.Key.Key_Backspace}:
            self.remove_requested.emit(self.selected)
            event.accept()
        elif event.key() == Qt.Key.Key_F:
            self.fit_scene()
            event.accept()
        else:
            super().keyPressEvent(event)
