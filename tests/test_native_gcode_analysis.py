from __future__ import annotations

import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cooling_tower.gcode.parser as parser_module
from cooling_tower.gcode.parser import (
    GCodeLine,
    MachineStateTracker,
    MotionTimingPlanner,
    Movement,
    clear_native_timing_cache,
    iter_parsed_gcode_lines,
    native_timing_available,
    native_timing_cache_info,
    parse_gcode_line,
    plan_movement_run,
)
from cooling_tower.services.analysis_service import GCodeAnalysisService


def parsed(number: int, text: str):
    return parse_gcode_line(GCodeLine(number=number, text=text))


def build_movements(*, bambu: bool, count: int = 600) -> list[Movement]:
    tracker = MachineStateTracker(bambu_compatible=bambu)
    for number, command in enumerate(
        (
            "M204 S2400",
            "M205 X8 Y9 Z0.4 E3",
            "M203 X300 Y300 Z15 E30",
            "M221 S97",
        ),
        start=1,
    ):
        tracker.process_line(parsed(number, command))

    randomizer = random.Random(4107)
    x = y = z = e = 0.0
    movements: list[Movement] = []
    for index in range(count):
        x += randomizer.uniform(-3.0, 3.0)
        y += randomizer.uniform(-3.0, 3.0)
        if index % 100 == 0:
            z += 0.2
        e += randomizer.uniform(0.01, 0.08)
        event = tracker.process_line(
            parsed(
                index + 10,
                (
                    f"G1 X{x:.6f} Y{y:.6f} Z{z:.4f} E{e:.6f} "
                    f"F{randomizer.uniform(600.0, 12_000.0):.5f}"
                ),
            )
        )
        if isinstance(event, Movement):
            movements.append(event)
    return movements


@unittest.skipUnless(native_timing_available(), "native timing extension unavailable")
class NativeLineParserTests(unittest.TestCase):
    def test_common_native_grammar_matches_python_reference(self) -> None:
        source_lines = [
            "",
            "; comment",
            "  ; indented comment",
            "G1 X10 Y20 E.5 F1200 ; movement",
            "G01X-1.2e+2Y.3",
            "M204 S1000",
            "G1 Xbad",
            "G1 X  foo",
            "foo",
            "G90.1",
            "G1 X1 X2",
            "G1X1*42",
            "N2 G1 X1",
            "SET_VELOCITY_LIMIT ACCEL=500",
            "G1 X1 (parenthesis)",
            "; Größenprüfung",
        ]
        native_rows = parser_module._native_timing.parse_common_lines(
            source_lines
        )
        native_count = 0
        for number, (text, native_row) in enumerate(
            zip(source_lines, native_rows), start=1
        ):
            if native_row is None:
                continue
            native_count += 1
            reference = parse_gcode_line(GCodeLine(number=number, text=text))
            self.assertEqual(
                native_row,
                (
                    reference.code_text,
                    reference.command,
                    reference.parameters,
                    reference.comment,
                    reference.unparsed_text,
                ),
            )
        self.assertGreaterEqual(native_count, 10)

    def test_stream_uses_exact_reference_fallback_for_uncommon_lines(self) -> None:
        source_lines = [
            "G1 X10 Y20 F1200",
            "SET_VELOCITY_LIMIT ACCEL=500",
            "N2 G1 X1*42",
            "G1 X2 (inline note)",
            "; Unicode: Größe",
        ]
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "mixed.gcode"
            path.write_text("\n".join(source_lines), encoding="utf-8")
            actual = list(iter_parsed_gcode_lines(path))
        expected = [
            parse_gcode_line(GCodeLine(number=index, text=text))
            for index, text in enumerate(source_lines, start=1)
        ]
        self.assertEqual(actual, expected)


