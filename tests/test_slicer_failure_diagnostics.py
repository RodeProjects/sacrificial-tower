from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cooling_tower.diagnostics import DiagnosticJournal, current_diagnostic_journal, set_current_diagnostic_journal
from cooling_tower.slicers.adapters import BambuStudioAdapter
from cooling_tower.slicers.base import BaseSlicerAdapter
from cooling_tower.slicers.failure_diagnostics import SlicerFailureArchive, prune_session_failure_archive
from cooling_tower.slicers.models import SliceRequest
from cooling_tower.slicers.process import ProcessOutcome
from cooling_tower.calibration.joint_project import JointProjectError


class SlicerFailureDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        previous = current_diagnostic_journal()
        self.addCleanup(set_current_diagnostic_journal, previous)
        self.journal = DiagnosticJournal(self.root / "logs/background_jobs.jsonl")
        set_current_diagnostic_journal(self.journal)

    def prepared(self):
        parent = self.root / "temporary/preview/calibration"
        work = parent / "slicer"
        (work / "input").mkdir(parents=True)
        (work / "output").mkdir()
        (work / "effective_profiles").mkdir()
        model = work / "input/candidate.3mf"
        model.write_bytes(b"exact native project")
        (work / "effective_profiles/machine.json").write_text('{"name":"local profile"}')
        profile = SimpleNamespace(
            installation=SimpleNamespace(adapter_id="bambu_studio", version="02.08.02.61",
                                         executable_path=self.root / "installation/slicer.exe", profile_roots=()),
            source_paths=(),
        )
        request = SliceRequest(model, profile, parent / "slice", diagnostics_root=parent / "diagnostics",
                               purpose="calibration", calibration_round=7)
        prepared = SimpleNamespace(request=request, working_root=work, input_directory=work / "input",
                                   output_directory=work / "output", copied_model=model,
                                   arguments=("--arrange", "1"), executable=profile.installation.executable_path)
        outcome = ProcessOutcome(("slicer.exe", "--slice", "0", str(model)), 2, "output", "error", 100,
                                 process_id=123, backend="qprocess")
        return prepared, outcome

    def test_failed_cancelled_and_timed_out_calls_survive_all_temporary_cleanup(self):
        prepared, original = self.prepared()
        hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in prepared.working_root.rglob("*") if p.is_file()}
        paths = []
        for flags in ({}, {"cancelled": True}, {"timed_out": True}, {"crashed": True}):
            with self.subTest(flags=flags):
                result = BaseSlicerAdapter().finalize_slice(prepared, replace(original, **flags))
                self.assertFalse(result.success)
                paths.append(result.diagnostic_path)
                payload = json.loads(result.diagnostic_path.read_text())
                self.assertEqual(payload["calibration_round"], 7)
                self.assertEqual(payload["process_id"], 123)
                self.assertEqual(payload["command"], list(original.command))
                for key, value in flags.items(): self.assertEqual(payload[key], value)
                saved = result.diagnostic_path.parent / "input/candidate.3mf"
                self.assertEqual(saved.read_bytes(), b"exact native project")
                entry = next(e for e in payload["files"] if e["path"] == "input/candidate.3mf")
                self.assertEqual(entry["sha256"], hashes[prepared.copied_model])
                self.assertTrue((result.diagnostic_path.parent / "effective_profiles/machine.json").is_file())
        self.assertEqual({p: hashlib.sha256(p.read_bytes()).hexdigest() for p in hashes}, hashes)
        BaseSlicerAdapter.cleanup_prepared_slice(prepared)
        import shutil
        shutil.rmtree(self.root / "temporary")
        self.assertTrue(all(p.is_file() for p in paths))

    def test_failed_native_project_export_is_retained_before_cleanup(self):
        prepared, outcome = self.prepared()
        tower = self.root / "tower.stl"
        tower.write_bytes(b"exact tower")
        runner = SimpleNamespace(run=lambda executable, arguments, **kw: replace(outcome, command=(str(executable), *arguments)))
        adapter = BambuStudioAdapter(runner=runner)
        with patch.object(adapter, "prepare_slice", return_value=prepared):
            with self.assertRaises(JointProjectError):
                adapter.create_joint_project(prepared.request, prepared.copied_model, tower, self.root / "project.3mf",
                                             occupied=object(), placement=object(), tower_full_infill=True)
        self.assertFalse(prepared.working_root.exists())
        path = next((self.root / "logs/slicer_failures").glob("slice-*/slicer_failure.json"))
        self.assertIn("--export-3mf", json.loads(path.read_text())["command"])
        self.assertEqual((path.parent / "input/tower.stl").read_bytes(), tower.read_bytes())

    def test_spooled_output_has_a_durable_result_path(self):
        prepared, outcome = self.prepared()
        spool = prepared.working_root / "output.binlog"
        spool.write_bytes(b"full process output")
        result = BaseSlicerAdapter().finalize_slice(prepared, replace(outcome, output_diagnostic_path=spool))
        BaseSlicerAdapter.cleanup_prepared_slice(prepared)
        self.assertEqual(result.process_output_diagnostic_path.read_bytes(), b"full process output")

    def test_disabled_retention_does_not_create_an_archive(self):
        prepared, outcome = self.prepared()
        prepared.request = replace(prepared.request, retain_failure_diagnostics=False)
        result = BaseSlicerAdapter().finalize_slice(prepared, outcome)
        self.assertIsNone(result.diagnostic_path)
        self.assertFalse((self.root / "logs/slicer_failures").exists())

    def test_assembly_references_are_saved_and_raw_files_do_not_enter_support_exports(self):
        prepared, outcome = self.prepared()
        source = self.root / "original.stl"
        source.write_bytes(b"PRIVATE_MODEL_CONTENT")
        model = prepared.working_root / "input/assemble.json"
        model.write_text(json.dumps({"plates": [{"objects": [{"path": str(source)}]}]}))
        prepared.request = replace(prepared.request, model_path=model, use_cli_assemble_list=True)
        result = BaseSlicerAdapter().finalize_slice(prepared, outcome)
        saved = result.diagnostic_path.parent / "assembly_inputs/001.stl"
        self.assertEqual(saved.read_bytes(), source.read_bytes())
        from cooling_tower.support_report import SupportReportService

        bundle = SupportReportService(self.root, diagnostic_journal=self.journal).create_bundle()
        with zipfile.ZipFile(bundle.path) as archive:
            self.assertEqual(len(archive.namelist()), 3)
            self.assertFalse(any(b"PRIVATE_MODEL_CONTENT" in archive.read(name) for name in archive.namelist()))

    def test_failed_retention_does_not_replace_the_slicer_failure(self):
        prepared, outcome = self.prepared()
        with patch.object(SlicerFailureArchive, "retain", side_effect=PermissionError("locked")):
            result = BaseSlicerAdapter().finalize_slice(prepared, outcome)
        self.assertEqual(result.return_code, 2)
        self.assertFalse(result.success)
        self.assertIsNone(result.diagnostic_path)

    def test_count_age_and_startup_pruning_leave_unrelated_files_alone(self):
        archive = SlicerFailureArchive(self.root / "archive", maximum_cases=2)
        first = archive.retain({}, [])
        os.utime(first.parent, (time.time()-100, time.time()-100))
        second = archive.retain({}, [])
        third = archive.retain({}, [])
        self.assertFalse(first.exists())
        self.assertTrue(second.exists() and third.exists())
        foreign = archive.root / "unrelated"
        foreign.mkdir()
        (foreign / "keep.txt").write_text("keep")
        os.utime(second.parent, (1, 1))
        archive.prune()
        self.assertFalse(second.exists())
        self.assertTrue((foreign / "keep.txt").exists())
        # Startup uses the same bounded location as capture.
        session_root = self.root / "logs/slicer_failures"
        old = SlicerFailureArchive(session_root).retain({}, [])
        os.utime(old.parent, (1, 1))
        prune_session_failure_archive()
        self.assertFalse(old.exists())

    def test_byte_quota_and_oversized_evidence_are_explicit(self):
        archive = SlicerFailureArchive(self.root / "archive", maximum_cases=10,
                                      maximum_bytes=8192, maximum_case_bytes=4096)
        source = self.root / "evidence.stl"
        source.write_bytes(b"x" * 1800)
        paths = [archive.retain({}, [(source, "input/model.stl")]) for _ in range(5)]
        self.assertLess(sum(p.exists() for p in paths), 5)
        self.assertLessEqual(sum(p.stat().st_size for p in archive.root.rglob("*") if p.is_file()), 8192)
        source.write_bytes(b"x" * 5000)
        saved = archive.retain({"stderr": "e" * 10000}, [(source, "input/model.stl")])
        payload = json.loads(saved.read_text())
        self.assertEqual(payload["files"][0]["omitted"], "size_limit")
        self.assertTrue(payload["stderr_archive_truncated"])
        self.assertFalse((saved.parent / "input/model.stl").exists())

    def test_parallel_failures_do_not_overwrite_cases_or_exceed_count(self):
        archive = SlicerFailureArchive(self.root / "archive", maximum_cases=3)
        with ThreadPoolExecutor(max_workers=4) as pool:
            paths = list(pool.map(lambda i: archive.retain({"process_id": i}, []), range(12)))
        self.assertEqual(len(set(paths)), 12)
        self.assertEqual(sum(p.exists() for p in paths), 3)

    def test_cleanup_does_not_follow_a_link_to_another_directory(self):
        archive = SlicerFailureArchive(self.root / "archive")
        archive.root.mkdir()
        outside = self.root / "outside"
        outside.mkdir()
        marker = outside / "keep.txt"
        marker.write_text("keep")
        link = archive.root / ("slice-" + "a" * 32)
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            if os.name != "nt":
                self.skipTest("Creating directory symlinks is unavailable.")
            created = subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(outside)],
                capture_output=True, check=False,
            )
            if created.returncode:
                self.skipTest("Creating directory links is unavailable.")
        archive.prune()
        self.assertEqual(marker.read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
