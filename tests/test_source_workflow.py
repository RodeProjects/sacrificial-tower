from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cooling_tower.gui.workflow_controller import WorkflowStage
from cooling_tower.models import (
    GCodeOrigin,
    PreSliceProvenance,
    PreparedAnalysisSource,
    SourceArtifact,
    SourceKind,
)


class SourceModelTests(unittest.TestCase):
    def test_source_kind_accepts_only_stl(self) -> None:
        self.assertIs(SourceKind.from_path("MODEL.STL"), SourceKind.STL)
        for path in ("print.gcode", "model.3mf"):
            with self.subTest(path=path):
                with self.assertRaisesRegex(ValueError, "ausschließlich STL"):
                    SourceKind.from_path(path)

    def test_source_artifact_captures_immutable_stl_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.stl"
            payload = b"solid test\nendsolid test\n"
            path.write_bytes(payload)
            artifact = SourceArtifact.capture(path)
            self.assertIs(artifact.source_kind, SourceKind.STL)
            self.assertEqual(artifact.original_sha256, hashlib.sha256(payload).hexdigest())
            self.assertTrue(artifact.matches_current_file(verify_content=True))
            path.write_bytes(payload + b"changed")
            self.assertFalse(artifact.matches_current_file())

    def test_prepared_source_requires_generated_preslice_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stl = root / "model.stl"
            generated = root / "prepared.gcode"
            stl.write_bytes(b"solid x\nendsolid x\n")
            generated.write_text("G1 X1 Y1 E1\n", encoding="ascii")
            source = SourceArtifact.capture(stl)
            provenance = PreSliceProvenance.now(
                duration_s=1.5,
                cache_key="a" * 64,
                adapter_version=1,
            )
            prepared = PreparedAnalysisSource.capture(
                source_artifact=source,
                analysis_gcode_path=generated,
                gcode_origin=GCodeOrigin.GENERATED_PRESLICE,
                preslice_provenance=provenance,
            )
            self.assertTrue(prepared.matches_analysis_gcode())
            with self.assertRaisesRegex(ValueError, "Provenienz"):
                PreparedAnalysisSource.capture(
                    source_artifact=source,
                    analysis_gcode_path=generated,
                    gcode_origin=GCodeOrigin.GENERATED_PRESLICE,
                )


class WorkflowStageTests(unittest.TestCase):
    def test_workflow_contains_only_stl_preparation_stages(self) -> None:
        expected = {
            "WAITING_FOR_SOURCE",
            "VALIDATING_SOURCE",
            "VALIDATING_STL",
            "SOURCE_INVALID",
            "DISCOVERING_SLICER",
            "MATCHING_PROFILES",
            "WAITING_FOR_PROFILE_CONFIRMATION",
            "PRESLICING_MODEL",
            "ANALYZING_PRESLICE",
            "READY",
            "DEGRADED",
            "ERROR",
        }
        self.assertTrue(expected.issubset(WorkflowStage.__members__))
        self.assertNotIn("ANALYZING_GCODE", WorkflowStage.__members__)


if __name__ == "__main__":
    unittest.main()
