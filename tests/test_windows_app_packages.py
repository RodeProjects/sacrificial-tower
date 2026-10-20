from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from cooling_tower.slicers import (
    OrcaSlicerAdapter, SlicerDiscoverySource, SlicerSupportLevel, default_adapters,
)
from cooling_tower.slicers.windows_app_packages import (
    MAXIMUM_PACKAGE_RESPONSE_BYTES, PACKAGE_LOOKUP_TIMEOUT_S,
    _package_adapters, _package_candidates, discover_windows_app_packages,
)
from test_slicer_failure_safety import _SlicerGuiFixture, discovery_result


class WindowsPackageCandidateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.adapters = default_adapters()
        self.known = _package_adapters(self.adapters)
        self.executable = self.root / "orca-slicer.exe"
        self.executable.write_bytes(b"MZ")
        self.record = {
            "package_name": "Publisher.UnrelatedIdentity",
            "version": "2.4.3.0",
            "install_location": str(self.root),
            "executable": self.executable.name,
        }

    def test_all_known_slicer_executable_names_are_detected_without_package_name_assumptions(self):
        records = []
        for index, name in enumerate(self.known):
            root = self.root / f"package-{index}"
            root.mkdir()
            (root / name).write_bytes(b"MZ")
            records.append({**self.record, "install_location": str(root), "executable": name})
        candidates = _package_candidates(records, self.known)
        self.assertEqual(len(candidates), len(self.known))
        self.assertEqual(
            {item.adapter_hint for item in candidates},
            {adapter.adapter_id for adapter in self.adapters},
        )
        self.assertTrue(all(item.discovery_source is SlicerDiscoverySource.APP_PACKAGE for item in candidates))

    def test_packaged_orca_is_supported_and_never_executed_during_detection(self):
        candidate, = _package_candidates([self.record], self.known)
        runner = Mock()
        adapter = OrcaSlicerAdapter(runner=runner)
        with patch.dict(os.environ, {"APPDATA": str(self.root / "user-data")}):
            result = adapter.verify_installation(candidate)
        self.assertEqual(result.version, "2.4.3.0")
        self.assertTrue(result.automatically_discovered)
        self.assertTrue(result.can_slice)
        self.assertEqual(result.support_level, SlicerSupportLevel.FULL)
        self.assertNotIn("nur erkannt", result.display_name)
        runner.run.assert_not_called()

    def test_vfs_and_unicode_install_paths_are_supported(self):
        root = self.root / "Änderbare Namen 空格"
        executable = root / "VFS" / "ProgramFilesX64" / "OrcaSlicer" / "ORCA-SLICER.EXE"
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"MZ")
        record = {**self.record, "install_location": str(root), "executable": r"VFS\ProgramFilesX64\OrcaSlicer\ORCA-SLICER.EXE"}
        candidate, = _package_candidates([record], self.known)
        self.assertEqual(candidate.executable_path, executable.resolve())

    def test_unknown_launchers_missing_files_and_escaping_paths_are_rejected(self):
        for relative in (
            "unknown.exe", "orca-slicer.dll", r"..\orca-slicer.exe", "../orca-slicer.exe",
            r"C:\orca-slicer.exe", r"\orca-slicer.exe", r"C:orca-slicer.exe",
            r"missing\orca-slicer.exe", r"\\server\share\orca-slicer.exe",
        ):
            with self.subTest(relative=relative):
                self.assertEqual(_package_candidates([{**self.record, "executable": relative}], self.known), ())

    def test_malformed_entries_do_not_hide_valid_packages(self):
        for invalid in (None, 1, "text", {}, {**self.record, "executable": []}, {**self.record, "install_location": "relative"}):
            with self.subTest(invalid=invalid):
                self.assertEqual(len(_package_candidates([invalid, self.record], self.known)), 1)
        for invalid_response in (None, {}, "text", 12):
            self.assertEqual(_package_candidates(invalid_response, self.known), ())

    def test_denied_executable_and_resolved_path_outside_package_fail_closed(self):
        with patch.object(Path, "is_file", side_effect=PermissionError()):
            self.assertEqual(_package_candidates([self.record], self.known), ())
        outside = self.root.parent / "orca-slicer.exe"
        with patch.object(Path, "resolve", side_effect=[self.root, outside]):
            self.assertEqual(_package_candidates([self.record], self.known), ())

    @unittest.skipUnless(os.name == "nt", "Windows package API")
    def test_query_is_bounded_and_passes_names_as_data(self):
        completed = SimpleNamespace(returncode=0, stdout=json.dumps([self.record]))
        with patch("cooling_tower.slicers.windows_app_packages.subprocess.run", return_value=completed) as run:
            self.assertEqual(len(discover_windows_app_packages(self.adapters)), 1)
        args, kwargs = run.call_args
        self.assertEqual(set(json.loads(kwargs["input"])), set(self.known))
        self.assertEqual(kwargs["timeout"], PACKAGE_LOOKUP_TIMEOUT_S)
        self.assertFalse(kwargs["shell"])
        self.assertIn("-NonInteractive", args[0])
        self.assertIn("Get-AppxPackageManifest", args[0][-1])
        self.assertNotIn("Add-AppxPackage", args[0][-1])

    @unittest.skipUnless(os.name == "nt", "Windows package API")
    def test_optional_query_errors_and_oversized_responses_do_not_escape(self):
        for error in (OSError(), subprocess.TimeoutExpired("powershell.exe", 12)):
            with self.subTest(error=error), patch("cooling_tower.slicers.windows_app_packages.subprocess.run", side_effect=error):
                self.assertEqual(discover_windows_app_packages(self.adapters), ())
        for completed in (
            SimpleNamespace(returncode=1, stdout=""),
            SimpleNamespace(returncode=0, stdout="not json"),
            SimpleNamespace(returncode=0, stdout="x" * (MAXIMUM_PACKAGE_RESPONSE_BYTES + 1)),
        ):
            with self.subTest(completed=completed.returncode), patch("cooling_tower.slicers.windows_app_packages.subprocess.run", return_value=completed):
                self.assertEqual(discover_windows_app_packages(self.adapters), ())


