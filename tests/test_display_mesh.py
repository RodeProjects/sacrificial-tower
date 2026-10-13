import sys
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

import numpy as np
import trimesh

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from cooling_tower.preview import display_mesh as display
from cooling_tower.preview import PreviewCancelled


class DisplayMeshTests(unittest.TestCase):
    def sphere(self,center=(0,0,0),subdivisions=5):
        mesh=trimesh.creation.icosphere(subdivisions=subdivisions)
        mesh.apply_translation(center)
        triangles=mesh.triangles.copy();triangles.setflags(write=False)
        return triangles

    def test_low_polygon_and_thin_objects_remain_exact_at_every_positive_stage(self):
        small=self.sphere(subdivisions=3)
        thin=self.sphere().copy();thin[:,:,2]*=.001
        for stage in (1,5,15,50,100):
            for source in (small,thin):
                self.assertIs(display.simplify_display_mesh(source,stage),source)

    def test_quality_preference_reduces_dense_sources_with_bounded_error_and_caches_results(self):
        source=self.sphere()
        topology=display.build_mesh_topology(source)
        low=display.simplify_display_mesh(source,1,topology=topology)
        self.assertLessEqual(len(low),len(source)*.8)
        checked=display.build_mesh_topology(low)
        self.assertTrue(checked.reliable_contours)
        self.assertEqual(len(checked.safe_components),1)
        self.assertGreater(np.linalg.norm(checked.vertices,axis=1).min(),.99)
        high=display.simplify_display_mesh(source,100,topology=topology)
        self.assertGreaterEqual(len(high),len(low))
        with patch.object(display,"_reduce_component",side_effect=AssertionError("repeated reduction")):
            self.assertIs(display.simplify_display_mesh(source,1,topology=topology),low)
            self.assertIs(display.simplify_display_mesh(source,100,topology=topology),high)
        for stage in (5,10,15,25,50,75):display.simplify_display_mesh(source,stage,topology=topology)
        self.assertLessEqual(len(topology._cache),8)
        self.assertFalse(source.flags.writeable)
        self.assertFalse(low.flags.writeable)

    def test_non_manifold_open_duplicate_and_inconsistently_wound_sources_remain_verbatim(self):
        source=self.sphere()
        reversed_face=source.copy();reversed_face[0]=reversed_face[0,::-1]
        for bad in (source[:-1],np.concatenate((source,source[:1])),reversed_face):
            before=bad.copy()
            topology=display.build_mesh_topology(bad)
            self.assertFalse(topology.reliable_contours)
            for stage in (1,15,100):
                self.assertIs(display.simplify_display_mesh(bad,stage,topology=topology),bad)
            np.testing.assert_array_equal(bad,before)

    def test_closed_pinched_vertex_is_detected_even_with_two_faces_per_edge(self):
        source=np.concatenate((self.sphere(subdivisions=2),self.sphere((2,0,0),subdivisions=2)))
        topology=display.build_mesh_topology(source)
        self.assertTrue((topology.counts==2).all())
        self.assertEqual(len(topology.safe_components),1)
        self.assertFalse(topology.manifold)
        self.assertTrue(topology.reliable_contours)

    def test_pinched_neighborhoods_remain_exact_while_dense_surfaces_reduce(self):
        source=np.concatenate((self.sphere(),self.sphere((2,0,0))))
        original=display.build_mesh_topology(source)
        result=display.simplify_display_mesh(source,1,topology=original)
        checked=display.build_mesh_topology(result)
        self.assertLess(len(result),len(source)*.8)
        self.assertTrue(checked.reliable_contours)
        self.assertFalse(checked.manifold)
        np.testing.assert_array_equal(checked.vertices[checked.singular_vertices],
                                      original.vertices[original.singular_vertices])
        pin=np.array((1,0,0))
        incident=source[np.any(np.all(source==pin,axis=2),axis=1)]
        output={tuple(face.ravel()) for face in result}
        self.assertTrue(all(tuple(face.ravel()) in output for face in incident))

    def test_separated_objects_keep_count_gap_and_small_component(self):
        large=self.sphere((-2,0,0))
        other=self.sphere((2,0,0))
        small=trimesh.creation.box(extents=(.1,.1,.1));small.apply_translation((0,0,3))
        source=np.concatenate((large,other,small.triangles))
        original=source.copy()
        result=display.simplify_display_mesh(source,1)
        topology=display.build_mesh_topology(result)
        self.assertEqual(len(topology.safe_components),3)
        self.assertTrue(topology.reliable_contours)
        self.assertLess(len(result),len(source))
        bounds=sorted(topology.bounds,key=lambda row:row[0,0])
        self.assertLessEqual(bounds[0][1,0],-1)
        self.assertGreaterEqual(bounds[-1][0,0],1)
        small_faces=result[topology.face_components==np.argmax(topology.bounds[:,0,2])]
        self.assertEqual({tuple(row.ravel()) for row in small_faces},{tuple(row.ravel()) for row in small.triangles})
        np.testing.assert_array_equal(source,original)

    def test_close_and_nested_shells_use_original_when_gap_cannot_safely_allow_reduction(self):
        source=np.concatenate((self.sphere(),self.sphere((2.001,0,0))))
        self.assertIs(display.simplify_display_mesh(source,1),source)
        outer=self.sphere();inner=outer*.8
        source=np.concatenate((outer,inner))
        self.assertIs(display.simplify_display_mesh(source,1),source)

    def test_unsafe_component_remains_exact_while_separate_safe_component_reduces(self):
        unsafe=self.sphere((-2,0,0))[:-1]
        safe=self.sphere((2,0,0))
        source=np.concatenate((unsafe,safe))
        result=display.simplify_display_mesh(source,1)
        self.assertLess(len(result),len(source))
        left=result[result[:,:,0].max(axis=1)<0]
        np.testing.assert_array_equal(left,unsafe)

    def test_cancelled_calls_do_not_publish_results_or_return_cached_data(self):
        source=self.sphere();topology=display.build_mesh_topology(source)
        display.simplify_display_mesh(source,1,topology=topology)
        event=Event();event.set()
        with self.assertRaises(PreviewCancelled):display.simplify_display_mesh(source,1,event,topology=topology)
        with self.assertRaises(PreviewCancelled):display.build_mesh_topology(source,event)
        event.clear()
        original=display._reduce_component
        def cancelled(*args,**kwargs):
            event.set()
            return original(*args,**kwargs)
        with patch.object(display,"_reduce_component",side_effect=cancelled):
            with self.assertRaises(PreviewCancelled):display.simplify_display_mesh(source,15,event,topology=topology)
        self.assertNotIn(15,topology._cache)

    def test_smooth_ring_keeps_its_opening_and_genus_after_automatic_reduction(self):
        mesh=trimesh.creation.torus(major_radius=1,minor_radius=.25,major_sections=128,minor_sections=64)
        source=mesh.triangles.copy()
        result=display.simplify_display_mesh(source,1)
        topology=display.build_mesh_topology(result)
        self.assertTrue(topology.reliable_contours)
        self.assertEqual(len(topology.safe_components),1)
        self.assertEqual(len(topology.vertices)-len(topology.edges)+len(topology.faces),0)
        self.assertGreater(np.linalg.norm(topology.vertices[:,:2],axis=1).min(),.72)

    def test_dense_sharp_box_keeps_original_corners_and_extents(self):
        mesh=trimesh.creation.box(extents=(2,2,2))
        vertices,faces=mesh.vertices,mesh.faces
        for _ in range(4):vertices,faces=trimesh.remesh.subdivide(vertices,faces)
        source=vertices[faces]
        result=display.simplify_display_mesh(source,1)
        topology=display.build_mesh_topology(result)
        self.assertTrue(topology.reliable_contours)
        for corner in mesh.vertices:
            self.assertTrue(np.any(np.all(topology.vertices==corner,axis=1)))
        np.testing.assert_array_equal(result.min(axis=(0,1)),(-1,-1,-1))
        np.testing.assert_array_equal(result.max(axis=(0,1)),(1,1,1))


if __name__ == "__main__":unittest.main()
