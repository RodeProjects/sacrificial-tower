"""Thread-owned QImage rendering; no widget or QPixmap crosses the worker."""
from dataclasses import dataclass
import math
import traceback
from collections import defaultdict
from bisect import bisect_left
import numpy as np
from PySide6.QtCore import QPointF,QLineF,QRectF,Qt,Signal,Slot
from PySide6.QtGui import QImage,QPicture,QPainter,QPainterPath,QPolygonF,QPen,QColor
from cooling_tower.gui.worker_contract import CancelableWorker
from cooling_tower.gui.widgets.layer_range_canvas import LayerRangeCanvas
from cooling_tower.manual.service import check_cancel
from cooling_tower.preview import PreviewCancelled
from cooling_tower.preview.mesh_silhouette import build_mesh_silhouette
from cooling_tower.preview.display_mesh import SMALL_MESH_FACES,simplify_display_mesh


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
    exact_silhouette: bool = False

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


def draw_display_surface(painter,polygon,style,*,edges=False):
    """Dense previews omit per-vertex dots and optional mesh-edge commands."""
    fill,edge,_=style
    painter.setBrush(fill)
    painter.setPen(edge if edges else Qt.PenStyle.NoPen)
    painter.drawPolygon(polygon)


class RasterObjectPicture(QPicture):
    """Immutable worker result with normal and per-surface X-ray rasters."""
    def __init__(self):
        super().__init__()
        self.xray_picture=None
        self.raster_size=(0,0)


def _raster_object_picture(projected,silhouette,frame,settings,paint,event,exact_contour):
    """Bound GUI replay cost to one image, independent of source face count.

    Rasterization stays in the worker. Original contours remain vector paths
    at viewport precision; the image only carries the shaded interior.
    """
    bounds=silhouette.boundingRect() if silhouette is not None and not silhouette.isEmpty() else QRectF()
    if bounds.isEmpty():
        low,high=projected.min(axis=(0,1)),projected.max(axis=(0,1))
        bounds=QRectF(float(low[0]),float(low[1]),max(float(high[0]-low[0]),1e-6),max(float(high[1]-low[1]),1e-6))
    pixels=round(512+768*settings.object_resolution_percent/100)
    scale=pixels/max(bounds.width(),bounds.height(),1e-6)
    bounds=bounds.adjusted(-2/scale,-2/scale,2/scale,2/scale)
    width,height=math.ceil(bounds.width()*scale),math.ceil(bounds.height()*scale)
    result=RasterObjectPicture()
    result.raster_size=(width,height)
    for opacity in (1,.28):
        check_cancel(event)
        raster=QImage(width,height,QImage.Format.Format_ARGB32_Premultiplied)
        raster.fill(Qt.GlobalColor.transparent)
        painter=QPainter(raster)
        try:
            painter.scale(scale,scale)
            painter.translate(-bounds.left(),-bounds.top())
            paint(painter,opacity,False)
        finally:painter.end()
        picture=result if opacity==1 else QPicture()
        painter=QPainter(picture)
        try:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            if exact_contour and silhouette is not None and not silhouette.isEmpty():
                painter.setClipPath(silhouette)
            painter.drawImage(bounds,raster)
            painter.setClipping(False)
            if exact_contour and silhouette is not None and not silhouette.isEmpty():
                painter.setOpacity(opacity)
                painter.strokePath(silhouette,cosmetic_pen(QColor("#429baa").darker(125),1))
        finally:painter.end()
        if opacity!=1:result.xray_picture=picture
    check_cancel(event)
    return result


def silhouette_backing_color():
    # Keep the full contour visible around reduced facets without flattening
    # their shading. Object X-Ray still applies to the complete original.
    return QColor(173,211,238,210)


def render_silhouette_backing(reference,frame,event=None):
    picture=QPicture();painter=QPainter(picture)
    try:
        path=original_silhouette_path(reference,frame,event)
        painter.fillPath(path,silhouette_backing_color())
        if reliable_original_contours(reference):
            painter.strokePath(path,cosmetic_pen(QColor("#429baa").darker(125),1))
    finally:painter.end()
    return picture


