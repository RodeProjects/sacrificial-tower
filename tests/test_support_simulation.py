from dataclasses import replace
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import PropertyMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from cooling_tower.models import OccupiedBounds
from cooling_tower.preview import LineSegment3D, Point3D
from cooling_tower.gui.main_window import MainWindow
from cooling_tower.models import SourceKind
from cooling_tower.persistence import PreSliceCache
from cooling_tower.services import SourcePreSliceError, build_preslice_cache_key
from cooling_tower.slicers import ProfileConfirmation, ProfileCatalog
from cooling_tower.slicers.support_simulation import (
    can_offer_support_simulation, tower_support_warning_angle,
    with_simulated_supports, simulated_support_settings,
)
from cooling_tower.calibration.slice_evaluator import build_calibration_profile
from cooling_tower.preview import PreviewExportResult, OutputMode
import test_source_preslice as preslice_tests
from test_source_preslice import FakeSliceAdapter


class SupportAdapter(FakeSliceAdapter):
    adapter_id = 'anycubic_slicer_next'

    def slice_model(self, request):
        self.copied_process = json.loads(request.profile.process.path.read_text(encoding='utf-8'))
        if self.mode == 'needs-supports' and self.copied_process.get('enable_support') != '1':
            self.requests.append(request)
            return replace(self._result(request, None, success=False), return_code=-100)
        return super().slice_model(request)


class SupportSimulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.fixture = preslice_tests.SourcePreSliceServiceTests()
        self.fixture.setUp()
        f = self.fixture
        installation = replace(f.installation, adapter_id='anycubic_slicer_next')
        profile = replace(f.match.selected.effective_profile, installation=installation)
        f.process.path.write_text(json.dumps({'name': 'process', 'enable_support': '0',
            'support_type': 'tree(auto)', 'support_threshold_angle': '23',
            'support_top_z_distance': '0.18'}), encoding='utf-8')
        f.match = replace(f.match, execution_slicer=installation,
                          selected=replace(f.match.selected, effective_profile=profile))
        f.confirmation = ProfileConfirmation.from_result(f.match, f.validation.source_artifact)
        self.originals = {p: p.read_bytes() for p in (f.source, *profile.source_paths)}

    def tearDown(self):
        for path, data in self.originals.items():
            self.assertEqual(path.read_bytes(), data)
        self.fixture.tearDown()

    def run_preslice(self, adapter, simulated=False):
        f = self.fixture
        return f.service.run(stl_validation=f.validation, profile_match=f.match,
            confirmation=f.confirmation, adapter=adapter, simulate_supports=simulated)

    def test_offer_retry_changes_only_activation_and_never_repeats_offer(self):
        adapter = SupportAdapter('needs-supports')
        with self.assertRaises(SourcePreSliceError) as caught:
            self.run_preslice(adapter)
        self.assertTrue(caught.exception.support_simulation_available)
        result = self.run_preslice(adapter, True)
        try:
            self.assertTrue(result.supports_simulated)
            self.assertEqual(adapter.copied_process['enable_support'], '1')
            self.assertEqual(adapter.copied_process['support_type'], 'tree(auto)')
            self.assertEqual(adapter.copied_process['support_threshold_angle'], '23')
            self.assertEqual(adapter.copied_process['support_top_z_distance'], '0.18')
        finally:
            result.cleanup()
        failure = replace(FakeSliceAdapter._result(adapter.requests[-1], None, success=False), return_code=-100)
        profile = self.fixture.match.selected.effective_profile
        for changed in (replace(failure, cancelled=True), replace(failure, timed_out=True),
                        replace(failure, crashed=True), replace(failure, return_code=-17)):
            self.assertFalse(can_offer_support_simulation(changed, profile))
        self.assertFalse(can_offer_support_simulation(failure, with_simulated_supports(profile)))

    def test_cache_distinguishes_simulation_and_restores_its_state(self):
        f = self.fixture
        f.service.cache = PreSliceCache(f.app_root / 'cache')
        adapter = SupportAdapter()
        for simulated, cached in ((False, False), (True, False), (True, True), (False, True)):
            result = self.run_preslice(adapter, simulated)
            try:
                self.assertEqual(result.cache_hit, cached)
                self.assertEqual(result.supports_simulated, simulated)
            finally:
                result.cleanup()
        self.assertEqual(len(adapter.requests), 2)

    def test_calibration_copies_retain_approved_supports(self):
        f = self.fixture
        profile = with_simulated_supports(f.match.selected.effective_profile)
        for full in (False, True):
            copied, overrides = build_calibration_profile(profile, f.app_root / str(full),
                simulate_full_tower_infill=full, resolved_profiles=())
            values = json.loads(copied.process.path.read_text())
            self.assertEqual(values['enable_support'], '1')
            self.assertEqual(values['support_threshold_angle'], '23')
            self.assertEqual(overrides['enable_support'], '1')

    def test_tower_support_threshold_converts_horizontal_to_vertical(self):
        profile = self.fixture.match.selected.effective_profile
        profile = replace(profile, effective_values={
            **profile.effective_values,
            'enable_support': '1',
            'support_threshold_angle': '23',
        })
        self.assertEqual(tower_support_warning_angle(profile), 67.0)
        self.assertIsNone(tower_support_warning_angle(replace(
            profile, effective_values={**profile.effective_values, 'enable_support': '0'}
        )))
        self.assertIsNone(tower_support_warning_angle(replace(
            profile, effective_values={**profile.effective_values, 'support_threshold_angle': '0'}
        )))

    def test_tower_support_override_only_changes_disposable_profile(self):
        profile = with_simulated_supports(self.fixture.match.selected.effective_profile)
        copied, overrides = build_calibration_profile(
            profile, self.fixture.app_root / 'without_supports',
            simulate_tower_without_supports=True, resolved_profiles=(),
        )
        values = json.loads(copied.process.path.read_text(encoding='utf-8'))
        self.assertEqual(values['enable_support'], '0')
        self.assertEqual(overrides['enable_support'], '0')
        self.assertTrue(profile.supports_simulated)

    def make_window(self):
        f = self.fixture
        window = MainWindow(user_settings_path=f.app_root / 'settings.json',
            enable_update_check=False, enable_startup_slicer_discovery=False)
        window.source_artifact = f.validation.source_artifact
        window.current_source_kind = SourceKind.STL
        window.stl_validation_result = f.validation
        window.profile_match_result = f.match
        window.confirmed_profile_context = f.confirmation
        window._preslice_request_id = 12
        return window

    def test_modular_support_style_policies_and_legacy_preservation(self):
        profile = self.fixture.match.selected.effective_profile
        for adapter_id, version, expected in (
            ('orca_slicer', '2.4.2', {'enable_support':'1', 'support_type':'tree(auto)',
                                   'support_style':'default', 'independent_support_layer_height':'0'}),
            ('prusa_slicer', '2.9.6', {'support_material':'1', 'support_material_auto':'1',
                                    'support_material_style':'organic'}),
            ('prusa_slicer', '2.5.2', {'support_material':'1', 'support_material_auto':'1'}),
            ('bambu_studio', '2.0', {'enable_support':'1'}),
            ('anycubic_slicer_next', '1.3', {'enable_support':'1'}),
        ):
            with self.subTest(adapter=adapter_id, version=version):
                changed = replace(profile, installation=replace(profile.installation,
                                  adapter_id=adapter_id, version=version))
                self.assertEqual(simulated_support_settings(changed), expected)
                simulated = with_simulated_supports(changed)
                self.assertEqual(simulated.effective_values, {**profile.effective_values, **expected})
                self.assertFalse(changed.supports_simulated)

    def recovery_window(self, adapter='orca_slicer', value='0', confirmed=True):
        window = self.make_window()
        self.addCleanup(window.close)
        selected = window.profile_match_result.selected
        key = 'support_material' if adapter == 'prusa_slicer' else 'enable_support'
        values = {} if value is None else {key:value}
        profile = replace(selected.effective_profile,
            installation=replace(selected.effective_profile.installation,adapter_id=adapter,version='2.9.6'),
            effective_values=values)
        window.profile_match_result = replace(window.profile_match_result, user_confirmed=confirmed,
                                             selected=replace(selected,effective_profile=profile))
        window._refresh_phase17_actions()
        return window

    def test_first_layer_recovery_advice_is_conditional_and_does_not_parse_error_html(self):
        for adapter,value,confirmed,offered in (
            ('orca_slicer','0',True,True), ('prusa_slicer','0',True,True),
            ('orca_slicer','1',True,False), ('orca_slicer',None,True,False),
            ('orca_slicer','unknown',True,False), ('orca_slicer','0',False,False),
            ('unsupported','0',True,False),
        ):
            with self.subTest(adapter=adapter,value=value,confirmed=confirmed):
                window = self.recovery_window(adapter,value,confirmed)
                message = 'Vorschau fehlgeschlagen: Erste Schicht ohne Auflagefläche <a href="bad">Fehler</a>'
                window._set_main_status(message,state='error')
                hint = window.source_support_recovery
                self.assertEqual(not hint.isHidden(),offered)
                self.assertIn('<b>Stützen für STL-Objekt simulieren</b>',hint.label.text())
                self.assertNotIn('<a',hint.label.text())
                layout = hint.layout()
                self.assertEqual(layout.count(), 2)
                self.assertEqual(layout.itemAt(0).widget(), hint.label)
                self.assertEqual(layout.itemAt(1).widget(), hint.button)
                self.assertEqual(layout.direction().name, 'LeftToRight')
                self.assertTrue(layout.itemAt(1).alignment() & Qt.AlignmentFlag.AlignRight)
                self.assertEqual(window.status_label.text(),message)
                if offered:
                    window._set_main_status('Zeitlimit überschritten',state='error')
                    self.assertTrue(hint.isHidden())
                    window._set_main_status('Erste Schicht wird geprüft',state='running')
                    self.assertTrue(hint.isHidden())

    def test_recovery_button_activates_existing_option_and_rechecks_changed_profile(self):
        window = self.recovery_window('prusa_slicer')
        window._set_main_status('Erste Schicht hat keine Auflagefläche',state='error')
        with patch.object(window,'_invalidate_preview') as invalidate:
            window.source_support_recovery.button.click()
            self.assertTrue(window.simulate_source_supports_checkbox.isChecked())
            invalidate.assert_called_once()
        self.assertTrue(window.source_support_recovery.isHidden())
        window.simulate_source_supports_checkbox.setChecked(False)
        window.profile_match_result = replace(window.profile_match_result,user_confirmed=False)
        window.source_support_recovery.button.click()
        self.assertFalse(window.simulate_source_supports_checkbox.isChecked())

    def test_manual_recovery_and_running_job_guard(self):
        window = self.recovery_window()
        controller = window.manual_controller
        controller.panel.status_label.setText('Neuer manueller Lauf fehlgeschlagen: Erste Schicht ohne Auflagefläche')
        window._refresh_support_recovery()
        hint = controller.support_recovery
        self.assertFalse(hint.isHidden())
        with patch.object(window.background_job_manager,'has_active',return_value=True):
            window._refresh_support_recovery()
            self.assertFalse(hint.button.isEnabled())
            window._activate_source_support_recovery(manual=True)
            self.assertFalse(controller.panel.source_supports_checkbox.isChecked())
        window._refresh_support_recovery()
        hint.button.click()
        self.assertTrue(controller.panel.source_supports_checkbox.isChecked())
        self.assertFalse(window.simulate_source_supports_checkbox.isChecked())
        self.assertTrue(hint.isHidden())

    def test_angle_warning_appears_at_threshold_and_respects_override(self):
        window = self.make_window()
        self.addCleanup(window.close)
        selected = window.profile_match_result.selected
        profile = replace(selected.effective_profile, effective_values={
            **selected.effective_profile.effective_values,
            'enable_support': '1', 'support_threshold_angle': '23',
        })
        window.profile_match_result = replace(
            window.profile_match_result,
            selected=replace(selected, effective_profile=profile),
        )
        window.source_preslice_result = SimpleNamespace(supports_simulated=False)
        self.addCleanup(lambda: setattr(window, 'source_preslice_result', None))
        spin = window.maximum_expansion_angle_spin
        spin.blockSignals(True)
        spin.setValue(23)
        window._update_expansion_angle_warning()
        self.assertFalse(any('23°' in text for text in
                             window.maximum_expansion_angle_setting._warning_messages))
        spin.setValue(22.9)
        spin.blockSignals(False)
        window._update_expansion_angle_warning()
        self.assertTrue(any('23°' in text for text in
                            window.maximum_expansion_angle_setting._warning_messages))
        checkbox = window.simulate_tower_without_supports_checkbox
        checkbox.blockSignals(True)
        checkbox.setChecked(True)
        checkbox.blockSignals(False)
        window._update_expansion_angle_warning()
        self.assertFalse(any('23°' in text for text in
                             window.maximum_expansion_angle_setting._warning_messages))

    def test_support_warning_reflows_after_repeated_checkbox_changes(self):
        window = self.make_window()
        self.addCleanup(window.close)
        window.resize(900, 900)
        window.show()
        window.workflow.set_slicer_step_visible(True)
        window.workflow.source_validation_succeeded('STL', analysis_complete=True)
        window.workflow.slicer_succeeded('Testslicer')
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        selected = window.profile_match_result.selected
        profile = replace(selected.effective_profile, effective_values={
            **selected.effective_profile.effective_values,
            'enable_support': '1', 'support_threshold_angle': '23',
        })
        window.profile_match_result = replace(
            window.profile_match_result,
            selected=replace(selected, effective_profile=profile),
        )
        window.source_preslice_result = SimpleNamespace(supports_simulated=False)
        self.addCleanup(lambda: setattr(window, 'source_preslice_result', None))
        support_row = window.simulate_tower_without_supports_checkbox.parentWidget()
        timing_layout = window.timing_group.content_layout
        infill_row = window.full_infill_checkbox.parentWidget()
        self.assertEqual(timing_layout.indexOf(support_row), timing_layout.indexOf(infill_row) + 1)
        self.assertEqual(
            window.simulate_tower_without_supports_checkbox.text(),
            'Deaktivierte Turmstützen simulieren',
        )
        self.assertEqual(support_row.height(), infill_row.height())
        self.assertEqual(
            window.simulate_tower_without_supports_checkbox.height(),
            window.full_infill_checkbox.height(),
        )

        spin = window.maximum_expansion_angle_spin
        row = window.maximum_expansion_angle_setting
        following = window._setting_widgets['maximum_contraction_angle_deg']
        checkbox = window.simulate_tower_without_supports_checkbox
        spin.setValue(21)
        self.app.processEvents()
        self.assertIn(
            'Aktiviere die Einstellung <b>„Deaktivierte Turmstützen simulieren“</b>, '
            'um dies zu verhindern.',
            row.message_label.text(),
        )
        self.assertIn('<br>', row.message_label.text())
        expanded_height = row.height()
        expanded_card_height = window.geometry_settings_group.height()
        self.assertLess(row.geometry().bottom(), following.geometry().top())

        for checked, angle in ((True, 22), (False, 22), (True, 21), (False, 21)):
            checkbox.setChecked(checked)
            spin.setValue(angle)
            self.app.processEvents()
            self.assertEqual('23°' in row.message_label.text(), not checked)
            self.assertLess(row.geometry().bottom(), following.geometry().top())
            self.assertLessEqual(row.message_container.geometry().bottom(), row.height())
            if checked:
                self.assertLess(row.height(), expanded_height)
                self.assertLess(window.geometry_settings_group.height(), expanded_card_height)
            else:
                self.assertGreaterEqual(row.height(), expanded_height)
                self.assertGreaterEqual(window.geometry_settings_group.height(), expanded_card_height)

    def test_original_preview_explains_missing_tower_above_divider(self):
        window = self.make_window()
        self.addCleanup(window.close)
        window.show()
        window.workflow.set_slicer_step_visible(True)
        window.workflow.source_validation_succeeded('STL', analysis_complete=True)
        window.workflow.slicer_succeeded('Testslicer')
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        segment = LineSegment3D(Point3D(1, 1, 0.2), Point3D(2, 2, 0.2))
        window.source_preslice_result = SimpleNamespace(
            supports_simulated=False,
            preview_source_data=SimpleNamespace(
                object_segments=(segment,), source_segment_count=1,
                occupied_bounds=OccupiedBounds(1, 2, 1, 2),
            ),
        )
        self.addCleanup(lambda: setattr(window, 'source_preslice_result', None))
        window.analysis_snapshot = SimpleNamespace(maximum_print_z_mm=0.2, layer_count=1)
        window._show_original_object_preview()
        self.app.processEvents()
        self.assertEqual(
            (window.preview_dialog.canvas.yaw_deg,
             window.preview_dialog.canvas.pitch_deg),
            (-38.0, 28.0),
        )
        self.assertFalse(window.generation_intro_label.isHidden())
        self.assertEqual(
            window.generation_intro_label.text(),
            'Die Vorschau zeigt derzeit nur das übergebene Originalobjekt, '
            'da noch kein Kühlturm generiert wurde.',
        )
        self.assertLess(
            window.generation_intro_label.geometry().bottom(),
            window.prediction_preview_divider.geometry().top(),
        )
        self.assertFalse(window.preview_dialog.canvas.scene.tower_segments)

    def test_popup_accept_cancel_and_stale_response(self):
        for action in ('accept', 'cancel', 'stale'):
            window = self.make_window()
            try:
                with patch.object(window, 'start_source_preslice') as restart:
                    window._on_support_simulation_available(12)
                    window._on_source_preslice_failed(12, 'Kein G-Code', 'Diagnose')
                    dialog = window._support_simulation_dialog
                    self.assertIsNotNone(dialog)
                    self.assertIn('gespeicherte Änderungen', dialog.message.text())
                    self.assertIn('originalen Profile', dialog.message.text())
                    self.app.processEvents()
                    if action == 'cancel':
                        dialog.cancel_button.click()
                    else:
                        if action == 'stale':
                            window._preslice_request_id += 1
                        dialog.simulate_button.click()
                    if action == 'accept':
                        restart.assert_called_once_with(simulate_supports=True)
                        self.assertIsNone(window._workflow_error_message)
                        self.assertFalse(window._analysis_failed)
                        self.assertNotIn('Kein G-Code', window.validation_label.text())
                        self.assertEqual(window.profile_diagnostics.toPlainText(), '')
                    else:
                        restart.assert_not_called()
            finally:
                window.close()

    def test_retry_waits_for_worker_release_and_rechecks_context(self):
        for stale in (False, True):
            window = self.make_window()
            try:
                with patch.object(window, 'start_source_preslice') as restart, \
                        patch.object(window.background_job_manager, 'has_active', return_value=True) as active:
                    window._show_support_simulation_dialog(12, self.fixture.confirmation)
                    window._support_simulation_dialog.accept()
                    restart.assert_not_called()
                    self.assertIsNotNone(window._pending_support_retry)
                    if stale:
                        window.profile_match_result = replace(window.profile_match_result)
                    active.return_value = False
                    window._start_pending_support_retry()
                    self.assertIsNone(window._pending_support_retry)
                    if stale:
                        restart.assert_not_called()
                    else:
                        restart.assert_called_once_with(simulate_supports=True)
                    window._start_pending_support_retry()
                    self.assertEqual(restart.call_count, 0 if stale else 1)
            finally:
                window.close()

    def test_saved_supports_reloads_all_selected_profiles_and_clears_error(self):
        window = self.make_window()
        try:
            with patch.object(window, 'start_profile_catalog_loading') as reload_profiles, \
                    patch.object(window, 'start_source_preslice') as restart, \
                    patch.object(window.background_job_manager, 'has_active', return_value=True) as active:
                window._on_support_simulation_available(12)
                window._on_source_preslice_failed(12, 'Kein G-Code', 'Alte Diagnose')
                window._support_simulation_dialog.reload_button.click()
                self.assertIsNone(window._workflow_error_message)
                self.assertFalse(window._analysis_failed)
                self.assertEqual(window.profile_diagnostics.toPlainText(), '')
                self.assertIsNone(window.confirmed_profile_context)
                self.assertIsNone(window.profile_catalog_confirmation)
                reload_profiles.assert_not_called()
                active.return_value = False
                window._start_pending_support_retry()
                reload_profiles.assert_called_once()
                kwargs = reload_profiles.call_args.kwargs
                self.assertTrue(kwargs['force_inventory'])
                self.assertFalse(kwargs['restore_remembered_profiles'])
                self.assertFalse(kwargs['match_source_after_loading'])
                refs = kwargs['selected_profile_ids']
                for role in ('machine', 'filament', 'process'):
                    record = getattr(self.fixture.match.selected, role)
                    self.assertEqual(refs[role].profile_id, record.profile_id)
                    self.assertEqual(refs[role].path, record.path)
                catalog = ProfileCatalog(
                    execution_slicer=self.fixture.match.execution_slicer,
                    inventory_fingerprint='fresh-inventory',
                    machine_options=(self.fixture.machine,),
                    process_options=(self.fixture.process,),
                    filament_options=(self.fixture.filament,),
                    selected_machine=refs['machine'], selected_process=refs['process'],
                    selected_filament=refs['filament'],
                )
                with patch.object(MainWindow, 'selected_slicer_installation',
                                  new_callable=PropertyMock, return_value=catalog.execution_slicer):
                    window._on_profile_catalog_succeeded(window._profile_request_id, catalog)
                self.assertIsNone(window.profile_catalog_confirmation)
                self.assertIsNone(window.confirmed_profile_context)
                self.assertTrue(window.profile_confirm_button.text().startswith('Slicer und Profile bestätigen'))
                for role in ('machine', 'filament', 'process'):
                    combo = getattr(window, role + '_profile_combo')
                    self.assertEqual(window._profile_combo_reference(combo), refs[role])
                restart.assert_not_called()
        finally:
            window.close()

    def test_summary_mentions_simulation_and_actual_export(self):
        window = self.make_window()
        try:
            f = self.fixture
            result = PreviewExportResult(output_mode=OutputMode.STL, run_directory=f.root,
                output_path=f.root/'tower.stl', report_path=f.root/'report.json',
                user_report_path=f.root/'summary.txt', calibrated=True, slicer_optimized=True,
                minimum_verified_layer_time_s=10, source_sha256='a', output_sha256='b',
                supports_simulated=True, full_tower_infill_simulated=True,
                tower_supports_disabled_simulated=True,
                project_path=f.root/'project.3mf')
            with patch.object(window, '_show_internal_dialog_without_flash'):
                window._show_export_success_dialog(result)
                text = window.export_success_simulation_label.text()
                self.assertIn('Stützen wurden simuliert', text)
                self.assertIn('in der exportierten 3MF aktiviert', text)
                self.assertIn('100%-Turmfüllung simuliert', text)
                self.assertIn('Deaktivierte Turmstützen simuliert', text)
                window._show_export_success_dialog(replace(result, project_path=None))
                self.assertTrue(window.export_success_simulation_frame.isHidden())
                window._show_export_success_dialog(replace(result, supports_simulated=False))
                self.assertNotIn('Stützen wurden simuliert', window.export_success_simulation_label.text())
        finally:
            window.close()


if __name__ == '__main__':
    unittest.main()
