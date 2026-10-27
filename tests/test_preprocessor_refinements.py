"""Independent numerical checks and larger placement/restart regressions."""
from dataclasses import replace
import math
from threading import Event
import unittest

import test_preprocessor as fixture_module
from test_preprocessor import make_gcode
from cooling_tower.preprocessor import BEGIN, END, PreprocessorSettings
from cooling_tower.preprocessor_placement import OriginalMotionIndex
from cooling_tower.preprocessor_profiles import first_layer_parameters, resolve_profile_settings
from cooling_tower.gcode.parser import MachineStateTracker, Movement, iter_parsed_gcode_lines
from cooling_tower.preview.toolpath import PreviewCancelled
from cooling_tower.preprocessor_state import PreprocessorStateTracker
from cooling_tower.gcode.parser import GCodeLine, parse_gcode_line


def inserted_movements(path):
    tracker, active, layer = MachineStateTracker(bambu_compatible=True), False, -1
    for line in iter_parsed_gcode_lines(path):
        if line.raw_text == BEGIN:
            active, layer = True, layer + 1
        event = tracker.process_line(line)
        if active and isinstance(event, Movement):
            yield layer, line, event, tracker.state.speed_factor_percent, tracker.state.extrusion_factor
        if line.raw_text == END:
            active = False


def variable_gcode(heights):
    lines, index, z = [], -1, 0.0
    for line in make_gcode(layers=len(heights)).splitlines():
        if line.startswith(";Z:"):
            index += 1
            z += heights[index]
            line = f";Z:{z:.5f}"
        elif line.startswith(";HEIGHT:"):
            line = f";HEIGHT:{heights[index]:.5f}"
        elif line.startswith("G1 Z"):
            line = f"G1 Z{z:.5f} F1200"
        lines.append(line)
    return "\n".join(lines)+"\n"


