"""Thread-owned QImage rendering; no widget or QPixmap crosses the worker."""
from dataclasses import dataclass
import math
import traceback
from collections import defaultdict
from bisect import bisect_left
import numpy as np
from PySide6.QtCore import QPointF,QLineF,Qt,Signal,Slot
from PySide6.QtGui import QImage,QPainter,QPolygonF,QPen,QColor
from cooling_tower.gui.worker_contract import CancelableWorker
from cooling_tower.gui.widgets.layer_range_canvas import LayerRangeCanvas
from cooling_tower.manual.service import check_cancel
from cooling_tower.preview import PreviewCancelled


@dataclass(frozen=True,slots=True)
class SpatialFrame:
    width: int
    height: int
    scale: float
    pan: tuple[float,float]
    yaw: float
    pitch: float
    world_origin: tuple[float,float]
    projected_center: tuple[float,float]
    object_center: tuple[float,float]
    object_rotation: float
    highlight: str

    def project(self,array):
        points=np.asarray(array,dtype=float).copy()
        points[...,0]-=self.world_origin[0];points[...,1]-=self.world_origin[1]
        yaw,pitch=math.radians(self.yaw),math.radians(self.pitch)
        horizontal=points[...,0]*math.cos(yaw)-points[...,1]*math.sin(yaw)
        depth=points[...,0]*math.sin(yaw)+points[...,1]*math.cos(yaw)
        vertical=points[...,2]*math.cos(pitch)-depth*math.sin(pitch)
        return np.stack((self.width/2+self.pan[0]+(horizontal-self.projected_center[0])*self.scale,
                         self.height/2+self.pan[1]-(vertical-self.projected_center[1])*self.scale),axis=-1),depth*math.cos(pitch)+points[...,2]*math.sin(pitch)


def render_spatial_object(reference,frame,settings,event):
    check_cancel(event)
    image=QImage(frame.width,frame.height,QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    if reference.object_triangles is None:
        return render_spatial_toolpaths(reference,frame,settings,event,image)
    triangles=reference.object_triangles.copy()
    center=np.asarray(reference.silhouette.center_xy)
    x,y=triangles[...,0]-center[0],triangles[...,1]-center[1]
    angle=math.radians(frame.object_rotation)
    triangles[...,0]=frame.object_center[0]+x*math.cos(angle)-y*math.sin(angle)
    triangles[...,1]=frame.object_center[1]+x*math.sin(angle)+y*math.cos(angle)
    projected,depth=frame.project(triangles)
    order=np.argsort(depth.mean(axis=1))
    painter=QPainter(image)
    try:
        painter.setOpacity(.28 if frame.highlight=="tower" else 1)
        base_color=QColor(LayerRangeCanvas.OBJECT_COLOR if settings.critical_layers_enabled else "#429baa")
        painter.setPen(QPen(base_color,.5));painter.setBrush(base_color)
        for i,index in enumerate(order):
            if i%512==0:check_cancel(event)
            painter.drawPolygon(QPolygonF([QPointF(*p) for p in projected[index]]))
        if settings.critical_layers_enabled:
            groups=defaultdict(list)
            for layer,section in zip(reference.context.layers,reference.silhouette.segments_xy):
                check_cancel(event)
                color=LayerRangeCanvas.layer_color(settings.target_layer_time_s,layer.total_time_s,
                                                   settings.gradient_start_deficit_s,settings.gradient_full_deficit_s)
                if color==QColor(LayerRangeCanvas.OBJECT_COLOR) or not len(section):continue
                coordinates=np.empty((*section.shape[:-1],3))
                sx,sy=section[...,0]-center[0],section[...,1]-center[1]
                coordinates[...,0]=frame.object_center[0]+sx*math.cos(angle)-sy*math.sin(angle)
                coordinates[...,1]=frame.object_center[1]+sx*math.sin(angle)+sy*math.cos(angle)
                coordinates[...,2]=layer.z_mm
                screens,_=frame.project(coordinates)
                groups[color.rgb()].extend(QLineF(QPointF(*a),QPointF(*b)) for a,b in screens)
            for color,lines in groups.items():
                check_cancel(event)
                painter.setPen(QPen(QColor.fromRgb(color),1.5));painter.drawLines(lines)
        check_cancel(event)
    finally:painter.end()
    return image


def render_spatial_toolpaths(reference, frame, settings, event, image):
    """Retain the original G-code paths when no verified source mesh exists."""
    coordinates = []
    for i, segment in enumerate(reference.source_data.object_segments):
        if i % 1024 == 0:
            check_cancel(event)
        coordinates.append(((segment.start.x, segment.start.y, segment.start.z),
                            (segment.end.x, segment.end.y, segment.end.z)))
    array = np.asarray(coordinates, dtype=float).reshape(-1, 2, 3)
    center = np.asarray(frame.object_center)
    x, y = array[..., 0] - center[0], array[..., 1] - center[1]
    angle = math.radians(frame.object_rotation)
    array[..., 0] = center[0] + x * math.cos(angle) - y * math.sin(angle)
    array[..., 1] = center[1] + x * math.sin(angle) + y * math.cos(angle)
    screens, _ = frame.project(array)
    tops = [layer.z_mm for layer in reference.context.layers]
    groups = defaultdict(list)
    for i, (segment, screen) in enumerate(zip(array, screens)):
        if i % 1024 == 0:
            check_cancel(event)
        layer = reference.context.layers[min(len(tops) - 1,
            bisect_left(tops, float(segment[:, 2].mean()) - 1e-5))]
        color = (LayerRangeCanvas.layer_color(settings.target_layer_time_s, layer.total_time_s,
                    settings.gradient_start_deficit_s, settings.gradient_full_deficit_s)
                 if settings.critical_layers_enabled else QColor(LayerRangeCanvas.OBJECT_COLOR))
        groups[color.rgb()].append(QLineF(QPointF(*screen[0]), QPointF(*screen[1])))
    painter = QPainter(image)
    try:
        painter.setOpacity(.28 if frame.highlight == "tower" else 1)
        for color, lines in groups.items():
            check_cancel(event)
            painter.setPen(QPen(QColor.fromRgb(color), 1.2))
            painter.drawLines(lines)
    finally:
        painter.end()
    check_cancel(event)
    return image


class ManualViewWorker(CancelableWorker):
    succeeded=Signal(int,object)
    failed=Signal(int,str,str)
    finished=Signal(int)

    def __init__(self,request_id,reference,frame,settings,key):
        super().__init__()
        self.request_id,self.reference,self.frame,self.settings,self.key=request_id,reference,frame,settings,key

    @Slot()
    def run(self):
        with self.diagnostic_scope():
            try:result=render_spatial_object(self.reference,self.frame,self.settings,self.cancellation_event)
            except PreviewCancelled:pass
            except Exception as error:
                if not self.cancellation_requested():self.failed.emit(self.request_id,str(error),traceback.format_exc())
            else:
                if not self.cancellation_requested():self.succeeded.emit(self.request_id,(self.key,result))
            finally:self.finished.emit(self.request_id)
