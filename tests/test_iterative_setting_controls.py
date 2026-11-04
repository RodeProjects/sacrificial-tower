"""Automatic/manual controls and durable tower wall preferences."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionFrame, QStyleOptionSpinBox
from cooling_tower.gui.main_window import MainWindow
from cooling_tower.gui.design_tokens import METRICS
from cooling_tower.gui.settings_store import UserSettingsStore
from cooling_tower.models import GenerationSettings
from cooling_tower.config import SETTINGS_SCHEMA_VERSION
from cooling_tower.settings_compatibility import SETTING_COMPATIBILITY_CATALOG, merge_compatible_setting_changes
from cooling_tower.postprocessor import PostprocessorSettings
from cooling_tower.postprocessor_capture import capture_design
from gui_lifecycle import dispose_test_widget


class IterativeControlTests(unittest.TestCase):
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
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.window = MainWindow(user_settings_path=Path(temporary.name) / "settings.json",
            enable_update_check=False, enable_startup_slicer_discovery=False)
        self.addCleanup(dispose_test_widget, self.window)

    def ready(self):
        w = self.window
        w.resize(1500, 1000)
        w.show()
        w.workflow.set_slicer_step_visible(True)
        w.workflow.source_validation_succeeded("object.stl", analysis_complete=True)
        w.workflow.slicer_succeeded("Testslicer")
        w.workflow.complete_preparation()
        w.automatic_generation_card.click()
        w.geometry_group.set_expanded(True)
        for _ in range(5):
            self.app.processEvents()
        return w

    def test_clearance_warning_tracks_full_infill_and_stays_below_diameter(self):
        w = self.ready()
        row = w._setting_widgets['minimum_outer_diameter_mm']
        w.full_infill_checkbox.setChecked(False)
        self.app.processEvents()
        self.assertIn('nicht bestimmbar', row.message_label.text() + row.secondary_message_label.text())
        w.full_infill_checkbox.setChecked(True)
        self.app.processEvents()
        self.assertEqual(row._helper_text, '')

    def test_clearance_warning_updates_with_profile_and_wall_count(self):
        w = self.ready()
        w.full_infill_checkbox.setChecked(False)
        profile = SimpleNamespace(effective_values={'line_width': '0.4', 'minimum_sparse_infill_area': '20',
                                                    'sparse_infill_density': '12%'},
                                  installation=SimpleNamespace(adapter_id='orca_slicer'))
        old = w.profile_match_result
        try:
            w.profile_match_result = SimpleNamespace(selected=SimpleNamespace(effective_profile=profile))
            w.tower_wall_count_spin.blockSignals(True)
            w.tower_wall_count_spin.setValue(3)
            w.tower_wall_count_spin.blockSignals(False)
            w._update_tower_wall_clearance_warning()
            row = w._setting_widgets['minimum_outer_diameter_mm']
            self.assertIn('7,5 mm', row._helper_text)
            w.minimum_outer_spin.blockSignals(True)
            w.minimum_outer_spin.setValue(7.5)
            w.minimum_outer_spin.blockSignals(False)
            w._update_tower_wall_clearance_warning()
            self.assertEqual(row._helper_text, '')
            profile.effective_values['sparse_infill_density'] = '100%'
            w._update_tower_wall_clearance_warning()
            self.assertIn('100 % Füllung', w._setting_widgets['minimum_outer_diameter_mm']._helper_text)
        finally:
            w.profile_match_result = old

    def test_auto_controls_match_postprocessor_positions_and_indicator_sizes(self):
        w = self.ready()
        reference = w.postprocessor_panel.rows["height_mm"]
        expected_gap = reference.layout().horizontalSpacing()
        for name, checkbox in (("manual_base_width_mm", w.automatic_base_checkbox),
                ("circle_segments", w.automatic_circle_segments_checkbox),
                ("maximum_contraction_angle_deg", w.automatic_contraction_checkbox)):
            row = w._setting_widgets[name]
            grid = row.layout()
            self.assertEqual(grid.horizontalSpacing(), expected_gap)
            self.assertEqual(grid.itemAtPosition(0, 2).widget().text(), "Auto")
            self.assertIs(grid.itemAtPosition(0, 3).widget(), checkbox)
            self.assertIs(grid.itemAtPosition(0, 4).widget(), row.editor)
            self.assertEqual(checkbox.sizeHint(), w.postprocessor_panel.automatic["automatic_height"].sizeHint())
            self.assertLessEqual(abs(checkbox.geometry().center().y() - row.editor.geometry().center().y()), 1)
            self.assertGreaterEqual(grid.itemAtPosition(0, 2).widget().x() - row.label.geometry().right(), expected_gap)
        self.assertEqual(w.manual_base_width_setting.label.text(), "Standfußbreite")

    def test_numeric_fields_shrink_uniformly_and_expand_for_longer_values(self):
        w = self.ready()
        rows = (*w._setting_widgets.values(), *w.slice_budget_settings.values())
        widths = {row.editor.width() for row in rows}
        self.assertEqual(len(widths), 1)
        self.assertLess(next(iter(widths)), 150)
        w.automatic_base_checkbox.setChecked(False)
        w.manual_base_width_spin.setValue(79.99)
        for _ in range(4):
            self.app.processEvents()
        for row in rows:
            edit = row.editor.lineEdit()
            self.assertGreaterEqual(edit.width(), edit.fontMetrics().horizontalAdvance(edit.text()))

    def test_auto_solid_and_decimal_text_fit_inside_actual_line_contents(self):
        w = self.ready()
        for full in (False, True):
            w.full_infill_checkbox.setChecked(full)
            for _ in range(3):
                self.app.processEvents()
            for name in ("tower_wall_count", "circle_segments", "maximum_contraction_angle_deg", "manual_base_width_mm"):
                edit = w._setting_widgets[name].editor.lineEdit()
                option = QStyleOptionFrame()
                edit.initStyleOption(option)
                contents = edit.style().subElementRect(QStyle.SubElement.SE_LineEditContents, option, edit)
                margins = edit.textMargins()
                self.assertGreaterEqual(contents.width()-margins.left()-margins.right(),
                    edit.fontMetrics().horizontalAdvance(edit.text())+2, name)

    def test_manual_angle_survives_auto_and_full_infill_and_reset(self):
        w = self.window
        flag, spin = w.automatic_contraction_checkbox, w.maximum_contraction_angle_spin
        self.assertTrue(flag.isChecked())
        flag.setChecked(False)
        spin.setValue(27.125)
        for infill in (True, False):
            w.full_infill_checkbox.setChecked(infill)
            self.assertTrue(spin.isEnabled())
            flag.setChecked(True)
            self.assertEqual(spin.text(), "auto")
            flag.setChecked(False)
            self.assertEqual(spin.value(), 27.125)
        w._setting_widgets["maximum_contraction_angle_deg"].reset_button.click()
        self.assertTrue(flag.isChecked())

    def test_wall_count_is_retained_while_full_infill_disables_it(self):
        w = self.window
        w.tower_wall_count_spin.setValue(4)
        w.full_infill_checkbox.setChecked(True)
        self.assertFalse(w.tower_wall_count_spin.isEnabled())
        self.assertEqual(w.tower_wall_count_spin.text(), "solid")
        self.assertEqual(w.tower_wall_count_spin.grab().toImage().pixelColor(10, 10).name(), "#f1f4f6")
        w.tower_wall_count_spin.interpretText()
        self.assertEqual(w.tower_wall_count_spin.value(), 4)
        self.assertIn("ausgegraut", w._setting_widgets["tower_wall_count"].info_button.toolTip())
        w.full_infill_checkbox.setChecked(False)
        self.assertTrue(w.tower_wall_count_spin.isEnabled())
        self.assertEqual(w.collect_settings().tower_wall_count, 4)

    def test_wall_count_accepts_real_mouse_arrow_and_keyboard_input(self):
        w = self.ready()
        row = w._setting_widgets["tower_wall_count"]
        self.assertIs(w.geometry_fields_layout.itemAt(1).widget(), row)
        spin = w.tower_wall_count_spin
        w.full_infill_checkbox.setChecked(False)
        option = QStyleOptionSpinBox()
        spin.initStyleOption(option)
        up = spin.style().subControlRect(QStyle.ComplexControl.CC_SpinBox,
            option, QStyle.SubControl.SC_SpinBoxUp, spin).center()
        QTest.mouseClick(w.windowHandle(), Qt.MouseButton.LeftButton,
            pos=spin.mapTo(w, up))
        self.assertEqual(spin.value(), 3)
        edit = spin.lineEdit()
        QTest.mouseClick(w.windowHandle(), Qt.MouseButton.LeftButton,
            pos=edit.mapTo(w, edit.rect().center()))
        edit.selectAll()
        QTest.keyClicks(edit, "5")
        QTest.keyClick(edit, Qt.Key.Key_Enter)
        self.assertEqual(w.collect_settings().tower_wall_count, 5)
        w.full_infill_checkbox.setChecked(True)
        self.assertFalse(spin.isEnabled())
        w.full_infill_checkbox.setChecked(False)
        self.assertTrue(spin.isEnabled())
        QTest.mouseClick(w.windowHandle(), Qt.MouseButton.LeftButton,
            pos=spin.mapTo(w, up))
        self.assertEqual(spin.value(), 6)

    def test_minimum_visible_text_gap_matches_postprocessor(self):
        w = self.ready()
        reference = w.postprocessor_panel.rows["base_width_mm"]
        reference.ensurePolished()

        def minimum_gap(row):
            row.resize(row.minimumSizeHint().width(), row.sizeHint().height())
            row.layout().setGeometry(row.rect())
            auto = row.layout().itemAtPosition(0, 2).widget()
            return auto.x() + auto.contentsMargins().left() - row.label.x() - row.label.fontMetrics().horizontalAdvance(row.label.text())

        gap = minimum_gap(reference)
        self.assertEqual(minimum_gap(w.manual_base_width_setting), gap)
        for name in ("circle_segments", "maximum_contraction_angle_deg"):
            row = w._setting_widgets[name]
            self.assertGreaterEqual(row.label.minimumWidth(), row.label.fontMetrics().horizontalAdvance(row.label.text()))
            self.assertGreaterEqual(minimum_gap(row), METRICS.form_auto_label_gap_px)

    def test_dragging_splitter_moves_editors_and_resets_with_the_right_edge(self):
        w = self.ready()
        w.resize(1900, 1000)
        for _ in range(4):
            self.app.processEvents()
        splitter = w.ready_grid.splitter
        names = ("target_layer_time_s", "tower_wall_count", "manual_base_width_mm", "maximum_contraction_angle_deg")
        def positions():
            return {name: w._setting_widgets[name].reset_button.mapTo(w, QPoint()).x() for name in names}
        before = positions()
        initial = splitter.sizes()[0]
        splitter.moveSplitter(initial + 120, 1)
        for _ in range(6):
            self.app.processEvents()
        moved = splitter.sizes()[0] - initial
        self.assertGreater(moved, 50)
        for name, position in positions().items():
            self.assertAlmostEqual(position-before[name], moved, delta=1, msg=name)

    def test_heading_reopens_cards_and_splitter_keeps_manual_ratio(self):
        w = self.ready()
        columns = w.ready_grid
        self.assertTrue(columns.is_two_column())
        initial = columns.splitter.sizes()[0]
        self.assertLessEqual(initial, w.ready_left_column.minimumSizeHint().width() + 2)
        columns.splitter.moveSplitter(0, 1)
        self.app.processEvents()
        self.assertEqual(w.profile_angle_limit.suffix.text(), " des Slicer-Profils verwenden")
        for row in w._setting_widgets.values():
            self.assertNotIn("…", row.label.text())
            if not row.label.wordWrap():
                self.assertGreaterEqual(row.label.width(), row.label.fontMetrics().horizontalAdvance(row.label.text()))
        profile = w.profile_angle_limit
        profile._position()
        profile.layout().activate()
        checkbox_end = profile.checkbox.mapTo(w, QPoint(profile.checkbox.width(), 0)).x()
        editor_start = w.maximum_expansion_angle_spin.mapTo(w, QPoint()).x()
        self.assertGreaterEqual(editor_start-checkbox_end, METRICS.form_auto_label_gap_px)
        columns.splitter.moveSplitter(initial + 100, 1)
        ratio = columns._ratio
        w.resize(1600, 1000)
        for _ in range(4):
            self.app.processEvents()
        sizes = columns.splitter.sizes()
        self.assertAlmostEqual(sizes[0] / sum(sizes), ratio, delta=.01)
        w.header_method_selection.heading.click()
        self.app.processEvents()
        self.assertTrue(w.generation_method_picker.isVisible())


class IterativePersistenceTests(unittest.TestCase):
    def test_direct_and_multistep_migration_backup_and_manual_angle(self):
        for version in (0, 27, 28):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "settings.json"
                original = json.dumps({"settings_schema_version": version,
                    "generation": {"maximum_contraction_angle_deg": 63.0}}).encode()
                path.write_bytes(original)
                store = UserSettingsStore(path, ROOT / "config/default_settings.json")
                settings, state = store.load()
                self.assertEqual(state["settings_schema_version"], SETTINGS_SCHEMA_VERSION)
                self.assertFalse(settings.automatic_contraction_angle)
                self.assertEqual(settings.maximum_contraction_angle_deg, 63)
                self.assertEqual(settings.tower_wall_count, 2)
                self.assertEqual(store.last_migration_backup.read_bytes(), original)

    def test_atomic_failure_recovers_without_changing_original(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            original = b'{"settings_schema_version":28,"generation":{}}'
            path.write_bytes(original)
            with patch("cooling_tower.persistence.versioned_json.os.replace", side_effect=OSError("blocked")):
                UserSettingsStore(path, ROOT / "config/default_settings.json").load()
            self.assertEqual(path.read_bytes(), original)
            settings, _ = UserSettingsStore(path, ROOT / "config/default_settings.json").load()
            self.assertTrue(settings.automatic_contraction_angle)

    def test_downgrade_rejects_types_units_and_bounds_per_setting(self):
        base = {"generation": GenerationSettings(tower_wall_count=4).to_dict()}
        stable = "generation.tower_wall_count"
        for value, token in ((0, "tower-wall-count-v1"), (11, "tower-wall-count-v1"),
                (True, "tower-wall-count-v1"), ("3", "tower-wall-count-v1"),
                (3.5, "tower-wall-count-v1"), (3, "tower-wall-width-mm-v1")):
            result = merge_compatible_setting_changes(base, {stable: {"value": value, "token": token}})
            self.assertEqual(result.payload["generation"]["tower_wall_count"], 4)
            self.assertIn(stable, result.rejected_ids)
        flag = "generation.automatic_contraction_angle"
        result = merge_compatible_setting_changes(base, {flag: {"value": "false",
            "token": SETTING_COMPATIBILITY_CATALOG[flag]}})
        self.assertTrue(result.payload["generation"]["automatic_contraction_angle"])

    def test_postprocessor_defaults_and_double_width_preserve_manual_width(self):
        self.assertEqual(PostprocessorSettings().target_layer_time_s, 9)
        self.assertEqual(capture_design(40, ()).diameter_mm, 24)
        self.assertEqual(capture_design(40, (90,)).diameter_mm, 24 * 2 ** .5)
        self.assertEqual(capture_design(40, (), diameter=13).diameter_mm, 13)
