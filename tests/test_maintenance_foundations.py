from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cooling_tower.file_integrity import sha256_file
from cooling_tower.slicers.discovery import deduplicate_candidates
from cooling_tower.slicers.models import (
    SlicerCandidate,
    SlicerDiscoverySource,
)


class FileIntegrityTests(unittest.TestCase):
    def test_sha256_file_matches_standard_library_for_multiple_blocks(
        self,
    ) -> None:
        payload = (bytes(range(256)) * 8193) + b"tail"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "large.bin"
            path.write_bytes(payload)
            self.assertEqual(
                sha256_file(path),
                hashlib.sha256(payload).hexdigest(),
            )


class CandidateDeduplicationTests(unittest.TestCase):
    def test_preserves_order_and_only_merges_same_path_and_adapter(
        self,
    ) -> None:
        root = Path(os.getcwd())
        first = SlicerCandidate(
            root / "slicer.exe",
            SlicerDiscoverySource.KNOWN_PATH,
            adapter_hint="orca",
        )
        duplicate = SlicerCandidate(
            root / "." / "slicer.exe",
            SlicerDiscoverySource.MANUAL,
            adapter_hint="orca",
        )
        other_adapter = SlicerCandidate(
            root / "slicer.exe",
            SlicerDiscoverySource.KNOWN_PATH,
            adapter_hint="bambu",
        )

        self.assertEqual(
            deduplicate_candidates((first, duplicate, other_adapter)),
            (first, other_adapter),
        )


if __name__ == "__main__":
    unittest.main()
