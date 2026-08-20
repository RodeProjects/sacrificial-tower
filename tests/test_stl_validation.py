from __future__ import annotations

from dataclasses import replace
import hashlib
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cooling_tower.services import (
    StlFormat,
    StlIssueCode,
    StlValidationCancelled,
    StlValidationLimits,
    StlValidationService,
)
from cooling_tower.models import SourceArtifact, SourceChangedError


TETRAHEDRON = np.asarray(
    [
        ((0, 0, 0), (0, 1, 0), (1, 0, 0)),
        ((0, 0, 0), (1, 0, 0), (0, 0, 1)),
        ((0, 0, 0), (0, 0, 1), (0, 1, 0)),
        ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
    ],
    dtype=np.float32,
)


def write_binary_stl(path: Path, triangles: np.ndarray) -> None:
    values = np.asarray(triangles, dtype=np.float32)
    with path.open("wb") as handle:
        handle.write(b"strict-stl-test".ljust(80, b"\0"))
        handle.write(struct.pack("<I", len(values)))
        for triangle in values:
            normal = np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0])
            length = float(np.linalg.norm(normal))
            if length:
                normal /= length
            handle.write(struct.pack("<3f", *normal))
            handle.write(struct.pack("<9f", *triangle.reshape(-1)))
            handle.write(struct.pack("<H", 0))


def write_ascii_stl(path: Path, triangles: np.ndarray) -> None:
    rows = ["solid strict-test"]
    for triangle in np.asarray(triangles):
        rows.extend(("facet normal 0 0 0", "outer loop"))
        rows.extend(
            f"vertex {vertex[0]} {vertex[1]} {vertex[2]}"
            for vertex in triangle
        )
        rows.extend(("endloop", "endfacet"))
    rows.append("endsolid strict-test")
    path.write_text("\n".join(rows) + "\n", encoding="ascii")


class StlValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.service = StlValidationService()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def validate_binary(self, triangles: np.ndarray):
        path = self.root / "model.stl"
        write_binary_stl(path, triangles)
        return self.service.validate(path)

    def assert_issue(self, result, code: StlIssueCode) -> None:
        self.assertIn(code, {issue.code for issue in result.issues})

    def test_accepts_closed_binary_and_ascii_tetrahedron(self) -> None:
        binary = self.root / "binary.stl"
        ascii_path = self.root / "ascii.stl"
        write_binary_stl(binary, TETRAHEDRON)
        write_ascii_stl(ascii_path, TETRAHEDRON)
        binary_result = self.service.validate(binary)
        ascii_result = self.service.validate(ascii_path)
        self.assertTrue(binary_result.valid)
        self.assertTrue(ascii_result.valid)
        self.assertIs(binary_result.format, StlFormat.BINARY)
        self.assertIs(ascii_result.format, StlFormat.ASCII)
        self.assertEqual(binary_result.vertex_count, 4)
        self.assertEqual(binary_result.component_count, 1)
        self.assertAlmostEqual(binary_result.component_volumes_mm3[0], 1 / 6)

    def test_accepts_multiple_separate_closed_components(self) -> None:
        shifted = TETRAHEDRON + np.asarray((4, 0, 0), dtype=np.float32)
        result = self.validate_binary(np.concatenate((TETRAHEDRON, shifted)))
        self.assertTrue(result.valid)
        self.assertEqual(result.component_count, 2)
        self.assertEqual(len(result.component_volumes_mm3), 2)

    def test_open_model_reports_boundary_edges(self) -> None:
        result = self.validate_binary(TETRAHEDRON[:-1])
        self.assertFalse(result.valid)
        self.assertEqual(result.boundary_edge_count, 3)
        self.assert_issue(result, StlIssueCode.BOUNDARY_EDGE)
        self.assertIn(
            "non-manifold (nicht vollständig geschlossen)",
            result.technical_summary,
        )

    def test_non_manifold_edge_is_blocked(self) -> None:
        extra = np.asarray([((0, 0, 0), (1, 0, 0), (0, -1, 0))], dtype=np.float32)
        result = self.validate_binary(np.concatenate((TETRAHEDRON, extra)))
        self.assertFalse(result.valid)
        self.assertGreater(result.non_manifold_edge_count, 0)

    def test_rejected_result_can_be_explicitly_user_confirmed(self) -> None:
        triangles = np.concatenate((TETRAHEDRON, TETRAHEDRON[:1]), axis=0)
        result = self.validate_binary(triangles)

        self.assertFalse(result.valid)
        self.assertFalse(result.accepted)
        confirmed = replace(result, user_confirmed=True)

        self.assertFalse(confirmed.valid)
        self.assertTrue(confirmed.user_confirmed)
        self.assertTrue(confirmed.accepted)
        self.assertIn("Akzeptanz: user-bestätigt", confirmed.technical_summary)
        self.assert_issue(result, StlIssueCode.NON_MANIFOLD_EDGE)

    def test_inconsistent_winding_is_blocked(self) -> None:
        triangles = TETRAHEDRON.copy()
        triangles[0] = triangles[0, [0, 2, 1]]
        result = self.validate_binary(triangles)
        self.assertFalse(result.valid)
        self.assertGreater(result.inconsistent_edge_count, 0)
        self.assert_issue(result, StlIssueCode.INCONSISTENT_WINDING)

    def test_degenerate_and_duplicate_faces_are_blocked(self) -> None:
        degenerate = np.asarray([((0, 0, 0), (0, 0, 0), (1, 0, 0))], dtype=np.float32)
        result = self.validate_binary(
            np.concatenate((TETRAHEDRON, TETRAHEDRON[:1], degenerate))
        )
        self.assertFalse(result.valid)
        self.assertGreater(result.degenerate_face_count, 0)
        self.assertGreater(result.duplicate_face_count, 0)
        self.assert_issue(result, StlIssueCode.DEGENERATE_FACE)
        self.assert_issue(result, StlIssueCode.DUPLICATE_FACE)

    def test_non_finite_coordinate_is_blocked(self) -> None:
        triangles = TETRAHEDRON.copy()
        triangles[0, 0, 0] = np.nan
        result = self.validate_binary(triangles)
        self.assertFalse(result.valid)
        self.assert_issue(result, StlIssueCode.INVALID_VALUE)

    def test_negative_volume_from_inward_winding_is_blocked(self) -> None:
        triangles = TETRAHEDRON[:, [0, 2, 1]]
        result = self.validate_binary(triangles)
        self.assertFalse(result.valid)
        self.assertFalse(result.positive_volume)
        self.assert_issue(result, StlIssueCode.NON_POSITIVE_VOLUME)

    def test_intersecting_separate_components_are_blocked(self) -> None:
        shifted = TETRAHEDRON + np.asarray((0.25, 0.25, 0.25), dtype=np.float32)
        result = self.validate_binary(np.concatenate((TETRAHEDRON, shifted)))
        self.assertFalse(result.valid)
        self.assertGreater(result.self_intersection_count, 0)
        self.assert_issue(result, StlIssueCode.SELF_INTERSECTION)

    def test_even_shallow_intersection_between_components_is_blocked(self) -> None:
        shifted = TETRAHEDRON + np.asarray((0.9999, 0, 0), dtype=np.float32)
        result = self.validate_binary(np.concatenate((TETRAHEDRON, shifted)))
        self.assertFalse(result.valid)
        self.assertEqual(result.component_count, 2)
        self.assertGreater(result.self_intersection_count, 0)
        self.assertTrue(result.blocking_issues)
        self.assert_issue(result, StlIssueCode.SELF_INTERSECTION)

    def test_partially_overlapping_coplanar_component_faces_are_blocked(self) -> None:
        reflected = TETRAHEDRON.copy()
        reflected[:, :, 2] *= -1
        reflected = reflected[:, [0, 2, 1]]
        reflected += np.asarray((0.1, 0.1, 0), dtype=np.float32)
        result = self.validate_binary(
            np.concatenate((TETRAHEDRON, reflected))
        )
        self.assertFalse(result.valid)
        self.assertEqual(result.component_count, 2)
        self.assertGreater(result.self_intersection_count, 0)
        self.assert_issue(result, StlIssueCode.SELF_INTERSECTION)

    def test_topologically_manifold_self_crossing_component_is_blocked(self) -> None:
        vertices = np.asarray(
            (
                (3, 0, 0),
                (-1, -1, 1),
                (-1, 1, -1),
                (-1, 1, 1),
                (1, -1, -1),
                (1, -1, 1),
                (1, 1, -1),
                (1, 1, 1),
            ),
            dtype=np.float32,
        )
        faces = np.asarray(
            (
                (1, 3, 0), (4, 1, 0), (0, 3, 2), (2, 4, 0),
                (1, 7, 3), (5, 1, 4), (5, 7, 1), (3, 7, 2),
                (6, 4, 2), (2, 7, 6), (6, 5, 4), (7, 5, 6),
            ),
            dtype=np.int64,
        )
        result = self.validate_binary(vertices[faces])
        self.assertFalse(result.valid)
        self.assertEqual(result.component_count, 1)
        self.assertEqual(result.boundary_edge_count, 0)
        self.assertEqual(result.non_manifold_edge_count, 0)
        self.assertEqual(result.inconsistent_edge_count, 0)
        self.assertGreater(result.self_intersection_count, 0)
        self.assert_issue(result, StlIssueCode.SELF_INTERSECTION)

    def test_shallow_local_self_crossing_is_warning_but_safety_cap_blocks(self) -> None:
        vertices = np.asarray(
            (
                (1.0001, -1, -1),
                (-1, -1, 1),
                (-1, 1, -1),
                (-1, 1, 1),
                (1, -1, -1),
                (1, -1, 1),
                (1, 1, -1),
                (1, 1, 1),
            ),
            dtype=np.float32,
        )
        faces = np.asarray(
            (
                (1, 3, 0), (4, 1, 0), (0, 3, 2), (2, 4, 0),
                (1, 7, 3), (5, 1, 4), (5, 7, 1), (3, 7, 2),
                (6, 4, 2), (2, 7, 6), (6, 5, 4), (7, 5, 6),
            ),
            dtype=np.int64,
        )
        triangles = vertices[faces]
        accepted = self.validate_binary(triangles)
        self.assertTrue(accepted.valid, accepted.technical_summary)
        self.assertGreater(accepted.self_intersection_count, 0)
        self.assertFalse(accepted.warning_issues[0].blocking)

        path = self.root / "strict-cap.stl"
        write_binary_stl(path, triangles)
        capped = StlValidationService(
            StlValidationLimits(maximum_tolerable_self_intersection_pairs=1)
        ).validate(path)
        self.assertFalse(capped.valid)
        self.assert_issue(capped, StlIssueCode.SELF_INTERSECTION)

    def test_declared_triangle_limit_and_truncated_binary_are_blocked(self) -> None:
        path = self.root / "limited.stl"
        write_binary_stl(path, TETRAHEDRON)
        limited = StlValidationService(
            StlValidationLimits(maximum_triangle_count=3)
        ).validate(path)
        self.assert_issue(limited, StlIssueCode.RESOURCE_LIMIT)
        truncated = self.root / "truncated.stl"
        truncated.write_bytes(path.read_bytes()[:-1])
        malformed = self.service.validate(truncated)
        self.assert_issue(malformed, StlIssueCode.INVALID_FORMAT)

    def test_file_size_limit_is_checked_before_geometry_loading(self) -> None:
        path = self.root / "size-limited.stl"
        write_binary_stl(path, TETRAHEDRON)
        limits = StlValidationLimits(maximum_file_size_bytes=100)
        result = StlValidationService(limits).validate(path)
        self.assertFalse(result.valid)
        self.assert_issue(result, StlIssueCode.RESOURCE_LIMIT)

    def test_incomplete_intersection_scan_fails_closed(self) -> None:
        opposite_corner = (1.0 - TETRAHEDRON)[:, [0, 2, 1]]
        path = self.root / "candidate-limited.stl"
        write_binary_stl(path, np.concatenate((TETRAHEDRON, opposite_corner)))
        result = StlValidationService(
            StlValidationLimits(maximum_intersection_candidates=1)
        ).validate(path)
        self.assertFalse(result.valid)
        self.assertFalse(result.intersection_check_complete)
        self.assert_issue(result, StlIssueCode.RESOURCE_LIMIT)

    def test_external_change_during_validation_is_never_accepted(self) -> None:
        path = self.root / "changed.stl"
        write_binary_stl(path, TETRAHEDRON)
        with patch.object(
            SourceArtifact,
            "matches_current_file",
            return_value=False,
        ):
            with self.assertRaises(SourceChangedError):
                self.service.validate(path)

    def test_cancellation_is_observed(self) -> None:
        path = self.root / "cancelled.stl"
        write_binary_stl(path, TETRAHEDRON)
        with self.assertRaises(StlValidationCancelled):
            self.service.validate(path, cancellation_callback=lambda: True)

    def test_validation_never_changes_the_source(self) -> None:
        path = self.root / "unchanged.stl"
        write_binary_stl(path, TETRAHEDRON)
        before = (path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest())
        self.service.validate(path)
        after = (path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(after, before)


class SuppliedStlFixtureTests(unittest.TestCase):
    FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "stl"

    def test_supplied_manifold_fixture_is_accepted_with_bounded_warning(self) -> None:
        path = self.FIXTURE_ROOT / "test_model_manifold.stl"
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        result = StlValidationService().validate(path)
        self.assertTrue(result.valid, result.technical_summary)
        self.assertEqual(result.face_count, 88_924)
        self.assertEqual(result.vertex_count, 44_343)
        self.assertEqual(result.component_count, 1)
        self.assertEqual(result.boundary_edge_count, 0)
        self.assertEqual(result.non_manifold_edge_count, 0)
        self.assertGreater(result.self_intersection_count, 0)
        self.assertEqual(len(result.warning_issues), 1)
        self.assertEqual(result.blocking_issues, ())
        self.assertIn(
            StlIssueCode.SELF_INTERSECTION,
            {issue.code for issue in result.issues},
        )
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_supplied_non_manifold_fixture_is_rejected_with_stable_findings(self) -> None:
        path = self.FIXTURE_ROOT / "test_model_non_manifold.stl"
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        result = StlValidationService().validate(path)
        self.assertFalse(result.valid)
        self.assertEqual(result.face_count, 88_496)
        self.assertEqual(result.boundary_edge_count, 161)
        self.assertEqual(result.non_manifold_edge_count, 118)
        self.assertEqual(result.degenerate_face_count, 3)
        self.assertEqual(result.duplicate_face_count, 29)
        self.assertEqual(result.inconsistent_edge_count, 156)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)


if __name__ == "__main__":
    unittest.main()
