from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from PySide6.QtCore import QEvent, QObject, QThread, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QAbstractSpinBox,
    QStyle,
    QStyleOptionSpinBox,
    QWidget,
)

from cooling_tower.application import (
    MAIN_WINDOW_REVEAL_DELAY_MS,
    _show_main_window,
    show_startup_error,
)
from cooling_tower.config import SETTINGS_SCHEMA_VERSION
from cooling_tower.gui import MainWindow
from cooling_tower.gui.background_jobs import JobKind
from cooling_tower.gui.design_tokens import METRICS
from cooling_tower.gui.settings_store import UserSettingsStore
from cooling_tower.models import (
    FeasibilityIssue,
    GenerationSettings,
    ProfileFeasibilityAssessment,
)
from cooling_tower.services import (
    StlValidationCancelled,
    StlValidationService,
    assess_profile_feasibility,
    assess_tower_need,
)
from test_phase9 import SAMPLE_GCODE, make_snapshot


DEFAULTS_PATH = PROJECT_ROOT / "config" / "default_settings.json"


class _TopLevelShowRecorder(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.shown: list[tuple[str, str]] = []

    def eventFilter(self, watched, event) -> bool:  # type: ignore[no-untyped-def]
        if (
            event.type() == QEvent.Type.Show
            and isinstance(watched, QWidget)
            and watched.isWindow()
        ):
            self.shown.append(
                (watched.metaObject().className(), watched.objectName())
            )
        return False


class StartupWindowVisibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_constructor_does_not_flash_temporary_top_level_widgets(self) -> None:
        """Only run_application may expose the completed main window."""

        with tempfile.TemporaryDirectory() as temporary:
            recorder = _TopLevelShowRecorder()
            self.app.installEventFilter(recorder)
            window = None
            try:
                window = MainWindow(
                    user_settings_path=Path(temporary) / "user.json",
                    enable_update_check=False,
                )
            finally:
                self.app.removeEventFilter(recorder)
                if window is not None:
                    window.close()
                self.app.processEvents()

        self.assertEqual(recorder.shown, [])

    def test_saved_main_window_geometry_is_complete_before_show(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            settings_path = Path(temporary) / "user.json"
            available = self.app.primaryScreen().availableGeometry()
            target_x = available.left() + 20
            target_y = available.top() + 20

            first = MainWindow(
                user_settings_path=settings_path,
                enable_update_check=False,
            )
            first.resize(720, 640)
            first.move(target_x, target_y)
            first.show()
            self.app.processEvents()
            first.close()
            self.app.processEvents()

            saved = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["window"]["x"], target_x)
            self.assertEqual(saved["window"]["y"], target_y)

            restored = MainWindow(
                user_settings_path=settings_path,
                enable_update_check=False,
            )
            self.assertEqual(restored.width(), 720)
            self.assertEqual(restored.height(), 640)
            self.assertEqual(restored.x(), target_x)
            self.assertEqual(restored.y(), target_y)
            restored.show()
            self.app.processEvents()
            self.assertEqual(restored.x(), target_x)
            self.assertEqual(restored.y(), target_y)
            restored.close()

    def test_windows_startup_frame_remains_transparent_until_reveal(self) -> None:
        class WindowStub:
            def __init__(self) -> None:
                self.visible = False
                self.opacity_values: list[float] = []

            def setWindowOpacity(self, value: float) -> None:  # noqa: N802
                self.opacity_values.append(value)

            def show(self) -> None:
                self.visible = True

            def isVisible(self) -> bool:  # noqa: N802
                return self.visible

        window = WindowStub()
        with (
            patch("cooling_tower.application.sys.platform", "win32"),
            patch("cooling_tower.application.QTimer.singleShot") as schedule,
        ):
            _show_main_window(window)

        self.assertTrue(window.visible)
        self.assertEqual(window.opacity_values, [0.0])
        self.assertEqual(
            schedule.call_args.args[0],
            MAIN_WINDOW_REVEAL_DELAY_MS,
        )
        schedule.call_args.args[1]()
        self.assertEqual(window.opacity_values, [0.0, 1.0])


class SettingsSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.user_path = self.root / "user.json"
        self.store = UserSettingsStore(self.user_path, DEFAULTS_PATH)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_default_file_has_current_schema_version(self) -> None:
        payload = json.loads(DEFAULTS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            payload["settings_schema_version"],
            SETTINGS_SCHEMA_VERSION,
        )

    def test_legacy_flat_aliases_are_migrated(self) -> None:
        self.user_path.write_text(
            json.dumps(
                {
                    "minimum_radius_mm": 7.5,
                    "maximum_radius_mm": 42.0,
                    "expansion_angle_deg": 48.0,
                    "base_width_mm": 24.0,
                }
            ),
            encoding="utf-8",
        )
        settings, _ui = self.store.load()
        self.assertEqual(settings.minimum_outer_radius_mm, 7.5)
        self.assertEqual(settings.maximum_outer_radius_mm, 42.0)
        self.assertEqual(settings.maximum_expansion_angle_deg, 48.0)
        self.assertEqual(settings.manual_base_width_mm, 24.0)

    def test_unknown_legacy_keys_are_ignored(self) -> None:
        self.user_path.write_text(
            json.dumps({"unknown_future_key": 123, "target_layer_time_s": 8}),
            encoding="utf-8",
        )
        settings, _ui = self.store.load()
        self.assertEqual(settings.target_layer_time_s, 8)
        self.assertNotIn("unknown_future_key", settings.to_dict())

    def test_saved_settings_include_schema_version(self) -> None:
        self.store.save(
            GenerationSettings(),
            output_root=str(self.root / "output"),
            window_width=900,
            window_height=700,
            window_x=-320,
            window_y=45,
        )
        payload = json.loads(self.user_path.read_text(encoding="utf-8"))
        self.assertEqual(
            payload["settings_schema_version"],
            SETTINGS_SCHEMA_VERSION,
        )
        self.assertIn("generation", payload)
        self.assertEqual(
            payload["window"],
            {"width": 900, "height": 700, "x": -320, "y": 45},
        )

    def test_schema_4_migrates_directly_before_window_positions_are_saved(
        self,
    ) -> None:
        self.user_path.write_text(
            json.dumps(
                {
                    "settings_schema_version": 4,
                    "generation": {"target_layer_time_s": 73.0},
                    "window": {"width": 840, "height": 680},
                }
            ),
            encoding="utf-8",
        )
        original = self.user_path.read_bytes()

        settings, state = self.store.load()

        self.assertEqual(settings.target_layer_time_s, 30.0)
        self.assertEqual(
            state["settings_schema_version"],
            SETTINGS_SCHEMA_VERSION,
        )
        self.assertEqual(state["window"], {"width": 840, "height": 680})
        self.assertIsNotNone(self.store.last_migration_backup)
        self.assertEqual(self.store.last_migration_backup.read_bytes(), original)

    def test_relative_default_output_is_resolved_from_project(self) -> None:
        self.assertEqual(
            self.store.load_default_output_root(),
            (PROJECT_ROOT / "output").resolve(),
        )

    def test_migration_is_persisted_with_byte_exact_backup(self) -> None:
        self.user_path.write_text(
            json.dumps(
                {
                    "minimum_radius_mm": 7.5,
                    "slicer_iterations": 6,
                    "output_mode": "obsolete",
                }
            ),
            encoding="utf-8",
        )
        original = self.user_path.read_bytes()

        settings, state = self.store.load()

        self.assertEqual(settings.minimum_outer_radius_mm, 7.5)
        self.assertEqual(state["settings_schema_version"], SETTINGS_SCHEMA_VERSION)
        self.assertEqual(state["preview_iterations"], 8)
        self.assertNotIn("preview_quality", state)
        self.assertNotIn("output_mode", state)
        self.assertIsNotNone(self.store.last_migration_backup)
        self.assertEqual(
            self.store.last_migration_backup.read_bytes(),
            original,
        )
        persisted = json.loads(self.user_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted, state)

    def test_invalid_individual_value_falls_back_without_losing_others(self) -> None:
        self.user_path.write_text(
            json.dumps(
                {
                    "settings_schema_version": SETTINGS_SCHEMA_VERSION,
                    "generation": {
                        "target_layer_time_s": "invalid",
                        "layer_time_tolerance_s": 1.25,
                    },
                }
            ),
            encoding="utf-8",
        )

        settings, _state = self.store.load()

        self.assertEqual(
            settings.target_layer_time_s,
            GenerationSettings().target_layer_time_s,
        )
        self.assertEqual(settings.layer_time_tolerance_s, 1.25)
        self.assertIsNotNone(self.store.last_migration_backup)

    def test_future_schema_uses_separate_journal_and_preserves_original(self) -> None:
        self.user_path.write_text(
            json.dumps(
                {
                    "settings_schema_version": SETTINGS_SCHEMA_VERSION + 1,
                    "generation": {"target_layer_time_s": 99.0},
                }
            ),
            encoding="utf-8",
        )
        original = self.user_path.read_bytes()

        settings, state = self.store.load()

        self.assertEqual(settings, GenerationSettings())
        self.assertEqual(
            state["settings_schema_version"],
            SETTINGS_SCHEMA_VERSION,
        )
        self.assertIn("nicht überschrieben", self.store.last_load_warning)
        journal = self.store.save(
            settings,
            output_root="output",
            window_width=900,
            window_height=700,
        )
        self.assertTrue(journal.is_file())
        self.assertIn("downgrade-changes", journal.name)
        self.assertEqual(self.user_path.read_bytes(), original)

    def test_malformed_file_requires_explicit_recovery(self) -> None:
        original = b'{"settings_schema_version": '
        self.user_path.write_bytes(original)

        settings, state = self.store.load()

        self.assertEqual(settings, GenerationSettings())
        self.assertEqual(state, {})
        self.assertIsNotNone(self.store.last_load_warning)
        recovered = self.store.recover(
            settings,
            output_root="output",
            window_width=900,
            window_height=700,
        )
        self.assertEqual(recovered, self.user_path.resolve())
        backups = list(
            self.root.glob("user.json.schema-recovery.backup*")
        )
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)


class GuiCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "phase11.gcode"
        self.source.write_text(SAMPLE_GCODE, encoding="utf-8")
        self.window = MainWindow(user_settings_path=self.root / "user.json")
        self.window.resize(900, 900)
        self.window.show()
        self.app.processEvents()

    def tearDown(self) -> None:
        self.window.close()
        self.app.processEvents()
        self.temporary.cleanup()

    def wait_until(self, predicate, timeout_s: float = 5.0) -> None:
        deadline = time.monotonic() + timeout_s
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.app.processEvents()
        self.assertTrue(predicate(), "Zeitlimit beim Warten auf GUI-Zustand")

    def complete_source_step(self) -> None:
        self.window.workflow.set_slicer_step_visible(True)
        self.window.workflow.source_validation_succeeded(
            "referenz.stl geprüft",
            analysis_complete=True,
        )

    def test_future_settings_are_visible_and_survive_window_close(self) -> None:
        self.window.close()
        protected_path = self.root / "future-user.json"
        protected_path.write_text(
            json.dumps(
                {
                    "settings_schema_version": SETTINGS_SCHEMA_VERSION + 1,
                    "generation": {"target_layer_time_s": 99.0},
                }
            ),
            encoding="utf-8",
        )
        original = protected_path.read_bytes()
        self.window = MainWindow(user_settings_path=protected_path)
        self.window.show()
        self.app.processEvents()

        self.assertTrue(self.window.footer.isHidden())
        self.assertFalse(self.window.settings_load_notice_panel.isHidden())
        self.assertIn(
            "nicht überschrieben",
            self.window.settings_load_notice_label.text(),
        )
        self.complete_source_step()
        self.window.workflow.slicer_succeeded("Testslicer")
        self.window.workflow.complete_preparation()
        self.app.processEvents()
        self.assertFalse(self.window.footer.isHidden())
        self.assertTrue(self.window.settings_load_notice_panel.isVisible())
        self.window.close()
        self.app.processEvents()
        self.assertEqual(protected_path.read_bytes(), original)

    def feed_snapshot(
        self,
        layer_times: tuple[float, ...],
        *,
        layer_heights: tuple[float, ...] | None = None,
    ) -> None:
        snapshot = make_snapshot(
            self.source,
            layer_times,
            layer_heights=layer_heights,
        )
        self.window.current_gcode_path = self.source.resolve()
        self.window._adopt_common_analysis_snapshot(snapshot)

    @staticmethod
    def spin_subcontrol(editor, control):
        option = QStyleOptionSpinBox()
        editor.initStyleOption(option)
        return editor.style().subControlRect(
            QStyle.ComplexControl.CC_SpinBox,
            option,
            control,
            editor,
        )


