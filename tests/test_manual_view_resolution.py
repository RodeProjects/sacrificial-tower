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


class ManualViewResolutionTests(unittest.TestCase):
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
            for highlight in ("both","object"):
                current=replace(frame,highlight=highlight)
                with patch.object(rendering,"draw_surface",side_effect=legacy):
                    expected=rendering.render_spatial_object(reference,current,settings,None)
                actual=rendering.render_spatial_object(reference,current,settings,None)
                self.assertEqual(actual,expected)

    def test_all_stages_reduce_complete_surfaces_without_mutating_source(self):
        source=trimesh.creation.icosphere(subdivisions=4).triangles.copy()
        original=source.copy();source.setflags(write=False)
        counts=[]
        for percent in OBJECT_RESOLUTION_STAGES:
            reduced=simplify_display_mesh(source,percent)
            counts.append(len(reduced))
            mesh=trimesh.Trimesh(vertices=reduced.reshape(-1,3),
                faces=np.arange(len(reduced)*3).reshape(-1,3),process=True)
            self.assertTrue(mesh.is_watertight)
            self.assertTrue(np.isfinite(reduced).all())
            tolerance=.3 if percent < 5 else .15
            np.testing.assert_allclose(reduced.min(axis=(0,1)),source.min(axis=(0,1)),atol=tolerance)
            np.testing.assert_allclose(reduced.max(axis=(0,1)),source.max(axis=(0,1)),atol=tolerance)
        self.assertEqual(counts,sorted(counts))
        self.assertLess(counts[7],len(source)*.6)
        self.assertLess(counts[0],len(source)*.15)
        self.assertIs(simplify_display_mesh(source,100),source)
        np.testing.assert_array_equal(source,original)

    def test_small_or_degenerate_sources_and_cancelled_reduction(self):
        small=trimesh.creation.box().triangles
        self.assertIs(simplify_display_mesh(small,10),small)
        degenerate=np.zeros((100,3,3))
        self.assertIs(simplify_display_mesh(degenerate,50),degenerate)
        event=Event();event.set()
        with self.assertRaises(PreviewCancelled):
            simplify_display_mesh(trimesh.creation.icosphere(subdivisions=2).triangles,50,event)