@unittest.skipUnless(native_timing_available(), "native timing extension unavailable")
class NativeMotionTimingTests(unittest.TestCase):
    def assert_timing_equal(
        self,
        actual: list[Movement],
        expected: list[Movement],
    ) -> None:
        self.assertEqual(len(actual), len(expected))
        timing_fields = (
            "effective_feedrate_mm_min",
            "timing_distance_mm",
            "duration_s",
            "entry_speed_mm_s",
            "cruise_speed_mm_s",
            "exit_speed_mm_s",
        )
        for actual_movement, expected_movement in zip(actual, expected):
            for field_name in timing_fields:
                actual_value = getattr(actual_movement, field_name)
                expected_value = getattr(expected_movement, field_name)
                if actual_value is None or expected_value is None:
                    self.assertIs(actual_value, expected_value)
                else:
                    self.assertAlmostEqual(
                        actual_value,
                        expected_value,
                        delta=1e-10,
                    )

    def test_native_planner_matches_generic_and_bambu_reference(self) -> None:
        for bambu in (False, True):
            with self.subTest(bambu=bambu):
                movements = build_movements(bambu=bambu)
                actual = plan_movement_run(
                    movements,
                    start_speed_mm_s=1.25,
                    end_speed_mm_s=0.75,
                    bambu_compatible=bambu,
                )
                with patch.object(parser_module, "_native_timing", None):
                    expected = plan_movement_run(
                        movements,
                        start_speed_mm_s=1.25,
                        end_speed_mm_s=0.75,
                        bambu_compatible=bambu,
                    )
                self.assert_timing_equal(actual, expected)
                self.assertAlmostEqual(
                    sum(item.duration_s or 0.0 for item in actual),
                    sum(item.duration_s or 0.0 for item in expected),
                    delta=1e-10,
                )

    def test_native_planner_matches_arc_reference(self) -> None:
        tracker = MachineStateTracker(bambu_compatible=True)
        commands = (
            "M204 S2000",
            "M205 X8 Y8 Z0.4 E3",
            "G1 X10 Y0 E0.1 F6000",
            "G3 X0 Y10 I-10 J0 E0.2 F6000",
            "G3 X-10 Y0 I0 J-10 E0.3 F6000",
            "G1 X-20 Y0 E0.4 F6000",
        )
        movements: list[Movement] = []
        for number, command in enumerate(commands, start=1):
            event = tracker.process_line(parsed(number, command))
            if isinstance(event, Movement):
                movements.append(event)
        actual = plan_movement_run(movements, bambu_compatible=True)
        with patch.object(parser_module, "_native_timing", None):
            expected = plan_movement_run(movements, bambu_compatible=True)
        self.assert_timing_equal(actual, expected)

    def test_exact_cache_reuses_only_identical_state_and_lookahead(self) -> None:
        movements = build_movements(bambu=False, count=180)
        clear_native_timing_cache()
        first = plan_movement_run(
            movements,
            start_speed_mm_s=1.0,
            end_speed_mm_s=2.0,
        )
        after_first = native_timing_cache_info()
        second = plan_movement_run(
            movements,
            start_speed_mm_s=1.0,
            end_speed_mm_s=2.0,
        )
        after_second = native_timing_cache_info()
        plan_movement_run(
            movements,
            start_speed_mm_s=1.0000000001,
            end_speed_mm_s=2.0,
        )
        after_changed_state = native_timing_cache_info()

        self.assert_timing_equal(second, first)
        self.assertEqual(after_first["misses"], 1)
        self.assertEqual(after_second["hits"], 1)
        self.assertEqual(
            after_changed_state["misses"],
            after_second["misses"] + 1,
        )

    def test_streaming_cache_hits_between_repeated_joint_runs(self) -> None:
        movements = build_movements(bambu=True, count=220)

        def run() -> list[Movement]:
            planner = MotionTimingPlanner(
                lookahead_movements=8,
                refresh_threshold_movements=64,
                bambu_compatible=True,
            )
            output: list[Movement] = []
            for movement in movements:
                output.extend(planner.process_event(movement))
            output.extend(planner.finish())
            return output

        clear_native_timing_cache()
        first = run()
        after_first = native_timing_cache_info()
        second = run()
        after_second = native_timing_cache_info()
        self.assert_timing_equal(second, first)
        self.assertGreater(after_first["misses"], 1)
        self.assertGreater(
            after_second["hits"],
            after_first["hits"],
        )

    def test_python_fallback_remains_operational(self) -> None:
        movements = build_movements(bambu=False, count=20)
        native = plan_movement_run(movements)
        with patch.object(parser_module, "_native_timing", None):
            fallback = plan_movement_run(movements)
        self.assert_timing_equal(native, fallback)


