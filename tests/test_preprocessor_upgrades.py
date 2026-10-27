from dataclasses import replace
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cooling_tower.preprocessor import BEGIN, SUPPORTED_SLICERS
from cooling_tower.preprocessor_safety import ExclusionRect
from cooling_tower.preprocessor_travel import original_paths_clear
from cooling_tower.gcode.parser import MachineStateTracker, Movement, iter_parsed_gcode_lines
from cooling_tower.calibration.gcode_integration import _point_segment_distance
import test_preprocessor as fixture_module
from test_preprocessor import make_gcode


class PreprocessorUpgradeTests(unittest.TestCase):
    def test_tower_brim_is_real_first_layer_gcode_and_separately_coloured_scene(self):
        for adapter in SUPPORTED_SLICERS:
            with self.subTest(adapter=adapter):
                request = self.fixture.request(adapter=adapter)
                request.profile.effective_values.update({"brim_type": "outer_only", "brim_width": 4,
                    "brim_separation": .15, "filament_max_volumetric_speed": .8})
                source_bytes = request.prepared_source.analysis_gcode_path.read_bytes()
                result = self.fixture.prepare(request)
                self.assertTrue(result.scene.brim_segments)
                self.assertEqual(result.placement.brim_width_mm, 2)
                self.assertEqual(result.placement.brim_gap_mm, .15)
                center = result.scene.tower_center_xy_mm
                maximum = max(math.hypot(p.x-center[0], p.y-center[1])
                    for segment in result.scene.brim_segments for p in (segment.start, segment.end))
                self.assertAlmostEqual(maximum + result.placement.brim_line_width_mm/2,
                    result.base_width_mm/2+2.15, places=5)
                self.assertEqual({round(s.end.z, 5) for s in result.scene.brim_segments}, {.2})
                self.assertGreaterEqual(result.placement.reserved_radius_mm, maximum)
                tracker, in_brim, deposits = MachineStateTracker(), False, []
                for parsed in iter_parsed_gcode_lines(result.gcode_path):
                    if parsed.raw_text == "; SACRIFICIAL_TOWER_BRIM_BEGIN":
                        in_brim = True
                    elif parsed.raw_text == "; SACRIFICIAL_TOWER_BRIM_END":
                        in_brim = False
                    event = tracker.process_line(parsed)
                    if in_brim and isinstance(event, Movement) and event.category == "deposition":
                        deposits.append(event)
                self.assertEqual(len(deposits), len(result.scene.brim_segments))
                self.assertEqual(request.prepared_source.analysis_gcode_path.read_bytes(), source_bytes)
                original = self.fixture.original_movements(request.prepared_source.analysis_gcode_path)
                retained = self.fixture.original_movements(result.gcode_path)
                self.assertEqual(len(original), len(retained))
                for a, b in zip(original, retained):
                    self.assertEqual((a[0], a[-1]), (b[0], b[-1]))
                    for before, after in zip(a[1:-1], b[1:-1]):
                        self.assertAlmostEqual(before, after, places=5)

    def test_disabled_and_inner_only_model_brim_do_not_disable_tower_brim(self):
        for brim_type in ("none", "no_brim", "inner_only", "inner_only_brim"):
            request = self.fixture.request()
            request.profile.effective_values.update({"brim_type": brim_type, "brim_width": 5})
            result = self.fixture.prepare(request)
            self.assertTrue(result.scene.brim_segments)
            self.assertEqual(result.placement.brim_width_mm, 2)

    def setUp(self):
        self.fixture = fixture_module.PreprocessorTests()
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def test_missing_head_geometry_does_not_inflate_layerwise_distances_or_z_hop(self):
        for adapter in SUPPORTED_SLICERS:
            with self.subTest(adapter=adapter):
                request = self.fixture.request(adapter=adapter)
                request.profile.effective_values.pop("extruder_clearance_radius")
                request.profile.effective_values.pop("extruder_clearance_height")
                result = self.fixture.prepare(request)
                self.assertTrue(result.printhead.estimated)
                self.assertIn(result.printhead.note, result.scene.notes)
                self.assertEqual(result.effective_z_hop_mm, request.settings.z_hop_mm)
                self.assertGreaterEqual(math.dist(result.scene.wait_position_xy_mm, result.scene.tower_center_xy_mm),
                    result.base_width_mm / 2 + request.settings.wait_clearance_mm)
                self.assertLess(math.dist(result.scene.wait_position_xy_mm, result.scene.tower_center_xy_mm), 50)
                self.assertFalse(result.placement.head_clearance_required)
                self.assertTrue(result.scene.wait_travel_segments)
                self.assertTrue(result.scene.tower_travel_segments)
                self.assertTrue(all(t >= result.effective_settings.target_layer_time_s - .01 for t in result.layer_times_s))

    def test_profile_values_and_flow_limit_are_used_in_actual_gcode_with_speed_override(self):
        request = self.fixture.request(make_gcode(layers=5).replace("M201 X", "M220 S200\nM221 S150\nM201 X"))
        request = replace(request, settings=replace(request.settings, automatic_target_time=True))
        request.profile.effective_values.update({"slow_down_layer_time": [20], "outer_wall_speed": 100,
            "filament_max_volumetric_speed": [.7], "retraction_length": [1.1], "retraction_speed": 40,
            "travel_speed": 200, "machine_max_speed_x": [90], "machine_max_speed_y": [100]})
        result = self.fixture.prepare(request)
        self.assertEqual(result.effective_settings.target_layer_time_s, 20)
        self.assertEqual(result.effective_settings.retract_mm, 1.1)
        self.assertEqual(result.effective_settings.travel_speed_mm_s, 90)
        tracker, inserted, peak_flow = MachineStateTracker(bambu_compatible=True), False, 0
        for parsed in iter_parsed_gcode_lines(result.gcode_path):
            if parsed.raw_text == BEGIN:
                inserted = True
            event = tracker.process_line(parsed)
            if inserted and isinstance(event, Movement) and event.category == "deposition":
                physical_e = event.delta_e * tracker.state.extrusion_factor
                seconds = event.endpoint_distance_xy_mm / (event.feedrate_mm_min / 60 * tracker.state.speed_factor_percent / 100)
                peak_flow = max(peak_flow, physical_e * math.pi * (.875 ** 2) / seconds)
            if parsed.raw_text.endswith("POSTPROCESSOR_END"):
                inserted = False
        self.assertGreater(peak_flow, .5)
        self.assertLessEqual(peak_flow, .7001)

    def test_custom_exclusions_are_immutable_and_exclude_tower_park_and_head_swept_routes(self):
        request = self.fixture.request(make_gcode().replace("G1 X100 Y100 Z0.2 F1200",
            "G1 X0 Y220 Z0.2 F1200\nG1 X100 Y220 F6000\nG1 X100 Y100 F6000"))
        baseline = self.fixture.prepare(request)
        x, y = baseline.scene.tower_center_xy_mm
        zone = ExclusionRect(x - 2, y - 2, x + 2, y + 2)
        before = dict(request.profile.effective_values)
        result = self.fixture.prepare(replace(request, settings=replace(request.settings, exclusions=(zone,))))
        self.assertNotEqual(result.scene.tower_center_xy_mm, baseline.scene.tower_center_xy_mm)
        self.assertIn(zone.polygon, result.scene.bed_geometry.excluded_polygons)
        self.assertEqual(request.profile.effective_values, before)
        for segment in result.scene.travel_segments:
            if abs(segment.start.z - segment.end.z) > .001:
                continue
            a, b = (segment.start.x, segment.start.y), (segment.end.x, segment.end.y)
            for i, p in enumerate(zone.polygon):
                self.assertGreaterEqual(min(_point_segment_distance(a, p, zone.polygon[i - 1]),
                    _point_segment_distance(b, p, zone.polygon[i - 1]), _point_segment_distance(p, a, b)), result.printhead.radius_mm - .01)

    def test_custom_obstacle_on_original_model_or_original_travel_blocks_export(self):
        for zone in (ExclusionRect(99, 99, 106, 106), ExclusionRect(40, 40, 50, 50)):
            request = self.fixture.request()
            with self.subTest(zone=zone), self.assertRaisesRegex(ValueError, "Original-G-Code"):
                self.fixture.prepare(replace(request, settings=replace(request.settings, exclusions=(zone,))))

    def test_head_body_detects_collision_even_when_nozzle_path_misses_tower(self):
        path = self.fixture.root / "head-collision.gcode"
        path.write_text("G90\nM83\nG1 X0 Y0 Z30 F600\nG1 X0 Y5 Z1 F600\nG1 X100 Y5 F1200\n")
        self.assertTrue(original_paths_clear(path, (50, 25), 3, {3: 30}))
        self.assertFalse(original_paths_clear(path, (50, 25), 3, {3: 30}, head_radius=25, head_height=10))
        self.assertTrue(original_paths_clear(path, (50, 25), 3, {3: 30}, head_radius=25, head_height=40))
        self.assertFalse(original_paths_clear(path, (50, 25), 3, {3: 30}, head_radius=25, head_height=40, lower_head_radius=25))
        self.assertTrue(original_paths_clear(path, (200, 25), 3, {3: 30}, head_radius=25, head_height=10))
        self.assertFalse(original_paths_clear(path, (200, 25), 3, {3: 30}, head_radius=25, head_height=10, gantry_height=10))

    def test_layerwise_head_radius_does_not_impose_sequential_object_spacing(self):
        path = self.fixture.root / "same-layer.gcode"
        path.write_text("G90\nM83\nG1 X0 Y0 Z1 F600\nG1 X100 Y0 F1200\n")
        self.assertTrue(original_paths_clear(path, (50, 25), 3, {3: 1},
            head_radius=65, lower_head_radius=65, head_height=20, gantry_height=20))
        path.write_text("G90\nM83\nG1 X0 Y0 Z1 F600\nG1 X100 Y0 Z.8 F1200\n")
        self.assertFalse(original_paths_clear(path, (50, 25), 3, {3: 1},
            head_radius=65, lower_head_radius=65, head_height=20, gantry_height=20))

    def test_head_sizes_do_not_move_automatic_layerwise_positions_without_obstacles(self):
        request = self.fixture.request()
        first = self.fixture.prepare(request)
        request.profile.effective_values["extruder_clearance_radius"] = 250
        second = self.fixture.prepare(request)
        self.assertEqual(first.scene.tower_center_xy_mm, second.scene.tower_center_xy_mm)
        self.assertEqual(first.scene.wait_position_xy_mm, second.scene.wait_position_xy_mm)
        self.assertEqual(first.effective_z_hop_mm, second.effective_z_hop_mm)

    def test_parking_to_tower_avoids_model_even_when_manual_points_face_each_other(self):
        from cooling_tower.preprocessor_travel import segments_cross
        request = self.fixture.request()
        request = replace(request, settings=replace(request.settings, automatic_position=False, automatic_wait_position=False,
            center_x_mm=30, center_y_mm=105, wait_x_mm=180, wait_y_mm=105))
        result = self.fixture.prepare(request)
        polygon = ((100, 100), (110, 100), (110, 110), (100, 110))
        for _outward, park_to_tower, _back in result.placement_solution[2]:
            self.assertGreater(len(park_to_tower), 2)
            for a, b in zip(park_to_tower, park_to_tower[1:]):
                self.assertFalse(any(segments_cross(a, b, p, polygon[i-1]) for i, p in enumerate(polygon)))

    def test_rotated_seams_match_checked_paths_and_distribute_prime_while_moving(self):
        request = self.fixture.request(make_gcode(layers=12))
        result = self.fixture.prepare(request)
        starts = {}
        for segment in result.scene.tower_segments:
            starts.setdefault(round(segment.start.z, 5), segment.start)
        self.assertEqual(len(result.wipe_angles_rad), 12)
        measured = []
        for z, angle in zip(result.layer_heights_mm, result.wipe_angles_rad):
            point = starts[round(z, 5)]
            actual = math.atan2(point.y - result.scene.tower_center_xy_mm[1], point.x - result.scene.tower_center_xy_mm[0]) % math.tau
            self.assertAlmostEqual(math.cos(actual), math.cos(angle), places=5)
            self.assertAlmostEqual(math.sin(actual), math.sin(angle), places=5)
            measured.append(actual)
        self.assertEqual(len({round(value, 3) for value in measured}), 12)
        original = self.fixture.original_movements(request.prepared_source.analysis_gcode_path)
        retained = self.fixture.original_movements(result.gcode_path)
        self.assertEqual(len(original), len(retained))
        for a, b in zip(original, retained):
            self.assertEqual((a[0], a[-1]), (b[0], b[-1]))
            for before, after in zip(a[1:-1], b[1:-1]):
                self.assertAlmostEqual(before, after, places=5)
        self.assertEqual(len(result.scene.wait_travel_segments), len(result.scene.wait_travel_layer_indices))
        self.assertEqual(len(result.scene.tower_travel_segments), len(result.scene.tower_travel_layer_indices))

    def test_invalid_rectangles_or_too_many_exclusions_are_rejected(self):
        request = self.fixture.request()
        for values in ((0, 0, .1, 2), (1, 1, 0, 2), (0, 0, math.nan, 2)):
            with self.assertRaises(ValueError):
                ExclusionRect(*values)
        with self.assertRaises(ValueError):
            replace(request.settings, exclusions=(ExclusionRect(0, 0, 1, 1),) * 65)

    def test_terminal_firmware_homing_cannot_bypass_custom_unknown_height_obstacles(self):
        request = self.fixture.request(make_gcode() + "G28 X Y\n")
        original = request.prepared_source.analysis_gcode_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "Referenzfahrt"):
            self.fixture.prepare(replace(request, settings=replace(request.settings,
                exclusions=(ExclusionRect(170, 20, 180, 30),))))
        self.assertEqual(request.prepared_source.analysis_gcode_path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
