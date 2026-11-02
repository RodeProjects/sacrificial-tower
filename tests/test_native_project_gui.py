from pathlib import Path
import io
import os
import sys
import tempfile
from threading import Event
import time
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
        request=controller.request_id
        controller.close_after_shutdown()
        result=Resource()
        controller._succeeded(request,result)
        self.assertTrue(result.closed)
        self.assertIsNone(controller.prepared)


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

    def test_native_header_has_only_identity_and_handover_lists_profiles_vertically(self):
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
        self.assertEqual(page.header.facts,(('Dateiname','neutral.3mf'),('Slicer','Bambu Studio')))
        self.assertEqual(set(page.header.fact_labels),{'Dateiname','Slicer'})
        fields=self.window.native_drop_zone.project_fields
        self.assertEqual(fields['Filamentprofile'][1].text(),'Alpha\nBeta\nGamma')
        self.assertEqual(fields['Maschinenprofil'][1].text(),'Machine Profile')
        self.assertEqual(fields['Prozessprofil'][1].text(),'Process Profile')
        self.assertNotIn('Alpha',page.context_label.text())
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
        infill = editor.inputs['simulate_full_tower_infill'][0]
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
        editor.set_profile_angle(25.5)
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
        from cooling_tower.gui.native_project.plate_selector import NativePlateSelector
        picker=NativePlateSelector()
        self.addCleanup(dispose_test_widget,picker)
        thumbnail=QPixmap(200,160);thumbnail.fill(QColor('#586b80'))
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
        self.assertEqual(first.thumbnail.pixmap().size().width(),96)
        self.assertIn('lesbarem Namen',first.title.text())
        position=picker.visualItemRect(picker.item(1)).center()
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
