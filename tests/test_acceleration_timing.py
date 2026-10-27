from __future__ import annotations

import math
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from gcode_parser import (
    GCodeLine,
    MachineStateTracker,
    MotionTimingPlanner,
    calculate_movement_timing,
    parse_gcode_line,
    plan_movement_run,
)

from cooling_tower.services.analysis_service import GCodeAnalysisService


def parsed(text: str, line_number: int = 1):
    return parse_gcode_line(GCodeLine(number=line_number, text=text))


def movement(tracker: MachineStateTracker, text: str, line_number: int = 1):
    event = tracker.process_line(parsed(text, line_number))
    if event is None:
        raise AssertionError(f"Expected movement for {text!r}.")
    return event


class AccelerationCommandTests(unittest.TestCase):
    def test_named_klipper_parameters_are_parsed(self) -> None:
        line = parsed(
            "SET_VELOCITY_LIMIT ACCEL=2500 "
            "SQUARE_CORNER_VELOCITY=7.5"
        )

        self.assertEqual(line.command, "SET_VELOCITY_LIMIT")
        self.assertEqual(line.parameters["ACCEL"], 2500.0)
        self.assertEqual(
            line.parameters["SQUARE_CORNER_VELOCITY"],
            7.5,
        )
        self.assertIsNone(line.unparsed_text)

    def test_m204_selects_print_travel_and_retract_acceleration(self) -> None:
        tracker = MachineStateTracker()
        tracker.process_line(parsed("G90"))
        tracker.process_line(parsed("M83"))
        tracker.process_line(parsed("M204 P100 R50 T200"))

        deposition = movement(tracker, "G1 X10 E1 F600")
        travel = movement(tracker, "G1 X20 F600")
        retraction = movement(tracker, "G1 E-1 F600")

        self.assertEqual(deposition.category, "deposition")
        self.assertEqual(deposition.acceleration_mm_s2, 100.0)
        self.assertEqual(travel.category, "travel")
        self.assertEqual(travel.acceleration_mm_s2, 200.0)
        self.assertEqual(retraction.category, "retraction")
        self.assertEqual(retraction.acceleration_mm_s2, 50.0)

    def test_legacy_m204_s_preserves_retract_acceleration(self) -> None:
        tracker = MachineStateTracker(bambu_compatible=True)
        tracker.process_line(parsed("M204 P100 R300 T200"))
        tracker.process_line(parsed("M204 S25"))

        deposition = movement(tracker, "G1 X10 E1 F600")
        travel = movement(tracker, "G1 X20 F600")
        retraction = movement(tracker, "G1 E-1 F600")

        self.assertEqual(deposition.acceleration_mm_s2, 25.0)
        self.assertEqual(travel.acceleration_mm_s2, 25.0)
        self.assertEqual(retraction.acceleration_mm_s2, 300.0)

    def test_generic_m204_s_keeps_existing_retract_semantics(self) -> None:
        tracker = MachineStateTracker()
        tracker.process_line(parsed("M204 P100 R300 T200"))
        tracker.process_line(parsed("M204 S25"))

        retraction = movement(tracker, "G1 E-1 F600")

        self.assertEqual(retraction.acceleration_mm_s2, 25.0)

    def test_bambu_machine_envelope_and_extrusion_factor_are_stored(
        self,
    ) -> None:
        tracker = MachineStateTracker(bambu_compatible=True)
        tracker.process_line(parsed("M203 X100 Y90 Z20 E30"))
        tracker.process_line(parsed("M205 X9 Z3 E2.5 S2 T4"))
        tracker.process_line(parsed("M221 S95"))

        result = movement(tracker, "G1 X10 E1 F600")

        self.assertEqual(result.maximum_feedrate_x_mm_s, 100.0)
        self.assertEqual(result.maximum_feedrate_y_mm_s, 90.0)
        self.assertEqual(result.maximum_feedrate_z_mm_s, 20.0)
        self.assertEqual(result.maximum_feedrate_e_mm_s, 30.0)
        self.assertEqual(result.jerk_x_mm_s, 9.0)
        self.assertEqual(result.jerk_y_mm_s, 9.0)
        self.assertEqual(result.minimum_extruding_feedrate_mm_s, 2.0)
        self.assertEqual(result.minimum_travel_feedrate_mm_s, 4.0)
        self.assertAlmostEqual(result.extrusion_factor, 0.95)

    def test_m201_limits_diagonal_path_acceleration(self) -> None:
        tracker = MachineStateTracker()
        tracker.process_line(parsed("M201 X100 Y100 Z50 E500"))
        tracker.process_line(parsed("M204 S1000"))

        diagonal = movement(tracker, "G1 X10 Y10 F6000")

        self.assertAlmostEqual(
            diagonal.acceleration_mm_s2,
            100.0 * math.sqrt(2.0),
        )

    def test_set_velocity_limit_updates_acceleration_and_corner_speed(
        self,
    ) -> None:
        tracker = MachineStateTracker()
        tracker.process_line(
            parsed(
                "SET_VELOCITY_LIMIT ACCEL=800 "
                "SQUARE_CORNER_VELOCITY=6"
            )
        )

        result = movement(tracker, "G1 X10 F600")

        self.assertEqual(result.acceleration_mm_s2, 800.0)
        self.assertEqual(result.square_corner_velocity_mm_s, 6.0)


