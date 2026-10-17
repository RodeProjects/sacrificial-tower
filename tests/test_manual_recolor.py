"""Color-only edits reuse immutable geometry, lighting and projected paths."""
import os
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import trimesh
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from PySide6.QtGui import QImage,QPainter
from cooling_tower.gui import manual_view_worker as rendering
from cooling_tower.gui.object_material import draw_object_picture,object_picture_cache_size
from cooling_tower.manual.geometry import ManualSettings
from cooling_tower.preview.mesh_silhouette import build_mesh_silhouette


class RecolorMaterialTests(unittest.TestCase):
    def reference(self):
        triangles=trimesh.creation.box(extents=(2,2,12)).triangles.copy()
        triangles[:,:,2]+=6
        triangles.setflags(write=False)
        layers=tuple(SimpleNamespace(z_mm=z,total_time_s=time) for z,time in ((4,6),(8,8),(12,10)))
        section=np.array([[[-1,-1],[1,-1]],[[1,-1],[1,1]],[[1,1],[-1,1]],[[-1,1],[-1,-1]]])
        reference=SimpleNamespace(object_triangles=triangles,object_silhouette=build_mesh_silhouette(triangles),
            silhouette=SimpleNamespace(center_xy=(0,0),segments_xy=(section,)*3),
            context=SimpleNamespace(layers=layers))
        frame=rendering.SpatialFrame(0,0,1,(0,0),0,0,(0,0),(0,0),(0,0),0,"both",True)
        return reference,frame

    def image(self,picture,opacity=1):
        image=QImage(120,280,QImage.Format.Format_ARGB32_Premultiplied);image.fill(0)
        painter=QPainter(image);painter.translate(60,260);painter.scale(20,20)
        draw_object_picture(painter,picture,opacity)
        painter.end()
        return image

    def assert_same_display(self,first,second):
        arrays=[np.frombuffer(image.constBits(),dtype=np.uint8).reshape(280,120,4).copy()
                for image in (first,second)]
        # QPicture serializes transform coordinates; direct replay can round
        # edge pixels by one or two channel levels at fractional image bounds.
        self.assertLessEqual(np.abs(arrays[0].astype(int)-arrays[1]).max(),2)
        np.testing.assert_array_equal(arrays[0][:,:,3]>0,arrays[1][:,:,3]>0)

    def test_profile_endpoints_transition_neutral_and_xray_reuse_shading(self):
        reference,frame=self.reference()
        settings=replace(ManualSettings(),critical_layers_enabled=True)
        initial=rendering.render_spatial_object(reference,frame,settings,None,vector=True)
        material=initial.material
        original=reference.object_triangles.copy()
        with patch.object(rendering,"simplify_display_mesh",side_effect=AssertionError("mesh rebuilt")), \
             patch.object(rendering.SpatialFrame,"project",side_effect=AssertionError("projected again")), \
             patch.object(rendering,"draw_surface",side_effect=AssertionError("faces redrawn")):
            for enabled,target,deficit in ((True,10,4),(True,12,2),(False,10,4),(True,10,4)):
                current=replace(settings,critical_layers_enabled=enabled,
                    color_reference_time_s=target,color_deficit_time_s=deficit)
                fast=material.recolor(current,serialize=False)
                serialized=material.recolor(current)
                for opacity in (1,.28):
                    self.assert_same_display(self.image(fast,opacity),self.image(serialized,opacity))
                self.assertIs(fast.material,material)
        image=self.image(initial)
        red,middle,green=[image.pixelColor(60,260-20*z) for z in (2,6,10)]
        self.assertGreater(red.red(),red.green())
        self.assertGreater(green.green(),green.red())
        self.assertTrue(red.red()>middle.red()>green.red())
        self.assertTrue(red.green()<middle.green()<green.green())
        np.testing.assert_array_equal(reference.object_triangles,original)
        self.assertFalse(reference.object_triangles.flags.writeable)
        self.assertTrue(all(not array.flags.writeable for pair in material.palettes.values() for array in pair))

    def test_hard_boundary_recolors_cached_raster_without_division_or_geometry_work(self):
        reference,frame=self.reference()
        settings=replace(ManualSettings(),critical_layers_enabled=True)
        initial=rendering.render_spatial_object(reference,frame,settings,None,vector=True)
        for threshold in (8,10):
            current=replace(settings,color_reference_time_s=threshold,color_deficit_time_s=0)
            with np.errstate(all="raise"), \
                 patch.object(rendering.SpatialFrame,"project",side_effect=AssertionError("projected again")):
                fast=initial.material.recolor(current,serialize=False)
                serialized=initial.material.recolor(current)
            expected=rendering.render_spatial_object(reference,frame,current,None,vector=True)
            self.assert_same_display(self.image(fast),self.image(expected))
            self.assert_same_display(self.image(serialized),self.image(expected))
            self.assertIs(fast.material,initial.material)
        current=replace(settings,color_reference_time_s=8,color_deficit_time_s=0)
        image=self.image(initial.material.recolor(current,serialize=False))
        red,at_boundary,above=[image.pixelColor(60,260-20*z) for z in (2,6,10)]
        self.assertGreater(red.red(),red.green())
        self.assertGreater(at_boundary.green(),at_boundary.red())
        self.assertGreater(above.green(),above.red())

    def test_silhouettes_and_spatial_views_keep_preprojected_paths(self):
        reference,frame=self.reference()
        settings=replace(ManualSettings(),critical_layers_enabled=True)
        for pitch in (0,25,90,-90):
            for resolution in (0,75):
                with self.subTest(pitch=pitch,resolution=resolution):
                    picture=rendering.render_spatial_object(reference,replace(frame,pitch=pitch),
                        replace(settings,object_resolution_percent=resolution),None,vector=True)
                    paths=picture.material.paths
                    with patch.object(rendering.SpatialFrame,"project",side_effect=AssertionError("projected again")):
                        changed=picture.material.recolor(replace(settings,color_reference_time_s=12),serialize=False)
                    self.assertIs(changed.material.paths,paths)
                    expected=rendering.render_spatial_object(reference,replace(frame,pitch=pitch),
                        replace(settings,object_resolution_percent=resolution,color_reference_time_s=12),None,vector=True)
                    self.assert_same_display(self.image(changed),self.image(expected))

    def test_gcode_paths_recolor_without_reading_source_again(self):
        reference,frame=self.reference()
        reference.object_triangles=None
        reference.silhouette=None
        def point(x,y,z):return SimpleNamespace(x=x,y=y,z=z)
        reference.source_data=SimpleNamespace(object_segments=tuple(
            SimpleNamespace(start=point(-1,0,z),end=point(1,0,z)) for z in (4,8,12)))
        settings=replace(ManualSettings(),critical_layers_enabled=True)
        picture=rendering.render_spatial_object(reference,frame,settings,None,vector=True)
        reference.source_data=None
        with patch.object(rendering.SpatialFrame,"project",side_effect=AssertionError("projected again")):
            fast=picture.material.recolor(replace(settings,color_reference_time_s=12),serialize=False)
        self.assertEqual(len(fast.material.paths),3)
        self.assertNotEqual(self.image(fast),self.image(picture))

    def test_shared_material_buffers_count_once_in_cache_budget(self):
        reference,frame=self.reference()
        settings=ManualSettings()
        initial=rendering.render_spatial_object(reference,frame,settings,None,vector=True)
        other=initial.material.recolor(replace(settings,critical_layers_enabled=True),serialize=False)
        expected=(initial.material.storage_size()+initial.size()+initial.xray_picture.size()+
            other.size()+other.xray_picture.size()+sum(image.sizeInBytes() for image in other.material_images))
        self.assertEqual(object_picture_cache_size((initial,other)),expected)


if __name__=="__main__":unittest.main()
