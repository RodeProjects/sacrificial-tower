"""Regressions for the supplied detailed models and bounded GUI replay work."""
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import trimesh
from PySide6.QtGui import QImage,QPainter

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from cooling_tower.gui import manual_view_worker as rendering
from cooling_tower.gui.manual_view_worker import SpatialFrame,RasterObjectPicture
from cooling_tower.manual.geometry import ManualSettings,OBJECT_RESOLUTION_STAGES
from cooling_tower.preview.mesh_silhouette import build_mesh_silhouette


class ManualViewPerformanceTests(unittest.TestCase):
    def reference(self,name):
        path=ROOT/"input"/name
        if not path.is_file():self.skipTest("Optional local regression model is absent: "+name)
        triangles=trimesh.load(path,file_type="stl",force="mesh",process=False).triangles.copy()
        triangles[:,:,2]-=triangles[:,:,2].min()
        triangles.setflags(write=False)
        mesh=build_mesh_silhouette(triangles)
        center=tuple(((triangles.min(axis=(0,1))+triangles.max(axis=(0,1)))/2)[:2])
        reference=SimpleNamespace(object_triangles=triangles,object_silhouette=mesh,
            silhouette=SimpleNamespace(center_xy=center,segments_xy=()),context=SimpleNamespace(layers=()))
        frame=SpatialFrame(0,0,1,(0,0),0,0,center,(0,0),center,0,"both",True)
        return reference,frame

    def check_model(self,name):
        reference,frame=self.reference(name)
        triangles=reference.object_triangles
        mesh=reference.object_silhouette
        self.assertTrue(mesh.topology.reliable_contours)
        topology=mesh.topology
        for stage in OBJECT_RESOLUTION_STAGES[1:]:
            result=rendering.simplify_display_mesh(triangles,stage,topology=topology)
            self.assertLessEqual(len(result),len(triangles)*.8,(name,stage,"Unchanged fallback would regress performance"))
            checked=build_mesh_silhouette(result).topology
            self.assertEqual(len(checked.vertices)-len(checked.edges)+len(checked.faces),
                             len(topology.vertices)-len(topology.edges)+len(topology.faces))
            np.testing.assert_array_equal(checked.vertices[checked.singular_vertices],
                                          topology.vertices[topology.singular_vertices])
        settings=replace(ManualSettings(),object_resolution_percent=0)
        # Pinched but edge-consistent models must use the fast contour path.
        with patch.object(rendering,"rotate_object",wraps=rendering.rotate_object) as rotate:
            silhouette=rendering.render_spatial_object(reference,frame,settings,None,vector=True)
        self.assertTrue(rotate.call_args_list)
        self.assertTrue(all(call.args[0].ndim==2 for call in rotate.call_args_list))
        self.assertLess(silhouette.size(),300_000)
        pictures=[]
        with patch.object(rendering,"_build_original_silhouette_path",side_effect=AssertionError("contour rebuilt")),\
             patch.object(rendering,"draw_surface",side_effect=AssertionError("per-vertex details in dense mesh")):
            for stage in (1,100):
                picture=rendering.render_spatial_object(reference,frame,replace(settings,object_resolution_percent=stage),None,vector=True)
                self.assertIsInstance(picture,RasterObjectPicture)
                self.assertIsNotNone(picture.xray_picture)
                self.assertLess(picture.size()+picture.xray_picture.size(),4*1024*1024)
                pictures.append(picture)
        self.assertLess(max(pictures[0].raster_size),550)
        self.assertGreater(max(pictures[1].raster_size),1200)
        # Raster alpha must preserve projected openings and separated regions;
        # vector clipping keeps the full original outline at viewport precision.
        images=[]
        for picture in (silhouette,*pictures):
            image=QImage(600,900,QImage.Format.Format_ARGB32_Premultiplied);image.fill(0)
            painter=QPainter(image)
            painter.translate(300,820);painter.scale(700/triangles[:,:,2].max(),700/triangles[:,:,2].max())
            painter.drawPicture(0,0,picture);painter.end()
            images.append(np.frombuffer(image.constBits(),dtype=np.uint8).reshape(image.height(),image.bytesPerLine()//4,4)[:,:,3].copy())
        original=images[0]>0
        for alpha in images[1:]:
            overlap=(alpha>0)&original
            self.assertGreater(overlap.sum()/original.sum(),.98)
        self.assertFalse(triangles.flags.writeable)

    def test_full_detailed_model_has_effective_budgets_and_fast_silhouette(self):
        self.check_model("Test-STL (manifold).stl")

    def test_shortened_model_has_effective_budgets_and_fast_silhouette(self):
        self.check_model("Test-STL (manifold) gekürzt.stl")

    def test_vase_model_has_effective_budgets_and_fast_silhouette(self):
        self.check_model("Test-STL Vase (manifold).stl")

    def test_dense_xray_keeps_per_surface_opacity_instead_of_flat_image_opacity(self):
        triangles=trimesh.creation.icosphere(subdivisions=5).triangles.copy()
        reference=SimpleNamespace(object_triangles=triangles,object_silhouette=build_mesh_silhouette(triangles),
            silhouette=SimpleNamespace(center_xy=(0,0),segments_xy=()),context=SimpleNamespace(layers=()))
        frame=SpatialFrame(0,0,1,(0,0),0,0,(0,0),(0,0),(0,0),0,"both",True)
        picture=rendering.render_spatial_object(reference,frame,replace(ManualSettings(),object_resolution_percent=1),None,vector=True)
        image=QImage(200,200,QImage.Format.Format_ARGB32_Premultiplied);image.fill(0)
        painter=QPainter(image);painter.translate(100,100);painter.scale(70,70)
        painter.drawPicture(0,0,picture.xray_picture);painter.end()
        self.assertGreater(image.pixelColor(100,100).alpha(),100)
        self.assertLess(image.pixelColor(100,100).alpha(),200)

    def test_free_view_keeps_openings_and_separated_objects_even_with_open_edges(self):
        ring=trimesh.creation.torus(major_radius=1,minor_radius=.25,
                                  major_sections=128,minor_sections=64).triangles.copy()
        sphere=trimesh.creation.icosphere(subdivisions=4)
        sphere.apply_translation((5,0,0))
        frame=SpatialFrame(0,0,1,(0,0),23,62,(0,0),(0,0),(0,0),31,"both",True)
        for open_edges in (False,True):
            source=np.concatenate((ring[:-1] if open_edges else ring,sphere.triangles))
            original=source.copy();source.setflags(write=False)
            mesh=build_mesh_silhouette(source)
            reference=SimpleNamespace(object_triangles=source,object_silhouette=mesh,
                silhouette=SimpleNamespace(center_xy=(0,0),segments_xy=()),context=SimpleNamespace(layers=()))
            self.assertEqual(mesh.topology.reliable_contours,not open_edges)
            for stage in (0,1,100):
                with self.subTest(open_edges=open_edges,stage=stage):
                    picture=rendering.render_spatial_object(reference,frame,
                        replace(ManualSettings(),object_resolution_percent=stage),None,vector=True)
                    if stage:self.assertIsInstance(picture,RasterObjectPicture)
                    image=QImage(900,600,QImage.Format.Format_ARGB32_Premultiplied);image.fill(0)
                    painter=QPainter(image);painter.translate(250,110);painter.scale(85,85)
                    painter.drawPicture(0,0,picture);painter.end()
                    projected,_=frame.project(rendering.rotate_object(
                        np.array(((0,0,0),(2.5,0,0),(1,0,0),(5,0,0))),
                        (0,0),(0,0),31))
                    alpha=[image.pixelColor(round(250+85*x),round(110+85*y)).alpha()
                           for x,y in projected]
                    self.assertEqual(alpha[:2],[0,0],"Opening and gap must remain empty")
                    self.assertGreater(min(alpha[2:]),200,"Both separate surfaces must remain visible")
            np.testing.assert_array_equal(source,original)


if __name__=="__main__":unittest.main()
