from __future__ import annotations

import csv
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from PySide6.QtWidgets import QApplication

from cooling_tower.gcode.layer_detector import (
    LayerAnalysis,
    LayerRecord,
)
from cooling_tower.gui import MainWindow
from cooling_tower.models import (
    GCodeAnalysisSnapshot,
    GenerationResult,
    GenerationSettings,
    NoTowerRequiredResult,
)
from cooling_tower.services import (
    AnalysisCancelled,
    GCodeAnalysisService,
    GenerationService,
    assess_tower_need,
    format_no_tower_report,
)


SAMPLE_GCODE = "\n".join(
    (
        "G90",
        "M83",
        "G1 Z0.2 F600",
        "G1 X10 E1 F600",
        "G1 Z0.4 F600",
        "G1 X20 E1 F600",
        "G1 Z0.6 F600",
        "G1 X30 E1 F600",
    )
)


def generation_settings(
    target_layer_time_s: float,
    *,
    safety_factor: float = 1.0,
) -> GenerationSettings:
    return GenerationSettings(
        target_layer_time_s=target_layer_time_s,
        safety_factor=safety_factor,
        minimum_outer_radius_mm=3.0,
        maximum_outer_radius_mm=20.0,
        minimum_wall_thickness_mm=0.8,
        maximum_wall_thickness_mm=2.1,
        wall_path_width_mm=0.42,
        minimum_inner_radius_mm=1.0,
        minimum_base_radius_mm=4.0,
        base_height_mm=0.2,
        base_margin_mm=1.0,
        base_height_factor=0.0,
        minimum_radius_height_factor=0.0,
        maximum_radius_change_per_mm_z=10.0,
        maximum_wall_change_per_mm_z=10.0,
        local_reference_window=3,
        mesh_segments=12,
    )


def make_layer(
    index: int,
    z_mm: float,
    height_mm: float,
    total_time_s: float,
) -> LayerRecord:
    path = max(total_time_s * 10.0, 1.0)
    return LayerRecord(
        index=index,
        z_mm=z_mm,
        height_mm=height_mm,
        start_line=index * 10,
        first_deposition_line=index * 10 + 1,
        end_line=index * 10 + 9,
        event_count=2,
        movement_count=2,
        deposition_count=1,
        total_time_s=total_time_s,
        deposition_time_s=total_time_s,
        travel_time_s=0.0,
        retraction_time_s=0.0,
        unretraction_time_s=0.0,
        dwell_time_s=0.0,
        other_time_s=0.0,
        deposition_path_mm=path,
        deposition_e_mm=1.0,
        untimed_event_count=0,
        untimed_distance_mm=0.0,
    )


def make_snapshot(
    path: Path,
    layer_times: tuple[float, ...],
    *,
    layer_heights: tuple[float, ...] | None = None,
) -> GCodeAnalysisSnapshot:
    if not path.exists():
        path.write_text("snapshot source", encoding="utf-8")
    heights = layer_heights or tuple(0.2 for _ in layer_times)
    z_mm = 0.0
    layers: list[LayerRecord] = []
    for position, (layer_time, layer_height) in enumerate(
        zip(layer_times, heights, strict=True),
        start=1,
    ):
        z_mm += layer_height
        layers.append(
            make_layer(position, z_mm, layer_height, layer_time)
        )
    analysis = LayerAnalysis(
        layers=tuple(layers),
        confirmed_layer_changes=max(0, len(layers) - 1),
        rejected_z_candidates=0,
        pre_layer_event_count=0,
        pre_layer_time_s=0.0,
        pre_layer_untimed_event_count=0,
    )
    statistics = path.resolve().stat()
    total_deposition_time = sum(
        layer.deposition_time_s for layer in layers
    )
    total_deposition_path = sum(
        layer.deposition_path_mm for layer in layers
    )
    return GCodeAnalysisSnapshot(
        gcode_path=path.resolve(),
        file_size_bytes=statistics.st_size,
        file_modified_ns=statistics.st_mtime_ns,
        analysis=analysis,
        minimum_layer_time_s=min(layer_times),
        maximum_layer_time_s=max(layer_times),
        maximum_print_z_mm=layers[-1].z_mm,
        global_seconds_per_deposition_mm=(
            total_deposition_time / total_deposition_path
        ),
    )


class TowerNeedAssessmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "assessment.gcode"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_no_layer_below_or_exactly_at_target_needs_no_tower(self) -> None:
        snapshot = make_snapshot(self.source, (5.0, 6.0, 7.0))
        assessment = assess_tower_need(
            snapshot,
            generation_settings(5.0),
        )
        self.assertFalse(assessment.tower_required)
        self.assertEqual(assessment.deficit_layer_count, 0)
        self.assertIsNone(assessment.tower_end_z_mm)
        self.assertEqual(assessment.tower_layer_count, 0)

    def test_epsilon_ignores_rounding_but_real_deficit_requires_tower(self) -> None:
        almost_equal = make_snapshot(
            self.source,
            (5.0 - 0.5e-6, 6.0),
        )
        self.assertFalse(
            assess_tower_need(
                almost_equal,
                generation_settings(5.0),
            ).tower_required
        )
        real_deficit = make_snapshot(
            self.source,
            (5.0 - 2.0e-6, 6.0),
        )
        self.assertTrue(
            assess_tower_need(
                real_deficit,
                generation_settings(5.0),
            ).tower_required
        )

    def test_first_last_deficit_and_early_end_are_reported(self) -> None:
        snapshot = make_snapshot(
            self.source,
            (10.0, 2.0, 10.0, 10.0),
            layer_heights=(0.2, 0.3, 0.1, 0.4),
        )
        assessment = assess_tower_need(
            snapshot,
            generation_settings(5.0),
        )
        self.assertTrue(assessment.tower_required)
        self.assertEqual(assessment.first_deficit_layer_index, 2)
        self.assertEqual(assessment.last_deficit_layer_index, 2)
        self.assertEqual(assessment.tower_end_layer_index, 2)
        self.assertAlmostEqual(assessment.tower_end_z_mm, 0.5)
        self.assertEqual(assessment.tower_layer_count, 2)
        self.assertAlmostEqual(assessment.saved_tower_height_mm, 0.5)
        self.assertFalse(assessment.synthetic_final_layer_used)

    def test_critical_final_layer_ends_at_object_height(self) -> None:
        snapshot = make_snapshot(
            self.source,
            (10.0, 10.0, 2.0),
            layer_heights=(0.2, 0.3, 0.15),
        )
        assessment = assess_tower_need(
            snapshot,
            generation_settings(5.0),
        )
        self.assertFalse(assessment.synthetic_final_layer_used)
        self.assertEqual(assessment.last_deficit_layer_index, 3)
        self.assertEqual(assessment.tower_end_layer_index, 3)
        self.assertAlmostEqual(assessment.tower_end_z_mm, 0.65)
        self.assertEqual(assessment.tower_layer_count, 3)

    def test_safety_factor_changes_capacity_not_need_decision(self) -> None:
        snapshot = make_snapshot(self.source, (5.0, 6.0))
        first = assess_tower_need(
            snapshot,
            generation_settings(5.0, safety_factor=1.0),
        )
        second = assess_tower_need(
            snapshot,
            generation_settings(5.0, safety_factor=2.0),
        )
        self.assertFalse(first.tower_required)
        self.assertFalse(second.tower_required)


class AnalysisCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "cache.gcode"
        self.source.write_text(SAMPLE_GCODE, encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_unchanged_file_returns_same_snapshot_instance(self) -> None:
        service = GCodeAnalysisService()
        first = service.analyze(self.source)
        second = service.analyze(self.source)
        self.assertIs(first, second)
        self.assertTrue(first.matches_file())

    def test_changed_file_invalidates_cache_and_is_reanalyzed(self) -> None:
        service = GCodeAnalysisService()
        first = service.analyze(self.source)
        self.source.write_text(
            SAMPLE_GCODE + "\nG1 Z0.8 F600\nG1 X40 E1 F600",
            encoding="utf-8",
        )
        second = service.analyze(self.source)
        self.assertIsNot(first, second)
        self.assertEqual(second.layer_count, first.layer_count + 1)

    def test_obsolete_analysis_can_be_cancelled(self) -> None:
        service = GCodeAnalysisService()
        with self.assertRaises(AnalysisCancelled):
            service.analyze(
                self.source,
                cancellation_callback=lambda: True,
            )


class GenerationBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "generation.gcode"
        self.source.write_text("snapshot source", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_no_tower_result_creates_no_output_directory(self) -> None:
        snapshot = make_snapshot(self.source, (5.0, 6.0, 7.0))
        output_root = self.root / "no_output"
        result = GenerationService(output_root).generate_from_analysis(
            snapshot,
            generation_settings(5.0),
        )
        self.assertIsInstance(result, NoTowerRequiredResult)
        self.assertFalse(output_root.exists())
        self.assertIn("keine STL", result.reason)
        self.assertIn("STL: nicht erzeugt", format_no_tower_report(result))

    def test_profile_and_mesh_end_at_last_deficit(self) -> None:
        snapshot = make_snapshot(
            self.source,
            (10.0, 2.0, 10.0, 10.0),
        )
        output_root = self.root / "shortened"
        result = GenerationService(output_root).generate_from_analysis(
            snapshot,
            generation_settings(5.0),
        )
        self.assertIsInstance(result, GenerationResult)
        self.assertAlmostEqual(result.assessment.tower_end_z_mm, 0.4)
        self.assertAlmostEqual(
            result.mesh_validation.maximum_z_mm,
            0.4,
        )
        self.assertEqual(len(result.profile), 2)
        with result.analysis_path.open(
            mode="r", encoding="utf-8", newline=""
        ) as csv_file:
            rows = list(csv.DictReader(csv_file))
        self.assertEqual(len(rows), 4)

    def test_critical_last_layer_ends_mesh_at_object_height(self) -> None:
        snapshot = make_snapshot(
            self.source,
            (10.0, 10.0, 10.0, 2.0),
        )
        result = GenerationService(
            self.root / "synthetic"
        ).generate_from_analysis(
            snapshot,
            generation_settings(5.0),
        )
        self.assertIsInstance(result, GenerationResult)
        self.assertFalse(result.assessment.synthetic_final_layer_used)
        self.assertAlmostEqual(result.assessment.tower_end_z_mm, 0.8)
        self.assertAlmostEqual(
            result.mesh_validation.maximum_z_mm,
            0.8,
        )


class CliNoTowerTests(unittest.TestCase):
    def test_cli_reports_success_without_creating_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "cli.gcode"
            source.write_text(SAMPLE_GCODE, encoding="utf-8")
            output = root / "output"
            command = (
                sys.executable,
                "-B",
                str(PROJECT_ROOT / "cli_main.py"),
                "--gcode",
                str(source),
                "--target-time",
                "0.5",
                "--output-root",
                str(output),
                "--preview",
                "0",
            )
            completed = subprocess.run(
                command,
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("Kühlturm erforderlich: Nein", completed.stdout)
            self.assertIn("STL: nicht erzeugt", completed.stdout)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
