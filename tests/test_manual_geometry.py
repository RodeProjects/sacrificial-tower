import sys
import math
import unittest
from dataclasses import replace
from pathlib import Path
from threading import Event
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))

from cooling_tower.manual.geometry import (Coordinate, Cubic, ManualSettings, GeometryError, initial_draft,
                                          validate, validate_settings, set_minimum_diameter, move_point, insert_point, remove_point, set_curve, set_point_curve_mode, reset_point_curves, couple_point,
                                          bounded_edit, tessellate, create_mesh, CURVE_RADIAL_ERROR_MM)
from cooling_tower.tower.mesh_generator import validate_triangle_mesh
from cooling_tower.preview import PreviewCancelled


def draft(height=100,settings=None):
    return initial_draft(settings or ManualSettings(),(SimpleNamespace(z_mm=.3),SimpleNamespace(z_mm=height)),150,"source")


class ManualGeometryTests(unittest.TestCase):
    def test_minimum_diameter_has_absolute_one_millimetre_floor(self):
        for value in (.999, .1, 0, -1):
            with self.subTest(value=value), self.assertRaises(GeometryError):
                validate_settings(replace(ManualSettings(),minimum_diameter_mm=value))
        validate_settings(replace(ManualSettings(),minimum_diameter_mm=1))

    def test_minimum_moves_fixed_free_and_curve_anchors_without_changing_heights_or_maxima(self):
        original,identity=insert_point(draft(),50)
        original=move_point(original,identity,diameter_mm=12)
        original=set_curve(original,1,control=1,position=Coordinate(3,20))
        changed=set_minimum_diameter(original,30)
        self.assertEqual(changed.settings.minimum_diameter_mm,30)
        self.assertEqual(changed.settings.maximum_diameter_mm,original.settings.maximum_diameter_mm)
        self.assertEqual(changed.settings.maximum_foot_diameter_mm,original.settings.maximum_foot_diameter_mm)
        for old,new in zip(original.points,changed.points):
            self.assertEqual(new.position,Coordinate(max(15,old.position.radius_mm),old.position.z_mm))
            self.assertEqual(new.identity,old.identity)
        for old,new in zip(original.curves,changed.curves):
            self.assertEqual(new.curved,old.curved)
            for name in ("start","control1","control2","end"):
                self.assertGreaterEqual(getattr(new,name).radius_mm,15)
                self.assertEqual(getattr(new,name).z_mm,getattr(old,name).z_mm)
        # An accepted numeric edit is permanent, even if the minimum is lowered.
        self.assertEqual(set_minimum_diameter(changed,5).artifact_payload(),changed.artifact_payload())
        for settings in (replace(original.settings,maximum_diameter_mm=29),
                         replace(original.settings,maximum_foot_diameter_mm=29)):
            with self.assertRaises(GeometryError):set_minimum_diameter(replace(original,settings=settings),30)

    def test_minimum_preserves_coupled_tangents_when_controls_or_points_hit_boundary(self):
        original=move_point(draft(),"base",diameter_mm=12)
        original,identity=insert_point(original,50)
        original=move_point(original,identity,diameter_mm=20)
        original=set_curve(original,1,control=2,position=Coordinate(4,40))
        original=couple_point(original,identity,True)
        for minimum in (16,24):
            with self.subTest(minimum=minimum):
                changed=set_minimum_diameter(original,minimum)
                self.assertTrue(changed.points[2].smooth)
                incoming,outgoing=changed.curves[1:3]
                self.assertAlmostEqual(incoming.derivative(1,"radius_mm")/incoming.derivative(1,"z_mm"),
                                       outgoing.derivative(0,"radius_mm")/outgoing.derivative(0,"z_mm"))
                self.assertGreaterEqual(incoming.control2.diameter_mm,minimum)
                self.assertGreaterEqual(outgoing.control1.diameter_mm,minimum)
                validate(changed)
                self.assertEqual(set_minimum_diameter(changed,1).artifact_payload(),changed.artifact_payload())
        self.assertEqual(set_minimum_diameter(original,5),original)

    def test_draft_requires_a_positive_actual_first_layer_height(self):
        for height in (0, -0.2, float("nan"), float("inf")):
            with self.subTest(height=height), self.assertRaises(GeometryError):
                initial_draft(ManualSettings(), (SimpleNamespace(z_mm=height), SimpleNamespace(z_mm=100)), 150, "source")
        self.assertEqual(draft().first_layer_z_mm, 0.3)

    def test_initial_foot_uses_automatic_rule_full_object_height_and_expands_its_limit(self):
        from cooling_tower.tower.base_calculator import calculate_phase10_base_outer_radius
        for height in (1,100,120.08,200,380,381,1000):
            settings=replace(ManualSettings(),foot_diameter_mm=30,maximum_foot_diameter_mm=30)
            d=initial_draft(settings,(SimpleNamespace(z_mm=.2),SimpleNamespace(z_mm=height)),150,"source")
            expected=2*calculate_phase10_base_outer_radius(object_height_mm=height,
                automatic_base_width=True,manual_base_width_mm=25)
            self.assertAlmostEqual(d.foot_diameter_mm,expected)
            self.assertEqual(d.settings.maximum_foot_diameter_mm,max(30,expected))
            self.assertEqual(settings.foot_diameter_mm,30)
            self.assertEqual(d.height_mm,min(height,150))
        self.assertEqual(initial_draft(ManualSettings(),(SimpleNamespace(z_mm=.2),SimpleNamespace(z_mm=200)),80,"short").foot_diameter_mm,42)
        for value in (False,"42",float("nan"),0,1001):
            with self.assertRaises(GeometryError):
                initial_draft(ManualSettings(),(SimpleNamespace(z_mm=.2),SimpleNamespace(z_mm=200)),80,"short",foot_diameter_mm=value)

    def test_manual_foot_can_expand_its_limit_and_narrow_again_without_shrinking_the_limit(self):
        d=draft()
        wide=move_point(d,"foot",diameter_mm=95)
        self.assertEqual((wide.foot_diameter_mm,wide.settings.maximum_foot_diameter_mm),(95,95))
        self.assertEqual(wide.settings.foot_height_mm,d.settings.foot_height_mm)
        narrow=move_point(wide,"foot",diameter_mm=30)
        self.assertEqual((narrow.foot_diameter_mm,narrow.settings.maximum_foot_diameter_mm),(30,95))
        self.assertEqual(d.foot_diameter_mm,25)

    def test_removing_a_point_resets_only_the_neighbor_controls_facing_it(self):
        original=draft()
        fixed,identity=insert_point(original,50)
        fixed=set_curve(fixed,0,control=2,position=Coordinate(3.5,6))
        fixed=set_curve(fixed,1,control=1,position=Coordinate(4,15))
        fixed=set_curve(fixed,2,control=2,position=Coordinate(5,90))
        reset=remove_point(fixed,identity)
        self.assertEqual(reset.curves[0],fixed.curves[0])
        self.assertEqual(reset.points,original.points)
        self.assertEqual(reset.curves[1].control1,reset.curves[1].start.lerp(reset.curves[1].end,1/3))
        self.assertEqual(reset.curves[1].control2,reset.curves[1].start.lerp(reset.curves[1].end,2/3))
        d=draft()
        identities=[]
        for z in (30,50,70):
            d,identity=insert_point(d,z)
            identities.append(identity)
            d=move_point(d,identity,diameter_mm=12)
        for index,curve in enumerate(d.curves[1:],1):
            d=set_curve(d,index,control=1,position=Coordinate(7,curve.start.lerp(curve.end,1/3).z_mm))
            d=set_curve(d,index,control=2,position=Coordinate(7,curve.start.lerp(curve.end,2/3).z_mm))
        d=couple_point(d,identities[0],True)
        d=couple_point(d,identities[2],True)
        reset=remove_point(d,identities[1])
        self.assertEqual(reset.curves[:2],d.curves[:2])
        self.assertEqual(reset.curves[3:],d.curves[4:])
        bridge=reset.curves[2]
        self.assertEqual(bridge.control1,bridge.start.lerp(bridge.end,1/3))
        self.assertEqual(bridge.control2,bridge.start.lerp(bridge.end,2/3))
        self.assertTrue(bridge.curved)
        self.assertTrue(all(not point.smooth for point in reset.points if point.identity in {identities[0],identities[2]}))
        validate(reset)

    def test_curve_reset_restores_defaults_for_free_and_fixed_points_without_moving_endpoints(self):
        original=draft()
        changed=set_curve(original,0,control=1,position=Coordinate(7,3))
        for identity in ("foot","foot_height","base"):
            reset=reset_point_curves(changed,identity)
            self.assertEqual(reset.points,original.points)
            self.assertEqual(reset.curves[0],original.curves[0])
        changed,identity=insert_point(original,50)
        changed=set_curve(changed,1,control=2,position=Coordinate(6,40))
        reset=reset_point_curves(changed,identity)
        self.assertEqual(reset.points,changed.points)
        for curve in reset.curves[1:]:
            self.assertTrue(curve.curved)
            self.assertEqual(curve.control1,curve.start.lerp(curve.end,1/3))
            self.assertEqual(curve.control2,curve.start.lerp(curve.end,2/3))
        self.assertEqual(reset_point_curves(reset,identity),reset)

    def test_insertion_uses_point_one_gap_but_later_movement_keeps_point_zero_five(self):
        d=draft();base=d.points[1].position.z_mm
        with self.assertRaises(GeometryError):insert_point(d,base+.075)
        d,identity=insert_point(d,base+.1)
        moved=move_point(d,identity,z_mm=base+.05)
        self.assertAlmostEqual(moved.points[2].position.z_mm,base+.05)
        with self.assertRaises(GeometryError):insert_point(d,d.height_mm-.075)

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
        self.assertEqual(mesh.segment_count,max(30,math.ceil(d.foot_diameter_mm)))

    def test_initial_segment_default_has_floor_30_and_still_follows_foot_diameter(self):
        for foot_diameter,expected in ((25,30),(30,30),(30.01,31),(42,42),(95,95),(300,256)):
            with self.subTest(foot_diameter=foot_diameter):
                d=initial_draft(ManualSettings(),(SimpleNamespace(z_mm=.2),SimpleNamespace(z_mm=100)),150,"segments",
                                foot_diameter_mm=foot_diameter)
                self.assertEqual(d.settings.circle_segments,expected)
                self.assertEqual(create_mesh(d).segment_count,expected)
        self.assertEqual(draft(settings=replace(ManualSettings(),circle_segments=48)).settings.circle_segments,48)

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

    def test_body_connection_expands_foot_and_limit_while_tower_limit_remains_binding(self):
        d = draft(settings=replace(ManualSettings(),maximum_diameter_mm=100,maximum_foot_diameter_mm=30))
        valid = move_point(d,"base",diameter_mm=30)
        self.assertEqual((valid.foot_diameter_mm,valid.settings.maximum_foot_diameter_mm),(32,32))
        wide=move_point(d,"base",diameter_mm=31)
        self.assertEqual((wide.foot_diameter_mm,wide.settings.maximum_foot_diameter_mm),(33,33))
        limited,error = bounded_edit(d,lambda t:move_point(d,"base",diameter_mm=5+45*t))
        self.assertAlmostEqual(limited.base_diameter_mm,50,places=6)
        self.assertEqual((limited.foot_diameter_mm,limited.settings.maximum_foot_diameter_mm),(52,52))
        self.assertIsNone(error)
        with self.assertRaises(GeometryError) as c: move_point(d,"base",diameter_mm=101)
        self.assertEqual(c.exception.setting,"maximum_diameter_mm")

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

    def test_inserted_point_stays_linear_inside_a_linear_segment(self):
        d=draft()
        position=d.curves[1].at(d.curves[1].parameter_at_z(50))
        result,identity=insert_point(d,50)
        self.assertEqual(result.points[2].position,position)
        self.assertEqual(result.curves[0],d.curves[0])
        self.assertFalse(any(c.curved for c in result.curves[1:]))
        midpoint=(result.curves[1].start.z_mm+50)/2
        expected=(result.curves[1].start.radius_mm+position.radius_mm)/2
        self.assertAlmostEqual(result.radius_at_z(midpoint),expected)

    def test_insertion_preserves_curves_and_coupling_at_fixed_and_manual_neighbors(self):
        for neighbor_heights in ((),(30,),(70,),(30,70)):
            with self.subTest(neighbor_heights=neighbor_heights):
                d=draft()
                for z in neighbor_heights:
                    d,identity=insert_point(d,z)
                    d=move_point(d,identity,diameter_mm=12)
                index=next(i for i,c in enumerate(d.curves) if c.start.z_mm < 50 < c.end.z_mm)
                for point in d.points[index:index+2]:
                    if point.kind == "free":
                        d=couple_point(d,point.identity,True)
                curve=d.curves[index]
                d=set_curve(d,index,control=1,position=Coordinate(curve.start.radius_mm+2,
                                                                 curve.start.lerp(curve.end,1/3).z_mm))
                d=set_curve(d,index,control=2,position=Coordinate(curve.end.radius_mm+1,
                                                                 curve.start.lerp(curve.end,2/3).z_mm))
                before=[d.radius_at_z(z) for z in range(1,101)]
                result,identity=insert_point(d,50)
                self.assertEqual(tuple(p for p in result.points if p.identity != identity),d.points)
                self.assertEqual(result.curves[:index],d.curves[:index])
                self.assertEqual(result.curves[index+2:],d.curves[index+1:])
                left,right=result.curves[index:index+2]
                self.assertTrue(left.curved and right.curved)
                self.assertNotEqual(left.control1,left.start.lerp(left.end,1/3))
                self.assertNotEqual(right.control2,right.start.lerp(right.end,2/3))
                for z,radius in enumerate(before,1):
                    self.assertAlmostEqual(result.radius_at_z(z),radius,places=10)
                original=d.curves[index]
                for old,new,t in ((original,left,0),(original,right,1)):
                    self.assertAlmostEqual(old.derivative(t,"radius_mm")/old.derivative(t,"z_mm"),
                                           new.derivative(t,"radius_mm")/new.derivative(t,"z_mm"),places=10)
                validate(result)

    def test_point_curve_switch_discards_edits_and_restarts_with_basic_controls(self):
        d,identity=insert_point(draft(),50)
        d=move_point(d,identity,diameter_mm=30)
        d=set_point_curve_mode(d,identity,True)
        d=set_curve(d,1,control=2,position=Coordinate(17,45))
        original=d.points[2].position
        linear=set_point_curve_mode(d,identity,False)
        self.assertFalse(any(c.curved for c in linear.curves[1:]))
        restored=set_point_curve_mode(linear,identity,True)
        self.assertEqual(restored.points[2].position,original)
        self.assertNotEqual(restored.curves[1].control2,d.curves[1].control2)
        self.assertTrue(all(c.curved for c in restored.curves[1:]))
        self.assertEqual(restored.curves[1].control2,restored.curves[1].start.lerp(original,2/3))
        for identity in ("base","foot","top"):
            with self.assertRaises(GeometryError):set_point_curve_mode(restored,identity,False)

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

    def test_foot_curve_obeys_minimum_while_controls_can_cross_it(self):
        for base_diameter in (5,20):
            d=move_point(draft(),"base",diameter_mm=base_diameter)
            for n in (1,2):
                with self.subTest(base=base_diameter,control=n):
                    control=getattr(d.curves[0],f"control{n}")
                    boundary=Coordinate(d.settings.minimum_diameter_mm/2,control.z_mm)
                    valid=set_curve(d,0,control=n,position=boundary)
                    self.assertGreaterEqual(min(valid.curves[0].radius_extrema()),boundary.radius_mm-1e-9)
                    destination=Coordinate(boundary.radius_mm-.1,control.z_mm)
                    if base_diameter == 20:
                        valid=set_curve(d,0,control=n,position=destination)
                        self.assertLess(getattr(valid.curves[0],f"control{n}").radius_mm,boundary.radius_mm)
                        self.assertGreaterEqual(min(valid.curves[0].radius_extrema()),boundary.radius_mm-1e-9)
                    else:
                        with self.assertRaises(GeometryError) as caught:
                            set_curve(d,0,control=n,position=destination)
                        self.assertEqual(caught.exception.setting,"minimum_diameter_mm")
                        self.assertIn("minimum_diameter_mm",caught.exception.limits)

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