class NumericSettingWidgetTests(GuiCase):
    def test_resets_are_disabled_at_defaults_and_enable_for_changes(self) -> None:
        for group in (
            self.window.geometry_group,
            self.window.stability_group,
            self.window.geometry_settings_group,
        ):
            group.setChecked(True)
        self.assertEqual(len(self.window._setting_widgets), 8)
        for setting in self.window._setting_widgets.values():
            self.assertFalse(setting.reset_button.isEnabled())
            self.assertIn("Standardwert", setting.reset_button.toolTip())
        self.window.target_time_spin.setValue(77)
        self.app.processEvents()
        self.assertTrue(
            self.window._setting_widgets[
                "target_layer_time_s"
            ].reset_button.isEnabled()
        )
        self.assertFalse(
            self.window._setting_widgets[
                "maximum_outer_diameter_mm"
            ].reset_button.isEnabled()
        )

    def test_individual_reset_changes_only_its_own_value(self) -> None:
        self.window.target_time_spin.setValue(77)
        self.window.maximum_outer_spin.setValue(63)
        self.window._setting_widgets[
            "target_layer_time_s"
        ].reset_button.click()
        self.assertEqual(
            self.window.target_time_spin.value(),
            self.window.default_settings.target_layer_time_s,
        )
        self.assertEqual(self.window.maximum_outer_spin.value(), 63)

    def test_individual_reset_reads_custom_default_file(self) -> None:
        custom_defaults = self.root / "defaults.json"
        payload = json.loads(DEFAULTS_PATH.read_text(encoding="utf-8"))
        payload["target_layer_time_s"] = 12.75
        custom_defaults.write_text(json.dumps(payload), encoding="utf-8")
        alternate = MainWindow(
            user_settings_path=self.root / "alternate_user.json",
            default_settings_path=custom_defaults,
        )
        try:
            alternate.target_time_spin.setValue(99)
            alternate._setting_widgets[
                "target_layer_time_s"
            ].reset_button.click()
            self.assertEqual(alternate.target_time_spin.value(), 12.75)
        finally:
            alternate.close()

    def test_global_reset_restores_values_mode_and_output(self) -> None:
        self.window.target_time_spin.setValue(91)
        self.window.automatic_base_checkbox.setChecked(False)
        self.window.output_root_edit.setText(str(self.root / "other"))
        self.window.reset_defaults()
        self.assertEqual(
            self.window.target_time_spin.value(),
            self.window.default_settings.target_layer_time_s,
        )
        self.assertEqual(
            self.window.automatic_base_checkbox.isChecked(),
            self.window.default_settings.automatic_base_width,
        )
        self.assertEqual(
            Path(self.window.output_root_edit.text()),
            (PROJECT_ROOT / "output").resolve(),
        )

    def test_output_and_base_mode_have_dedicated_resets(self) -> None:
        self.window.geometry_settings_group.setChecked(True)
        self.window.stability_group.setChecked(True)
        self.assertFalse(self.window.output_root_reset_button.isEnabled())
        self.window.output_root_edit.setText(str(self.root / "changed"))
        self.assertTrue(self.window.output_root_reset_button.isEnabled())
        self.window.output_root_reset_button.click()
        self.assertEqual(
            Path(self.window.output_root_edit.text()),
            self.window.default_output_root,
        )
        self.assertTrue(self.window.automatic_base_reset_button.isHidden())
        self.window.automatic_base_checkbox.setChecked(False)
        self.assertFalse(self.window.automatic_base_reset_button.isHidden())
        self.assertFalse(self.window.automatic_base_reset_button.isEnabled())
        changed_width = self.window.default_settings.manual_base_width_mm + 5.0
        self.window.manual_base_width_spin.setValue(changed_width)
        self.assertTrue(self.window.automatic_base_reset_button.isEnabled())
        self.window.automatic_base_reset_button.click()
        self.assertEqual(
            self.window.manual_base_width_spin.value(),
            self.window.default_settings.manual_base_width_mm,
        )
        self.assertFalse(self.window.automatic_base_checkbox.isChecked())
        self.assertFalse(self.window.automatic_base_reset_button.isEnabled())

    def test_spin_arrows_are_clickable_for_every_numeric_editor(self) -> None:
        for group in (
            self.window.geometry_group,
            self.window.stability_group,
            self.window.geometry_settings_group,
        ):
            group.setChecked(True)
        for setting in self.window._setting_widgets.values():
            editor = setting.editor
            editor.setEnabled(True)
            editor.setValue((editor.minimum() + editor.maximum()) / 2)
            before = editor.value()
            up = self.spin_subcontrol(
                editor,
                QStyle.SubControl.SC_SpinBoxUp,
            )
            up_left = up.center()
            up_left.setX(up.left() + 2)
            QTest.mouseClick(
                editor,
                Qt.MouseButton.LeftButton,
                pos=up_left,
            )
            self.assertGreater(editor.value(), before, setting.setting_name)
            increased = editor.value()
            down = self.spin_subcontrol(
                editor,
                QStyle.SubControl.SC_SpinBoxDown,
            )
            down_left = down.center()
            down_left.setX(down.left() + 2)
            QTest.mouseClick(
                editor,
                Qt.MouseButton.LeftButton,
                pos=down_left,
            )
            self.assertLess(editor.value(), increased, setting.setting_name)

    def test_spin_text_area_does_not_cover_arrow_buttons(self) -> None:
        for setting in self.window._setting_widgets.values():
            editor = setting.editor
            up = self.spin_subcontrol(
                editor,
                QStyle.SubControl.SC_SpinBoxUp,
            )
            down = self.spin_subcontrol(
                editor,
                QStyle.SubControl.SC_SpinBoxDown,
            )
            self.assertFalse(editor.lineEdit().geometry().intersects(up))
            self.assertFalse(editor.lineEdit().geometry().intersects(down))

    def test_editor_and_reset_click_areas_do_not_overlap(self) -> None:
        # Optional groups are collapsed by default.  Expand them before
        # checking the actual, interactive click geometry of their controls.
        self.window.workflow.slicer_unavailable("Layouttest")
        for group in (
            self.window.geometry_group,
            self.window.stability_group,
            self.window.geometry_settings_group,
        ):
            group.setChecked(True)
        self.app.processEvents()
        for setting in self.window._setting_widgets.values():
            if not setting.isVisible():
                continue
            self.assertFalse(
                setting.editor.geometry().intersects(
                    setting.reset_button.geometry()
                ),
                setting.setting_name,
            )
            self.assertGreaterEqual(setting.reset_button.width(), 32)
            self.assertGreaterEqual(setting.reset_button.height(), 32)

    def test_numeric_editors_use_equal_fixed_phase18_size(self) -> None:
        for setting in self.window._setting_widgets.values():
            self.assertEqual(
                setting.editor.minimumWidth(),
                METRICS.form_editor_width_px,
            )
            self.assertEqual(
                setting.editor.maximumWidth(),
                METRICS.form_editor_width_px,
            )
            self.assertEqual(
                setting.editor.height(),
                METRICS.form_control_height_px,
            )

    def test_spin_arrow_icons_are_resolved_and_rendered(self) -> None:
        style = self.window.styleSheet()
        self.assertNotIn("__SPIN_UP_ICON__", style)
        self.assertNotIn("__SPIN_DOWN_ICON__", style)
        self.assertIn("spin_up.svg", style)
        self.assertIn("spin_down.svg", style)

        editor = self.window.target_time_spin
        image = editor.grab().toImage()
        for control in (
            QStyle.SubControl.SC_SpinBoxUp,
            QStyle.SubControl.SC_SpinBoxDown,
        ):
            rectangle = self.spin_subcontrol(editor, control).adjusted(
                4, 3, -4, -3
            )
            dark_pixels = 0
            for y in range(rectangle.top(), rectangle.bottom() + 1):
                for x in range(rectangle.left(), rectangle.right() + 1):
                    color = image.pixelColor(x, y)
                    if (
                        color.red() < 90
                        and color.green() < 120
                        and color.blue() < 140
                    ):
                        dark_pixels += 1
            self.assertGreater(dark_pixels, 0)

    def test_keyboard_entry_and_tab_navigation_work(self) -> None:
        self.complete_source_step()
        self.window.workflow.slicer_succeeded("Tastaturtest")
        self.window.workflow.complete_preparation()
        QTest.qWait(300)
        editor = self.window.target_time_spin
        editor.setFocus()
        editor.selectAll()
        QTest.keyClicks(editor, "23")
        QTest.keyClick(editor, Qt.Key.Key_Return)
        self.assertEqual(editor.value(), 23)
        QTest.keyClick(editor, Qt.Key.Key_Tab)
        self.assertTrue(
            self.window._setting_widgets[
                "target_layer_time_s"
            ].reset_button.hasFocus()
        )


