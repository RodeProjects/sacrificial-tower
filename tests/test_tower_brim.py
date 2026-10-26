"""Independent tower adhesion, physical extrusion and the wider foot outline."""
from copy import deepcopy
from dataclasses import replace
import json
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import test_preprocessor as fixture_module
from cooling_tower.gcode.parser import MachineStateTracker, Movement, iter_parsed_gcode_lines
from cooling_tower.preprocessor import PreprocessorSettings, SUPPORTED_SLICERS
from cooling_tower.preprocessor_profiles import resolve_profile_settings
from cooling_tower.preprocessor_export import export_preprocessor_run
from cooling_tower.tower.diameter_transitions import full_infill_foot_taper


class TowerBrimTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.PreprocessorTests()
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def test_model_brim_width_and_enablement_never_control_tower_adhesion(self):
        for adapter in SUPPORTED_SLICERS:
            for kind, width in (("none", 0), ("outer_only", 18), ("inner_only", 5)):
                with self.subTest(adapter=adapter, kind=kind):
                    request = self.fixture.request(adapter=adapter)
                    request.profile.effective_values.update({"brim_type": kind, "brim_width": width,
                        "brim_separation" if adapter == "prusa_slicer" else "brim_object_gap": .15})
                    before = deepcopy(request.profile.effective_values)
                    source = request.prepared_source.analysis_gcode_path.read_bytes()
                    result = self.fixture.prepare(request)
                    self.assertEqual(result.placement.brim_width_mm, .2)
                    self.assertEqual(result.placement.brim_gap_mm, .15)
                    self.assertTrue(result.scene.brim_segments)
                    self.assertEqual(request.profile.effective_values, before)
                    self.assertEqual(request.prepared_source.analysis_gcode_path.read_bytes(), source)

    def test_manual_zero_disables_tower_brim_even_with_model_brim_enabled(self):
        settings = PreprocessorSettings(automatic_tower_brim_width=False, tower_brim_width_mm=0)
        request = self.fixture.request(settings=settings)
        request.profile.effective_values.update({"brim_type": "outer_only", "brim_width": 20, "brim_separation": 4})
        result = self.fixture.prepare(request)
        self.assertFalse(result.scene.brim_segments)
        self.assertEqual(result.placement.brim_line_width_mm, 0)
        self.assertNotIn("SACRIFICIAL_TOWER_BRIM_BEGIN", result.gcode_path.read_text())
        self.assertLess(result.placement.reserved_radius_mm, result.base_width_mm/2 + 1)

    def test_manual_width_and_gap_define_physical_envelope_and_placement(self):
        for width in (.1, 3, 20):
            settings = PreprocessorSettings(automatic_tower_brim_width=False, tower_brim_width_mm=width,
                automatic_tower_brim_gap=False, tower_brim_gap_mm=.7)
            request = self.fixture.request(settings=settings)
            request.profile.effective_values.update({"brim_width": 0, "brim_object_gap": .1})
            result = self.fixture.prepare(request)
            center = result.scene.tower_center_xy_mm
            radii = [math.dist((p.x, p.y), center) for s in result.scene.brim_segments for p in (s.start, s.end)]
            line_width = min(width, result.placement.brim_line_width_mm)
            self.assertAlmostEqual(max(radii) + line_width/2, result.base_width_mm/2 + .7 + width, places=5)
            self.assertAlmostEqual(min(radii) - line_width/2, result.base_width_mm/2 + .7, places=5)
            self.assertAlmostEqual(result.placement.reserved_radius_mm, result.base_width_mm/2 + .7 + width)
            self.assertEqual({round(s.end.z, 5) for s in result.scene.brim_segments}, {.2})

    def test_brim_uses_slicer_first_layer_then_inner_then_general_line_width(self):
        cases = (
            ("prusa_slicer", {"first_layer_extrusion_width": "250%", "perimeter_extrusion_width": .6}, .5),
            ("prusa_slicer", {"first_layer_extrusion_width": 0, "perimeter_extrusion_width": .6,
                "external_perimeter_extrusion_width": .3}, .6),
            ("prusa_slicer", {"perimeter_extrusion_width": 0, "extrusion_width": .55}, .55),
            ("orca_slicer", {"initial_layer_line_width": "150%", "inner_wall_line_width": .5}, .6),
            ("bambu_studio", {"initial_layer_line_width": 0, "inner_wall_line_width": .5,
                "outer_wall_line_width": .3}, .5),
            ("anycubic_slicer_next", {"inner_wall_line_width": 0, "line_width": .55}, .55),
        )
        for adapter, values, expected in cases:
            with self.subTest(adapter=adapter, values=values):
                request = self.fixture.request(adapter=adapter, settings=PreprocessorSettings(
                    automatic_tower_brim_width=False, tower_brim_width_mm=3))
                request.profile.effective_values.update(values)
                result = self.fixture.prepare(request)
                self.assertAlmostEqual(result.placement.brim_line_width_mm, expected)
                tracker, active, checked = MachineStateTracker(), False, False
                for line in iter_parsed_gcode_lines(result.gcode_path):
                    if line.raw_text == "; SACRIFICIAL_TOWER_BRIM_BEGIN":
                        active = True
                    elif line.raw_text == "; SACRIFICIAL_TOWER_BRIM_END":
                        active = False
                    event = tracker.process_line(line)
                    if active and isinstance(event, Movement) and event.category == "deposition":
                        area = event.delta_e * tracker.state.extrusion_factor * math.pi * .875**2 / event.endpoint_distance_xy_mm
                        self.assertAlmostEqual(area, (expected - .2 * (1-math.pi/4)) * .2, delta=1e-5)
                        checked = True
                self.assertTrue(checked)

    def test_gap_automation_reads_zero_and_falls_back_without_a_profile_value(self):
        for profile, expected in (({}, .2), ({"brim_separation": 0}, 0),
                ({"brim_object_gap": [.35]}, .35), ({"brim_separation": "bad"}, .2)):
            effective, _ = resolve_profile_settings(PreprocessorSettings(tower_brim_width_mm=19), profile)
            self.assertEqual(effective.tower_brim_width_mm, .2)
            self.assertEqual(effective.tower_brim_gap_mm, expected)
        manual = PreprocessorSettings(automatic_tower_brim_width=False, tower_brim_width_mm=7,
            automatic_tower_brim_gap=False, tower_brim_gap_mm=1)
        self.assertEqual(resolve_profile_settings(manual, {"brim_separation": .15})[0], manual)

    def test_new_setting_ranges_and_types_are_validated(self):
        for changes in ({"tower_brim_width_mm": -1}, {"tower_brim_width_mm": 20.01},
                {"tower_brim_width_mm": True}, {"tower_brim_gap_mm": float("nan")},
                {"automatic_tower_brim_gap": False, "tower_brim_gap_mm": .09},
                {"automatic_tower_brim_gap": False, "tower_brim_gap_mm": 1.01},
                {"automatic_tower_brim_width": 1}, {"automatic_tower_brim_gap": "yes"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                PreprocessorSettings(**changes)
        for gap in (.1, 1):
            PreprocessorSettings(automatic_tower_brim_gap=False, tower_brim_gap_mm=gap)

    def test_export_records_effective_independent_brim(self):
        request = self.fixture.request()
        request.profile.effective_values.update({"brim_width": 8, "brim_object_gap": .15})
        result = self.fixture.prepare(request)
        exported = export_preprocessor_run(self.fixture.service, result, self.fixture.root / "exports")
        report = json.loads(exported.report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["tower_brim"]["width_mm"], .2)
        self.assertEqual(report["tower_brim"]["gap_mm"], .15)
        self.assertAlmostEqual(report["tower_brim"]["line_width_mm"], .2)
        self.assertIn("Turm-Brim Breite: 0.20 mm", exported.user_report_path.read_text(encoding="utf-8"))

    def test_second_foot_layer_is_broader_for_real_and_variable_layer_heights(self):
        for z in (tuple(.2*i for i in range(1, 61)), (.3, .4, .7) + tuple(.7+.2*i for i in range(1, 50))):
            old = full_infill_foot_taper(z, 10, 2, z[-1])
            old = replace(old, foot_start_fraction=0)
            new = full_infill_foot_taper(z, 12.5, 2, z[-1])
            self.assertEqual(new.radius(z[0]), 1.25 * old.radius(z[0]))
            self.assertGreater(new.radius(z[1]), 1.3 * old.radius(z[1]))
            self.assertAlmostEqual(new.radius(z[2]), replace(new, foot_start_fraction=0).radius(z[2]))
            self.assertAlmostEqual(new.radius(z[-1]), 2)
            values = [new.radius(height) for height in z]
            self.assertTrue(all(a >= b >= 2 for a, b in zip(values, values[1:])))
        for z in ((.2,), (.2, .4), (.2, .3, .6)):
            foot = full_infill_foot_taper(z, 10, 2, 10)
            self.assertEqual(foot.radius(z[0]), 10)
            if len(z) > 1:
                self.assertAlmostEqual(foot.radius(z[-1]), 2)


if __name__ == "__main__":
    unittest.main()
