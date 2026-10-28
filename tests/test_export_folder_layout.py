"""Default folder migration, custom targets and history across renamed roots."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from cooling_tower.config import SETTINGS_SCHEMA_VERSION
from cooling_tower.export_paths import default_export_roots, legacy_export_roots
from cooling_tower.gui.export_history import resolve_latest_export_directory
from cooling_tower.gui.settings_store import UserSettingsStore
from cooling_tower.legacy_method_ids import LEGACY_POSTPROCESSOR_ID
import test_export_history as history_fixture


class ExportFolderLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.path=self.root/"settings.json"
        self.defaults=Path(__file__).resolve().parents[1]/"config/default_settings.json"

    def tearDown(self):
        self.temp.cleanup()

    def store(self):
        return UserSettingsStore(self.path,self.defaults,default_output_base=self.root)

    def test_default_folder_names_match_each_mode(self):
        self.assertEqual(default_export_roots(self.root),{
            "automatic":str(self.root/"exports_automatic_mode"),
            "manual":str(self.root/"exports_manual_mode"),
            "postprocessor":str(self.root/"exports_postprocessor")})

    def test_recovery_defaults_use_the_same_automatic_destination(self):
        store = self.store()
        payload = store._default_payload(store.load_defaults())
        self.assertEqual(payload["output_root"], payload["export_roots"]["automatic"])
        self.assertEqual(
            payload["export_roots"], default_export_roots(store.load_default_output_root()),
        )

    def test_schema_26_migrates_shared_layout_with_backup_and_no_file_changes(self):
        base=self.root/"output"
        roots={mode:str(base/mode) for mode in ("automatic","manual","postprocessor")}
        old=base/"automatic"/"old.gcode";old.parent.mkdir(parents=True);old.write_bytes(b"original")
        self.path.write_text(json.dumps({"settings_schema_version":26,"generation":{},
            "export_roots":roots,"output_root":roots["automatic"]}),encoding="utf-8")
        original=self.path.read_bytes();store=self.store();_,state=store.load()
        self.assertEqual(state["settings_schema_version"],SETTINGS_SCHEMA_VERSION)
        self.assertEqual(state["export_roots"],default_export_roots(base))
        self.assertEqual(state["output_root"],state["export_roots"]["automatic"])
        self.assertEqual(store.last_migration_backup.read_bytes(),original)
        self.assertEqual(old.read_bytes(),b"original")

    def test_known_default_migrates_independently_of_custom_other_modes(self):
        roots={"automatic":str(self.root/"output"/"automatic"),
            "manual":str(self.root/"own"/"manual"),"postprocessor":str(self.root/"different-custom")}
        self.path.write_text(json.dumps({"settings_schema_version":26,"generation":{},
            "export_roots":roots}),encoding="utf-8")
        _,state=self.store().load()
        self.assertEqual(state["export_roots"],{**roots,"automatic":str(self.root/"output"/"exports_automatic_mode")})

    def test_custom_paths_survive_and_failed_migration_does_not_overwrite_original(self):
        roots={"automatic":str(self.root/"custom"/"automatic"),
            "manual":str(self.root/"other"/"manual"),"postprocessor":str(self.root/"third")}
        payload={"settings_schema_version":26,"generation":{},"export_roots":roots}
        self.path.write_text(json.dumps(payload),encoding="utf-8")
        original=self.path.read_bytes()
        with patch("cooling_tower.persistence.versioned_json.os.replace",side_effect=OSError("locked")):
            self.store().load()
        self.assertEqual(self.path.read_bytes(),original)
        _,state=self.store().load()
        self.assertEqual(state["export_roots"],roots)

    def test_legacy_history_remains_visible_before_and_after_physical_rename(self):
        for method in ("automatic","manual","postprocessor"):
            for name in ((method,LEGACY_POSTPROCESSOR_ID) if method=="postprocessor" else (method,)):
                with self.subTest(method=method,name=name):
                    base=self.root/(method+"-"+name);base.mkdir()
                    old_root=base/name;old_root.mkdir()
                    fixture=history_fixture.ExportHistoryTests();fixture.root=old_root
                    old=fixture._write_export("existing","2026-10-01T12:00:00+02:00")
                    new_root=Path(default_export_roots(base)[method])
                    self.assertEqual(resolve_latest_export_directory(new_root,
                        additional_roots=legacy_export_roots(new_root,method)).directory,old)
                    before=(old/"export_report.json").read_bytes()
                    self.assertEqual(old_root.resolve().parent,base.resolve())
                    self.assertEqual(new_root.resolve().parent,base.resolve())
                    old_root.rename(new_root)
                    current=resolve_latest_export_directory(new_root,
                        additional_roots=legacy_export_roots(new_root,method)).directory
                    self.assertEqual(current,new_root/"existing")
                    self.assertEqual((current/"export_report.json").read_bytes(),before)
                    self.assertTrue((current/"tower.stl").is_file())
        self.assertEqual(legacy_export_roots(self.root/"custom","manual"),())

    def test_corrupt_and_future_files_remain_protected(self):
        for data in (b"not json",json.dumps({"settings_schema_version":SETTINGS_SCHEMA_VERSION+1}).encode()):
            self.path.write_bytes(data)
            store=self.store();store.load()
            self.assertEqual(self.path.read_bytes(),data)
            if data==b"not json":
                self.assertIsNotNone(store.write_blocked_reason)


if __name__=="__main__":
    unittest.main()