@unittest.skipUnless(native_timing_available(), "native timing extension unavailable")
class NativeFullAnalysisTests(unittest.TestCase):
    def test_complete_analysis_matches_python_reference(self) -> None:
        lines = [
            "; generated by a generic future slicer",
            "M82",
            "G90",
            "M204 S1800",
            "M205 X8 Y8 Z0.4 E3",
        ]
        extrusion = 0.0
        for layer in range(1, 31):
            z = layer * 0.2
            lines.append(f";LAYER:{layer - 1}")
            lines.append(f"G1 Z{z:.3f} F900")
            for point in range(40):
                extrusion += 0.035
                x = (point % 10) * 2.0
                y = ((point // 10) % 4) * 2.0
                lines.append(
                    f"G1 X{x:.3f} Y{y:.3f} E{extrusion:.5f} F3600"
                )
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "joint.gcode"
            path.write_text("\n".join(lines), encoding="utf-8")
            actual = GCodeAnalysisService().analyze(path, force=True)
            with patch.object(parser_module, "_native_timing", None):
                expected = GCodeAnalysisService().analyze(path, force=True)

        self.assertEqual(actual.layer_count, expected.layer_count)
        self.assertEqual(
            actual.analysis.confirmed_layer_changes,
            expected.analysis.confirmed_layer_changes,
        )
        self.assertEqual(
            actual.analysis.rejected_z_candidates,
            expected.analysis.rejected_z_candidates,
        )
        for actual_layer, expected_layer in zip(
            actual.analysis.layers, expected.analysis.layers
        ):
            self.assertEqual(actual_layer.index, expected_layer.index)
            self.assertAlmostEqual(
                actual_layer.total_time_s,
                expected_layer.total_time_s,
                delta=1e-10,
            )

    def test_changed_tower_reuses_exact_unchanged_object_blocks(self) -> None:
        def joint_gcode(*, tower_points: int, bambu: bool) -> str:
            lines = [
                (
                    "; generated by BambuStudio"
                    if bambu
                    else "; generated by Anycubic Slicer Next"
                ),
                "M83",
                "G90",
                "M204 S1800",
                "M205 X8 Y8 Z0.4 E3",
            ]
            for layer in range(1, 13):
                z = layer * 0.2
                if bambu:
                    lines.extend(
                        (
                            "; CHANGE_LAYER",
                            f"; Z_HEIGHT: {z:.3f}",
                            "; LAYER_HEIGHT: 0.2",
                        )
                    )
                else:
                    lines.append(f";LAYER:{layer - 1}")
                lines.extend((f"G1 Z{z:.3f} F900", "; tower object"))
                for point in range(tower_points):
                    angle = point % 20
                    lines.append(
                        f"G1 X{80 + angle * 0.2:.3f} "
                        f"Y{80 + (point % 7) * 0.2:.3f} E0.02 F2400"
                    )
                lines.extend(("; source object", "G92 E0", "G1 X0 Y0 F6000"))
                for point in range(360):
                    lines.append(
                        f"G1 X{(point % 30) * 0.3:.3f} "
                        f"Y{((point // 30) % 12) * 0.3:.3f} E0.03 F3600"
                    )
            return "\n".join(lines)

        for bambu in (False, True):
            with self.subTest(bambu=bambu), tempfile.TemporaryDirectory() as temporary_directory:
                root = Path(temporary_directory)
                first_path = root / "joint_100_percent.gcode"
                second_path = root / "joint_profile_fill.gcode"
                first_path.write_text(
                    joint_gcode(tower_points=80, bambu=bambu),
                    encoding="utf-8",
                )
                second_path.write_text(
                    joint_gcode(tower_points=113, bambu=bambu),
                    encoding="utf-8",
                )
                service = GCodeAnalysisService()
                service.analyze(first_path, force=True)
                before = service.exact_block_cache_info
                reused = service.analyze(second_path, force=True)
                after = service.exact_block_cache_info
                reference = GCodeAnalysisService().analyze(
                    second_path,
                    force=True,
                )

                self.assertGreater(after["hits"], before["hits"])
                self.assertEqual(reused.layer_count, reference.layer_count)
                for reused_layer, reference_layer in zip(
                    reused.analysis.layers,
                    reference.analysis.layers,
                ):
                    self.assertEqual(
                        (
                            reused_layer.start_line,
                            reused_layer.first_deposition_line,
                            reused_layer.end_line,
                        ),
                        (
                            reference_layer.start_line,
                            reference_layer.first_deposition_line,
                            reference_layer.end_line,
                        ),
                    )
                    self.assertAlmostEqual(
                        reused_layer.total_time_s,
                        reference_layer.total_time_s,
                        delta=1e-10,
                    )


if __name__ == "__main__":
    unittest.main()