class AccelerationProfileTests(unittest.TestCase):
    def test_long_move_uses_trapezoidal_profile(self) -> None:
        timing = calculate_movement_timing(
            has_spatial_motion=True,
            path_length_mm=100.0,
            delta_e=0.0,
            feedrate_mm_min=600.0,
            speed_factor_percent=100.0,
            acceleration_mm_s2=10.0,
        )

        self.assertAlmostEqual(timing.duration_s, 11.0)
        self.assertAlmostEqual(timing.cruise_speed_mm_s, 10.0)

    def test_short_move_uses_triangular_profile(self) -> None:
        timing = calculate_movement_timing(
            has_spatial_motion=True,
            path_length_mm=1.0,
            delta_e=0.0,
            feedrate_mm_min=6000.0,
            speed_factor_percent=100.0,
            acceleration_mm_s2=10.0,
        )

        self.assertAlmostEqual(
            timing.duration_s,
            2.0 * math.sqrt(1.0 / 10.0),
        )
        self.assertAlmostEqual(
            timing.cruise_speed_mm_s,
            math.sqrt(10.0),
        )

    def test_unknown_acceleration_keeps_nominal_legacy_timing(self) -> None:
        timing = calculate_movement_timing(
            has_spatial_motion=True,
            path_length_mm=10.0,
            delta_e=0.0,
            feedrate_mm_min=600.0,
            speed_factor_percent=100.0,
        )

        self.assertAlmostEqual(timing.duration_s, 1.0)
        self.assertIsNone(timing.acceleration_mm_s2)

    def test_zero_acceleration_is_reported_as_untimed(self) -> None:
        timing = calculate_movement_timing(
            has_spatial_motion=True,
            path_length_mm=10.0,
            delta_e=0.0,
            feedrate_mm_min=600.0,
            speed_factor_percent=100.0,
            acceleration_mm_s2=0.0,
        )

        self.assertIsNone(timing.duration_s)
        self.assertIn("acceleration", timing.error or "")


