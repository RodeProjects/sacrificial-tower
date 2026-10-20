"""Opt-in real CLI checks for simulated supports on the repository test STL."""
from __future__ import annotations

from dataclasses import replace
import json
import os
import sys
from pathlib import Path
import unittest
from xml.etree import ElementTree as ET
import zipfile

TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from slicer_acceptance_support import (
    require_profile_records,
    require_slicer_installation,
)


@unittest.skipUnless(os.environ.get("COOLING_TOWER_RUN_SUPPORT_REGRESSION") == "1",
                     "Real installed slicers and the repository test STL are opt-in")
class InstalledSourceSupportTests(unittest.TestCase):
    def exercise(self, identifier):
        from cooling_tower.slicers import (
            OrcaSlicerAdapter, PrusaSlicerAdapter, ProfileCandidate, SliceRequest, read_active_presets,
        )
        from cooling_tower.slicers.profile_safety import fingerprint_profile_paths
        from cooling_tower.slicers.support_simulation import global_supports_disabled, simulated_support_settings
        from cooling_tower.services import GCodeAnalysisService
        from cooling_tower.models import SourceArtifact, GenerationSettings, CalibrationConfig
        from cooling_tower.preview import PreviewRequest, PreviewService, PreviewExportService, OutputMode
        from cooling_tower.manual.service import ManualRequest, ManualGenerationService, ManualExportService
        from cooling_tower.manual.geometry import ManualSettings, initial_draft

        simulated_preslice = os.environ.get('COOLING_TOWER_SUPPORT_PRESLICE_SIMULATED') == '1'
        evidence = 'support-preslice-acceptance' if simulated_preslice else 'support-activation-acceptance'
        root = Path(__file__).resolve().parents[1] / 'build' / evidence / identifier
        root.mkdir(parents=True, exist_ok=True)
        source = Path(__file__).resolve().parents[1] / "input" / "Test-STL (manifold).stl"
        adapter = OrcaSlicerAdapter() if identifier == 'orca_slicer' else PrusaSlicerAdapter()
        installation = require_slicer_installation(adapter)
        selected_profiles = require_profile_records(
            self,
            test_key="source_support_regressions",
            adapter=adapter,
            installation=installation,
            roles=("machine", "process", "filament"),
            expected_sources={
                "machine": "user",
                "process": "user",
                "filament": "user",
            },
        )
        originals = {source, installation.executable_path}
        active = read_active_presets(installation)
        if active.source_path:
            originals.add(active.source_path)
        for directory in installation.profile_roots:
            originals.update(path for path in directory.rglob('*') if path.is_file())
        before = fingerprint_profile_paths(originals)
        try:
            profile = adapter.resolve_profile_bundle(ProfileCandidate(
                installation,
                selected_profiles["machine"],
                selected_profiles["process"],
                (selected_profiles["filament"],),
            ))
            self.assertTrue(global_supports_disabled(profile))
            # Use the exact preview control path: source settings remain disabled
            # globally; only the source object in the shared project gets supports.
            from cooling_tower.slicers.support_simulation import with_simulated_supports
            from cooling_tower.calibration.slice_evaluator import build_calibration_profile
            preslice_profile = with_simulated_supports(profile) if simulated_preslice else profile
            copied, overrides = build_calibration_profile(preslice_profile, root / 'preslice_profile')
            sliced = adapter.slice_model(SliceRequest(source, copied, root / 'preslice',
                temporary_overrides=overrides, timeout_s=240, diagnostics_root=root / 'preslice_diagnostics'))
            self.assertTrue(sliced.success, sliced.failure_reason)
            snapshot = GCodeAnalysisService().analyze(sliced.gcode_path, force=True)
            print('SUPPORT PHASE',identifier,'source layers',snapshot.layer_count,flush=True)
            settings = GenerationSettings(target_layer_time_s=12,
                                          simulate_full_tower_infill=True, simulate_source_supports=True)
            common = dict(snapshot=snapshot, settings=settings, output_mode=OutputMode.STL,
                calibration_config=CalibrationConfig(maximum_iterations=9, maximum_joint_slices=3,
                    minimum_joint_slices=3, maximum_runtime_s=900, timeout_per_slice_s=240),
                adapter=adapter, effective_profile=profile, source_artifact=SourceArtifact.capture(source))
            request = PreviewRequest(**common)
            updates = []
            service = PreviewService()
            preview = service.prepare(request, joint_progress_callback=updates.append)
            try:
                self.assertGreaterEqual(preview.completed_joint_slice_count, 3)
                self.assertEqual(len(updates), preview.completed_joint_slice_count)
                exported = PreviewExportService().export(preview,request,root / 'automatic_export')
                auto = self.verify_export(adapter,profile,exported,preview.minimum_verified_layer_time_s,
                                          root / 'auto_reopen',simulated_support_settings(profile))
                self.assertGreater(auto['minimum'],5)
                if preview.calibrated:
                    self.assertLessEqual(abs(auto['minimum']-settings.target_layer_time_s),
                                         common['calibration_config'].time_tolerance_s)
                print('SUPPORT PHASE',identifier,'automatic verified',auto,flush=True)
            finally:
                preview.dispose()
            manual_service = ManualGenerationService(workspace_parent=root)
            manual_request = ManualRequest(**common)
            reference = manual_service.prepare_reference(manual_request)
            draft = initial_draft(ManualSettings(),snapshot.layers,reference.context.maximum_height_mm,
                                  reference.context.key)
            manual_request = replace(manual_request, draft=draft, context=reference.context,
                                     profile_source_hashes=reference.profile_source_hashes)
            manual = manual_service.prepare(manual_request)
            try:
                temporary_gcode = manual.manual_evaluation.gcode_path
                exported = ManualExportService().export(manual,manual_request,root / 'manual_export')
                self.assertFalse((exported.run_directory / 'verification.gcode').exists())
                self.assertFalse(temporary_gcode.exists())
                self.assertIsNone(manual.manual_evaluation.gcode_path)
                manual_summary = self.verify_export(adapter,profile,exported,manual.minimum_verified_layer_time_s,
                    root / 'manual_reopen',simulated_support_settings(profile))
            finally:
                manual.dispose()
            summary = dict(source_layers=snapshot.layer_count, preslice_supports_simulated=simulated_preslice,
                           automatic=auto, manual=manual_summary)
            (root / 'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
            print('SUPPORT ACCEPTANCE', identifier, summary, flush=True)
        finally:
            self.assertEqual(before, fingerprint_profile_paths(originals))
            after = {source,installation.executable_path}
            if active.source_path:
                after.add(active.source_path)
            for directory in installation.profile_roots:
                after.update(path for path in directory.rglob('*') if path.is_file())
            self.assertEqual(originals,after)

    def verify_export(self,adapter,profile,exported,minimum,root,expected):
        from cooling_tower.slicers import SliceRequest
        from cooling_tower.services import GCodeAnalysisService
        project = next(exported.run_directory.glob('*.3mf'))
        with zipfile.ZipFile(project) as archive:
            name = ('Metadata/Slic3r_PE_model.config' if adapter.adapter_id == 'prusa_slicer'
                    else 'Metadata/model_settings.config')
            settings = ET.fromstring(archive.read(name))
            source = next(obj for obj in settings.findall('object')
                          if any(e.get('key') == 'name' and e.get('value') in ('source_object','Source object')
                                 for e in obj.findall('metadata')))
            values = {e.get('key'):e.get('value') for e in source.findall('metadata')}
            for key,value in expected.items():
                self.assertEqual(values.get(key),value)
            tower = next(obj for obj in settings.findall('object') if obj is not source)
            tower_values = {e.get('key'):e.get('value') for e in tower.findall('metadata')}
            for key in expected:
                self.assertNotIn(key,tower_values)
        sliced = adapter.slice_model(SliceRequest(project,profile,root,timeout_s=240,
            preserve_model_positions=True,purpose='calibration',diagnostics_root=root / 'diagnostics'))
        self.assertTrue(sliced.success,sliced.failure_reason)
        snapshot = GCodeAnalysisService().analyze(sliced.gcode_path,force=True)
        self.assertAlmostEqual(snapshot.minimum_layer_time_s,minimum,
                               delta=.05 if adapter.adapter_id == 'prusa_slicer' else 1e-5)
        # Tree/organic supports must not introduce the hundreds of alternating
        # support-only layers observed with the user's normal support setup.
        self.assertLessEqual(snapshot.layer_count,895)
        self.assertGreater(snapshot.minimum_layer_time_s,0)
        return dict(layers=snapshot.layer_count, minimum=snapshot.minimum_layer_time_s,
                    reopened_project=str(project))

    def test_orca_tree_supports_automatic_manual_and_reopened_project(self):
        self.exercise('orca_slicer')

    def test_prusa_organic_supports_automatic_manual_and_reopened_project(self):
        self.exercise('prusa_slicer')
