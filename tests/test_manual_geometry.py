import sys
import math
import unittest
from dataclasses import replace
from pathlib import Path
from threading import Event
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))

from cooling_tower.manual.geometry import (Coordinate, Cubic, ManualSettings, GeometryError, initial_draft,
                                          validate, move_point, insert_point, remove_point, set_curve, couple_point,
                                          bounded_edit, tessellate, create_mesh, CURVE_RADIAL_ERROR_MM)
from cooling_tower.tower.mesh_generator import validate_triangle_mesh
from cooling_tower.preview import PreviewCancelled


def draft(height=100,settings=None):
    return initial_draft(settings or ManualSettings(),(SimpleNamespace(z_mm=.3),SimpleNamespace(z_mm=height)),150,"source")


class ManualGeometryTests(unittest.TestCase):
    def test_initial_full_height_minimum_body_true_foot_and_caps(self):
        d = draft()
        self.assertEqual(d.height_mm,100)
        self.assertEqual(d.base_diameter_mm,d.settings.minimum_diameter_mm)
        self.assertEqual(d.points[0].position.z_mm,.3)
        self.assertTrue(d.curves[0].curved)
        self.assertNotEqual(d.curves[0].control1,Cubic.line(d.curves[0].start,d.curves[0].end).control1)
        self.assertEqual(d.curves[0].derivative(1,"radius_mm"),0)
        mesh = create_mesh(d)
        result = validate_triangle_mesh(mesh)
        self.assertTrue(result.is_valid)
        self.assertEqual(result.minimum_z_mm,0)
        self.assertEqual(result.maximum_z_mm,100)
        self.assertEqual(mesh.segment_count,max(25,math.ceil(d.foot_diameter_mm)))

    def test_machine_height_and_short_object(self):
        d = initial_draft(ManualSettings(),(SimpleNamespace(z_mm=.2),SimpleNamespace(z_mm=200)),80,"short")
        self.assertEqual(d.height_mm,80)
        self.assertLess(d.settings.foot_height_mm,80)
        self.assertTrue(validate_triangle_mesh(create_mesh(draft(.5))).is_valid)
        with self.assertRaises(GeometryError): draft(.35)

    def test_dynamic_foot_maintains_height_and_does_not_shrink(self):
        d = draft()
        wider = move_point(d,"base",diameter_mm=35)
        self.assertEqual(wider.settings.foot_height_mm,d.settings.foot_height_mm)
        self.assertEqual(wider.curves[0].end,wider.curves[1].start)
        self.assertEqual(wider.base_diameter_mm,35)
        self.assertEqual(wider.foot_diameter_mm,37)
        narrow = move_point(wider,"base",diameter_mm=5)
        self.assertEqual(narrow.foot_diameter_mm,37)

    def test_feedback_reports_first_effective_boundary_among_multiple_limits(self):
        d = draft(settings=replace(ManualSettings(),maximum_diameter_mm=40,maximum_foot_diameter_mm=80))
        limited,error = bounded_edit(d,lambda t:move_point(d,"base",diameter_mm=5+95*t))
        self.assertAlmostEqual(limited.base_diameter_mm,40,places=6)
        self.assertEqual(error.setting,"maximum_diameter_mm")

    def test_foot_limit_prioritizes_valid_connection_and_reports_actual_limit(self):
        d = draft(settings=replace(ManualSettings(),maximum_diameter_mm=100,maximum_foot_diameter_mm=30))
        valid = move_point(d,"base",diameter_mm=30)
        self.assertEqual(valid.foot_diameter_mm,30)
        with self.assertRaises(GeometryError) as c: move_point(d,"base",diameter_mm=31)
        self.assertEqual(c.exception.setting,"maximum_foot_diameter_mm")
        limited,error = bounded_edit(d,lambda t:move_point(d,"base",diameter_mm=5+45*t))
        self.assertAlmostEqual(limited.base_diameter_mm,30,places=6)
        self.assertEqual(error.setting,"maximum_foot_diameter_mm")

    def test_inserting_cubic_is_form_preserving_and_ids_are_stable(self):
        d = draft()
        d = set_curve(d,1,curved=True)
        d = set_curve(d,1,control=1,position=Coordinate(10,35))
        before = [d.radius_at_z(z/10) for z in range(80,1001)]
        new,identity = insert_point(d,50)
        self.assertEqual([p.identity for p in new.points if p.identity != identity],[p.identity for p in d.points])
        self.assertTrue(all(abs(a-new.radius_at_z(z/10)) < 1e-10 for a,z in zip(before,range(80,1001))))
        edited = move_point(new,identity,diameter_mm=20,z_mm=55)
        self.assertEqual(edited.points[2].identity,identity)
        self.assertEqual(edited.points[2].position,Coordinate(10,55))

    def test_multiple_widenings_and_base_does_not_scale_free_points(self):
        d = draft()
        for z,width in ((25,30),(40,8),(60,35),(80,7)):
            d,i = insert_point(d,z)
            d = move_point(d,i,diameter_mm=width)
        positions = [p.position for p in d.points[2:]]
        d = move_point(d,"base",diameter_mm=10)
        self.assertEqual([p.position for p in d.points[2:]],positions)
        self.assertTrue(validate_triangle_mesh(create_mesh(d)).is_valid)

    def test_point_removal_and_required_anchors(self):
        d = draft()
        for identity in ("foot","base","top"):
            with self.assertRaises(GeometryError): remove_point(d,identity)
        d,i = insert_point(d,50)
        self.assertEqual(len(remove_point(d,i).points),3)

    def test_points_cannot_overtake_and_height_cannot_delete_points(self):
        d,i = insert_point(draft(),80)
        with self.assertRaises(GeometryError): move_point(d,"top",z_mm=79)
        with self.assertRaises(GeometryError): move_point(d,i,z_mm=7)
        with self.assertRaises(GeometryError): insert_point(d,8.01)
        d2,error = bounded_edit(d,lambda t:move_point(d,"top",z_mm=100-50*t))
        self.assertAlmostEqual(d2.height_mm,80.05,places=6)
        self.assertEqual(len(d2.points),len(d.points))

    def test_diameter_overshoot_between_nodes_and_reversed_z_rejected(self):
        d = draft(settings=replace(ManualSettings(),maximum_diameter_mm=10))
        with self.assertRaises(GeometryError) as c: set_curve(d,1,control=1,position=Coordinate(20,35))
        self.assertEqual(c.exception.setting,"maximum_diameter_mm")
        with self.assertRaises(GeometryError): set_curve(d,1,control=1,position=Coordinate(3,101))
        with self.assertRaises(GeometryError): set_curve(d,1,control=1,position=d.curves[1].start)

    def test_exact_slope_extrema_not_endpoint_chords(self):
        curve = Cubic(Coordinate(2,0),Coordinate(2,1),Coordinate(20,2),Coordinate(20,3))
        self.assertAlmostEqual(max(curve.slope_extrema()),9)
        self.assertEqual(curve.derivative(0,"radius_mm"),0)
        self.assertEqual(curve.derivative(1,"radius_mm"),0)
        self.assertGreater(max(curve.slope_extrema()),(curve.end.radius_mm-curve.start.radius_mm)/3)

    def test_coupled_tangents_keep_points_and_match_local_slopes(self):
        d,i = insert_point(draft(),50)
        d = move_point(d,i,diameter_mm=20)
        before = tuple(p.position for p in d.points)
        d = couple_point(d,i,True)
        d = set_curve(d,1,control=2,position=Coordinate(8,45))
        a,b = d.curves[1:3]
        slope_a = a.derivative(1,"radius_mm")/a.derivative(1,"z_mm")
        slope_b = b.derivative(0,"radius_mm")/b.derivative(0,"z_mm")
        self.assertAlmostEqual(slope_a,slope_b)
        self.assertEqual(tuple(p.position for p in d.points),before)
        self.assertTrue(validate_triangle_mesh(create_mesh(d)).is_valid)

    def test_angle_activation_tightening_and_disabled_limit(self):
        d = draft()
        with self.assertRaises(GeometryError) as c: validate(replace(d,settings=replace(d.settings,contraction_enabled=True,contraction_angle_deg=1)))
        self.assertEqual(c.exception.setting,"contraction_angle_deg")
        self.assertEqual(validate(replace(d,settings=replace(d.settings,contraction_angle_deg=1))),replace(d,settings=replace(d.settings,contraction_angle_deg=1)))
        enabled = validate(replace(d,settings=replace(d.settings,contraction_enabled=True,contraction_angle_deg=89)))
        with self.assertRaises(GeometryError): validate(replace(enabled,settings=replace(enabled.settings,contraction_angle_deg=1)))

    def test_tessellation_radial_error_and_uniform_circle_segments(self):
        d = draft(settings=replace(ManualSettings(),circle_segments=48))
        profile = tessellate(d)
        for a,b in zip(profile.points,profile.points[1:]):
            for step in range(1,10):
                z = a.z_mm+(b.z_mm-a.z_mm)*step/10
                radius = a.radius_mm+(b.radius_mm-a.radius_mm)*step/10
                self.assertLessEqual(abs(radius-d.radius_at_z(z)),CURVE_RADIAL_ERROR_MM+1e-8)
        mesh = create_mesh(d)
        self.assertEqual(len(mesh.vertices),len(profile.points)*48+2)
        self.assertTrue(validate_triangle_mesh(mesh).is_valid)
        from cooling_tower.tower.mesh_generator import generate_tower_mesh,TowerMeshConfig
        expected = generate_tower_mesh(profile,TowerMeshConfig(48))
        self.assertEqual(mesh.vertices,expected.vertices)
        self.assertEqual(mesh.faces,expected.faces)

    def test_cancellation_during_mesh_validation_and_stl_writing(self):
        event = Event()
        mesh = create_mesh(draft(),event)
        event.set()
        with self.assertRaises(PreviewCancelled): validate_triangle_mesh(mesh)

    def test_cancelled_geometry_creates_no_result(self):
        event = Event(); event.set()
        with self.assertRaises(PreviewCancelled): create_mesh(draft(),event)

    def test_artifact_identity_ignores_visual_options_and_validation_limits(self):
        d = draft()
        changes = dict(overhang_enabled=True,overhang_angle_deg=20,critical_layers_enabled=True,maximum_diameter_mm=90)
        self.assertEqual(d.artifact_payload(),replace(d,settings=replace(d.settings,**changes)).artifact_payload())
        self.assertNotEqual(d.artifact_payload(),replace(d,settings=replace(d.settings,circle_segments=48)).artifact_payload())

    def test_nonfinite_and_invalid_types_rejected(self):
        for value in (float("nan"),float("inf"),False,"20"):
            with self.subTest(value=value),self.assertRaises((GeometryError,TypeError)):
                draft(settings=replace(ManualSettings(),minimum_diameter_mm=value))


if __name__ == "__main__": unittest.main()