class MotionLookaheadTests(unittest.TestCase):
    def test_planning_preserves_every_non_timing_movement_field(self) -> None:
        tracker = MachineStateTracker()
        tracker.process_line(parsed("M204 S10"))
        tracker.process_line(parsed("M205 X5 Y6 Z7 E8"))
        original = movement(tracker, "G1 X10 Y4 E1 F600")

        planned = plan_movement_run([original])[0]
        expected = replace(
            original,
            duration_s=planned.duration_s,
            timing_error=planned.timing_error,
            entry_speed_mm_s=planned.entry_speed_mm_s,
            cruise_speed_mm_s=planned.cruise_speed_mm_s,
            exit_speed_mm_s=planned.exit_speed_mm_s,
        )

        self.assertEqual(planned, expected)

    def test_collinear_moves_keep_velocity_through_junction(self) -> None:
        tracker = MachineStateTracker()
        tracker.process_line(parsed("M204 S10"))
        tracker.process_line(parsed("M205 X5 Y5"))
        first = movement(tracker, "G1 X10 F600")
        second = movement(tracker, "G1 X20")

        planner = MotionTimingPlanner(lookahead_movements=1)
        emitted = list(planner.process_event(first))
        emitted.extend(planner.process_event(second))
        emitted.extend(planner.finish())

        self.assertEqual(len(emitted), 2)
        self.assertAlmostEqual(emitted[0].exit_speed_mm_s, 10.0)
        self.assertAlmostEqual(emitted[1].entry_speed_mm_s, 10.0)
        self.assertAlmostEqual(
            sum(event.duration_s or 0.0 for event in emitted),
            3.0,
        )

    def test_square_corner_velocity_limits_ninety_degree_junction(
        self,
    ) -> None:
        tracker = MachineStateTracker()
        tracker.process_line(parsed("M204 S10"))
        tracker.process_line(
            parsed(
                "SET_VELOCITY_LIMIT SQUARE_CORNER_VELOCITY=5"
            )
        )
        first = movement(tracker, "G1 X10 F600")
        second = movement(tracker, "G1 Y10")

        planner = MotionTimingPlanner(lookahead_movements=1)
        emitted = list(planner.process_event(first))
        emitted.extend(planner.process_event(second))
        emitted.extend(planner.finish())

        self.assertAlmostEqual(emitted[0].exit_speed_mm_s, 5.0)
        self.assertAlmostEqual(emitted[1].entry_speed_mm_s, 5.0)
        self.assertAlmostEqual(
            sum(event.duration_s or 0.0 for event in emitted),
            3.25,
        )

    def test_dwell_flushes_motion_to_zero_speed(self) -> None:
        tracker = MachineStateTracker()
        tracker.process_line(parsed("M204 S10"))
        first = movement(tracker, "G1 X10 F600")
        dwell = tracker.process_line(parsed("G4 S1"))
        self.assertIsNotNone(dwell)

        planner = MotionTimingPlanner()
        self.assertEqual(planner.process_event(first), ())
        emitted = planner.process_event(dwell)

        self.assertEqual(len(emitted), 2)
        self.assertAlmostEqual(emitted[0].exit_speed_mm_s, 0.0)
        self.assertAlmostEqual(emitted[1].duration_s, 1.0)

    def test_bambu_planner_retains_classic_jerk_safe_speed(self) -> None:
        tracker = MachineStateTracker()
        tracker.process_line(parsed("M204 S10"))
        tracker.process_line(parsed("M205 X5 Y5"))
        first = movement(tracker, "G1 X10 F600")
        second = movement(tracker, "G1 Y10")

        planned = plan_movement_run(
            [first, second],
            bambu_compatible=True,
        )

        self.assertAlmostEqual(planned[0].entry_speed_mm_s, 5.0)
        self.assertAlmostEqual(planned[0].exit_speed_mm_s, 5.0)
        self.assertAlmostEqual(planned[1].entry_speed_mm_s, 5.0)
        self.assertAlmostEqual(planned[1].exit_speed_mm_s, 5.0)
        self.assertAlmostEqual(
            sum(event.duration_s or 0.0 for event in planned),
            2.5,
        )

    def test_bambu_m203_and_m221_limit_axis_feedrate(self) -> None:
        tracker = MachineStateTracker(bambu_compatible=True)
        tracker.process_line(parsed("M204 S10000"))
        tracker.process_line(parsed("M205 X100 Y100 Z100 E100"))
        tracker.process_line(parsed("M203 X1000 Y1000 Z1000 E1"))
        tracker.process_line(parsed("M221 S200"))
        result = movement(tracker, "G1 X10 E10 F600")

        planned = plan_movement_run(
            [result],
            bambu_compatible=True,
        )[0]

        self.assertAlmostEqual(
            (planned.effective_feedrate_mm_min or 0.0) / 60.0,
            0.5,
        )

    def test_bambu_g1_centripetal_limit_is_not_used_generically(self) -> None:
        tracker = MachineStateTracker(bambu_compatible=True)
        tracker.process_line(parsed("M204 S25"))
        tracker.process_line(parsed("M205 X100 Y100"))
        first = movement(tracker, "G1 X10 F6000")
        second = movement(tracker, "G1 X20 Y1 F6000")

        bambu = plan_movement_run(
            [first, second],
            bambu_compatible=True,
        )
        generic = plan_movement_run([first, second])

        self.assertLess(
            bambu[1].effective_feedrate_mm_min or 0.0,
            generic[1].effective_feedrate_mm_min or 0.0,
        )
        self.assertAlmostEqual(
            (generic[1].effective_feedrate_mm_min or 0.0) / 60.0,
            100.0,
        )

    def test_bambu_streaming_retains_direction_across_refresh(self) -> None:
        tracker = MachineStateTracker(bambu_compatible=True)
        tracker.process_line(parsed("M204 S25"))
        tracker.process_line(parsed("M205 X100 Y100"))
        movements = [
            movement(tracker, "G1 X10 F6000", 1),
            movement(tracker, "G1 X20 F6000", 2),
            movement(tracker, "G1 X30 Y1 F6000", 3),
            movement(tracker, "G1 X40 Y2 F6000", 4),
        ]

        expected = plan_movement_run(
            movements,
            bambu_compatible=True,
        )
        planner = MotionTimingPlanner(
            lookahead_movements=1,
            refresh_threshold_movements=2,
            bambu_compatible=True,
        )
        actual = []
        for item in movements:
            actual.extend(planner.process_event(item))
        actual.extend(planner.finish())

        self.assertAlmostEqual(
            actual[2].effective_feedrate_mm_min or 0.0,
            expected[2].effective_feedrate_mm_min or 0.0,
        )


