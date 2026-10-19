from __future__ import annotations

import json
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import cooling_tower.gcode.parser as parser_module
import cooling_tower.gcode.native_analysis as native_analysis_module
import cooling_tower.services.analysis_service as analysis_service_module
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
from cooling_tower.calibration.joint_project import TowerInfillEvidenceCollector
from cooling_tower.services.analysis_service import (
    AnalysisCancelled,
    GCodeAnalysisService,
)


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
    def assert_layer_analysis_equal(self, actual, expected) -> None:
        self.assertEqual(
            actual.confirmed_layer_changes,
            expected.confirmed_layer_changes,
        )
        self.assertEqual(
            actual.rejected_z_candidates,
            expected.rejected_z_candidates,
        )
        self.assertEqual(
            actual.pre_layer_event_count,
            expected.pre_layer_event_count,
        )
        self.assertAlmostEqual(
            actual.pre_layer_time_s,
            expected.pre_layer_time_s,
            delta=1e-10,
        )
        self.assertEqual(
            actual.pre_layer_untimed_event_count,
            expected.pre_layer_untimed_event_count,
        )
        self.assertEqual(len(actual.layers), len(expected.layers))
        for actual_layer, expected_layer in zip(
            actual.layers, expected.layers
        ):
            for field_name in actual_layer.__dataclass_fields__:
                actual_value = getattr(actual_layer, field_name)
                expected_value = getattr(expected_layer, field_name)
                if isinstance(actual_value, float):
                    self.assertAlmostEqual(
                        actual_value,
                        expected_value,
                        delta=1e-10,
                        msg=field_name,
                    )
                else:
                    self.assertEqual(
                        actual_value,
                        expected_value,
                        field_name,
                    )

    def test_complete_analysis_matches_python_reference(self) -> None:
        lines = [
            "; generated by OrcaSlicer 2.3.0",
            "; CONFIG_BLOCK_START = 1",
            "; layer_height = 0.2",
            "; outer_wall_speed = 60",
            "; CONFIG_BLOCK_END = 1",
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
            service = GCodeAnalysisService()
            actual = service.analyze(path, force=True)
            self.assertTrue(service.native_full_analysis_info["used"])
            with (
                patch.object(parser_module, "_native_timing", None),
                patch.object(native_analysis_module, "_native_timing", None),
            ):
                expected = GCodeAnalysisService().analyze(path, force=True)

        self.assertEqual(actual.layer_count, expected.layer_count)
        self.assert_layer_analysis_equal(actual.analysis, expected.analysis)
        self.assertEqual(actual.metadata, expected.metadata)
        self.assertEqual(actual.timing_evidence, expected.timing_evidence)

    def test_family_golden_snapshots_remain_stable_and_read_only(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        fixture_root = project_root / "tests" / "fixtures" / "gcode"
        expected = json.loads(
            (
                project_root
                / "tests"
                / "references"
                / "native_analysis_golden.json"
            ).read_text(encoding="utf-8")
        )
        for filename, snapshot_payload in expected.items():
            with self.subTest(filename=filename):
                source = fixture_root / filename
                original = source.read_bytes()
                service = GCodeAnalysisService()
                snapshot = service.analyze(source, force=True)
                self.assertTrue(service.native_full_analysis_info["used"])
                self.assertEqual(source.read_bytes(), original)
                self.assertEqual(
                    snapshot.metadata.slicer.product_name,
                    snapshot_payload["slicer"],
                )
                self.assertEqual(
                    snapshot.analysis.confirmed_layer_changes,
                    snapshot_payload["confirmed_layer_changes"],
                )
                self.assertEqual(
                    snapshot.analysis.rejected_z_candidates,
                    snapshot_payload["rejected_z_candidates"],
                )
                self.assertEqual(
                    snapshot.analysis.pre_layer_event_count,
                    snapshot_payload["pre_layer_event_count"],
                )
                self.assertAlmostEqual(
                    snapshot.analysis.pre_layer_time_s,
                    snapshot_payload["pre_layer_time_s"],
                    delta=1e-12,
                )
                self.assertEqual(
                    len(snapshot.layers),
                    len(snapshot_payload["layers"]),
                )
                for layer, expected_layer in zip(
                    snapshot.layers,
                    snapshot_payload["layers"],
                ):
                    for field_name, expected_value in expected_layer.items():
                        actual_value = getattr(layer, field_name)
                        if isinstance(expected_value, float):
                            self.assertAlmostEqual(
                                actual_value,
                                expected_value,
                                delta=1e-12,
                                msg=f"{filename}:{field_name}",
                            )
                        else:
                            self.assertEqual(actual_value, expected_value)

    def test_large_streaming_lookahead_matches_python_reference(self) -> None:
        lines = ["M83", "G90", "M204 S2400", "M205 X8 Y8 Z0.4 E3"]
        for layer in range(3):
            lines.extend((f";LAYER:{layer}", f"G1 Z{(layer + 1) * 0.2:.3f} F900"))
            for point in range(4_500):
                lines.append(
                    f"G1 X{point % 101:.3f} Y{(point * 7) % 97:.3f} "
                    "E0.025 F4200"
                )
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "large.gcode"
            path.write_text("\n".join(lines), encoding="utf-8")
            service = GCodeAnalysisService()
            actual = service.analyze(path, force=True)
            self.assertTrue(service.native_full_analysis_info["used"])
            with (
                patch.object(parser_module, "_native_timing", None),
                patch.object(native_analysis_module, "_native_timing", None),
            ):
                expected = GCodeAnalysisService().analyze(path, force=True)
        self.assert_layer_analysis_equal(actual.analysis, expected.analysis)

    def test_unknown_state_command_uses_complete_python_fallback(self) -> None:
        lines = (
            "G54",
            "M83",
            "G90",
            "M204 S1000",
            "G1 Z0.2 F900",
            "G1 X10 E0.2 F1200",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "unsupported.gcode"
            path.write_text("\n".join(lines), encoding="utf-8")
            service = GCodeAnalysisService()
            actual = service.analyze(path, force=True)
            info = service.native_full_analysis_info
            self.assertFalse(info["used"])
            self.assertEqual(info["status"], "unsupported_syntax")
            self.assertEqual(info["fallback_line"], 1)
            self.assertEqual(info["fallback_command"], "G54")
            with (
                patch.object(parser_module, "_native_timing", None),
                patch.object(native_analysis_module, "_native_timing", None),
            ):
                expected = GCodeAnalysisService().analyze(path, force=True)
        self.assertEqual(actual, expected)

    def test_anycubic_status_fields_and_startup_macro_use_native_path(
        self,
    ) -> None:
        lines = (
            "; generated by AnycubicSlicerNext 1.4.1.2",
            "M73 P0 R226.7 QuietR357.8 SportR205.1",
            "G9111 bedTemp=61 extruderTemp=220",
            "G90",
            "G21",
            "M83",
            "M204 S1000",
            ";LAYER_CHANGE",
            ";Z:0.2",
            ";HEIGHT:0.2",
            "G1 Z0.2 F900",
            "G1 X10 E0.2 F1200",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "anycubic.gcode"
            path.write_text("\n".join(lines), encoding="utf-8")
            service = GCodeAnalysisService()
            actual = service.analyze(path, force=True)
            info = service.native_full_analysis_info
            self.assertTrue(info["used"])
            self.assertEqual(info["anycubic_startup_macro_count"], 1)
            with (
                patch.object(parser_module, "_native_timing", None),
                patch.object(native_analysis_module, "_native_timing", None),
            ):
                expected = GCodeAnalysisService().analyze(path, force=True)
        self.assert_layer_analysis_equal(actual.analysis, expected.analysis)
        self.assertEqual(actual.metadata, expected.metadata)

    def test_bambu_firmware_macros_use_native_path_and_match_reference(
        self,
    ) -> None:
        bambu_firmware_commands = (
            "G29 A1",
            "G29.1 Z0.0",
            "G29.2 S0",
            "G29.99",
            "G130",
            "G150 S10",
            "G150.1 R255",
            "G150.2 R255",
            "G150.3",
            "G151",
            "G380 S2 Z30 F300",
            "G3811",
            "G383",
            "G383.3",
            "G383.4",
            "M1003 S1",
            "M1004 S5 P1",
            "M1006 A1",
            "M1012.1 S1",
            "M1012.5 P1",
            "M1015.3 S1",
            "M1015.4 S1",
            "M1028 S1",
            "M141 S35",
            "M142 P1",
            "M145 S0 H220 B60",
            "M191 S35",
            "M201.2 K1.0",
            "M211 X1 Y1 Z1",
            "M500",
            "M562 S1",
            "M620.6 A0",
            "M620.10 A0 F74.8 H0.4 T220 P220 S1",
            "M620.11 S1 I0 E0",
            "M620.17 S1",
            "M620.22 S1",
            "M622 J1",
            "M622.1 S1",
            "M623",
            "M624",
            "M625",
            "M628 S1",
            "M629 S1",
            "M630 S1",
            "M73.2 R1.0",
            "M970.2 Q1 A5 B30 C80 H15 K0 M20 O3",
            "M970.3 Q1 A5 K0 O1",
            "M974 Q1 S2 P0",
            "M981 S1 P20000",
            "M982.2 S1",
            "M983.1 A0",
            "M983.3 A0",
            "M983.4 A0",
            "M993 A0 B0 C0",
        )
        lines = (
            "; generated by BambuStudio 02.08.02.61",
            *bambu_firmware_commands,
            "G28 X T300 R",
            "M83",
            "G90",
            "M204 S1000",
            "; CHANGE_LAYER",
            "; Z_HEIGHT: 0.2",
            "; LAYER_HEIGHT: 0.2",
            "G1 Z0.2 F900",
            "G1 X10 E0.2 F1200",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "bambu_firmware.gcode"
            path.write_text("\n".join(lines), encoding="utf-8")
            service = GCodeAnalysisService()
            actual = service.analyze(path, force=True)
            info = service.native_full_analysis_info
            self.assertTrue(info["used"])
            with (
                patch.object(parser_module, "_native_timing", None),
                patch.object(native_analysis_module, "_native_timing", None),
            ):
                expected = GCodeAnalysisService().analyze(path, force=True)
        self.assert_layer_analysis_equal(actual.analysis, expected.analysis)
        self.assertEqual(actual.metadata, expected.metadata)
        self.assertEqual(actual.timing_evidence, expected.timing_evidence)

    def test_bambu_firmware_macros_remain_strictly_scoped(self) -> None:
        for command in (
            "M993 A0 B0 C0",
            "M974 Q1 S2 P0",
            "M624",
            "M625",
        ):
            with (
                self.subTest(command=command),
                tempfile.TemporaryDirectory() as temporary_directory,
            ):
                path = Path(temporary_directory) / "foreign.gcode"
                path.write_text(
                    "\n".join(
                        (
                            "; generated by OrcaSlicer 2.3.0",
                            command,
                            "M83",
                            "G90",
                            "G1 Z0.2 F900",
                            "G1 X10 E0.2 F1200",
                        )
                    ),
                    encoding="utf-8",
                )
                service = GCodeAnalysisService()
                service.analyze(path, force=True)
                info = service.native_full_analysis_info
                self.assertFalse(info["used"])
                self.assertEqual(info["status"], "unsupported_syntax")
                self.assertEqual(info["fallback_command"], command.split()[0])

    def test_native_success_does_not_report_stale_python_cache_stats(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fallback_path = root / "fallback.gcode"
            native_path = root / "native.gcode"
            fallback_path.write_text(
                "\n".join(
                    ("G54", "M83", "G90", "G1 Z0.2 F900", "G1 X10 E0.2")
                ),
                encoding="utf-8",
            )
            native_path.write_text(
                "\n".join(
                    ("M83", "G90", "G1 Z0.2 F900", "G1 X10 E0.2")
                ),
                encoding="utf-8",
            )
            service = GCodeAnalysisService()
            service.analyze(fallback_path, force=True)
            with patch.object(
                analysis_service_module,
                "record_diagnostic",
            ) as record:
                service.analyze(native_path, force=True)

        self.assertTrue(service.native_full_analysis_info["used"])
        event_names = [call.args[0] for call in record.call_args_list]
        self.assertIn("gcode_native_full_analysis", event_names)
        self.assertNotIn("gcode_python_block_cache_analysis", event_names)

    def test_anycubic_startup_macro_remains_strictly_scoped(self) -> None:
        cases = {
            "foreign producer": (
                "; generated by OrcaSlicer 2.3.0",
                "G9111 bedTemp=61 extruderTemp=220",
            ),
            "unknown parameter": (
                "; generated by AnycubicSlicerNext 1.4.1.2",
                "G9111 bedTemp=61 extruderTemp=220 unsafe=1",
            ),
            "after movement": (
                "; generated by AnycubicSlicerNext 1.4.1.2",
                "G1 Z0.1 F900",
                "G9111 bedTemp=61 extruderTemp=220",
            ),
        }
        for name, preamble in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "unsafe_macro.gcode"
                path.write_text(
                    "\n".join(
                        (*preamble, "M83", "G90", "G1 Z0.2 F900", "G1 X10 E0.2 F1200")
                    ),
                    encoding="utf-8",
                )
                service = GCodeAnalysisService()
                service.analyze(path, force=True)
                info = service.native_full_analysis_info
                self.assertFalse(info["used"])
                self.assertEqual(info["status"], "unsupported_syntax")
                self.assertEqual(info["fallback_command"], "G9111")

    def test_unparsed_state_command_still_uses_python_fallback(self) -> None:
        lines = (
            "M83",
            "G90",
            "M204 S1000 unsafe",
            "G1 Z0.2 F900",
            "G1 X10 E0.2 F1200",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "unsafe_state.gcode"
            path.write_text("\n".join(lines), encoding="utf-8")
            service = GCodeAnalysisService()
            service.analyze(path, force=True)
            info = service.native_full_analysis_info
        self.assertFalse(info["used"])
        self.assertEqual(info["status"], "unsupported_syntax")
        self.assertEqual(info["fallback_command"], "M204")

    def test_inch_units_and_homing_match_python_reference(self) -> None:
        lines = (
            "G20",
            "G28",
            "M83",
            "G90",
            "M204 S40",
            "M205 X0.3 Y0.3 Z0.02 E0.1",
            "G1 Z0.01 F30",
            "G1 X0.5 Y0.25 E0.01 F120",
            "G21",
            "G1 Z0.4 F900",
            "G1 X20 Y10 E0.2 F2400",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "units.gcode"
            path.write_text("\n".join(lines), encoding="utf-8")
            service = GCodeAnalysisService()
            actual = service.analyze(path, force=True)
            self.assertTrue(service.native_full_analysis_info["used"])
            with (
                patch.object(parser_module, "_native_timing", None),
                patch.object(native_analysis_module, "_native_timing", None),
            ):
                expected = GCodeAnalysisService().analyze(path, force=True)
        self.assert_layer_analysis_equal(actual.analysis, expected.analysis)

    def test_xz_and_yz_plane_arcs_match_python_reference(self) -> None:
        lines = (
            "M83",
            "G90",
            "M201 X3000 Y3000 Z1000 E1000",
            "M204 S1200",
            "M205 X8 Y8 Z2 E3",
            "G1 X10 Y0 Z0.2 E0.2 F1800",
            "G18",
            "G3 X0 Z10.2 I-10 K0 E0.4 F1800",
            "G19",
            "G3 Y10 Z0.2 J0 K-10 E0.4 F1800",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "planes.gcode"
            path.write_text("\n".join(lines), encoding="utf-8")
            service = GCodeAnalysisService()
            actual = service.analyze(path, force=True)
            self.assertTrue(service.native_full_analysis_info["used"])
            with (
                patch.object(parser_module, "_native_timing", None),
                patch.object(native_analysis_module, "_native_timing", None),
            ):
                expected = GCodeAnalysisService().analyze(path, force=True)
        self.assert_layer_analysis_equal(actual.analysis, expected.analysis)
        self.assertEqual(actual.analysis.layers[0].untimed_event_count, 0)

    def test_native_cancellation_is_checked_in_bounded_intervals(self) -> None:
        lines = ["M83", "G90", "M204 S1000", "G1 Z0.2 F900"]
        lines.extend("G1 X1 E0.01 F1200" for _ in range(5_000))
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "cancel.gcode"
            path.write_text("\n".join(lines), encoding="utf-8")
            checks = 0

            def cancelled() -> bool:
                nonlocal checks
                checks += 1
                return True

            with self.assertRaises(AnalysisCancelled):
                GCodeAnalysisService().analyze(
                    path,
                    force=True,
                    cancellation_callback=cancelled,
                )
        self.assertEqual(checks, 1)

    def test_native_infill_collector_matches_python_reference(self) -> None:
        lines = (
            "; generated by BambuStudio",
            "M83",
            "G90",
            "M204 S1000",
            "EXCLUDE_OBJECT_START NAME=cooling_tower",
            "; FEATURE: Internal solid infill",
            "G1 Z0.2 F900",
            "G1 X10 Y10 E0.2 F1200",
            "EXCLUDE_OBJECT_END NAME=cooling_tower",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "infill.gcode"
            path.write_text("\n".join(lines), encoding="utf-8")
            native_collector = TowerInfillEvidenceCollector()
            service = GCodeAnalysisService()
            service.analyze(
                path,
                force=True,
                line_observer=native_collector.consume,
            )
            self.assertTrue(service.native_full_analysis_info["used"])
            reference_collector = TowerInfillEvidenceCollector()
            with (
                patch.object(parser_module, "_native_timing", None),
                patch.object(native_analysis_module, "_native_timing", None),
            ):
                GCodeAnalysisService().analyze(
                    path,
                    force=True,
                    line_observer=reference_collector.consume,
                )
        self.assertEqual(native_collector, reference_collector)
        native_collector.validate()

    def test_orca_named_object_infill_matches_python_reference(self) -> None:
        for feature in ("Internal solid infill", "Sparse infill"):
            with self.subTest(feature=feature), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "orca.gcode"
                path.write_text(
                    "; generated by OrcaSlicer 2.4.2\nM83\nG90\nM204 S1000\n"
                    "; printing object Cooling tower id:12 copy 0\n"
                    f";TYPE:{feature}\nG1 Z0.2 F900\nG1 X10 Y10 E0.2 F1200\n"
                    "; stop printing object Cooling tower id:12 copy 0\n",
                    encoding="utf-8",
                )
                native_collector = TowerInfillEvidenceCollector()
                service = GCodeAnalysisService()
                service.analyze(path, force=True, line_observer=native_collector.consume)
                self.assertTrue(service.native_full_analysis_info["used"])
                reference_collector = TowerInfillEvidenceCollector()
                with (patch.object(parser_module, "_native_timing", None),
                      patch.object(native_analysis_module, "_native_timing", None)):
                    GCodeAnalysisService().analyze(path, force=True, line_observer=reference_collector.consume)
                self.assertEqual(native_collector, reference_collector)
                self.assertEqual(native_collector.tower_block_count, 1)
                self.assertEqual(native_collector.sparse_tower_infill, feature == "Sparse infill")

    def test_prusa_firmware_labels_and_malformed_indices_match_python(self) -> None:
        for invalid in ("1.5", "1e30"):
            with self.subTest(index=invalid), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "prusa.gcode"
                path.write_text(
                    "; generated by PrusaSlicer 2.9.6\nM83\nM204 S1000\n"
                    "M486 S1\nM486 Acooling_tower\nM486 S-1\n;LAYER_CHANGE\n"
                    "M486 S1\n;TYPE:Solid infill\nG1 Z.2 F600\nG1 X10 E.2 F1200\n"
                    f"M486 S{invalid}\n;TYPE:Sparse infill\nG1 X20 E.2\nM486 S-1\n"
                    "; gcode_flavor = marlin2\n", encoding="utf-8",
                )
                native = TowerInfillEvidenceCollector()
                service = GCodeAnalysisService()
                service.analyze(path, force=True, line_observer=native.consume)
                self.assertTrue(service.native_full_analysis_info["used"])
                reference = TowerInfillEvidenceCollector()
                with (patch.object(parser_module, "_native_timing", None),
                      patch.object(native_analysis_module, "_native_timing", None)):
                    GCodeAnalysisService().analyze(path, force=True, line_observer=reference.consume)
                self.assertEqual(native, reference)
                self.assertEqual(native.tower_block_count, 1)
                self.assertFalse(native.sparse_tower_infill)

    def test_full_native_stream_bypasses_legacy_python_block_cache(self) -> None:
        def joint_gcode(*, tower_points: int, bambu: bool) -> str:
            lines = [
                (
                    "; generated by BambuStudio"
                    if bambu
                    else "; generated by AnycubicSlicerNext 1.4.1.2"
                ),
                *(
                    (
                        "M970.3 Q1 A5 K0 O1",
                        "M974 Q1 S2 P0",
                        "M993 A0 B0 C0",
                        "M624",
                        "M625",
                    )
                    if bambu
                    else ("G9111 bedTemp=61 extruderTemp=220",)
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
                with (
                    patch.object(parser_module, "_native_timing", None),
                    patch.object(native_analysis_module, "_native_timing", None),
                ):
                    reference = GCodeAnalysisService().analyze(
                        second_path,
                        force=True,
                    )

                self.assertTrue(service.native_full_analysis_info["used"])
                self.assertEqual(after["hits"], before["hits"])
                self.assertEqual(after["misses"], before["misses"])
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
