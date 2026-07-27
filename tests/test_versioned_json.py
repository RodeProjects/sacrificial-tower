from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cooling_tower.persistence import (
    ConcurrentDocumentChangeError,
    FutureSchemaVersionError,
    InvalidVersionedDocumentError,
    MissingMigrationError,
    VersionedDocumentWriteBlockedError,
    VersionedJsonStore,
    atomic_write_json,
)


class VersionedJsonStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.path = self.root / "profile.json"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def migrations():
        def zero_to_one(payload: dict[str, object]) -> dict[str, object]:
            payload["history"] = ["0→1"]
            return payload

        def one_to_two(payload: dict[str, object]) -> dict[str, object]:
            payload["history"] = [*payload.get("history", []), "1→2"]
            payload["new_name"] = payload.pop("old_name", None)
            return payload

        def two_to_three(payload: dict[str, object]) -> dict[str, object]:
            payload["history"] = [*payload.get("history", []), "2→3"]
            return payload

        return {0: zero_to_one, 1: one_to_two, 2: two_to_three}

    def store(self, **overrides) -> VersionedJsonStore:
        arguments = {
            "schema_key": "profile_schema_version",
            "current_version": 3,
            "migrations": self.migrations(),
            "document_name": "Das Testprofil",
        }
        arguments.update(overrides)
        return VersionedJsonStore(self.path, **arguments)

    def test_applies_every_migration_and_preserves_original_backup(self) -> None:
        original = '{"old_name": "value"}\n'
        self.path.write_text(original, encoding="utf-8")
        original_bytes = self.path.read_bytes()

        result = self.store().load()

        self.assertTrue(result.migrated)
        self.assertEqual(result.source_version, 0)
        self.assertEqual(result.target_version, 3)
        self.assertEqual(result.payload["history"], ["0→1", "1→2", "2→3"])
        self.assertEqual(result.payload["new_name"], "value")
        self.assertEqual(result.payload["profile_schema_version"], 3)
        self.assertIsNotNone(result.backup_path)
        self.assertEqual(result.backup_path.read_bytes(), original_bytes)
        self.assertEqual(
            json.loads(self.path.read_text(encoding="utf-8")),
            result.payload,
        )

    def test_missing_intermediate_migration_blocks_all_writes(self) -> None:
        original = b'{"profile_schema_version": 1, "value": 7}\n'
        self.path.write_bytes(original)
        store = self.store(migrations={1: self.migrations()[1]})

        with self.assertRaises(MissingMigrationError):
            store.load()
        with self.assertRaises(VersionedDocumentWriteBlockedError):
            store.save({"value": 8})

        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.root.glob("*.backup*")), [])

    def test_future_schema_is_never_downgraded_or_overwritten(self) -> None:
        original = b'{"profile_schema_version": 99, "value": "future"}\n'
        self.path.write_bytes(original)
        store = self.store()

        with self.assertRaises(FutureSchemaVersionError):
            store.load()
        with self.assertRaises(VersionedDocumentWriteBlockedError):
            store.save({"value": "old application"})

        self.assertEqual(self.path.read_bytes(), original)

    def test_invalid_json_is_preserved_until_explicit_recovery(self) -> None:
        original = b'{"broken": '
        self.path.write_bytes(original)
        store = self.store()

        with self.assertRaises(InvalidVersionedDocumentError):
            store.load()
        with self.assertRaises(VersionedDocumentWriteBlockedError):
            store.save({"value": "unsafe"})

        recovered = store.replace_with_recovery({"value": "safe"})
        self.assertEqual(recovered, self.path.resolve())
        backups = list(self.root.glob("profile.json.schema-recovery.backup*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)
        self.assertEqual(
            json.loads(self.path.read_text(encoding="utf-8")),
            {"profile_schema_version": 3, "value": "safe"},
        )

    def test_existing_document_must_be_loaded_before_regular_save(self) -> None:
        original = b'{"profile_schema_version": 3, "value": 1}\n'
        self.path.write_bytes(original)

        with self.assertRaises(VersionedDocumentWriteBlockedError):
            self.store().save({"value": 2})

        self.assertEqual(self.path.read_bytes(), original)

    def test_normalization_of_current_schema_is_backed_up(self) -> None:
        original = b'{"profile_schema_version": 3, "obsolete": true}\n'
        self.path.write_bytes(original)
        store = self.store(
            normalizer=lambda payload: {
                key: value
                for key, value in payload.items()
                if key != "obsolete"
            }
        )

        result = store.load()

        self.assertFalse(result.migrated)
        self.assertTrue(result.normalized)
        self.assertEqual(result.backup_path.read_bytes(), original)
        self.assertNotIn("obsolete", result.payload)

    def test_concurrent_change_after_load_is_not_overwritten(self) -> None:
        self.path.write_text(
            json.dumps({"profile_schema_version": 3, "value": "loaded"}),
            encoding="utf-8",
        )
        store = self.store()
        store.load()
        concurrent = b'{"profile_schema_version": 3, "value": "other process"}\n'
        self.path.write_bytes(concurrent)

        with self.assertRaises(ConcurrentDocumentChangeError):
            store.save({"value": "stale process"})

        self.assertEqual(self.path.read_bytes(), concurrent)
        self.assertTrue(store.write_blocked)

    def test_concurrent_deletion_after_load_is_not_silently_recreated(self) -> None:
        self.path.write_text(
            json.dumps({"profile_schema_version": 3, "value": "loaded"}),
            encoding="utf-8",
        )
        store = self.store()
        store.load()
        self.path.unlink()

        with self.assertRaises(ConcurrentDocumentChangeError):
            store.save({"value": "stale process"})

        self.assertFalse(self.path.exists())
        self.assertTrue(store.write_blocked)

    def test_atomic_write_leaves_original_on_replace_failure(self) -> None:
        original = b'{"profile_schema_version": 3, "value": "original"}\n'
        self.path.write_bytes(original)

        with patch(
            "cooling_tower.persistence.versioned_json.os.replace",
            side_effect=OSError("simulierter Fehler"),
        ):
            with self.assertRaises(OSError):
                atomic_write_json(self.path, {"value": "replacement"})

        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.root.glob(".*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