class LiveValidationTests(GuiCase):
    def test_global_reset_restarts_feasibility_for_analyzed_source(self) -> None:
        self.window.current_source_path = self.source
        self.feed_snapshot((1.0,) * 60)
        self.complete_source_step()
        self.window.workflow.slicer_succeeded("Testslicer")
        self.window.workflow.complete_preparation()
        self.wait_until(lambda: self.window.profile_feasibility is not None)
        snapshot = self.window.analysis_snapshot

        self.window.target_time_spin.setValue(10.0)
        self.wait_until(lambda: self.window.profile_feasibility is not None)
        previous_request_id = self.window._feasibility_request_id
        self.window.reset_defaults()

        self.assertIs(self.window.analysis_snapshot, snapshot)
        self.assertGreater(self.window._feasibility_request_id, previous_request_id)
        self.window._on_feasibility_succeeded(
            previous_request_id,
            ProfileFeasibilityAssessment(tower_required=True, feasible=False),
        )
        self.assertIsNone(self.window.profile_feasibility)
        self.wait_until(lambda: self.window.profile_feasibility is not None)
        self.assertNotIn(
            "Die Turmgeometrie wird noch geprüft",
            self.window.export_availability_label.text(),
        )

    def test_global_reset_keeps_local_window_valid_for_short_source(self) -> None:
        self.window.current_source_path = self.source
        self.feed_snapshot((1.0, 2.0, 3.0))
        self.complete_source_step()
        self.window.workflow.slicer_succeeded("Testslicer")
        self.window.workflow.complete_preparation()
        self.wait_until(lambda: self.window.profile_feasibility is not None)

        self.window.target_time_spin.setValue(10.0)
        self.wait_until(lambda: self.window.profile_feasibility is not None)
        self.window.reset_defaults()

        self.assertEqual(self.window.local_window_spin.value(), 3)
        self.assertNotIn("local_reference_window", self.window._static_field_errors)
        self.wait_until(lambda: self.window.profile_feasibility is not None)

    def test_no_tower_hint_is_live_and_generation_stays_disabled(self) -> None:
        self.window.target_time_spin.setValue(1.0)
        self.feed_snapshot((1.0, 2.0, 3.0))
        self.assertIn("Kein Kühlturm erforderlich", self.window.tower_need_label.text())
        self.assertNotIn("Layer", self.window.tower_need_label.text())
        self.assertFalse(self.window.tower_need_label.isHidden())
        self.assertFalse(self.window.preview_button.isEnabled())

    def test_no_tower_requires_confirmation_and_explains_observed_time(self) -> None:
        self.window.current_source_path = self.source
        self.feed_snapshot((31.0, 32.0, 33.0))
        self.complete_source_step()
        self.window.workflow.slicer_succeeded("Testslicer")
        self.window.workflow.complete_preparation()
        self.app.processEvents()

        reason = self.window.export_availability_label.text()
        self.assertIn("Kein Kühlturm erforderlich", reason)
        self.assertIn("9.00 s", reason)
        self.assertIn("31.000 s", reason)
        self.assertTrue(self.window.preview_button.isEnabled())
        with patch.object(self.window, "_ask_no_tower_confirmation", return_value=False) as ask, \
             patch.object(self.window, "_show_preview_dialog") as show_dialog:
            self.window.start_preview()
        ask.assert_called_once()
        self.assertIn("31.000 s", ask.call_args.args[0])
        show_dialog.assert_not_called()
        self.assertFalse(self.window._force_no_tower_generation)
        self.assertFalse(self.window.background_job_manager.has_active(JobKind.PREVIEW))

    def test_confirmed_unnecessary_tower_requests_force_generation(self) -> None:
        self.window.current_source_path = self.source
        self.feed_snapshot((31.0, 32.0, 33.0))
        self.complete_source_step()
        self.window.workflow.slicer_succeeded("Testslicer")
        self.window.workflow.complete_preparation()
        self.app.processEvents()

        def inspect_request():
            self.assertTrue(self.window._force_no_tower_generation)
            raise ValueError("Testabbruch nach Bestätigung")

        with patch.object(self.window, "_ask_no_tower_confirmation", return_value=True), \
             patch.object(self.window, "_show_preview_dialog"), \
             patch.object(self.window, "_current_preview_request", side_effect=inspect_request) as request:
            self.window.start_preview()
        request.assert_called_once()

    def test_no_tower_reason_precedes_other_invalid_settings(self) -> None:
        self.window.current_source_path = self.source
        self.feed_snapshot((8.0, 9.0, 10.0))
        self.complete_source_step()
        self.window.workflow.slicer_succeeded("Testslicer")
        self.window.workflow.complete_preparation()
        self.window.target_time_spin.setValue(8.0)
        self.app.processEvents()

        self.assertFalse(self.window.tower_assessment.tower_required)
        self.assertTrue(self.window.preview_button.isEnabled())
        self.assertIn(
            "Kein Kühlturm erforderlich",
            self.window.export_availability_label.text(),
        )

    def test_target_change_reassesses_need_without_new_file_analysis(self) -> None:
        self.window.target_time_spin.setValue(5.0)
        self.feed_snapshot((1.0, 2.0, 3.0))
        snapshot = self.window.analysis_snapshot
        self.window.target_time_spin.setValue(6.0)
        self.wait_until(lambda: self.window.profile_feasibility is not None)
        self.assertIs(self.window.analysis_snapshot, snapshot)
        self.assertTrue(self.window.tower_assessment.tower_required)

    def test_base_preview_uses_complete_object_not_short_tower_height(self) -> None:
        self.window.target_time_spin.setValue(5.0)
        self.feed_snapshot(
            (1.0, 10.0, 10.0),
            layer_heights=(0.2, 0.2, 199.6),
        )
        self.assertAlmostEqual(self.window.tower_assessment.tower_end_z_mm, 0.2)
        self.assertIn(
            "200.00 mm ermittelte Modellhöhe",
            self.window.automatic_base_width_label.text(),
        )
        self.assertIn("40.00 mm", self.window.automatic_base_width_label.text())

    def test_feasible_tower_still_waits_for_stl_and_slicer(self) -> None:
        self.window.target_time_spin.setValue(5.0)
        self.feed_snapshot((1.0, 1.0, 1.0))
        self.wait_until(lambda: self.window.profile_feasibility is not None)
        self.assertTrue(self.window.profile_feasibility.feasible)
        self.assertFalse(self.window.preview_button.isEnabled())

    def test_geometry_limit_does_not_bypass_required_slicer_context(self) -> None:
        self.window.maximum_expansion_angle_spin.setValue(20.0)
        self.window.automatic_base_checkbox.setChecked(False)
        self.window.manual_base_width_spin.setValue(20.0)
        self.window.maximum_outer_spin.setValue(100.0)
        self.feed_snapshot((29.0, 1.0, 40.0))
        self.window.target_time_spin.setValue(30.0)
        self.wait_until(
            lambda: self.window.profile_feasibility is not None
            and self.window.tower_assessment is not None
            and self.window.tower_assessment.target_layer_time_s == 30.0
        )
        self.window.workflow.slicer_succeeded("Testslicer")
        self.window.validate_form()
        target = self.window._setting_widgets["target_layer_time_s"]
        expansion = self.window._setting_widgets["maximum_expansion_angle_deg"]
        self.assertTrue(self.window.profile_feasibility.feasible)
        self.assertFalse(bool(target.editor.property("invalid")))
        self.assertFalse(bool(expansion.editor.property("invalid")))
        self.assertFalse(target.message_label.text())
        self.assertEqual(
            self.window.tower_need_label.text(),
            "Kühlturm erforderlich - 2 Layer unterschreiten die gewünschte "
            "Mindest-Layerzeit.",
        )
        self.assertFalse(self.window.validation_label.text())
        self.assertFalse(self.window.preview_button.isEnabled())

    def test_correcting_geometry_limit_remains_error_free(self) -> None:
        self.window.maximum_expansion_angle_spin.setValue(20.0)
        self.window.automatic_base_checkbox.setChecked(False)
        self.window.manual_base_width_spin.setValue(20.0)
        self.window.maximum_outer_spin.setValue(100.0)
        self.feed_snapshot((29.0, 1.0, 40.0))
        self.window.target_time_spin.setValue(30.0)
        self.wait_until(
            lambda: self.window.profile_feasibility is not None
            and self.window.profile_feasibility.feasible
        )
        self.window.workflow.slicer_succeeded("Testslicer")
        self.window.validate_form()
        setting = self.window._setting_widgets["target_layer_time_s"]
        self.assertFalse(bool(setting.editor.property("invalid")))
        self.window.target_time_spin.setValue(5.0)
        self.wait_until(
            lambda: self.window.profile_feasibility is not None
            and self.window.profile_feasibility.feasible
        )
        self.assertFalse(bool(setting.editor.property("invalid")))
        self.assertEqual(setting.message_label.text(), "")

    def test_related_settings_are_reported_without_invalidating_a_field(self) -> None:
        self.complete_source_step()
        self.window.workflow.slicer_succeeded("Testslicer")
        self.window.workflow.complete_preparation()
        issue = FeasibilityIssue(
            code="EXPANSION_ANGLE_TOO_SMALL",
            message="Grenze nicht erreichbar.",
            affected_layer_index=4,
            related_setting_names=(
                "maximum_outer_diameter_mm",
                "maximum_expansion_angle_deg",
            ),
            required_value=8,
            achievable_value=6,
        )
        self.window._feasibility_issues = (issue,)
        self.window._feasibility_field_errors = {}
        self.window._feasibility_issue_summaries = [issue.message]
        self.window.validate_form()
        target = self.window._setting_widgets["target_layer_time_s"]
        self.assertFalse(bool(target.editor.property("invalid")))
        self.assertFalse(target.message_label.text().strip())
        self.assertIn(issue.message, self.window.validation_label.text())
        for name in (
            "maximum_outer_diameter_mm",
            "maximum_expansion_angle_deg",
        ):
            widget = self.window._setting_widgets[name]
            self.assertFalse(bool(widget.editor.property("invalid")))

    def test_static_invalid_value_is_inline_and_blocks_profile_check(self) -> None:
        self.complete_source_step()
        self.window.workflow.slicer_succeeded("Testslicer")
        self.window.workflow.complete_preparation()
        self.window.minimum_outer_spin.setValue(30)
        self.window.maximum_outer_spin.setValue(1001)
        self.assertFalse(bool(self.window.minimum_outer_spin.property("invalid")))
        self.assertTrue(bool(self.window.maximum_outer_spin.property("invalid")))
        self.assertTrue(
            self.window._setting_widgets[
                "maximum_outer_diameter_mm"
            ].message_label.text()
        )
        self.assertIn("Maximaler Turmdurchmesser", self.window.validation_label.text())
        self.assertFalse(self.window.preview_button.isEnabled())

    def test_incomplete_numeric_text_is_safe_and_inline(self) -> None:
        self.complete_source_step()
        self.window.workflow.slicer_succeeded("Testslicer")
        self.window.workflow.complete_preparation()
        line_edit = self.window.target_time_spin.lineEdit()
        line_edit.clear()
        self.app.processEvents()
        self.assertIn(
            "target_layer_time_s",
            self.window._incomplete_setting_names,
        )
        self.assertTrue(
            bool(self.window.target_time_spin.property("invalid"))
        )
        self.assertFalse(self.window.preview_button.isEnabled())

    def test_stale_feasibility_result_is_ignored(self) -> None:
        self.window._feasibility_request_id = 7
        result = ProfileFeasibilityAssessment(
            tower_required=True,
            feasible=False,
        )
        self.window._on_feasibility_succeeded(6, result)
        self.assertIsNone(self.window.profile_feasibility)

    def test_live_feasibility_creates_no_output_directory(self) -> None:
        snapshot = make_snapshot(self.source, (1.0, 1.0, 1.0))
        settings = GenerationSettings(
            target_layer_time_s=2.0,
        )
        assessment = assess_tower_need(snapshot, settings)
        unexpected = self.root / "unexpected_output"
        result = assess_profile_feasibility(snapshot, settings, assessment)
        self.assertTrue(result.tower_required)
        self.assertFalse(unexpected.exists())


