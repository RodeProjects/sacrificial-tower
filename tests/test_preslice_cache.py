from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cooling_tower.persistence import (
    PRESLICE_CACHE_SCHEMA_VERSION,
    PreSliceCache,
)


def key(number: int) -> str:
    return hashlib.sha256(str(number).encode("ascii")).hexdigest()


class PreSliceCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.gcode = self.root / "source.gcode"
        self.gcode.write_text(
            "G90\nM83\nG1 Z0.2\nG1 X1 E0.2\n",
            encoding="ascii",
        )
        self.created = datetime.now(timezone.utc).isoformat()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def put(self, cache: PreSliceCache, number: int = 1):
        return cache.put(
            cache_key=key(number),
            gcode_path=self.gcode,
            created_at_utc=datetime.fromtimestamp(
                number,
                tz=timezone.utc,
            ).isoformat(),
            preslice_duration_s=float(number),
        )

    def test_schema_one_index_and_artifact_roundtrip(self) -> None:
        cache = PreSliceCache(self.root / "cache")
        stored = self.put(cache)
        self.assertIsNotNone(stored)
        restored = cache.get(key(1))
        self.assertEqual(restored, stored)
        document = json.loads(cache.index_path.read_text(encoding="utf-8"))
        self.assertEqual(
            document["preslice_cache_schema_version"],
            PRESLICE_CACHE_SCHEMA_VERSION,
        )
        self.assertEqual(set(document["entries"]), {key(1)})

    def test_changed_missing_or_corrupt_artifact_is_ignored(self) -> None:
        for mutation in ("changed", "missing"):
            cache = PreSliceCache(self.root / f"cache-{mutation}")
            stored = self.put(cache)
            assert stored is not None
            if mutation == "changed":
                stored.artifact_path.write_text("changed", encoding="ascii")
            else:
                stored.artifact_path.unlink()
            with self.subTest(mutation=mutation):
                self.assertIsNone(cache.get(key(1)))

    def test_corrupt_future_and_path_traversal_indexes_are_not_overwritten(self) -> None:
        payloads = (
            b"not json",
            json.dumps(
                {
                    "preslice_cache_schema_version": 999,
                    "entries": {},
                }
            ).encode("utf-8"),
            json.dumps(
                {
                    "preslice_cache_schema_version": 1,
                    "entries": {
                        key(1): {
                            "artifact_name": "../escape.gcode",
                            "gcode_sha256": key(2),
                            "gcode_size_bytes": 1,
                            "created_at_utc": self.created,
                            "preslice_duration_s": 1.0,
                        }
                    },
                }
            ).encode("utf-8"),
        )
        for index, payload in enumerate(payloads):
            cache = PreSliceCache(self.root / f"blocked-{index}")
            cache.root.mkdir(parents=True)
            cache.index_path.write_bytes(payload)
            before = cache.index_path.read_bytes()
            with self.subTest(index=index):
                self.assertIsNone(cache.get(key(1)))
                self.assertIsNone(self.put(cache))
                self.assertEqual(cache.index_path.read_bytes(), before)

    def test_retention_removes_only_old_app_owned_artifacts(self) -> None:
        cache = PreSliceCache(self.root / "limited", maximum_entries=2)
        entries = []
        for number in range(1, 4):
            entry = self.put(cache, number)
            assert entry is not None
            entries.append(entry)
        self.assertIsNone(cache.get(key(1)))
        self.assertFalse(entries[0].artifact_path.exists())
        self.assertIsNotNone(cache.get(key(2)))
        self.assertIsNotNone(cache.get(key(3)))

    def test_unsafe_cache_location_is_rejected_without_creating_it(self) -> None:
        forbidden = self.root / "slicer"
        cache = PreSliceCache(forbidden / "cache")
        with self.assertRaisesRegex(ValueError, "Slicer-Verzeichnis"):
            cache.assert_safe_location((forbidden,))
        self.assertFalse(cache.root.exists())

    def test_failed_atomic_artifact_or_index_write_leaves_no_cache_entry(self) -> None:
        cache = PreSliceCache(self.root / "atomic-artifact")
        with patch(
            "cooling_tower.persistence.preslice_cache.os.replace",
            side_effect=OSError("controlled replace failure"),
        ), self.assertRaises(OSError):
            self.put(cache)
        self.assertFalse(cache.index_path.exists())
        self.assertEqual(
            tuple(cache.artifact_root.glob("*"))
            if cache.artifact_root.exists()
            else (),
            (),
        )

        cache = PreSliceCache(self.root / "atomic-index")
        with patch.object(
            cache._store,
            "save",
            side_effect=OSError("controlled index failure"),
        ):
            self.assertIsNone(self.put(cache))
        self.assertFalse(cache.index_path.exists())
        self.assertEqual(
            tuple(cache.artifact_root.glob("*.gcode"))
            if cache.artifact_root.exists()
            else (),
            (),
        )


if __name__ == "__main__":
    unittest.main()
