"""Thread-owned QImage rendering; no widget or QPixmap crosses the worker."""
from dataclasses import dataclass
import math
import traceback
from collections import defaultdict
from bisect import bisect_left
import numpy as np
from PySide6.QtCore import QPointF,QLineF,Qt,Signal,Slot
from PySide6.QtGui import QImage,QPicture,QPainter,QPolygonF,QPen,QColor
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


def rotate_object(array, source_center, target_center, angle_deg):
    """Use the same original orientation for mesh, sections and wireframe."""
    result = np.asarray(array,dtype=float).copy()
    x,y = result[...,0]-source_center[0],result[...,1]-source_center[1]
    angle = math.radians(angle_deg)
    result[...,0] = target_center[0]+x*math.cos(angle)-y*math.sin(angle)
    result[...,1] = target_center[1]+x*math.sin(angle)+y*math.cos(angle)
    return result


def cosmetic_pen(color,width):
    pen = QPen(color,width)
    pen.setCosmetic(True)
    return pen


def surface_brightness(vertices,frame):
    """Flat lighting in camera space; evaluate normals after object rotation."""
    vertices = np.asarray(vertices,dtype=float)
    normals = np.cross(vertices[:,1]-vertices[:,0],vertices[:,2]-vertices[:,0])
    lengths = np.linalg.norm(normals,axis=1)
    normals = np.divide(normals,lengths[:,None],out=np.zeros_like(normals),where=lengths[:,None]>1e-12)
    yaw,pitch = math.radians(frame.yaw),math.radians(frame.pitch)
    horizontal = np.array((math.cos(yaw),-math.sin(yaw),0))
    vertical = np.array((-math.sin(yaw)*math.sin(pitch),-math.cos(yaw)*math.sin(pitch),math.cos(pitch)))
    depth = np.array((math.sin(yaw)*math.cos(pitch),math.cos(yaw)*math.cos(pitch),math.sin(pitch)))
    light = -.35*horizontal+.45*vertical+.82*depth
    light /= np.linalg.norm(light)
    return .86+.28*np.abs(normals@light)


def shaded_color(color,brightness):
    return QColor(*(min(255,round(channel*brightness)) for channel in (color.red(),color.green(),color.blue())))


def surface_styles(color,brightness):
    """Create each exact quantized fill/edge/node style once per render job."""
    channels=np.array((color.red(),color.green(),color.blue()))
    shades=np.minimum(255,np.rint(brightness[:,None]*channels)).astype(np.uint8)
    unique,indices=np.unique(shades,axis=0,return_inverse=True)
    styles=[]
    for shade in unique:
        fill=QColor(*map(int,shade))
        edge=cosmetic_pen(fill.darker(125),0)
        node=cosmetic_pen(fill.darker(145),0)
        node.setCapStyle(Qt.PenCapStyle.RoundCap)
        styles.append((fill,edge,node))
    return styles,indices


def draw_surface(painter,polygon,color,brightness,style=None):
    """Draw details with each depth-sorted patch so hidden edges stay hidden."""
    if style is None:
        fill = shaded_color(color,brightness)
        edge=cosmetic_pen(fill.darker(125),0)
        node=cosmetic_pen(fill.darker(145),0)
        node.setCapStyle(Qt.PenCapStyle.RoundCap)
    else:
        fill,edge,node=style
    painter.setBrush(fill)
    # Width zero is Qt's intrinsic one-pixel pen.
    painter.setPen(edge)
    painter.drawPolygon(polygon)
    painter.setPen(node)
    # QPicture replays points/zero-length lines as scaled squares. Tiny but
    # nonzero lines use its correct cosmetic-line path (under 0.01 px at zoom).
    painter.drawLines([QLineF(point,point+QPointF(1e-6,0)) for point in polygon])