class SlowStlValidationService(StlValidationService):
    def validate(self, path, *, progress_callback=None, cancellation_callback=None):
        cancelled = cancellation_callback or (lambda: False)
        while not cancelled():
            time.sleep(0.005)
        raise StlValidationCancelled()


class StartupLayoutAndLifecycleTests(GuiCase):
    def test_small_window_scrolls_without_horizontal_overlap(self) -> None:
        self.window.workflow.slicer_unavailable("Layouttest")
        for group in (
            self.window.geometry_group,
            self.window.stability_group,
            self.window.geometry_settings_group,
        ):
            group.setChecked(True)
        self.window.resize(720, 640)
        QTest.qWait(350)
        self.assertGreater(
            self.window.settings_scroll.verticalScrollBar().maximum(),
            0,
        )
        self.assertEqual(
            self.window.settings_scroll.horizontalScrollBar().maximum(),
            0,
        )

    def test_status_area_remains_outside_scrolling_settings(self) -> None:
        self.assertFalse(
            self.window.settings_scroll.isAncestorOf(self.window.status_label)
        )
        self.assertFalse(
            self.window.settings_scroll.isAncestorOf(self.window.progress_bar)
        )

    def test_common_dpi_scale_factors_have_no_editor_reset_overlap(self) -> None:
        code = "\n".join(
            (
                "import os,sys",
                f"sys.path.insert(0, {str(SRC_ROOT)!r})",
                "from PySide6.QtWidgets import QApplication",
                "from cooling_tower.gui import MainWindow",
                "app=QApplication([])",
                "win=MainWindow()",
                "win.workflow.set_slicer_step_visible(True)",
                "win.workflow.source_validation_succeeded('layout.stl geprüft', analysis_complete=True)",
                "win.workflow.slicer_succeeded('Layouttest')",
                "win.workflow.complete_preparation()",
                "win.show()",
                "[group.setChecked(True) for group in (win.geometry_group,win.stability_group,win.geometry_settings_group)]",
                "for width,height in ((720,640),(1024,768),(1280,720),(1920,1080)):",
                "    win.resize(width,height)",
                "    app.processEvents()",
                "    assert all(not w.editor.geometry().intersects(w.reset_button.geometry()) for w in win._setting_widgets.values() if w.isVisible())",
                "    assert win.settings_scroll.horizontalScrollBar().maximum() == 0",
                "    win.settings_scroll.ensureWidgetVisible(win.preview_button)",
                "    app.processEvents()",
                "    assert win.preview_button.isVisible()",
                "win.close()",
                "app.processEvents()",
            )
        )
        for factor in ("1", "1.25", "1.5", "1.75", "2"):
            environment = os.environ.copy()
            environment["QT_QPA_PLATFORM"] = "offscreen"
            environment["QT_SCALE_FACTOR"] = factor
            environment["COOLING_TOWER_USER_SETTINGS_PATH"] = str(
                self.root / f"dpi-{factor}.json"
            )
            completed = subprocess.run(
                [sys.executable, "-B", "-c", code],
                cwd=PROJECT_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            self.assertEqual(
                completed.returncode,
                0,
                f"DPI {factor}: {completed.stderr}",
            )

    def test_pythonw_entry_point_starts_and_closes_cleanly(self) -> None:
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        if not pythonw.is_file():
            self.skipTest("Der aktuelle Python-Build enthält kein pythonw.exe.")
        environment = os.environ.copy()
        environment["QT_QPA_PLATFORM"] = "offscreen"
        environment["COOLING_TOWER_TEST_AUTOCLOSE_MS"] = "250"
        environment["COOLING_TOWER_USER_SETTINGS_PATH"] = str(
            self.root / "pythonw-user.json"
        )
        process = subprocess.Popen(
            [str(pythonw), str(PROJECT_ROOT / "start_gui.pyw")],
            cwd=PROJECT_ROOT,
            env=environment,
        )
        self.assertEqual(process.wait(timeout=15), 0)

    def test_startup_error_is_logged_and_shown_as_dialog(self) -> None:
        log_path = self.root / "logs" / "startup.log"
        with patch("cooling_tower.application.QMessageBox.critical") as dialog:
            written = show_startup_error("test traceback", log_path=log_path)
        self.assertEqual(written, log_path.resolve())
        self.assertEqual(log_path.read_text(encoding="utf-8"), "test traceback")
        dialog.assert_called_once()

    def test_close_cancels_background_stl_validation_thread(self) -> None:
        stl_source = self.root / "slow.stl"
        stl_source.write_text(
            "solid slow\n"
            "facet normal 0 0 1\n"
            "outer loop\n"
            "vertex 0 0 0\n"
            "vertex 1 0 0\n"
            "vertex 0 1 0\n"
            "endloop\n"
            "endfacet\n"
            "endsolid slow\n",
            encoding="utf-8",
        )
        alternate = MainWindow(
            user_settings_path=self.root / "slow-user.json",
            stl_validation_service=SlowStlValidationService(),
        )
        alternate.drop_zone.set_file(stl_source)
        deadline = time.monotonic() + 2
        while (
            not alternate.background_job_manager.has_active(
                JobKind.STL_VALIDATION
            )
            and time.monotonic() < deadline
        ):
            self.app.processEvents()
        threads = [
            job.thread
            for job in alternate.background_job_manager.active_jobs(
                JobKind.STL_VALIDATION
            )
            if isinstance(job.thread, QThread)
        ]
        self.assertTrue(threads and threads[0].isRunning())
        alternate.close()
        self.app.processEvents()
        self.assertTrue(all(not thread.isRunning() for thread in threads))

    def test_cli_help_remains_an_explicit_console_interface(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-B", str(PROJECT_ROOT / "cli_main.py"), "--help"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--target-time", completed.stdout)


if __name__ == "__main__":
    unittest.main()
