import sys
import json
import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))

from cooling_tower.manual.geometry import ManualSettings
from cooling_tower.manual.settings_store import ManualSettingsStore
from cooling_tower.persistence.versioned_json import ConcurrentDocumentChangeError, VersionedDocumentWriteBlockedError


class ManualPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root/"manual_settings.json"
    def tearDown(self): self.temp.cleanup()

    def test_separate_settings_roundtrip_and_no_source_bound_geometry(self):
        auto = self.root/"user_settings.json"; auto.write_bytes(b"automatic settings")
        store = ManualSettingsStore(self.path)
        s = replace(store.load(),circle_segments=48,foot_diameter_mm=35,target_layer_time_s=20)
        store.save(s)
        self.assertEqual(ManualSettingsStore(self.path).load(),s)
        payload = json.loads(self.path.read_text())
        self.assertEqual(set(payload),{"manual","manual_settings_schema_version"})
        self.assertNotIn("points",str(payload))
        self.assertEqual(auto.read_bytes(),b"automatic settings")
        self.assertFalse(list(self.root.glob("*.tmp")))

    def test_legacy_migration_backup_normalization_and_atomic_write(self):
        original = b'{"manual":{"target_layer_time_s":12,"minimum_diameter_mm":"unsafe"}}'
        self.path.write_bytes(original)
        store = ManualSettingsStore(self.path)
        s = store.load()
        self.assertEqual(s.target_layer_time_s,12)
        self.assertEqual(s.minimum_diameter_mm,ManualSettings().minimum_diameter_mm)
        self.assertTrue(any(p.read_bytes() == original for p in self.root.glob("*backup*")))
        self.assertEqual(json.loads(self.path.read_text())["manual_settings_schema_version"],1)
        store.save(replace(s,target_layer_time_s=15))
        self.assertFalse(list(self.root.glob("*.tmp")))

    def test_unknown_future_and_corrupt_original_never_overwritten(self):
        for original in (b"broken",b'{"manual_settings_schema_version":2,"manual":{"target_layer_time_s":18}}'):
            self.path.write_bytes(original)
            store = ManualSettingsStore(self.path); s = store.load()
            self.assertIsNotNone(store.warning)
            with self.assertRaises(VersionedDocumentWriteBlockedError): store.save(s)
            self.assertEqual(self.path.read_bytes(),original)

    def test_external_change_and_explicit_recovery_preserve_original(self):
        store = ManualSettingsStore(self.path); s=store.load(); store.save(s)
        changed = self.path.read_bytes()+b"\n"; self.path.write_bytes(changed)
        with self.assertRaises(ConcurrentDocumentChangeError): store.save(replace(s,target_layer_time_s=16))
        self.assertEqual(self.path.read_bytes(),changed)
        self.path.write_bytes(b"corrupt")
        store = ManualSettingsStore(self.path); store.load(); store.recover()
        self.assertTrue(any(p.read_bytes() == b"corrupt" for p in self.root.glob("*backup*")))
        self.assertEqual(ManualSettingsStore(self.path).load(),ManualSettings())

    def test_future_downgrade_rejects_all_types_units_ranges_without_auto_mapping(self):
        for value in ("20",{"unit":"radians","value":1},-3,1e10,False):
            original=json.dumps({"manual_settings_schema_version":99,"manual":{"contraction_angle_deg":value},
                                 "generation":{"manual_base_width_mm":77}}).encode()
            self.path.write_bytes(original)
            store=ManualSettingsStore(self.path); s=store.load()
            self.assertEqual(s,ManualSettings())
            with self.assertRaises(VersionedDocumentWriteBlockedError): store.save(s)
            self.assertEqual(self.path.read_bytes(),original)

    def test_invalid_groups_do_not_leak_partially_and_bools_are_strict(self):
        self.path.write_text(json.dumps({"manual_settings_schema_version":1,"manual":{
            "minimum_diameter_mm":50,"maximum_diameter_mm":10,"maximum_foot_diameter_mm":12,
            "circle_segments":True,"overhang_enabled":"true","expansion_angle_deg":float("nan")}}))
        s=ManualSettingsStore(self.path).load()
        self.assertEqual(s,ManualSettings())


if __name__ == "__main__": unittest.main()
