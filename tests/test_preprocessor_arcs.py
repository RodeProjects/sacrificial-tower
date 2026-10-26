"""Arc fitting must preserve curved-path safety without blocking the whole bed."""
from dataclasses import replace
import math
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import test_preprocessor as fixture
from cooling_tower.preprocessor_placement import OriginalMotionIndex
from cooling_tower.preprocessor_safety import ExclusionRect
from cooling_tower.preprocessor_travel import original_exclusions_clear


class PreprocessorArcTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.PreprocessorTests()
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def capture(self, text, insertions=None):
        path = self.fixture.root / "arcs.gcode"
        path.write_text(text, encoding="utf-8")
        return path, OriginalMotionIndex.capture(path, insertions or {})

    def test_short_large_radius_arcs_leave_distant_positions_free(self):
        # A 5 mm chord on a 2 m circle represents an almost straight model edge.
        for direction in ("G2", "G3"):
            with self.subTest(direction=direction):
                offset = -2000 if direction == "G2" else 2000
                _, index = self.capture("G90\nM83\nG1 X100 Y100 Z.2 F1200\n"
                    f"{direction} X105 Y100 I2.5 J{offset} E.2\n")
                self.assertTrue(index.model_clear((40, 40), 20, lambda z: 20))
                self.assertFalse(index.model_clear((102.5, 100), 1, lambda z: 1))

    def test_placement_editor_and_generation_accept_arc_fitted_models(self):
        for adapter in ("bambu_studio", "prusa_slicer", "orca_slicer", "anycubic_slicer_next"):
            with self.subTest(adapter=adapter):
                text = fixture.make_gcode().replace("G1 X110 Y100 E", "G3 X110 Y100 I5 J2000 E")
                request = self.fixture.request(text, adapter=adapter)
                original = request.prepared_source.analysis_gcode_path.read_bytes()
                context = self.fixture.service.placement_context(request)
                center, wait, _ = context.resolve()
                settings = replace(context.settings, automatic_position=False, automatic_wait_position=False,
                    center_x_mm=center[0], center_y_mm=center[1], wait_x_mm=wait[0], wait_y_mm=wait[1])
                for kind, point in (("tower", center), ("wait", wait)):
                    self.assertTrue(context.position_valid(kind, point, settings))
                    regions = context.regions.regions(kind, settings)
                    self.assertIn(1, regions.states)
                    bounds = regions.bounds
                    green = np.flatnonzero(np.frombuffer(regions.states, dtype=np.uint8))
                    dx = (bounds.maximum_x_mm-bounds.minimum_x_mm)/regions.columns
                    dy = (bounds.maximum_y_mm-bounds.minimum_y_mm)/regions.rows
                    for i in green[::max(1, len(green)//12)]:
                        x = bounds.minimum_x_mm+(i % regions.columns+.5)*dx
                        y = bounds.maximum_y_mm-(i // regions.columns+.5)*dy
                        for ox, oy in ((-dx/2, -dy/2), (-dx/2, dy/2), (dx/2, -dy/2), (dx/2, dy/2)):
                            self.assertTrue(context.position_valid(kind, (x+ox, y+oy), settings))
                result = self.fixture.prepare(request)
                exported = self.fixture.service.export(result, self.fixture.root / f"{adapter}.gcode")
                self.assertTrue(exported.is_file())
                self.assertEqual(request.prepared_source.analysis_gcode_path.read_bytes(), original)
                self.assertTrue(all(t >= request.settings.target_layer_time_s-.01 for t in result.layer_times_s))
                before = self.fixture.original_movements(request.prepared_source.analysis_gcode_path)
                after = self.fixture.original_movements(result.gcode_path)
                self.assertEqual(len(before), len(after))
                for a, b in zip(before, after):
                    self.assertEqual((a[0], a[-1]), (b[0], b[-1]))
                    for old, new in zip(a[1:-1], b[1:-1]):
                        self.assertAlmostEqual(old, new, places=5)

    def test_arc_bulge_is_blocked_but_chord_interior_is_free(self):
        for command, sign in (("G2", 1), ("G3", -1)):
            with self.subTest(command=command):
                _, index = self.capture("G90\nM83\nG1 X80 Y100 Z.2 F1200\n"
                    f"{command} X120 Y100 I20 J0 E1\n", {3: .2})
                self.assertFalse(index.model_clear((100, 100+sign*20), .1, lambda z: .1))
                self.assertTrue(index.model_clear((100, 100), 1, lambda z: 1))
                self.assertIsNotNone(index.tower_rejection((100, 100+sign*20), 1))
                self.assertIsNone(index.tower_rejection((100, 100-sign*20), 1))

    def test_full_circle_retains_every_quadrant_and_leaves_its_center_free(self):
        for command in ("G2", "G3"):
            with self.subTest(command=command):
                _, index = self.capture("G90\nM83\nG1 X80 Y100 Z.2 F1200\n"
                    f"{command} X80 Y100 I20 J0 E1\n")
                self.assertTrue(index.model_clear((100, 100), 1, lambda z: 1))
                for i in range(361):
                    angle = math.radians(i)
                    point = (100+20*math.cos(angle), 100+20*math.sin(angle))
                    self.assertFalse(index.model_clear(point, .0001, lambda z: .0001), point)

    def test_modal_centers_radii_units_and_major_arcs_follow_the_actual_sweep(self):
        cases = (
            ("", "G3 X100 Y80 I20 J0 E1", math.pi/2),
            ("G90.1\n", "G3 X100 Y80 I100 J100 E1", math.pi/2),
            ("G91\n", "G3 X20 Y-20 I20 J0 E1", math.pi/2),
            ("", "G3 X100 Y80 R20 E1", math.pi/2),
            ("", "G2 X100 Y80 R-20 E1", -3*math.pi/2),
            ("G20\n", "G3 X3.937007874015748 Y3.149606299212598 R.7874015748031496 E1", math.pi/2),
        )
        for mode, command, sweep in cases:
            with self.subTest(mode=mode, command=command):
                _, index = self.capture("G90\nM83\nG1 X80 Y100 Z.2 F1200\n"+mode+command+"\n")
                for i in range(101):
                    theta = math.pi+sweep*i/100
                    point = (100+20*math.cos(theta), 100+20*math.sin(theta))
                    self.assertFalse(index.model_clear(point, .0001, lambda z: .0001), point)
                self.assertTrue(index.model_clear((100, 100), 1, lambda z: 1))
                # A point on the complementary, untraversed quarter stays free.
                missing = (85.858 if sweep < 0 else 114.142, 85.858)
                self.assertTrue(index.model_clear(missing, 1, lambda z: 1))

    def test_helix_retains_heights_and_chronology_after_the_insertion(self):
        _, index = self.capture("G90\nM83\nG1 X80 Y100 Z20 F1200\n"
            "G3 X120 Y100 Z.2 I20 J0 E1\n", {3: 20})
        self.assertFalse(index.model_clear((100, 80), .001, lambda z: .001, height=11))
        self.assertTrue(index.model_clear((100, 80), .001, lambda z: .001, height=5))
        self.assertIsNotNone(index.tower_rejection((100, 80), 1))

    def test_vertical_plane_arcs_retain_their_xy_projection_and_lowest_z(self):
        for plane, start, end, center, point in (
            ("G18", "X100 Y100 Z80", "X100 Y100 Z120", "K20 I0", (120, 100)),
            ("G19", "X100 Y80 Z100", "X100 Y120 Z100", "J20 K0", (100, 100)),
        ):
            with self.subTest(plane=plane):
                _, index = self.capture(f"G90\nM83\n{plane}\nG1 {start} F1200\nG2 {end} {center} E1\n")
                self.assertFalse(index.model_clear(point, .01, lambda z: .01))
                self.assertTrue(index.model_clear((40, 40), 1, lambda z: 1))

    def test_rounded_arc_endpoints_keep_the_radial_mismatch_reserved(self):
        _, index = self.capture("G90\nM83\nG1 X80 Y100 Z.2 F1200\n"
            "G3 X120.005 Y100 I20 J0 E1\n")
        for radius in (20, 20.0025, 20.005):
            point = (100, 100-radius)
            self.assertFalse(index.model_clear(point, .0001, lambda z: .0001))

    def test_invalid_arc_geometry_blocks_placement(self):
        with self.assertRaisesRegex(ValueError, "Kreisbogen.*sicher"):
            self.capture("G90\nM83\nG1 X80 Y100 Z.2 F1200\nG3 X120 Y100 R1 E1\n")

    def test_subdivision_limit_keeps_the_remaining_deviation_reserved(self):
        _, index = self.capture("G90\nM83\nG1 X0 Y0 Z.2 F1200\nG3 X0 Y0 I1000000 J0 E1\n")
        self.assertEqual(index.deposition_count, 1)
        self.assertTrue(index.model_clear((1000000, 0), 1, lambda z: 1))
        for i in range(100):
            angle = math.tau*(i+.37)/100
            point = (1000000+1000000*math.cos(angle), 1000000*math.sin(angle))
            self.assertFalse(index.model_clear(point, .0001, lambda z: .0001))

    def test_custom_obstacles_use_arc_path_instead_of_entire_circle_radius(self):
        path, _ = self.capture("G90\nM83\nG1 X100 Y100 Z.2 F1200\n"
            "G3 X105 Y100 I2.5 J2000 E.2\n")
        original_exclusions_clear(path, (ExclusionRect(160, 160, 170, 170).polygon,), 12)
        with self.assertRaisesRegex(ValueError, "Original-G-Code"):
            original_exclusions_clear(path, (ExclusionRect(101, 99, 104, 101).polygon,), 0)
        path, _ = self.capture("G90\nM83\nG1 X80 Y100 Z.2 F1200\n"
            "G3 X120 Y100 I20 J0 E1\n")
        # The obstacle intersects the bulge, although the endpoint chord misses it.
        with self.assertRaisesRegex(ValueError, "Original-G-Code"):
            original_exclusions_clear(path, (ExclusionRect(99, 79, 101, 81).polygon,), 0)


if __name__ == "__main__":
    unittest.main()