def simplify_display_mesh(triangles,percent,event=None):
    """Cluster vertices for a complete coarse surface, never discard isolated faces.

    Only preview coordinates are reduced. At 100% return the exact original.
    The percentage is a face-count target, not a topology/print-accuracy claim.
    """
    if percent == 100 or len(triangles) <= 24:
        return triangles
    check_cancel(event)
    vertices,inverse = np.unique(np.asarray(triangles).reshape(-1,3),axis=0,return_inverse=True)
    faces = inverse.reshape(-1,3)
    area = np.linalg.norm(np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0]),axis=1).sum()/2
    target = max(12,round(len(triangles)*percent/100))
    if area <= 1e-12:
        return triangles
    size = math.sqrt(area/target)
    origin = vertices.min(axis=0)
    best = triangles
    for _ in range(4):
        check_cancel(event)
        cells = np.floor((vertices-origin)/size).astype(np.int64)
        _,groups = np.unique(cells,axis=0,return_inverse=True)
        counts = np.bincount(groups)
        reduced = np.column_stack([np.bincount(groups,weights=vertices[:,axis])/counts for axis in range(3)])
        clustered = groups[faces]
        valid = (clustered[:,0]!=clustered[:,1])&(clustered[:,1]!=clustered[:,2])&(clustered[:,2]!=clustered[:,0])
        clustered = clustered[valid]
        if not len(clustered):
            size /= 2
            continue
        # Keep original winding while removing duplicate surface patches.
        _,indices = np.unique(np.sort(clustered,axis=1),axis=0,return_index=True)
        candidate = reduced[clustered[indices]]
        if len(candidate) >= 4 and abs(len(candidate)-target) < abs(len(best)-target):
            best = candidate
        if len(candidate) <= target*1.1:
            break
        size *= max(1.15,math.sqrt(len(candidate)/target))
    check_cancel(event)
    return best


def render_spatial_object(reference,frame,settings,event,*,vector=False):
    check_cancel(event)
    image = QPicture() if vector else QImage(frame.width,frame.height,QImage.Format.Format_ARGB32_Premultiplied)
    if not vector:
        image.fill(Qt.GlobalColor.transparent)
    if reference.object_triangles is None:
        return render_spatial_toolpaths(reference,frame,settings,event,image)
    center=np.asarray(reference.silhouette.center_xy)
    angle=math.radians(frame.object_rotation)
    display_triangles=simplify_display_mesh(reference.object_triangles,settings.object_resolution_percent,event)
    triangles=rotate_object(display_triangles,center,frame.object_center,frame.object_rotation)
    projected,depth=frame.project(triangles)
    brightness=surface_brightness(triangles,frame)
    order=np.argsort(depth.mean(axis=1))
    painter=QPainter(image)
    try:
        if not vector:
            painter.setOpacity(.28 if frame.highlight=="object" else 1)
        base_color=QColor(LayerRangeCanvas.OBJECT_COLOR if settings.critical_layers_enabled else "#429baa")
        styles,style_indices=surface_styles(base_color,brightness)
        for i,index in enumerate(order):
            if i%512==0:check_cancel(event)
            draw_surface(painter,QPolygonF([QPointF(*p) for p in projected[index]]),base_color,brightness[index],
                         styles[style_indices[index]])
        if settings.critical_layers_enabled:
            groups=defaultdict(list)
            for layer,section in zip(reference.context.layers,reference.silhouette.segments_xy):
                check_cancel(event)
                color=LayerRangeCanvas.layer_color(settings.color_reference_time_s,layer.total_time_s,
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
                painter.setPen(cosmetic_pen(QColor.fromRgb(color),1.5));painter.drawLines(lines)
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
    array = rotate_object(array,frame.object_center,frame.object_center,frame.object_rotation)
    screens, _ = frame.project(array)
    tops = [layer.z_mm for layer in reference.context.layers]
    groups = defaultdict(list)
    for i, (segment, screen) in enumerate(zip(array, screens)):
        if i % 1024 == 0:
            check_cancel(event)
        layer = reference.context.layers[min(len(tops) - 1,
            bisect_left(tops, float(segment[:, 2].mean()) - 1e-5))]
        color = (LayerRangeCanvas.layer_color(settings.color_reference_time_s, layer.total_time_s,
                    settings.gradient_start_deficit_s, settings.gradient_full_deficit_s)
                 if settings.critical_layers_enabled else QColor(LayerRangeCanvas.OBJECT_COLOR))
        groups[color.rgb()].append(QLineF(QPointF(*screen[0]), QPointF(*screen[1])))
    painter = QPainter(image)
    try:
        if not isinstance(image,QPicture):
            painter.setOpacity(.28 if frame.highlight == "object" else 1)
        for color, lines in groups.items():
            check_cancel(event)
            painter.setPen(cosmetic_pen(QColor.fromRgb(color), 1.2))
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
            try:result=render_spatial_object(self.reference,self.frame,self.settings,self.cancellation_event,vector=True)
            except PreviewCancelled:pass
            except Exception as error:
                if not self.cancellation_requested():self.failed.emit(self.request_id,str(error),traceback.format_exc())
            else:
                if not self.cancellation_requested():self.succeeded.emit(self.request_id,(self.key,result))
            finally:self.finished.emit(self.request_id)
