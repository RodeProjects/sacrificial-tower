from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("COOLING_TOWER_DISABLE_SLICER_DISCOVERY", "1")

from PySide6.QtGui import QFontDatabase, QValidator
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from cooling_tower.config import SETTINGS_SCHEMA_VERSION
from cooling_tower.gui.main_window import MainWindow
from cooling_tower.gui.settings_store import UserSettingsStore
from cooling_tower.models import GenerationSettings
from cooling_tower.preview.service import _tower_wireframe
from cooling_tower.settings_compatibility import SETTING_COMPATIBILITY_CATALOG, merge_compatible_setting_changes
from cooling_tower.tower.mesh_generator import configured_mesh_segments
from cooling_tower.tower.solid_profile import validate_solid_settings
from gui_lifecycle import dispose_test_widget


class CircleSegmentsPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "settings.json"

    def store(self):
        return UserSettingsStore(self.path, ROOT / "config/default_settings.json")

    def save(self, store, settings):
        return store.save(settings, output_root="output", window_width=1400, window_height=900)

    def test_direct_and_multistep_migrations_preserve_values_and_original_backup(self):
        for version in (21, 22):
            with self.subTest(version=version):
                original = json.dumps({"settings_schema_version": version,
                                       "generation": {"target_layer_time_s": 13.0}}).encode()
                self.path.write_bytes(original)
                store = self.store()
                settings, state = store.load()
                self.assertEqual(state["settings_schema_version"], SETTINGS_SCHEMA_VERSION)
                self.assertEqual(settings.target_layer_time_s, 13)
                self.assertTrue(settings.automatic_circle_segments)
                self.assertEqual(settings.circle_segments, 32)
                self.assertEqual(store.last_migration_backup.read_bytes(), original)

    def test_manual_limits_roundtrip_without_losing_automatic_preference(self):
        for count in (4, 64, 256):
            with self.subTest(count=count):
                settings = GenerationSettings(automatic_circle_segments=False, circle_segments=count)
                store = self.store()
                store.load()
                self.save(store, settings)
                loaded, _ = self.store().load()
                self.assertEqual(loaded, settings)

    def test_invalid_current_values_fall_back_to_safe_defaults(self):
        for count in (3, 257, True, "64", 64.5):
            with self.subTest(count=count):
                self.path.write_text(json.dumps({"settings_schema_version": SETTINGS_SCHEMA_VERSION,
                    "generation": {"circle_segments": count, "automatic_circle_segments": "false"}}))
                settings, _ = self.store().load()
                self.assertEqual(settings.circle_segments, 32)
                self.assertTrue(settings.automatic_circle_segments)

    def test_failed_atomic_migration_retains_original_and_can_recover(self):
        original = json.dumps({"settings_schema_version": 22, "generation": {}}).encode()
        self.path.write_bytes(original)
        with patch("cooling_tower.persistence.versioned_json.os.replace", side_effect=OSError("replace failed")):
            store = self.store()
            store.load()
            self.assertEqual(self.path.read_bytes(), original)
            self.assertTrue(store.last_load_warning)
        settings, _ = self.store().load()
        self.assertTrue(settings.automatic_circle_segments)
        self.assertEqual(json.loads(self.path.read_text())["settings_schema_version"], SETTINGS_SCHEMA_VERSION)

    def test_downgrade_checks_types_units_and_both_bounds(self):
        base = {"generation": GenerationSettings(circle_segments=64).to_dict()}
        stable_id = "generation.circle_segments"
        for count, token in ((3, "circle-segments-count-v1"), (257, "circle-segments-count-v1"),
                             (True, "circle-segments-count-v1"), ("32", "circle-segments-count-v1"),
                             (32, "circle-segments-degrees-v1")):
            with self.subTest(count=count, token=token):
                result = merge_compatible_setting_changes(base, {stable_id: {"token": token, "value": count}})
                self.assertEqual(result.payload["generation"]["circle_segments"], 64)
                self.assertIn(stable_id, result.rejected_ids)
        result = merge_compatible_setting_changes(base, {stable_id: {
            "token": SETTING_COMPATIBILITY_CATALOG[stable_id], "value": 256}})
        self.assertEqual(result.payload["generation"]["circle_segments"], 256)

    def test_future_file_stays_intact_when_manual_count_is_saved(self):
        payload = {"settings_schema_version": SETTINGS_SCHEMA_VERSION + 1,
                   "generation": GenerationSettings(circle_segments=64).to_dict(),
                   "setting_compatibility": dict(SETTING_COMPATIBILITY_CATALOG)}
        original = json.dumps(payload).encode()
        self.path.write_bytes(original)
        store = self.store()
        store.load()
        journal = self.save(store, GenerationSettings(automatic_circle_segments=False, circle_segments=96))
        self.assertEqual(self.path.read_bytes(), original)
        changes = json.loads(journal.read_text())["changes"]
        self.assertEqual(changes["generation.circle_segments"]["value"], 96)


