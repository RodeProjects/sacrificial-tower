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
    def setUp(self):
        self.fixture = fixture_module.PreprocessorTests()
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def test_fallback_for_each_slicer_has_visible_warning_larger_hop_and_clear_routes(self):
        for adapter in SUPPORTED_SLICERS:
            with self.subTest(adapter=adapter):
                request = self.fixture.request(adapter=adapter)
                request.profile.effective_values.pop("extruder_clearance_radius")
                request.profile.effective_values.pop("extruder_clearance_height")
                result = self.fixture.prepare(request)
                self.assertTrue(result.printhead.estimated)
                self.assertIn(result.printhead.note, result.scene.notes)
                self.assertGreaterEqual(result.effective_z_hop_mm, 2)
                self.assertGreaterEqual(math.dist(result.scene.wait_position_xy_mm, result.scene.tower_center_xy_mm),
                    result.base_width_mm / 2 + result.printhead.radius_mm)
                self.assertTrue(result.scene.wait_travel_segments)
                self.assertTrue(result.scene.tower_travel_segments)
                self.assertTrue(all(t >= result.effective_settings.target_layer_time_s - .01 for t in result.layer_times_s))

    def test_profile_values_and_flow_limit_are_used_in_actual_gcode_with_speed_override(self):
        request = self.fixture.request(make_gcode(layers=5).replace("M201 X", "M220 S200\nM221 S150\nM201 X"))
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
            if parsed.raw_text.endswith("PREPROCESSOR_END"):
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
