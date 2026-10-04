"""Full joint-slice timing follows the selected mesh through display and export."""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import trimesh

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("COOLING_TOWER_DISABLE_SLICER_DISCOVERY", "1")

from PySide6.QtWidgets import QApplication
from cooling_tower.calibration import CalibrationService
from cooling_tower.calibration.candidate_evaluation import minimum_combined_layer_time
from cooling_tower.file_integrity import sha256_file
from cooling_tower.gui.generation_panel import GenerationPanel
from cooling_tower.gui.generation_progress_dialog import TowerGenerationDialog
from cooling_tower.models import CalibrationConfig, GenerationSettings, SourceArtifact
from cooling_tower.preview import OutputMode, PreviewExportService, PreviewRequest, PreviewService
from cooling_tower.services import GCodeAnalysisService
from test_phase9 import make_snapshot
import test_phase16 as calibration_fixture
from test_real_bambu_joint_slice import _embedded_3mf_meshes


def joint_gcode(dwells: tuple[float, ...]) -> str:
    """Vary the actual slicer output, without mocking its measured timings."""
    lines = calibration_fixture.tower_gcode(layer_count=len(dwells), feed=600).splitlines()
    output = []
    layer = -1
    for line in lines:
        if line.startswith("G1 Z"):
            if layer >= 0:
                output.append(f"G4 S{dwells[layer]}")
            layer += 1
        output.append(line)
    output.append(f"G4 S{dwells[layer]}")
    return "\n".join(output) + "\n"


class JointTimingConsistencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.fixture = calibration_fixture.Phase16Tests("test_01_config_rejects_unbounded_values")
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.root = self.fixture.root
        self.model = self.root / "source.stl"
        trimesh.creation.box(extents=(10, 10, 1)).export(self.model)
        self.artifact = SourceArtifact.capture(self.model)

    def request(self, outputs, *, times=(1, 1, 1), excluded=((2, 2),)):
        adapter = calibration_fixture.SequencedAdapter(outputs)
        snapshot = make_snapshot(self.fixture.source, times)
        request = PreviewRequest(
            snapshot=snapshot,
            settings=GenerationSettings(target_layer_time_s=8, excluded_layer_ranges=excluded),
            output_mode=OutputMode.STL,
            calibration_config=CalibrationConfig(
                maximum_iterations=len(outputs), maximum_joint_slices=len(outputs),
                minimum_joint_slices=1, time_tolerance_s=.01,
            ),
            adapter=adapter, effective_profile=self.fixture.profile,
            source_artifact=self.artifact,
        )
        return request, adapter

    def test_complete_project_includes_excluded_layers_above_tower(self):
        request, adapter = self.request(
            [joint_gcode((8, 8, 8, 4, 0))],
            times=(1, 1, 1, 20, 1), excluded=((5, 5),),
        )
        updates = []
        result = CalibrationService().calibrate(
            request.snapshot, request.settings, adapter=adapter,
            profile=request.effective_profile, config=request.calibration_config,
            source_artifact=self.artifact, output_directory=self.root / "calibration",
            joint_progress_callback=updates.append,
        )
        self.assertTrue(result.has_usable_improvement, result.failures)
        self.assertEqual(result.profile.printable_layer_count, 3)
        measured = GCodeAnalysisService().analyze(result.gcode_path)
        self.assertEqual(len(result.best_iteration.evaluation.layer_timings), 5)
        self.assertEqual(min(measured.layers, key=lambda layer: layer.total_time_s).index, 5)
        self.assertAlmostEqual(minimum_combined_layer_time(updates[-1].best_iteration.evaluation), measured.minimum_layer_time_s)
        self.assertAlmostEqual(PreviewService._minimum_verified_time(request, result), measured.minimum_layer_time_s)

    def test_complete_measurement_wins_over_matched_profile_layers_in_both_displays(self):
        evaluation = SimpleNamespace(
            metadata_source="final_combined_gcode", minimum_sliced_layer_time_s=.5,
            layer_timings=(SimpleNamespace(combined_layer_time_s=8.2),),
        )
        iteration = SimpleNamespace(evaluation=evaluation)
        self.assertEqual(minimum_combined_layer_time(evaluation), .5)
        for widget_type in (GenerationPanel, TowerGenerationDialog):
            widget = widget_type(ROOT / "src/cooling_tower/gui/assets/tower_gen_finished.webp")
            self.addCleanup(widget.close)
            widget.begin(8, .2, 0, 3)
            widget.complete_slice(1, 3, iteration, 8)
            self.assertIn("0.50 s", widget.best_minimum_value.text())
            self.assertIn("7.50 s", widget.best_deviation_value.text())

    def test_same_excluded_minimum_still_allows_relevant_layers_to_improve(self):
        request, adapter = self.request([joint_gcode((4, 0, 4)), joint_gcode((6, 0, 6))])
        updates = []
        result = CalibrationService().calibrate(
            request.snapshot, request.settings, adapter=adapter,
            profile=request.effective_profile, config=request.calibration_config,
            source_artifact=self.artifact, output_directory=self.root / "plateau",
            joint_progress_callback=updates.append,
        )
        self.assertEqual(len(updates), 2)
        self.assertEqual(result.best_iteration_number, 2)
        self.assertAlmostEqual(
            minimum_combined_layer_time(updates[0].best_iteration.evaluation),
            minimum_combined_layer_time(updates[1].best_iteration.evaluation),
        )
        self.assertLess(result.iterations[1].maximum_remaining_deficit_s, result.iterations[0].maximum_remaining_deficit_s)
        self.assertEqual(result.profile.layers[1].time_deficit_s, 0)

    def test_live_best_preview_accepted_export_and_3mf_keep_the_same_candidate(self):
        request, adapter = self.request([
            joint_gcode((6, 0, 6)), joint_gcode((3, 0, 3)), joint_gcode((7, 0, 7)),
        ])
        updates, scenes = [], []
        accept = Event()

        def progress(update):
            updates.append(update)
            if update.completed_count == 2:
                accept.set()

        original_hashes = {path: sha256_file(path) for path in (*self.fixture.profile.source_paths, self.fixture.source, self.model)}
        preview = PreviewService().prepare(
            request, accept_best_event=accept,
            joint_progress_callback=progress, joint_scene_callback=scenes.append,
        )
        self.addCleanup(preview.dispose)
        result = preview.calibration
        self.assertEqual(result.termination_reason, "user_accepted")
        self.assertEqual(result.best_iteration_number, 1)
        self.assertFalse(updates[-1].current_is_best)
        self.assertIs(updates[-1].best_profile, updates[0].best_profile)
        self.assertEqual(scenes[0].tower_segments, scenes[1].tower_segments)
        self.assertEqual(preview.scene.tower_segments, scenes[-1].tower_segments)

        measured = GCodeAnalysisService().analyze(result.gcode_path)
        expected = measured.minimum_layer_time_s
        self.assertLess(expected, request.settings.target_layer_time_s)
        self.assertAlmostEqual(preview.minimum_verified_layer_time_s, expected)
        panel = GenerationPanel(ROOT / "src/cooling_tower/gui/assets/tower_gen_finished.webp")
        self.addCleanup(panel.close)
        panel.begin(8, .01, 0, 3)
        panel.complete_slice(2, 3, updates[-1].best_iteration, 8)
        live_text = panel.best_minimum_value.text(), panel.best_deviation_value.text()
        panel.set_achieved(preview.minimum_verified_layer_time_s)
        self.assertEqual((panel.best_minimum_value.text(), panel.best_deviation_value.text()), live_text)
        self.assertIn(f"{expected:.2f} s", live_text[0])
        self.assertEqual(live_text[1], f"{expected - 8:+.2f} s")

        exported = PreviewExportService().export(preview, request, self.root / "export")
        self.assertEqual(exported.minimum_verified_layer_time_s, expected)
        self.assertEqual(exported.output_sha256, sha256_file(preview.artifact_path))
        self.assertEqual(sha256_file(exported.project_path), preview.project_sha256)
        report = json.loads(exported.report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["minimum_verified_layer_time_s"], expected)
        candidate = trimesh.load(exported.output_path, force="mesh", process=True)
        self.assertTrue(any(
            abs(abs(float(mesh.volume)) - abs(float(candidate.volume))) < .01
            and all(abs(float(a) - float(b)) < .001 for a, b in zip(mesh.extents, candidate.extents))
            for mesh in _embedded_3mf_meshes(exported.project_path)
        ))
        self.assertEqual({path: sha256_file(path) for path in original_hashes}, original_hashes)


if __name__ == "__main__":
    unittest.main()
