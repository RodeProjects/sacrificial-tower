from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cooling_tower.config import SETTINGS_SCHEMA_VERSION
from cooling_tower.legacy_method_ids import LEGACY_POSTPROCESSOR_ID
from cooling_tower.export_paths import default_export_roots, EXPORT_FOLDER_NAMES
from cooling_tower.gui.settings_store import UserSettingsStore
from cooling_tower.models import GenerationSettings
from cooling_tower.persistence import VersionedDocumentError, VersionedDocumentWriteBlockedError
from cooling_tower.settings_compatibility import SETTING_COMPATIBILITY_CATALOG, merge_compatible_setting_changes


class ExportPathsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.path = self.root / "settings.json"
        self.defaults = Path(__file__).resolve().parents[1] / "config/default_settings.json"

    def tearDown(self):
        self.temporary.cleanup()

    def store(self):
        return UserSettingsStore(self.path, self.defaults)

    def save(self, store, roots):
        return store.save(GenerationSettings(), output_root="output", export_roots=roots,
            window_width=900, window_height=700)

    def test_direct_and_multistep_migrations_preserve_existing_outputs_and_backup(self):
        for schema in (0, 22, 23):
            with self.subTest(schema=schema):
                old_root = self.root / f"old-{schema}"
                old_root.mkdir()
                old_export = old_root / "old.gcode"
                old_export.write_bytes(b"original")
                self.path.write_text(json.dumps({"settings_schema_version": schema,
                    "generation": {}, "output_root": str(old_root)}), encoding="utf-8")
                before = self.path.read_bytes()
                store = self.store()
                _, state = store.load()
                self.assertEqual(state["settings_schema_version"], SETTINGS_SCHEMA_VERSION)
                self.assertEqual(state["export_roots"], default_export_roots(old_root))
                self.assertEqual(state["output_root"], default_export_roots(old_root)["automatic"])
                self.assertEqual(store.last_migration_backup.read_bytes(), before)
                self.assertEqual(old_export.read_bytes(), b"original")
                self.assertFalse((old_root / EXPORT_FOLDER_NAMES["automatic"]).exists())

    def test_individual_paths_round_trip_and_invalid_values_are_discarded(self):
        roots = default_export_roots(self.root / "exports")
        roots["manual"] = str(self.root / "eigener manueller Ordner")
        self.save(self.store(), roots)
        _, state = self.store().load()
        self.assertEqual(state["export_roots"], roots)
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        payload["export_roots"] = {"automatic": 3, "manual": "x\x00y", "postprocessor": "   ", "unknown": "x"}
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(self.store().load()[1]["export_roots"], {})

    def test_schema_24_updates_standard_spelling_with_backup_and_keeps_custom_paths(self):
        for standard in (True, False):
            with self.subTest(standard=standard):
                base = self.root/"exports"
                roots = default_export_roots(base)
                old = base/LEGACY_POSTPROCESSOR_ID if standard else self.root/"custom"/LEGACY_POSTPROCESSOR_ID
                roots[LEGACY_POSTPROCESSOR_ID] = str(old)
                roots.pop("postprocessor")
                payload = {"settings_schema_version": 24, "generation": {},
                    "output_root": roots["automatic"], "export_roots": roots}
                self.path.write_text(json.dumps(payload), encoding="utf-8")
                original = self.path.read_bytes()
                store = self.store()
                _, state = store.load()
                self.assertEqual(state["settings_schema_version"], SETTINGS_SCHEMA_VERSION)
                self.assertEqual(state["export_roots"]["postprocessor"], default_export_roots(base)["postprocessor"] if standard else str(old))
                self.assertEqual(store.last_migration_backup.read_bytes(), original)
                self.assertFalse(old.exists())

    def test_failed_schema_24_migration_write_preserves_original(self):
        roots = {**default_export_roots(self.root), LEGACY_POSTPROCESSOR_ID: str(self.root/LEGACY_POSTPROCESSOR_ID)}
        roots.pop("postprocessor")
        self.path.write_text(json.dumps({"settings_schema_version": 24, "generation": {},
            "output_root": roots["automatic"], "export_roots": roots}), encoding="utf-8")
        original = self.path.read_bytes()
        with patch("cooling_tower.persistence.versioned_json.os.replace", side_effect=OSError("locked")):
            self.store().load()
        self.assertEqual(self.path.read_bytes(), original)

    def test_failed_atomic_write_preserves_original(self):
        store = self.store()
        roots = default_export_roots(self.root)
        self.save(store, roots)
        original = self.path.read_bytes()
        with patch("cooling_tower.persistence.versioned_json.os.replace", side_effect=OSError("locked")):
            with self.assertRaises(OSError):
                self.save(store, {**roots, "manual": "changed"})
        self.assertEqual(self.path.read_bytes(), original)

    def test_external_changes_and_corrupt_files_are_preserved_until_explicit_recovery(self):
        roots = default_export_roots(self.root)
        store = self.store()
        self.save(store, roots)
        self.path.write_bytes(b"changed externally")
        with self.assertRaises(VersionedDocumentError):
            self.save(store, roots)
        self.assertEqual(self.path.read_bytes(), b"changed externally")
        damaged = self.store()
        damaged.load()
        with self.assertRaises(VersionedDocumentWriteBlockedError):
            self.save(damaged, roots)
        damaged.recover(GenerationSettings(), output_root="output", export_roots=roots,
            window_width=900, window_height=700)
        self.assertEqual(self.store().load()[1]["export_roots"], roots)
        self.assertTrue(any(path.read_bytes() == b"changed externally" for path in self.root.glob("*.backup*")))

    def test_future_schema_keeps_original_and_records_compatible_path_changes_separately(self):
        roots = default_export_roots(self.root)
        self.path.write_text(json.dumps({"settings_schema_version": SETTINGS_SCHEMA_VERSION + 1,
            "generation": {}, "output_root": "output", "export_roots": roots,
            "setting_compatibility": SETTING_COMPATIBILITY_CATALOG}), encoding="utf-8")
        original = self.path.read_bytes()
        store = self.store()
        self.assertEqual(store.load()[1]["export_roots"], roots)
        journal = self.save(store, {**roots, "manual": "changed"})
        self.assertEqual(self.path.read_bytes(), original)
        change = json.loads(journal.read_text(encoding="utf-8"))["changes"]["export_roots.manual"]
        self.assertEqual(change["value"], "changed")

    def test_downgrade_rejects_types_units_and_invalid_paths_per_method(self):
        roots = default_export_roots(self.root)
        for value, token in ((4, "method-export-directory-path-v1"),
                (True, "method-export-directory-path-v1"), ("", "method-export-directory-path-v1"),
                ("x\x00y", "method-export-directory-path-v1"), ("new", "duration-seconds-v1")):
            with self.subTest(value=value, token=token):
                result = merge_compatible_setting_changes({"generation": {}, "export_roots": roots}, {
                    "export_roots.manual": {"token": token, "value": value},
                    "export_roots.postprocessor": {"token": "method-export-directory-path-v1", "value": "safe"}})
                self.assertIn("export_roots.manual", result.rejected_ids)
                self.assertEqual(result.payload["export_roots"]["manual"], roots["manual"])
                self.assertEqual(result.payload["export_roots"]["postprocessor"], "safe")

    def test_old_shared_directory_token_cannot_replace_method_destinations(self):
        roots = default_export_roots(self.root)
        merged = merge_compatible_setting_changes({"output_root": roots["automatic"], "export_roots": roots}, {
            "output_root": {"token": "output-directory-path-v1", "value": "different-shared-folder"}})
        self.assertEqual(merged.payload["export_roots"], roots)
        self.assertEqual(merged.payload["output_root"], roots["automatic"])
        self.assertIn("output_root", merged.rejected_ids)


if __name__ == "__main__":
    unittest.main()
