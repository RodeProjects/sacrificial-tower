"""Physical path invariants for the supported capsule capture tower."""
from dataclasses import replace
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"src"))
from cooling_tower.calibration.gcode_integration import _point_segment_distance
from cooling_tower.gcode.parser import MachineStateTracker, Movement, iter_parsed_gcode_lines
from cooling_tower.postprocessor import BEGIN, END, PostprocessorSettings
from cooling_tower.postprocessor_capture import (
    CAPTURE_MARKER, DEPARTURE_WIPE_MARKER, DRY_EXIT_MARKER, MODEL_WIPE_MARKER, capture_design,
    capture_frame, additional_prime, alignment_penalty, supported_foot_holes,
)
from cooling_tower.postprocessor_toolpaths import contour_path, tower_paths
import test_postprocessor as fixtures


def inserted_events(path):
    tracker, active, layer, phase = MachineStateTracker(), False, -1, ""
    for line in iter_parsed_gcode_lines(path):
        if line.raw_text == BEGIN:
            active, layer, phase = True, layer+1, "begin"
        if active and line.raw_text.startswith("; SACRIFICIAL_TOWER_"):
            phase = line.raw_text
        if line.raw_text.startswith("; sacrificial wipe / prime and "):
            phase = "print"
        event = tracker.process_line(line)
        if active and isinstance(event, Movement):
            yield layer, phase, event, tracker.state.extrusion_factor
        if line.raw_text == END:
            active = False


class CaptureGeometryTests(unittest.TestCase):
    def frame(self, index=0, *, width=.45, height=.2):
        return capture_frame((0, 0), (50, 0), 8, 8, width, width,
            height, 2, 3, contact_index=index)

    def test_late_wait_reserve_increases_size_and_keeps_a_supported_constant_shaft(self):
        short = capture_design(30, (0, 1))
        long = capture_design(30, (0, 1, 60))
        self.assertGreaterEqual(short.diameter_mm, 12)
        self.assertGreater(long.diameter_mm, short.diameter_mm)
        self.assertGreater(long.depth_mm, short.depth_mm)
        self.assertEqual(long.reserve_wait_s, 60)
        self.assertEqual(capture_design(30, (60,), diameter=16).diameter_mm, 16)

    def test_contact_lanes_alternate_sides_then_move_inward_with_bead_clearance(self):
        frame = self.frame()
        count = frame.contact_lane_count
        lanes = [self.frame(i).contact_v for i in range(count)]
        self.assertGreaterEqual(count, 4)
        for i in range(0, count-1, 2):
            self.assertAlmostEqual(lanes[i], -lanes[i+1])
            if i:
                self.assertLess(abs(lanes[i]), abs(lanes[i-2]))
        self.assertGreaterEqual(min(b-a for a, b in zip(sorted(lanes), sorted(lanes)[1:])), .9-1e-8)
        self.assertAlmostEqual(self.frame(count).contact_v, lanes[0])

    def test_early_capture_pull_stays_in_open_chamber_beside_the_brace(self):
        for i in range(18):
            frame = self.frame(i)
            paths = frame.internal_paths()
            for p in frame.capture_points[1:]:
                self.assertLess(p[0], frame.core_minor)
                self.assertLess(abs(p[1]), frame.spine_half)
                self.assertGreater(min(_point_segment_distance(p, a, b)
                    for path in paths for a,b in zip(path.points,path.points[1:])), frame.inner_width/2)
            self.assertGreater(frame.entry[0], frame.minor_radius)

    def test_capsule_faces_have_exact_bead_spacing_instead_of_scaled_walls(self):
        frame = self.frame()
        faces = []
        for path in list(tower_paths((0, 0), 8, 8, .45, .45, .2, 2,
                hollow=True, first=False, angle=math.pi, spine_half=frame.spine_half)):
            faces.append(max(p[0] for p in path.points))
            self.assertEqual(path.points[0], path.points[-1])
            self.assertTrue(all(p[0] <= frame.minor_radius-.45/2+1e-8 for p in path.points))
        self.assertAlmostEqual(faces[0]-faces[1], .45-.2*(1-math.pi/4))

    def test_taper_capture_stays_at_front_instead_of_crossing_entire_solid_annulus(self):
        frame = capture_frame((0, 0), (50, 0), 18, 8, .45, .45, .2, 2, 3)
        entry, inside, sideways = frame.capture_points
        self.assertLess(entry[0]-inside[0], 2)
        self.assertEqual(inside[0], sideways[0])
        self.assertGreater(inside[0], 8)

    def test_departure_starts_at_last_return_bead_and_crosses_clean_wall(self):
        frame = self.frame()
        rail = frame.internal_paths()[-1]
        self.assertGreater(rail.points[0][0], rail.points[1][0])
        self.assertEqual(frame.departure_origin, rail.points[-1])
        self.assertLess(frame.exit[0], -frame.minor_radius)
        self.assertEqual(frame.exit[1], frame.departure_origin[1])

    def test_inner_foot_taper_saves_material_and_limits_inward_overhang(self):
        radii = [12-6*(i/39)**.35 for i in range(40)]
        holes = supported_foot_holes(radii, 6, [.86]*40, [.2]*40, [.45]*40)
        self.assertGreater(holes[2], 6-.86)
        self.assertAlmostEqual(holes[-1], 6-.86)
        for i in range(2,39):
            self.assertLessEqual(holes[i]-holes[i+1], .100001)
            self.assertGreaterEqual(radii[i]-holes[i], .86-1e-8)

    def test_prime_is_zero_without_wait_and_bounded_for_long_waits(self):
        self.assertEqual(additional_prime(0, .3, 1), 0)
        self.assertEqual(additional_prime(2, .3, 1), .04)
        self.assertEqual(additional_prime(100, 5, 1), .15)
        self.assertEqual(additional_prime(100, 0, 1), 0)


class CaptureGCodeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PostprocessorTests()
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def test_all_slicers_preserve_original_and_use_early_capture_and_supported_exit(self):
        for adapter in ("prusa_slicer", "orca_slicer", "bambu_studio", "anycubic_slicer_next"):
            with self.subTest(adapter=adapter):
                request = self.fixture.request(fixtures.make_gcode(layers=45), adapter=adapter,
                    settings=PostprocessorSettings(target_layer_time_s=20))
                original = request.prepared_source.analysis_gcode_path.read_bytes()
                result = self.fixture.prepare(request)
                self.assertEqual(request.prepared_source.analysis_gcode_path.read_bytes(), original)
                self.assertLess(alignment_penalty(result.scene.tower_center_xy_mm,
                    result.scene.wait_position_xy_mm, (105, 105)), .01)
                self.assertEqual(len(set(result.wipe_angles_rad)), 1)
                phases = set()
                for index, phase, event, _factor in inserted_events(result.gcode_path):
                    phases.add(phase)
                    if phase in (CAPTURE_MARKER, DEPARTURE_WIPE_MARKER, DRY_EXIT_MARKER, MODEL_WIPE_MARKER):
                        self.assertLessEqual(event.delta_e, 0)
                        self.assertGreaterEqual(min(event.start_z, event.end_z), result.layer_heights_mm[index]-1e-6)
                    if phase in (DEPARTURE_WIPE_MARKER, DRY_EXIT_MARKER) and event.endpoint_distance_xy_mm > 0:
                        relief = min(result.effective_z_hop_mm, .05,
                            request.snapshot.layers[index].height_mm*.25) if phase == DRY_EXIT_MARKER else 0.
                        self.assertAlmostEqual(event.start_z, result.layer_heights_mm[index]+relief, places=5)
                        self.assertAlmostEqual(event.end_z, result.layer_heights_mm[index]+relief, places=5)
                self.assertTrue({CAPTURE_MARKER, DEPARTURE_WIPE_MARKER, MODEL_WIPE_MARKER} <= phases)
                before = self.fixture.original_movements(request.prepared_source.analysis_gcode_path)
                after = self.fixture.original_movements(result.gcode_path)
                self.assertEqual(len(before), len(after))
                for a, b in zip(before, after):
                    self.assertEqual((a[0], a[-1]), (b[0], b[-1]))
                    for x, y in zip(a[1:-1], b[1:-1]):
                        self.assertAlmostEqual(x, y, places=5)

    def test_prime_follows_real_pause_and_disappears_when_tower_alone_fills_deficit(self):
        result = self.fixture.prepare(self.fixture.request(settings=PostprocessorSettings(target_layer_time_s=3)))
        self.assertEqual(result.wait_count, 0)
        self.assertTrue(all(p == 0 for p in result.layer_primes_mm))
        result = self.fixture.prepare(self.fixture.request(settings=PostprocessorSettings(target_layer_time_s=30)))
        self.assertGreater(result.wait_count, 0)
        for wait, prime in zip(result.layer_waits_s, result.layer_primes_mm):
            self.assertLessEqual(prime, min(.3, wait*.02)+1e-6)
            if not wait:
                self.assertEqual(prime, 0)

    def test_automatic_prime_ceiling_tracks_geometry_and_manual_override_stays_a_ceiling(self):
        request = self.fixture.request(fixtures.make_gcode(layers=45),
            settings=PostprocessorSettings(target_layer_time_s=30,
                automatic_diameter=False, diameter_mm=12))
        small = self.fixture.prepare(request)
        large = self.fixture.prepare(replace(request, settings=replace(request.settings, diameter_mm=24)))
        self.assertTrue(PostprocessorSettings().automatic_prime)
        self.assertGreater(large.effective_settings.prime_mm, small.effective_settings.prime_mm)
        self.assertLessEqual(large.effective_settings.prime_mm, 1)
        manual = self.fixture.prepare(replace(request, settings=replace(request.settings,
            automatic_prime=False, prime_mm=.123)))
        self.assertEqual(manual.effective_settings.prime_mm, .123)
        self.assertTrue(all(p <= .123+1e-6 for p in manual.layer_primes_mm))
        disabled = self.fixture.prepare(replace(request, settings=replace(request.settings,
            automatic_prime=False, prime_mm=0)))
        self.assertTrue(all(p == 0 for p in disabled.layer_primes_mm))

    def test_retract_on_model_follows_only_already_deposited_segments(self):
        request = self.fixture.request()
        result = self.fixture.prepare(request)
        checked = 0
        for index, phase, event, _factor in inserted_events(result.gcode_path):
            if phase == MODEL_WIPE_MARKER and event.endpoint_distance_xy_mm > 0:
                self.assertAlmostEqual(event.start_x, 100)
                self.assertAlmostEqual(event.end_x, 100)
                self.assertGreaterEqual(event.end_y, 100)
                self.assertLessEqual(event.end_y, 110)
                self.assertLess(event.delta_e, 0)
                checked += 1
        self.assertEqual(checked, result.scene.tower_layer_count)

    def test_contours_then_two_brace_beads_then_retract_and_one_way_relief_exit(self):
        result = self.fixture.prepare(self.fixture.request(fixtures.make_gcode(layers=45)))
        tracker, active, layer, groups, current = MachineStateTracker(), False, -1, [], []
        for line in iter_parsed_gcode_lines(result.gcode_path):
            if line.raw_text == BEGIN:
                active, layer = True, layer+1
            if active and layer == result.scene.tower_layer_count-1:
                if line.raw_text.startswith((";TYPE:", "; FEATURE:")) or line.raw_text == DEPARTURE_WIPE_MARKER:
                    if current:
                        groups.append(current)
                        current = []
                if line.raw_text == DEPARTURE_WIPE_MARKER:
                    break
            event = tracker.process_line(line)
            if active and layer == result.scene.tower_layer_count-1 and isinstance(event,Movement) and event.category == "deposition":
                if not current:
                    current.append((event.start_x,event.start_y))
                current.append((event.end_x,event.end_y))
            if line.raw_text == END:
                active = False
        self.assertEqual(len(groups), result.effective_settings.wall_count+2)
        for contour in groups[:-2]:
            self.assertLess(math.dist(contour[0],contour[-1]), 1e-5)
        outward, inward = groups[-2:]
        self.assertEqual((len(outward),len(inward)), (2,2))
        center, park = result.scene.tower_center_xy_mm, result.scene.wait_position_xy_mm
        direction = park[0]-center[0],park[1]-center[1]
        def along(a,b):
            return (b[0]-a[0])*direction[0]+(b[1]-a[1])*direction[1]
        self.assertGreater(along(*outward), 0)
        self.assertLess(along(*inward), 0)
        wipes = [e for i,phase,e,_ in inserted_events(result.gcode_path)
            if i == result.scene.tower_layer_count-1 and phase == DEPARTURE_WIPE_MARKER
            and e.delta_e < 0]
        self.assertEqual(len(wipes), 1)
        wipe = wipes[0]
        self.assertLess(math.dist((wipe.end_x,wipe.end_y),inward[-1]), 1e-5)
        self.assertEqual(wipe.endpoint_distance_xy_mm, 0)
        self.assertLess(math.dist((wipe.start_x,wipe.start_y),inward[-1]), 1e-5)
        dry = [e for i,phase,e,_ in inserted_events(result.gcode_path)
            if i == result.scene.tower_layer_count-1 and phase == DRY_EXIT_MARKER]
        crossing = [e for e in dry if e.endpoint_distance_xy_mm > 0]
        self.assertEqual(len(crossing), 1)
        self.assertEqual(crossing[0].delta_e, 0)
        self.assertLess(along((crossing[0].start_x,crossing[0].start_y),
            (crossing[0].end_x,crossing[0].end_y)), 0)
        self.assertLess(math.dist((crossing[0].start_x,crossing[0].start_y),inward[-1]), 1e-5)
        # Lifting happens only after the dry exit, still fully retracted.
        self.assertGreater(dry[-1].end_z, dry[0].start_z)

    def test_microscopic_isolated_terminal_stroke_uses_stationary_retract(self):
        text = fixtures.make_gcode(layers=4).replace('G1 X100 Y100 E0.40000 F1200',
            'G1 X100 Y100 E0.40000 F1200\nG1 X106 Y106 F6000\nG1 X106.000001 Y106 E.000001 F1200')
        result = self.fixture.prepare(self.fixture.request(text))
        self.assertNotIn(MODEL_WIPE_MARKER, result.gcode_path.read_text())
        for _index, _phase, event, _factor in inserted_events(result.gcode_path):
            self.assertGreater(event.feedrate_mm_min, 0)

    def test_concave_foot_and_rails_are_supported_by_the_previous_layer(self):
        result = self.fixture.prepare(self.fixture.request(fixtures.make_gcode(layers=45),
            settings=PostprocessorSettings(automatic_diameter=False, diameter_mm=12,
                automatic_base=False, base_width_mm=27)))
        by_z = {}
        for segment in result.scene.tower_segments:
            by_z.setdefault(round(segment.start.z, 5), []).append(segment)
        previous = None
        for z, segments in sorted(by_z.items()):
            if previous is not None:
                # Sample actual deposited segments, independently of the
                # contour construction, including straight faces and the brace.
                for segment in segments:
                    for t in (0., .5, 1.):
                        p = (segment.start.x+t*(segment.end.x-segment.start.x),
                            segment.start.y+t*(segment.end.y-segment.start.y))
                        distance = min(_point_segment_distance(p,
                            (s.start.x, s.start.y), (s.end.x, s.end.y)) for s in previous)
                        self.assertLessEqual(distance, .45+.025, (z, p, distance))
            previous = segments

    def test_tapered_inner_foot_uses_less_material_with_identical_outer_contour(self):
        request = self.fixture.request(fixtures.make_gcode(layers=45),
            settings=PostprocessorSettings(automatic_diameter=False, diameter_mm=12,
                automatic_base=False, base_width_mm=27, automatic_position=False,
                center_x_mm=60, center_y_mm=60, automatic_wait_position=False,
                wait_x_mm=30, wait_y_mm=30))
        tapered = self.fixture.prepare(request)
        with patch("cooling_tower.postprocessor.supported_foot_holes",
                lambda radii, shaft, thicknesses, heights, widths:
                    tuple(max(0., shaft-t) for t in thicknesses)):
            vertical = self.fixture.prepare(request)
        def amount(result):
            return sum(e.delta_e*factor for _,_,e,factor in inserted_events(result.gcode_path)
                if e.category == "deposition" and e.endpoint_distance_xy_mm > 0)
        self.assertLess(amount(tapered), amount(vertical))
        def contours(result):
            by_z = {}
            for s in result.scene.tower_segments:
                by_z.setdefault(round(s.start.z,5), []).extend(((s.start.x,s.start.y),(s.end.x,s.end.y)))
            return {z: tuple(round(f(p[i] for p in ps),5) for i in (0,1) for f in (min,max))
                for z, ps in by_z.items()}
        self.assertEqual(contours(tapered), contours(vertical))

    def test_broad_floor_plates_preserve_old_area_reserve_only_in_first_two_layers(self):
        request = self.fixture.request(fixtures.make_gcode(layers=45),
            settings=PostprocessorSettings(automatic_diameter=False, diameter_mm=12,
                automatic_position=False, center_x_mm=60, center_y_mm=60,
                automatic_wait_position=False, wait_x_mm=30, wait_y_mm=30))
        broad = self.fixture.prepare(request)
        design = broad.capture_design
        normal = self.fixture.prepare(replace(request, settings=replace(request.settings,
            automatic_base=False, base_width_mm=design.concave_base_width_mm)))
        self.assertGreater(design.bottom_widths_mm[0], design.concave_base_width_mm)
        self.assertEqual(broad.base_width_mm, max(design.bottom_widths_mm))
        spine = (broad.diameter_mm-design.depth_mm)/2
        def area(width):
            minor = width/2-spine
            return math.pi*minor**2+4*spine*minor
        # The former circular sizing used 1.8 times the shaft, then 25% reserve.
        self.assertAlmostEqual(area(broad.base_width_mm)/area(broad.diameter_mm), (1.8*1.25)**2)
        def upper(result):
            return [(s.start,s.end) for s in result.scene.tower_segments if s.start.z > .4+1e-6]
        self.assertEqual(upper(broad), upper(normal))


if __name__ == "__main__":
    unittest.main()