class CircleSegmentsGeometryTests(unittest.TestCase):
    def test_support_export_allows_only_the_declared_technical_segment_values(self):
        from cooling_tower.support_privacy import SETTING_KEYS, sanitize_technical

        self.assertEqual(sanitize_technical({
            "automatic_circle_segments": True, "circle_segments": 64,
            "unknown_private_field": "private value",
        }, allowed_keys=SETTING_KEYS), {
            "automatic_circle_segments": True, "circle_segments": 64,
        })

    def test_configured_count_matches_preview_geometry(self):
        profile = SimpleNamespace(points=(SimpleNamespace(outer_radius_mm=22, z_mm=.2),
                                          SimpleNamespace(outer_radius_mm=20, z_mm=.4)))
        placement = SimpleNamespace(center_x_mm=0, center_y_mm=0)
        self.assertEqual(configured_mesh_segments(profile, GenerationSettings()), 44)
        for count in (4, 64, 256):
            settings = GenerationSettings(automatic_circle_segments=False, circle_segments=count)
            self.assertEqual(configured_mesh_segments(profile, settings), count)
            lines = _tower_wireframe(profile, placement, settings)
            self.assertEqual(len(lines), 2 * count + len(range(0, count, 4)))

    def test_invalid_manual_counts_are_rejected_before_generation(self):
        for count in (3, 257, True, 4.5, "32"):
            with self.subTest(count=count), self.assertRaises(ValueError):
                validate_solid_settings(GenerationSettings(automatic_circle_segments=False, circle_segments=count))


class CircleSegmentsUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.fonts = [QFontDatabase.addApplicationFont(f"C:/Windows/Fonts/{name}")
                     for name in ("segoeui.ttf", "seguisym.ttf")]

    @classmethod
    def tearDownClass(cls):
        for font in cls.fonts:
            if font >= 0:
                QFontDatabase.removeApplicationFont(font)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.window = MainWindow(user_settings_path=Path(self.temp.name)/"settings.json",
                                 enable_update_check=False, enable_startup_slicer_discovery=False)
        self.addCleanup(dispose_test_widget, self.window)

    def test_auto_display_retains_manual_count_and_reset_restores_default(self):
        w = self.window
        self.assertTrue(w.automatic_circle_segments_checkbox.isChecked())
        self.assertFalse(w.circle_segments_spin.isEnabled())
        self.assertEqual(w.circle_segments_spin.text(), "auto")
        w.automatic_circle_segments_checkbox.setChecked(False)
        self.assertTrue(w.circle_segments_spin.isEnabled())
        w.circle_segments_spin.setValue(64)
        w.automatic_circle_segments_checkbox.setChecked(True)
        w.circle_segments_setting.set_accepted_count(43)
        self.assertEqual(w.circle_segments_spin.text(), "43")
        self.assertEqual(w.collect_settings().circle_segments, 64)
        self.assertNotIn("circle_segments", w._incomplete_setting_names)
        w.automatic_circle_segments_checkbox.setChecked(False)
        self.assertEqual(w.circle_segments_spin.text(), "64")
        w.circle_segments_setting.reset_button.click()
        self.assertTrue(w.collect_settings().automatic_circle_segments)
        self.assertEqual(w.collect_settings().circle_segments, 32)
        w.circle_segments_setting.set_accepted_count(None)
        self.assertEqual(w.circle_segments_spin.text(), "auto")

    def test_loaded_manual_count_and_global_reset(self):
        w = self.window
        w.apply_settings(GenerationSettings(automatic_circle_segments=False, circle_segments=256))
        self.assertEqual(w.collect_settings().circle_segments, 256)
        self.assertTrue(w.circle_segments_spin.isEnabled())
        w.reset_defaults()
        self.assertTrue(w.collect_settings().automatic_circle_segments)
        self.assertEqual(w.collect_settings().circle_segments, 32)

    def test_typing_and_pasting_reject_out_of_range_values_without_losing_valid_prefixes(self):
        w = self.window
        w.automatic_circle_segments_checkbox.setChecked(False)
        spin = w.circle_segments_spin
        edit = spin.lineEdit()
        for receiver in (edit, spin):
            for value in (4, 9, 12, 20, 32, 100, 128, 200, 256):
                with self.subTest(receiver=type(receiver).__name__, valid=value):
                    QTest.keyClick(receiver, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
                    QTest.keyClicks(receiver, str(value))
                    self.assertEqual(spin.value(), value)
                    self.assertEqual(edit.text(), str(value))
                    self.assertTrue(spin.hasAcceptableInput())
        for text in ("0", "1", "2", "3", "-1", "257", "abc", "4.5"):
            with self.subTest(rejected=text):
                spin.setValue(64)
                QTest.keyClick(edit, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
                self.assertEqual(spin.validate(text, len(text))[0], QValidator.State.Invalid)
                edit.insert(text)
                self.assertEqual(edit.text(), "64")
                self.assertEqual(spin.value(), 64)
        for text in ("0", "1", "2", "3"):
            with self.subTest(typed=text):
                QTest.keyClick(edit, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
                QTest.keyClicks(edit, text)
                self.assertEqual(edit.text(), "64")
                self.assertEqual(spin.value(), 64)

    def test_injected_invalid_text_keeps_range_errors_and_recovers_with_spin_buttons(self):
        w = self.window
        w.workflow.set_slicer_step_visible(True)
        w.workflow.source_validation_succeeded("STL", analysis_complete=True)
        w.workflow.slicer_succeeded("Testslicer")
        w.workflow.complete_preparation()
        w.automatic_generation_card.click()
        w.automatic_circle_segments_checkbox.setChecked(False)
        spin = w.circle_segments_spin
        row = w.circle_segments_setting
        for text in ("3", "257", "-1", "abc", "4.5"):
            with self.subTest(injected=text):
                spin.lineEdit().setText(text)
                self.assertFalse(w.validate_form())
                self.assertFalse(w._phase17_static_valid)
                self.assertIn("circle_segments", w._incomplete_setting_names)
                self.assertTrue(spin.property("invalid"))
                self.assertIn("Erlaubt sind ganze Zahlen von 4 bis 256.", row.message_label.text())
                spin.stepUp()
                self.assertTrue(spin.hasAcceptableInput())
                self.assertNotIn("circle_segments", w._incomplete_setting_names)
                self.assertFalse(spin.property("invalid"))
        for text in ("", "0"):
            with self.subTest(empty=text):
                spin.lineEdit().setText(text)
                self.assertFalse(w.validate_form())
                self.assertIn("Das Feld darf nicht leer sein!", row.message_label.text())
                spin.setValue(32)
                row.refresh_input_state()
                self.assertTrue(spin.hasAcceptableInput())

    def test_setting_sublines_share_spacing_and_nine_point_type(self):
        w = self.window
        w.resize(1422, 1000)
        w.show()
        w.workflow.set_slicer_step_visible(True)
        w.workflow.source_validation_succeeded("STL", analysis_complete=True)
        w.workflow.slicer_succeeded("Testslicer")
        w.workflow.complete_preparation()
        w.automatic_generation_card.click()
        for _ in range(5):
            self.app.processEvents()
        controls = (w.profile_angle_limit, w.circle_segments_setting.automatic_control)
        offsets = []
        for control in controls:
            control._position()
            label = control.row.label
            text_bottom = (label.mapToGlobal(QPoint()).y()
                           + (label.height() + label.fontMetrics().height()) // 2)
            offsets.append(control.mapToGlobal(QPoint()).y() - text_bottom)
        self.assertEqual(offsets, [0, 0])
        for label in (w.profile_angle_limit.prefix, w.profile_angle_limit.threshold_hint,
                      w.profile_angle_limit.suffix, controls[1].text_label):
            self.assertEqual(label.font().pointSizeF(), 9)

    def test_footer_right_buttons_keep_original_height_and_left_messages_stay_at_top(self):
        w = self.window
        w.resize(1422, 1000)
        w.show()
        w.workflow.set_slicer_step_visible(True)
        w.workflow.source_validation_succeeded("STL", analysis_complete=True)
        w.workflow.slicer_succeeded("Testslicer")
        w.workflow.complete_preparation()
        w.automatic_generation_card.click()
        w._set_main_status("Vorschau ist aktuell", icon="✓", state="success")
        w.result_label.clear()
        w.action_availability_widget.hide()
        w._fit_footer_height()
        for _ in range(4):
            self.app.processEvents()
        w._fit_footer_height()
        self.assertTrue(w.result_label.isHidden())
        self.assertLessEqual(w.footer.height(), 85)
        for button in (w.open_output_button, w.open_stl_button, w.open_run_button,
                       w.preview_button, w.export_button):
            with self.subTest(button=button.objectName()):
                self.assertEqual(button.sizeHint().height(), 50)
        self.assertEqual(w.reset_button.height(), 32)
        self.assertEqual(w.tower_reset_button.height(), 32)
        status_top = w.status_label.mapTo(w.footer, QPoint()).y()
        message_height = w.footer_messages_scroll.height()
        compact_height = w.footer.height()
        w.preview_button.setFixedHeight(110)
        w._fit_footer_height()
        self.app.processEvents()
        w._fit_footer_height()
        self.assertGreater(w.footer.height(), compact_height)
        self.assertEqual(w.status_label.mapTo(w.footer, QPoint()).y(), status_top)
        self.assertEqual(w.footer_messages_scroll.height(), message_height)
        w.preview_button.setFixedHeight(50)
        w._fit_footer_height()
        self.app.processEvents()
        w._fit_footer_height()
        self.assertEqual(w.footer.height(), compact_height)
        for text in ("Ein längerer Status zur Darstellung mehrzeiliger Informationen. " * 9,
                     "Vorschau ist aktuell"):
            w._set_main_status(text, icon="✓", state="success")
            w._fit_footer_height()
            self.app.processEvents()
        self.assertLessEqual(w.footer.height(), 85)


if __name__ == "__main__":
    unittest.main()