class WindowsPackageGuiSafetyTests(_SlicerGuiFixture, unittest.TestCase):
    def test_explicitly_detection_only_store_slicer_cannot_start_profile_processing(self):
        executable = self.root / "orca-slicer.exe"
        executable.write_bytes(b"MZ")
        record = {
            "package_name": "DifferentPublisher.StoreIdentity", "version": "2.4.3.0",
            "install_location": str(self.root), "executable": executable.name,
        }
        candidate, = _package_candidates([record], _package_adapters(default_adapters()))
        adapter = OrcaSlicerAdapter(runner=Mock())
        with patch.dict(os.environ, {"APPDATA": str(self.root / "user-data")}):
            item = adapter.verify_installation(candidate)
        item = replace(item, support_level=SlicerSupportLevel.DETECTION_ONLY, capabilities=frozenset())
        self.service.discover_installations.return_value = discovery_result(self.working, item)
        window = self.start()
        before = self.profiles.catalog.call_count
        window.slicer_combo.setCurrentIndex(window.slicer_combo.findData(item.identity_key))
        self.assertIn("nur erkannt", window.slicer_combo.currentText())
        self.assert_failed(window)
        self.assertIn("noch nicht", window.profile_status_label.text())
        self.assertEqual(self.profiles.catalog.call_count, before)
        self.assertTrue(window.close())


@unittest.skipUnless(
    os.environ.get("COOLING_TOWER_RUN_INSTALLED_STORE_SLICER_TEST") == "1",
    "Real installed Store slicer test is opt-in.",
)
class InstalledStoreSlicerTests(unittest.TestCase):
    def test_registered_store_orca_is_detected_read_only(self):
        candidates = discover_windows_app_packages(default_adapters())
        candidate = next(
            (item for item in candidates if item.adapter_hint == "orca_slicer"),
            None,
        )
        if candidate is None:
            self.skipTest(
                "Kein registrierter OrcaSlicer aus dem Microsoft Store gefunden; "
                "Store-Slicer-Abnahme übersprungen."
            )
        before = (candidate.executable_path.stat().st_size, candidate.executable_path.stat().st_mtime_ns)
        adapter = OrcaSlicerAdapter(runner=Mock())
        item = adapter.verify_installation(candidate)
        self.assertTrue(item.can_slice)
        self.assertTrue(item.verified)
        self.assertNotIn("nur erkannt", item.display_name)
        self.assertEqual(before, (candidate.executable_path.stat().st_size, candidate.executable_path.stat().st_mtime_ns))
        adapter.runner.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
