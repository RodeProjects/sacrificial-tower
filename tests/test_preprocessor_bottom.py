"""Bottom-surface semantics and the open core of the annular tower foot."""
from dataclasses import replace
import math
import unittest

from cooling_tower.calibration.gcode_integration import _point_segment_distance
from cooling_tower.gcode.parser import MachineStateTracker, Movement, iter_parsed_gcode_lines
from cooling_tower.preprocessor import BEGIN, END, PreprocessorSettings, SUPPORTED_SLICERS
from cooling_tower.preprocessor_features import FeatureComments
from cooling_tower.preprocessor_toolpaths import tower_paths
import test_preprocessor as fixture_module
from test_preprocessor import make_gcode


class BottomToolpathTests(unittest.TestCase):
    def test_bottom_rejects_width_that_cannot_form_its_perimeter(self):
        with self.assertRaisesRegex(ValueError, "Linienbreite"):
            list(tower_paths((0, 0), 1.5, 1.5, 1.6, 1.6, .2, 2,
                hollow=True, first=True, angle=0))

    def test_second_bottom_is_solid_with_crossed_surface_and_third_layer_is_hollow(self):
        first = list(tower_paths((0, 0), 7, 3, .44, .44, .2, 2, hollow=True, first=True, angle=0))
        second = list(tower_paths((0, 0), 6.8, 3, .44, .44, .2, 2, hollow=True,
            first=False, closed_bottom=True, angle=1))
        self.assertTrue(all(p.feature == "solid" for p in second[2:]))
        a, b = first[-1].points
        c, d = second[-1].points
        self.assertAlmostEqual((b[0]-a[0])*(d[0]-c[0])+(b[1]-a[1])*(d[1]-c[1]), 0)
        self.assertLess(min(_point_segment_distance((0, 0), a, b)
            for p in second for a, b in zip(p.points, p.points[1:])), .22)

    def test_bottom_is_dense_parallel_surface_after_the_requested_perimeters(self):
        for walls in (1, 2, 3):
            paths = list(tower_paths((0, 0), 7, 3, .5, .5, .2, walls, hollow=True, first=True, angle=0))
            self.assertEqual([p.feature for p in paths[:walls]], ["outer"]+["inner"]*(walls-1))
            self.assertTrue(all(p.feature == "bottom" and p.width == .5 for p in paths[walls:]))
            for path in paths[walls:]:
                a, b = path.points
                self.assertAlmostEqual(abs(b[0]-a[0]), abs(b[1]-a[1]))
            # Check actual coverage independently of the path construction.
            for x in range(-48, 49, 6):
                for y in range(-48, 49, 6):
                    point = x/10, y/10
                    if math.hypot(*point) < 4.8:
                        self.assertTrue(any(_point_segment_distance(point, a, b) <= p.width/2+.01
                            for p in paths for a, b in zip(p.points, p.points[1:])), (walls, point))

    def test_annular_foot_has_a_fixed_open_core_and_fills_the_outer_band(self):
        for walls in (1, 2, 3):
            for radius in (7, 5, 3.1, 3):
                paths = list(tower_paths((0, 0), radius, 3, .44, .44, .2, walls, hollow=True, first=False, angle=.7))
                hole = 3-(.44+(walls-1)*(.44-.2*(1-math.pi/4)))
                self.assertAlmostEqual(math.dist((0, 0), paths[0].points[0])+paths[0].width/2, radius)
                for p in paths:
                    self.assertGreater(p.width, .2)
                    self.assertNotEqual(p.feature, "bottom")
                    for a, b in zip(p.points, p.points[1:]):
                        self.assertGreaterEqual(_point_segment_distance((0, 0), a, b)-p.width/2, hole-.035)
                if radius == 3:
                    self.assertEqual(len(paths), walls)
                    self.assertTrue(all(abs(p.width-.44) < 1e-8 for p in paths))
                if radius > 3.1:
                    for r in (3.05, (radius+3)/2, radius-.05):
                        for i in range(16):
                            point = r*math.cos(i*math.tau/16), r*math.sin(i*math.tau/16)
                            self.assertTrue(any(_point_segment_distance(point, a, b) <= p.width/2+.01
                                for p in paths for a, b in zip(p.points, p.points[1:])), (walls, radius, point))


class BottomGCodeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.PreprocessorTests()
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def test_all_slicers_get_bottom_surface_widths_and_restore_original_viewer_state(self):
        for adapter in SUPPORTED_SLICERS:
            with self.subTest(adapter=adapter):
                native = adapter == "bambu_studio"
                role, width, height = (("; FEATURE: Gap infill", "; LINE_WIDTH: 0.08", "; LAYER_HEIGHT: 0.2")
                    if native else (";TYPE:Gap fill" if adapter == "prusa_slicer" else ";TYPE:Gap infill", ";WIDTH:0.08", ";HEIGHT:0.2"))
                wipe = "; WIPE_START" if native else ";WIPE_START"
                source = []
                for line in make_gcode(layers=45).splitlines():
                    closing = line.startswith("G1 X100 Y100 E")
                    if closing:
                        source.extend((role, width, height, wipe))
                    source.append(line)
                    if closing:
                        source.append(wipe.replace("START", "END"))
                request = self.fixture.request("\n".join(source)+"\n", adapter=adapter,
                    settings=replace(PreprocessorSettings(), automatic_base=False, base_width_mm=20,
                        automatic_diameter=False, diameter_mm=6))
                original = request.prepared_source.analysis_gcode_path.read_bytes()
                result = self.fixture.prepare(request)
                blocks = result.gcode_path.read_text().split(BEGIN)[1:]
                bottom = ";TYPE:Solid infill" if adapter == "prusa_slicer" else "; FEATURE: Bottom surface" if native else ";TYPE:Bottom surface"
                self.assertIn(bottom, blocks[0])
                if adapter != "prusa_slicer":
                    self.assertTrue(all(bottom not in b for b in blocks[1:]))
                for block in blocks:
                    before_end = block.split(END)[0]
                    self.assertEqual(before_end.rstrip().splitlines()[-4:], [role, width, height, wipe])
                    self.assertIn(wipe.replace("START", "END"), before_end.splitlines()[:5])
                tracker, active, layer, declared_width, feature = MachineStateTracker(), False, -1, None, ""
                bottom_lines = 0
                for line in iter_parsed_gcode_lines(result.gcode_path):
                    if line.raw_text == BEGIN:
                        active, layer = True, layer+1
                    if active and line.raw_text.startswith((";TYPE:", "; FEATURE:")):
                        feature = line.raw_text
                    if active and line.raw_text.startswith((";WIDTH:", "; LINE_WIDTH:")):
                        declared_width = float(line.raw_text.partition(":")[2])
                    event = tracker.process_line(line)
                    if active and isinstance(event, Movement) and event.category == "deposition" and event.endpoint_distance_xy_mm > 0:
                        self.assertNotIn("Gap", feature)
                        if layer == 0 and feature == bottom:
                            bottom_lines += 1
                            self.assertAlmostEqual(declared_width, result.first_layer.line_width_mm)
                            section = event.delta_e*tracker.state.extrusion_factor*math.pi*.875**2/event.endpoint_distance_xy_mm
                            h = request.snapshot.layers[0].height_mm
                            self.assertAlmostEqual(section, declared_width*h-h*h*(1-math.pi/4), delta=1e-5)
                    if line.raw_text == END:
                        active = False
                self.assertGreater(bottom_lines, 10)
                # Only the first two layers close the core; the third is open.
                centre = result.scene.tower_center_xy_mm
                second = [s for s in result.scene.tower_segments if abs(s.end.z-.4) < 1e-6]
                third = [s for s in result.scene.tower_segments if abs(s.end.z-.6) < 1e-6]
                self.assertTrue(third)
                self.assertLess(min(_point_segment_distance(centre, (s.start.x, s.start.y), (s.end.x, s.end.y)) for s in second), .25)
                self.assertGreater(min(_point_segment_distance(centre, (s.start.x, s.start.y), (s.end.x, s.end.y)) for s in third), 2)
                self.assertEqual(request.prepared_source.analysis_gcode_path.read_bytes(), original)

    def test_comment_dialect_follows_source_and_missing_width_restores_automatic_detection(self):
        comments = FeatureComments.for_adapter("orca_slicer")
        comments.observe("; FEATURE: Outer wall")
        self.assertTrue(comments.native)
        self.assertIn("; LINE_WIDTH: 0", comments.restore())
        comments.observe(";TYPE:Inner wall")
        self.assertFalse(comments.native)
        self.assertEqual(comments.restore(), [";TYPE:Inner wall", ";WIDTH:0", ";HEIGHT:0", ";WIPE_END"])

    def test_two_closed_bottoms_do_not_duplicate_profile_brim(self):
        request = self.fixture.request(adapter="anycubic_slicer_next")
        request.profile.effective_values.update({"brim_type": "outer_only", "brim_width": 4})
        result = self.fixture.prepare(request)
        self.assertTrue(result.scene.brim_segments)
        self.assertEqual({round(s.end.z, 6) for s in result.scene.brim_segments}, {result.layer_heights_mm[0]})
        second = result.gcode_path.read_text().split(BEGIN)[2].split(END)[0]
        self.assertNotIn("SACRIFICIAL_TOWER_BRIM_BEGIN", second)
        self.assertIn(";TYPE:Internal solid infill", second)
