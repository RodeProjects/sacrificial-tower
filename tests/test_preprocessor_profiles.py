from dataclasses import replace
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cooling_tower.preprocessor import PreprocessorSettings
from cooling_tower.preprocessor_profiles import resolve_profile_settings, flow_limited_speed, printhead_envelope
from cooling_tower.calibration.gcode_integration import parse_bed_geometry


class PreprocessorProfileTests(unittest.TestCase):
    def test_native_keys_percentages_and_filament_overrides(self):
        for values in (
            {"slow_down_layer_time": ["12"], "retraction_length": ["1.5"], "filament_retraction_length": ["0"],
                "retraction_speed": ["35"], "filament_retraction_speed": ["nil"], "outer_wall_speed": "75%", "inner_wall_speed": 80,
                "travel_speed": 300, "machine_max_speed_x": [120], "machine_max_speed_y": [150]},
            {"slowdown_below_layer_time": "12", "retract_length": "1.5", "filament_retract_length": "0",
                "retract_speed": "35", "external_perimeter_speed": "75%", "perimeter_speed": 80,
                "travel_speed": 300, "machine_max_feedrate_x": 120, "machine_max_feedrate_y": 150},
        ):
            with self.subTest(values=values):
                before = dict(values)
                effective, notes = resolve_profile_settings(PreprocessorSettings(automatic_target_time=True), values)
                self.assertEqual((effective.target_layer_time_s, effective.retract_mm, effective.retract_speed_mm_s,
                    effective.print_speed_mm_s, effective.travel_speed_mm_s), (12, 0, 35, 60, 120))
                self.assertTrue(notes)
                self.assertEqual(values, before)

    def test_manual_overrides_stay_manual_and_disabled_cooling_uses_fallback(self):
        settings = replace(PreprocessorSettings(), target_layer_time_s=25, automatic_target_time=False,
            retract_mm=2, automatic_retraction=False, print_speed_mm_s=17, automatic_print_speed=False,
            travel_speed_mm_s=33, automatic_travel_speed=False)
        actual, _ = resolve_profile_settings(settings, {"slow_down_layer_time": 4, "retraction_length": .2,
            "outer_wall_speed": 90, "travel_speed": 250})
        self.assertEqual(actual, settings)
        actual, notes = resolve_profile_settings(PreprocessorSettings(automatic_target_time=True), {"slowdown_below_layer_time": 4, "cooling": "0"})
        self.assertEqual(actual.target_layer_time_s, PreprocessorSettings().target_layer_time_s)
        self.assertTrue(any("deaktiviert" in note for note in notes))
        actual, notes = resolve_profile_settings(PreprocessorSettings(automatic_target_time=True), {"slow_down_layer_time": 4, "slow_down_for_layer_cooling": ["0"],
            "deretraction_speed": ["22"]})
        self.assertEqual(actual.target_layer_time_s, PreprocessorSettings().target_layer_time_s)
        self.assertEqual(actual.unretract_speed_mm_s, 22)

    def test_default_minimum_time_is_manual_ten_seconds_even_with_profile_value(self):
        settings = PreprocessorSettings()
        self.assertEqual(settings.target_layer_time_s, 10)
        self.assertFalse(settings.automatic_target_time)
        effective, _ = resolve_profile_settings(settings, {"slow_down_layer_time": 18})
        self.assertEqual(effective.target_layer_time_s, 10)
        automatic, _ = resolve_profile_settings(replace(settings, automatic_target_time=True), {"slow_down_layer_time": 18})
        self.assertEqual(automatic.target_layer_time_s, 18)

    def test_invalid_or_missing_profile_values_are_reported_without_nan_or_free_text(self):
        settings = PreprocessorSettings()
        result, notes = resolve_profile_settings(settings, {"slow_down_layer_time": float("nan"),
            "retract_length": -1, "travel_speed": "secret-profile-name", "outer_wall_speed": True})
        self.assertEqual(result, settings)
        self.assertTrue(any("Ersatzwert" in note for note in notes))
        self.assertNotIn("secret-profile-name", str(notes))

    def test_flow_limit_uses_widest_line_and_actual_variable_heights(self):
        settings = replace(PreprocessorSettings(), print_speed_mm_s=100)
        result = flow_limited_speed(settings, {"filament_max_volumetric_speed": ["3"], "max_volumetric_speed": 0}, (.45, .6), (.1, .3))
        area = (.6 - .3 * (1 - math.pi / 4)) * .3
        self.assertAlmostEqual(result.print_speed_mm_s * area, 3)
        self.assertEqual(flow_limited_speed(settings, {"max_volumetric_speed": 0}, (.4,), (.2,)), settings)
        with self.assertRaisesRegex(ValueError, "Maschinenbegrenzung"):
            resolve_profile_settings(PreprocessorSettings(), {"machine_max_speed_x": .5})

    def test_four_slicer_envelopes_take_largest_radius_and_lowest_clearance(self):
        geometry = parse_bed_geometry({"bed_shape": ["0x0", "250x0", "250x250", "0x250"]})
        for adapter, values, expected in (
            ("prusa", {"extruder_clearance_radius": 45, "extruder_clearance_height": 13}, (45, 13)),
            ("orca", {"extruder_clearance_radius": "45", "extruder_clearance_height_to_rod": "30", "extruder_clearance_height_to_lid": 250}, (45, 30)),
            ("anycubic", {"extruder_clearance_radius": "65", "extruder_clearance_height_to_rod": "20"}, (65, 20)),
            ("bambu", {"extruder_clearance_radius": 13, "extruder_clearance_max_radius": 60,
                "extruder_clearance_dist_to_rod": 33, "extruder_clearance_height_to_rod": 32.8}, (60, 32.8)),
        ):
            with self.subTest(adapter=adapter):
                head = printhead_envelope(values, geometry)
                self.assertEqual((head.radius_mm, head.clearance_height_mm), expected)
                self.assertFalse(head.estimated)
        for values in ({}, {"extruder_clearance_radius": float("nan")}, {"extruder_clearance_radius": True},
                {"extruder_clearance_radius": 45}):
            head = printhead_envelope(values, geometry)
            self.assertTrue(head.estimated)
            self.assertGreaterEqual(head.radius_mm, 45)
            self.assertEqual(head.clearance_height_mm, 0)
            self.assertIn("unvollständig", head.note)


if __name__ == "__main__":
    unittest.main()
