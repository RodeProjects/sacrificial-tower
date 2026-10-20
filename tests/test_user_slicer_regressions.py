"""Opt-in acceptance against the user's unchanged STL and installed profiles."""
from __future__ import annotations

import os
import shutil
import re
import sys
import tempfile
import unittest
from pathlib import Path
from threading import Event

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src")]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from slicer_acceptance_support import (
    require_profile_records,
    require_slicer_installation,
    require_test_path,
)


@unittest.skipUnless(os.environ.get("COOLING_TOWER_RUN_USER_SLICER_REGRESSION") == "1",
                     "Installed slicers and the explicitly supplied regression STL are opt-in.")
class UserSlicerRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_manual_gui import preview_test_application
        cls._app, cls._previous_font, cls._font_id = preview_test_application()

    @classmethod
    def tearDownClass(cls):
        from test_manual_gui import restore_preview_test_application
        restore_preview_test_application(cls._app, cls._previous_font, cls._font_id)

    def test_orca_reported_14_4_second_regression_and_native_total(self):
        from cooling_tower.services import GCodeAnalysisService
        from cooling_tower.file_integrity import sha256_file

        path = require_test_path(
            self,
            test_key="user_slicer_regressions",
            adapter_id="orca_slicer",
            field="reference_gcode",
        )
        before = sha256_file(path)
        snapshot = GCodeAnalysisService().analyze(path, force=True)
        # The user's screenshot is the independent Orca viewer reference.
        # Its displayed tenth-second value is not treated as an exact clock.
        self.assertAlmostEqual(snapshot.minimum_layer_time_s, 14.4, delta=.15)
        text = path.read_text(encoding="utf-8")
        native = re.search(r"estimated printing time \(normal mode\) = ([^\r\n]+)", text)
        self.assertIsNotNone(native)
        scales = {"d":86400, "h":3600, "m":60, "s":1}
        native_total = sum(float(value) * scales[unit]
                           for value, unit in re.findall(r"([\d.]+)([dhms])", native.group(1)))
        calculated_total = sum(layer.total_time_s for layer in snapshot.layers)
        self.assertLess(abs(calculated_total-native_total) / native_total, .01)
        self.assertEqual(sha256_file(path), before)
        print(f"REFERENCE orca_slicer: reported=14.4, calculated={snapshot.minimum_layer_time_s:.6f}, "
              f"native_total={native_total:.3f}, calculated_total={calculated_total:.3f}", flush=True)

    def exercise(self, adapter_id, *, accept_after_two=False):
        from cooling_tower.services import GCodeAnalysisService, SourcePreSliceService, StlValidationService
        from cooling_tower.slicers import (
            OrcaSlicerAdapter, PrusaSlicerAdapter, ProfileInventoryService,
            ProfileMatchingService, ProfileMatchingContext, ProfileMappingStore,
            ProfileSelectionReference, ProfileConfirmation, SliceRequest,
            SecureSlicerProcessRunner, read_active_presets,
        )
        from cooling_tower.slicers.profile_safety import fingerprint_profile_paths
        from cooling_tower.models import GenerationSettings, CalibrationConfig
        from cooling_tower.preview import PreviewService, PreviewRequest, OutputMode, PreviewExportService
        from cooling_tower.gui.preview_dialog import PreviewDialog

        source = require_test_path(
            self,
            test_key="user_slicer_regressions",
            field="source_stl",
        )
        build = ROOT / "build"
        build.mkdir(exist_ok=True)
        runner = SecureSlicerProcessRunner()
        if adapter_id == "prusa_slicer":
            adapter = PrusaSlicerAdapter(runner=runner)
        else:
            adapter = OrcaSlicerAdapter(runner=runner)
        installation = require_slicer_installation(adapter)
        original_paths = {installation.executable_path, source}
        active = read_active_presets(installation)
        if active.source_path:
            original_paths.add(active.source_path)
        for directory in installation.profile_roots:
            original_paths.update(p for p in directory.rglob("*") if p.is_file())
        before = fingerprint_profile_paths(original_paths)
        panel = PreviewDialog(embedded=True)
        self.addCleanup(panel.close)
        updates, scenes = [], []
        acceptance = Event()
        with tempfile.TemporaryDirectory(prefix="slicer_acceptance_", dir=build) as temporary:
            work = Path(temporary)
            preslice = None
            preview = None
            try:
                validation = StlValidationService().validate(source)
                self.assertTrue(validation.accepted, validation.technical_summary)
                selected_profiles = require_profile_records(
                    self,
                    test_key="user_slicer_regressions",
                    adapter=adapter,
                    installation=installation,
                    roles=("machine", "process", "filament"),
                    expected_sources={
                        "machine": "user",
                        "process": "user",
                        "filament": "user",
                    },
                )
                references = {
                    role: ProfileSelectionReference(record.profile_id, record.path)
                    for role, record in selected_profiles.items()
                }
                matching = ProfileMatchingService(inventory_service=ProfileInventoryService(),
                                                  mapping_store=ProfileMappingStore(work / "mappings.json"))
                match = matching.match(ProfileMatchingContext.from_stl(validation.source_artifact), installation,
                                       adapter, selected_profile_ids=references)
                self.assertIsNotNone(match.selected, match.message)
                binding = ProfileConfirmation.from_result(match, validation.source_artifact)
                confirmed = matching.confirm(match)
                preslice = SourcePreSliceService(workspace_parent=work / "preslice", timeout_s=180).run(
                    stl_validation=validation, profile_match=confirmed, confirmation=binding, adapter=adapter,
                )
                self.assertTrue(preslice.metadata_verified)
                self.assertEqual(preslice.analysis_snapshot.layer_count, 490)
                data = preslice.preview_source_data
                self.assertIsNotNone(data)
                self.assertGreater(data.occupied_bounds.minimum_x_mm, 50)
                self.assertGreater(data.occupied_bounds.minimum_y_mm, 40)
                request = PreviewRequest(
                    snapshot=preslice.analysis_snapshot,
                    settings=GenerationSettings(target_layer_time_s=12., simulate_full_tower_infill=True),
                    output_mode=OutputMode.STL,
                    calibration_config=CalibrationConfig(maximum_iterations=18, maximum_joint_slices=12,
                                                         minimum_joint_slices=3, maximum_runtime_s=900,
                                                         timeout_per_slice_s=180, time_tolerance_s=.25),
                    adapter=adapter, effective_profile=confirmed.selected.effective_profile,
                    slicer_identity_key=installation.identity_key,
                    profile_fingerprint=confirmed.effective_profile_fingerprint,
                    source_artifact=validation.source_artifact,
                    prepared_analysis_source=preslice.prepared_source,
                    prepared_source_data=data,
                )
                panel.set_building("Gemeinsame Slices werden geprüft")
                def progress(value):
                    updates.append(value)
                    if accept_after_two and value.completed_count == 2:
                        acceptance.set()
                def scene(value):
                    scenes.append(value)
                    panel.set_intermediate_scene(value)
                    self.assertAlmostEqual(panel.canvas.pitch_deg, 0.)
                preview = PreviewService().prepare(request, accept_best_event=acceptance,
                    joint_progress_callback=progress, joint_scene_callback=scene)
                calibration = preview.calibration
                joint = [item for item in calibration.iterations if item.joint_slice]
                isolated = [item for item in calibration.iterations if not item.joint_slice]
                self.assertEqual(len(isolated), 6)
                self.assertGreaterEqual(len(joint), 3)
                self.assertEqual([u.completed_count for u in updates], list(range(1, len(joint)+1)))
                self.assertEqual(len(scenes), len(joint))
                self.assertTrue(preview.joint_sliced)
                self.assertEqual(preview.completed_joint_slice_count, len(joint))
                self.assertTrue(calibration.best_iteration.joint_slice)
                self.assertTrue(preview.project_path and preview.project_path.is_file())
                if accept_after_two:
                    self.assertEqual(len(joint), 3)
                    self.assertIn(calibration.termination_reason, {"user_accepted", "target_tolerance"})
                panel.set_preview(preview)
                output = ROOT / "build" / "slicer-fixes-evidence" / adapter_id
                output.mkdir(parents=True, exist_ok=True)
                panel.resize(1000, 750)
                panel.show()
                type(self)._app.processEvents()
                self.assertTrue(panel.grab().save(str(output / "preview.png")))
                exported = PreviewExportService().export(preview, request, output)
                self.assertTrue(exported.output_path.is_file())
                self.assertTrue(exported.project_path and exported.project_path.is_file())
                sliced = adapter.slice_model(SliceRequest(exported.project_path, request.effective_profile,
                    work / "reopened", preserve_model_positions=True, purpose="calibration", timeout_s=180))
                self.assertTrue(sliced.success, sliced.failure_reason or sliced.stderr)
                shutil.copy2(sliced.gcode_path, output / "reopened.gcode")
                reopened = GCodeAnalysisService().analyze(sliced.gcode_path, force=True)
                # Independent Prusa re-slicing may vary by a few milliseconds
                # as parallel polygon/arc processing changes path rounding.
                self.assertAlmostEqual(preview.minimum_verified_layer_time_s, reopened.minimum_layer_time_s,
                    delta=.05 if adapter_id == "prusa_slicer" else 1e-5)
                self.assertEqual(reopened.layer_count, 490)
                if preview.calibrated:
                    self.assertLessEqual(abs(preview.minimum_verified_layer_time_s-12), .25)
                print(f"ACCEPTANCE {adapter_id}: separate={len(isolated)}, joint={len(joint)}, "
                      f"minimum={preview.minimum_verified_layer_time_s:.6f}, "
                      f"reopened={reopened.minimum_layer_time_s:.6f}, state={calibration.state.value}, "
                      f"termination={calibration.termination_reason}", flush=True)
            finally:
                if preview is not None:
                    preview.dispose()
                if preslice is not None:
                    preslice.cleanup()
                self.assertEqual(before, fingerprint_profile_paths(original_paths))
                after = {installation.executable_path, source}
                if active.source_path:
                    after.add(active.source_path)
                for directory in installation.profile_roots:
                    after.update(p for p in directory.rglob("*") if p.is_file())
                self.assertEqual(original_paths, after)

    def test_prusa_full_size_automatic_joint_preview_and_reopened_export(self):
        self.exercise("prusa_slicer")

    def test_orca_full_size_early_accept_requires_three_joint_slices_and_reproducible_export(self):
        self.exercise("orca_slicer", accept_after_two=True)
