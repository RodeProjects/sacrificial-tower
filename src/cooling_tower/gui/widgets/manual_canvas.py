"""Software-rendered manual editor with one reversible physical transform."""
from __future__ import annotations

import math
from dataclasses import replace
from collections import defaultdict,OrderedDict
from bisect import bisect_left

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QLineF, QSize, Qt, Signal,QTimer,Slot,QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPicture, QPolygonF,QImage,QBrush,QLinearGradient,QIcon,QPixmap
from PySide6.QtWidgets import QWidget, QPushButton, QHBoxLayout

from cooling_tower.gui.widgets.layer_range_canvas import LayerRangeCanvas
from cooling_tower.gui.widgets.manual_view_controls import ManualViewControls
from cooling_tower.manual.geometry import tessellate, roots
from cooling_tower.tower.mesh_generator import MINIMUM_AUTOMATIC_CIRCLE_SEGMENTS
from cooling_tower.manual.layer_snap import snap_layer_height
from cooling_tower.gui.background_jobs import JobKind
from cooling_tower.gui.design_tokens import BOUNDARY_FEEDBACK_HOLD_MS,BOUNDARY_FEEDBACK_FADE_MS,ORIGINAL_OBJECT_BLUE
from cooling_tower.gui.manual_view_worker import (SpatialFrame,ManualViewWorker,render_spatial_object,rotate_object,
                                                cosmetic_pen,surface_brightness,draw_surface,render_silhouette_backing)
from cooling_tower.gui.object_material import draw_object_picture,object_picture_cache_size


