from pathlib import Path
import io
import os
import sys
import tempfile
from threading import Event
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication, QPushButton
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from cooling_tower.gui.background_jobs import BackgroundJobManager
from cooling_tower.gui.main_window import MainWindow
from cooling_tower.gui.native_project.controller import NativeImported, NativeProjectController
from cooling_tower.gui.native_project.canvas import NativePreviewCanvas
from cooling_tower.gui.widgets.preview_canvas import PreviewCanvas
from cooling_tower.models import GenerationSettings
from cooling_tower.native_project.settings import NativeGenerationSettings
from gui_lifecycle import dispose_test_widget
from native_project_fixtures import write_native


class Resource:
    def __init__(self,name=''):
        self.name,self.closed=name,False
    def close(self):
        self.closed=True


class NativeControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.manager=BackgroundJobManager(strict_transitions=True)

    def wait(self,predicate):
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            self.app.processEvents()
            if predicate():return
            time.sleep(.005)
        self.fail('Native lifecycle condition was not reached.')

    def tearDown(self):
        self.assertTrue(self.manager.shutdown(3000).clean)

    def test_cancelled_late_import_is_closed_and_cannot_replace_new_source(self):
        started,release=Event(),Event()
        first,second=Resource('first'),Resource('second')
        def importer(path,event,notify):
            if path=='first':
                started.set();release.wait(2)
                return NativeImported(first,None,())
            return NativeImported(second,None,())
        controller=NativeProjectController(self.manager,importer=importer)
        controller.load('first');self.wait(started.is_set)
        controller.load('second');release.set()
        self.wait(lambda:not self.manager.has_active())
        self.assertIs(controller.imported.session,second)
        self.assertTrue(first.closed)
        self.assertFalse(second.closed)
        controller.close_after_shutdown();self.assertTrue(second.closed)

    def test_plate_change_discards_results_but_retains_import_basis(self):
        controller=NativeProjectController(self.manager)
        session,prepared,generated=Resource(),Resource(),Resource()
        controller.imported=NativeImported(session,None,())
        controller.prepared,controller.generated=prepared,generated
        controller.select_plate()
        self.assertTrue(prepared.closed);self.assertTrue(generated.closed)
        self.assertFalse(session.closed)
        self.assertIsNone(controller.prepared);self.assertIsNone(controller.generated)
        controller.close_after_shutdown();self.assertTrue(session.closed)

    def test_late_success_after_shutdown_releases_resources(self):
        controller=NativeProjectController(self.manager)
        previews = []
        controller.iteration_ready.connect(previews.append)
        request=controller.request_id
        controller.close_after_shutdown()
        result=Resource()
        controller._succeeded(request,result)
        controller._preview(request, object())
        self.assertTrue(result.closed)
        self.assertIsNone(controller.prepared)
        self.assertEqual(previews, [])

    def test_accept_keeps_verified_result_and_continue_transfers_it_to_worker(self):
        from cooling_tower.native_project.automatic import NativeAutomaticResult, NativeAutomaticState
        from cooling_tower.native_project.options import NativeCalibrationOptions

        controller = NativeProjectController(self.manager)
        session, source, candidate = Resource(), Resource(), Resource()
        controller.imported = NativeImported(session, object(), ())
        controller.prepared = source
        settings = NativeGenerationSettings(target_layer_time_s=11.)
        options = NativeCalibrationOptions()
        paused = NativeAutomaticResult(NativeAutomaticState.PAUSED, candidate, (), settings, 'Vorläufig',
            (50., 50.), 5., minimum_layer_time_s=10.96, best_iteration=2,
            continuation=SimpleNamespace(options=options))
        resumed = Event()
        resume_inputs = []
        genuine_cancellation = []

        def generate(*_, cancellation_event, acceptance_event, preview, resume, **_kwargs):
            if resume is None:
                preview(SimpleNamespace(best_candidate=paused.best_candidate))
                if not acceptance_event.wait(3.):
                    raise RuntimeError('Accept was not delivered.')
                genuine_cancellation.append(cancellation_event.is_set())
                return paused
            resume_inputs.append(resume)
            resumed.set()
            cancellation_event.wait(3.)
            return resume

        with patch('cooling_tower.gui.native_project.controller.NativeAutomaticService.run', side_effect=generate):
            controller.generate(settings, options)
            self.wait(lambda: controller.can_accept_best)
            self.assertEqual(controller.best_candidate, paused.best_candidate)
            self.assertIsNone(controller.generated)
            controller.accept_best()
            self.assertFalse(controller.can_accept_best)
            self.wait(lambda: not controller.busy)
            self.assertEqual(genuine_cancellation, [False])
            self.assertIs(controller.generated, paused)
            self.assertTrue(controller.can_continue)
            self.assertFalse(candidate.closed)

            controller.continue_generation()
            self.wait(resumed.is_set)
            self.assertEqual(resume_inputs, [paused])
            self.assertIsNone(controller.generated)
            self.assertTrue(controller.can_accept_best)
            self.assertFalse(candidate.closed)
            controller.select_plate()
            self.wait(lambda: not self.manager.has_active())
            self.assertTrue(source.closed)
            self.assertTrue(candidate.closed)
            self.assertIsNone(controller.best_candidate)
            self.assertFalse(controller.can_continue)
        controller.close_after_shutdown()


class NativePageRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.window=MainWindow(user_data_root=self.root/'user',enable_update_check=False,enable_startup_slicer_discovery=False)
        self.addCleanup(dispose_test_widget,self.window)

    def wait_error(self):
        page=self.window.native_project_page
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            self.app.processEvents()
            if not page.controller.busy and page.error_label.text():return page
            time.sleep(.005)
        self.fail('Expected native error was not delivered.')

    def test_empty_handover_preserves_full_drop_box_and_browse_action(self):
        self.window.show()
        for width,height in ((1440,900),(1874,1394),(900,720)):
            with self.subTest(width=width,height=height):
                self.window.resize(width,height)
                for _ in range(12):self.app.processEvents()
                drop=self.window.drop_zone
                self.assertGreaterEqual(self.window.source_handover.height(),drop.height())
                self.assertLessEqual(drop.mapTo(self.window.source_group,QPoint(0,drop.height())).y(),
                    self.window.source_group.contentsRect().bottom())
                self.assertFalse(drop.browse_button.visibleRegion().isEmpty())

    def test_source_requirements_use_common_file_label_and_show_geometry_only_for_stl(self):
        self.window.show();self.app.processEvents()
        rows=self.window.preparation_requirement_rows
        self.assertEqual(rows['source_selected'][1].text(),
            'STL oder vollständiges natives 3MF-Projekt übergeben')
        self.assertTrue(all(widget.isHidden() for widget in rows['source_validated']))
        source=Path(__file__).parent/'fixtures/stl/known_valid_tetrahedron_ascii.stl'
        self.window.drop_zone.set_file(source)
        self.assertTrue(all(not widget.isHidden() for widget in rows['source_validated']))
        self.assertEqual(rows['source_validated'][1].text(),'STL-Geometrie geprüft')
        self.window._set_native_handover_active(True)
        self.window._present_native_handover()
        self.assertTrue(all(not widget.isHidden() for widget in rows['source_validated']))
        self.assertEqual(rows['source_validated'][1].text(),'Projektinformationen geprüft')
        self.assertEqual(rows['source_selected'][1].text(),
            'STL oder vollständiges natives 3MF-Projekt übergeben')
        self.window._remove_native_project()
        self.assertTrue(all(widget.isHidden() for widget in rows['source_validated']))

    def test_corrupt_3mf_keeps_handover_and_uses_its_native_error_box(self):
        source=self.root/'corrupt.3mf';source.write_bytes(b'broken archive')
        with patch('cooling_tower.gui.native_project.controller.SlicerDiscoveryService.discover_installations',side_effect=AssertionError('Must not discover for invalid archive')):
            self.assertTrue(self.window.drop_zone.set_file(source))
            page=self.wait_error()
        self.assertIs(self.window.input_pages.currentWidget(),self.window._stl_page)
        self.assertTrue(self.window.native_drop_zone.guide_label.isHidden())
        self.assertIn('ZIP',self.window.native_drop_zone.notice_label.text())
        self.assertFalse(page.prepare_button.isEnabled())

    def test_geometry_only_3mf_has_specific_save_guidance_and_direct_reselection(self):
        source=self.root/'geometry.3mf';write_native(source)
        original=source.read_bytes()
        with zipfile.ZipFile(source,'w') as after,zipfile.ZipFile(io.BytesIO(original)) as before:
            for name in before.namelist():
                if name!='Metadata/project_settings.config':after.writestr(name,before.read(name))
        self.window.drop_zone.set_file(source);page=self.wait_error()
        self.assertFalse(self.window.native_drop_zone.guide_label.isHidden())
        self.assertIn('keine vollständigen nativen',self.window.native_drop_zone.notice_label.text())
        for slicer in ('Anycubic Slicer Next','Bambu Studio','PrusaSlicer','OrcaSlicer'):
            self.assertIn(slicer,self.window.native_drop_zone.guide_label.text())
        self.assertTrue(self.window.native_drop_zone.browse_button.isEnabled())

    def test_native_settings_and_canvas_are_independent_of_stl(self):
        page=self.window.native_project_page
        legacy=self.window.collect_settings()
        page._inputs['target_layer_time_s'][0].setValue(17)
        self.assertEqual(page.collect_settings().target_layer_time_s,17)
        self.assertEqual(self.window.collect_settings(),legacy)
        self.assertIsNot(NativeGenerationSettings,GenerationSettings)
        self.assertFalse(issubclass(NativePreviewCanvas,PreviewCanvas))
        labels=[button.text().casefold() for button in page.findChildren(QPushButton)]
        self.assertFalse(any('postprozessor' in label or 'manuelle methode' in label for label in labels))

    def test_import_stays_in_handover_then_opens_editor_directly(self):
        import threading
        from types import SimpleNamespace
        from cooling_tower.native_project.session import NativeProjectSession
        source=self.root/'neutral.3mf';write_native(source)
        release,started=threading.Event(),threading.Event()
        def importer(path,cancelled,notify):
            started.set()
            while not release.wait(.01):
                if cancelled.is_set():
                    raise RuntimeError('Cancelled neutral import')
            return NativeImported(NativeProjectSession(path),SimpleNamespace(display_name='Bambu Studio'),())
        page=self.window.native_project_page
        page.controller.importer=importer
        self.window.resize(1440,900)
        self.window.show()
        self.app.processEvents()
        previous=self.window.collect_settings()
        stl_labels=(self.window.drop_zone.prompt_label.text(),self.window.drop_zone.browse_button.text())
        previous_stl_request=self.window._stl_validation_request_id
        try:
            self.window.native_drop_zone.set_file(source)
            deadline=time.monotonic()+5
            while not started.is_set() and time.monotonic()<deadline:
                self.app.processEvents();time.sleep(.005)
            self.assertTrue(started.is_set())
            self.assertIs(self.window.input_pages.currentWidget(),self.window._stl_page)
            self.assertTrue(self.window.source_group.isVisible())
            self.assertTrue(self.window.native_drop_zone.isVisible())
            self.window._on_stl_validation_progress(previous_stl_request,100,'Previous STL completed')
            self.assertTrue(self.window.source_progress_bar.isVisible())
            self.window._finish_source_progress(completed=True)
            self.assertTrue(self.window.source_progress_bar.isVisible())
            self.assertTrue(self.window.source_progress_status_widget.isHidden())
            self.assertTrue(self.window.drop_zone.isHidden())
            self.assertIs(self.window.source_handover.currentWidget(),self.window.native_drop_zone)
            self.assertEqual(self.window.source_progress_bar.maximum(),0)
            self.assertNotIn('Abgebrochen',self.window.native_drop_zone.status_value_label.text())
            self.window._refresh_preparation_workspace(True)
            self.app.processEvents()
            self.assertTrue(self.window.source_group.isVisible())
            self.assertTrue(self.window.native_drop_zone.isVisible())
            self.assertEqual(stl_labels,(self.window.drop_zone.prompt_label.text(),self.window.drop_zone.browse_button.text()))
            release.set()
            deadline=time.monotonic()+8
            while time.monotonic()<deadline:
                self.app.processEvents()
                if page.controller.imported is not None and not page.controller.busy:break
                time.sleep(.005)
            self.assertIs(self.window.input_pages.currentWidget(),page)
            self.assertEqual(previous,self.window.collect_settings())
            self.assertFalse(page.prepare_button.isHidden())
            self.assertTrue(page.generate_button.isHidden())
            self.assertTrue(page.canvas.navigation_enabled)
            self.assertEqual(page.header.method_selection.back_button.text(),'Zurück\nzur\nDateiübergabe')
            self.assertEqual(set(page.editor.camera_buttons),{'three_quarter','front','side','top','fit'})
            self.assertEqual(self.window.native_drop_zone.project_fields['Slicer'][1].text(),'Bambu Studio')
            page.back_requested.emit()
            self.assertIs(self.window.input_pages.currentWidget(),self.window._stl_page)
            self.assertTrue(self.window.source_group.isVisible())
            self.assertTrue(self.window.native_drop_zone.isVisible())
        finally:
            release.set()

    def test_native_back_uses_actual_card_owner_before_and_after_stl_preparation(self):
        from types import SimpleNamespace
        from cooling_tower.native_project.session import NativeProjectSession
        source=self.root/'neutral.3mf';write_native(source)
        page=self.window.native_project_page
        imported=NativeImported(NativeProjectSession(source),SimpleNamespace(display_name='Bambu Studio'),())
        page._path=source;page.controller.imported=imported;page._imported(imported)
        self.window.native_drop_zone.show_imported(imported)
        self.window._set_native_handover_active(True)
        self.window.resize(1440,900);self.window.show()
        for moved in (False,True):
            if moved:
                self.window._set_native_handover_active(False)
                self.window._refresh_preparation_workspace(True)
                self.assertTrue(self.window._preparation_in_workspace)
                self.window._set_native_handover_active(True)
            self.window.input_pages.setCurrentWidget(page)
            page.header.preparation_button.click()
            self.app.processEvents()
            expected=self.window.preparation_workspace if moved else self.window.main_surface
            self.assertIs(self.window.window_pages.currentWidget(),expected)
            self.assertTrue(self.window.source_group.isVisible())
            self.assertTrue(self.window.native_drop_zone.isVisible())
            self.assertFalse(self.window.drop_zone.isVisible())
            self.assertIsNone(expected.graphicsEffect())
            self.window._open_native_editor()
            self.assertTrue(page.isVisible())
            page.header.method_selection.back_button.click()
            self.app.processEvents()
            self.assertTrue(self.window.native_drop_zone.isVisible())

    def test_native_header_combines_project_facts_and_handover_lists_profiles_vertically(self):
        from types import SimpleNamespace
        from cooling_tower.native_project.session import NativeProjectSession
        source=self.root/'neutral.3mf'
        write_native(source,values={'filament_settings_id':['Alpha','Beta','Gamma'],
            'filament_type':['PLA','PLA','PETG'],'printer_settings_id':'Machine Profile',
            'print_settings_id':'Process Profile'})
        page=self.window.native_project_page
        imported=NativeImported(NativeProjectSession(source),SimpleNamespace(display_name='Bambu Studio'),())
        page._path=source;page.controller.imported=imported;page._imported(imported)
        self.window.native_drop_zone.show_imported(imported)
        self.assertEqual(dict(page.header.facts), {
            'Dateiname': 'neutral.3mf', 'Slicer': 'Bambu Studio', 'Methode': 'Iterativ',
            'Projektversion': '02.08.02.61', 'Druckplatte': 'Druckplatte 1 · 1 Objekt',
        })
        self.assertTrue(page.project_group.isHidden())
        self.assertEqual({key for key, label in page.header.fact_labels.items() if not label.isHidden()},
                         set(dict(page.header.facts)))
        fields=self.window.native_drop_zone.project_fields
        self.assertEqual(fields['Filamentprofile'][1].text(),'Alpha\nBeta\nGamma')
        self.assertEqual(fields['Maschinenprofil'][1].text(),'Machine Profile')
        self.assertEqual(fields['Prozessprofil'][1].text(),'Process Profile')
        self.assertNotIn('Alpha',str(page.header.facts))
        from dataclasses import replace
        prusa=replace(imported.session.context,adapter_id='prusa_slicer',
            settings={'filament_settings_id':'"Alpha; special";"Beta"'})
        self.window.native_drop_zone.show_imported(SimpleNamespace(
            session=SimpleNamespace(context=prusa),installation=imported.installation))
        self.assertEqual(fields['Filamentprofile'][1].text(),'Alpha; special\nBeta')

    def test_native_visible_drop_can_replace_project_with_stl_in_same_slot(self):
        self.window._set_native_handover_active(True)
        self.window.show();self.app.processEvents()
        source=Path(__file__).parent/'fixtures/stl/known_valid_tetrahedron_ascii.stl'
        self.assertTrue(self.window.native_drop_zone.set_file(source))
        self.assertFalse(self.window._native_handover_active)
        self.assertIs(self.window.source_handover.currentWidget(),self.window.drop_zone)
        self.assertTrue(self.window.drop_zone.isVisible())
        self.assertEqual(self.window.source_progress_bar.maximum(),100)

    def test_project_intake_does_not_read_archive_on_ui_thread(self):
        from PySide6.QtCore import QUrl
        source=self.root/'damaged.3mf';source.write_bytes(b'broken archive')
        with patch('cooling_tower.gui.widgets.source_drop_zone.recognize_source',side_effect=AssertionError('Synchronous ZIP scan')):
            self.assertTrue(self.window.drop_zone.set_file(source))
        self.assertEqual(self.window.native_drop_zone._single_supported_url([QUrl.fromLocalFile(str(source))]),source)
        self.wait_error()

    def test_prepare_generate_export_buttons_follow_native_state(self):
        from types import SimpleNamespace
        from cooling_tower.native_project.session import NativeProjectSession
        source=self.root/'neutral.3mf';write_native(source)
        page=self.window.native_project_page
        page._path=source
        imported=NativeImported(NativeProjectSession(source),SimpleNamespace(display_name='Bambu Studio'),())
        page.controller.imported=imported;page._imported(imported)
        page._set_busy(False)
        self.assertFalse(page.prepare_button.isHidden())
        self.assertTrue(page.generate_button.isHidden())
        self.assertTrue(page.export_button.isHidden())
        page.controller.prepared=Resource()
        page._update_controls()
        self.assertTrue(page.prepare_button.isHidden())
        self.assertFalse(page.generate_button.isHidden())
        generated=Resource();generated.prepared=Resource()
        page.controller.generated=generated
        page._update_controls()
        self.assertTrue(page.generate_button.isHidden())
        self.assertFalse(page.export_button.isHidden())
        self.assertEqual(page.generate_button.text(),'Turm generieren')
        page._set_busy(True)
        self.assertFalse(page.cancel_button.isHidden())
        self.assertTrue(page.export_button.isHidden())

    def test_shell_settings_restore_manual_values_after_auto_and_reset(self):
        page = self.window.native_project_page
        editor = page.editor
        self.assertTrue(page.collect_settings().simulate_tower_without_supports)
        settings_layout = editor.input_group.content_layout
        tolerance = editor.rows['layer_time_tolerance_s']
        top_shell = editor.rows['top_shell_layers']
        bottom_shell = editor.rows['bottom_shell_layers']
        extra = editor.inputs['extra_top_layer'][0]
        self.assertEqual(extra.text(), 'Turm +1 Layer höher generieren (druck endet am Turm)')
        self.assertEqual(settings_layout.indexOf(top_shell), settings_layout.indexOf(tolerance) + 1)
        self.assertEqual(settings_layout.indexOf(bottom_shell), settings_layout.indexOf(top_shell) + 1)
        self.assertEqual(settings_layout.indexOf(extra.parentWidget()), settings_layout.indexOf(bottom_shell) + 1)
        self.assertEqual(page.layout().indexOf(page.plates), page.layout().indexOf(page.main_header) + 1)
        self.assertTrue(editor.timing_panel.isHidden())
        self.assertFalse(editor.timing_toggle.isEnabled())
        self.assertFalse(editor.timing_toggle.isChecked())
        editor.set_project_profile(SimpleNamespace(adapter_id='bambu_studio', settings={
            'support_threshold_angle': 28., 'top_shell_layers': 12, 'bottom_shell_layers': 0,
        }))
        for surface, automatic_value in (('top', 12), ('bottom', 0)):
            field = f'{surface}_shell_layers'
            spin = editor.inputs[field][0]
            flag = editor.automatic[f'automatic_{field}']
            self.assertEqual((spin.minimum(), spin.value(), spin.maximum()), (0, 1, 5))
            spin.setValue(4)
            flag.setChecked(True)
            self.assertFalse(spin.isEnabled())
            self.assertEqual(spin.text(), str(automatic_value))
            self.assertEqual(getattr(page.collect_settings(), field), 4)
            flag.setChecked(False)
            self.assertEqual(spin.value(), 4)
            editor.rows[field].reset_button.click()
            self.assertEqual(spin.value(), 1)
        concave = editor.concave_base_row
        self.assertFalse(concave.isHidden())
        editor.inputs['simulate_full_tower_infill'][0].setChecked(True)
        self.assertTrue(concave.isHidden())
        editor.reset()
        self.assertFalse(concave.isHidden())
        editor.refresh_layout()

    def test_numeric_drafts_survive_live_refresh_and_commit_only_when_confirmed(self):
        page = self.window.native_project_page
        self.window.input_pages.setCurrentWidget(page)
        self.window.show()
        self.app.processEvents()
        editor = page.editor
        fields = (
            (editor.inputs['top_shell_layers'][0], '3', 3),
            (editor.inputs['bottom_shell_layers'][0], '04', 4),
            (editor.inputs['target_layer_time_s'][0], '12.50', 12.5),
            (editor.iterations, '24', 24),
            (editor.separate_iterations, '10', 10),
        )
        for spin, draft, value in fields:
            with self.subTest(field=spin.accessibleName()):
                old = spin.value()
                spin.setFocus()
                spin.selectAll()
                for index, character in enumerate(draft, 1):
                    QTest.keyClicks(spin, character)
                    self.app.processEvents()
                    self.assertEqual(spin.lineEdit().text(), draft[:index])
                    self.assertEqual(spin.lineEdit().cursorPosition(), index)
                    self.assertEqual(spin.value(), old)
                    self.assertTrue(spin.input_pending)
                if spin is editor.separate_iterations:
                    QTest.keyClick(spin, Qt.Key.Key_Tab)
                else:
                    QTest.keyClick(spin, Qt.Key.Key_Return)
                self.assertEqual(spin.value(), value)
                self.assertFalse(spin.input_pending)

    def test_native_minimum_diameter_warns_using_embedded_profile_and_current_settings(self):
        from cooling_tower.native_project.session import NativeProjectSession

        source = self.root/'wall-clearance.3mf'
        write_native(source, values={
            'outer_wall_line_width': '0.42', 'inner_wall_line_width': '0.45',
            'minimum_sparse_infill_area': '20', 'sparse_infill_density': '12%',
        })
        page = self.window.native_project_page
        page._path = source
        page.controller.imported = NativeImported(
            NativeProjectSession(source), SimpleNamespace(display_name='Bambu Studio'), ())
        page._imported(page.controller.imported)
        editor = page.editor
        diameter = editor.rows['minimum_outer_diameter_mm']
        full = editor.inputs['simulate_full_tower_infill'][0]
        self.assertIn('mindestens 6,9 mm', diameter.message_label.text())
        full.setChecked(True)
        self.assertTrue(diameter.message_container.isHidden())
        full.setChecked(False)
        self.assertIn('mindestens 6,9 mm', diameter.message_label.text())
        editor.inputs['tower_wall_count'][0].setValue(1)
        self.assertIn('mindestens 6,0 mm', diameter.message_label.text())
        diameter.editor.setValue(6.)
        self.assertTrue(diameter.message_container.isHidden())
        editor.inputs['circle_segments'][0].setValue(4)
        editor.automatic['automatic_circle_segments'].setChecked(False)
        self.assertIn('massiv', diameter.message_label.text())
        page.deactivate()
        self.assertTrue(diameter.message_container.isHidden())

    def test_slice_previews_update_chart_and_canvas_then_cancel_restores_basis(self):
        from types import SimpleNamespace
        from cooling_tower.native_project.automatic import NativeSlicePreview
        from cooling_tower.native_project.toolpath import DepositionToolpathAnalysis
        from cooling_tower.preview.models import LineSegment3D, Point3D
        from test_phase2 import make_layer

        page = self.window.native_project_page
        settings = SimpleNamespace(as_dict=lambda: {
            'printable_area': ['0x0', '200x0', '200x200', '0x200'],
        })
        context = SimpleNamespace(settings=settings)
        analysis = SimpleNamespace(layers=tuple(make_layer(i, total_time_s=2.,
            deposition_time_s=1., deposition_path_mm=10.) for i in range(1, 4)),
            layer_count=3, maximum_print_z_mm=.6)
        def paths(x):
            return DepositionToolpathAnalysis(
                (LineSegment3D(Point3D(x,10,.2), Point3D(x+1,10,.2)),), 1, None)
        basis = Resource()
        basis.context, basis.analysis, basis.toolpaths = context, analysis, paths(10)
        page.controller.prepared = basis
        page._show_result(basis)
        self.assertTrue(page.editor.timing_toggle.isChecked())
        page._select_layer(2)
        page._iteration(NativeSlicePreview(context, analysis, paths(20), (20.,10.), 5., True, (4., 5., 6.)))
        self.assertEqual(page.layer_spin.value(), 2)
        self.assertEqual(page.chart.combined, (4., 5., 6.))
        self.assertEqual(len(page.canvas.scene.tower_segments), 1)
        self.assertEqual(page.canvas.scene.object_segments, ())
        self.assertIn('geschätzt', page.editor.time_legend.labels[1].text())
        page.cancel()
        self.assertIs(page._displayed, basis)
        self.assertIsNone(page.chart.combined)
        page._clear_display()
        self.assertFalse(page.editor.timing_toggle.isChecked())

    def test_native_header_facts_can_be_clicked_without_taking_focus(self):
        from PySide6.QtTest import QSignalSpy
        from cooling_tower.gui.native_project.header import NativePreparationFactsButton

        facts = NativePreparationFactsButton()
        self.addCleanup(dispose_test_widget, facts)
        facts.set_facts((('Dateiname', 'neutral.3mf'),))
        facts.show()
        spy = QSignalSpy(facts.clicked)
        facts.clearFocus()
        QTest.mouseClick(facts, Qt.MouseButton.LeftButton)
        self.assertEqual(spy.count(), 1)
        self.assertFalse(facts.hasFocus())

    def test_native_report_reuses_export_dialog_and_native_folder(self):
        import json
        page = self.window.native_project_page
        root = self.root/'native-exports'
        folder = root/'Projekt_test'
        folder.mkdir(parents=True)
        project = folder/'Projekt_mit_Turm.3mf'
        project.touch()
        (folder/'Projektbericht.json').write_text(json.dumps({
            'native_project_report_version': 1,
            'target_layer_time_s': 9.0,
            'minimum_layer_time_s': 8.9,
            'layer_time_tolerance_s': .25,
            'extra_layer_z_mm': 24.2,
        }), encoding='utf-8')
        page._export_directory = root
        self.window.show()
        page._exported(str(project))
        self.app.processEvents()
        dialog = self.window.export_success_dialog
        self.assertTrue(dialog.isVisible())
        self.assertIn('8,9 von 9', self.window.export_success_achieved_label.text())
        self.assertIn('zusätzliche Turmlayer', self.window.export_success_usage_label.text())
        dialog.accept()
        page.editor.open_report_button.click()
        self.app.processEvents()
        self.assertTrue(dialog.isVisible())
        with patch('cooling_tower.gui.main_window.open_directory') as open_directory:
            self.window._open_export_directory_from_success_dialog()
        open_directory.assert_called_once_with(folder.resolve())

    def test_shifted_paths_and_seams_select_by_their_print_layer(self):
        from cooling_tower.preview.models import PreviewScene,LineSegment3D,Point3D
        from cooling_tower.models import BedBounds
        segments = tuple(LineSegment3D(Point3D(0,0,z),Point3D(1,1,z)) for z in (.2,.3,.5))
        canvas = self.window.native_project_page.canvas
        scene = PreviewScene(segments,(),BedBounds(0,100,0,100),(0,0),3,3,0,
                             layer_z_mm=(.2,.4),seam_points=(Point3D(0,0,.3),))
        canvas.set_scene(scene,object_layer_heights=(.2,.2,.4),seam_layer_heights=(.2,))
        canvas.set_layer_height(.2)
        self.assertEqual(canvas._layer_segments(scene.object_segments),segments[:2])
        self.assertEqual(len(canvas._layer_segments(canvas._seam_segments)),1)
        canvas.set_layer_height(.4)
        self.assertEqual(canvas._layer_segments(scene.object_segments),segments[2:])

    def test_automatic_fields_keep_manual_values_and_infill_controls_contraction(self):
        editor = self.window.native_project_page.editor
        base = editor.inputs['manual_base_width_mm'][0]
        flag = editor.automatic['automatic_base_width']
        flag.setChecked(False)
        base.setValue(42.)
        flag.setChecked(True)
        editor.show_automatic_values({'manual_base_width_mm':36.5,'circle_segments':44})
        self.assertFalse(base.isEnabled())
        self.assertEqual(base.text(),'36,50')
        base.interpretText()
        self.assertEqual(base.value(),42.)
        flag.setChecked(False)
        self.assertEqual(base.text(),'42')
        contraction = editor.inputs['maximum_contraction_angle_deg'][0]
        infill = editor.automatic['automatic_contraction_angle']
        infill.setChecked(False)
        contraction.setValue(43.)
        infill.setChecked(True)
        self.assertFalse(contraction.isEnabled())
        self.assertEqual(contraction.text(),'auto')
        infill.setChecked(False)
        self.assertTrue(contraction.isEnabled())
        self.assertEqual(contraction.value(),43.)
        expansion = editor.inputs['maximum_expansion_angle_deg'][0]
        expansion.setValue(40.)
        editor.set_project_profile(SimpleNamespace(adapter_id='bambu_studio', settings={
            'support_threshold_angle': 25.5,
        }))
        self.assertFalse(expansion.isEnabled())
        self.assertEqual(expansion.text(),'25,50')
        self.assertEqual(expansion.value(),40.)
        editor.inputs['limit_expansion_to_profile'][0].setChecked(False)
        self.assertTrue(expansion.isEnabled())
        self.assertEqual(expansion.value(),40.)
        expansion.setValue(29.)
        self.assertIn('sehr starken Überhang',editor.rows['maximum_expansion_angle_deg'].message_label.text())
        expansion.setValue(35.)
        self.assertEqual(editor.rows['maximum_expansion_angle_deg'].message_label.text(),'')

    def test_chart_settings_match_stl_hints_and_preserve_exact_comparison_times(self):
        from cooling_tower.gui.native_project.hints import chart_hint
        from cooling_tower.gui.postprocessor_controls import setting_hint
        from cooling_tower.gui.widgets.info_tool_button import InfoToolButton
        editor = self.window.native_project_page.editor
        hints = {button.toolTip() for button in editor.findChildren(InfoToolButton)}
        for label,key in (('Logarithmische Zeitskala','logarithmic_time_scale'),
                          ('Zeitskala normalisieren','normalize_time_scale')):
            self.assertEqual(chart_hint(label,key),setting_hint(label,key))
            self.assertIn(chart_hint(label,key),hints)
        chart = editor.time_chart
        chart.set_comparison((100.,8.,10.),(110.,6.,12.),(.2,.4,.6),9.)
        self.assertTrue(chart.normalized)
        self.assertEqual(chart.original,(100.,8.,10.))
        self.assertEqual(chart.combined,(110.,6.,12.))
        self.assertAlmostEqual(chart._maximum,12.*1.05)
        editor.normalized_scale.setChecked(True)
        editor.normalized_scale.setChecked(False)
        self.assertAlmostEqual(chart._maximum,110.*1.05)
        editor.logarithmic_scale.setChecked(False)
        self.assertFalse(chart.logarithmic)
        self.assertEqual(chart.combined,(110.,6.,12.))

    def test_native_export_history_ignores_malformed_report_and_follows_root_changes(self):
        import json
        page = self.window.native_project_page
        first = self.root/'first-exports'
        for name,data in (('Projekt_bad',[]),('Projekt_good',{'native_project_report_version':1})):
            folder = first/name;folder.mkdir(parents=True)
            (folder/'Projekt_mit_Turm.3mf').write_bytes(b'neutral export')
            (folder/'Projektbericht.json').write_text(json.dumps(data),encoding='utf-8')
        (first/'Projekt_good/Projektbericht.txt').write_text('neutral report',encoding='utf-8')
        page._export_directory = first
        page._refresh_export_actions()
        self.assertEqual(page._last_export,first/'Projekt_good/Projekt_mit_Turm.3mf')
        self.assertFalse(page.editor.open_last_button.isHidden())
        self.assertFalse(page.editor.open_report_button.isHidden())
        page._export_directory = self.root/'new-exports'
        page._refresh_export_actions()
        self.assertIsNone(page._last_export)
        self.assertFalse(page.editor.open_output_button.isEnabled())
        self.assertTrue(page.editor.open_last_button.isHidden())

    def test_finishing_unchanged_numeric_edit_does_not_discard_generated_project(self):
        page = self.window.native_project_page
        generated = Resource()
        generated.prepared = Resource()
        page.controller.generated = generated
        page.editor.inputs['target_layer_time_s'][0].editingFinished.emit()
        self.assertIs(page.controller.generated,generated)
        self.assertFalse(generated.closed)
        page.iterations.setValue(page.iterations.value()+1)
        self.assertTrue(generated.closed)
        self.assertIsNone(page.controller.generated)

    def test_preview_reset_and_transparency_follow_layer_chart_without_changing_settings(self):
        from types import SimpleNamespace
        page = self.window.native_project_page
        editor = page.editor
        before = page.collect_settings()
        page._displayed = SimpleNamespace(analysis=SimpleNamespace(layers=tuple(
            SimpleNamespace(z_mm=z,total_time_s=seconds) for z,seconds in ((.2,20.),(.4,5.),(.6,7.)))))
        page.layer_spin.setRange(1,3)
        page.chart.set_comparison((20.,4.,6.),(21.,5.,7.),(.2,.4,.6),9.)
        for button in (editor.preview_reset,editor.transparency_toggle):button.setEnabled(True)
        page._select_layer(2)
        editor.transparency_toggle.click()
        self.assertFalse(page.canvas._layer_colours_highlight)
        page.chart.layer_selected.emit(1)
        self.assertTrue(editor.transparency_toggle.isChecked())
        self.assertTrue(page.canvas._layer_colours_highlight)
        editor.logarithmic_scale.setChecked(False)
        editor.normalized_scale.setChecked(False)
        page.canvas.set_navigation_enabled(False)
        editor.preview_reset.click()
        self.assertTrue(page.canvas.navigation_enabled)
        self.assertTrue(page.chart.logarithmic)
        self.assertTrue(page.chart.normalized)
        self.assertEqual(page.layer_spin.value(),3)
        self.assertIsNone(page.canvas._layer_z)
        self.assertEqual(page.collect_settings(),before)

    def test_navigation_matches_postprocessor_drag_pan_and_cursor_zoom(self):
        from PySide6.QtCore import QEvent,QPointF
        from PySide6.QtGui import QMouseEvent,QWheelEvent
        native=self.window.native_project_page.editor
        reference=self.window.postprocessor_panel
        for panel in (native,reference):
            panel.three_quarter_view()
            panel.canvas.set_navigation_enabled(True)
        self.assertEqual(native.canvas.camera_state(),reference.canvas.camera_state())
        def drag(canvas,button,delta):
            start=QPointF(200,180)
            for kind,position,changed,buttons in (
                (QEvent.Type.MouseButtonPress,start,button,button),
                (QEvent.Type.MouseMove,start+delta,Qt.MouseButton.NoButton,button),
                (QEvent.Type.MouseButtonRelease,start+delta,button,Qt.MouseButton.NoButton)):
                self.app.sendEvent(canvas,QMouseEvent(kind,position,position,changed,buttons,Qt.KeyboardModifier.NoModifier))
        for button in (Qt.MouseButton.LeftButton,Qt.MouseButton.RightButton,Qt.MouseButton.MiddleButton):
            for delta in (QPointF(30,20),QPointF(-30,-20)):
                for panel in (native,reference):drag(panel.canvas,button,delta)
                self.assertEqual(native.canvas.camera_state(),reference.canvas.camera_state())
        for amount in (120,-120,0):
            for panel in (native,reference):
                canvas=panel.canvas
                pos=QPointF(canvas.width()/2+30,canvas.height()/2-20)
                self.app.sendEvent(canvas,QWheelEvent(pos,pos,QPoint(),QPoint(0,amount),
                    Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False))
            self.assertEqual(native.canvas.camera_state(),reference.canvas.camera_state())
        for panel in (native,reference):
            panel.canvas.set_navigation_enabled(False)
            before=panel.canvas.camera_state()
            drag(panel.canvas,Qt.MouseButton.LeftButton,QPointF(20,30))
            self.assertEqual(panel.canvas.camera_state(),before)

    def test_native_route_buttons_filter_logical_layers_and_reset_without_changing_result(self):
        from types import SimpleNamespace
        from cooling_tower.preview.models import PreviewScene,LineSegment3D,Point3D
        from cooling_tower.models import BedBounds
        page=self.window.native_project_page;editor=page.editor
        routes=tuple(LineSegment3D(Point3D(0,0,z),Point3D(5,5,z+.4)) for z in (.2,.4,.6))
        scene=PreviewScene((),(),BedBounds(0,200,0,200),(0,0),0,0,0,
            tower_travel_segments=routes,tower_travel_layer_indices=(0,1,2),layer_z_mm=(.2,.4,.6))
        page.canvas.set_scene(scene)
        editor.set_preview_available(True)
        page.layer_spin.setRange(1,3)
        displayed=SimpleNamespace(analysis=SimpleNamespace(layers=tuple(SimpleNamespace(z_mm=z,total_time_s=1.) for z in (.2,.4,.6))))
        page._displayed=displayed
        before=page.collect_settings()
        page._select_layer(2)
        self.assertEqual(page.canvas._travel_segments(routes,(0,1,2)),(routes[1],))
        editor.travel_mode_toggle.click()
        self.assertTrue(page.canvas._all_travel_visible)
        editor.travel_visibility_button.click()
        self.assertFalse(page.canvas._tower_travel_visible)
        self.assertEqual(editor.travel_visibility_button.text(),'Fahrwege anzeigen')
        editor._travel_reveal_animation.setCurrentTime(editor._travel_reveal_animation.duration())
        self.assertFalse(editor.travel_mode_toggle.isEnabled())
        editor.preview_reset.click()
        self.assertTrue(editor.travel_visibility_button.isChecked())
        self.assertFalse(editor.travel_mode_toggle.isChecked())
        self.assertFalse(page.canvas._all_travel_visible)
        self.assertIs(page._displayed,displayed)
        self.assertEqual(page.collect_settings(),before)
        editor._position_preview_controls()
        self.assertEqual(editor.travel_visibility_button.x()+editor.travel_visibility_button.width(),page.canvas.width())
        page._clear_display()
        self.assertFalse(editor.travel_visibility_button.isEnabled())
        self.assertTrue(editor.travel_mode_toggle.isHidden())

    def test_native_object_fitting_does_not_shrink_for_parking_routes(self):
        from dataclasses import replace
        from cooling_tower.preview.models import PreviewScene,LineSegment3D,Point3D
        from cooling_tower.models import BedBounds
        canvas=self.window.native_project_page.canvas
        printed=LineSegment3D(Point3D(10,10,.2),Point3D(20,20,.2))
        scene=PreviewScene((printed,),(),BedBounds(0,250,0,250),(0,0),1,1,0)
        canvas.set_scene(scene)
        before=canvas._fit_parameters()
        route=LineSegment3D(printed.end,Point3D(250,250,100))
        canvas.set_scene(replace(scene,tower_travel_segments=(route,),tower_travel_layer_indices=(0,)),preserve_view=True)
        self.assertEqual(canvas._fit_parameters(),before)

    def test_header_menu_has_same_actions_icons_and_owned_popup_as_stl(self):
        from PySide6.QtWidgets import QMenu
        page = self.window.native_project_page
        native,stl = page.options_menu.actions(),self.window.options_menu.actions()
        self.assertEqual([action.text() for action in native],[action.text() for action in stl])
        self.assertTrue(all(not action.icon().isNull() for action in native))
        self.assertEqual(page.options_menu.objectName(),'mainOptionsMenu')
        page._show_options_menu()
        self.app.processEvents()
        self.assertTrue(page.options_menu.isVisible())
        page.options_menu.close()
        page._show_options_menu()
        self.app.processEvents()
        self.assertEqual(page.findChildren(QMenu),[page.options_menu])
        page.options_menu.close()


class NativePlateSelectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def test_click_drag_and_keyboard_are_distinct_and_cards_stay_readable(self):
        from types import SimpleNamespace
        from PySide6.QtGui import QPixmap, QColor
        from cooling_tower.gui.native_project.plate_selector import NativePlateSelector, _thumbnail_content
        picker=NativePlateSelector()
        self.addCleanup(dispose_test_widget,picker)
        from PySide6.QtGui import QPainter
        thumbnail = QPixmap(200,160)
        thumbnail.fill(Qt.GlobalColor.transparent)
        painter = QPainter(thumbnail)
        painter.fillRect(80, 40, 40, 80, QColor('#586b80'))
        painter.end()
        opaque = QPixmap(200, 160)
        opaque.fill(QColor('#ffffff'))
        painter = QPainter(opaque)
        painter.fillRect(80, 40, 40, 80, QColor('#586b80'))
        painter.end()
        self.assertEqual((_thumbnail_content(opaque).width(), _thumbnail_content(opaque).height()), (40, 80))
        for number in range(8):
            picker.add_plate(SimpleNamespace(identifier=str(number),
                name=f'Druckplatte {number+1} mit lesbarem Namen',object_count=number+1),thumbnail)
        picker.setCurrentRow(0)
        picker.resize(620,156);picker.show()
        self.app.processEvents()
        self.assertGreater(picker.horizontalScrollBar().maximum(),0)
        first=picker.itemWidget(picker.item(0))
        second=picker.itemWidget(picker.item(1))
        self.assertTrue(first.property('selected'))
        self.assertFalse(second.property('selected'))
        self.assertEqual((first.thumbnail.pixmap().width(), first.thumbnail.pixmap().height()), (38, 76))
        self.assertEqual(picker.height(), 125)
        self.assertIn('lesbarem Namen',first.title.text())
        position=picker.visualItemRect(picker.item(1)).center()
        QTest.mouseMove(picker.viewport(), position)
        self.assertTrue(second.property('hovered'))
        self.assertEqual(picker.currentRow(), 0)
        QTest.mousePress(picker.viewport(),Qt.MouseButton.LeftButton,pos=position)
        self.assertEqual(picker.currentRow(),0)
        QTest.mouseRelease(picker.viewport(),Qt.MouseButton.LeftButton,pos=position)
        self.assertEqual(picker.currentRow(),1)
        self.assertTrue(second.property('selected'))
        QTest.mousePress(picker.viewport(),Qt.MouseButton.LeftButton,pos=position)
        end=QPoint(position.x()-220,position.y())
        QTest.mouseMove(picker.viewport(),end)
        QTest.mouseRelease(picker.viewport(),Qt.MouseButton.LeftButton,pos=end)
        self.assertGreaterEqual(picker.horizontalScrollBar().value(),200)
        self.assertEqual(picker.currentRow(),1)
        self.assertEqual(picker.item(1).data(Qt.ItemDataRole.UserRole),'1')
        QTest.keyClick(picker,Qt.Key.Key_Right)
        self.assertEqual(picker.currentRow(),2)


if __name__=='__main__':unittest.main()
