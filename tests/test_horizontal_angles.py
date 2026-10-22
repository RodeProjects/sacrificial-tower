"""Horizontal presentation, profile binding and unchanged stored geometry."""
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('COOLING_TOWER_DISABLE_SLICER_DISCOVERY', '1')

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QEnterEvent, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QStyle, QStyleOptionButton, QStyleOptionSpinBox
from cooling_tower.angles import complementary_angle
from cooling_tower.config import load_generation_settings, save_generation_settings
from cooling_tower.gui.manual_panel import ManualGenerationPanel
from cooling_tower.gui.design_tokens import COLORS
from cooling_tower.gui.settings_store import UserSettingsStore
from cooling_tower.manual.settings_store import ManualSettingsStore, MANUAL_SCHEMA_VERSION
from cooling_tower.manual.geometry import ManualSettings
from cooling_tower.persistence.versioned_json import VersionedDocumentError
from cooling_tower.models import GenerationSettings
from cooling_tower.slicers.support_angles import profile_binding_threshold, profile_support_threshold
from cooling_tower.gui.widgets.profile_angle_limit import PROFILE_ANGLE_HINT, PROFILE_ANGLE_FALLBACK_NOTICE
from cooling_tower.tower.solid_profile import validate_solid_settings
import test_support_simulation as support
from test_manual_generation import create_fixture
from test_manual_gui import preview_test_application, restore_preview_test_application

ROOT = Path(__file__).resolve().parents[1]


class HorizontalAngleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app, cls.font, cls.font_id = preview_test_application()

    @classmethod
    def tearDownClass(cls):
        restore_preview_test_application(cls.app, cls.font, cls.font_id)

    def window(self, threshold=23.5, adapter='orca_slicer'):
        fixture = support.SupportSimulationTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        self.addCleanup(fixture.doCleanups)
        w = fixture.recovery_window(adapter)
        selected = w.profile_match_result.selected
        key = 'support_material_threshold' if adapter == 'prusa_slicer' else 'support_threshold_angle'
        profile = replace(selected.effective_profile, effective_values={
            **selected.effective_profile.effective_values, key: threshold})
        w.profile_match_result = replace(w.profile_match_result,
                                        selected=replace(selected, effective_profile=profile))
        w.apply_settings(GenerationSettings(limit_expansion_to_profile=False))
        return w

    def test_auto_angles_roundtrip_without_changing_saved_geometry(self):
        w = self.window()
        self.assertEqual(w.maximum_expansion_angle_spin.value(), 40)
        self.assertEqual(w.maximum_contraction_angle_spin.value(), 35)
        w.maximum_expansion_angle_spin.setValue(30)
        w.maximum_contraction_angle_spin.setValue(25)
        settings = w.collect_settings()
        self.assertEqual(settings.maximum_expansion_angle_deg, 60)
        self.assertEqual(settings.maximum_contraction_angle_deg, 65)
        self.assertAlmostEqual(math.tan(math.radians(settings.maximum_contraction_angle_deg)),
                               1/math.tan(math.radians(25)))
        w.apply_settings(settings)
        self.assertEqual(w.maximum_contraction_angle_spin.value(), 25)
        w._setting_widgets['maximum_contraction_angle_deg'].reset_button.click()
        self.assertEqual(w.maximum_contraction_angle_spin.value(), 35)
        w.full_infill_checkbox.setChecked(True)
        self.assertFalse(w.maximum_contraction_angle_spin.isEnabled())
        self.assertEqual(w.maximum_contraction_angle_spin.text(), 'auto')
        self.assertEqual(w.collect_settings().maximum_contraction_angle_deg, 55)

    def test_contraction_auto_display_retains_manual_angle_after_loading_and_toggling(self):
        w = self.ready_angle_window()
        spin = w.maximum_contraction_angle_spin
        row = w._setting_widgets['maximum_contraction_angle_deg']
        for full_infill in (True, False, True):
            with self.subTest(full_infill=full_infill):
                w.apply_settings(replace(w.collect_settings(), simulate_full_tower_infill=full_infill,
                                         maximum_contraction_angle_deg=63))
                self.assertEqual(spin.isEnabled(), not full_infill)
                self.assertEqual(spin.text(), 'auto' if full_infill else '27,0')
                self.assertEqual(row.unit_label.isHidden(), full_infill)
                self.assertEqual(row.reset_button.isEnabled(), not full_infill)
                self.assertEqual(spin.value(), 27)
                self.assertEqual(w.collect_settings().maximum_contraction_angle_deg, 63)
                spin.interpretText()
                self.assertEqual(spin.value(), 27)
                w.full_infill_checkbox.setChecked(False)
                self.assertTrue(spin.isEnabled())
                self.assertEqual(spin.value(), 27)
                spin.setFocus()
                spin.lineEdit().selectAll()
                QTest.keyClicks(spin.lineEdit(), '29')
                QTest.keyClick(spin, Qt.Key.Key_Enter)
                self.assertEqual(spin.value(), 29)
                w.full_infill_checkbox.setChecked(True)
                self.assertEqual(spin.text(), 'auto')
                self.assertEqual(spin.value(), 29)
                self.assertFalse(row.reset_button.isEnabled())
                w.full_infill_checkbox.setChecked(False)
                self.assertEqual(spin.text(), '29,0')
                self.assertTrue(row.reset_button.isEnabled())
                row.reset_button.click()
                self.assertEqual(spin.value(), 35)
                self.assertTrue(spin.isEnabled())

    def test_contraction_auto_display_is_gray_and_preserves_saved_numeric_precision(self):
        w = self.ready_angle_window()
        spin = w.maximum_contraction_angle_spin
        row = w._setting_widgets['maximum_contraction_angle_deg']
        w.apply_settings(replace(w.collect_settings(), simulate_full_tower_infill=True,
                                 maximum_contraction_angle_deg=62.875))
        self.assertEqual(spin.text(), 'auto')
        self.assertTrue(spin.hasAcceptableInput())
        self.assertNotIn('maximum_contraction_angle_deg', w._incomplete_setting_names)
        self.assertEqual(spin.grab().toImage().pixelColor(10, 10).name(), '#f1f4f6')
        w._save_user_settings(strict=True)
        saved, _ = w.settings_store.load()
        self.assertEqual(saved.maximum_contraction_angle_deg, 62.875)
        self.assertTrue(saved.simulate_full_tower_infill)
        w.apply_settings(saved)
        self.assertEqual(spin.text(), 'auto')
        spin.interpretText()
        self.assertEqual(spin.value(), 27.125)
        w.full_infill_checkbox.setChecked(False)
        self.assertEqual(spin.value(), 27.125)
        self.assertEqual(spin.text(), '27,1')
        self.assertFalse(row.unit_label.isHidden())
        self.assertTrue(row.reset_button.isEnabled())
        self.assertNotEqual(spin.grab().toImage().pixelColor(10, 10).name(), '#f1f4f6')

    def test_contraction_help_explains_auto_and_keeps_steps_without_threshold_paragraph(self):
        from cooling_tower.gui.texts import SETTING_INFO_TEXTS
        hint = SETTING_INFO_TEXTS['maximum_contraction_angle_deg']
        self.assertIn('nach eigenen Regeln', hint)
        self.assertIn('„auto“', hint)
        self.assertIn('bleibt aber erhalten', hint)
        self.assertIn('Direkte Absätze nach innen', hint)
        self.assertNotIn('Threshold angle', hint)
        self.assertNotIn('Stütz-Erkennung', hint)

    def test_new_defaults_enable_profile_binding_in_both_modes(self):
        self.assertTrue(GenerationSettings().limit_expansion_to_profile)
        self.assertTrue(load_generation_settings(ROOT / 'config/default_settings.json').limit_expansion_to_profile)
        self.assertTrue(ManualSettings().limit_expansion_to_profile)
        w = self.window(15)
        w.apply_settings(GenerationSettings())
        self.assertTrue(w.profile_angle_limit.checkbox.isChecked())
        self.assertTrue(w.profile_angle_limit.state.active)
        self.assertEqual(w.maximum_expansion_angle_spin.value(), 15)
        self.assertFalse(w.maximum_expansion_angle_spin.isEnabled())
        _, _, reference, _, _ = create_fixture(self, joint=True, count=200)
        reference = replace(reference, context=replace(reference.context, support_threshold_angle_deg=15))
        panel = ManualGenerationPanel()
        self.addCleanup(panel.close)
        panel.initialize(reference)
        self.assertTrue(panel.profile_angle_limit.checkbox.isChecked())
        self.assertTrue(panel.profile_angle_limit.state.active)
        self.assertEqual(panel.editors['expansion_angle_deg'].value(), 15)
        panel.profile_angle_limit.checkbox.click()
        panel.editors['expansion_angle_deg'].setValue(35)
        panel.reset_all()
        self.assertTrue(panel.settings.limit_expansion_to_profile)
        self.assertEqual(panel.editors['expansion_angle_deg'].value(), 15)
        self.assertEqual(panel.settings_for_persistence().expansion_angle_deg, 50)

    def test_active_profile_binding_hides_yellow_warnings_and_keeps_red_errors(self):
        from cooling_tower.gui.texts import EXPANSION_ANGLE_CAUTION
        w = self.ready_angle_window(15)
        w.maximum_expansion_angle_spin.setValue(25)
        self.assertIn(EXPANSION_ANGLE_CAUTION, w.maximum_expansion_angle_setting._helper_text)
        w.profile_angle_limit.checkbox.click()
        row = w.maximum_expansion_angle_setting
        row.set_error('Testfehler')
        w._update_expansion_angle_warning()
        self.assertEqual(row._helper_text, '')
        self.assertIn('Testfehler', row.message_label.text())
        self.assertTrue(row.message_label.property('error'))
        w.profile_angle_limit.checkbox.click()
        self.assertIn(EXPANSION_ANGLE_CAUTION, row._helper_text)
        _, _, reference, _, _ = create_fixture(self, joint=True, count=200)
        reference = replace(reference, context=replace(reference.context, support_threshold_angle_deg=15))
        panel = ManualGenerationPanel(ManualSettings(limit_expansion_to_profile=False))
        self.addCleanup(panel.close)
        panel.initialize(reference)
        panel.editors['expansion_angle_deg'].setValue(25)
        self.assertIn(EXPANSION_ANGLE_CAUTION, panel.expansion_warning.text())
        panel.profile_angle_limit.checkbox.click()
        row = panel.rows['expansion_angle_deg']
        row.set_error('Testfehler')
        panel._sync()
        self.assertTrue(panel.expansion_warning.isHidden())
        self.assertIn('Testfehler', row.message_label.text())
        self.assertFalse(row.message_label.isHidden())
        self.assertIn(f"color: {COLORS['error']}", row.message_label.styleSheet())
        panel.profile_angle_limit.checkbox.click()
        self.assertIn(EXPANSION_ANGLE_CAUTION, panel.expansion_warning.text())

    def test_manual_bound_preview_limit_is_checked_disabled_and_gray(self):
        w = self.window(15)
        _, _, reference, _, _ = create_fixture(self, joint=True, count=200)
        reference = replace(reference, context=replace(reference.context, support_threshold_angle_deg=15))
        panel = ManualGenerationPanel()
        self.addCleanup(panel.close)
        panel.setStyleSheet(w.styleSheet())
        panel.initialize(reference)
        panel.resize(1400, 900)
        panel.show()
        self.app.processEvents()
        box = panel.checks['expansion_enabled']
        self.assertTrue(box.isChecked())
        self.assertFalse(box.isEnabled())
        self.assertTrue(panel.profile_angle_limit.checkbox.isEnabled())
        self.assertEqual(box.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText).name(), '#8393a3')
        option = QStyleOptionButton()
        option.initFrom(box)
        indicator = box.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, option, box)
        rendered = box.grab().toImage()
        self.assertTrue(any(rendered.pixelColor(x, y).name() == '#9aa9b6'
                            for x in range(indicator.left(), indicator.right() + 1)
                            for y in range(indicator.top(), indicator.bottom() + 1)))
        box.click()
        self.assertTrue(box.isChecked())
        panel.profile_angle_limit.checkbox.click()
        self.app.processEvents()
        self.assertTrue(box.isEnabled())
        self.assertTrue(box.isChecked())
        self.assertEqual(box.palette().color(QPalette.ColorGroup.Active, QPalette.ColorRole.WindowText).name(), '#152536')
        box.click()
        self.assertFalse(box.isChecked())

    def test_binding_exact_profile_angle_and_restores_free_angle(self):
        for adapter in ('orca_slicer', 'prusa_slicer'):
            with self.subTest(adapter=adapter):
                w = self.window(adapter=adapter)
                box = w.profile_angle_limit.checkbox
                self.assertTrue(box.isEnabled())
                box.click()
                self.assertEqual(w.maximum_expansion_angle_spin.value(), 23.5)
                self.assertFalse(w.maximum_expansion_angle_spin.isEnabled())
                self.assertAlmostEqual(w.collect_settings().maximum_expansion_angle_deg, 66.5)
                self.assertTrue(w.collect_settings().limit_expansion_to_profile)
                box.click()
                self.assertTrue(w.maximum_expansion_angle_spin.isEnabled())
                self.assertEqual(w.maximum_expansion_angle_spin.value(), 40)

    def test_auto_bound_angle_is_visibly_grey_and_restores_background(self):
        w = self.window()
        w._apply_style()
        spin = w.maximum_expansion_angle_spin
        spin.ensurePolished()
        def background():
            return spin.grab().toImage().pixelColor(10, 10).name()
        free_background = background()
        spin.setValue(23.5)
        spin.selectAll()
        self.assertTrue(spin.lineEdit().hasSelectedText())
        w.profile_angle_limit.checkbox.click()
        self.app.processEvents()
        self.assertFalse(spin.isEnabled())
        self.assertFalse(spin.lineEdit().hasSelectedText())
        self.assertEqual(background(), '#f1f4f6')
        self.assertNotEqual(background(), free_background)
        w.profile_angle_limit.checkbox.click()
        self.app.processEvents()
        self.assertTrue(spin.isEnabled())
        self.assertEqual(background(), free_background)

    def test_small_profile_angle_validates_and_persists_free_value(self):
        w = self.window(15)
        w.profile_angle_limit.checkbox.click()
        self.assertEqual(w.maximum_expansion_angle_spin.value(), 15)
        self.assertEqual(w.maximum_expansion_angle_spin.minimum(), 15)
        self.assertEqual(w.profile_angle_limit.applied_threshold, 15)

        validate_solid_settings(w.collect_settings())
        w._save_user_settings(strict=True)
        saved, _ = w.settings_store.load()
        self.assertTrue(saved.limit_expansion_to_profile)
        self.assertEqual(saved.maximum_expansion_angle_deg, 50)
        w.profile_match_result = replace(w.profile_match_result, user_confirmed=False)
        w._refresh_profile_angle_binding()
        self.assertFalse(w.profile_angle_limit.checkbox.isEnabled())
        self.assertEqual(w.maximum_expansion_angle_spin.value(), 40)
        self.assertTrue(w.maximum_expansion_angle_spin.isEnabled())
        w.profile_match_result = replace(w.profile_match_result, user_confirmed=True)
        w._refresh_profile_angle_binding()
        self.assertEqual(w.maximum_expansion_angle_spin.value(), 15)
        w.profile_angle_limit.checkbox.click()
        self.assertEqual(w.maximum_expansion_angle_spin.value(), 40)
        self.assertEqual(w.maximum_expansion_angle_spin.minimum(), 20)
        w.maximum_expansion_angle_spin.setValue(15)
        self.assertEqual(w.maximum_expansion_angle_spin.value(), 20)

    def test_unbinding_immediately_restores_reset_for_a_modified_free_angle(self):
        w = self.window()
        spin = w.maximum_expansion_angle_spin
        reset = w.maximum_expansion_angle_setting.reset_button
        spin.setValue(37)
        self.assertTrue(reset.isEnabled())
        w.profile_angle_limit.checkbox.click()
        self.assertFalse(reset.isEnabled())
        w.profile_angle_limit.checkbox.click()
        self.assertEqual(spin.value(), 37)
        self.assertTrue(reset.isEnabled())
        reset.click()
        self.assertEqual(spin.value(), 40)
        self.assertFalse(reset.isEnabled())
        # A profile/free value match still requires the button state to change.
        spin.setValue(23.5)
        w.profile_angle_limit.checkbox.click()
        self.assertFalse(reset.isEnabled())
        w.profile_angle_limit.checkbox.click()
        self.assertEqual(spin.value(), 23.5)
        self.assertTrue(reset.isEnabled())

    def test_automatic_minimum_and_warning_boundaries(self):
        w = self.window()
        w.workflow.set_slicer_step_visible(True)
        w.workflow.source_validation_succeeded('STL', analysis_complete=True)
        w.workflow.slicer_succeeded('Testslicer')
        w.workflow.complete_preparation()
        w.automatic_generation_card.click()
        w.simulate_tower_without_supports_checkbox.setChecked(True)
        row = w.maximum_expansion_angle_setting
        spin = w.maximum_expansion_angle_spin
        for angle in (40, 35, 30, 29.1):
            spin.setValue(angle)
            self.assertEqual(row.message_label.text(), '')
        for angle in (29, 28.9, 28, 20):
            spin.setValue(angle)
            self.assertIn('Vorsicht: Der aktuelle Aufweitungswinkel erzeugt einen sehr starken Überhang.',
                          row.message_label.text())
            self.assertNotIn('Haftungs-', row.message_label.text())
        spin.setValue(15)
        self.assertEqual(spin.value(), 20)
        self.assertEqual(w.collect_settings().maximum_expansion_angle_deg, 70)
        self.assertTrue(w.validate_form())

    def ready_angle_window(self, threshold=23.5):
        w = self.window(threshold)
        w.workflow.set_slicer_step_visible(True)
        w.workflow.source_validation_succeeded('STL', analysis_complete=True)
        w.workflow.slicer_succeeded('Testslicer')
        w.workflow.complete_preparation()
        w.automatic_generation_card.click()
        w.simulate_tower_without_supports_checkbox.setChecked(True)
        self.assertTrue(w._phase17_static_valid)
        return w

    def enter_invalid_expansion(self, w, text='19'):
        spin = w.maximum_expansion_angle_spin
        spin.lineEdit().setText(text)
        self.assertFalse(w._phase17_static_valid)
        self.assertIn('maximum_expansion_angle_deg', w._incomplete_setting_names)
        self.assertTrue(spin.property('invalid'))

    def assert_expansion_recovered(self, w):
        self.assertTrue(w.maximum_expansion_angle_spin.hasAcceptableInput())
        self.assertNotIn('maximum_expansion_angle_deg', w._incomplete_setting_names)
        self.assertFalse(w.maximum_expansion_angle_spin.property('invalid'))
        self.assertEqual(w.maximum_expansion_angle_setting._error_messages, ())
        self.assertTrue(w._phase17_static_valid)

    def test_spin_arrows_clear_rejected_angle_even_without_a_value_change(self):
        for subcontrol in (QStyle.SubControl.SC_SpinBoxUp, QStyle.SubControl.SC_SpinBoxDown):
            with self.subTest(arrow=subcontrol):
                w = self.ready_angle_window()
                spin = w.maximum_expansion_angle_spin
                self.enter_invalid_expansion(w)
                previous = spin.value()
                option = QStyleOptionSpinBox()
                spin.initStyleOption(option)
                rect = spin.style().subControlRect(QStyle.ComplexControl.CC_SpinBox, option, subcontrol, spin)
                QTest.mouseClick(spin, Qt.MouseButton.LeftButton, pos=rect.center())
                self.assertGreaterEqual(spin.value(), 20)
                self.assert_expansion_recovered(w)
                # The first correction can retain the last valid value.
                self.assertLessEqual(abs(spin.value() - previous), spin.singleStep())

    def test_profile_binding_clears_rejected_angle_and_restores_valid_free_value(self):
        for threshold in (15, 23.5, 40):
            with self.subTest(threshold=threshold):
                w = self.ready_angle_window(threshold)
                self.enter_invalid_expansion(w)
                w.profile_angle_limit.checkbox.click()
                self.assertEqual(w.maximum_expansion_angle_spin.value(), threshold)
                self.assert_expansion_recovered(w)
                w.profile_angle_limit.checkbox.click()
                self.assertEqual(w.maximum_expansion_angle_spin.value(), 40)
                self.assert_expansion_recovered(w)

    def test_finishing_rejected_angle_edit_clears_error_after_qt_correction(self):
        w = self.ready_angle_window()
        self.enter_invalid_expansion(w)
        QTest.keyClick(w.maximum_expansion_angle_spin, Qt.Key.Key_Return)
        self.assert_expansion_recovered(w)

    def test_validating_current_input_clears_stale_flags_but_preserves_other_errors(self):
        w = self.ready_angle_window()
        self.enter_invalid_expansion(w)
        w.target_time_spin.lineEdit().clear()
        from PySide6.QtCore import QSignalBlocker
        with QSignalBlocker(w.maximum_expansion_angle_spin):
            w.maximum_expansion_angle_spin.setValue(30)
        self.assertFalse(w.validate_form())
        self.assertNotIn('maximum_expansion_angle_deg', w._incomplete_setting_names)
        self.assertIn('target_layer_time_s', w._incomplete_setting_names)
        self.assertFalse(w.maximum_expansion_angle_spin.property('invalid'))
        self.assertTrue(w.target_time_spin.property('invalid'))

    def test_generation_action_recovers_after_correcting_rejected_angle(self):
        from cooling_tower.models import ProfileFeasibilityAssessment
        from test_phase9 import make_snapshot

        for correction in ('arrow', 'profile', 'reset', 'typed'):
            with self.subTest(correction=correction):
                w = self.ready_angle_window()
                w.current_source_path = w.source_artifact.original_path
                w.current_gcode_path = w.current_source_path
                w.analysis_snapshot = make_snapshot(w.current_source_path, (1, 1, 1))
                w._refresh_tower_assessment()
                feasible = ProfileFeasibilityAssessment(tower_required=True, feasible=True)
                w._on_feasibility_succeeded(w._feasibility_request_id, feasible)
                self.assertTrue(w.preview_button.isEnabled())
                self.enter_invalid_expansion(w)
                self.assertFalse(w.preview_button.isEnabled())
                if correction == 'arrow':
                    w.maximum_expansion_angle_spin.stepUp()
                elif correction == 'profile':
                    w.profile_angle_limit.checkbox.click()
                elif correction == 'reset':
                    w.maximum_expansion_angle_setting.reset_to_default()
                else:
                    w.maximum_expansion_angle_spin.lineEdit().setText('30')
                self.assert_expansion_recovered(w)
                w._on_feasibility_succeeded(w._feasibility_request_id, feasible)
                self.assertIsNone(w._generation_block_reason())
                self.assertTrue(w.preview_button.isEnabled())

    def test_fractional_profile_angle_stays_exact_and_does_not_replace_the_free_value(self):
        w = self.window(23.555)
        w.profile_angle_limit.checkbox.click()
        for _ in range(3):
            w._refresh_profile_angle_binding()
            self.assertAlmostEqual(w.maximum_expansion_angle_spin.value(), 23.555)
            self.assertEqual(w.maximum_expansion_angle_spin.cleanText(), '23,555')
            self.assertEqual(w.profile_angle_limit.state.free_angle_deg, 50)
        w.profile_angle_limit.checkbox.click()
        self.assertEqual(w.maximum_expansion_angle_spin.value(), 40)

    def test_threshold_parser_rejects_automatic_unknown_and_invalid_values(self):
        for adapter, key in (('orca_slicer','support_threshold_angle'),
                             ('prusa_slicer','support_material_threshold'),
                             ('bambu_studio','support_threshold_angle'),
                             ('anycubic_slicer_next','support_threshold_angle')):
            for raw, expected in ((['23.5'],23.5), ('45',45), (0,None), (90,None),
                                  (True,None), ('nan',None), ('inf',None), (None,None),
                                  (['23','42'],None)):
                with self.subTest(adapter=adapter, raw=raw):
                    profile = SimpleNamespace(installation=SimpleNamespace(adapter_id=adapter),
                                              effective_values={key:raw})
                    self.assertEqual(profile_support_threshold(profile), expected)

    def test_manual_numeric_entry_uses_horizontal_angle_and_binding_is_reversible(self):
        _, _, reference, _, _ = create_fixture(self, joint=True, count=200)
        reference = replace(reference, context=replace(reference.context, support_threshold_angle_deg=30))
        panel = ManualGenerationPanel(ManualSettings(limit_expansion_to_profile=False))
        self.addCleanup(panel.close)
        panel.initialize(reference)
        panel.resize(1400, 900)
        panel.show()
        self.app.processEvents()
        self.assertEqual(panel.profile_angle_limit.suffix.text(), ' begrenzen')
        spin = panel.editors['expansion_angle_deg']
        self.assertEqual(spin.value(), 40)
        spin.setValue(35)
        self.assertEqual(panel.settings.expansion_angle_deg, 55)
        panel.profile_angle_limit.checkbox.click()
        self.assertTrue(panel.settings.limit_expansion_to_profile)
        self.assertTrue(panel.settings.expansion_enabled)
        self.assertEqual(spin.value(), 30)
        self.assertFalse(spin.isEnabled())
        self.assertEqual(panel.settings_for_persistence().expansion_angle_deg, 55)
        panel.undo()
        self.assertFalse(panel.settings.limit_expansion_to_profile)
        self.assertEqual(spin.value(), 35)
        panel.redo()
        self.assertTrue(panel.settings.limit_expansion_to_profile)
        panel.profile_angle_limit.checkbox.click()
        self.assertEqual(spin.value(), 35)
        self.assertTrue(spin.isEnabled())
        self.assertTrue(panel.rows['expansion_angle_deg'].reset_button.isEnabled())
        panel.undo()
        self.assertTrue(panel.settings.limit_expansion_to_profile)
        self.assertEqual(spin.value(), 30)
        panel.profile_angle_limit.checkbox.click()
        self.assertEqual(spin.value(), 35)
        panel.set_busy(True)
        self.assertFalse(panel.profile_angle_limit.checkbox.isEnabled())
        panel.set_busy(False)
        self.assertTrue(panel.profile_angle_limit.checkbox.isEnabled())

    def test_manual_allows_shallow_angles_only_from_profile_with_persistent_warning(self):
        _, _, reference, _, _ = create_fixture(self, joint=True, count=200)
        reference = replace(reference, context=replace(reference.context, support_threshold_angle_deg=15))
        panel = ManualGenerationPanel(ManualSettings(limit_expansion_to_profile=False))
        self.addCleanup(panel.close)
        panel.initialize(reference)
        spin = panel.editors['expansion_angle_deg']
        for angle in (35, 29.1):
            spin.setValue(angle)
            self.assertTrue(panel.expansion_warning.isHidden())
        spin.setValue(29)
        self.assertFalse(panel.expansion_warning.isHidden())
        spin.setValue(15)
        self.assertEqual(spin.value(), 20)
        self.assertEqual(panel.settings.expansion_angle_deg, 70)
        self.assertFalse(panel.expansion_warning.isHidden())
        row = panel.rows['expansion_angle_deg']
        row.set_error('Testfehler')
        row.set_error(None)
        self.assertFalse(panel.expansion_warning.isHidden())
        panel.profile_angle_limit.checkbox.click()
        self.assertEqual(spin.value(), 15)
        self.assertFalse(spin.isEnabled())

    def test_nonpositive_profile_angles_use_thirty_degrees_in_both_modes(self):
        _, _, reference, _, _ = create_fixture(self, joint=True, count=200)
        for raw in (0, -1, -25):
            with self.subTest(raw=raw):
                w = self.window(raw)
                self.assertTrue(w.profile_angle_limit.checkbox.isEnabled())
                w.profile_angle_limit.checkbox.click()
                self.assertTrue(w.profile_angle_limit.state.active)
                self.assertEqual(w.maximum_expansion_angle_spin.value(), 30)
                self.assertEqual(w.profile_angle_limit.profile_warning, PROFILE_ANGLE_FALLBACK_NOTICE)
                self.assertEqual(w.maximum_expansion_angle_setting._helper_text, '')
                self.assertIn(PROFILE_ANGLE_FALLBACK_NOTICE, w.profile_angle_limit.threshold_hint.hint)
                validate_solid_settings(w.collect_settings())
                w.profile_angle_limit.checkbox.click()
                self.assertEqual(w.maximum_expansion_angle_spin.value(), 40)
                self.assertEqual(w.profile_angle_limit.profile_warning, '')

                panel = ManualGenerationPanel(ManualSettings(limit_expansion_to_profile=False))
                self.addCleanup(panel.close)
                panel.initialize(replace(reference, context=replace(reference.context,
                                                                   support_threshold_angle_deg=raw)))
                panel.profile_angle_limit.checkbox.click()
                self.assertTrue(panel.settings.limit_expansion_to_profile)
                self.assertEqual(panel.editors['expansion_angle_deg'].value(), 30)
                self.assertFalse(panel.editors['expansion_angle_deg'].isEnabled())
                self.assertEqual(panel.expansion_warning.text(), '')
                self.assertTrue(panel.expansion_warning.isHidden())
                self.assertIn(PROFILE_ANGLE_FALLBACK_NOTICE, panel.profile_angle_limit.threshold_hint.hint)
                self.assertEqual(panel.settings_for_persistence().expansion_angle_deg, 50)
                panel.profile_angle_limit.checkbox.click()
                self.assertEqual(panel.editors['expansion_angle_deg'].value(), 40)
                self.assertEqual(panel.profile_angle_limit.profile_warning, '')

    def test_positive_fractional_profile_angles_below_twenty_remain_exact(self):
        _, _, reference, _, _ = create_fixture(self, joint=True, count=200)
        for threshold in (19.75, 15, 0.05, 1e-13):
            with self.subTest(threshold=threshold):
                w = self.window(threshold)
                w.profile_angle_limit.checkbox.click()
                self.assertAlmostEqual(w.maximum_expansion_angle_spin.value(), threshold)
                self.assertGreater(w.maximum_expansion_angle_spin.value(), 0)
                self.assertEqual(w.profile_angle_limit.profile_warning, '')
                validate_solid_settings(w.collect_settings())
                panel = ManualGenerationPanel(ManualSettings(limit_expansion_to_profile=False))
                self.addCleanup(panel.close)
                panel.initialize(replace(reference, context=replace(reference.context,
                                                                   support_threshold_angle_deg=threshold)))
                panel.profile_angle_limit.checkbox.click()
                self.assertAlmostEqual(panel.editors['expansion_angle_deg'].value(), threshold)
                self.assertGreater(panel.editors['expansion_angle_deg'].value(), 0)
                self.assertFalse(panel.editors['expansion_angle_deg'].isEnabled())

    def test_binding_parser_preserves_nonpositive_values_without_affecting_support_detection(self):
        for adapter, key in (('orca_slicer', 'support_threshold_angle'),
                             ('bambu_studio', 'support_threshold_angle'),
                             ('anycubic_slicer_next', 'support_threshold_angle'),
                             ('prusa_slicer', 'support_material_threshold')):
            for raw, expected in ((0, 0), (['-12'], -12), ('0.05', .05), ('15', 15),
                                  (True, None), ('nan', None), ('inf', None),
                                  (90, None), (None, None), (['1', '2'], None)):
                with self.subTest(adapter=adapter, raw=raw):
                    profile = SimpleNamespace(installation=SimpleNamespace(adapter_id=adapter),
                                              effective_values={key: raw})
                    self.assertEqual(profile_binding_threshold(profile), expected)
                    if expected is not None and expected <= 0:
                        self.assertIsNone(profile_support_threshold(profile))

    def test_profile_help_is_shared_and_has_headings_bullets_and_indented_choices(self):
        w = self.window()
        panel = ManualGenerationPanel(ManualSettings(limit_expansion_to_profile=False))
        self.addCleanup(panel.close)
        for control in (w.profile_angle_limit, panel.profile_angle_limit):
            self.assertEqual(control.threshold_hint.hint, PROFILE_ANGLE_HINT)
            self.assertIn('<b>Was ist das?</b>', control.threshold_hint.hint)
            self.assertIn('<b>Sollte ich das aktivieren?</b>', control.threshold_hint.hint)
            self.assertEqual(control.threshold_hint.hint.count('&#8226;'), 2)
            self.assertEqual(control.threshold_hint.hint.count('&nbsp;&nbsp;...du'), 3)
            self.assertIn('Ja, wenn...<br>', control.threshold_hint.hint)
            self.assertIn('Nein, wenn...<br>', control.threshold_hint.hint)
            self.assertNotIn('margin-top:16px', control.threshold_hint.hint)
            self.assertIn('den horizontalen Grenzwinkel', control.threshold_hint.hint)
            self.assertIn('für die betreffenden Stellen', control.threshold_hint.hint)
            self.assertIn('Hier gilt: Je niedriger der Wert, desto flacher die Überhänge '
                          'und schwerer zu drucken.', control.threshold_hint.hint)

    def test_manual_bound_angle_uses_disabled_background_and_restores_it_on_unbinding(self):
        _, _, reference, _, _ = create_fixture(self, joint=True, count=200)
        reference = replace(reference, context=replace(reference.context, support_threshold_angle_deg=30))
        panel = ManualGenerationPanel(ManualSettings(limit_expansion_to_profile=False))
        self.addCleanup(panel.close)
        panel.setStyleSheet((ROOT / 'src/cooling_tower/gui/styles.qss').read_text(encoding='utf-8'))
        panel.initialize(reference)
        panel.resize(1400, 900)
        panel.show()
        self.app.processEvents()
        spin = panel.editors['expansion_angle_deg']
        def background():
            return spin.grab().toImage().pixelColor(10, 10).name()
        free_background = background()
        panel.profile_angle_limit.checkbox.click()
        self.assertEqual(spin.value(), 30)
        self.assertFalse(spin.isEnabled())
        self.assertEqual(background(), '#f1f4f6')
        self.assertNotEqual(background(), free_background)
        panel.profile_angle_limit.checkbox.click()
        self.assertTrue(spin.isEnabled())
        self.assertEqual(background(), free_background)
        panel.undo()
        self.assertFalse(spin.isEnabled())
        self.assertEqual(background(), '#f1f4f6')

    def test_profile_link_opens_the_same_popover_and_changes_color_on_hover(self):
        w = self.window()
        link = w.profile_angle_limit.threshold_hint
        normal = link.styleSheet()
        link.enterEvent(QEnterEvent(QPointF(1,1), QPointF(1,1), QPointF(1,1)))
        self.assertNotEqual(link.styleSheet(), normal)
        self.assertFalse(w._bounded_hint_popover.isHidden())
        self.assertIn('horizontalen Grenzwinkel', w._bounded_hint_popover.label.text())
        link.leaveEvent(QEvent(QEvent.Type.Leave))
        self.assertEqual(link.styleSheet(), normal)
        self.assertTrue(w._bounded_hint_popover.isHidden())

    def test_manual_binding_rejects_incompatible_existing_shape_atomically(self):
        _, _, reference, _, _ = create_fixture(self, joint=True, count=200)
        reference = replace(reference, context=replace(reference.context, support_threshold_angle_deg=89))
        panel = ManualGenerationPanel(ManualSettings(limit_expansion_to_profile=False))
        self.addCleanup(panel.close)
        panel.initialize(reference)
        panel.move('top_width', 35, panel.draft.height_mm)
        previous = panel.draft
        panel.profile_angle_limit.checkbox.click()
        self.assertEqual(panel.draft, previous)
        self.assertFalse(panel.settings.limit_expansion_to_profile)
        self.assertFalse(panel.profile_angle_limit.checkbox.isChecked())
        self.assertIn('Horizontalen', panel.rows['expansion_angle_deg'].message_label.text())

    def test_subline_keeps_existing_grid_positions_and_clears_main_label(self):
        w = self.window()
        w.resize(1400, 1000)
        w.show()
        w.workflow.set_slicer_step_visible(True)
        w.workflow.source_validation_succeeded('STL', analysis_complete=True)
        w.workflow.slicer_succeeded('Testslicer')
        w.workflow.complete_preparation()
        w.automatic_generation_card.click()
        w.geometry_group.setChecked(True)
        w.geometry_settings_group.setChecked(True)
        self.app.processEvents()
        row = w.maximum_expansion_angle_setting
        line = w.profile_angle_limit
        self.assertTrue(row.isVisible())
        before = tuple((widget.pos(), widget.size()) for widget in
                       (row.info_button, row.label, row.editor, row.reset_button))
        line.hide()
        self.app.processEvents()
        self.assertEqual(before, tuple((widget.pos(), widget.size()) for widget in
                         (row.info_button, row.label, row.editor, row.reset_button)))
        line._position()
        origin = row.label.mapTo(line.parentWidget(), row.label.rect().topLeft())
        self.assertEqual(line.x(), origin.x())
        self.assertGreaterEqual(line.y(), origin.y()+(row.label.height()+row.label.fontMetrics().height())//2)
        self.assertLessEqual(line.geometry().right(), origin.x()+row.label.width())


class HorizontalAngleMigrationTests(unittest.TestCase):
    def test_exported_settings_declare_the_storage_reference_and_reject_other_units(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'settings.json'
            settings = GenerationSettings(maximum_expansion_angle_deg=60, maximum_contraction_angle_deg=65)
            save_generation_settings(settings, path)
            self.assertEqual(load_generation_settings(path), settings)
            payload = json.loads(path.read_text())
            self.assertEqual(payload['angle_storage_reference'], 'vertical')
            payload['angle_storage_reference'] = 'horizontal'
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, 'unbekannten Bezug'):
                load_generation_settings(path)

    def test_manual_binding_type_future_file_and_external_change_are_protected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'manual.json'
            path.write_text(json.dumps({'manual_settings_schema_version':19,
                                       'manual':{'limit_expansion_to_profile':'true'}}))
            store = ManualSettingsStore(path)
            self.assertTrue(store.load().limit_expansion_to_profile)
            original = b'{"manual_settings_schema_version":99,"manual":{"limit_expansion_to_profile":true}}'
            path.write_bytes(original)
            store = ManualSettingsStore(path)
            settings = store.load()
            with self.assertRaises((OSError, VersionedDocumentError)):
                store.save(settings)
            self.assertEqual(path.read_bytes(), original)
            store.recover()
            settings = store.load()
            self.assertTrue(settings.limit_expansion_to_profile)
            external = path.read_bytes()+b' '
            path.write_bytes(external)
            with self.assertRaises((OSError, VersionedDocumentError)):
                store.save(replace(settings, limit_expansion_to_profile=True))
            self.assertEqual(path.read_bytes(), external)

    def test_atomic_manual_save_failure_preserves_original_and_next_save_recovers(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'manual.json'
            path.write_text(json.dumps({'manual_settings_schema_version':19,'manual':{}}))
            store = ManualSettingsStore(path)
            settings = store.load()
            original = path.read_bytes()
            with patch('cooling_tower.persistence.versioned_json.os.replace', side_effect=OSError('test replace failed')):
                with self.assertRaises(OSError):
                    store.save(replace(settings, limit_expansion_to_profile=True))
            self.assertEqual(path.read_bytes(), original)
            self.assertFalse(list(path.parent.glob('*.tmp')))
            settings = store.load()
            store.save(replace(settings, limit_expansion_to_profile=True))
            self.assertTrue(store.load().limit_expansion_to_profile)

    def test_direct_and_multistep_preserve_angles_and_backup_originals(self):
        for version in (20,21):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary)/'settings.json'
                original = json.dumps({'settings_schema_version':version, 'generation':{
                    'maximum_expansion_angle_deg':53, 'maximum_contraction_angle_deg':57}}).encode()
                path.write_bytes(original)
                store = UserSettingsStore(path, ROOT/'config/default_settings.json')
                settings, _ = store.load()
                self.assertEqual(settings.maximum_expansion_angle_deg, 53)
                self.assertEqual(settings.maximum_contraction_angle_deg, 57)
                self.assertFalse(settings.limit_expansion_to_profile)
                self.assertEqual(store.last_migration_backup.read_bytes(), original)

    def test_manual_migrations_preserve_vertical_storage_and_disable_new_binding(self):
        for version in (17,18):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary)/'manual.json'
                original = json.dumps({'manual_settings_schema_version':version,'manual':{
                    'expansion_angle_deg':53, 'contraction_angle_deg':57}}).encode()
                path.write_bytes(original)
                store = ManualSettingsStore(path)
                settings = store.load()
                self.assertEqual(settings.expansion_angle_deg, 53)
                self.assertEqual(settings.contraction_angle_deg, 57)
                self.assertFalse(settings.limit_expansion_to_profile)
                self.assertEqual(json.loads(path.read_text())['manual_settings_schema_version'], MANUAL_SCHEMA_VERSION)
                backups = list(path.parent.glob('manual.json*.backup*'))
                self.assertTrue(any(p.read_bytes() == original for p in backups))
