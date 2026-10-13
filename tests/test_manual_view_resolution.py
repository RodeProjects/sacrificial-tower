import sys
import unittest
from pathlib import Path
from threading import Event
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
import trimesh
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from PySide6.QtGui import QColor
from cooling_tower.gui import manual_view_worker as rendering
from cooling_tower.gui.manual_view_worker import simplify_display_mesh,SpatialFrame
from cooling_tower.manual.geometry import OBJECT_RESOLUTION_STAGES,ManualSettings
from cooling_tower.preview import PreviewCancelled
from cooling_tower.preview.mesh_silhouette import build_mesh_silhouette


class ManualViewResolutionTests(unittest.TestCase):
    def test_mesh_backing_is_lighter_transparent_and_xray_applies_consistently(self):
        triangles=trimesh.creation.icosphere(subdivisions=2).triangles
        reference=SimpleNamespace(object_triangles=triangles,object_silhouette=build_mesh_silhouette(triangles),
            silhouette=SimpleNamespace(center_xy=(0,0),segments_xy=()),context=SimpleNamespace(layers=()))
        frame=SpatialFrame(240,240,90,(0,0),0,0,(0,0),(0,0),(0,0),37,"both",True)
        settings=replace(ManualSettings(),object_resolution_percent=1)
        with patch.object(rendering,"simplify_display_mesh",return_value=triangles[:0]):
            plain=rendering.render_spatial_object(reference,frame,settings,None)
            xray=rendering.render_spatial_object(reference,replace(frame,highlight="object"),settings,None)
        backing=plain.pixelColor(120,120)
        self.assertEqual(backing.alpha(),210)
        self.assertGreater(backing.lightness(),QColor("#429baa").lightness())
        self.assertAlmostEqual(xray.pixelColor(120,120).alpha()/backing.alpha(),.28,delta=.025)
        solid=rendering.render_spatial_object(reference,frame,replace(settings,object_resolution_percent=0),None)
        self.assertEqual(solid.pixelColor(120,120),QColor("#429baa"))

    def test_exact_silhouette_keeps_full_bounds_at_all_mesh_stages_and_rotations(self):
        triangles=trimesh.creation.icosphere(subdivisions=3).triangles.copy()
        triangles*=np.array((1.3,.7,1.1))
        triangles.setflags(write=False)
        reference=SimpleNamespace(object_triangles=triangles,object_silhouette=build_mesh_silhouette(triangles),
            silhouette=SimpleNamespace(center_xy=(0,0),segments_xy=()),context=SimpleNamespace(layers=()))
        def bounds(image):
            data=np.frombuffer(image.constBits(),dtype=np.uint8).reshape(image.height(),image.bytesPerLine()//4,4)
            ys,xs=np.nonzero(data[:,:,3])
            return np.array((xs.min(),ys.min(),xs.max(),ys.max()))
        for yaw,pitch in ((0,0),(90,0),(0,90),(0,-90),(-35,25),(72,-18)):
            previous=None
            for rotation in (0,37,90):
                frame=SpatialFrame(300,300,90,(0,0),yaw,pitch,(0,0),(0,0),(0,0),rotation,"both",True)
                full=rendering.render_spatial_object(reference,frame,replace(ManualSettings(),object_resolution_percent=0),None)
                expected=bounds(full)
                if previous is not None and pitch==0:self.assertFalse(np.array_equal(previous,expected))
                previous=expected
                for percent in OBJECT_RESOLUTION_STAGES[1:]:
                    image=rendering.render_spatial_object(reference,frame,replace(ManualSettings(),object_resolution_percent=percent),None)
                    np.testing.assert_allclose(bounds(image),expected,atol=1)
                    self.assertNotEqual(image.pixelColor(150,150),QColor("#429baa"))
        self.assertFalse(triangles.flags.writeable)

    def test_silhouette_clips_coarse_surfaces_out_of_holes_including_free_view(self):
        triangles=trimesh.creation.annulus(r_min=.4,r_max=1,height=1,sections=96).triangles
        reference=SimpleNamespace(object_triangles=triangles,object_silhouette=build_mesh_silhouette(triangles),
            silhouette=SimpleNamespace(center_xy=(0,0),segments_xy=()),context=SimpleNamespace(layers=()))
        frame=SpatialFrame(240,240,90,(0,0),0,90,(0,0),(0,0),(0,0),37,"both",True)
        settings=replace(ManualSettings(),object_resolution_percent=5)
        with patch.object(rendering,"simplify_display_mesh",return_value=trimesh.creation.box(extents=(2,2,1)).triangles):
            image=rendering.render_spatial_object(reference,frame,settings,None)
        self.assertEqual(image.pixelColor(120,120).alpha(),0)
        self.assertGreater(image.pixelColor(180,120).alpha(),0)
        free=replace(frame,pitch=25,yaw=-35)
        with patch.object(rendering,"original_silhouette_path",wraps=rendering.original_silhouette_path) as contour:
            rendering.render_spatial_object(reference,free,settings,None)
        contour.assert_called_once()

    def test_reused_styles_keep_identical_colors_edges_and_transparent_pixels(self):
        brightness=np.linspace(.86,1.14,5120)
        color=QColor("#429baa")
        styles,indices=rendering.surface_styles(color,brightness)
        self.assertLess(len(styles),200)
        for index,value in enumerate(brightness):
            fill,edge,node=styles[indices[index]]
            self.assertEqual(fill,rendering.shaded_color(color,value))
            self.assertEqual(edge.color(),fill.darker(125))
            self.assertEqual(node.color(),fill.darker(145))
            self.assertTrue(edge.isCosmetic())
            self.assertTrue(node.isCosmetic())
        reference=SimpleNamespace(object_triangles=trimesh.creation.icosphere(subdivisions=2).triangles,
            silhouette=SimpleNamespace(center_xy=(0,0),segments_xy=(np.array([[[-.5,0],[.5,0]]]),)),
            context=SimpleNamespace(layers=(SimpleNamespace(z_mm=.2,total_time_s=1),)))
        frame=SpatialFrame(240,240,90,(0,0),-35,25,(0,0),(0,0),(0,0),37,"both")
        original=rendering.draw_surface
        def legacy(painter,polygon,color,brightness,style=None):
            original(painter,polygon,color,brightness)
        for critical in (False,True):
            settings=replace(ManualSettings(),object_resolution_percent=100,critical_layers_enabled=critical)
            for highlight in ("both","object","all"):
                current=replace(frame,highlight=highlight)
                with patch.object(rendering,"draw_surface",side_effect=legacy):
                    expected=rendering.render_spatial_object(reference,current,settings,None)
                actual=rendering.render_spatial_object(reference,current,settings,None)
                self.assertEqual(actual,expected)

    def test_all_stages_reduce_complete_surfaces_without_mutating_source(self):
        source=trimesh.creation.icosphere(subdivisions=5).triangles.copy()
        original=source.copy();source.setflags(write=False)
        counts=[]
        for percent in OBJECT_RESOLUTION_STAGES[1:]:
            reduced=simplify_display_mesh(source,percent)
            counts.append(len(reduced))
            mesh=trimesh.Trimesh(vertices=reduced.reshape(-1,3),
                faces=np.arange(len(reduced)*3).reshape(-1,3),process=True)
            self.assertTrue(mesh.is_watertight)
            self.assertTrue(np.isfinite(reduced).all())
            np.testing.assert_allclose(reduced.min(axis=(0,1)),source.min(axis=(0,1)),atol=.042)
            np.testing.assert_allclose(reduced.max(axis=(0,1)),source.max(axis=(0,1)),atol=.042)
        self.assertEqual(counts,sorted(counts))
        self.assertLessEqual(counts[0],len(source)*.8)
        self.assertGreater(counts[0],len(source)*.25)
        np.testing.assert_array_equal(source,original)

    def test_small_or_degenerate_sources_and_cancelled_reduction(self):
        small=trimesh.creation.box().triangles
        self.assertIs(simplify_display_mesh(small,10),small)
        degenerate=np.zeros((100,3,3))
        self.assertIs(simplify_display_mesh(degenerate,50),degenerate)
        event=Event();event.set()
        with self.assertRaises(PreviewCancelled):
            simplify_display_mesh(trimesh.creation.icosphere(subdivisions=2).triangles,50,event)

    def test_zero_draws_exact_flat_contours_without_simplification_or_surface_details(self):
        triangles=trimesh.creation.icosphere(subdivisions=4).triangles.copy()
        original=triangles.copy();triangles.setflags(write=False)
        topology=build_mesh_silhouette(triangles)
        reference=SimpleNamespace(object_triangles=triangles,object_silhouette=topology,
            silhouette=SimpleNamespace(center_xy=(0,0),segments_xy=()),context=SimpleNamespace(layers=()))
        settings=replace(ManualSettings(),object_resolution_percent=0)
        for yaw,pitch,rotation in ((0,0,0),(-35,25,37),(90,90,0),(0,-90,180)):
            frame=SpatialFrame(240,240,90,(0,0),yaw,pitch,(0,0),(0,0),(0,0),rotation,"both")
            with patch.object(rendering,"simplify_display_mesh",side_effect=AssertionError("mesh reduction")),\
                 patch.object(rendering,"draw_surface",side_effect=AssertionError("mesh details")),\
                 patch.object(rendering,"build_mesh_silhouette",side_effect=AssertionError("topology rebuilt")):
                image=rendering.render_spatial_object(reference,frame,settings,None)
            self.assertEqual(image.pixelColor(120,120),QColor("#429baa"))
            self.assertEqual(image.pixelColor(5,5).alpha(),0)
            self.assertLess(len(topology.contour_edges((0,0,1))),len(triangles)//20)
        np.testing.assert_array_equal(triangles,original)
        self.assertFalse(topology.vertices.flags.writeable)
        event=Event();event.set()
        with self.assertRaises(PreviewCancelled):build_mesh_silhouette(triangles,event)

    def test_zero_silhouette_preserves_holes_in_full_resolution_top_view(self):
        triangles=trimesh.creation.annulus(r_min=.4,r_max=1,height=1,sections=96).triangles
        reference=SimpleNamespace(object_triangles=triangles,object_silhouette=build_mesh_silhouette(triangles),
            silhouette=SimpleNamespace(center_xy=(0,0),segments_xy=()),context=SimpleNamespace(layers=()))
        frame=SpatialFrame(240,240,90,(0,0),0,90,(0,0),(0,0),(0,0),0,"both")
        image=rendering.render_spatial_object(reference,frame,replace(ManualSettings(),object_resolution_percent=0),None)
        self.assertEqual(image.pixelColor(120,120).alpha(),0)
        self.assertEqual(image.pixelColor(180,120),QColor("#429baa"))

    def test_zero_profile_silhouette_keeps_disconnected_islands_and_layer_colors(self):
        pieces=[]
        for center in (-.75,.75):
            mesh=trimesh.creation.box(extents=(.5,.5,1));mesh.apply_translation((center,0,.5))
            pieces.append(mesh.triangles)
        triangles=np.concatenate(pieces)
        section=np.array([[[-1,0],[-.5,0]],[[.5,0],[1,0]]])
        reference=SimpleNamespace(object_triangles=triangles,object_silhouette=build_mesh_silhouette(triangles),
            silhouette=SimpleNamespace(center_xy=(0,0),segments_xy=(section,section)),
            context=SimpleNamespace(layers=(SimpleNamespace(z_mm=.5,total_time_s=20),SimpleNamespace(z_mm=1,total_time_s=5))))
        frame=SpatialFrame(240,240,60,(0,0),0,0,(0,0),(0,0),(0,0),0,"both")
        settings=replace(ManualSettings(),object_resolution_percent=0,critical_layers_enabled=True)
        image=rendering.render_spatial_object(reference,frame,settings,None)
        self.assertEqual(image.pixelColor(165,105),QColor(rendering.LayerRangeCanvas.OBJECT_COLOR))
        self.assertEqual(image.pixelColor(165,75),QColor(rendering.LayerRangeCanvas.CRITICAL_COLOR))
        self.assertEqual(image.pixelColor(120,105).alpha(),0)

    def test_non_manifold_silhouette_matches_union_without_inventing_connections_or_clipping_faces(self):
        # Open, irregularly wound shells, with one overused edge. The source
        # triangle projection is the reference even when closed contours fail.
        pieces=[]
        for x in (-1,1):
            mesh=trimesh.creation.box(extents=(.6,.6,1))
            mesh.apply_translation((x,0,0))
            triangles=mesh.triangles.copy()[1:]
            triangles[::2]=triangles[::2,::-1]
            pieces.extend((triangles,triangles[:1]))
        triangles=np.concatenate(pieces)
        topology=build_mesh_silhouette(triangles)
        self.assertFalse(topology.topology.reliable_contours)
        reference=SimpleNamespace(object_triangles=triangles,object_silhouette=topology,
            silhouette=SimpleNamespace(center_xy=(0,0),segments_xy=()),context=SimpleNamespace(layers=()))
        for yaw,pitch in ((0,0),(-35,25),(0,90)):
            frame=SpatialFrame(300,240,65,(0,0),yaw,pitch,(0,0),(0,0),(0,0),0,"both",True)
            silhouette=rendering.render_spatial_object(reference,frame,replace(ManualSettings(),object_resolution_percent=0),None)
            image=rendering.render_spatial_object(reference,frame,replace(ManualSettings(),object_resolution_percent=1),None)
            for original,result in zip(np.frombuffer(silhouette.constBits(),dtype=np.uint8).reshape(-1,4),
                                       np.frombuffer(image.constBits(),dtype=np.uint8).reshape(-1,4)):
                if original[3]:self.assertGreater(result[3],0)
            self.assertEqual(image.pixelColor(150,120).alpha(),0)
        np.testing.assert_array_equal(triangles,np.concatenate(pieces))