class PreprocessorRefinementTests(unittest.TestCase):
    def test_bambu_special_commands_keep_real_tool_but_real_tool_changes_stay_rejected(self):
        text = make_gcode().replace("M83", "M83\nT0\nT1000\nT1100\nT255", 1)
        request = self.fixture.request(text, adapter="bambu_studio")
        result = self.fixture.prepare(request)
        self.assertTrue(result.scene.tower_segments)
        source = request.prepared_source.analysis_gcode_path.read_bytes()
        self.assertIn(b"T1000", source)
        self.assertEqual(request.prepared_source.analysis_gcode_path.read_bytes(), source)
        for adapter in ("bambu_studio", "prusa_slicer", "orca_slicer", "anycubic_slicer_next"):
            bad = self.fixture.request(make_gcode().replace("M83", "M83\nT1", 1), adapter=adapter)
            with self.subTest(adapter=adapter), self.assertRaisesRegex(ValueError, "Extruder T0"):
                self.fixture.service.prepare(bad)

    def test_plain_flow_and_tool_qualified_bambu_commands_are_distinct(self):
        for adapter in ("prusa_slicer", "bambu_studio", "orca_slicer", "anycubic_slicer_next"):
            tracker = PreprocessorStateTracker(adapter)
            tracker.process_line(parse_gcode_line(GCodeLine(1, "M221 S95")))
            self.assertEqual(tracker.state.extrusion_factor, .95)
            tracker.process_line(parse_gcode_line(GCodeLine(2, "M221 T0 S80")))
            self.assertEqual(tracker.state.extrusion_factor, .8 if adapter == "prusa_slicer" else .95)

    def setUp(self):
        self.fixture = fixture_module.PreprocessorTests()
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def test_first_layer_caps_and_width_reach_real_paths_and_volume(self):
        for adapter in ("prusa_slicer", "orca_slicer", "bambu_studio", "anycubic_slicer_next"):
            with self.subTest(adapter=adapter):
                request = self.fixture.request(adapter=adapter)
                request.profile.effective_values.update({"initial_layer_speed": [12], "initial_layer_infill_speed": [18],
                    "initial_layer_line_width": "150%", "outer_wall_speed": 80})
                result = self.fixture.prepare(request)
                deposits = [(layer, event, speed, factor) for layer, _, event, speed, factor in inserted_movements(result.gcode_path)
                    if event.category == "deposition" and event.endpoint_distance_xy_mm > 0]
                first = [item for item in deposits if item[0] == 0]
                speeds = {round(event.feedrate_mm_min / 60 * speed / 100, 4) for _, event, speed, _ in first}
                self.assertEqual(speeds, {12, 18})
                self.assertGreater(max(event.feedrate_mm_min/60 for i, event, _, _ in deposits if i > 0), 18)
                # Inner rings have no added prime. Check volume directly from
                # physical E and distance, independently of timing analysis.
                _, event, _, factor = first[-1]
                cross_section = event.delta_e * factor * math.pi * .875**2 / event.endpoint_distance_xy_mm
                expected_width = .3 if adapter == "prusa_slicer" else .6
                self.assertAlmostEqual(cross_section, expected_width * .2 - (1-math.pi/4)*.2**2, delta=1e-5)
                self.assertAlmostEqual(result.scene.tower_segments[0].start.x - result.scene.tower_center_xy_mm[0],
                    result.base_width_mm/2 - expected_width/2, places=5)

    def test_first_layer_percentages_auto_width_fallback_and_manual_lower_cap(self):
        first = first_layer_parameters({"perimeter_speed": 120, "external_perimeter_speed": "50%",
            "solid_infill_speed": 100, "first_layer_speed": "25%", "first_layer_infill_speed": "30%",
            "first_layer_extrusion_width": "125%"}, print_speed=90, nozzle=.4, line_width=.45, layer_height=.2, adapter_id="prusa_slicer")
        self.assertEqual((first.wall_speed_mm_s, first.infill_speed_mm_s, first.line_width_mm), (15, 30, .25))
        first = first_layer_parameters({"first_layer_speed": 40, "first_layer_extrusion_width": 0},
            print_speed=7, nozzle=.4, line_width=.45, layer_height=.2, adapter_id="prusa_slicer")
        self.assertEqual((first.wall_speed_mm_s, first.infill_speed_mm_s, first.line_width_mm), (7, 7, .45))
        first = first_layer_parameters({}, print_speed=80, nozzle=.4, line_width=.45, layer_height=.2, adapter_id="prusa_slicer")
        self.assertEqual(first.wall_speed_mm_s, 20)
        with self.assertRaises(ValueError):
            first_layer_parameters({"initial_layer_line_width": 3}, print_speed=80, nozzle=.4, line_width=.45,
                layer_height=.2, adapter_id="orca_slicer")

    def test_signed_restart_extra_nil_zero_and_manual_retraction(self):
        for extra in (-.2, 0, .15):
            settings, _ = resolve_profile_settings(PreprocessorSettings(), {"retraction_length": [1],
                "filament_retract_restart_extra": [extra], "retract_restart_extra": .8,
                "filament_deretraction_speed": [0], "retraction_speed": 28})
            self.assertEqual(settings.restart_extra_mm, extra)
            self.assertEqual(settings.unretract_speed_mm_s, 28)
        settings, _ = resolve_profile_settings(PreprocessorSettings(), {"filament_retract_restart_extra": ["nil"],
            "retract_restart_extra": "0.1,0.7", "machine_max_feedrate_e": "12,30"})
        self.assertEqual(settings.restart_extra_mm, .1)
        self.assertEqual(settings.retract_speed_mm_s, 12)
        manual = replace(PreprocessorSettings(), automatic_retraction=False)
        self.assertEqual(resolve_profile_settings(manual, {"retract_restart_extra": .2})[0], manual)
        for value in (True, float("nan"), 100, "bad"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                resolve_profile_settings(PreprocessorSettings(), {"retract_restart_extra": value})

    def test_restart_extra_changes_only_inserted_restarts_and_preserves_original_state(self):
        for relative in (False, True):
            for extra in (-.2, .15):
                with self.subTest(relative=relative, extra=extra):
                    request = self.fixture.request(make_gcode(relative=relative).replace("M201 X", "M220 S200\nM221 S150\nM201 X"))
                    request.profile.effective_values.update({"retraction_length": [1], "filament_retract_restart_extra": [extra],
                        "deretraction_speed": [18]})
                    result = self.fixture.prepare(request)
                    restarts = [event for _, _, event, _, _ in inserted_movements(result.gcode_path)
                        if event.endpoint_distance_xyz_mm < 1e-8 and event.delta_e > 0]
                    # The final tower departs directly to parking, without
                    # priming again on the already finished model.
                    self.assertEqual(len(restarts), len(result.wipe_angles_rad) * 2 - 1)
                    for event in restarts:
                        self.assertAlmostEqual(event.delta_e*1.5, 1+extra, places=5)
                        self.assertAlmostEqual(event.feedrate_mm_min/60*2, 18)
                    before = self.fixture.original_movements(request.prepared_source.analysis_gcode_path)
                    after = self.fixture.original_movements(result.gcode_path)
                    self.assertEqual(len(before), len(after))
                    for a, b in zip(before, after):
                        self.assertEqual((a[0], a[-1]), (b[0], b[-1]))
                        for x, y in zip(a[1:-1], b[1:-1]):
                            self.assertAlmostEqual(x, y, places=5)

    def test_impossible_negative_restart_blocks_and_zero_retract_adds_nothing(self):
        request = self.fixture.request()
        request.profile.effective_values.update({"retraction_length": .1, "retract_restart_extra": -.2})
        with self.assertRaisesRegex(ValueError, "Wiederanlauf"):
            self.fixture.prepare(request)
        request.profile.effective_values["retraction_length"] = 0
        result = self.fixture.prepare(request)
        self.assertFalse(any(event.delta_e for _, _, event, _, _ in inserted_movements(result.gcode_path)
            if event.endpoint_distance_xyz_mm < 1e-8))

    def test_variable_heights_long_dwells_and_tall_thin_tower(self):
        # A 48 mm tower with changing layer heights and several minute-long
        # pauses exercises the full foot-to-shaft transition and G4 splitting.
        text = variable_gcode((.2,) + (.16, .28)*99 + (.2,))
        request = self.fixture.request(text, settings=replace(PreprocessorSettings(),
            automatic_target_time=False, target_layer_time_s=180, automatic_diameter=False, diameter_mm=6))
        result = self.fixture.prepare(request)
        self.assertGreater(result.height_mm, 30)
        self.assertEqual(len(result.wipe_angles_rad), 200)
        self.assertTrue(all(t >= 179.99 for t in result.layer_times_s))
        for _, line, _, _, _ in inserted_movements(result.gcode_path):
            if line.command == "G4":
                self.assertLessEqual(line.parameters.get("P", 0), 60_000)
        self.assertLessEqual(result.placement_statistics["indexed_moves"], 200*7+5)

    def test_prusa_percentage_widths_follow_each_actual_layer_height(self):
        heights = (.2, .25, .15, .3, .2)
        request = self.fixture.request(variable_gcode(heights))
        request.profile.effective_values.update({"extrusion_width": "200%",
            "external_perimeter_extrusion_width": "200%", "perimeter_extrusion_width": "250%",
            "first_layer_extrusion_width": "250%"})
        result = self.fixture.prepare(request)
        self.assertAlmostEqual(result.first_layer.line_width_mm, .5)
        overlap = 1-math.pi/4
        expected = tuple(2*h + (2.5*h-overlap*h) for h in heights)
        self.assertAlmostEqual(result.wall_thickness_range_mm[0], min(expected))
        self.assertAlmostEqual(result.wall_thickness_range_mm[1], max(expected))
        # Nominal widths still determine the shaft and the outer wall at each
        # actual height. Annular foot beads may adapt to close residual strips.
        tracker, active, layer, outer, totals = MachineStateTracker(), False, -1, False, {}
        for line in iter_parsed_gcode_lines(result.gcode_path):
            if line.raw_text == BEGIN:
                active, layer = True, layer+1
            if active and line.raw_text.startswith(";TYPE:"):
                outer = line.raw_text == ";TYPE:External perimeter"
            event = tracker.process_line(line)
            if active and outer and isinstance(event, Movement) and event.category == "deposition":
                e, distance = totals.get(layer, (0., 0.))
                totals[layer] = e+event.delta_e*tracker.state.extrusion_factor, distance+event.endpoint_distance_xy_mm
            if line.raw_text == END:
                active = False
        for i, h in enumerate(heights):
            width = .5 if i == 0 else 2*h
            e, distance = totals[i]
            actual = (e-result.effective_settings.prime_mm)*math.pi*.875**2/distance
            self.assertAlmostEqual(actual, width*h-overlap*h*h, delta=1e-5)

    def test_index_preserves_chronology_arc_enclosures_and_cancellation(self):
        path = self.fixture.root / "index.gcode"
        path.write_text("G90\nM83\nG1 X0 Y0 Z20 F600\nG1 X100 Y0 Z1 F1200\nG2 X110 Y0 I5 J0 E1 F1200\n")
        index = OriginalMotionIndex.capture(path, {3: 20})
        self.assertIsNotNone(index.tower_rejection((105, 4), 1, head_radius=1, head_height=1))
        self.assertIsNone(index.tower_rejection((150, 150), 1, head_radius=1, head_height=1))
        self.assertTrue(index.model_clear((105, 4), 2, lambda z: 2, height=.5))
        self.assertFalse(index.model_clear((105, 4), 2, lambda z: 2, height=2))
        event = Event()
        event.set()
        with self.assertRaises(PreviewCancelled):
            OriginalMotionIndex.capture(path, {}, cancellation_event=event)

    def test_index_allows_empty_space_inside_global_bounds_and_uses_actual_height(self):
        path = self.fixture.root / "islands.gcode"
        path.write_text("G90\nM83\nG1 X0 Y0 Z.2 F600\nG1 X10 Y0 E1\n"
            "G1 X100 Y100\nG1 X110 Y100 E1\nG1 Z20\nG1 X45 Y50\nG1 X55 Y50 E1\n")
        index = OriginalMotionIndex.capture(path, {})
        self.assertTrue(index.model_clear((50, 50), 15, lambda z: 15, height=10))
        self.assertFalse(index.model_clear((50, 50), 15, lambda z: 15, height=25))
        self.assertTrue(index.model_clear((50, 35), 20, lambda z: 10 if z > 10 else 20, height=25))

    def test_full_circle_with_identical_endpoints_is_not_lost(self):
        path = self.fixture.root / "full-circle.gcode"
        path.write_text("G90\nM83\nG1 X0 Y0 Z20 F600\nG1 X10 Y10 Z1 F1200\nG2 X10 Y10 I10 J0 E1\n")
        index = OriginalMotionIndex.capture(path, {3: 20})
        self.assertEqual(index.deposition_count, 1)
        self.assertFalse(index.model_clear((30, 10), 2, lambda z: 2))
        self.assertIsNotNone(index.tower_rejection((30, 10), 2))
        from cooling_tower.preprocessor_travel import original_exclusions_clear
        from cooling_tower.preprocessor_safety import ExclusionRect
        with self.assertRaisesRegex(ValueError, "Original-G-Code"):
            original_exclusions_clear(path, (ExclusionRect(29, 9, 31, 11).polygon,), 1)

    def test_large_index_prunes_queries_and_reads_source_only_once(self):
        path = self.fixture.root / "large.gcode"
        path.write_text("G90\nM83\nG1 Z.2 F1200\n" + "".join(
            f"G1 X0 Y{i} F1200\nG1 X100 Y{i} E1\n" for i in range(4000)))
        index = OriginalMotionIndex.capture(path, {})
        path.unlink()  # All later candidates must work from the frozen index.
        for i in range(100):
            self.assertFalse(index.model_clear((50, i*35), 2, lambda z: 2))
        self.assertLess(index.examined_moves, 1000)

    def test_service_can_place_tower_between_separated_model_islands(self):
        lines = ["; generated by PrusaSlicer 2.9.0", "G90", "M83", "G1 Z.2 F1200"]
        for i in range(6):
            z = .2*(i+1)
            lines.extend([";LAYER_CHANGE", f";Z:{z:.2f}", ";HEIGHT:0.2", f"G1 Z{z:.2f} F1200"])
            for x in (40, 160):
                lines.append(f"G1 X{x} Y100 F6000")
                lines.extend((f"G1 X{x+10} Y100 E.4 F1200", f"G1 X{x+10} Y110 E.4",
                    f"G1 X{x} Y110 E.4", f"G1 X{x} Y100 E.4"))
        settings = replace(PreprocessorSettings(), automatic_position=False, center_x_mm=105, center_y_mm=105,
            automatic_wait_position=False, wait_x_mm=105, wait_y_mm=60)
        request = self.fixture.request("\n".join(lines)+"\n", settings=settings)
        result = self.fixture.prepare(request)
        self.assertEqual(result.scene.tower_center_xy_mm, (105, 105))
        self.assertTrue(result.scene.tower_segments)


if __name__ == "__main__":
    unittest.main()
