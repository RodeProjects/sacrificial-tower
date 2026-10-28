from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cooling_tower.export_paths import legacy_export_roots, EXPORT_FOLDER_NAMES
from cooling_tower.legacy_method_ids import LEGACY_POSTPROCESSOR_ID
from cooling_tower.gui.export_history import resolve_latest_export_directory
from cooling_tower.postprocessor_export import export_postprocessor_run
import test_postprocessor as fixture_module


class PostprocessorExportTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.PostprocessorTests()
        self.fixture.setUp()
        self.result = self.fixture.prepare(self.fixture.request())
        self.root = self.fixture.root / "output" / EXPORT_FOLDER_NAMES["postprocessor"]

    def tearDown(self):
        self.fixture.tearDown()

    def test_export_has_matching_artifact_reports_and_discoverable_history(self):
        result = export_postprocessor_run(self.fixture.service, self.result, self.root)
        self.assertEqual(result.output_path.read_bytes(), self.result.gcode_path.read_bytes())
        report = json.loads(result.report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["generation_method"], "postprocessor")
        self.assertEqual(report["output"]["sha256"], self.result.sha256)
        self.assertIn("rechnerische Prognosen", result.user_report_path.read_text(encoding="utf-8"))
        self.assertIn("Druckabschluss:", result.user_report_path.read_text(encoding="utf-8"))
        self.assertEqual(resolve_latest_export_directory(self.root).directory, result.run_directory)
        again = export_postprocessor_run(self.fixture.service, self.result, self.root)
        self.assertNotEqual(again.run_directory, result.run_directory)
        self.assertTrue(result.output_path.is_file())

    def test_legacy_exports_remain_discoverable_after_destination_rename(self):
        legacy = self.root.with_name(LEGACY_POSTPROCESSOR_ID)
        old = export_postprocessor_run(self.fixture.service, self.result, legacy)
        resolution = resolve_latest_export_directory(self.root, additional_roots=legacy_export_roots(self.root, "postprocessor"))
        self.assertEqual(resolution.directory, old.run_directory)
        new = export_postprocessor_run(self.fixture.service, self.result, self.root)
        self.assertEqual(resolve_latest_export_directory(self.root, additional_roots=legacy_export_roots(self.root, "postprocessor")).directory, new.run_directory)
        self.assertTrue(old.output_path.is_file())
        self.assertTrue(new.output_path.is_file())

    def test_report_failure_removes_only_new_incomplete_export(self):
        first = export_postprocessor_run(self.fixture.service, self.result, self.root)
        original = first.output_path.read_bytes()
        write_text = Path.write_text
        def fail_report(path, *args, **kwargs):
            if path.name == "export_report.json":
                raise OSError("report locked")
            return write_text(path, *args, **kwargs)
        with patch.object(Path, "write_text", fail_report):
            with self.assertRaises(OSError):
                export_postprocessor_run(self.fixture.service, self.result, self.root)
        self.assertEqual(tuple(self.root.iterdir()), (first.run_directory,))
        self.assertEqual(first.output_path.read_bytes(), original)

    def test_modified_gcode_and_slicer_directories_prevent_complete_export(self):
        self.result.gcode_path.write_text("changed")
        with self.assertRaises(ValueError):
            export_postprocessor_run(self.fixture.service, self.result, self.root)
        self.assertFalse(any(self.root.iterdir()))
        protected = self.result.request.profile.installation.profile_roots[0]
        with self.assertRaises(ValueError):
            export_postprocessor_run(self.fixture.service, self.result, protected / "exports")
        self.assertFalse(protected.exists())

    def test_report_distinguishes_profile_defaults_from_effective_values_and_timing_parts(self):
        request = self.fixture.request()
        request = replace(request, settings=replace(request.settings, automatic_target_time=True))
        request.profile.effective_values.update({"slow_down_layer_time": 18, "outer_wall_speed": 100,
            "filament_max_volumetric_speed": 1.2})
        result = self.fixture.prepare(request)
        exported = export_postprocessor_run(self.fixture.service, result, self.root)
        report = json.loads(exported.report_path.read_text(encoding="utf-8"))
        self.assertEqual(exported.target_layer_time_s, 18)
        self.assertEqual(report["effective_settings"]["target_layer_time_s"], 18)
        self.assertLess(report["effective_settings"]["print_speed_mm_s"], 100)
        self.assertIn("18.000 s", exported.user_report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["printhead"]["lower_radius_mm"], 12)
        self.assertEqual(len(report["original_layer_times_s"]), len(report["calculated_layer_times_s"]))
        self.assertTrue(report["wipe_angles_rad"])
        self.assertGreater(report["first_layer"]["line_width_mm"], 0)
        self.assertTrue(report["placement_statistics"]["indexed_moves"])
        self.assertTrue(report["collision_notes"])
        self.assertIn("keine vermessene", exported.user_report_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
