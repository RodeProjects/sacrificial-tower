"""Sufficient original layers bypass parking with the same safety/timing checks."""
from dataclasses import replace
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import test_preprocessor as fixture_module
from test_preprocessor import make_gcode
from test_preprocessor_refinements import inserted_movements
from cooling_tower.preprocessor import BEGIN, END, PreprocessorSettings, SUPPORTED_SLICERS
from cooling_tower.preprocessor_safety import ExclusionRect
from cooling_tower.preprocessor_travel import segments_cross
from cooling_tower.calibration.gcode_integration import _point_segment_distance
from cooling_tower.services.analysis_service import GCodeAnalysisService


def mixed_gcode(*, sufficient=(1, 3), relative=True):
    blocks = make_gcode(relative=relative).split(";LAYER_CHANGE")
    for index in sufficient:
        blocks[index+1] = "\n".join(line.replace(" F1200", " F40") if " E" in line and " X" in line else line
            for line in blocks[index+1].split("\n"))
    return ";LAYER_CHANGE".join(blocks)


class DirectTowerTravelTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.PreprocessorTests()
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def test_sufficient_original_layers_use_direct_checked_routes_in_all_slicers(self):
        for adapter in SUPPORTED_SLICERS:
            for sufficient in ((1, 3), (0, 2)):
                with self.subTest(adapter=adapter, sufficient=sufficient):
                    settings = PreprocessorSettings(target_layer_time_s=30,
                        automatic_position=False, center_x_mm=40, center_y_mm=40,
                        automatic_wait_position=False, wait_x_mm=40, wait_y_mm=180)
                    request = self.fixture.request(mixed_gcode(sufficient=sufficient,
                        relative=sufficient == (1, 3)), settings=settings, adapter=adapter)
                    original = request.prepared_source.analysis_gcode_path.read_bytes()
                    result = self.fixture.prepare(request)
                    blocks = [block.split(END)[0] for block in result.gcode_path.read_text().split(BEGIN)[1:]]
                    routes = result.placement_solution[2]
                    self.assertEqual(len(blocks), 6)  # Later deficient layers still need the continuous tower.
                    for index, block in enumerate(blocks):
                        if index in sufficient:
                            self.assertGreaterEqual(result.original_layer_times_s[index], 30)
                            self.assertFalse(routes[index][0])
                            self.assertNotIn("SACRIFICIAL_TOWER_TRAVEL_TO_WAIT", block)
                            self.assertNotIn("; SACRIFICIAL_TOWER_WAIT\n", block)
                            self.assertNotIn("M400", block)
                            self.assertNotIn("G4 ", block)
                            self.assertEqual(result.layer_waits_s[index], 0)
                            self.assertNotIn(index, result.scene.wait_travel_layer_indices)
                            self.assertNotIn(index, result.scene.wait_point_layer_indices)
                            self.assertIn(index, result.scene.tower_travel_layer_indices)
                            self.assertIn("; sacrificial wipe / prime and ", block)
                            to_tower = routes[index][1]
                            self.assertEqual(to_tower[0], (100, 100))
                            distance = sum(math.dist(a, b) for a, b in zip(to_tower, to_tower[1:]))
                            detour = math.dist(to_tower[0], (40, 180)) + math.dist((40, 180), to_tower[-1])
                            self.assertLess(distance, detour)
                        else:
                            self.assertLess(result.original_layer_times_s[index], 30)
                            self.assertTrue(routes[index][0])
                            self.assertIn("SACRIFICIAL_TOWER_TRAVEL_TO_WAIT", block)
                    deposited = set()
                    for index, _, event, _, _ in inserted_movements(result.gcode_path):
                        if event.category == "deposition":
                            deposited.add(index)
                        elif index in sufficient and event.endpoint_distance_xy_mm > 0:
                            minimum = result.layer_heights_mm[index] + (0 if index in deposited else result.effective_z_hop_mm)
                            self.assertGreaterEqual(event.start_z, minimum - 1e-6)
                            self.assertAlmostEqual(event.end_z, event.start_z)
                    checked = GCodeAnalysisService(preprocessor_mode=True).analyze(result.gcode_path)
                    for actual, planned in zip(checked.layers, result.layer_times_s):
                        self.assertGreaterEqual(actual.total_time_s, 30 - .005)
                        self.assertAlmostEqual(actual.total_time_s, planned, delta=.02)
                    self.assertEqual(request.prepared_source.analysis_gcode_path.read_bytes(), original)
                    before = self.fixture.original_movements(request.prepared_source.analysis_gcode_path)
                    after = self.fixture.original_movements(result.gcode_path)
                    self.assertEqual(len(before), len(after))
                    for expected, actual in zip(before, after):
                        self.assertEqual((expected[0], expected[-1]), (actual[0], actual[-1]))
                        for a, b in zip(expected[1:-1], actual[1:-1]):
                            self.assertAlmostEqual(a, b, places=5)

    def test_exact_minimum_original_time_also_bypasses_parking(self):
        request = self.fixture.request(mixed_gcode())
        raw = GCodeAnalysisService(preprocessor_mode=True).analyze(request.prepared_source.analysis_gcode_path)
        target = raw.layers[1].total_time_s
        request = replace(request, settings=replace(request.settings, target_layer_time_s=target))
        result = self.fixture.prepare(request)
        self.assertEqual(result.original_layer_times_s[1], target)
        self.assertFalse(result.placement_solution[2][1][0])
        self.assertEqual(result.layer_waits_s[1], 0)

    def test_zero_remaining_wait_from_tower_time_does_not_change_original_deficit_decision(self):
        request = self.fixture.request(settings=PreprocessorSettings(target_layer_time_s=3))
        result = self.fixture.prepare(request)
        self.assertLess(result.original_layer_times_s[0], 3)
        self.assertEqual(result.layer_waits_s[0], 0)
        self.assertTrue(result.placement_solution[2][0][0])
        first = result.gcode_path.read_text().split(BEGIN)[1].split(END)[0]
        self.assertIn("M400", first)
        self.assertIn("G4 P0", first)

    def test_manual_tower_with_no_original_deficits_contains_no_parking_travel(self):
        request = self.fixture.request(settings=PreprocessorSettings(target_layer_time_s=.1,
            automatic_height=False, height_mm=1.2))
        result = self.fixture.prepare(request)
        self.assertEqual(result.scene.tower_layer_count, 6)
        self.assertFalse(result.scene.wait_travel_segments)
        self.assertFalse(result.scene.wait_points)
        self.assertTrue(result.scene.tower_travel_segments)
        self.assertNotIn("SACRIFICIAL_TOWER_WAIT", result.gcode_path.read_text())

    def test_direct_route_still_detours_around_physical_exclusion_with_head_margin(self):
        text = mixed_gcode().replace("G1 X100 Y100 Z0.2 F1200",
            "G1 X0 Y100 Z0.2 F1200\nG1 X100 Y100 F6000")
        zone = ExclusionRect(65, 65, 75, 75)
        settings = PreprocessorSettings(target_layer_time_s=30, automatic_position=False,
            center_x_mm=30, center_y_mm=30, automatic_wait_position=False,
            wait_x_mm=30, wait_y_mm=180, exclusions=(zone,))
        result = self.fixture.prepare(self.fixture.request(text, settings=settings))
        to_wait, to_tower, _ = result.placement_solution[2][1]
        self.assertFalse(to_wait)
        self.assertGreater(len(to_tower), 2)
        for a, b in zip(to_tower, to_tower[1:]):
            for index, p in enumerate(zone.polygon):
                q = zone.polygon[index-1]
                self.assertFalse(segments_cross(a, b, p, q))
                self.assertGreaterEqual(min(_point_segment_distance(a, p, q), _point_segment_distance(b, p, q),
                    _point_segment_distance(p, a, b), _point_segment_distance(q, a, b)), result.printhead.radius_mm + 1 - 1e-6)


if __name__ == "__main__":
    unittest.main()
