"""Terminal model departures and mandatory clearance around tower deposits."""
from dataclasses import replace
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from threading import Event

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"src"))
from cooling_tower.calibration.gcode_integration import _point_segment_distance
from cooling_tower.gcode.parser import MachineStateTracker, Movement, iter_parsed_gcode_lines
from cooling_tower.gcode.slicer_layer_times import read_slicer_layer_times
from cooling_tower.postprocessor import BEGIN, END, FINAL_PARK, PARKED, PostprocessorSettings, SUPPORTED_SLICERS
from cooling_tower.postprocessor_capture import FINAL_TOWER_CLEARANCE_MM, TOWER_TRAVEL_CLEARANCE_MM, capture_obstacle
from cooling_tower.postprocessor_routing import prefer_model_avoiding_route
from cooling_tower.postprocessor_toolpaths import contour_path
from cooling_tower.postprocessor_travel import segments_cross, safe_travel_path
from cooling_tower.preview.toolpath import PreviewCancelled
from cooling_tower.postprocessor_export import export_postprocessor_run
from cooling_tower.postprocessor import PostprocessorPlacementError
import test_postprocessor as fixture_module
from test_postprocessor import make_gcode


class TerminalTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.PostprocessorTests()
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def terminal_events(self, result):
        tracker, active = MachineStateTracker(), False
        events = []
        for line in iter_parsed_gcode_lines(result.gcode_path):
            active = active or line.raw_text == FINAL_PARK
            event = tracker.process_line(line)
            if active and isinstance(event, Movement):
                events.append(event)
            if line.raw_text == PARKED:
                break
        return events

    def test_final_layer_only_departs_once_without_printing_or_waiting_in_all_modes(self):
        for adapter in SUPPORTED_SLICERS:
            for relative, xyz, hop in ((False,False,.2),(True,True,.6),(True,False,0)):
                with self.subTest(adapter=adapter, relative=relative, xyz=xyz, hop=hop):
                    request = self.fixture.request(make_gcode(relative=relative,relative_xyz=xyz), adapter=adapter,
                        settings=PostprocessorSettings(target_layer_time_s=30, automatic_z_hop=False,z_hop_mm=hop))
                    before = request.prepared_source.analysis_gcode_path.read_bytes()
                    result = self.fixture.prepare(request)
                    self.assertEqual(result.scene.tower_layer_count, len(request.snapshot.layers)-1)
                    for point in result.scene.wait_points:
                        self.assertAlmostEqual(point.x, result.scene.wait_position_xy_mm[0], places=5)
                        self.assertAlmostEqual(point.y, result.scene.wait_position_xy_mm[1], places=5)
                    self.assertEqual((result.layer_waits_s[-1],result.layer_primes_mm[-1]),(0,0))
                    terminal = result.gcode_path.read_text().split(FINAL_PARK)[1].split(END)[0]
                    self.assertNotIn("G4", terminal)
                    self.assertNotIn("M400", terminal)
                    self.assertNotIn("prime", terminal)
                    events = self.terminal_events(result)
                    self.assertTrue(all(e.delta_e <= 0 for e in events))
                    xy = [e for e in events if e.endpoint_distance_xy_mm > 0]
                    self.assertEqual(len(xy), 1)
                    self.assertEqual((xy[0].start_x,xy[0].start_y),(100,100))
                    self.assertAlmostEqual(xy[0].start_z, request.snapshot.layers[-1].z_mm)
                    self.assertAlmostEqual(xy[0].end_z, xy[0].start_z+hop)
                    self.assertLess(math.dist((xy[0].end_x,xy[0].end_y),result.final_position_xy_mm),1e-5)
                    self.assertEqual(request.prepared_source.analysis_gcode_path.read_bytes(),before)

    def test_final_stop_uses_same_virtual_shaft_after_early_tower_end_and_nearest_edge(self):
        settings = PostprocessorSettings(target_layer_time_s=30,automatic_diameter=False,diameter_mm=12,
            automatic_base=False,base_width_mm=18,automatic_position=False,center_x_mm=60,center_y_mm=100,
            automatic_wait_position=False,wait_x_mm=20,wait_y_mm=100)
        text = make_gcode()
        full = self.fixture.prepare(self.fixture.request(text,settings=settings))
        blocks = text.split(";LAYER_CHANGE")
        for i in (3,4,5):
            blocks[i+1] = blocks[i+1].replace(" F1200", " F40")
        early = self.fixture.prepare(self.fixture.request(";LAYER_CHANGE".join(blocks),settings=settings))
        self.assertEqual(early.scene.tower_layer_count,3)
        self.assertEqual(early.final_position_xy_mm,full.final_position_xy_mm)
        for result in (early,full):
            frame_angle = result.wipe_angles_rad[0]
            spine = (result.diameter_mm-result.capture_design.depth_mm)/2
            outline = contour_path(result.scene.tower_center_xy_mm,result.diameter_mm/2,0,"outer",frame_angle,spine_half=spine).points
            stop = result.final_position_xy_mm
            self.assertAlmostEqual(min(_point_segment_distance(stop,a,b) for a,b in zip(outline,outline[1:])),FINAL_TOWER_CLEARANCE_MM,delta=.015)
            # Independent dense boundary search: no other edge point is closer.
            origin = (100,100)
            closest = min(math.dist(origin,p) for p in outline)
            self.assertAlmostEqual(math.dist(origin,stop)+FINAL_TOWER_CLEARANCE_MM,closest,delta=.015)
            last = self.terminal_events(result)[-1]
            self.assertGreater(last.end_z,result.height_mm)

    def test_every_outbound_park_route_avoids_complete_foot_and_brim(self):
        settings = PostprocessorSettings(target_layer_time_s=30,automatic_diameter=False,diameter_mm=12,
            automatic_base=False,base_width_mm=18,automatic_position=False,center_x_mm=60,center_y_mm=100,
            automatic_wait_position=False,wait_x_mm=20,wait_y_mm=100)
        result = self.fixture.prepare(self.fixture.request(settings=settings))
        spine = (result.diameter_mm-result.capture_design.depth_mm)/2
        center = result.scene.tower_center_xy_mm
        axis_a,axis_b = (center[0],center[1]-spine),(center[0],center[1]+spine)
        minor = result.placement.reserved_radius_mm-spine
        for to_wait,_,_ in result.placement_solution[2]:
            self.assertGreater(len(to_wait),2)
            for a,b in zip(to_wait,to_wait[1:]):
                self.assertFalse(segments_cross(a,b,axis_a,axis_b))
                distance = min(_point_segment_distance(a,axis_a,axis_b),_point_segment_distance(b,axis_a,axis_b),
                    _point_segment_distance(axis_a,a,b),_point_segment_distance(axis_b,a,b))
                self.assertGreaterEqual(distance-minor,TOWER_TRAVEL_CLEARANCE_MM-1e-5)

    def test_single_layer_and_last_only_deficit_have_no_tower_and_no_cooling_pause(self):
        blocks = make_gcode().split(";LAYER_CHANGE")
        for i in range(5):
            blocks[i+1] = blocks[i+1].replace(" F1200"," F40")
        for text,target in ((make_gcode(layers=1),30),(";LAYER_CHANGE".join(blocks),30)):
            result = self.fixture.prepare(self.fixture.request(text,settings=PostprocessorSettings(target_layer_time_s=target)))
            self.assertEqual(result.scene.tower_layer_count,0)
            self.assertEqual(result.total_wait_s,0)
            self.assertEqual(len([e for e in self.terminal_events(result) if e.endpoint_distance_xy_mm>0]),1)
            self.assertNotEqual(result.final_position_xy_mm,(100,100))
            exported = export_postprocessor_run(self.fixture.service,result,self.fixture.root/"exports")
            if len(result.layer_times_s)==1:
                self.assertIsNone(exported.minimum_verified_layer_time_s)

    def test_native_terminal_clock_does_not_subtract_removed_shutdown_twice(self):
        from test_slicer_layer_times import scarf_gcode
        text = scarf_gcode().replace("G1 Z0.2 F600","G1 X100 Y100 Z0.2 F600",1)
        request = self.fixture.request(text,adapter="anycubic_slicer_next",settings=PostprocessorSettings(target_layer_time_s=120))
        request.profile.effective_values["seam_slope_type"] = "external"
        result = self.fixture.prepare(request)
        clock = read_slicer_layer_times(result.gcode_path)
        self.assertGreater(clock.times_s[-1],0)
        self.assertAlmostEqual(clock.times_s[-1],result.layer_times_s[-1],delta=1e-5)
        self.assertLess(result.layer_times_s[-1],120)
        self.assertTrue(all(t>=120-.005 for t in result.layer_times_s[:-1]))

    def test_final_virtual_stop_cannot_land_on_a_later_model_overhang(self):
        blocks = make_gcode().split(";LAYER_CHANGE")
        for i in (3,4,5):
            blocks[i+1] = blocks[i+1].replace(" F1200"," F40")
        blocks[-1] = blocks[-1].replace("G1 X100 Y100 E0.40000 F40",
            "G1 X63 Y100 E.4 F40\nG1 X100 Y100 E.4 F40")
        settings = PostprocessorSettings(target_layer_time_s=30,automatic_diameter=False,diameter_mm=12,
            automatic_base=False,base_width_mm=18,automatic_position=False,center_x_mm=60,center_y_mm=100,
            automatic_wait_position=False,wait_x_mm=20,wait_y_mm=100)
        request = self.fixture.request(";LAYER_CHANGE".join(blocks),settings=settings)
        with self.assertRaisesRegex(PostprocessorPlacementError,"Abschlussposition.*Modell"):
            self.fixture.prepare(request)

    def test_optional_model_detour_fallback_keeps_the_required_tower_obstacle(self):
        result = self.fixture.prepare(self.fixture.request())
        start,park = (100,103),result.scene.wait_position_xy_mm
        obstacle = capture_obstacle(result.scene.tower_center_xy_mm,park,result.capture_design,
            result.placement.reserved_radius_mm)
        midpoint = ((start[0]+park[0])/2,(start[1]+park[1])/2)
        island = tuple((midpoint[0]+x,midpoint[1]+y) for x,y in ((-2,-2),(2,-2),(2,2),(-2,2)))
        expected = safe_travel_path(start,park,result.placement.geometry,soft_polygons=(obstacle,))
        attempted = []
        def only_required(*args,**kwargs):
            attempted.append(len(kwargs.get("soft_polygons",())))
            if attempted[-1] > 1:
                raise ValueError("optional detour unavailable")
            return safe_travel_path(*args,**kwargs)
        with patch("cooling_tower.postprocessor_routing.safe_travel_path",side_effect=only_required):
            actual = prefer_model_avoiding_route(start,park,result.placement.geometry,(island,),
                margin_mm=1,required_polygons=(obstacle,))
        self.assertIn(2,attempted)
        self.assertEqual(actual,expected)

    def test_cancellation_during_native_reference_analysis_cleans_workspace(self):
        from test_slicer_layer_times import scarf_gcode
        request = self.fixture.request(scarf_gcode().replace("G1 Z0.2 F600","G1 X100 Y100 Z0.2 F600",1),adapter="anycubic_slicer_next")
        request.profile.effective_values["seam_slope_type"] = "external"
        event = Event()
        with self.assertRaises(PreviewCancelled):
            self.fixture.service.prepare(request,cancellation_event=event,
                progress_callback=lambda percent,_: event.set() if percent >= 55 else None)
        self.assertFalse(tuple(self.fixture.service.temporary_root.iterdir()))


if __name__ == "__main__":
    unittest.main()
