"""Canonical naming with validated recovery of older method identifiers."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"src"))
from cooling_tower.config import SETTINGS_SCHEMA_VERSION
from cooling_tower.export_paths import default_export_roots, normalize_export_roots
from cooling_tower.gui.generation_session import GenerationMode
from cooling_tower.gui.settings_store import UserSettingsStore
from cooling_tower.legacy_method_ids import LEGACY_POSTPROCESSOR_ID, LEGACY_POSTPROCESSOR_EXPORT_SETTING
from cooling_tower.settings_compatibility import SETTING_COMPATIBILITY_CATALOG, merge_compatible_setting_changes, project_compatible_settings


class PostprocessorNamingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root/"settings.json"
        self.defaults = Path(__file__).resolve().parents[1]/"config/default_settings.json"

    def tearDown(self):
        self.temp.cleanup()

    def old_payload(self, version=25):
        roots = default_export_roots(self.root/"exports")
        roots.pop("postprocessor")
        roots[LEGACY_POSTPROCESSOR_ID] = str(self.root/"custom-output")
        return {"settings_schema_version":version,"generation":{},"export_roots":roots,
            "output_root":roots["automatic"],"setting_compatibility":{
                LEGACY_POSTPROCESSOR_EXPORT_SETTING:"method-export-directory-path-v1"}}

    def test_direct_and_multistep_migrations_preserve_custom_path_and_original_backup(self):
        self.assertGreaterEqual(SETTINGS_SCHEMA_VERSION,26)
        for version in (24,25):
            with self.subTest(version=version):
                payload = self.old_payload(version)
                self.path.write_text(json.dumps(payload),encoding="utf-8")
                original = self.path.read_bytes()
                store = UserSettingsStore(self.path,self.defaults)
                _,state = store.load()
                self.assertEqual(state["export_roots"]["postprocessor"],str(self.root/"custom-output"))
                self.assertNotIn(LEGACY_POSTPROCESSOR_ID,state["export_roots"])
                self.assertNotIn(LEGACY_POSTPROCESSOR_EXPORT_SETTING,state["setting_compatibility"])
                self.assertEqual(store.last_migration_backup.read_bytes(),original)
                saved = json.loads(self.path.read_text())
                self.assertEqual(saved["settings_schema_version"],SETTINGS_SCHEMA_VERSION)
                self.assertEqual(saved["export_roots"],state["export_roots"])

    def test_current_key_has_priority_and_wrong_types_are_not_imported(self):
        both = {LEGACY_POSTPROCESSOR_ID:"old", "postprocessor":"current"}
        self.assertEqual(normalize_export_roots(both),{"postprocessor":"current"})
        for value in (True,12,"", "x\x00y"):
            with self.subTest(value=value):
                self.assertEqual(normalize_export_roots({LEGACY_POSTPROCESSOR_ID:value}),{})
                self.assertEqual(normalize_export_roots({**both,"postprocessor":value}),{})

    def test_failed_migration_keeps_original_bytes(self):
        self.path.write_text(json.dumps(self.old_payload()),encoding="utf-8")
        original = self.path.read_bytes()
        with patch("cooling_tower.persistence.versioned_json.os.replace",side_effect=OSError("locked")):
            UserSettingsStore(self.path,self.defaults).load()
        self.assertEqual(self.path.read_bytes(),original)

    def test_return_from_downgrade_translates_legacy_journal_and_rejects_incompatible_values(self):
        for value,token,accepted in (("changed","method-export-directory-path-v1",True),
                (True,"method-export-directory-path-v1",False),(4,"method-export-directory-path-v1",False),
                ("changed","duration-seconds-v1",False),("x\x00y","method-export-directory-path-v1",False)):
            with self.subTest(value=value,token=token):
                self.path.write_text(json.dumps(self.old_payload()),encoding="utf-8")
                original = self.path.read_bytes()
                journal_path = self.path.with_name(self.path.name+".downgrade-changes.json")
                journal_path.write_text(json.dumps({"downgrade_journal_schema_version":1,
                    "protected_sha256":hashlib.sha256(original).hexdigest(),"protected_settings_schema_version":25,
                    "next_revision":2,"status":"active","changes":{LEGACY_POSTPROCESSOR_EXPORT_SETTING:{
                        "token":token,"revision":1,"value":value}}}),encoding="utf-8")
                _,state = UserSettingsStore(self.path,self.defaults).load()
                self.assertEqual(state["export_roots"]["postprocessor"],"changed" if accepted else str(self.root/"custom-output"))
                journal = json.loads(journal_path.read_text())
                self.assertEqual(journal["status"],"applied")
                self.assertEqual(journal["accepted_ids"],["export_roots.postprocessor"] if accepted else [])

    def test_future_legacy_file_is_projected_without_overwriting_it(self):
        self.path.write_text(json.dumps(self.old_payload(SETTINGS_SCHEMA_VERSION+1)),encoding="utf-8")
        original = self.path.read_bytes()
        _,state = UserSettingsStore(self.path,self.defaults).load()
        self.assertEqual(state["export_roots"]["postprocessor"],str(self.root/"custom-output"))
        self.assertEqual(self.path.read_bytes(),original)

    def test_explicit_compatibility_alias_never_overrides_current_change(self):
        base = {"generation":{},"export_roots":{"postprocessor":"kept"}}
        merged = merge_compatible_setting_changes(base,{
            LEGACY_POSTPROCESSOR_EXPORT_SETTING:{"token":"method-export-directory-path-v1","value":"old"},
            "export_roots.postprocessor":{"token":"method-export-directory-path-v1","value":"current"}})
        self.assertEqual(merged.payload["export_roots"]["postprocessor"],"current")
        self.assertIn(LEGACY_POSTPROCESSOR_EXPORT_SETTING,merged.rejected_ids)
        incompatible = project_compatible_settings({"export_roots":{LEGACY_POSTPROCESSOR_ID:"old"},
            "setting_compatibility":{LEGACY_POSTPROCESSOR_EXPORT_SETTING:"duration-seconds-v1"}},base)
        self.assertEqual(incompatible.payload["export_roots"]["postprocessor"],"kept")

    def test_generation_mode_serializes_canonical_name_and_reads_legacy_value(self):
        self.assertEqual(GenerationMode(LEGACY_POSTPROCESSOR_ID),GenerationMode.POSTPROCESSOR)
        self.assertEqual(GenerationMode.POSTPROCESSOR.value,"postprocessor")
        self.assertEqual(set(mode.value for mode in GenerationMode),{"automatic","manual","postprocessor"})
        self.assertEqual(set(default_export_roots(self.root)),{"automatic","manual","postprocessor"})


if __name__ == "__main__":
    unittest.main()
