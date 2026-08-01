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

from cooling_tower.gui.workflow_controller import (
    WorkflowStage,
    _ALLOWED_TRANSITIONS,
)
from cooling_tower.models import (
    GCodeOrigin,
    PreSliceProvenance,
    PreparedAnalysisSource,
    SourceArtifact,
    SourceKind,
)


class SourceModelTests(unittest.TestCase):
    def test_source_kind_is_restricted_to_stl_and_gcode(self) -> None:
        self.assertIs(SourceKind.from_path("MODEL.STL"), SourceKind.STL)
        self.assertIs(SourceKind.from_path("print.GCODE"), SourceKind.GCODE)
        with self.assertRaisesRegex(ValueError, "STL- und G-Code"):
            SourceKind.from_path("model.3mf")

    def test_source_artifact_captures_immutable_file_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.stl"
            payload = b"solid test\nendsolid test\n"
            path.write_bytes(payload)
            artifact = SourceArtifact.capture(path)
            self.assertIs(artifact.source_kind, SourceKind.STL)
            self.assertEqual(artifact.original_size, len(payload))
            self.assertEqual(
                artifact.original_sha256,
                hashlib.sha256(payload).hexdigest(),
            )
            self.assertTrue(artifact.matches_current_file(verify_content=True))
            path.write_bytes(payload + b"changed")
            self.assertFalse(artifact.matches_current_file())

    def test_prepared_source_enforces_origin_and_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stl = root / "model.stl"
            gcode = root / "model.gcode"
            stl.write_bytes(b"solid x\nendsolid x\n")
            gcode.write_text("G1 X1 Y1 E1\n", encoding="ascii")
            source = SourceArtifact.capture(stl)
            provenance = PreSliceProvenance.now(
                duration_s=1.5,
                cache_key="a" * 64,
                adapter_version=1,
            )
            prepared = PreparedAnalysisSource.capture(
                source_artifact=source,
                analysis_gcode_path=gcode,
                gcode_origin=GCodeOrigin.GENERATED_PRESLICE,
                effective_profile_fingerprint="profile-v1",
                preslice_provenance=provenance,
            )
            self.assertTrue(prepared.matches_analysis_gcode())
            with self.assertRaisesRegex(ValueError, "Provenienz"):
                PreparedAnalysisSource.capture(
                    source_artifact=source,
                    analysis_gcode_path=gcode,
                    gcode_origin=GCodeOrigin.GENERATED_PRESLICE,
                )

    def test_direct_gcode_keeps_original_and_analysis_source_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            gcode = Path(directory) / "print.gcode"
            gcode.write_text("G1 X1 Y1 E1\n", encoding="ascii")
            source = SourceArtifact.capture(gcode)
            prepared = PreparedAnalysisSource.capture(
                source_artifact=source,
                analysis_gcode_path=gcode,
                gcode_origin=GCodeOrigin.USER_SUPPLIED,
            )
            self.assertEqual(prepared.gcode_sha256, source.original_sha256)
            self.assertEqual(prepared.analysis_gcode_path, source.original_path)


class WorkflowStageTests(unittest.TestCase):
    def test_required_neutral_states_and_legacy_aliases_exist(self) -> None:
        expected = {
            "WAITING_FOR_SOURCE",
            "VALIDATING_SOURCE",
            "ANALYZING_GCODE",
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
        self.assertIs(
            WorkflowStage.WAITING_FOR_GCODE,
            WorkflowStage.WAITING_FOR_SOURCE,
        )
        self.assertIs(
            WorkflowStage.SEARCHING_SLICER,
            WorkflowStage.DISCOVERING_SLICER,
        )

    def test_every_stage_allows_replacement_with_either_supported_source(self) -> None:
        replacement_stages = {
            WorkflowStage.ANALYZING_GCODE,
            WorkflowStage.VALIDATING_STL,
        }
        for current in WorkflowStage:
            allowed = _ALLOWED_TRANSITIONS[current] | {current}
            with self.subTest(current=current.value):
                self.assertTrue(replacement_stages.issubset(allowed))


if __name__ == "__main__":
    unittest.main()
