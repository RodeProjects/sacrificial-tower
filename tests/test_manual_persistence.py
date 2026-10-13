import sys
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from dataclasses import replace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))

from cooling_tower.manual.geometry import ManualSettings
from cooling_tower.manual.settings_store import ManualSettingsStore,MANUAL_SCHEMA_VERSION
from cooling_tower.persistence.versioned_json import (ConcurrentDocumentChangeError, VersionedDocumentWriteBlockedError,
                                                    VersionedJsonStore, FutureSchemaVersionError)


class ManualPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root/"manual_settings.json"
    def tearDown(self): self.temp.cleanup()

    def test_separate_settings_roundtrip_and_no_source_bound_geometry(self):
        auto = self.root/"user_settings.json"; auto.write_bytes(b"automatic settings")
        store = ManualSettingsStore(self.path)
        s = replace(store.load(),circle_segments=48,foot_diameter_mm=35,color_reference_time_s=20,layer_snap_enabled=False,object_resolution_percent=75)
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
        self.assertEqual(s.color_reference_time_s,12)
        self.assertEqual(s.minimum_diameter_mm,ManualSettings().minimum_diameter_mm)
        self.assertTrue(any(p.read_bytes() == original for p in self.root.glob("*backup*")))
        self.assertEqual(json.loads(self.path.read_text())["manual_settings_schema_version"],MANUAL_SCHEMA_VERSION)
        self.assertTrue(s.layer_snap_enabled)
        store.save(replace(s,color_reference_time_s=15))
        self.assertFalse(list(self.root.glob("*.tmp")))

    def test_direct_migration_discards_tolerance_and_preserves_valid_visual_and_geometry_settings(self):
        original=json.dumps({"manual_settings_schema_version":1,"manual":{
            "target_layer_time_s":18,"layer_time_tolerance_s":.75,"foot_diameter_mm":35,
            "circle_segments":48,"critical_layers_enabled":True}}).encode()
        self.path.write_bytes(original)
        s=ManualSettingsStore(self.path).load()
        self.assertEqual(s.color_reference_time_s,18)
        self.assertEqual(s.foot_diameter_mm,35)
        self.assertTrue(s.critical_layers_enabled)
        self.assertFalse(hasattr(s,"layer_time_tolerance_s"))
        payload=json.loads(self.path.read_bytes())
        self.assertEqual(payload["manual_settings_schema_version"],MANUAL_SCHEMA_VERSION)
        self.assertNotIn("target_layer_time_s",payload["manual"])
        self.assertNotIn("layer_time_tolerance_s",payload["manual"])
        self.assertTrue(any(p.read_bytes()==original for p in self.root.glob("*backup*")))
        self.assertFalse(list(self.root.glob("*.tmp")))

    def test_migration_normalizes_incompatible_types_units_and_ranges(self):
        for value in ("18",{"unit":"ms","value":18000},False,4,31,float("nan")):
            self.path.write_text(json.dumps({"manual_settings_schema_version":1,"manual":{
                "target_layer_time_s":value,"foot_diameter_mm":35}}))
            store=ManualSettingsStore(self.path)
            s=store.load()
            self.assertEqual(s.color_reference_time_s,ManualSettings().color_reference_time_s)
            self.assertEqual(s.foot_diameter_mm,35)
            self.assertIsNone(store.warning)

    def test_direct_v2_migration_enables_snap_and_preserves_preferences(self):
        original=json.dumps({"manual_settings_schema_version":2,"manual":{
            "color_reference_time_s":18,"circle_segments":48,"foot_diameter_mm":35}}).encode()
        self.path.write_bytes(original)
        s=ManualSettingsStore(self.path).load()
        self.assertTrue(s.layer_snap_enabled)
        self.assertEqual((s.color_reference_time_s,s.circle_segments,s.foot_diameter_mm),(18,48,35))
        self.assertTrue(any(p.read_bytes()==original for p in self.root.glob("*backup*")))
        self.assertEqual(json.loads(self.path.read_bytes())["manual_settings_schema_version"],MANUAL_SCHEMA_VERSION)
        self.assertFalse(list(self.root.glob("*.tmp")))

    def test_snap_boolean_normalizes_strictly_in_current_schema(self):
        for value in ("false",0,1,None,[],{"enabled":False}):
            self.path.write_text(json.dumps({"manual_settings_schema_version":MANUAL_SCHEMA_VERSION,"manual":{"layer_snap_enabled":value}}))
            self.assertTrue(ManualSettingsStore(self.path).load().layer_snap_enabled)

    def test_v3_resolution_migration_preserves_snap_and_backs_up_original(self):
        original=json.dumps({"manual_settings_schema_version":3,"manual":{
            "layer_snap_enabled":False,"color_reference_time_s":18,"circle_segments":48}}).encode()
        self.path.write_bytes(original)
        s=ManualSettingsStore(self.path).load()
        self.assertEqual(s.object_resolution_percent,50)
        self.assertFalse(s.layer_snap_enabled)
        self.assertEqual(s.circle_segments,48)
        self.assertTrue(any(p.read_bytes()==original for p in self.root.glob("*backup*")))
        self.assertEqual(json.loads(self.path.read_bytes())["manual_settings_schema_version"],MANUAL_SCHEMA_VERSION)
        self.assertFalse(list(self.root.glob("*.tmp")))

    def test_resolution_normalization_rejects_wrong_types_and_stages(self):
        for value in (True,"50",None,-1,3,20,2,55,110,50.0,{"unit":"ratio","value":.5}):
            self.path.write_text(json.dumps({"manual_settings_schema_version":MANUAL_SCHEMA_VERSION,"manual":{"object_resolution_percent":value}}))
            self.assertEqual(ManualSettingsStore(self.path).load().object_resolution_percent,0)

    def test_new_resolution_default_is_silhouette_and_existing_choices_remain(self):
        self.assertEqual(ManualSettingsStore(self.path).load().object_resolution_percent,0)
        for value in (0,1,10,15,75):
            self.path.write_text(json.dumps({"manual_settings_schema_version":MANUAL_SCHEMA_VERSION,
                                            "manual":{"object_resolution_percent":value}}))
            self.assertEqual(ManualSettingsStore(self.path).load().object_resolution_percent,value)

    def test_v4_resolution_migration_maps_old_stages_and_preserves_source_backup(self):
        for value,expected in ((10,10),(20,25),(30,25),(40,50),(50,50),(60,50),(70,75),(80,75),(90,100),(100,100)):
            with self.subTest(value=value):
                original=json.dumps({"manual_settings_schema_version":4,"manual":{
                    "object_resolution_percent":value,"layer_snap_enabled":False,"circle_segments":48}}).encode()
                self.path.write_bytes(original)
                settings=ManualSettingsStore(self.path).load()
                self.assertEqual(settings.object_resolution_percent,expected)
                self.assertFalse(settings.layer_snap_enabled)
                self.assertEqual(settings.circle_segments,48)
                self.assertTrue(any(p.read_bytes()==original for p in self.root.glob("*backup*")))
                self.assertEqual(json.loads(self.path.read_bytes())["manual_settings_schema_version"],MANUAL_SCHEMA_VERSION)
                self.assertFalse(list(self.root.glob("*.tmp")))

    def test_v4_resolution_migration_rejects_incompatible_types_units_and_old_ranges(self):
        for value in (False,"50",{"unit":"ratio","value":.5},0,5,55,110,50.0):
            self.path.write_text(json.dumps({"manual_settings_schema_version":4,"manual":{"object_resolution_percent":value}}))
            self.assertEqual(ManualSettingsStore(self.path).load().object_resolution_percent,10)

    def test_failed_migration_write_preserves_original_and_blocks_later_save(self):
        original=b'{"manual_settings_schema_version":1,"manual":{"target_layer_time_s":18}}'
        self.path.write_bytes(original)
        store=ManualSettingsStore(self.path)
        with patch("cooling_tower.persistence.versioned_json.atomic_write_json",side_effect=OSError("disk unavailable")):
            s=store.load()
        self.assertIsNotNone(store.warning)
        self.assertEqual(self.path.read_bytes(),original)
        self.assertTrue(any(p.read_bytes()==original for p in self.root.glob("*backup*")))
        with self.assertRaises(VersionedDocumentWriteBlockedError):store.save(s)
        self.assertFalse(list(self.root.glob("*.tmp")))

    def test_v5_resolution_migration_preserves_values_and_maps_twenty_with_backup(self):
        for value in (1,3,5,10,15,20,25,50,75,100):
            original=json.dumps({"manual_settings_schema_version":5,"manual":{
                "object_resolution_percent":value,"layer_snap_enabled":False,"circle_segments":48}}).encode()
            self.path.write_bytes(original)
            store=ManualSettingsStore(self.path);settings=store.load()
            self.assertEqual(settings.object_resolution_percent,25 if value == 20 else 5 if value in (1,3) else value)
            self.assertFalse(settings.layer_snap_enabled)
            self.assertEqual(settings.circle_segments,48)
            self.assertTrue(any(p.read_bytes()==original for p in self.root.glob("*backup*")))
            self.assertEqual(json.loads(self.path.read_bytes())["manual_settings_schema_version"],MANUAL_SCHEMA_VERSION)
            store.save(replace(settings,object_resolution_percent=0))
            self.assertEqual(ManualSettingsStore(self.path).load().object_resolution_percent,0)
            self.assertFalse(list(self.root.glob("*.tmp")))

    def test_v6_direct_and_multistep_migrations_reject_invalid_old_resolution_values(self):
        for value in (0,False,"20",20.,{"unit":"ratio","value":.2},-1,101):
            self.path.write_text(json.dumps({"manual_settings_schema_version":5,"manual":{
                "object_resolution_percent":value}}))
            self.assertEqual(ManualSettingsStore(self.path).load().object_resolution_percent,10)
        for version in range(6):
            original=json.dumps({"manual_settings_schema_version":version,"manual":{
                "object_resolution_percent":20,"circle_segments":48}}).encode()
            self.path.write_bytes(original)
            settings=ManualSettingsStore(self.path).load()
            self.assertEqual(settings.object_resolution_percent,50 if version < 4 else 25)
            self.assertEqual(settings.circle_segments,48)
            self.assertTrue(any(p.read_bytes()==original for p in self.root.glob("*backup*")))
        from cooling_tower.manual.settings_store import migrate_manual_v4
        self.assertEqual(migrate_manual_v4({"manual":{"object_resolution_percent":20}})["manual"]["object_resolution_percent"],20)

    def test_v6_downgrade_blocks_silhouette_types_units_and_changed_ranges(self):
        for value in (0,False,"0",{"unit":"ratio","value":0},-1,20,100,101):
            original=json.dumps({"manual_settings_schema_version":6,"manual":{
                "object_resolution_percent":value}}).encode()
            self.path.write_bytes(original)
            older=VersionedJsonStore(self.path,schema_key="manual_settings_schema_version",current_version=5,
                                     normalizer=lambda payload:dict(payload))
            with self.assertRaises(FutureSchemaVersionError):older.load()
            with self.assertRaises(VersionedDocumentWriteBlockedError):older.save({"manual":{}})
            self.assertEqual(self.path.read_bytes(),original)

    def test_v6_eight_stage_migration_keeps_silhouette_and_maps_one_and_three(self):
        for value in (0,1,3,5,10,15,25,50,75,100):
            original=json.dumps({"manual_settings_schema_version":6,"manual":{
                "object_resolution_percent":value,"layer_snap_enabled":False}}).encode()
            self.path.write_bytes(original)
            store=ManualSettingsStore(self.path);settings=store.load()
            self.assertEqual(settings.object_resolution_percent,5 if value in (1,3) else value)
            self.assertFalse(settings.layer_snap_enabled)
            self.assertTrue(any(p.read_bytes()==original for p in self.root.glob("*backup*")))
            self.assertEqual(json.loads(self.path.read_bytes())["manual_settings_schema_version"],MANUAL_SCHEMA_VERSION)
            self.assertFalse(list(self.root.glob("*.tmp")))
        for value in (False,"3",3.,{"unit":"ratio","value":.03},-1,20,101):
            self.path.write_text(json.dumps({"manual_settings_schema_version":6,"manual":{"object_resolution_percent":value}}))
            self.assertEqual(ManualSettingsStore(self.path).load().object_resolution_percent,10)

    def test_v7_downgrade_blocks_removed_stages_types_units_and_changed_ranges(self):
        for value in (0,1,3,False,"15",15.,{"unit":"ratio","value":.15},-1,101):
            original=json.dumps({"manual_settings_schema_version":7,"manual":{
                "object_resolution_percent":value}}).encode()
            self.path.write_bytes(original)
            older=VersionedJsonStore(self.path,schema_key="manual_settings_schema_version",current_version=6,
                                     normalizer=lambda payload:dict(payload))
            with self.assertRaises(FutureSchemaVersionError):older.load()
            with self.assertRaises(VersionedDocumentWriteBlockedError):older.save({"manual":{}})
            self.assertEqual(self.path.read_bytes(),original)

    def test_v7_adds_one_percent_preserves_old_choices_and_backs_up(self):
        for value in (0,5,10,15,25,50,75,100):
            original=json.dumps({"manual_settings_schema_version":7,"manual":{
                "object_resolution_percent":value,"circle_segments":48}}).encode()
            self.path.write_bytes(original)
            settings=ManualSettingsStore(self.path).load()
            self.assertEqual(settings.object_resolution_percent,value)
            self.assertEqual(settings.circle_segments,48)
            self.assertTrue(any(p.read_bytes()==original for p in self.root.glob("*backup*")))
            self.assertEqual(json.loads(self.path.read_bytes())["manual_settings_schema_version"],MANUAL_SCHEMA_VERSION)
            self.assertFalse(list(self.root.glob("*.tmp")))
        for value in (1,3,20,True,"1",1.,{"unit":"ratio","value":.01},-1,101):
            self.path.write_text(json.dumps({"manual_settings_schema_version":7,"manual":{"object_resolution_percent":value}}))
            self.assertEqual(ManualSettingsStore(self.path).load().object_resolution_percent,0)

    def test_v8_downgrade_preserves_original_and_current_one_percent_roundtrips(self):
        for value in (0,1,True,"1",1.,{"unit":"ratio","value":.01},-1,101):
            original=json.dumps({"manual_settings_schema_version":8,"manual":{"object_resolution_percent":value}}).encode()
            self.path.write_bytes(original)
            older=VersionedJsonStore(self.path,schema_key="manual_settings_schema_version",current_version=7,
                                     normalizer=lambda payload:dict(payload))
            with self.assertRaises(FutureSchemaVersionError):older.load()
            with self.assertRaises(VersionedDocumentWriteBlockedError):older.save({"manual":{}})
            self.assertEqual(self.path.read_bytes(),original)
        self.path.unlink()
        store=ManualSettingsStore(self.path);store.save(replace(ManualSettings(),object_resolution_percent=1))
        self.assertEqual(ManualSettingsStore(self.path).load().object_resolution_percent,1)

    def test_unknown_future_and_corrupt_original_never_overwritten(self):
        for original in (b"broken",b'{"manual_settings_schema_version":99,"manual":{"color_reference_time_s":18}}'):
            self.path.write_bytes(original)
            store = ManualSettingsStore(self.path); s = store.load()
            self.assertIsNotNone(store.warning)
            with self.assertRaises(VersionedDocumentWriteBlockedError): store.save(s)
            self.assertEqual(self.path.read_bytes(),original)

    def test_external_change_and_explicit_recovery_preserve_original(self):
        store = ManualSettingsStore(self.path); s=store.load(); store.save(s)
        changed = self.path.read_bytes()+b"\n"; self.path.write_bytes(changed)
        with self.assertRaises(ConcurrentDocumentChangeError): store.save(replace(s,color_reference_time_s=16))
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

    def test_v8_automatic_quality_migration_keeps_choices_and_backs_up_original(self):
        for stage in (0,1,5,10,15,25,50,75,100):
            original=json.dumps({"manual_settings_schema_version":8,"manual":{
                "object_resolution_percent":stage,"circle_segments":48}}).encode()
            self.path.write_bytes(original)
            store=ManualSettingsStore(self.path);settings=store.load()
            self.assertEqual(settings.object_resolution_percent,stage)
            self.assertEqual(settings.circle_segments,48)
            self.assertEqual(json.loads(self.path.read_bytes())["manual_settings_schema_version"],9)
            self.assertTrue(any(p.read_bytes()==original for p in self.root.glob("*backup*")))
            store.save(settings)
            self.assertFalse(list(self.root.glob("*.tmp")))

    def test_v9_downgrade_does_not_reinterpret_quality_preferences_as_face_percentages(self):
        for value in (1,100,False,"15",{"unit":"ratio","value":.15},-1,101):
            original=json.dumps({"manual_settings_schema_version":9,"manual":{
                "object_resolution_percent":value}}).encode()
            self.path.write_bytes(original)
            older=VersionedJsonStore(self.path,schema_key="manual_settings_schema_version",current_version=8)
            with self.assertRaises(FutureSchemaVersionError):older.load()
            with self.assertRaises(VersionedDocumentWriteBlockedError):older.save({"manual":{}})
            self.assertEqual(self.path.read_bytes(),original)

    def test_v8_migration_write_failure_concurrent_change_and_recovery_preserve_source(self):
        original=b'{"manual_settings_schema_version":8,"manual":{"object_resolution_percent":15}}'
        self.path.write_bytes(original);store=ManualSettingsStore(self.path)
        with patch("cooling_tower.persistence.versioned_json.atomic_write_json",side_effect=OSError("disk unavailable")):
            settings=store.load()
        self.assertEqual(self.path.read_bytes(),original)
        with self.assertRaises(VersionedDocumentWriteBlockedError):store.save(settings)
        self.assertTrue(any(p.read_bytes()==original for p in self.root.glob("*backup*")))
        store=ManualSettingsStore(self.path);settings=store.load()
        changed=self.path.read_bytes()+b" "
        self.path.write_bytes(changed)
        with self.assertRaises(ConcurrentDocumentChangeError):store.save(settings)
        self.assertEqual(self.path.read_bytes(),changed)
        store.recover()
        self.assertEqual(ManualSettingsStore(self.path).load(),ManualSettings())

    def test_invalid_groups_do_not_leak_partially_and_bools_are_strict(self):
        self.path.write_text(json.dumps({"manual_settings_schema_version":1,"manual":{
            "minimum_diameter_mm":50,"maximum_diameter_mm":10,"maximum_foot_diameter_mm":12,
            "circle_segments":True,"overhang_enabled":"true","expansion_angle_deg":float("nan")}}))
        s=ManualSettingsStore(self.path).load()
        self.assertEqual(s,replace(ManualSettings(),object_resolution_percent=50))


if __name__ == "__main__": unittest.main()
