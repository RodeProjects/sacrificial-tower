"""Prepared original-object material: recolor without projecting source geometry.

Profile rasters blend already shaded endpoint palettes per original layer.
Spatial views reuse their shaded surface and only recolor projected layer paths.
All buffers are owned and immutable after worker preparation.
"""
from collections import defaultdict

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor,QImage,QLinearGradient,QPainter,QPen

from cooling_tower.gui.design_tokens import ORIGINAL_OBJECT_BLUE
from cooling_tower.gui.widgets.layer_range_canvas import LayerRangeCanvas


def _color(settings,time):
    return LayerRangeCanvas.layer_time_color(settings.color_reference_time_s,settings.color_red_time_s,time)


def _line_pen(color,width):
    pen=QPen(color,width)
    pen.setCosmetic(True)
    return pen


def draw_object_picture(painter,picture,opacity):
    """Replay cached recolors directly, without QPicture image serialization."""
    xray=getattr(picture,"xray_picture",None)
    use_xray=xray is not None and opacity==.28
    painter.setOpacity(1 if use_xray else opacity)
    images=getattr(picture,"material_images",None)
    if images is not None:
        material=picture.material
        painter.save()
        if material.path is not None and not material.path.isEmpty():painter.setClipPath(material.path)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(material.bounds,images[1 if use_xray else 0])
        painter.restore()
    painter.drawPicture(0,0,xray if use_xray else picture)


def object_picture_cache_size(pictures):
    materials={}
    size=0
    for item in pictures:
        size+=item.size()+(item.xray_picture.size() if getattr(item,"xray_picture",None) is not None else 0)
        size+=sum(image.sizeInBytes() for image in getattr(item,"material_images",()))
        material=getattr(item,"material",None)
        if material is not None:materials[id(material)]=material
    return size+sum(material.storage_size() for material in materials.values())


class ObjectMaterial:
    def __init__(self,picture_type,*,path,layers,paths=(),fill=False,
                 neutral_color=ORIGINAL_OBJECT_BLUE,outline=False,line_width=1.5):
        self.picture_type=picture_type
        self.path=path
        self.layers=tuple(layers)
        self.paths=tuple(paths)
        self.fill=fill
        self.neutral_color=neutral_color
        self.outline=outline
        self.line_width=line_width
        self.palettes={}
        self.bounds=None
        self.row_layers=None
        self.profile_axis=None

    def add_palette(self,name,images,bounds):
        arrays=[]
        for image in images:
            array=np.frombuffer(image.constBits(),dtype=np.uint8).reshape(
                image.height(),image.bytesPerLine()//4,4)[:,:image.width()].copy()
            array.setflags(write=False)
            arrays.append(array)
        self.palettes[name]=tuple(arrays)
        self.bounds=bounds

    def set_profile_axis(self,y0,y1,height):
        self.profile_axis=(y0,y1,height)
        if self.bounds is None:return
        rows=next(iter(self.palettes.values()))[0].shape[0]
        y=self.bounds.top()+(np.arange(rows)+.5)*self.bounds.height()/rows
        z=(y-y0)*height/(y1-y0)
        self.row_layers=np.clip(np.searchsorted([layer.z_mm for layer in self.layers],z),0,len(self.layers)-1)

    def storage_size(self):
        return (sum(array.nbytes for pair in self.palettes.values() for array in pair)
                +sum(path.elementCount()*32 for _,path in self.paths)
                +(self.path.elementCount()*32 if self.path is not None else 0))

    def _raster(self,settings,index):
        if not settings.critical_layers_enabled:return self.palettes["neutral"][index]
        green=self.palettes["green"][index]
        if self.row_layers is None:return green
        times=np.asarray([layer.total_time_s for layer in self.layers])
        if settings.color_red_time_s==settings.color_reference_time_s:
            ratio=(times<settings.color_reference_time_s).astype(np.float32)
        else:
            ratio=np.clip((times-settings.color_reference_time_s)/
                          (settings.color_red_time_s-settings.color_reference_time_s),0,1)
        ratio=ratio[self.row_layers].astype(np.float32)[:,None]
        red=self.palettes["red"][index]
        result=np.empty_like(green)
        for channel in range(3):
            delta=red[:,:,channel].astype(np.int16)-green[:,:,channel]
            result[:,:,channel]=np.rint(green[:,:,channel]+delta*ratio).astype(np.uint8)
        result[:,:,3]=green[:,:,3]
        return result

    def _outline_color(self,settings):
        if not settings.critical_layers_enabled:return QColor(self.neutral_color).darker(125)
        if not self.profile_axis:return QColor(LayerRangeCanvas.OBJECT_COLOR).darker(125)
        y0,y1,height=self.profile_axis
        gradient=QLinearGradient(0,y0,0,y1)
        previous=None
        for index,layer in enumerate(self.layers):
            color=_color(settings,layer.total_time_s).darker(125)
            if color != previous:
                boundary=self.layers[index-1].z_mm/height if index else 0.
                if index:
                    epsilon=min(1e-7,(layer.z_mm-self.layers[index-1].z_mm)/height/4)
                    gradient.setColorAt(max(0,boundary-epsilon),previous)
                gradient.setColorAt(boundary,color)
                previous=color
        if previous is not None:gradient.setColorAt(1,previous)
        return gradient

    def recolor(self,settings,*,serialize=True):
        result=self.picture_type()
        result.material=self
        images=[]
        if self.palettes:
            height,width=next(iter(self.palettes.values()))[0].shape[:2]
            result.raster_size=(width,height)
        for index,opacity in enumerate((1.,.28)):
            picture=result if index==0 else self.picture_type()
            painter=QPainter(picture)
            try:
                if self.path is not None and not self.path.isEmpty():painter.setClipPath(self.path)
                if self.palettes:
                    array=self._raster(settings,index)
                    image=QImage(array.data,array.shape[1],array.shape[0],array.strides[0],
                                 QImage.Format.Format_ARGB32_Premultiplied).copy()
                    if serialize:
                        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                        painter.drawImage(self.bounds,image)
                    else:images.append(image)
                elif self.path is not None and not self.path.isEmpty() and (not self.fill or not settings.critical_layers_enabled):
                    painter.setOpacity(opacity)
                    painter.fillPath(self.path,QColor(LayerRangeCanvas.OBJECT_COLOR if settings.critical_layers_enabled else self.neutral_color))
                painter.setOpacity(opacity)
                groups=defaultdict(list)
                for time,path in self.paths:
                    surface=self.palettes or self.path is not None
                    if surface and not settings.critical_layers_enabled:continue
                    color=_color(settings,time) if settings.critical_layers_enabled else QColor(self.neutral_color)
                    if surface and not self.fill and color==QColor(LayerRangeCanvas.OBJECT_COLOR):continue
                    groups[color.rgba()].append(path)
                for rgba,paths in groups.items():
                    color=QColor.fromRgba(rgba)
                    if not self.fill:painter.setPen(_line_pen(color,self.line_width))
                    for path in paths:
                        if self.fill:painter.fillPath(path,color)
                        else:painter.drawPath(path)
                painter.setClipping(False)
                if self.outline and self.path is not None and not self.path.isEmpty():
                    painter.strokePath(self.path,_line_pen(self._outline_color(settings),1))
            finally:painter.end()
            if index:result.xray_picture=picture
        if images:result.material_images=tuple(images)
        return result
