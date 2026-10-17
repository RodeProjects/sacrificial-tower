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

    def test_v10_absolute_color_migration_keeps_reference_and_fade_width_with_backup(self):
        original=json.dumps({"manual_settings_schema_version":10,"manual":{
            "color_reference_time_s":12,"gradient_start_deficit_s":.5,"gradient_full_deficit_s":2,
            "circle_segments":48,"critical_layers_enabled":True}}).encode()
        self.path.write_bytes(original)
        settings=ManualSettingsStore(self.path).load()
        self.assertEqual((settings.color_reference_time_s,settings.color_red_time_s),(12,10.5))
        self.assertEqual(settings.circle_segments,48)
        self.assertTrue(settings.critical_layers_enabled)
        payload=json.loads(self.path.read_bytes())
        self.assertEqual(payload["manual_settings_schema_version"],MANUAL_SCHEMA_VERSION)
        self.assertNotIn("gradient_start_deficit_s",payload["manual"])
        self.assertNotIn("gradient_full_deficit_s",payload["manual"])
        self.assertTrue(any(path.read_bytes()==original for path in self.root.glob("*backup*")))
        self.assertEqual(ManualSettingsStore(self.path).load(),settings)
        self.assertFalse(list(self.root.glob("*.tmp")))

    def test_v10_migration_invalid_types_units_and_bounds_use_safe_seconds(self):
        for start,full in ((True,1),("0",1),(0,{"unit":"ms","value":1000}),
                           (-1,1),(2,1),(0,31),(0,float("nan"))):
            self.path.write_text(json.dumps({"manual_settings_schema_version":10,"manual":{
                "color_reference_time_s":20,"gradient_start_deficit_s":start,"gradient_full_deficit_s":full}}))
            settings=ManualSettingsStore(self.path).load()
            self.assertEqual((settings.color_reference_time_s,settings.color_red_time_s),(20,19))

    def test_v12_current_color_times_normalize_independently(self):
        for reference,deficit,expected in ((20,0,(20,4)),(20,-1,(20,4)),(31,6,(10,6)),
                (4,6,(10,6)),(10,61,(10,4)),(10,True,(10,4)),
                ("10",4,(10,4)),(10,{"unit":"ms","value":6000},(10,4))):
            self.path.write_text(json.dumps({"manual_settings_schema_version":12,"manual":{
                "color_reference_time_s":reference,"color_deficit_time_s":deficit}}))
            settings=ManualSettingsStore(self.path).load()
            self.assertEqual((settings.color_reference_time_s,settings.color_deficit_time_s),expected)

    def test_v11_downgrade_blocks_semantically_incompatible_color_times(self):
        for value in (12,10,9,True,"12",{"unit":"ms","value":12000},61):
            original=json.dumps({"manual_settings_schema_version":11,"manual":{
                "color_reference_time_s":10,"color_red_time_s":value}}).encode()
            self.path.write_bytes(original)
            older=VersionedJsonStore(self.path,schema_key="manual_settings_schema_version",current_version=10)
            with self.assertRaises(FutureSchemaVersionError):older.load()
            with self.assertRaises(VersionedDocumentWriteBlockedError):older.save({"manual":{}})
            self.assertEqual(self.path.read_bytes(),original)

    def test_v10_migration_failure_external_change_and_recovery_preserve_original(self):
        original=b'{"manual_settings_schema_version":10,"manual":{"color_reference_time_s":12}}'
        self.path.write_bytes(original);store=ManualSettingsStore(self.path)
        with patch("cooling_tower.persistence.versioned_json.atomic_write_json",side_effect=OSError("disk unavailable")):
            settings=store.load()
        self.assertEqual(self.path.read_bytes(),original)
        with self.assertRaises(VersionedDocumentWriteBlockedError):store.save(settings)
        self.assertTrue(any(path.read_bytes()==original for path in self.root.glob("*backup*")))
        store=ManualSettingsStore(self.path);settings=store.load()
        changed=self.path.read_bytes()+b" "
        self.path.write_bytes(changed)
        with self.assertRaises(ConcurrentDocumentChangeError):store.save(settings)
        self.assertEqual(self.path.read_bytes(),changed)
        store.recover()
        self.assertEqual(ManualSettingsStore(self.path).load(),ManualSettings())

    def test_v11_to_v12_preserves_fade_width_and_backs_up_absolute_colors(self):
        for reference,red in ((10,16),(12,13.5),(5,60)):
            original=json.dumps({"manual_settings_schema_version":11,"manual":{
                "color_reference_time_s":reference,"color_red_time_s":red,"circle_segments":48}}).encode()
            self.path.write_bytes(original)
            settings=ManualSettingsStore(self.path).load()
            self.assertEqual(settings.color_deficit_time_s,min(reference,red-reference))
            self.assertEqual(settings.color_red_time_s,max(0,2*reference-red))
            self.assertEqual(settings.circle_segments,48)
            payload=json.loads(self.path.read_bytes())
            self.assertEqual(payload["manual_settings_schema_version"],MANUAL_SCHEMA_VERSION)
            self.assertNotIn("color_red_time_s",payload["manual"])
            self.assertTrue(any(path.read_bytes()==original for path in self.root.glob("*backup*")))
            self.assertFalse(list(self.root.glob("*.tmp")))

    def test_v11_invalid_types_units_bounds_and_v12_downgrade_are_safe(self):
        for red in (True,"16",{"unit":"ms","value":16000},10,9,61,float("nan")):
            self.path.write_text(json.dumps({"manual_settings_schema_version":11,"manual":{
                "color_reference_time_s":10,"color_red_time_s":red}}))
            self.assertEqual(ManualSettingsStore(self.path).load(),ManualSettings())
        for deficit in (6,0,-1,61,True,"6",{"unit":"ms","value":6000}):
            original=json.dumps({"manual_settings_schema_version":12,"manual":{
                "color_reference_time_s":10,"color_deficit_time_s":deficit}}).encode()
            self.path.write_bytes(original)
            older=VersionedJsonStore(self.path,schema_key="manual_settings_schema_version",current_version=11)
            with self.assertRaises(FutureSchemaVersionError):older.load()
            with self.assertRaises(VersionedDocumentWriteBlockedError):older.save({"manual":{}})
            self.assertEqual(self.path.read_bytes(),original)

    def test_direct_v11_migration_write_failure_and_recovery_preserve_original(self):
        original=b'{"manual_settings_schema_version":11,"manual":{"color_reference_time_s":10,"color_red_time_s":16}}'
        self.path.write_bytes(original);store=ManualSettingsStore(self.path)
        with patch("cooling_tower.persistence.versioned_json.atomic_write_json",side_effect=OSError("disk unavailable")):
            settings=store.load()
        self.assertEqual(self.path.read_bytes(),original)
        with self.assertRaises(VersionedDocumentWriteBlockedError):store.save(settings)
        self.assertTrue(any(path.read_bytes()==original for path in self.root.glob("*backup*")))
        store=ManualSettingsStore(self.path);settings=store.load()
        changed=self.path.read_bytes()+b" "
        self.path.write_bytes(changed)
        with self.assertRaises(ConcurrentDocumentChangeError):store.save(settings)
        self.assertEqual(self.path.read_bytes(),changed)
        store.recover()
        self.assertEqual(ManualSettingsStore(self.path).load(),ManualSettings())

    def test_v12_caps_segments_and_negative_red_times_with_original_backup(self):
        for segments,deficit,expected in ((720,60,(256,10)),(257,4,(256,4)),(256,4,(256,4)),(48,4,(48,4))):
            original=json.dumps({"manual_settings_schema_version":12,"manual":{
                "circle_segments":segments,"color_reference_time_s":10,"color_deficit_time_s":deficit}}).encode()
            self.path.write_bytes(original)
            settings=ManualSettingsStore(self.path).load()
            self.assertEqual((settings.circle_segments,settings.color_deficit_time_s),expected)
            self.assertTrue(any(path.read_bytes()==original for path in self.root.glob("*backup*")))
            self.assertEqual(json.loads(self.path.read_bytes())["manual_settings_schema_version"],MANUAL_SCHEMA_VERSION)
            self.assertEqual(ManualSettingsStore(self.path).load(),settings)
            self.assertFalse(list(self.root.glob("*.tmp")))

    def test_v13_rejects_incompatible_types_units_and_tightened_bounds(self):
        for segments,reference,deficit,expected in ((257,10,4,(None,10,4)),(True,10,4,(None,10,4)),
                ("48",10,4,(None,10,4)),(48,5,6,(48,5,4)),
                (48,10,{"unit":"ms","value":4000},(48,10,4)),(48,10,-4,(48,10,4))):
            self.path.write_text(json.dumps({"manual_settings_schema_version":13,"manual":{
                "circle_segments":segments,"color_reference_time_s":reference,"color_deficit_time_s":deficit}}))
            settings=ManualSettingsStore(self.path).load()
            self.assertEqual((settings.circle_segments,settings.color_reference_time_s,settings.color_deficit_time_s),expected)

    def test_v13_to_v14_adds_scale_without_changing_times_and_keeps_backup(self):
        for reference,maximum in ((10,14),(20,20),(29.99,30)):
            original=json.dumps({"manual_settings_schema_version":13,"manual":{
                "color_reference_time_s":reference,"color_deficit_time_s":4,"circle_segments":48}}).encode()
            self.path.write_bytes(original)
            settings=ManualSettingsStore(self.path).load()
            self.assertEqual((settings.color_reference_time_s,settings.color_deficit_time_s,settings.circle_segments),(reference,4,48))
            self.assertEqual(settings.color_scale_max_time_s,maximum)
            self.assertTrue(any(path.read_bytes()==original for path in self.root.glob("*backup*")))
            self.assertEqual(json.loads(self.path.read_bytes())["manual_settings_schema_version"],MANUAL_SCHEMA_VERSION)
            self.assertFalse(list(self.root.glob("*.tmp")))

    def test_v14_scale_type_unit_bounds_and_downgrade_are_safe(self):
        for scale,expected in ((True,14),("20",14),({"unit":"ms","value":20000},14),
                (9,14),(-1,14),(3601,14),(float("nan"),14),(28,28)):
            self.path.write_text(json.dumps({"manual_settings_schema_version":14,"manual":{
                "color_reference_time_s":10,"color_deficit_time_s":4,"color_scale_max_time_s":scale}}))
            settings=ManualSettingsStore(self.path).load()
            self.assertEqual(settings.color_scale_max_time_s,expected)
            original=self.path.read_bytes()
            older=VersionedJsonStore(self.path,schema_key="manual_settings_schema_version",current_version=13)
            with self.assertRaises(FutureSchemaVersionError):older.load()
            with self.assertRaises(VersionedDocumentWriteBlockedError):older.save({"manual":{}})
            self.assertEqual(self.path.read_bytes(),original)

    def test_v13_scale_migration_write_failure_change_and_recovery_preserve_original(self):
        for version in (13,14,15,16,17):
            original=json.dumps({"manual_settings_schema_version":version,"manual":{"color_reference_time_s":20}}).encode()
            self.path.write_bytes(original);store=ManualSettingsStore(self.path)
            with patch("cooling_tower.persistence.versioned_json.atomic_write_json",side_effect=OSError("disk unavailable")):
                settings=store.load()
            self.assertEqual(self.path.read_bytes(),original)
            with self.assertRaises(VersionedDocumentWriteBlockedError):store.save(settings)
            self.assertTrue(any(path.read_bytes()==original for path in self.root.glob("*backup*")))
            store=ManualSettingsStore(self.path);settings=store.load()
            changed=self.path.read_bytes()+b" "
            self.path.write_bytes(changed)
            with self.assertRaises(ConcurrentDocumentChangeError):store.save(settings)
            self.assertEqual(self.path.read_bytes(),changed)
            store.recover()
            self.assertEqual(ManualSettingsStore(self.path).load(),ManualSettings())

    def test_v14_to_v15_preserves_valid_colors_scale_precision_and_original_backup(self):
        for reference,deficit,maximum in ((5,4,5),(10.0123456789,.0123456789,14),(30,6,3600)):
            original=json.dumps({"manual_settings_schema_version":14,"manual":{
                "color_reference_time_s":reference,"color_deficit_time_s":deficit,
                "color_scale_max_time_s":maximum,"circle_segments":48}}).encode()
            self.path.write_bytes(original)
            settings=ManualSettingsStore(self.path).load()
            self.assertEqual((settings.color_reference_time_s,settings.color_deficit_time_s,settings.color_scale_max_time_s),
                             (reference,deficit,maximum))
            self.assertEqual(settings.circle_segments,48)
            self.assertTrue(any(path.read_bytes()==original for path in self.root.glob("*backup*")))
            self.assertEqual(json.loads(self.path.read_bytes())["manual_settings_schema_version"],MANUAL_SCHEMA_VERSION)
            self.assertEqual(ManualSettingsStore(self.path).load(),settings)
            self.assertFalse(list(self.root.glob("*.tmp")))

    def test_v14_invalid_old_green_times_do_not_become_valid_during_migration(self):
        for reference in (3,4.9,True,"3",{"unit":"ms","value":3000},31,float("nan")):
            self.path.write_text(json.dumps({"manual_settings_schema_version":14,"manual":{
                "color_reference_time_s":reference,"color_deficit_time_s":4,"color_scale_max_time_s":14}}))
            self.assertEqual(ManualSettingsStore(self.path).load(),ManualSettings())

    def test_v15_low_color_times_roundtrip_and_invalid_deficits_use_valid_defaults(self):
        from cooling_tower.manual.geometry import validate_settings
        for reference,deficit,expected in ((3,.1,.1),(3,4,3),(3,True,3),(3,"1",3),
                (3,{"unit":"ms","value":1000},3),(3,-1,3),(3.5,4,3.5),(4,2,2)):
            self.path.write_text(json.dumps({"manual_settings_schema_version":MANUAL_SCHEMA_VERSION,"manual":{
                "color_reference_time_s":reference,"color_deficit_time_s":deficit,"color_scale_max_time_s":reference}}))
            store=ManualSettingsStore(self.path);settings=store.load()
            self.assertEqual((settings.color_reference_time_s,settings.color_deficit_time_s),(reference,expected))
            validate_settings(settings);store.save(settings)
            self.assertEqual(ManualSettingsStore(self.path).load(),settings)

    def test_v15_downgrade_blocks_types_units_and_changed_minimum_maximum(self):
        for reference in (True,"3",{"unit":"ms","value":3000},2.9,3,4.9,5,30,31):
            original=json.dumps({"manual_settings_schema_version":15,"manual":{
                "color_reference_time_s":reference,"color_deficit_time_s":.1,"color_scale_max_time_s":3}}).encode()
            self.path.write_bytes(original)
            older=VersionedJsonStore(self.path,schema_key="manual_settings_schema_version",current_version=14)
            with self.assertRaises(FutureSchemaVersionError):older.load()
            with self.assertRaises(VersionedDocumentWriteBlockedError):older.save({"manual":{}})
            self.assertEqual(self.path.read_bytes(),original)

    def test_v15_to_v16_preserves_valid_scales_and_backs_up_original(self):
        for maximum in (14,60,120,3600):
            original=json.dumps({"manual_settings_schema_version":15,"manual":{
                "color_scale_max_time_s":maximum,"circle_segments":48}}).encode()
            self.path.write_bytes(original)
            settings=ManualSettingsStore(self.path).load()
            self.assertEqual(settings.color_scale_max_time_s,maximum)
            self.assertEqual(settings.circle_segments,48)
            self.assertTrue(any(path.read_bytes()==original for path in self.root.glob("*backup*")))
            self.assertEqual(json.loads(self.path.read_bytes())["manual_settings_schema_version"],MANUAL_SCHEMA_VERSION)
            self.assertEqual(ManualSettingsStore(self.path).load(),settings)
            self.assertFalse(list(self.root.glob("*.tmp")))

    def test_v15_invalid_scales_do_not_become_valid_under_the_object_exception(self):
        for maximum in (3600.1,7200,True,"120",{"unit":"ms","value":120000},float("inf"),float("nan")):
            self.path.write_text(json.dumps({"manual_settings_schema_version":15,"manual":{
                "color_scale_max_time_s":maximum}}))
            self.assertEqual(ManualSettingsStore(self.path).load(),ManualSettings())

    def test_v16_allows_finite_long_object_scales_without_serializing_object_data(self):
        from cooling_tower.manual.geometry import validate_settings
        for maximum in (60,123.4,7200.5,1e308):
            store=ManualSettingsStore(self.path)
            settings=replace(store.load(),color_scale_max_time_s=maximum)
            validate_settings(settings);store.save(settings)
            self.assertEqual(ManualSettingsStore(self.path).load(),settings)
            self.assertNotIn("layers",json.loads(self.path.read_text())["manual"])

    def test_v16_downgrade_blocks_incompatible_scale_types_units_and_bounds(self):
        for maximum in (True,"120",{"unit":"ms","value":120000},2.9,60,3600,7200.5):
            original=json.dumps({"manual_settings_schema_version":16,"manual":{"color_scale_max_time_s":maximum}}).encode()
            self.path.write_bytes(original)
            older=VersionedJsonStore(self.path,schema_key="manual_settings_schema_version",current_version=15)
            with self.assertRaises(FutureSchemaVersionError):older.load()
            with self.assertRaises(VersionedDocumentWriteBlockedError):older.save({"manual":{}})
            self.assertEqual(self.path.read_bytes(),original)

    def test_v16_to_v17_preserves_valid_times_and_original_backup(self):
        for reference,maximum in ((3,3),(10,60),(30,120)):
            original=json.dumps({"manual_settings_schema_version":16,"manual":{
                "color_reference_time_s":reference,"color_deficit_time_s":.1,"color_scale_max_time_s":maximum}}).encode()
            self.path.write_bytes(original)
            settings=ManualSettingsStore(self.path).load()
            self.assertEqual((settings.color_reference_time_s,settings.color_scale_max_time_s),(reference,maximum))
            self.assertEqual(settings.color_deficit_time_s,.1)
            self.assertTrue(any(path.read_bytes()==original for path in self.root.glob("*backup*")))
            self.assertEqual(json.loads(self.path.read_bytes())["manual_settings_schema_version"],MANUAL_SCHEMA_VERSION)
            self.assertEqual(ManualSettingsStore(self.path).load(),settings)
            self.assertFalse(list(self.root.glob("*.tmp")))

    def test_v16_invalid_references_do_not_become_valid_in_the_expanded_green_range(self):
        for reference in (31,60,120,True,"60",{"unit":"ms","value":60000},float("inf"),float("nan")):
            self.path.write_text(json.dumps({"manual_settings_schema_version":16,"manual":{
                "color_reference_time_s":reference}}))
            self.assertEqual(ManualSettingsStore(self.path).load(),ManualSettings())

    def test_v17_roundtrips_long_green_times_and_blocks_downgrade_types_units_bounds(self):
        for reference in (60,123.4,7200.5):
            store=ManualSettingsStore(self.path)
            settings=replace(store.load(),color_reference_time_s=reference,color_deficit_time_s=4,color_scale_max_time_s=reference)
            store.save(settings)
            self.assertEqual(ManualSettingsStore(self.path).load(),settings)
        for reference in (True,"60",{"unit":"ms","value":60000},2.9,30,60,123.4):
            original=json.dumps({"manual_settings_schema_version":17,"manual":{"color_reference_time_s":reference}}).encode()
            self.path.write_bytes(original)
            older=VersionedJsonStore(self.path,schema_key="manual_settings_schema_version",current_version=16)
            with self.assertRaises(FutureSchemaVersionError):older.load()
            with self.assertRaises(VersionedDocumentWriteBlockedError):older.save({"manual":{}})
            self.assertEqual(self.path.read_bytes(),original)

    def test_v17_to_v18_preserves_positive_deficits_and_original_backup(self):
        for reference,deficit in ((3,.1),(10,4),(60,60),(120,10)):
            original=json.dumps({"manual_settings_schema_version":17,"manual":{
                "color_reference_time_s":reference,"color_deficit_time_s":deficit,"color_scale_max_time_s":reference}}).encode()
            self.path.write_bytes(original)
            settings=ManualSettingsStore(self.path).load()
            self.assertEqual((settings.color_reference_time_s,settings.color_deficit_time_s),(reference,deficit))
            self.assertTrue(any(path.read_bytes()==original for path in self.root.glob("*backup*")))
            self.assertEqual(json.loads(self.path.read_bytes())["manual_settings_schema_version"],MANUAL_SCHEMA_VERSION)
            self.assertEqual(ManualSettingsStore(self.path).load(),settings)
            self.assertFalse(list(self.root.glob("*.tmp")))

    def test_zero_deficits_from_old_formats_use_the_former_safe_default(self):
        for version in (16,17):
            for reference in (3,10,30):
                self.path.write_text(json.dumps({"manual_settings_schema_version":version,"manual":{
                    "color_reference_time_s":reference,"color_deficit_time_s":0}}))
                settings=ManualSettingsStore(self.path).load()
                self.assertEqual(settings.color_deficit_time_s,min(4,reference))

    def test_v18_roundtrips_hard_boundaries_and_blocks_downgrade(self):
        for reference in (3,10,60,120):
            store=ManualSettingsStore(self.path)
            settings=replace(store.load(),color_reference_time_s=reference,color_deficit_time_s=0,color_scale_max_time_s=reference)
            store.save(settings)
            self.assertEqual(ManualSettingsStore(self.path).load(),settings)
        for deficit in (0,-1,True,"0",{"unit":"ms","value":0},11):
            original=json.dumps({"manual_settings_schema_version":18,"manual":{"color_deficit_time_s":deficit}}).encode()
            self.path.write_bytes(original)
            older=VersionedJsonStore(self.path,schema_key="manual_settings_schema_version",current_version=17)
            with self.assertRaises(FutureSchemaVersionError):older.load()
            with self.assertRaises(VersionedDocumentWriteBlockedError):older.save({"manual":{}})
            self.assertEqual(self.path.read_bytes(),original)

    def test_v12_migration_write_failure_external_change_recovery_and_downgrade(self):
        original=b'{"manual_settings_schema_version":12,"manual":{"circle_segments":720}}'
        self.path.write_bytes(original);store=ManualSettingsStore(self.path)
        with patch("cooling_tower.persistence.versioned_json.atomic_write_json",side_effect=OSError("disk unavailable")):
            settings=store.load()
        self.assertEqual(self.path.read_bytes(),original)
        with self.assertRaises(VersionedDocumentWriteBlockedError):store.save(settings)
        self.assertTrue(any(path.read_bytes()==original for path in self.root.glob("*backup*")))
        store=ManualSettingsStore(self.path);settings=store.load()
        changed=self.path.read_bytes()+b" "
        self.path.write_bytes(changed)
        with self.assertRaises(ConcurrentDocumentChangeError):store.save(settings)
        self.assertEqual(self.path.read_bytes(),changed)
        older=VersionedJsonStore(self.path,schema_key="manual_settings_schema_version",current_version=12)
        with self.assertRaises(FutureSchemaVersionError):older.load()
        with self.assertRaises(VersionedDocumentWriteBlockedError):older.save({"manual":{"circle_segments":720}})
        self.assertEqual(self.path.read_bytes(),changed)
        store.recover()
        self.assertEqual(ManualSettingsStore(self.path).load(),ManualSettings())

    def test_overhang_default_is_enabled_and_saved_choices_remain(self):
        store = ManualSettingsStore(self.path)
        self.assertTrue(store.load().overhang_enabled)
        self.path.write_text(json.dumps({"manual_settings_schema_version":MANUAL_SCHEMA_VERSION,"manual":{}}))
        self.assertTrue(ManualSettingsStore(self.path).load().overhang_enabled)
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                store = ManualSettingsStore(self.path)
                store.save(replace(store.load(),overhang_enabled=enabled))
                self.assertEqual(ManualSettingsStore(self.path).load().overhang_enabled,enabled)

    def test_separate_settings_roundtrip_and_no_source_bound_geometry(self):
        auto = self.root/"user_settings.json"; auto.write_bytes(b"automatic settings")
        store = ManualSettingsStore(self.path)
        s = replace(store.load(),circle_segments=48,foot_diameter_mm=35,color_reference_time_s=20,color_deficit_time_s=6,color_scale_max_time_s=28,layer_snap_enabled=False,object_resolution_percent=75)
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
        store.save(replace(s,color_reference_time_s=15,color_deficit_time_s=6,color_scale_max_time_s=20))
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
            self.assertEqual(ManualSettingsStore(self.path).load().object_resolution_percent,75)

    def test_new_resolution_default_is_75_and_existing_choices_remain(self):
        self.assertEqual(ManualSettingsStore(self.path).load().object_resolution_percent,75)
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
        with self.assertRaises(ConcurrentDocumentChangeError): store.save(replace(s,color_reference_time_s=16,color_deficit_time_s=6,color_scale_max_time_s=20))
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
            self.assertEqual(json.loads(self.path.read_bytes())["manual_settings_schema_version"],MANUAL_SCHEMA_VERSION)
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
        self.assertEqual(s,replace(ManualSettings(),object_resolution_percent=50,color_deficit_time_s=1))

    def test_one_millimetre_migration_direct_multistep_backup_and_atomic_write(self):
        for version in (1,8,9):
            for minimum in (.25,1,12):
                with self.subTest(version=version,minimum=minimum):
                    original=json.dumps({"manual_settings_schema_version":version,"manual":{
                        "minimum_diameter_mm":minimum,"circle_segments":48}}).encode()
                    self.path.write_bytes(original)
                    store=ManualSettingsStore(self.path);settings=store.load()
                    self.assertEqual(settings.minimum_diameter_mm,max(1,minimum))
                    self.assertEqual(settings.circle_segments,48)
                    self.assertTrue(any(p.read_bytes()==original for p in self.root.glob("*backup*")))
                    store.save(settings)
                    self.assertEqual(json.loads(self.path.read_bytes())["manual_settings_schema_version"],MANUAL_SCHEMA_VERSION)
                    self.assertFalse(list(self.root.glob("*.tmp")))
        self.path.write_text(json.dumps({"manual_settings_schema_version":9,"manual":{
            "minimum_diameter_mm":.2,"maximum_diameter_mm":.8,
            "foot_diameter_mm":.5,"maximum_foot_diameter_mm":.9}}))
        settings=ManualSettingsStore(self.path).load()
        self.assertEqual(tuple(getattr(settings,name) for name in
            ("minimum_diameter_mm","maximum_diameter_mm","foot_diameter_mm","maximum_foot_diameter_mm")),(1,1,1,1))

    def test_v10_downgrade_blocks_incompatible_diameters_without_overwriting(self):
        for value in (.5,0,1001,False,"1",{"unit":"micrometres","value":1000}):
            original=json.dumps({"manual_settings_schema_version":10,"manual":{
                "minimum_diameter_mm":value}}).encode()
            self.path.write_bytes(original)
            older=VersionedJsonStore(self.path,schema_key="manual_settings_schema_version",current_version=9)
            with self.assertRaises(FutureSchemaVersionError):older.load()
            with self.assertRaises(VersionedDocumentWriteBlockedError):older.save({"manual":{}})
            self.assertEqual(self.path.read_bytes(),original)
        for version in (9,10):
            for value in (0,1001,False,"1",{"unit":"micrometres","value":1000}):
                self.path.write_text(json.dumps({"manual_settings_schema_version":version,"manual":{
                    "minimum_diameter_mm":value}}))
                self.assertEqual(ManualSettingsStore(self.path).load().minimum_diameter_mm,ManualSettings().minimum_diameter_mm)
        self.path.write_text(json.dumps({"manual_settings_schema_version":10,"manual":{"minimum_diameter_mm":.5}}))
        self.assertEqual(ManualSettingsStore(self.path).load().minimum_diameter_mm,ManualSettings().minimum_diameter_mm)

    def test_v9_floor_migration_write_failure_external_change_and_recovery(self):
        original=b'{"manual_settings_schema_version":9,"manual":{"minimum_diameter_mm":0.5}}'
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


if __name__ == "__main__": unittest.main()
