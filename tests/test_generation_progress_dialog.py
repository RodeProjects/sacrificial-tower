from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("COOLING_TOWER_DISABLE_SLICER_DISCOVERY", "1")

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QDialog, QDoubleSpinBox, QSpinBox

from cooling_tower.config import SETTINGS_SCHEMA_VERSION
from cooling_tower.gui.generation_progress_dialog import (
    JointSliceSettingsDialog,
    TowerGenerationDialog,
)
from cooling_tower.gui.main_window import MainWindow
from cooling_tower.gui.settings_store import UserSettingsStore
from gui_lifecycle import dispose_test_widget


class GenerationProgressDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.app.processEvents()

    def prepared_window(self):
        window = MainWindow(user_settings_path=self.root / "generation-settings.json",
            enable_update_check=False, enable_startup_slicer_discovery=False)
        self.addCleanup(dispose_test_widget, window)
        window.show()
        window.workflow.set_slicer_step_visible(True)
        window.workflow.source_validation_succeeded("STL", analysis_complete=True)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        self.app.processEvents()
        return window

    def test_image_progress_and_best_timing_are_presented(self) -> None:
        dialog = TowerGenerationDialog(
            PROJECT_ROOT / "src/cooling_tower/gui/assets/tower_gen_finished.webp"
        )
        dialog.setWindowState(Qt.WindowState.WindowMaximized)
        dialog.begin(9.0, 0.25, 0, 10)
        self.app.processEvents()
        self.assertFalse(dialog.isMaximized())
        self.assertEqual(dialog.width(), 610)
        self.assertEqual(
            dialog.target_value.text(),
            "9.00 s (± 0.25 s Toleranz)",
        )
        self.assertEqual(
            dialog.best_minimum_value.text(),
            "Noch kein gemeinsamer Slice abgeschlossen.",
        )
        self.assertIn(
            "schrittweise an Ihre Zielzeit angeglichen",
            dialog.explanation_label.text(),
        )
        self.assertIn(
            "Die ersten drei gemeinsamen Slices sind Pflicht. "
            "Danach können Sie das bisher beste Ergebnis übernehmen und anschließend "
            "exportieren",
            dialog.explanation_label.text(),
        )
        self.assertFalse(hasattr(dialog, "requirements_frame"))
        self.assertFalse(hasattr(dialog, "best_frame"))
        self.assertEqual(
            dialog.best_title_label.objectName(),
            "towerGenerationSummaryLabel",
        )
        self.assertEqual(
            dialog.best_values_layout.spacing(),
            dialog.best_minimum_value.fontMetrics().horizontalAdvance(" "),
        )
        self.assertEqual(dialog.image_progress.size().width(), 225)
        self.assertLess(
            dialog.layout().indexOf(dialog.image_progress),
            dialog.layout().indexOf(dialog.counter_label),
        )
        self.assertIn("0 von 10", dialog.counter_label.text())
        self.assertFalse(dialog.accept_button.isEnabled())
        self.assertTrue(dialog.accept_button.isHidden())

        iteration = SimpleNamespace(
            evaluation=SimpleNamespace(
                layer_timings=(
                    SimpleNamespace(combined_layer_time_s=8.95),
                    SimpleNamespace(combined_layer_time_s=9.20),
                )
            )
        )
        dialog.complete_slice(2, 10, iteration, 9.0)
        self.assertTrue(dialog.accept_button.isHidden())
        dialog.complete_slice(3, 10, iteration, 9.0)
        self.assertTrue(dialog.accept_button.isEnabled())
        self.assertFalse(dialog.accept_button.isHidden())
        self.assertEqual(dialog.best_minimum_value.text(), "8.95 s")
        self.assertEqual(dialog.best_deviation_value.text(), "(−0.05 s)")
        self.assertEqual(
            dialog.best_deviation_value.property("resultState"),
            "within",
        )
        self.assertIn("3 von 10", dialog.counter_label.text())

        dialog.set_slice_progress(0.58)
        self.assertGreaterEqual(
            dialog.image_progress._fill_animation.duration(),
            300,
        )
        QTest.qWait(420)
        self.assertAlmostEqual(dialog.image_progress._fill, 0.58, places=2)

        dialog.mark_finished(
            paused=True,
            can_continue=True,
            stop_reason="Testgrund für den vorzeitigen Abschluss.",
        )
        self.assertFalse(dialog.continue_button.isHidden())
        self.assertFalse(dialog.stop_reason_label.isHidden())
        self.assertEqual(
            dialog.stop_reason_label.property("resultState"),
            "within",
        )
        self.assertEqual(dialog.accept_button.text(), "Kühlturm exportieren")
        exported: list[bool] = []
        dialog.export_requested.connect(lambda: exported.append(True))
        dialog.accept_button.click()
        self.assertEqual(exported, [True])
        dialog.show_error("Slicer-Testfehler")
        self.assertTrue(dialog.continue_button.isHidden())
        self.assertIn("Slicer-Testfehler", dialog.error_label.text())
        dialog.close()

    def test_stop_reason_uses_warning_state_outside_tolerance(self) -> None:
        dialog = TowerGenerationDialog(
            PROJECT_ROOT / "src/cooling_tower/gui/assets/tower_gen_finished.webp"
        )
        dialog.begin(9.0, 0.25, 0, 10)
        iteration = SimpleNamespace(
            evaluation=SimpleNamespace(
                layer_timings=(
                    SimpleNamespace(combined_layer_time_s=8.60),
                )
            )
        )
        dialog.complete_slice(5, 10, iteration, 9.0)
        dialog.mark_finished(
            paused=False,
            can_continue=False,
            stop_reason="Die Angleichung wurde wegen Stagnation beendet.",
        )
        self.assertEqual(
            dialog.best_deviation_value.property("resultState"),
            "outside",
        )
        self.assertEqual(
            dialog.stop_reason_label.property("resultState"),
            "outside",
        )
        dialog.close()

    def test_slice_budgets_are_bounded_and_apply_with_individual_resets(self):
        window = self.prepared_window()
        for name, minimum, maximum, value in (
            ("maximum_separate_slices", 1, 15, 9),
            ("maximum_joint_slices", 5, 20, 17),
        ):
            setting = window.slice_budget_settings[name]
            self.assertTrue(window.geometry_group.isAncestorOf(setting))
            self.assertTrue(setting.isVisible())
            self.assertEqual((setting.editor.minimum(), setting.editor.maximum()), (minimum, maximum))
            setting.editor.setValue(value)
            self.assertEqual(getattr(window, name), value)
            self.assertTrue(setting.reset_button.isEnabled())
            self.assertEqual(setting.reset_button.objectName(), "settingResetButton")
            self.assertEqual(setting.reset_button.text(), "↺")
            self.assertEqual((setting.reset_button.width(), setting.reset_button.height()), (36, 36))
            setting.reset_button.click()
            self.assertEqual(getattr(window, name), getattr(window, "default_"+name))
            self.assertFalse(setting.reset_button.isEnabled())
        self.assertIn("±0,09 s", window.slice_budget_settings["maximum_joint_slices"].info_button.toolTip())
        self.assertEqual(window._calibration_config().maximum_iterations,
            window.maximum_separate_slices+window.maximum_joint_slices)

    def test_general_settings_only_offer_export_folders_before_preparation(self):
        dialog = JointSliceSettingsDialog(output_root="custom")
        self.addCleanup(dispose_test_widget, dialog)
        dialog.show()
        self.app.processEvents()
        self.assertFalse(dialog.findChildren(QSpinBox))
        self.assertFalse(dialog.findChildren(QDoubleSpinBox))
        for edit in dialog.export_root_edits.values():
            self.assertTrue(edit.isEnabled())
        self.assertTrue(dialog.general_reset_button.isEnabled())
        self.assertIsNot(dialog.focusWidget(), dialog.output_root_edit)
        self.assertFalse(dialog.output_root_edit.hasSelectedText())

    def test_general_settings_reset_only_changes_dialog_values_until_applied(self):
        dialog = JointSliceSettingsDialog(output_root="custom", default_output_root="default")
        self.addCleanup(dispose_test_widget, dialog)
        self.assertTrue(dialog.general_reset_button.isEnabled())
        footer_layout = dialog.general_reset_button.parentWidget().layout()
        self.assertEqual(footer_layout.itemAt(0).widget(), dialog.general_reset_button)
        applied = QSignalSpy(dialog.export_roots_applied)
        dialog.general_reset_button.click()
        self.assertEqual(dialog.output_root_edit.text(), "default")
        self.assertFalse(dialog.general_reset_button.isEnabled())
        self.assertEqual(applied.count(), 0)
        dialog.output_root_edit.setText("other")
        self.assertTrue(dialog.general_reset_button.isEnabled())
        dialog.reject()
        self.assertEqual(applied.count(), 0)

    def test_generation_settings_reset_with_tower_settings_and_preserve_export_folders(self):
        window = self.prepared_window()
        window.layer_time_tolerance_spin.setValue(0.6)
        window.local_window_spin.setValue(31)
        window.slice_budget_settings["maximum_separate_slices"].editor.setValue(9)
        window.slice_budget_settings["maximum_joint_slices"].editor.setValue(17)
        exports = dict(window.export_roots)
        self.assertTrue(window._has_non_default_settings())
        window.reset_defaults()
        self.assertEqual(window.layer_time_tolerance_spin.value(), 0.25)
        self.assertEqual(window.local_window_spin.value(), 51)
        self.assertEqual(window.maximum_separate_slices, 6)
        self.assertEqual(window.maximum_joint_slices, 12)
        self.assertEqual(window.export_roots, exports)
        window._save_user_settings()
        saved, data = window.settings_store.load()
        self.assertEqual(saved.layer_time_tolerance_s, 0.25)
        self.assertEqual(saved.local_reference_window, 51)
        self.assertEqual(data["maximum_separate_slices"], 6)
        self.assertEqual(data["maximum_joint_slices"], 12)

    def test_generation_panel_is_embedded_and_keeps_preview_accessible(self) -> None:
        window = MainWindow(user_settings_path=self.root / "settings.json", enable_update_check=False, enable_startup_slicer_discovery=False)
        self.addCleanup(dispose_test_widget, window)
        panel = window.joint_generation_dialog
        panel.begin(12.0, 0.25, 0, 15)
        self.assertFalse(panel.isWindow())
        self.assertTrue(window.prediction_frame.isAncestorOf(panel))
        self.assertLess(panel.image_progress.width(), 120)
        panel.set_achieved(12.04)
        panel.mark_finished(paused=True, can_continue=True)
        self.assertEqual(panel.best_deviation_value.text(), "+0.04 s")
        self.assertEqual(panel.title_label.text(), "Generierung gestoppt")
        self.assertFalse(panel.continue_button.isHidden())

    def test_schema_13_migrates_joint_slice_default(self) -> None:
        user_path = self.root / "settings.json"
        user_path.write_text(
            json.dumps(
                {
                    "settings_schema_version": 13,
                    "generation": {"target_layer_time_s": 9.0},
                }
            ),
            encoding="utf-8",
        )
        store = UserSettingsStore(
            user_path,
            PROJECT_ROOT / "config/default_settings.json",
        )
        _settings, state = store.load()
        self.assertEqual(state["settings_schema_version"], SETTINGS_SCHEMA_VERSION)
        self.assertEqual(state["maximum_joint_slices"], 10)
        self.assertEqual(state["maximum_separate_slices"], 6)
        migrated = json.loads(user_path.read_text(encoding="utf-8"))
        self.assertEqual(migrated["settings_schema_version"], SETTINGS_SCHEMA_VERSION)
        self.assertIsNotNone(store.last_migration_backup)

    def test_current_joint_slice_default_and_fallback_are_twelve(self) -> None:
        store = UserSettingsStore(
            self.root / "new-settings.json",
            PROJECT_ROOT / "config/default_settings.json",
        )
        self.assertEqual(store.load_default_maximum_joint_slices(), 12)
        self.assertEqual(store.load_default_maximum_separate_slices(), 6)
        self.assertEqual(
            store._default_payload(store.load_defaults())["maximum_joint_slices"],
            12,
        )
        missing_defaults = UserSettingsStore(
            self.root / "other-settings.json",
            self.root / "missing-defaults.json",
        )
        self.assertEqual(missing_defaults.load_default_maximum_joint_slices(), 12)
        self.assertEqual(missing_defaults.load_default_maximum_separate_slices(), 6)

    def test_schema_20_migrates_support_option_and_clamps_old_budgets(self) -> None:
        for old_schema in (18, 19):
            with self.subTest(old_schema=old_schema):
                path = self.root / f'settings-{old_schema}.json'
                original = json.dumps({
                    'settings_schema_version': old_schema,
                    'generation': {'target_layer_time_s': 9.0},
                    'maximum_joint_slices': 25,
                    'maximum_separate_slices': 25,
                }).encode()
                path.write_bytes(original)
                store = UserSettingsStore(path, PROJECT_ROOT / 'config/default_settings.json')
                settings, state = store.load()
                self.assertFalse(settings.simulate_tower_without_supports)
                self.assertEqual(settings.target_layer_time_s, 9.0)
                self.assertEqual(state['maximum_joint_slices'], 12)
                self.assertEqual(state['maximum_separate_slices'], 6)
                self.assertEqual(json.loads(path.read_text())['settings_schema_version'], SETTINGS_SCHEMA_VERSION)
                self.assertEqual(store.last_migration_backup.read_bytes(), original)

    def test_schema_21_limits_saved_manual_base_width_and_preserves_backup(self) -> None:
        for old_schema, width, expected in ((20, 120.0, 80.0), (8, 90.0, 80.0), (20, 60.0, 60.0)):
            with self.subTest(old_schema=old_schema, width=width):
                path = self.root / f"base-{old_schema}-{width}.json"
                original = json.dumps({
                    "settings_schema_version": old_schema,
                    "generation": {"manual_base_width_mm": width},
                }).encode("utf-8")
                path.write_bytes(original)
                store = UserSettingsStore(
                    path, PROJECT_ROOT / "config/default_settings.json"
                )
                settings, payload = store.load()
                self.assertEqual(settings.manual_base_width_mm, expected)
                self.assertEqual(payload["generation"]["manual_base_width_mm"], expected)
                self.assertEqual(json.loads(path.read_text())["settings_schema_version"], SETTINGS_SCHEMA_VERSION)
                self.assertEqual(store.last_migration_backup.read_bytes(), original)

    def test_target_time_default_is_nine_and_saved_values_are_preserved(self) -> None:
        path = self.root / "target-time.json"
        store = UserSettingsStore(path, PROJECT_ROOT / "config/default_settings.json")
        self.assertEqual(store.load_defaults().target_layer_time_s, 9.0)
        self.assertEqual(store.load()[0].target_layer_time_s, 9.0)
        for generation, expected in (({}, 9.0), ({"target_layer_time_s": 10.0}, 10.0),
                                     ({"target_layer_time_s": 17.5}, 17.5)):
            with self.subTest(generation=generation):
                path.write_text(json.dumps({
                    "settings_schema_version": SETTINGS_SCHEMA_VERSION,
                    "generation": generation,
                }), encoding="utf-8")
                self.assertEqual(store.load()[0].target_layer_time_s, expected)

    def test_local_window_individual_reset_and_export_dialog_do_not_change_other_settings(self):
        window = self.prepared_window()
        window.local_window_spin.setValue(31)
        window.layer_time_tolerance_spin.setValue(0.6)
        window._setting_widgets["local_reference_window"].reset_button.click()
        self.assertEqual(window.local_window_spin.value(), 51)
        self.assertEqual(window.layer_time_tolerance_spin.value(), 0.6)
        window.show_joint_slice_settings()
        dialog = window._joint_slice_settings_dialog
        dialog.general_reset_button.click()
        dialog.accept()
        self.assertEqual(window.layer_time_tolerance_spin.value(), 0.6)

    def test_main_menu_uses_persisted_joint_slice_budget(self) -> None:
        user_path = self.root / "settings.json"
        user_path.write_text(
            json.dumps(
                {
                    "settings_schema_version": SETTINGS_SCHEMA_VERSION,
                    "generation": {},
                    "maximum_joint_slices": 17,
                    "maximum_separate_slices": 8,
                }
            ),
            encoding="utf-8",
        )
        window = MainWindow(
            user_settings_path=user_path,
            enable_update_check=False,
            enable_startup_slicer_discovery=False,
        )
        self.addCleanup(dispose_test_widget, window)
        self.assertEqual(window.maximum_joint_slices, 17)
        self.assertEqual(window.maximum_separate_slices, 8)
        self.assertEqual(window._calibration_config().maximum_joint_slices, 17)
        self.assertEqual(window._calibration_config().maximum_iterations, 25)
        self.assertEqual(window.slice_budget_settings["maximum_joint_slices"].editor.value(), 17)
        self.assertEqual(window.slice_budget_settings["maximum_separate_slices"].editor.value(), 8)
        window.slice_budget_settings["maximum_joint_slices"].editor.setValue(14)
        self.assertEqual(window.maximum_joint_slices, 14)
        self.assertEqual(window.settings_store.load()[1]["maximum_joint_slices"], 14)
        self.assertEqual(
            window.joint_slice_settings_action.text(),
            "Allgemeine Einstellungen",
        )
        window.close()

    def test_joint_export_starts_directly_from_main(self) -> None:
        window = MainWindow(user_settings_path=self.root / "settings.json", enable_update_check=False, enable_startup_slicer_discovery=False)
        self.addCleanup(dispose_test_widget, window)
        panel = window.joint_generation_dialog
        panel.begin(9.0, 0.25, 1, 10)
        panel.mark_finished(paused=True, can_continue=True)
        window._joint_generation_paused = True
        window._update_responsive_action_labels()
        self.assertEqual(window.export_button.text(), "Kühlturm exportieren")
        with patch.object(window, "start_export") as start_export:
            window._on_main_export_clicked()
            start_export.assert_called_once_with()
        self.assertTrue(panel.accept_button.isHidden())

    def test_isolated_slice_progress_shows_overall_preparation_progress(self) -> None:
        window = MainWindow(
            user_settings_path=self.root / "settings.json",
            enable_update_check=False,
            enable_startup_slicer_discovery=False,
        )
        self.addCleanup(dispose_test_widget, window)
        window.show()
        window._on_preview_progress(
            window._preview_request_id,
            20,
            "Getrennter Slice 2/6 wird vorbereitet …",
        )
        self.app.processEvents()

        self.assertTrue(window.progress_bar.isHidden())
        self.assertFalse(window.isolated_progress_widget.isHidden())
        self.assertTrue(window.footer_status_widget.isHidden())
        self.assertEqual(
            window.isolated_progress_title_label.text(),
            "Turmgenerierung wird vorbereitet...",
        )
        self.assertEqual(window.footer_action_layout.count(), 3)
        self.assertEqual(
            window.isolated_progress_bar.objectName(),
            "preparationProgressBar",
        )
        self.assertEqual(window.isolated_progress_bar.value(), 17)
        self.assertIn(
            "Getrennter Slice 2/6",
            window.isolated_progress_detail_label.text(),
        )
        self.assertGreater(
            window.isolated_progress_detail_label.mapTo(
                window.isolated_progress_widget,
                QPoint(0, 0),
            ).y(),
            window.isolated_progress_bar.mapTo(
                window.isolated_progress_widget,
                QPoint(0, 0),
            ).y(),
        )
        window._on_preview_progress(
            window._preview_request_id,
            25,
            "Slicer und Profil werden für die Kalibrierung vorbereitet …",
        )
        self.app.processEvents()
        self.assertEqual(window.isolated_progress_bar.value(), 17)
        self.assertTrue(window.footer_status_widget.isHidden())

        window._on_preview_progress(
            window._preview_request_id,
            30,
            "Slicer-Ergebnis 2/21 wird ausgewertet …",
        )
        self.assertEqual(window.isolated_progress_bar.value(), 33)
        window._on_preview_progress(
            window._preview_request_id,
            40,
            "Getrennter Slice 3/6 wird ausgeführt …",
        )
        self.assertEqual(window.isolated_progress_bar.value(), 33)
        window._on_preview_progress(
            window._preview_request_id,
            50,
            "Slicer-Ergebnis 6/21 wird ausgewertet …",
        )
        self.assertEqual(window.isolated_progress_bar.value(), 100)

        window._on_preview_progress(
            window._preview_request_id,
            50,
            "Gemeinsamer Slice 1/10 wird vorbereitet …",
        )
        self.assertFalse(window.isolated_progress_widget.isHidden())
        self.assertTrue(window.footer_status_widget.isHidden())

        window._on_joint_phase_started(
            window._preview_request_id,
            0,
            window.maximum_joint_slices,
        )
        self.assertFalse(window.isolated_progress_widget.isHidden())
        fade_in_done = QSignalSpy(window._generation_phase_fade_in.finished)
        self.assertTrue(fade_in_done.wait(1500))
        self.assertTrue(window.isolated_progress_widget.isHidden())
        self.assertFalse(window.footer_status_widget.isHidden())
        self.assertEqual(window.footer_action_layout.count(), 3)
        window.joint_generation_dialog.allow_programmatic_close()
        window.joint_generation_dialog.close()
        window.close()


if __name__ == "__main__":
    unittest.main()