def history_arrow_icon(redo=False):
    """Draw a familiar curved arrow without depending on a symbol font."""
    pixmap = QPixmap(20, 20)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if redo:
        painter.translate(20, 0)
        painter.scale(-1, 1)
    color = QColor("#284f70")
    painter.setPen(QPen(color, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    path = QPainterPath(QPointF(16, 16))
    path.lineTo(16, 12)
    path.quadTo(16, 7, 11, 7)
    path.lineTo(5, 7)
    painter.drawPath(path)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawPolygon(QPolygonF([QPointF(3, 7), QPointF(8, 2), QPointF(8, 12)]))
    painter.end()
    return QIcon(pixmap)


class ManualCanvas(QWidget):
    HEIGHT_HANDLE_OFFSET_PX = 33
    HEIGHT_HANDLES = {"top", "foot_height"}
    INSERTION_HOVER_DISTANCE_PX = HEIGHT_HANDLE_OFFSET_PX
    HEIGHT_SNAP_DISTANCE_PX = 14.0
    HEIGHT_SNAP_GUIDE_DURATION_MS = 850
    WIDTH_LIMIT_GUIDE_HOLD_MS = BOUNDARY_FEEDBACK_HOLD_MS
    WIDTH_LIMIT_GUIDE_FADE_MS = BOUNDARY_FEEDBACK_FADE_MS
    WIDTH_LIMIT_GUIDE_DURATION_MS = WIDTH_LIMIT_GUIDE_HOLD_MS+WIDTH_LIMIT_GUIDE_FADE_MS
    selection_changed = Signal(str)
    move_requested = Signal(str, float, float)
    control_requested = Signal(int, int, float, float)
    insert_requested = Signal(float)
    remove_requested = Signal(str)
    curve_reset_requested = Signal(str)
    view_state_changed = Signal()
    interaction_started = Signal()
    interaction_finished = Signal()
    view_changed = Signal(str)
    OBJECT_COLOR = ORIGINAL_OBJECT_BLUE
    TOWER_COLOR = "#e99032"
    PROFILE_COLOR = "#ba299d"
    COLORS = {"top_width": "#d43b48", "foot": "#7952ba", "base": "#2476ca", "top": "#2476ca", "free": "#16856b", "control": "#536980",
              "foot_limit":"#7952ba", "body_limit":"#2476ca", "body_min":"#2476ca"}
    LIMITS = {"maximum_diameter_mm":"body_limit", "maximum_foot_diameter_mm":"foot_limit",
              "minimum_diameter_mm":"body_min"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("manualTowerCanvas")
        self.setMinimumSize(300, 360)
        self.setSizePolicy(self.sizePolicy().Policy.Expanding, self.sizePolicy().Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAccessibleName("Manuelles Turmprofil: Greifer ziehen, Profil doppelklicken, Mausrad zoomt")
        self.history_controls = QWidget(self)
        history_layout = QHBoxLayout(self.history_controls)
        history_layout.setContentsMargins(0, 0, 0, 0)
        history_layout.setSpacing(4)
        self.undo_button = QPushButton()
        self.redo_button = QPushButton()
        self.undo_button.setIcon(history_arrow_icon())
        self.redo_button.setIcon(history_arrow_icon(redo=True))
        for button, label in ((self.undo_button, "Letzte Aktion rückgängig machen (Strg+Z)"),
                              (self.redo_button, "Aktion wiederholen (Strg+Y)")):
            button.setFixedSize(28, 26)
            button.setIconSize(QSize(18, 18))
            button.setStyleSheet("QPushButton { padding: 0px; min-height: 0px; min-width: 0px; }")
            button.setToolTip(label)
            button.setAccessibleName(label)
            button.setEnabled(False)
            history_layout.addWidget(button)
        self.history_controls.setGeometry(8, 8, 60, 26)
        self.draft = self.reference = None
        self.selected = ""
        self.point_editor = None
        self._empty_click_position = None
        self._insertion_preview = None
        self.validate_insertion = None
        self._revealed_control_anchor = None
        self._layer_tops = ()
        self.hovered = None
        self.view = "side"
        self.zoom = 1.0
        self.pan = QPointF()
        self.yaw_deg, self.pitch_deg = -35.0, 25.0
        self.object_rotation = 0
        self.highlight = "both"
        self.editing_enabled = True
        self._drag = None
        self._drag_moved = False
        self._drag_radius = None
        self._drag_origin_draft = None
        self._drag_origin_height = None
        self._drag_axis = None
        self._drag_width_active = False
        self._drag_height_z = None
        self._height_snap_active = False
        self._height_snap_z = None
        self._height_snap_timer = QTimer(self)
        self._height_snap_timer.setSingleShot(True)
        self._height_snap_timer.setInterval(self.HEIGHT_SNAP_GUIDE_DURATION_MS)
        self._height_snap_timer.timeout.connect(self._hide_height_snap_guide)
        self._width_limit_setting = None
        self._width_limit_settings = ()
        self._control_height_limits = ()
        self._width_limit_last_request = None
        self._width_limit_opacity = 0.
        self._width_limit_animation = QVariantAnimation(self)
        self._width_limit_animation.setDuration(self.WIDTH_LIMIT_GUIDE_DURATION_MS)
        self._width_limit_animation.setStartValue(1.)
        self._width_limit_animation.setKeyValueAt(self.WIDTH_LIMIT_GUIDE_HOLD_MS/self.WIDTH_LIMIT_GUIDE_DURATION_MS,1.)
        self._width_limit_animation.setEndValue(0.)
        self._width_limit_animation.valueChanged.connect(self._set_width_limit_opacity)
        self._width_limit_animation.finished.connect(self._hide_width_limit_guide)
        self._object_cache = None
        self._object_image_cache = None
        self._object_image_key = None
        self._object_image_picture = None
        self._object_render_key = None
        self._object_pictures=OrderedDict()
        self._object_array = np.empty((0, 2, 3))
        self._rings = ()
        self._tower_cache = None
        self._tower_render_key = None
        self._fit_width, self._fit_height = 100.0, 100.0
        self._static_object_offset = 40.0
        self._profile_fit_center = 20.0
        self._profile_object_gap_px = 0.0
        self._profile_right_mm = 50.0
        self._profile_height_grip_radius = 0.0
        self._world_origin = (0.0, 0.0)
        self._spatial_center = (0.0,0.0)
        self._fitted_framing = None
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
        self.view_controls = ManualViewControls(self)

    def set_render_manager(self,manager):
        self._render_manager = manager
        manager.job_released.connect(self._spatial_released)

    def invalidate_reference(self):
        self._fitted_framing = None
        self._layer_tops = ()
        self._drag_height_z = None
        self._set_height_snap_feedback(None)
        self._hide_width_limit_guide()
        self._render_timer.stop()
        self._render_desired = None
        self._view_request_id += 1
        self._render_proxy = False
        self._render_failure_key = None
        if self._render_job and self._render_manager:
            self._render_manager.cancel_job(self._render_job,reason="manual_view_context_changed")
        self.reference = None
        self._object_cache = None
        self._object_image_cache = self._object_image_key = self._object_image_picture = None
        self._object_pictures.clear()

    def _spatial_frame(self):
        if self.view in {"side","front"}:
            scale,x,y = self.transform()
            return SpatialFrame(self.width(),self.height(),scale,
                                (x+self._static_object_center*scale-self.width()/2,y-self.height()/2),
                                90 if self.view == "front" else 0,0,self._object_center,(0,0),self._object_center,
                                self.object_rotation,self.highlight,True)
        center=self.plot_rect().center()
        return SpatialFrame(self.width(),self.height(),self.transform()[0],
                            (self.pan.x()+center.x()-self.width()/2,self.pan.y()+center.y()-self.height()/2),
                            self.yaw_deg,self.pitch_deg,self._world_origin,self._spatial_center,self._object_center,
                            self.object_rotation,self.highlight,True)

    def _spatial_render_frame(self):
        # Build projected surfaces once. Viewport translation/scale are applied
        # when replaying the picture; pan, zoom and resize need no worker.
        return replace(self._spatial_frame(),width=0,height=0,scale=1,pan=(0,0),
                       projected_center=(0,0),highlight="both")

    def _spatial_key(self):
        if self.reference is None or self.draft is None:return None
        s = self.draft.settings
        return (self.reference.context.key,self._spatial_render_frame(),s.color_reference_time_s,s.critical_layers_enabled,
                s.color_red_time_s,s.object_resolution_percent)

    @staticmethod
    def _object_geometry_key(key):
        return key[:2]+key[5:]

    def _queue_spatial_render(self):
        key = self._spatial_key()
        if key == self._render_failure_key:
            self._render_proxy = False
            return
        if key != self._render_desired:
            self._render_failure_key = None
            self.setAccessibleDescription("")
            self._render_desired = key
            if (self._render_job and self._render_active_key is not None and
                    self._object_geometry_key(key)!=self._object_geometry_key(self._render_active_key)):
                self._render_manager.cancel_job(self._render_job,reason="manual_view_replaced")
            self._render_timer.start()
        if self._render_job is None and not self._render_timer.isActive():
            self._render_timer.start()
        self._render_proxy = True

    def _start_spatial_render(self):
        if self._render_job or self._spatial_key() is None or self._render_manager is None:return
        if getattr(self._render_manager.parent(), "_closing", False):return
        self._view_request_id += 1
        key = self._spatial_key()
        self._render_desired = key
        self._render_active_key = key
        worker = ManualViewWorker(self._view_request_id,self.reference,self._spatial_render_frame(),self.draft.settings,key)
        worker.succeeded.connect(self._spatial_succeeded)
        worker.failed.connect(self._spatial_failed)
        self._render_job = self._render_manager.start_job(kind=JobKind.MANUAL_VIEW,request_id=self._view_request_id,
                                                         worker=worker,parent_operation_id="manual-object-view")

    @Slot(int,object)
    def _spatial_succeeded(self,request_id,result):
        key,img = result
        current=self._spatial_key()
        if (request_id==self._view_request_id and current is not None and
                self._object_geometry_key(key)==self._object_geometry_key(current)):
            if key!=current:
                material=getattr(img,"material",None)
                if material is None:return
                img=material.recolor(self.draft.settings,serialize=False)
                key=current
            self._render_timer.stop()
            self._object_cache = img
            self._object_render_key = key
            self._remember_object_picture(key,img)
            self._render_proxy = False
            self.update()

    @Slot(int,str,str)
    def _spatial_failed(self,request_id,message,details):
        current=self._spatial_key()
        if (request_id==self._view_request_id and current is not None and self._render_active_key is not None
                and self._object_geometry_key(self._render_active_key)==self._object_geometry_key(current)):
            self._render_proxy = False
            self._render_failure_key = current
            self.setAccessibleDescription("Vollständige Objektansicht konnte nicht aufgebaut werden: "+message)

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
        return self.editing_enabled and self.view in {"side", "front", "top", "bottom"} and self.draft is not None

    def set_reference(self, reference):
        self.invalidate_reference()
        self.reference = reference
        self._layer_tops = tuple(layer.z_mm for layer in reference.context.layers)
        self._object_array = np.array([[(s.start.x, s.start.y, s.start.z), (s.end.x, s.end.y, s.end.z)]
                                       for s in reference.source_data.object_segments], dtype=float).reshape(-1,2,3)
        bounds = reference.context.occupied_bounds
        self._object_center = ((bounds.minimum_x_mm+bounds.maximum_x_mm)/2,
                               (bounds.minimum_y_mm+bounds.maximum_y_mm)/2)
        native = reference.object_triangles
        points = native.reshape(-1,3) if native is not None else self._object_array.reshape(-1,3)
        if len(points):
            low,high = points[:,:2].min(axis=0),points[:,:2].max(axis=0)
            self._object_xy_corners = np.array([(x,y,0) for x in (low[0],high[0]) for y in (low[1],high[1])])
        else:
            self._object_xy_corners = np.array([(bounds.minimum_x_mm,bounds.minimum_y_mm,0),
                                                (bounds.maximum_x_mm,bounds.maximum_y_mm,0)])
        self._object_cache = None

    def set_draft(self, draft):
        old = self.draft
        colors_only=(old is not None and replace(old,settings=draft.settings)==draft and
            replace(old.settings,color_reference_time_s=draft.settings.color_reference_time_s,
                    color_deficit_time_s=draft.settings.color_deficit_time_s,
                    color_scale_max_time_s=draft.settings.color_scale_max_time_s,
                    critical_layers_enabled=draft.settings.critical_layers_enabled)==draft.settings)
        self.draft = draft
        self._insertion_preview = None
        if (old is not None and any(getattr(old.settings,name)!=getattr(draft.settings,name)
                                    for name in self._width_limit_settings)):
            self._hide_width_limit_guide()
        if self._height_snap_z is not None and not math.isclose(draft.height_mm,self._height_snap_z,rel_tol=0,abs_tol=1e-8):
            self._set_height_snap_feedback(None)
        if not colors_only:
            self._rings = tessellate(draft).points
            if self.reference is not None:
                self._placement = self.reference.context.validate(draft)
        if old is None or self._fitted_framing is None:
            self.fit_scene()
        color_fields = ("color_reference_time_s","critical_layers_enabled","color_red_time_s")
        if old is None or any(getattr(old.settings,n) != getattr(draft.settings,n) for n in color_fields):
            self._object_cache = None
        self._update_fit_button()
        self.update()

    def set_view(self, view):
        self._insertion_preview = None
        self._drag_height_z = None
        self._set_height_snap_feedback(None)
        self._hide_width_limit_guide()
        self._width_limit_last_request = None
        view = "free" if view == "three_quarter" else view
        previous_key = self._spatial_key()
        self.view = view
        self.view_controls.view_buttons[view].setChecked(True)
        if view == "free":
            self.yaw_deg, self.pitch_deg = -35, 25
        elif view in {"top","bottom"}:
            self.yaw_deg, self.pitch_deg = 0, 90 if view == "top" else -90
        if previous_key != self._spatial_key():
            if self._render_job and self._render_manager:self._render_manager.cancel_job(self._render_job,reason="manual_view_changed")
            self._render_desired = None
            self._render_timer.stop()
        self.fit_scene()
        self.view_changed.emit(view)

    def set_rotation(self, angle):
        if angle == self.object_rotation:
            self.view_state_changed.emit()
            return
        self.object_rotation = angle
        self._object_cache = None
        self._update_fit_button()
        self.view_state_changed.emit()
        self.update()

    def set_highlight(self, choice):
        self.highlight = choice
        self.view_state_changed.emit()
        self.update()

    def _fitting_radius(self):
        radius = self.draft.maximum_radius_mm
        if self.view in {"side","front","top","bottom"}:
            limits = (["maximum_diameter_mm"] if self.view == "top" else
                      ["maximum_foot_diameter_mm"] if self.view == "bottom" else self.LIMITS)
            radius = max(radius,*(getattr(self.draft.settings,name)/2 for name in limits))
        return radius

    def _framing_state(self):
        if self.draft is None or self.reference is None:
            return None
        camera = () if self.view in {"side","front"} else (self.yaw_deg,self.pitch_deg)
        return (id(self.reference),self.view,round(self.zoom,9),round(self.pan.x(),9),round(self.pan.y(),9),
                self.object_rotation%360,camera,self._fitting_radius(),self.draft.maximum_radius_mm,
                max(self.draft.points[1].position.radius_mm,self.draft.points[-1].position.radius_mm),
                max(self.reference.context.layers[-1].z_mm,self.draft.height_mm))

    def _update_fit_button(self):
        framing = self._framing_state()
        self.view_controls.set_fitted(framing is None or framing == self._fitted_framing)

    def fit_scene(self):
        self._insertion_preview=None
        self.zoom, self.pan = 1.0, QPointF()
        if self.draft is not None and self.reference is not None:
            b = self.reference.context.occupied_bounds
            native = self.reference.object_triangles
            source_points = native.reshape(-1,3) if native is not None else self._object_array.reshape(-1,3)
            source_center = self.reference.silhouette.center_xy if native is not None else self._object_center
            points = rotate_object(source_points,source_center,self._object_center,self.object_rotation)
            self._fit_height = max(self.reference.context.layers[-1].z_mm,self.draft.height_mm,
                                   float(points[:,2].max()) if len(points) else 0)
            radius = self._fitting_radius()
            self._profile_object_gap_px = 0.0
            if self.view in {"side","front"}:
                projected,_ = self._spatial_render_frame().project(points if len(points) else self._object_xy_corners)
                object_left,object_right = float(projected[:,0].min()),float(projected[:,0].max())
                # Limit grips occupy only the editable right side. Reserve the
                # actual tower radius on the left and a pixel gap for its grips.
                if self.view == "side":
                    self._profile_object_gap_px = 15.0
                    self._static_object_offset = radius-object_left
                    low,high = -self.draft.maximum_radius_mm,radius+object_right-object_left
                else:
                    self._static_object_offset = 0.0
                    low,high = min(-self.draft.maximum_radius_mm,object_left),max(radius,object_right)
                self._profile_fit_center = (low+high)/2
                self._fit_width = max(high-low,1e-6)
                self._profile_right_mm = radius if self.view == "side" else high
                self._profile_height_grip_radius = max(self.draft.points[1].position.radius_mm,
                                                       self.draft.points[-1].position.radius_mm)
            placement = self.reference.context.validate(self.draft)
            self._placement = placement
            self._world_origin = ((b.minimum_x_mm+b.maximum_x_mm+2*placement.center_x_mm)/4,
                                  (b.minimum_y_mm+b.maximum_y_mm+2*placement.center_y_mm)/4)
            if self.view not in {"side", "front"}:
                # Fit the actual polygon rings, rather than an oversized box
                # around the whole tower. Four projected ring extrema suffice.
                count=self.draft.settings.circle_segments or MINIMUM_AUTOMATIC_CIRCLE_SEGMENTS
                angles=np.arange(count)*math.tau/count
                circle=np.column_stack((np.cos(angles),np.sin(angles),np.zeros(count)))
                circle_raw,_=self._raw_world(circle)
                indices={int(operation(circle_raw[:,axis])) for operation in (np.argmin,np.argmax) for axis in (0,1)}
                directions=circle[sorted(indices),:2]
                tower_points=np.array([(placement.center_x_mm+dx*p.radius_mm,placement.center_y_mm+dy*p.radius_mm,p.z_mm)
                                       for p in self._rings for dx,dy in directions])
                if self.view in {"top","bottom"}:
                    point=self.draft.points[-1 if self.view == "top" else 0].position
                    name="maximum_diameter_mm" if self.view == "top" else "maximum_foot_diameter_mm"
                    tower_points=np.concatenate((tower_points,[(placement.center_x_mm+getattr(self.draft.settings,name)/2,
                                                                 placement.center_y_mm,point.z_mm)]))
                raw,_ = self._raw_world(np.concatenate((points,tower_points)))
                low,high = raw.min(axis=0),raw.max(axis=0)
                self._spatial_center = tuple((low+high)/2)
                self._fit_width,self._fit_height = np.maximum(high-low,1e-6)
        self._fitted_framing = self._framing_state()
        self._update_fit_button()
        self.view_state_changed.emit()
        self.update()

    def plot_rect(self):
        top=max(50,self.view_controls.geometry().bottom()+20)
        bottom=max(52,34+self.fontMetrics().height()) if self.view in {"side","front"} else 24
        return QRectF(60,top,max(1,self.width()-120),max(1,self.height()-top-bottom))

    def transform(self):
        rectangle=self.plot_rect()
        fitted_scale=self._fit_scale(rectangle)
        scale = fitted_scale*self.zoom
        origin_x = rectangle.center().x()-self._profile_fit_center*scale-self._profile_gap_for_scale(fitted_scale)*self.zoom/2+self.pan.x()
        origin_y = rectangle.bottom()+self.pan.y()
        return scale, origin_x, origin_y

    def _fit_scale(self,rectangle=None):
        if rectangle is None:rectangle=self.plot_rect()
        scale=min(max(1,rectangle.width()-self._profile_object_gap_px)/self._fit_width,
                  rectangle.height()/self._fit_height)
        if self.view in {"side","front"}:
            # Height grips may already fit inside the width-limit envelope.
            # Only their protruding pixels need additional horizontal space.
            width=self._fit_width+self._profile_height_grip_radius-self._profile_right_mm
            scale=min(scale,max(1,rectangle.width()-self._profile_object_gap_px-self.HEIGHT_HANDLE_OFFSET_PX)/max(width,1e-6))
        return scale

    @property
    def _profile_gap_px(self):
        return self._profile_gap_for_scale(self._fit_scale())

    def _profile_gap_for_scale(self,scale):
        if self.view not in {"side","front"}:return 0.0
        return self._profile_object_gap_px+max(0,self.HEIGHT_HANDLE_OFFSET_PX+
            (self._profile_height_grip_radius-self._profile_right_mm)*scale)

    @property
    def _static_object_center(self):
        if self.view!="side":return 0.0
        scale=self._fit_scale()
        return self._static_object_offset+self._profile_gap_for_scale(scale)/scale

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
        scale = self.transform()[0]
        center=self.plot_rect().center()
        return np.stack((center.x()+self.pan.x()+(raw[...,0]-self._spatial_center[0])*scale,
                         center.y()+self.pan.y()-(raw[...,1]-self._spatial_center[1])*scale),axis=-1),depth

    def handles(self):
        if not self.editable:
            return []
        if self.view in {"top","bottom"}:
            point = self.draft.points[-1 if self.view == "top" else 0].position
            identity,kind = ("top_width","top_width") if self.view == "top" else ("foot","foot")
            center = self._placement.center_x_mm,self._placement.center_y_mm
            screen,_ = self._project_world(np.array([(center[0]+point.radius_mm,center[1],point.z_mm)]))
            return [(identity,QPointF(*screen[0]),kind),*self.limit_handles()]
        handles = []
        for p in self.draft.points:
            pos = self.profile_to_screen(p.position.radius_mm, p.position.z_mm)
            # Foot-height and base-width anchors share geometry but get distinct
            # screen offsets and explicit restricted axes.
            if p.kind == "base":
                handles.append(("foot_height", QPointF(pos.x()+self.HEIGHT_HANDLE_OFFSET_PX, pos.y()), "foot"))
            if p.kind == "top":
                handles.append(("top_width",pos,"top_width"))
                handles.append((p.identity,QPointF(pos.x()+self.HEIGHT_HANDLE_OFFSET_PX,pos.y()),p.kind))
            else:
                handles.append((p.identity, pos, p.kind))
        selected_identity={"foot_height":"base","top_width":"top"}.get(self.selected,self.selected)
        selected_index = next((i for i,p in enumerate(self.draft.points) if p.identity == selected_identity), None)
        if self.selected.startswith("control:"):
            _,index,number = self.selected.split(":")
            selected_index = int(index)+(number == "2")
            controls = ((selected_index-1,2),(selected_index,1))
        elif self.selected in {"top","top_width"}:
            controls = ((len(self.draft.curves)-1,2),)
        elif self.selected in {"foot","foot_height"}:
            controls = ((0,1 if self.selected == "foot" else 2),)
        elif not self.selected or self.selected in self.LIMITS:
            controls = ()
        elif selected_index is None:
            controls = ()
        else:
            controls = ((selected_index-1,2),(selected_index,1))
        neighbor_controls = ()
        selected_point = self.draft.points[selected_index] if selected_index is not None else None
        if selected_point is not None:
            # Every selected endpoint, including fixed points and the owner
            # of a selected control, keeps its neighbors' facing controls.
            neighbor_controls = ((selected_index-1,1),(selected_index,2))
        controls += neighbor_controls
        reveal_linear = selected_point is not None and (selected_point.kind == "free" or selected_point.identity == self._revealed_control_anchor)
        for i,n in controls:
            if 0 <= i < len(self.draft.curves) and (self.draft.curves[i].curved or reveal_linear or (i,n) in neighbor_controls or
                    self.selected == f"control:{i}:{n}" or
                    (i == len(self.draft.curves)-1 and n == 2 and self.selected in {"top_width",f"control:{i}:2"})):
                pos = getattr(self.draft.curves[i],f"control{n}")
                handles.append((f"control:{i}:{n}", self.profile_to_screen(pos.radius_mm,pos.z_mm), "control"))
        return [*handles,*self.limit_handles()]

    def limit_geometry(self,identity):
        """Return the profile edge and limit in the same millimetre frame."""
        if identity == "minimum_diameter_mm":
            _,start,_,end=self.minimum_measure_geometry()
            return start,end
        if self.view in {"top","bottom"}:
            point = self.draft.points[-1 if self.view == "top" else 0].position
            z,radius = point.z_mm,point.radius_mm
        else:
            z = (self.draft.settings.foot_height_mm/2 if identity == "maximum_foot_diameter_mm"
                 else (self.draft.settings.foot_height_mm+self.draft.height_mm)/2)
            curve = next(c for c in self.draft.curves if c.start.z_mm <= z <= c.end.z_mm)
            radius = curve.at(curve.parameter_at_z(z)).radius_mm
        limit = getattr(self.draft.settings,identity)/2
        if self.view in {"top","bottom"}:
            center = self._placement.center_x_mm,self._placement.center_y_mm
            screen,_ = self._project_world(np.array([(center[0]+r,center[1],z) for r in (radius,limit)]))
            return QPointF(*screen[0]),QPointF(*screen[1])
        return self.profile_to_screen(radius,z),self.profile_to_screen(limit,z)

    def height_handle_geometry(self,identity):
        point = self.draft.points[-1 if identity == "top" else 1].position
        start = self.profile_to_screen(point.radius_mm,point.z_mm)
        return start,start+QPointF(self.HEIGHT_HANDLE_OFFSET_PX,0)

    def information_identity(self):
        """Control handles edit a curve while its endpoint owns the info box."""
        if self.selected.startswith("control:") and self.draft is not None:
            _,index,number = self.selected.split(":")
            point = self.draft.points[int(index)+(number == "2")]
            return "top_width" if point.kind == "top" else point.identity
        return self.selected

    def minimum_measure_geometry(self):
        radius=self.draft.settings.minimum_diameter_mm/2
        left=self.profile_to_screen(-radius,0)
        right=self.profile_to_screen(radius,0)
        return left,right,left+QPointF(0,26),right+QPointF(0,26)

    def width_limit_guide_geometry(self,left=False,setting=None):
        radius=getattr(self.draft.settings,setting or self._width_limit_setting)/2
        if left:radius=-radius
        start=self.profile_to_screen(radius,0)
        return start,QPointF(start.x(),self._scale_line_top())

    def _minimum_measure_pen(self):
        left,_,end,_=self.minimum_measure_geometry()
        return self._limit_guide_pen(left,end)

    @staticmethod
    def _limit_guide_pen(start,end):
        gradient=QLinearGradient(start,end)
        gradient.setColorAt(0,QColor("#a3b1c0").darker(150))
        gradient.setColorAt(1,QColor("#bec5ce"))
        return QPen(QBrush(gradient),1,Qt.PenStyle.DashLine)

    def minimum_measure_label_rect(self):
        _,_,left,right=self.minimum_measure_geometry()
        metrics=self.fontMetrics()
        width=max(right.x()-left.x(),metrics.horizontalAdvance("Min. Turm-Ø")+8)
        return QRectF((left.x()+right.x()-width)/2,left.y()+5,width,max(18,metrics.height()))

    def limit_handles(self):
        names = (["maximum_diameter_mm"] if self.view == "top" else
                 ["maximum_foot_diameter_mm"] if self.view == "bottom" else self.LIMITS)
        return [(name,self.limit_geometry(name)[1],self.LIMITS[name]) for name in names]

    def hit_test(self, point):
        handles = self.handles()
        handles.sort(key=lambda h: h[0] == self.selected, reverse=True)
        found = [(math.hypot(h[1].x()-point.x(),h[1].y()-point.y()), h) for h in handles]
        return min(found, key=lambda item:item[0])[1][0] if found and min(item[0] for item in found) <= 11 else None

    def _object_color(self, layer):
        settings = self.draft.settings
        if settings.critical_layers_enabled:
            return LayerRangeCanvas.layer_time_color(settings.color_reference_time_s,settings.color_red_time_s,layer.total_time_s)
        return QColor(self.OBJECT_COLOR)

    def _render_object(self):
        native = self.reference.object_triangles
        silhouette = self.draft.settings.object_resolution_percent == 0
        mesh=getattr(self.reference,"object_silhouette",None)
        fast_contour=mesh is not None and mesh.source is native and mesh.topology.reliable_contours
        key=self._spatial_key()
        cached=self._object_pictures.get(key)
        if cached is None:
            geometry_key=self._object_geometry_key(key)
            material=next((getattr(picture,"material",None)
                for old_key,picture in reversed(self._object_pictures.items())
                if self._object_geometry_key(old_key)==geometry_key and getattr(picture,"material",None) is not None),None)
            if material is not None:
                cached=material.recolor(self.draft.settings,serialize=False)
                self._remember_object_picture(key,cached)
        if cached is not None:
            self._object_pictures.move_to_end(key)
            self._render_timer.stop()
            if self._render_job and self._render_manager is not None:
                self._view_request_id+=1
                self._render_manager.cancel_job(self._render_job,reason="manual_view_cached")
            self._object_cache=cached
            self._object_render_key=key
            self._render_proxy=False
            self._render_desired=self._render_failure_key=None
            self.setAccessibleDescription("")
            return
        asynchronous = self._render_manager is not None and (
            (native is not None and len(native)>4000 and (not silhouette or not fast_contour or self.draft.settings.critical_layers_enabled))
            or (native is None and len(self._object_array)>4000))
        if not asynchronous:
            self._render_timer.stop()
            self._render_desired = self._render_failure_key = None
            self.setAccessibleDescription("")
            if self._render_job and self._render_manager is not None:
                self._view_request_id += 1
                self._render_manager.cancel_job(self._render_job,reason="manual_view_synchronous")
            self._object_cache = render_spatial_object(self.reference,self._spatial_render_frame(),
                                                     self.draft.settings,None,vector=True)
            self._object_render_key = self._spatial_key()
            self._remember_object_picture(self._object_render_key,self._object_cache)
            self._render_proxy = False
            return
        self._queue_spatial_render()
        if silhouette and native is not None and fast_contour:
            # Show the exact light contour immediately while colored layer
            # bands are prepared; the 0% stage never shows a mesh-wire proxy.
            self._object_cache=render_spatial_object(self.reference,self._spatial_render_frame(),
                replace(self.draft.settings,critical_layers_enabled=False),None,vector=True)
            self._object_render_key=self._spatial_key()
            return
        if self.reference.object_triangles is not None and fast_contour:
            self._object_cache=render_silhouette_backing(self.reference,self._spatial_render_frame())
            self._object_render_key=self._spatial_key()
            return
        picture = QPicture()
        painter = QPainter(picture)
        # The proxy and final surfaces use the same oriented original mesh.
        if native is not None:
            triangles = native[::max(1,len(native)//2000)]
            array = triangles[:,(0,1,1,2,2,0),:].reshape(-1,2,3)
            source_center = self.reference.silhouette.center_xy
        else:
            array = self._object_array[::max(1,len(self._object_array)//4000)]
            source_center = self._object_center
        array = rotate_object(array,source_center,self._object_center,self.object_rotation)
        projected,_ = self._spatial_render_frame().project(array)
        pen = QPen(QColor(self.OBJECT_COLOR),1)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawLines([QLineF(QPointF(*a),QPointF(*b)) for a,b in projected])
        painter.end()
        self._object_cache = picture
        self._object_render_key = self._spatial_key()

    def _remember_object_picture(self,key,picture):
        self._object_pictures[key]=picture
        self._object_pictures.move_to_end(key)
        while len(self._object_pictures)>1 and (len(self._object_pictures)>10 or object_picture_cache_size(self._object_pictures.values())>64*1024*1024):
            self._object_pictures.popitem(last=False)

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

    def _tower_picture(self,rings):
        settings = self.draft.settings
        key = (rings,self.draft.curves,settings.circle_segments,settings.overhang_enabled,
               settings.overhang_angle_deg,self._placement.center_x_mm,self._placement.center_y_mm,
               self._world_origin,self.yaw_deg,self.pitch_deg,self.view in {"top","bottom"})
        if key == self._tower_render_key:
            return self._tower_cache
        picture = QPicture()
        painter = QPainter(picture)
        # Filled, depth-sorted surface patches avoid sparse wireframe gaps.
        count = self.draft.settings.circle_segments
        surfaces = []
        center = self._placement.center_x_mm,self._placement.center_y_mm
        arrays = [np.array([(center[0]+p.radius_mm*math.cos(math.tau*i/count),
                            center[1]+p.radius_mm*math.sin(math.tau*i/count),p.z_mm) for i in range(count)]) for p in rings]
        projected = [self._spatial_render_frame().project(a) for a in arrays]
        for j,(a,b) in enumerate(zip(projected,projected[1:])):
            color = self._surface_color((rings[j].z_mm+rings[j+1].z_mm)/2)
            for i in range(count):
                k = (i+1)%count
                surfaces.append(((a[1][i]+a[1][k]+b[1][i]+b[1][k])/4,
                                 QPolygonF([QPointF(*a[0][i]),QPointF(*a[0][k]),QPointF(*b[0][k]),QPointF(*b[0][i])]),
                                 color,j,i,k))
        patches = np.array([[arrays[j][i],arrays[j][k],arrays[j+1][k]] for _,_,_,j,i,k in surfaces])
        brightness = surface_brightness(patches,self._spatial_render_frame())
        order = sorted(range(len(surfaces)),key=lambda index:surfaces[index][0])
        for index in order:
            _,polygon,color,_,_,_ = surfaces[index]
            draw_surface(painter,polygon,color,brightness[index])
        cap = -1 if self.pitch_deg >= 0 else 0
        contour_color = self.COLORS["foot"] if self.view == "bottom" else self.PROFILE_COLOR
        painter.setPen(cosmetic_pen(QColor(contour_color),2) if self.view in {"top","bottom"}
                       else cosmetic_pen(self._surface_color(rings[cap].z_mm),.5))
        painter.setBrush(self._surface_color(rings[cap].z_mm))
        painter.drawPolygon(QPolygonF([QPointF(*p) for p in projected[cap][0]]))
        painter.end()
        self._tower_cache,self._tower_render_key = picture,key
        return picture

    def _draw_spatial_picture(self,painter,picture,opacity):
        painter.save()
        frame = self._spatial_frame()
        scale = frame.scale
        painter.translate(frame.width/2+frame.pan[0]-frame.projected_center[0]*scale,
                          frame.height/2+frame.pan[1]+frame.projected_center[1]*scale)
        painter.scale(scale,scale)
        draw_object_picture(painter,picture,opacity)
        painter.restore()

    def _original_image(self):
        """Cache exact device pixels, including per-patch X-ray composition."""
        frame=replace(self._spatial_frame(),highlight="both")
        opacity=.28 if self.highlight in {"object","all"} else 1
        ratio=self.devicePixelRatioF()
        key=(frame,opacity,ratio)
        if (self._object_image_cache is None or self._object_image_picture is not self._object_cache or
                self._object_image_key != key):
            image=QImage(math.ceil(self.width()*ratio),math.ceil(self.height()*ratio),
                         QImage.Format.Format_ARGB32_Premultiplied)
            image.setDevicePixelRatio(ratio)
            # Cache only the background and original, before tower, scales and
            # handles. This preserves even overlapping translucent mesh edges.
            image.fill(QColor("#e6ecf2"))
            painter=QPainter(image)
            self._draw_spatial_picture(painter,self._object_cache,opacity)
            painter.end()
            self._object_image_cache=image
            self._object_image_key=key
            self._object_image_picture=self._object_cache
        return self._object_image_cache

    def paintEvent(self,event):
        self._update_fit_button()
        painter = QPainter(self)
        painter.fillRect(self.rect(),QColor("#e6ecf2"))
        if self.draft is None or self.reference is None:
            painter.setPen(QColor("#526274"))
            painter.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,"Manueller Entwurf wird vorbereitet …")
            painter.end()
            return
        if self._object_cache is None or self._object_render_key != self._spatial_key():
            self._render_object()
        painter.drawImage(QPointF(),self._original_image())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(.35 if self.highlight in {"tower","all"} else 1)
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
            foot_path,body_path = QPainterPath(),QPainterPath()
            foot_path.moveTo(self.profile_to_screen(rings[0].radius_mm,0))
            body_started = False
            for a,b in zip(rings,rings[1:]):
                if b.z_mm <= self.draft.settings.foot_height_mm+1e-8:
                    foot_path.lineTo(self.profile_to_screen(b.radius_mm,b.z_mm))
                else:
                    if not body_started:
                        body_path.moveTo(self.profile_to_screen(a.radius_mm,a.z_mm));body_started=True
                    body_path.lineTo(self.profile_to_screen(b.radius_mm,b.z_mm))
            painter.setPen(QPen(QColor(self.COLORS["foot"]),3));painter.drawPath(foot_path)
            painter.setPen(QPen(QColor(self.PROFILE_COLOR),3));painter.drawPath(body_path)
            painter.setPen(QPen(QColor("#a3b1c0"),1))
            painter.drawLine(self.profile_to_screen(-self._fit_width,0),self.profile_to_screen(self._fit_width,0))
        else:
            self._draw_spatial_picture(painter,self._tower_picture(rings),.35 if self.highlight in {"tower","all"} else 1)
        painter.setOpacity(1)
        if self._insertion_preview is not None and self.editable:
            position,_ = self._insertion_preview
            painter.setPen(QPen(QColor(181,232,201,180),1))
            painter.setBrush(QColor(127,207,159,145))
            painter.drawEllipse(position,6,6)
        self._draw_scales(painter)
        if self._drag_height_z is not None and self.editable:
            y = self.profile_to_screen(0,self._drag_height_z).y()
            painter.setPen(QPen(QColor("#536980"),1.5,Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(12,y),QPointF(self.width()-12,y))
            painter.drawText(QRectF(12,y+4,self.width()-24,20),Qt.AlignmentFlag.AlignLeft,
                             self.drag_height_text())
        if self._height_snap_z is not None and self.view in {"side","front"}:
            y = self.profile_to_screen(0,self._height_snap_z).y()
            painter.setPen(QPen(QColor(self.COLORS["top"]),1.5,Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(12,y),QPointF(self.width()-12,y))
            painter.drawText(self._height_snap_label_rect(y),Qt.AlignmentFlag.AlignRight,"Objektoberkante")
        if (self._width_limit_settings or self._control_height_limits) and self.view in {"side","front"}:
            painter.save()
            painter.setOpacity(self._width_limit_opacity)
            painter.setPen(QPen(QColor("#146fd1"),1,Qt.PenStyle.DashLine))
            for setting in self._width_limit_settings:
                painter.drawLine(*self.width_limit_guide_geometry(setting=setting))
                if setting == "minimum_diameter_mm":
                    painter.drawLine(*self.width_limit_guide_geometry(left=True,setting=setting))
            for height in self._control_height_limits:
                y=self.profile_to_screen(0,height).y()
                painter.drawLine(QPointF(12,y),QPointF(self.width()-12,y))
            painter.restore()
        if self.editable:
            if self.view in {"side","front"}:
                left,right,left_end,right_end=self.minimum_measure_geometry()
                painter.setPen(self._minimum_measure_pen())
                painter.drawLine(left,left_end)
                painter.drawLine(right,right_end)
                painter.setPen(QPen(QColor("#bec5ce"),1,Qt.PenStyle.DashLine))
                painter.drawLine(left_end,right_end)
                painter.setPen(QColor("#536980"))
                painter.drawText(self.minimum_measure_label_rect(),
                                 Qt.AlignmentFlag.AlignHCenter,"Min. Turm-Ø")
            handles = self.handles()
            for identity,pos,kind in handles:
                if identity in self.LIMITS and identity != "minimum_diameter_mm":
                    start,_ = self.limit_geometry(identity)
                    painter.setPen(self._limit_guide_pen(start,pos))
                    painter.drawLine(start,pos)
                elif identity in self.HEIGHT_HANDLES:
                    start,end = self.height_handle_geometry(identity)
                    painter.setPen(self._limit_guide_pen(start,end))
                    painter.drawLine(start,end)
                if kind == "control":
                    _,i,n = identity.split(":")
                    curve = self.draft.curves[int(i)]
                    anchor = curve.start if n == "1" else curve.end
                    painter.setPen(QPen(QColor(self.COLORS[kind]),1,Qt.PenStyle.DashLine))
                    painter.drawLine(pos,self.profile_to_screen(anchor.radius_mm,anchor.z_mm))
            for identity,pos,kind in handles:
                active = identity in {self.selected,self.information_identity(),self.hovered}
                painter.setPen(QPen(QColor("#ffffff"),3 if active else 1.5))
                painter.setBrush(QColor(self.COLORS[kind]))
                if (identity in self.LIMITS and identity != "minimum_diameter_mm") or identity in self.HEIGHT_HANDLES:
                    delta = QPointF(7,0) if identity in self.HEIGHT_HANDLES else QPointF(0,7)
                    stroke = QLineF(pos-delta,pos+delta)
                    painter.setPen(QPen(QColor("#ffffff"),6 if active else 4))
                    painter.drawLine(stroke)
                    painter.setPen(QPen(QColor(self.COLORS[kind]),4 if active else 2.5))
                    painter.drawLine(stroke)
                elif kind == "control":
                    painter.drawRect(QRectF(pos.x()-5,pos.y()-5,10,10))
                else:
                    painter.drawEllipse(pos,8 if active else 6,8 if active else 6)
            selected_handle = next((pos for identity,pos,_ in handles if identity == self.selected),None)
            text = self.selected_handle_text()
            if self.point_editor is None and selected_handle is not None and text:
                # Keep the label to the right of nearby companion grips as well.
                right = max(pos.x() for _,pos,_ in handles if abs(pos.y()-selected_handle.y()) <= 11)
                if self.selected == "minimum_diameter_mm":
                    right=max(right,self.minimum_measure_label_rect().right()-6)
                painter.save()
                font = painter.font()
                font.setPointSizeF(max(9,font.pointSizeF()*.9))
                painter.setFont(font)
                width = painter.fontMetrics().horizontalAdvance(text)+14
                rectangle = QRectF(right+14,selected_handle.y()-12,width,24)
                painter.setPen(QPen(QColor("#a3b1c0"),.7))
                painter.setBrush(QColor(230,236,242,235))
                painter.drawRoundedRect(rectangle,4,4)
                painter.setPen(QColor("#536980"))
                painter.drawText(rectangle.adjusted(7,0,-7,0),Qt.AlignmentFlag.AlignVCenter,text)
                painter.restore()
        painter.setPen(QColor("#526274"))
        caption = self.caption_text()
        if self.caption_visible():
            painter.drawText(self.caption_rect(), Qt.AlignmentFlag.AlignVCenter, caption)
        painter.end()
        if self.point_editor is not None:self.point_editor.reposition()

    def caption_text(self):
        caption = ("Nebeneinander · Turm links, Original rechts · gleicher Maßstab" if self.view == "side" else
                   "Voreinander · Turm und Original hintereinander · gleicher Maßstab" if self.view == "front" else
                   "Räumliche Prüfung · tatsächliche Druckbettanordnung")
        if self._render_proxy and self.view not in {"side","front"}:caption += " · Objektflächen werden aufgebaut …"
        elif self._render_failure_key == self._spatial_key() and self._render_failure_key is not None:
            caption += " · Vollständige Objektansicht nicht verfügbar"
        return caption

    def caption_visible(self):
        return self.fontMetrics().horizontalAdvance(self.caption_text()) <= self.caption_rect().width()

    def caption_rect(self):
        left = self.history_controls.geometry().right() + 8
        right = self.width()-8 if self.view_controls.y() > self.history_controls.geometry().bottom() else self.view_controls.x()-8
        return QRectF(left, 8, max(0, right-left), 26)

    def _axis_projection(self):
        if self.view in {"side","front"}:
            scale,_,origin = self.transform()
            return origin,scale
        if self.view in {"top","bottom"}:
            return None
        center = self._placement.center_x_mm,self._placement.center_y_mm
        screen,_ = self._project_world(np.array([(center[0],center[1],0),(center[0],center[1],1)]))
        scale = screen[0,1]-screen[1,1]
        return (screen[0,1],scale) if scale > 1e-6 else None

    @staticmethod
    def _nice_step(minimum):
        power = 10**math.floor(math.log10(max(minimum,1e-12)))
        return next(value*power for value in (1,2,5,10) if value*power >= minimum)

    def scale_ticks(self):
        axis = self._axis_projection()
        if axis is None:
            return (),()
        origin,scale = axis
        rectangle=self.plot_rect()
        lower,upper = max(0,(origin-rectangle.bottom())/scale),(origin-rectangle.top())/scale
        step = self._nice_step(45/scale)
        heights = []
        z = math.ceil(lower/step)*step
        while z <= upper+1e-9:
            heights.append((z,origin-z*scale))
            z += step
        tops = [layer.z_mm for layer in self.reference.context.layers]
        start,end = bisect_left(tops,lower),bisect_left(tops,upper+1e-9)
        visible = tops[start:end]
        layer_step = float(np.median(np.diff(visible))) if len(visible)>1 else tops[0]
        stride = max(1,int(self._nice_step(max(1,24/max(1e-9,layer_step*scale)))))
        layers = []
        last_tick,last_label = math.inf,math.inf
        for i in range(start,end):
            y = origin-tops[i]*scale
            major = ((i+1)%stride==0 or i==0 or i==len(tops)-1) and last_label-y >= 22
            if major or last_tick-y >= 3:
                layers.append((i+1,y,major))
                last_tick = y
                if major: last_label = y
        return tuple(heights),tuple(layers)

    def drag_height_text(self):
        z = self._drag_height_z
        if z is None:
            return ""
        tops = [layer.z_mm for layer in self.reference.context.layers]
        layer = str(bisect_left(tops,z-1e-8)+1) if 0 <= z <= tops[-1]+1e-8 else "–"
        return f"Höhe: {z:.2f} mm · Layer: {layer}".replace(".",",")

    def _draw_scales(self,painter):
        heights,layers = self.scale_ticks()
        left,right = 43,self.width()-43
        line_top=self._scale_line_top()
        top=line_top-2
        painter.fillRect(QRectF(0,top,left+2,self.height()-top-20),QColor(230,236,242,235))
        painter.fillRect(QRectF(right-2,top,self.width()-right+2,self.height()-top-20),QColor(230,236,242,235))
        painter.setPen(QPen(QColor("#8195aa"),1))
        if self._axis_projection() is not None:
            painter.drawLine(QPointF(left,line_top),QPointF(left,self.height()-24))
            painter.drawLine(QPointF(right,line_top),QPointF(right,self.height()-24))
        painter.setPen(QColor("#526274"))
        painter.drawText(QRectF(3,top,left-6,20),Qt.AlignmentFlag.AlignRight,"mm")
        painter.drawText(self._layer_scale_heading_rect(),Qt.AlignmentFlag.AlignRight,"Layer")
        for z,y in heights:
            painter.drawLine(QPointF(left-4,y),QPointF(left,y))
            if y >= top+30:
                painter.drawText(QRectF(2,y-10,left-8,20),Qt.AlignmentFlag.AlignRight,f"{z:g}".replace(".",","))
        for layer,y,major in layers:
            painter.drawLine(QPointF(right,y),QPointF(right+(4 if major else 2),y))
            if major and y >= top+30:
                painter.drawText(QRectF(right+6,y-10,36,20),Qt.AlignmentFlag.AlignLeft,str(layer))
        if self.view in {"top","bottom"}:
            z = self.draft.height_mm if self.view == "top" else self.draft.first_layer_z_mm
            tops = [layer.z_mm for layer in self.reference.context.layers]
            layer = str(bisect_left(tops,z-1e-8)+1) if z <= tops[-1]+1e-8 else "–"
            painter.drawText(QRectF(2,top+24,left-8,20),Qt.AlignmentFlag.AlignRight,f"{z:g}".replace(".",","))
            painter.drawText(QRectF(right+6,top+24,36,20),Qt.AlignmentFlag.AlignLeft,layer)

    def _scale_line_top(self):
        return max(46,self.view_controls.geometry().bottom()+4)+2

    def _layer_scale_heading_rect(self):
        return QRectF(self.width()-93,self._scale_line_top()-2,44,20)

    def _height_snap_label_rect(self,y):
        heading=self._layer_scale_heading_rect()
        rectangle=QRectF(12,y+4,heading.right()-12,20)
        if rectangle.intersects(heading):
            rectangle.setRight(heading.left()-6)
        return rectangle

    def resizeEvent(self,event):
        self._insertion_preview=None
        self.view_controls.relayout()
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

    def _hide_width_limit_guide(self):
        self._width_limit_animation.stop()
        self._width_limit_opacity = 0.
        self._width_limit_setting = None
        self._width_limit_settings = ()
        self._control_height_limits = ()
        self.update()

    def _set_width_limit_opacity(self,value):
        self._width_limit_opacity=float(value)
        self.update()

    def set_width_limit_feedback(self,setting,diameter):
        previous = self._width_limit_last_request
        self._width_limit_last_request = diameter
        if setting is None:
            return
        outward = (previous is None or
                   (diameter < previous-1e-8 if setting == "minimum_diameter_mm" else diameter > previous+1e-8))
        if outward and (setting != self._width_limit_setting or
                        self._width_limit_animation.state() != QVariantAnimation.State.Running):
            # A brief pulse is not extended by continued movement. After it
            # expires, another outward attempt can show the boundary again.
            self._width_limit_setting = setting
            self._width_limit_settings = (setting,)
            self._control_height_limits = ()
            self._width_limit_animation.stop()
            self._width_limit_opacity=1.
            self._width_limit_animation.start()
            self.update()

    def set_control_limit_feedback(self,error,index,n,diameter,z):
        if error is None:return
        widths=getattr(error,"limits",())
        if not widths and error.setting in self.LIMITS:widths=(error.setting,)
        heights=()
        if error.setting=="control_height_mm":
            curve=self.draft.curves[index]
            lower=curve.start.z_mm if n==1 else curve.control1.z_mm
            upper=curve.control2.z_mm if n==1 else curve.end.z_mm
            heights=tuple(value for value,violated in ((lower,z<=lower),(upper,z>=upper)) if violated)
        if not widths and not heights:return
        if ((widths,heights)!=(self._width_limit_settings,self._control_height_limits) or
                self._width_limit_animation.state()!=QVariantAnimation.State.Running):
            self._width_limit_setting=next(iter(widths),None)
            self._width_limit_settings=tuple(widths);self._control_height_limits=heights
            self._width_limit_animation.stop();self._width_limit_opacity=1.
            self._width_limit_animation.start();self.update()

    def _vertical_handle_height(self,identity):
        if identity.startswith("control:"):
            _,index,number = identity.split(":")
            return getattr(self.draft.curves[int(index)],f"control{number}").z_mm
        if identity == "foot_height":
            return self.draft.settings.foot_height_mm
        return next((p.position.z_mm for p in self.draft.points
                     if p.identity == identity and p.kind in {"free","top"}),None)

    def _horizontal_handle_radius(self,identity):
        if identity in self.LIMITS:
            return getattr(self.draft.settings,identity)/2
        if identity in {"top","foot_height"}:
            return None
        if identity.startswith("control:"):
            _,index,number = identity.split(":")
            return getattr(self.draft.curves[int(index)],f"control{number}").radius_mm
        actual = "top" if identity == "top_width" else identity
        return next((p.position.radius_mm for p in self.draft.points if p.identity == actual),None)

    def selected_handle_text(self):
        if self.draft is None:
            return ""
        identity = self.information_identity()
        name = {"top_width":"Spitze", "base":"Grund", "foot":"Fuß",
                "maximum_diameter_mm":"Turmgrenze", "maximum_foot_diameter_mm":"Fußgrenze",
                "minimum_diameter_mm":"Minimum"}.get(identity)
        if name is not None:
            radius = self._horizontal_handle_radius(identity)
            return f"{name}: Ø {radius*2:.2f} mm".replace(".",",") if radius is not None else ""
        height = self._vertical_handle_height(identity)
        if height is None:
            return ""
        if self.draft.settings.layer_snap_enabled:
            layer = str(bisect_left(self._layer_tops,height-1e-8)+1) if self._layer_tops and height <= self._layer_tops[-1]+1e-8 else "–"
            return f"Layer: {layer}"
        return f"Höhe: {height:.2f} mm".replace(".",",")

    def horizontal_drag_snaps(self):
        return self._drag_width_active and self._drag is not None and self._drag[0] == "edit"

    def neighbor_diameter_snaps(self, identity, diameter):
        """Nearby radial positions of the two direct profile neighbours only."""
        draft = self._drag_origin_draft or self.draft
        if draft is None or identity.startswith("control:"):
            return ()
        index = next((i for i, point in enumerate(draft.points) if point.identity == identity), None)
        if index is None:
            return ()
        scale = self.transform()[0]
        nearby = []
        for neighbor in draft.points[max(0,index-1):index+2]:
            if neighbor.identity == identity:
                continue
            if identity == "base" and neighbor.identity == "top" and draft.top_follows_base and len(draft.points) == 3:
                # This endpoint already follows every radial base move.
                continue
            distance_px = abs(neighbor.position.diameter_mm-diameter)*scale/2
            if distance_px <= 8:
                nearby.append((distance_px, neighbor.identity, neighbor.position.diameter_mm))
        return tuple((key, value) for _, key, value in sorted(nearby))

    def constrained_drag_origin(self):
        return self._drag_origin_draft if self._drag_axis is not None and self._drag is not None else None

    def limit_drag_origin(self, identity):
        return self._drag_origin_draft if self._drag is not None and self._drag[:2] == ("edit",identity) else None

    def vertical_drag_snaps(self):
        return (self.draft is not None and self.draft.settings.layer_snap_enabled and
                self._drag is not None and self._drag[0] == "edit" and
                self._vertical_handle_height(self._drag[1]) is not None and
                self._drag_height_z is not None)

    def mousePressEvent(self,event):
        self._insertion_preview=None
        self.setFocus()
        self._drag_moved = False
        self._drag_width_active = False
        self._drag_radius = None
        self._drag_origin_draft = None
        self._drag_origin_height = None
        self._drag_axis = None
        self._drag_height_z = None
        self._set_height_snap_feedback(None)
        self._width_limit_last_request = None
        point = event.position()
        if self.view == "free":point=QPointF(point.toPoint())
        hit = self.hit_test(point) if event.button() in {Qt.MouseButton.LeftButton,Qt.MouseButton.RightButton} else None
        self._empty_click_position=None
        if event.button()==Qt.MouseButton.LeftButton and hit is None:
            interactive=self.insertion_at(point) is not None
            if not interactive:self._empty_click_position=QPointF(point)
        if event.button() == Qt.MouseButton.RightButton and hit is not None:
            if any(p.identity == hit and p.kind == "free" for p in self.draft.points):
                self.remove_requested.emit(hit)
            event.accept()
            return
        if hit:
            self.selected = hit
            self._drag_origin_draft = self.draft
            self._drag_origin_height = self._vertical_handle_height(hit)
            self._drag_radius = self._horizontal_handle_radius(hit)
            if self._drag_radius is not None:
                self._width_limit_last_request = self._drag_radius*2
            self.selection_changed.emit(hit)
            self.interaction_started.emit()
            self._drag = ("edit", hit, point)
        elif self.view == "free" and event.button() == Qt.MouseButton.LeftButton:
            self._drag = ("rotate",QPointF(point.toPoint()),None)
        elif event.button() in {Qt.MouseButton.MiddleButton,Qt.MouseButton.LeftButton} or (
                self.view == "free" and event.button() == Qt.MouseButton.RightButton):
            self._drag = ("pan",point,QPointF(self.pan))
        self.update()
        event.accept()

    def mouseMoveEvent(self,event):
        point = event.position()
        if self.view == "free":point=QPointF(point.toPoint())
        if self._empty_click_position is not None and (point-self._empty_click_position).manhattanLength()>3:
            self._empty_click_position=None
        if self._drag is None:
            self.hovered = self.hit_test(point)
            self._insertion_preview = self.insertion_at(point) if self.hovered is None else None
            self.setCursor(Qt.CursorShape.PointingHandCursor if self.hovered else Qt.CursorShape.ArrowCursor)
            self.update()
            return
        action,a,b = self._drag
        if action == "pan":
            self.pan = b+point-a
        elif action == "rotate":
            current=QPointF(point.toPoint())
            delta=current-a
            self._drag=("rotate",current,None)
            self.yaw_deg -= delta.x()*.45
            self.pitch_deg = max(-89,min(89,self.pitch_deg+delta.y()*.35))
            self._object_cache = None
        elif self.editable:
            self._drag_moved = self._drag_moved or (point-b).manhattanLength()>1e-6
            if self.view in {"top","bottom"}:
                position = self.draft.points[-1 if self.view == "top" else 0].position
                radius = position.radius_mm
                z = position.z_mm
            else:
                radius,z = self.screen_to_profile(point)
                shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
                unrestricted = a.startswith("control:") or any(p.identity == a and p.kind == "free" for p in self.draft.points)
                delta = point-b
                self._drag_axis = ("horizontal" if abs(delta.x()) >= abs(delta.y()) else "vertical") if shift and unrestricted else None
                requested_z = z
                height = self._vertical_handle_height(a)
                if height is not None:
                    if abs(point.y()-b.y()) > 1e-6 or self._drag_height_z is not None:
                        self._drag_height_z = height
                        if self.draft.settings.layer_snap_enabled:
                            snapped = snap_layer_height(z,self._layer_tops,upper=self.draft.maximum_height_mm)
                            if snapped is not None:
                                z = snapped
                    else:
                        z = height
            if self._drag_radius is not None:
                radius = self._drag_radius+(point.x()-b.x())/self.transform()[0]
                self._drag_width_active = self._drag_width_active or abs(point.x()-b.x())>1e-6
                if self._drag_width_active:
                    radius = round(radius*20)/20
            if self._drag_axis == "horizontal":
                z = self._drag_origin_height
                self._drag_height_z = None
            elif self._drag_axis == "vertical":
                radius = self._drag_radius
                self._drag_width_active = False
                z = self._drag_origin_height+(b.y()-point.y())/self.transform()[0]
                self._drag_height_z = self._drag_origin_height if abs(delta.y())>1e-6 else None
                if self.draft.settings.layer_snap_enabled:
                    snapped = snap_layer_height(z,self._layer_tops,upper=self.draft.maximum_height_mm)
                    if snapped is not None:z = snapped
            snap_height = None
            if a == "top" and self.reference is not None and self.draft.settings.layer_snap_enabled:
                object_top = self.reference.context.layers[-1].z_mm
                if (object_top <= self.draft.maximum_height_mm and
                        abs(requested_z-object_top)*self.transform()[0] <= self.HEIGHT_SNAP_DISTANCE_PX):
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
            elif self._drag_axis != "horizontal" and (self._drag_height_z is not None or abs(point.y()-b.y())>1e-6):
                # Use the accepted model height, including geometry limits and
                # snapping, rather than the potentially rejected mouse height.
                self._drag_height_z = height
        self._update_fit_button()
        if action in {"pan","rotate"}:
            self.view_state_changed.emit()
        self.update()
        event.accept()

    def insertion_at(self,point):
        """Detect either contour, but offer the node on the editable right edge."""
        if not self.editable or self.view not in {"side","front"}:return None
        radius,z=self.screen_to_profile(point)
        if not self.draft.settings.foot_height_mm<z<self.draft.height_mm:return None
        actual=self.draft.radius_at_z(z)
        contour=self.profile_to_screen(-actual if radius<0 else actual,z)
        if (point-contour).manhattanLength()>self.INSERTION_HOVER_DISTANCE_PX:return None
        position=self.profile_to_screen(actual,z)
        if any(math.hypot(position.x()-p.x(),position.y()-p.y())<=11 for _,p,_ in self.handles()):return None
        if self.validate_insertion is None or not self.validate_insertion(z):return None
        return position,z

    def leaveEvent(self,event):
        self.hovered=None;self._insertion_preview=None;self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self,event):
        deselect=(event.button()==Qt.MouseButton.LeftButton and self._empty_click_position is not None and
                  (event.position()-self._empty_click_position).manhattanLength()<=3)
        if self._drag is not None:
            editing = self._drag[0] == "edit"
            moved = editing and (self._drag_moved or (event.position()-self._drag[2]).manhattanLength()>1e-6)
            if editing and not moved and any(p.identity == self._drag[1] and p.kind == "free" for p in self.draft.points):
                # Show both own controls even for linear segments. Visibility
                # does not change their mode or the printed profile.
                self._revealed_control_anchor = self._drag[1]
            if not editing or moved:
                self.mouseMoveEvent(event)
            self._drag = None
            self._drag_origin_draft = None
            self._drag_origin_height = None
            self._drag_axis = None
            self._drag_height_z = None
            self.update()
            if editing:
                self.interaction_finished.emit()
        self._empty_click_position=None
        if deselect:
            self.selected="";self.hovered=None;self._revealed_control_anchor=None
            self.selection_changed.emit("");self.update()
        event.accept()

    def mouseDoubleClickEvent(self,event):
        self._empty_click_position=None
        if self.editable and self.view in {"side","front"} and event.button() == Qt.MouseButton.LeftButton:
            hit = self.hit_test(event.position())
            if hit is not None:
                editing = self._drag is not None and self._drag[0] == "edit"
                self._drag = None
                self._drag_height_z = None
                if hit in {"foot","foot_height","base","top","top_width"} or any(p.identity == hit for p in self.draft.points):
                    self.selected = hit
                    self.selection_changed.emit(hit)
                    self.curve_reset_requested.emit(hit)
                    self.update()
                if editing:
                    self.interaction_finished.emit()
                event.accept()
                return
            if self.view not in {"side","front"}:
                event.accept()
                return
            insertion=self.insertion_at(event.position())
            if insertion is not None:
                self._drag = None
                self._drag_height_z = None
                self._insertion_preview = None
                self.insert_requested.emit(insertion[1])
        event.accept()

    def wheelEvent(self,event):
        self._insertion_preview=None
        if self._drag is not None and self.view != "free":
            event.accept()
            return
        if self.view == "free":
            factor=1.15 if event.angleDelta().y() > 0 else 1/1.15
            self.zoom=max(.05,min(50,self.zoom*factor))
            self._update_fit_button()
            self.view_state_changed.emit()
            self.update()
            event.accept()
            return
        old = self.zoom
        def origin():
            if self.view in {"side","front"}:
                _,x,y = self.transform()
                return QPointF(x,y)
            scale = self.transform()[0]
            center=self.plot_rect().center()
            return QPointF(center.x()+self.pan.x()-self._spatial_center[0]*scale,
                           center.y()+self.pan.y()+self._spatial_center[1]*scale)
        old_origin = origin()
        self.zoom = max(.25,min(80,self.zoom*1.12**(event.angleDelta().y()/120)))
        ratio = self.zoom/old
        self.pan += event.position()-(origin()+(event.position()-old_origin)*ratio)
        self._update_fit_button()
        self.view_state_changed.emit()
        self.update()
        event.accept()

    def keyPressEvent(self,event):
        if self.editable and self.view in {"side","front"} and event.key() in {Qt.Key.Key_Delete,Qt.Key.Key_Backspace}:
            self.remove_requested.emit(self.selected)
            event.accept()
        elif event.key() == Qt.Key.Key_F:
            self.fit_scene()
            event.accept()
        else:
            super().keyPressEvent(event)
