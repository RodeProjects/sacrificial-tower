"""Opt-in STL -> real pre-slice -> cooling G-code -> reconstruction -> export."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import math
import os
import json
import shutil
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import trimesh
from cooling_tower.preprocessor import PreprocessorRequest, PreprocessorService, PreprocessorSettings, BEGIN
from cooling_tower.services import GCodeAnalysisService, SourcePreSliceService, StlValidationService
from cooling_tower.slicers import (
    AnycubicSlicerNextAdapter, BambuStudioAdapter, OrcaSlicerAdapter, PrusaSlicerAdapter,
    ProfileConfirmation, ProfileInventoryService, ProfileMappingStore,
    ProfileMatchingContext, ProfileMatchingService,
)
from slicer_acceptance_support import require_slicer_installation, require_profile_records


@unittest.skipUnless(os.environ.get("COOLING_TOWER_RUN_REAL_SLICER_TESTS") == "1", "Real slicer integration is opt-in.")
class PreprocessorRealSlicerTests(unittest.TestCase):
    def exercise(self, adapter):
        installation = require_slicer_installation(adapter)
        selected = require_profile_records(self, test_key="preprocessor_acceptance", adapter=adapter,
            installation=installation, roles=("machine", "process", "filament"))
        with tempfile.TemporaryDirectory(prefix="preprocessor_acceptance_") as temporary:
            root = Path(temporary)
            source = root / "user-input" / "test_cube.stl"
            source.parent.mkdir()
            mesh = trimesh.creation.box(extents=(8, 8, 4))
            mesh.apply_translation((0, 0, 2))
            mesh.export(source)
            validation = StlValidationService().validate(source)
            self.assertTrue(validation.valid, validation.technical_summary)
            matcher = ProfileMatchingService(inventory_service=ProfileInventoryService(root / "inventory.json"),
                mapping_store=ProfileMappingStore(root / "mapping.json"))
            match = matcher.match(ProfileMatchingContext.from_stl(validation.source_artifact),
                installation, adapter, force_inventory=True, include_all_profiles=True,
                selected_profile_ids={role: str(record.path) for role, record in selected.items()})
            self.assertIsNotNone(match.selected, match.message)
            confirmation = ProfileConfirmation.from_result(match, validation.source_artifact)
            confirmed = matcher.confirm(match)
            profile = confirmed.selected.effective_profile
            protected = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in profile.source_paths}
            preslice = SourcePreSliceService(workspace_parent=root / "preslice", diagnostics_root=root / "diagnostics").run(
                stl_validation=validation, profile_match=confirmed, confirmation=confirmation, adapter=adapter)
            result = None
            second = None
            try:
                artifacts = os.environ.get("COOLING_TOWER_PREPROCESSOR_ARTIFACT_ROOT")
                if artifacts:
                    artifact_root = Path(artifacts) / adapter.adapter_id
                    artifact_root.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(preslice.prepared_source.analysis_gcode_path, artifact_root / "source.gcode")
                    shutil.copyfile(source, artifact_root / "source.stl")
                    (artifact_root / "profile.json").write_text(json.dumps(dict(profile.effective_values), default=str), encoding="utf-8")
                request = PreprocessorRequest(preslice.prepared_source, preslice.analysis_snapshot, profile,
                    PreprocessorSettings(target_layer_time_s=60))
                service = PreprocessorService(root / "generated")
                result = service.prepare(request)
                self.assertGreater(result.wait_count, 0)
                self.assertTrue(result.scene.tower_segments)
                self.assertTrue(result.scene.object_segments)
                self.assertTrue(result.scene.travel_segments)
                self.assertTrue(result.scene.wait_points)
                for point in result.scene.wait_points:
                    self.assertGreaterEqual(math.dist((point.x, point.y), result.scene.tower_center_xy_mm),
                        result.base_width_mm/2 + request.settings.wait_clearance_mm)
                self.assertTrue(result.request.settings.hollow_tower)
                output = service.export(result, root / "export.gcode")
                output_analysis = GCodeAnalysisService().analyze(output)
                self.assertEqual(output_analysis.layer_count, preslice.analysis_snapshot.layer_count)
                self.assertGreaterEqual(min(layer.total_time_s for layer in output_analysis.layers), 59.9)
                second = service.prepare(replace(request, settings=replace(request.settings, target_layer_time_s=65)))
                self.assertGreater(second.total_wait_s, result.total_wait_s)
                self.assertEqual(second.gcode_path.read_text().count(BEGIN), result.gcode_path.read_text().count(BEGIN))
                self.assertTrue(preslice.prepared_source.matches_analysis_gcode())
                self.assertEqual({path: hashlib.sha256(path.read_bytes()).hexdigest() for path in protected}, protected)
            finally:
                if second is not None:
                    second.dispose()
                if result is not None:
                    result.dispose()
                preslice.cleanup()

    def test_anycubic(self):
        self.exercise(AnycubicSlicerNextAdapter())

    def test_bambu(self):
        self.exercise(BambuStudioAdapter())

    def test_orca(self):
        self.exercise(OrcaSlicerAdapter())

    def test_prusa(self):
        self.exercise(PrusaSlicerAdapter())


if __name__ == "__main__":
    unittest.main()