def render_spatial_object(reference,frame,settings,event,*,vector=False):
    check_cancel(event)
    image = QPicture() if vector else QImage(frame.width,frame.height,QImage.Format.Format_ARGB32_Premultiplied)
    if not vector:
        image.fill(Qt.GlobalColor.transparent)
    if reference.object_triangles is None:
        return render_spatial_toolpaths(reference,frame,settings,event,image)
    if settings.object_resolution_percent == 0:
        return render_silhouette_object(reference,frame,settings,event,image)
    center=np.asarray(reference.silhouette.center_xy)
    angle=math.radians(frame.object_rotation)
    mesh=getattr(reference,"object_silhouette",None)
    display_triangles=simplify_display_mesh(reference.object_triangles,settings.object_resolution_percent,event,
        topology=mesh.topology if mesh is not None and mesh.source is reference.object_triangles else None)
    triangles=rotate_object(display_triangles,center,frame.object_center,frame.object_rotation)
    projected,depth=frame.project(triangles)
    brightness=surface_brightness(triangles,frame)
    order=np.argsort(depth.mean(axis=1))
    base_color=QColor(LayerRangeCanvas.OBJECT_COLOR if settings.critical_layers_enabled else "#429baa")
    silhouette=original_silhouette_path(reference,frame,event) if frame.exact_silhouette else None
    styles,style_indices=surface_styles(base_color,brightness)
    dense=len(reference.object_triangles)>SMALL_MESH_FACES
    show_edges=settings.object_resolution_percent>=75
    groups=defaultdict(list)
    if settings.critical_layers_enabled:
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

    def paint(painter,opacity=1,outline=True):
        painter.setOpacity(opacity)
        if silhouette is not None and not silhouette.isEmpty():
            painter.fillPath(silhouette,silhouette_backing_color())
            painter.setClipPath(silhouette)
        for i,index in enumerate(order):
            if i%512==0:check_cancel(event)
            polygon=QPolygonF([QPointF(*p) for p in projected[index]])
            style=styles[style_indices[index]]
            if dense:draw_display_surface(painter,polygon,style,edges=show_edges)
            else:draw_surface(painter,polygon,base_color,brightness[index],style)
        for color,lines in groups.items():
            check_cancel(event)
            painter.setPen(cosmetic_pen(QColor.fromRgb(color),1.5));painter.drawLines(lines)
        if silhouette is not None and not silhouette.isEmpty():
            painter.setClipping(False)
            if outline and reliable_original_contours(reference):
                painter.strokePath(silhouette,cosmetic_pen(base_color.darker(125),1))
        check_cancel(event)

    if dense and vector and len(projected):
        return _raster_object_picture(projected,silhouette,frame,settings,paint,event,reliable_original_contours(reference))
    painter=QPainter(image)
    try:
        paint(painter,.28 if not vector and frame.highlight in {"object","all"} else 1)
    finally:painter.end()
    return image


def reliable_original_contours(reference):
    mesh=getattr(reference,"object_silhouette",None)
    return mesh is not None and mesh.source is reference.object_triangles and mesh.topology.reliable_contours


def original_silhouette_path(reference,frame,event=None):
    """Reuse the original contour across resolution changes and proxy/final views."""
    check_cancel(event)
    mesh=getattr(reference,"object_silhouette",None)
    if mesh is None or mesh.source is not reference.object_triangles:
        mesh=build_mesh_silhouette(reference.object_triangles,event)
    key=(frame.width,frame.height,frame.scale,frame.pan,frame.yaw,frame.pitch,
         frame.world_origin,frame.projected_center,frame.object_center,frame.object_rotation)
    with mesh.contour_lock:
        cached=mesh.contour_cache.get(key)
        if cached is not None:
            mesh.contour_cache.move_to_end(key)
            return QPainterPath(cached)
    path=_build_original_silhouette_path(reference,frame,mesh,event)
    check_cancel(event)
    with mesh.contour_lock:
        mesh.contour_cache[key]=QPainterPath(path)
        while len(mesh.contour_cache)>8 or sum(item.elementCount()*32 for item in mesh.contour_cache.values())>16*1024*1024:
            mesh.contour_cache.popitem(last=False)
    return path


def _build_original_silhouette_path(reference,frame,mesh,event=None):
    """Project exact contour edges using the same object rotation as the mesh."""
    if not mesh.topology.reliable_contours:
        # Triangle projection works for open and non-manifold edge input.
        # Equal screen winding produces a union without inventing a solid
        # enclosure, closing existing holes or joining separated components.
        projected,_=frame.project(rotate_object(reference.object_triangles,reference.silhouette.center_xy,
                                                frame.object_center,frame.object_rotation))
        path=QPainterPath();path.setFillRule(Qt.FillRule.WindingFill)
        for index,triangle in enumerate(projected):
            if index%512 == 0:check_cancel(event)
            if not np.isfinite(triangle).all():continue
            a,b=triangle[1]-triangle[0],triangle[2]-triangle[0]
            cross=a[0]*b[1]-a[1]*b[0]
            if cross == 0:continue
            if cross < 0:triangle=triangle[::-1]
            path.addPolygon(QPolygonF([QPointF(*point) for point in triangle]))
            path.closeSubpath()
        check_cancel(event)
        return path
    yaw,pitch,angle=map(math.radians,(frame.yaw,frame.pitch,frame.object_rotation))
    direction=(math.sin(yaw+angle)*math.cos(pitch),math.cos(yaw+angle)*math.cos(pitch),math.sin(pitch))
    edges=mesh.contour_edges(direction,event)
    indices=np.unique(edges)
    projected,_=frame.project(rotate_object(mesh.vertices[indices],reference.silhouette.center_xy,
                                           frame.object_center,frame.object_rotation))
    points=dict(zip(map(int,indices),projected))
    following=defaultdict(list)
    for start,end in edges:following[int(start)].append(int(end))
    path=QPainterPath()
    path.setFillRule(Qt.FillRule.WindingFill)
    count=0
    while following:
        start=next(iter(following));current=start
        path.moveTo(QPointF(*points[start]))
        while current in following:
            if count%512 == 0:check_cancel(event)
            destinations=following[current]
            destination=destinations.pop()
            if not destinations:del following[current]
            path.lineTo(QPointF(*points[destination]))
            count+=1;current=destination
            if current == start:
                path.closeSubpath()
                break
    return path


