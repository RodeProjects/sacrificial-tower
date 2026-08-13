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


if __name__ == "__main__":
    unittest.main()
