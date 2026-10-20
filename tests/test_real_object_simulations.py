"""Opt-in native acceptance of object support and manual full-infill overrides."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
from dataclasses import replace
from unittest.mock import patch

import test_real_manual_generation as acceptance
from cooling_tower.calibration.joint_project import validate_joint_project
from cooling_tower.preview.joint_source_toolpath import analyze_joint_source_toolpaths


@unittest.skipUnless(os.environ.get("COOLING_TOWER_RUN_REAL_SLICER_TESTS") == "1", "Installed slicer acceptance is opt-in.")
class RealObjectSimulationTests(unittest.TestCase):
    def run_adapter(self, adapter, executable, name):
        if not executable.is_file():
            self.skipTest(f"Installed slicer unavailable: {executable}")
        if os.environ.get("COOLING_TOWER_SIMULATION_CHILD") != name:
            environment = dict(os.environ, COOLING_TOWER_SIMULATION_CHILD=name,
                               COOLING_TOWER_MANUAL_ACCEPTANCE_CHILD=name, PYTHONIOENCODING="utf-8")
            outcome = subprocess.run((sys.executable, str(Path(__file__).resolve()),
                                      f"RealObjectSimulationTests.{self._testMethodName}", "-q"),
                                     cwd=acceptance.ROOT, env=environment, capture_output=True,
                                     text=True, encoding="utf-8", errors="replace", timeout=420)
            print(outcome.stdout, flush=True)
            self.assertEqual(outcome.returncode, 0, outcome.stderr + outcome.stdout[-5000:])
            return
        acceptance.RealManualGenerationTests.setUpClass()
        harness = acceptance.RealManualGenerationTests()
        self.addCleanup(harness.doCleanups)
        request_type = acceptance.ManualRequest
        export_method = acceptance.ManualExportService.export
        exports = []

        def request(**kwargs):
            profile = kwargs["effective_profile"]
            kwargs["effective_profile"] = replace(profile, effective_values={**profile.effective_values, "enable_support": "0"},
                                                  supports_simulated=False)
            kwargs["settings"] = replace(kwargs["settings"], simulate_source_supports=True, simulate_full_tower_infill=True)
            return request_type(**kwargs)

        def export(service, preview, request, output_root):
            source_paths = analyze_joint_source_toolpaths(
                preview.manual_evaluation.gcode_path,
                tower_center_xy_mm=preview.scene.tower_center_xy_mm,
                expected_layer_count=request.snapshot.layer_count,
            )
            result = export_method(service, preview, request, output_root)
            validate_joint_project(result.project_path, tower_full_infill=True, source_supports_enabled=True)
            self.assertEqual(request.effective_profile.effective_values["enable_support"], "0")
            self.assertTrue(result.source_supports_simulated)
            self.assertTrue(result.full_tower_infill_simulated)
            self.assertGreater(len(source_paths.object_segments), 1000)
            self.assertLessEqual(len(source_paths.object_segments), 60_000)
            bounds = source_paths.occupied_bounds
            tx, ty = preview.scene.tower_center_xy_mm
            self.assertFalse(bounds.minimum_x_mm <= tx <= bounds.maximum_x_mm
                             and bounds.minimum_y_mm <= ty <= bounds.maximum_y_mm)
            self.assertEqual(request.effective_profile.effective_values["enable_support"], "0")
            exports.append(result)
            return result

        with patch.object(acceptance, "ManualRequest", side_effect=request), \
             patch.object(acceptance.ManualExportService, "export", new=export):
            harness.run_adapter(adapter, executable, name + "_simulations")
        self.assertEqual(len(exports), 1)

    def test_bambu_object_supports_and_full_tower_infill(self):
        self.run_adapter(acceptance.BambuStudioAdapter(), Path(r"C:\Program Files\Bambu Studio\bambu-studio.exe"), "bambu")

    def test_anycubic_object_supports_and_full_tower_infill(self):
        self.run_adapter(acceptance.AnycubicSlicerNextAdapter(), Path(r"C:\Program Files\AnycubicSlicerNext\AnycubicSlicerNext.exe"), "anycubic")


if __name__ == "__main__":
    unittest.main()