def render_silhouette_object(reference,frame,settings,event,image):
    """Draw complete original contours without a reduced mesh or triangle details."""
    painter=QPainter(image)
    try:
        if not isinstance(image,QPicture):
            painter.setOpacity(.28 if frame.highlight in {"object","all"} else 1)
        # In profile views, retain the former complete layer silhouettes and
        # their solid layer colors, including separate projected islands.
        if frame.pitch == 0 and settings.critical_layers_enabled and reference.silhouette is not None:
            paths=defaultdict(QPainterPath)
            bottom=0.
            for layer,section in zip(reference.context.layers,reference.silhouette.segments_xy):
                check_cancel(event)
                if len(section):
                    coordinates=np.empty((*section.shape[:-1],3))
                    coordinates[...,:2]=section
                    coordinates[...,2]=layer.z_mm
                    coordinates=rotate_object(coordinates,reference.silhouette.center_xy,
                                              frame.object_center,frame.object_rotation)
                    screens,_=frame.project(coordinates)
                    lower=screens[...,0].min(axis=1)
                    upper=screens[...,0].max(axis=1)
                    order=np.argsort(lower)
                    lower,upper=lower[order],np.maximum.accumulate(upper[order])
                    starts=np.r_[0,np.flatnonzero(lower[1:] > upper[:-1]+1e-9)+1]
                    ends=np.r_[starts[1:]-1,len(lower)-1]
                    heights,_=frame.project(np.array([(frame.object_center[0],frame.object_center[1],z)
                                                       for z in (bottom,layer.z_mm)]))
                    y1,y2=heights[:,1]
                    color=(LayerRangeCanvas.layer_color(settings.color_reference_time_s,layer.total_time_s,
                        settings.gradient_start_deficit_s,settings.gradient_full_deficit_s)
                        if settings.critical_layers_enabled else QColor("#429baa"))
                    for left,right in zip(lower[starts],upper[ends]):
                        paths[color.rgb()].addRect(QRectF(float(left),min(y1,y2),float(right-left),abs(y2-y1)))
                bottom=layer.z_mm
            for color,path in paths.items():
                path.setFillRule(Qt.FillRule.WindingFill)
                painter.fillPath(path,QColor.fromRgb(color))
        else:
            # Reuse adjacency from preparation. Only silhouette vertices are
            # projected and recorded, rather than thousands of filled faces.
            path=original_silhouette_path(reference,frame,event)
            painter.fillPath(path,QColor(LayerRangeCanvas.OBJECT_COLOR if settings.critical_layers_enabled else "#429baa"))
            if settings.critical_layers_enabled:
                for layer,section in zip(reference.context.layers,reference.silhouette.segments_xy):
                    check_cancel(event)
                    color=LayerRangeCanvas.layer_color(settings.color_reference_time_s,layer.total_time_s,
                        settings.gradient_start_deficit_s,settings.gradient_full_deficit_s)
                    if color == QColor(LayerRangeCanvas.OBJECT_COLOR) or not len(section):continue
                    coordinates=np.empty((*section.shape[:-1],3))
                    coordinates[...,:2]=section
                    coordinates[...,2]=layer.z_mm
                    screens,_=frame.project(rotate_object(coordinates,reference.silhouette.center_xy,
                                                          frame.object_center,frame.object_rotation))
                    painter.setPen(cosmetic_pen(color,1.5))
                    painter.drawLines([QLineF(QPointF(*a),QPointF(*b)) for a,b in screens])
        check_cancel(event)
    finally:
        painter.end()
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
            painter.setOpacity(.28 if frame.highlight in {"object","all"} else 1)
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