class AccelerationAnalysisIntegrationTests(unittest.TestCase):
    @staticmethod
    def _analyze(gcode: str):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "model.gcode"
            path.write_text(gcode, encoding="utf-8")
            return GCodeAnalysisService().analyze(path, force=True)

    def test_analysis_service_uses_acceleration_aware_planner(self) -> None:
        movement_lines = (
            "G90",
            "M83",
            "G1 Z0.2 F600",
            "G1 X10 E1 F600",
            "G1 Y10 E1",
            "G1 Z0.4",
            "G1 X20 E1",
            "G1 Y20 E1",
        )
        nominal = self._analyze("\n".join(movement_lines))
        accelerated = self._analyze(
            "\n".join(
                (
                    "M201 X100 Y100 Z100 E100",
                    "M204 S10",
                    "M205 X5 Y5 Z5 E5",
                    *movement_lines,
                )
            )
        )

        nominal_time = sum(
            layer.total_time_s for layer in nominal.analysis.layers
        )
        accelerated_time = sum(
            layer.total_time_s for layer in accelerated.analysis.layers
        )

        self.assertGreater(accelerated_time, nominal_time)
        self.assertEqual(len(accelerated.analysis.layers), 2)
        self.assertEqual(
            sum(
                layer.untimed_event_count
                for layer in accelerated.analysis.layers
            ),
            0,
        )

    def test_bambu_header_selects_viewer_compatible_timing(self) -> None:
        body = "\n".join(
            (
                "M204 S10",
                "M205 X5 Y5",
                "G1 Z0.2 F600",
                "G1 X10 E1 F600",
                "G1 Y10 E1",
            )
        )

        generic = self._analyze(body)
        bambu = self._analyze(
            "; generated by Bambu Studio 02.08\n" + body
        )

        self.assertLess(
            bambu.analysis.layers[0].total_time_s,
            generic.analysis.layers[0].total_time_s,
        )

    def test_bambu_layer_tags_assign_transition_to_new_layer(self) -> None:
        snapshot = self._analyze(
            "\n".join(
                (
                    "; BambuStudio 02.08",
                    "G90",
                    "M83",
                    "M204 S1000",
                    "M205 X5 Y5 Z5 E5",
                    "; CHANGE_LAYER",
                    "; Z_HEIGHT: 0.2",
                    "; LAYER_HEIGHT: 0.2",
                    "G1 Z0.2 F600",
                    "G1 X10 E1 F600",
                    "; CHANGE_LAYER",
                    "; Z_HEIGHT: 0.4",
                    "; LAYER_HEIGHT: 0.2",
                    "G1 X9 E-0.2 F600",
                    "G1 Z0.4 F600",
                    "G1 X20 E1 F600",
                )
            )
        )

        self.assertEqual(snapshot.layer_count, 2)
        self.assertEqual(snapshot.layers[0].z_mm, 0.2)
        self.assertEqual(snapshot.layers[1].z_mm, 0.4)
        self.assertEqual(snapshot.layers[0].retraction_time_s, 0.0)
        self.assertGreater(snapshot.layers[1].travel_time_s, 0.0)

    def test_bambu_arc_tangents_match_smooth_curve_planning(self) -> None:
        body = "\n".join(
            (
                "G90",
                "M83",
                "M204 S10000",
                "M205 X9 Y9 Z3 E2.5",
                "G1 Z0.2 F600",
                "G1 X-10 Y10 E1 F12000",
                "G1 X0 Y10 E1",
                "G2 X10 Y0 I0 J-10 E1",
                "G1 X10 Y-10 E1",
            )
        )

        generic = self._analyze(body)
        bambu = self._analyze("; BambuStudio 02.08\n" + body)

        self.assertLess(
            bambu.layers[0].total_time_s,
            generic.layers[0].total_time_s,
        )

    def test_anycubic_header_keeps_generic_timing_unchanged(self) -> None:
        body = "\n".join(
            (
                "G90",
                "M83",
                "M201 X1000 Y1000 Z1000 E1000",
                "M203 X5 Y5 Z5 E1",
                "M204 P100 R300 T200",
                "M204 S25",
                "M205 X9 S20 T20",
                "M221 S200",
                "G1 Z0.2 F600",
                "G1 X10 E10 F6000",
                "G1 X20 Y1 E10",
            )
        )

        generic = self._analyze(body)
        anycubic = self._analyze(
            "; generated by Anycubic Slicer Next\n" + body
        )

        self.assertEqual(anycubic.layer_count, generic.layer_count)
        for anycubic_layer, generic_layer in zip(
            anycubic.layers,
            generic.layers,
        ):
            self.assertEqual(
                replace(
                    anycubic_layer,
                    start_line=generic_layer.start_line,
                    first_deposition_line=(
                        generic_layer.first_deposition_line
                    ),
                    end_line=generic_layer.end_line,
                ),
                generic_layer,
            )

    def test_bambu_m203_machine_speed_limit_changes_timing(self) -> None:
        body = "\n".join(
            (
                "G90",
                "M83",
                "M201 X10000 Y10000 Z10000 E10000",
                "M203 X5 Y1000 Z1000 E1000",
                "M204 S10000",
                "M205 X100 Y100 Z100 E100",
                "G1 Z0.2 F600",
                "G1 X100 E1 F6000",
            )
        )

        generic = self._analyze(body)
        bambu = self._analyze("; BambuStudio 02.08\n" + body)

        self.assertGreater(
            bambu.layers[0].total_time_s,
            generic.layers[0].total_time_s,
        )


if __name__ == "__main__":
    unittest.main()
