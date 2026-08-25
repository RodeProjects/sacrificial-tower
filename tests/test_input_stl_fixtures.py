from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cooling_tower.services.stl_validation import (
    StlIssueCode,
    StlValidationService,
)


MANIFOLD_STL = PROJECT_ROOT / "input" / "Test-STL (manifold).stl"
NON_MANIFOLD_STL = PROJECT_ROOT / "input" / "Test-STL (non-manifold).stl"


class InputStlFixtureTests(unittest.TestCase):
    def test_supplied_manifold_stl_is_accepted_without_source_write(self) -> None:
        before = hashlib.sha256(MANIFOLD_STL.read_bytes()).digest()

        result = StlValidationService().validate(MANIFOLD_STL)

        self.assertTrue(result.valid, result.technical_summary)
        self.assertEqual(result.boundary_edge_count, 0)
        self.assertEqual(result.non_manifold_edge_count, 0)
        self.assertEqual(
            hashlib.sha256(MANIFOLD_STL.read_bytes()).digest(),
            before,
        )

    def test_supplied_non_manifold_stl_is_rejected_without_source_write(self) -> None:
        before = hashlib.sha256(NON_MANIFOLD_STL.read_bytes()).digest()

        result = StlValidationService().validate(NON_MANIFOLD_STL)

        issue_codes = {issue.code for issue in result.issues}
        self.assertFalse(result.valid)
        self.assertGreater(result.non_manifold_edge_count, 0)
        self.assertIn(StlIssueCode.NON_MANIFOLD_EDGE, issue_codes)
        self.assertEqual(
            hashlib.sha256(NON_MANIFOLD_STL.read_bytes()).digest(),
            before,
        )


if __name__ == "__main__":
    unittest.main()
