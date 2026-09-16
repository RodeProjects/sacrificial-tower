import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from cooling_tower.config import SETTINGS_SCHEMA_VERSION
from cooling_tower.gui.main_window import MainWindow
from cooling_tower.gui.settings_store import UserSettingsStore
from cooling_tower.models import GenerationSettings
from cooling_tower.preview import PreviewExportResult, OutputMode
from cooling_tower.settings_compatibility import merge_compatible_setting_changes


class LayerTimeToleranceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'settings.json'

    def store(self):
        return UserSettingsStore(self.path, ROOT / 'config/default_settings.json')

    def save(self, store, settings):
        return store.save(settings, output_root='output', window_width=900, window_height=900)

    def test_direct_and_multistep_migration_backup_and_roundtrip(self):
        for version in (0, 8, 10, 11):
            with self.subTest(version=version):
                original = json.dumps({'settings_schema_version': version,
                    'generation': {'target_layer_time_s': 12.0, 'base_height_mm': 7.0}}).encode()
                self.path.write_bytes(original)
                store = self.store()
                settings, payload = store.load()
                self.assertEqual(settings.layer_time_tolerance_s, 0.2 if version < 11 else 0.25)
                self.assertEqual(settings.target_layer_time_s, 12.0)
                self.assertEqual(payload['settings_schema_version'], SETTINGS_SCHEMA_VERSION)
                self.assertNotIn('base_height_mm', payload['generation'])
                self.assertNotIn('base_height_mm', settings.to_dict())
                self.assertEqual(store.last_migration_backup.read_bytes(), original)
                self.save(store, replace(settings, layer_time_tolerance_s=0.01))
                self.assertEqual(self.store().load()[0].layer_time_tolerance_s, 0.01)
                self.save(store, replace(settings, layer_time_tolerance_s=3.0))
                self.assertEqual(self.store().load()[0].layer_time_tolerance_s, 3.0)

    def test_failed_atomic_migration_preserves_original_and_recovers(self):
        original = b'{"settings_schema_version":11,"generation":{"base_height_mm":7}}'
        self.path.write_bytes(original)
        store = self.store()
        with patch('cooling_tower.persistence.versioned_json.os.replace', side_effect=OSError('locked')):
            store.load()
        self.assertEqual(self.path.read_bytes(), original)
        self.assertIsNotNone(store.last_load_warning)
        self.assertEqual(self.store().load()[0].layer_time_tolerance_s, 0.25)

    def test_corrupt_and_future_files_are_preserved(self):
        for original in (b'{broken', b'{"settings_schema_version":999,"generation":{"layer_time_tolerance_s":0.8}}'):
            self.path.write_bytes(original)
            store = self.store()
            store.load()
            self.assertEqual(self.path.read_bytes(), original)
            self.assertIsNotNone(store.last_load_warning)
        self.path.write_bytes(b'{broken')
        store = self.store()
        store.load()
        store.recover(GenerationSettings(layer_time_tolerance_s=0.8), output_root='output',
                      window_width=900, window_height=900)
        self.assertEqual(self.store().load()[0].layer_time_tolerance_s, 0.8)

    def test_downgrade_merge_rejects_incompatible_units_types_and_limits(self):
        obsolete = merge_compatible_setting_changes(
            {'generation': GenerationSettings().to_dict()},
            {'generation.base_height_mm': {'token': 'base-height-mm-v1', 'value': 8.0}})
        self.assertNotIn('generation.base_height_mm', obsolete.accepted_ids)
        self.assertNotIn('base_height_mm', obsolete.payload['generation'])
        stable_id = 'generation.layer_time_tolerance_s'
        for value, token, accepted in (
            (0.01, 'layer-time-tolerance-seconds-v1', True),
            (3.0, 'layer-time-tolerance-seconds-v1', True),
            (0.009, 'layer-time-tolerance-seconds-v1', False),
            (3.01, 'layer-time-tolerance-seconds-v1', False),
            (True, 'layer-time-tolerance-seconds-v1', False),
            ('0.5', 'layer-time-tolerance-seconds-v1', False),
            (500, 'layer-time-tolerance-milliseconds-v1', False),
        ):
            result = merge_compatible_setting_changes(
                {'generation': GenerationSettings(layer_time_tolerance_s=0.4).to_dict()},
                {stable_id: {'token': token, 'value': value}})
            self.assertEqual(stable_id in result.accepted_ids, accepted)
            self.assertEqual(result.payload['generation']['layer_time_tolerance_s'], value if accepted else 0.4)

    def test_target_time_migration_and_downgrade_limits(self):
        for version in (0, 11, 12):
            for value, expected in ((120, 30), (30, 30), (12, 12), (True, 9), (-1, 9), ('12', 9)):
                with self.subTest(version=version, value=value):
                    original = json.dumps({'settings_schema_version': version,
                        'generation': {'target_layer_time_s': value}}).encode()
                    self.path.write_bytes(original)
                    store = self.store()
                    settings, _ = store.load()
                    self.assertEqual(settings.target_layer_time_s, expected)
                    self.assertEqual(store.last_migration_backup.read_bytes(), original)
        stable_id = 'generation.target_layer_time_s'
        for value, token in ((31, 'duration-seconds-v1'), (0, 'duration-seconds-v1'),
                             (True, 'duration-seconds-v1'), ('9', 'duration-seconds-v1'),
                             (9000, 'duration-milliseconds-v1')):
            result = merge_compatible_setting_changes(
                {'generation': GenerationSettings().to_dict()},
                {stable_id: {'token': token, 'value': value}})
            self.assertNotIn(stable_id, result.accepted_ids)
            self.assertEqual(result.payload['generation']['target_layer_time_s'], 9)

    def test_ui_config_export_list_and_tolerance_boundary(self):
        window = MainWindow(user_settings_path=self.path, enable_update_check=False,
                            enable_startup_slicer_discovery=False)
        try:
            spin = window.layer_time_tolerance_spin
            self.assertEqual((spin.property('validationMinimum'), spin.property('validationMaximum'), spin.value()), (0.01, 3.0, 0.25))
            spin.setValue(0.37)
            self.assertEqual(window.collect_settings().layer_time_tolerance_s, 0.37)
            self.assertEqual(window._calibration_config().time_tolerance_s, 0.37)
            result = PreviewExportResult(output_mode=OutputMode.STL, run_directory=self.path.parent,
                output_path=self.path.parent/'tower.stl', report_path=self.path, user_report_path=self.path,
                calibrated=True, slicer_optimized=True, minimum_verified_layer_time_s=10.2,
                source_sha256='source', output_sha256='output', target_layer_time_s=10,
                calibration_time_tolerance_s=0.2, project_path=self.path.parent/'project.3mf')
            with patch.object(window, '_show_internal_dialog_without_flash'):
                for supports, infill in ((False, False), (True, False), (False, True), (True, True)):
                    window.full_infill_checkbox.setChecked(not infill)
                    exported = replace(result, supports_simulated=supports, full_tower_infill_simulated=infill)
                    window._show_export_success_dialog(exported)
                    text = window.export_success_simulation_label.text()
                    self.assertEqual('Aktivierte Stützen wurden simuliert' in text, supports)
                    self.assertEqual('100%-Turmfüllung simuliert' in text, infill)
                    self.assertEqual(window.export_success_deviation_label.property('status'), 'within')
                    self.assertNotIn('\n', window.export_success_deviation_label.text())
                    window._show_export_success_dialog(replace(exported, project_path=None))
                    self.assertTrue(window.export_success_simulation_frame.isHidden())
        finally:
            window.close()


if __name__ == '__main__':
    unittest.main()
