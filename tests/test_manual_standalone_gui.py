import os
import sys
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
os.environ.setdefault("COOLING_TOWER_DISABLE_SLICER_DISCOVERY","1")
import test_manual_gui as fixture
from PySide6.QtCore import QPointF,QPoint,Qt
from PySide6.QtTest import QTest
from cooling_tower.gui.main_window import MainWindow
from cooling_tower.gui.generation_session import GenerationMode
from cooling_tower.manual.service import ManualGenerationService
from cooling_tower.manual.standalone import StandaloneRequest
from cooling_tower.manual.geometry import ManualSettings
from cooling_tower.models.calibration import BedBounds,BedGeometry,OccupiedBounds


class StandaloneGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app,cls.font,cls.font_id=fixture.preview_test_application()
    @classmethod
    def tearDownClass(cls):fixture.restore_preview_test_application(cls.app,cls.font,cls.font_id)

    def setUp(self):
        self.f,self.service,self.reference,self.request,self.adapter=fixture.create_fixture(self,joint=True,count=100)
        self.window=MainWindow(user_data_root=self.f.root/"app",enable_update_check=False,enable_startup_slicer_discovery=False)
        self.addCleanup(self.window.close)
        self.panel=self.window.manual_generation_panel;self.controller=self.window.manual_controller
        self.window.resize(1450,1000);self.window.show();self.app.processEvents()

    def normal_context(self):
        w,c,p=self.window,self.controller,self.panel
        w.analysis_snapshot=self.f.snapshot;w.source_artifact=self.request.source_artifact
        w.profile_match_result=SimpleNamespace(selected=SimpleNamespace(effective_profile=self.f.profile,bundle_id="manual"),
            user_confirmed=True,can_use_stl_mode=True,execution_slicer=self.f.profile.installation,inventory_fingerprint="fixture")
        w.slicer_service.adapter_for=Mock(return_value=self.adapter)
        base=c.build_request();reference=self.service.prepare_reference(base)
        c.reference=reference;c._reference_request=base;p.initialize(reference)
        w.workflow.set_slicer_step_visible(True)
        w.workflow.source_validation_succeeded("source.stl",analysis_complete=True)
        w.workflow.slicer_succeeded("Test slicer");w.workflow.complete_preparation()
        w.select_generation_mode(GenerationMode.MANUAL);self.app.processEvents()

    def wait_idle(self):
        until=time.monotonic()+10
        while self.controller.job_id is not None and time.monotonic()<until:
            self.app.processEvents();time.sleep(.01)
        self.assertIsNone(self.controller.job_id,self.panel.status_label.text())

    def open_free(self):
        self.window.select_generation_mode(GenerationMode.FREE)
        self.app.processEvents()
        return self.window.free_generation_panel,self.window.free_manual_controller

    def test_free_card_without_preparation_exports_only_stl_and_keeps_session(self):
        w=self.window
        self.assertTrue(w.generation_method_picker.isHidden())
        self.assertFalse(w.manual_generation_card.isEnabled())
        self.assertTrue(w.free_generation_card.isEnabled())
        w.free_tower_action.trigger();self.app.processEvents()
        p,c=w.free_generation_panel,w.free_manual_controller
        self.panel,self.controller=p,c
        self.assertIs(w.generation_mode,GenerationMode.FREE)
        self.assertTrue(p.isVisible());self.assertTrue(w.footer.isVisible())
        self.assertTrue(c.standalone_note.isVisible())
        self.assertIsInstance(c.build_request(p.draft),StandaloneRequest)
        self.assertEqual(p.selected,"");self.assertTrue(p.point_editor.isHidden())
        w.slicer_service.adapter_for=Mock(side_effect=AssertionError("No adapter in free mode"))
        p.move("top",5,500);p.move("foot",250,0)
        c.generate();self.wait_idle()
        self.assertIsNotNone(c.session.preview,p.status_label.text())
        w.output_root_edit.setText(str(self.f.root/"exports"))
        with patch.object(w,"_show_export_success_dialog"):
            w.export_button.click();self.wait_idle()
        result=c.session.export_result
        self.assertTrue(result.standalone);self.assertIsNone(result.project_path)
        self.assertEqual(len(list(result.run_directory.iterdir())),3)
        _=w.export_success_dialog;c.describe_export(result)
        self.assertIn("ohne Slice",w.export_success_achieved_label.text())
        draft=p.draft;preview=c.session.preview
        w.show_generation_method_selection();self.app.processEvents()
        self.assertTrue(w.generation_method_picker.isVisible());self.assertTrue(w.footer.isHidden())
        w.free_generation_card.click();self.app.processEvents()
        self.assertEqual(p.draft,draft);self.assertIs(c.session.preview,preview)
        self.assertFalse(w.export_button.isEnabled())

    def test_drafts_cameras_results_and_resets_are_independent_across_methods(self):
        self.normal_context();w=self.window;p,c=self.panel,self.controller
        p.move("base",10,8);p.insert(12)
        p.canvas.set_view("front");p.canvas.zoom=1.7;p.canvas.pan=QPointF(18,-12)
        p.canvas.object_rotation=-33;p.canvas.set_highlight("all")
        normal_draft,normal_initial=p.draft,p.initial
        camera=(p.canvas.view,p.canvas.zoom,QPointF(p.canvas.pan),p.canvas.object_rotation,p.canvas.highlight)
        session=c.session;preview=Mock()
        preview.request_signature=c.build_request(p.draft).signature();preview.artifact_sha256="normal"
        session.preview=preview;session.successful_request=c.build_request(p.draft)
        free,fc=self.open_free()
        self.assertIsNot(fc.session,session);self.assertIs(w.manual_controller,fc)
        free.move("top",5,400);free.move("foot",240,0);free.insert(200)
        free.canvas.zoom=1.3;free.canvas.pan=QPointF(-15,7)
        free_draft=free.draft;free_camera=(free.canvas.zoom,QPointF(free.canvas.pan))
        w.select_generation_mode(GenerationMode.MANUAL);self.app.processEvents()
        self.assertEqual(p.draft,normal_draft);self.assertEqual(p.initial,normal_initial)
        self.assertEqual(p.selected,"");self.assertTrue(p.point_editor.isHidden())
        self.assertIs(c.session.preview,preview);preview.dispose.assert_not_called()
        self.assertEqual((p.canvas.view,p.canvas.zoom,p.canvas.pan,p.canvas.object_rotation,p.canvas.highlight),camera)
        w.tower_reset_button.click();self.app.processEvents()
        self.assertFalse(p.can_reset_tower());self.assertEqual(free.draft,free_draft)
        free,fc=self.open_free()
        self.assertEqual(free.draft,free_draft);self.assertEqual(free.selected,"")
        self.assertEqual((free.canvas.zoom,free.canvas.pan),free_camera)
        normal_draft=p.draft
        box=Mock();box._reset_yes_button=object();box.clickedButton.return_value=box._reset_yes_button
        with patch.object(w,"_create_reset_defaults_message_box",return_value=box):
            w.request_reset_defaults()
        self.assertFalse(free.can_reset_all());self.assertEqual(p.draft,normal_draft)
        with patch.object(c.store,"save") as saved:
            c.save_settings();saved.assert_called_once_with(p.settings)
        self.assertIsNone(fc.store)
        self.assertTrue(w.free_footer_status_widget.isVisible());self.assertTrue(w.manual_footer_status_widget.isHidden())
        w.close();preview.dispose.assert_called_once()

    def test_free_views_hide_original_xray_and_layer_data_and_center_tower(self):
        p,_=self.open_free();c=p.canvas
        self.assertTrue(p.preview_tools.isHidden())
        self.assertTrue(p.resolution_host.isHidden());self.assertTrue(p.rotation_host.isHidden())
        self.assertFalse(p.highlight_host.isVisible());self.assertEqual(c.highlight,"both")
        self.assertEqual(c._object_array.size,0)
        for view in ("side","front","top","bottom","free"):
            c.set_view(view);self.app.processEvents();c.grab()
            self.assertEqual(c._world_origin,(0,0));self.assertNotIn("Original",c.caption_text())
            self.assertEqual(c.scale_ticks()[1],());self.assertNotIn("Layer",c.selected_handle_text())
            if view in ("side","front"):
                self.assertAlmostEqual(c.profile_to_screen(0,0).x(),c.plot_rect().center().x())
            else:self.assertAlmostEqual(c._spatial_center[0],0,delta=.05)
        p.reset_all();self.assertFalse(p.settings.layer_snap_enabled)
        self.assertFalse(p.settings.critical_layers_enabled)
        self.assertEqual(p.settings.maximum_foot_diameter_mm,250)
        self.assertEqual(p.draft.first_layer_z_mm,0)

    def test_free_preview_gains_toolbar_height_with_same_footer(self):
        self.normal_context();normal=self.panel
        QTest.qWait(40);normal_height=normal.canvas.height()
        normal_footer=self.window.footer.geometry().height()
        free,_=self.open_free();QTest.qWait(40)
        self.assertGreater(free.canvas.height(),normal_height)
        self.assertEqual(self.window.footer.geometry().height(),normal_footer)
        self.assertFalse(free.preview_tools.isVisible())
        self.assertTrue(self.window.tower_reset_button.isVisible())

    def test_source_change_preserves_free_draft_and_result_but_invalidates_normal(self):
        self.normal_context();normal=self.panel;nc=self.controller
        free,fc=self.open_free();free.move("top",5,450);draft=free.draft
        preview=Mock();preview.request_signature=fc.build_request(draft).signature();preview.artifact_sha256="free"
        fc.session.preview=preview;fc.session.successful_request=fc.build_request(draft)
        self.window._discard_generated_tower();self.app.processEvents()
        self.assertEqual(free.draft,draft);self.assertIs(fc.session.preview,preview)
        self.assertIsNone(normal.draft);self.assertIsNone(nc.reference)
        preview.dispose.assert_not_called()

    def test_busy_job_blocks_switch_and_free_sizes_are_enforced(self):
        p,c=self.open_free();w=self.window
        self.assertEqual(p.editors["height_mm"].maximum(),500)
        self.assertEqual(p.editors["foot_diameter_mm"].maximum(),250)
        self.assertIsNotNone(p._validate_point_value("base_diameter_mm",251))
        with patch.object(w.background_job_manager,"has_active",return_value=True):
            w.show_generation_method_selection();w.select_generation_mode(GenerationMode.MANUAL)
        self.assertIs(w.generation_mode,GenerationMode.FREE)

    def test_normal_foot_default_is_limited_by_actual_bed_object_and_brim(self):
        bed=BedGeometry(BedBounds(0,50,0,50),((0,0),(50,0),(50,50),(0,50)))
        context=replace(self.reference.context,key="small-physical-bed",bed_geometry=bed,
                        occupied_bounds=OccupiedBounds(20,30,20,30),brim_width_mm=1)
        reference=replace(self.reference,context=context)
        p=self.panel;p.initialize(reference,ManualSettings())
        limit=context.maximum_foot_diameter_mm
        self.assertLess(limit,25)
        self.assertEqual(p.settings.maximum_foot_diameter_mm,limit)
        self.assertEqual(p.settings.foot_diameter_mm,limit)
        self.assertEqual(p.default_value("foot_diameter_mm"),limit)
        self.assertEqual(p.default_value("maximum_foot_diameter_mm"),limit)
        placement=context.validate(p.draft)
        self.assertAlmostEqual(placement.radius_mm,limit/2+1)
        p.move("foot",10,p.draft.first_layer_z_mm)
        self.assertEqual(p.draft.foot_diameter_mm,10)
        p.reset_all();self.assertEqual(p.settings.maximum_foot_diameter_mm,limit)
        self.assertEqual(p.settings.foot_diameter_mm,limit)

    def test_tiny_free_space_has_valid_context_specific_form_reset_defaults(self):
        bed=BedGeometry(BedBounds(0,20,0,20),((0,0),(20,0),(20,20),(0,20)))
        context=replace(self.reference.context,key="tiny-physical-bed",bed_geometry=bed,
                        occupied_bounds=OccupiedBounds(8,12,8,12),brim_width_mm=1.3)
        p=self.panel
        p.initialize(replace(self.reference,context=context),replace(ManualSettings(),minimum_diameter_mm=1))
        limit=context.maximum_foot_diameter_mm
        self.assertLess(limit,7)
        p.reset_all();context.validate(p.draft)
        self.assertAlmostEqual(p.settings.minimum_diameter_mm,limit-2)
        self.assertEqual(p.settings.foot_diameter_mm,limit)
        p.move("base",1,p.settings.foot_height_mm)
        p.reset_tower();context.validate(p.draft)
        self.assertFalse(p.can_reset_tower())


if __name__=="__main__":unittest.main()
