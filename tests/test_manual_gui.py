import os
import sys
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
os.environ.setdefault("COOLING_TOWER_DISABLE_SLICER_DISCOVERY","1")

from PySide6.QtCore import QPointF,Qt,QPoint
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from cooling_tower.gui.main_window import MainWindow
from cooling_tower.gui.manual_panel import ManualGenerationPanel
from cooling_tower.gui.widgets.layer_range_canvas import LayerRangeCanvas
from cooling_tower.gui.background_jobs import JobKind
from cooling_tower.gui.generation_session import GenerationMode
from cooling_tower.manual.geometry import ManualSettings,move_point,GeometryError
from cooling_tower.preview import PreviewState
from test_manual_generation import create_fixture


class ManualGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.f,self.service,self.reference,self.request,self.adapter=create_fixture(self,joint=True,count=200)
        self.panel=ManualGenerationPanel()
        self.panel.initialize(self.reference)
        self.panel.set_busy(False)
        self.panel.resize(1400,900)
        self.panel.show();self.app.processEvents()
        self.addCleanup(self.panel.close)

    def test_bidirectional_diameter_handles_and_numeric_values(self):
        self.panel.editors["base_diameter_mm"].setValue(10)
        self.assertEqual(self.panel.draft.base_diameter_mm,10)
        self.panel.move("base",20,90)
        self.assertEqual(self.panel.editors["base_diameter_mm"].value(),20)
        self.assertEqual(self.panel.draft.settings.foot_height_mm,8)
        self.panel.move("foot_height",999,10)
        self.assertEqual(self.panel.draft.base_diameter_mm,20)
        self.assertEqual(self.panel.editors["foot_height_mm"].value(),10)
        self.panel.move("top",999,35)
        self.assertEqual(self.panel.draft.height_mm,35)
        self.assertEqual(self.panel.draft.points[-1].position.diameter_mm,20)

    def test_height_grip_snaps_near_object_top_but_other_heights_remain_continuous(self):
        p=self.panel;canvas=p.canvas
        object_top=self.reference.context.layers[-1].z_mm
        for view in ("side","front"):
            canvas.set_view(view)
            canvas.zoom=1.6;canvas.pan=QPointF(17,-20)
            p.move("top",5,object_top)
            top=canvas.profile_to_screen(p.draft.points[-1].position.radius_mm,object_top)
            canvas.pan+=QPointF(0,canvas.height()/2-top.y())
            top=canvas.profile_to_screen(p.draft.points[-1].position.radius_mm,object_top)
            near=(top+QPointF(0,10)).toPoint()
            QTest.mousePress(canvas,Qt.MouseButton.LeftButton,pos=top.toPoint())
            QTest.mouseMove(canvas,near)
            self.assertEqual(p.draft.height_mm,object_top)
            self.assertEqual(canvas._height_snap_z,object_top)
            image=canvas.grab().toImage()
            guide_y=round(canvas.profile_to_screen(0,object_top).y())
            self.assertTrue(any(image.pixelColor(x,y).blue()>image.pixelColor(x,y).red()+60
                                for x in range(12,52) for y in range(guide_y-1,guide_y+2)))
            QTest.qWait(canvas.HEIGHT_SNAP_GUIDE_DURATION_MS+100)
            self.assertIsNone(canvas._height_snap_z)
            self.assertEqual(canvas._drag_height_z,object_top)
            QTest.mouseMove(canvas,near+QPoint(0,1))
            QTest.mouseRelease(canvas,Qt.MouseButton.LeftButton,pos=near)
            self.assertIsNone(canvas._height_snap_z)
            self.assertIsNone(canvas._drag_height_z)
            farther=(top+QPointF(0,36)).toPoint()
            expected=canvas.screen_to_profile(QPointF(farther))[1]
            QTest.mousePress(canvas,Qt.MouseButton.LeftButton,pos=top.toPoint())
            QTest.mouseMove(canvas,farther)
            QTest.mouseRelease(canvas,Qt.MouseButton.LeftButton,pos=farther)
            self.assertAlmostEqual(p.draft.height_mm,expected)
            self.assertLess(p.draft.height_mm,object_top)
            self.assertIsNone(canvas._height_snap_z)
        p.editors["height_mm"].setValue(object_top-.03)
        self.assertAlmostEqual(p.draft.height_mm,object_top-.03)
        self.assertIsNone(canvas._height_snap_z)

    def test_vertical_drag_guide_tracks_accepted_height_and_clears_on_release(self):
        p=self.panel;canvas=p.canvas
        p.insert(20);free=p.selected
        original=p.draft
        for view in ("side","front"):
            canvas.set_view(view)
            for identity in ("top","foot_height",free,"control:0:1"):
                with self.subTest(view=view,identity=identity):
                    p.commit(original)
                    p.select("foot" if identity.startswith("control:") else identity)
                    canvas.fit_scene();canvas.zoom=2
                    handle=next(pos for name,pos,_ in canvas.handles() if name==identity)
                    canvas.pan+=QPointF(0,canvas.height()/2-handle.y())
                    handle=next(pos for name,pos,_ in canvas.handles() if name==identity)
                    target=(handle+QPointF(0,-24)).toPoint()
                    QTest.mousePress(canvas,Qt.MouseButton.LeftButton,pos=handle.toPoint())
                    self.assertEqual(canvas._drag[1],identity)
                    QTest.mouseMove(canvas,target)
                    self.assertEqual(canvas._drag_height_z,canvas._vertical_handle_height(identity))
                    if identity.startswith("control:"):
                        self.assertTrue(any(name==identity for name,_,_ in canvas.handles()))
                    image=canvas.grab().toImage()
                    y=round(canvas.profile_to_screen(0,canvas._drag_height_z).y())
                    self.assertTrue(any(abs(image.pixelColor(x,row).red()-83)<=45 and
                                        abs(image.pixelColor(x,row).green()-105)<=45 and
                                        abs(image.pixelColor(x,row).blue()-128)<=45
                                        for x in range(canvas.width()-52,canvas.width()-12)
                                        for row in range(y-1,y+2)))
                    QTest.mouseRelease(canvas,Qt.MouseButton.LeftButton,pos=target)
                    self.assertIsNone(canvas._drag_height_z)
        p.commit(original);p.select(free);canvas.fit_scene()
        handle=next(pos for name,pos,_ in canvas.handles() if name==free).toPoint()
        QTest.mousePress(canvas,Qt.MouseButton.LeftButton,pos=handle)
        QTest.mouseMove(canvas,handle+QPoint(20,0))
        self.assertIsNone(canvas._drag_height_z)
        QTest.mouseRelease(canvas,Qt.MouseButton.LeftButton,pos=handle+QPoint(20,0))

    def test_two_visible_decimals_retain_exact_profile_coordinates(self):
        p=self.panel
        p.insert(20);identity=p.selected
        p.move(identity,12.345678,20.123456)
        for name,spin in p.editors.items():
            if name != "circle_segments":
                self.assertEqual(spin.textFromValue(12.345678),"12,35",name)
        self.assertEqual(p.editors["point_diameter_mm"].text(),"12,35")
        self.assertAlmostEqual(p.draft.points[2].position.diameter_mm,12.345678)
        self.assertAlmostEqual(p.draft.points[2].position.z_mm,20.123456)
        before=p.draft.artifact_payload()
        p.editors["point_diameter_mm"].setFocus();self.app.processEvents()
        p.canvas.setFocus();self.app.processEvents()
        self.assertEqual(p.draft.artifact_payload(),before)

    def test_settings_feedback_cannot_change_canvas_geometry(self):
        p=self.panel
        self.assertEqual(p.splitter.handleWidth(),1)
        self.assertEqual(p.settings_content.layout().contentsMargins().right(),14)
        self.assertEqual(p.preview_container.layout().contentsMargins().left(),14)
        for width,height in ((1400,900),(650,1100)):
            p.resize(width,height)
            self.app.processEvents()
            before=p.canvas.geometry()
            previous_scroll=p.settings_scroll.verticalScrollBar().maximum()
            p.rows["maximum_diameter_mm"].set_error("Eine ausführliche Grenzrückmeldung. "*12)
            for _ in range(4):self.app.processEvents()
            self.assertEqual(p.canvas.geometry(),before)
            self.assertGreaterEqual(p.settings_scroll.verticalScrollBar().maximum(),previous_scroll)
            p.rows["maximum_diameter_mm"].set_error(None)
            self.app.processEvents()
            self.assertEqual(p.canvas.geometry(),before)

    def test_front_view_places_both_objects_on_same_reference_axis(self):
        canvas=self.panel.canvas
        before=self.panel.draft
        canvas.set_view("side")
        tower_axis=canvas.profile_to_screen(0,0).x()
        object_axis=canvas.profile_to_screen(canvas._static_object_center,0).x()
        self.assertGreater(object_axis,tower_axis)
        canvas.set_view("front")
        self.assertEqual(canvas.profile_to_screen(canvas._static_object_center,0).x(),canvas.profile_to_screen(0,0).x())
        canvas.grab()
        self.assertEqual(canvas._interval_helper.yaw_deg,90)
        self.assertEqual(canvas.object_rotation,0)
        self.assertEqual(self.panel.draft,before)

    def test_spatial_original_surface_uses_existing_layer_color_baseline(self):
        import numpy as np
        from PySide6.QtGui import QColor
        from threading import Event
        from cooling_tower.gui.manual_view_worker import render_spatial_object
        p=self.panel
        p.canvas.set_view("three_quarter")
        settings=replace(p.settings,critical_layers_enabled=True)
        image=render_spatial_object(self.reference,p.canvas._spatial_frame(),settings,Event())
        pixels=np.frombuffer(image.constBits(),dtype=np.uint32)
        self.assertIn(QColor(LayerRangeCanvas.OBJECT_COLOR).rgba(),pixels)

    def test_free_points_selection_removal_curve_and_reset(self):
        self.panel.insert(20)
        identity=self.panel.selected
        self.panel.editors["point_diameter_mm"].setValue(30)
        self.assertEqual(self.panel.draft.points[2].position.diameter_mm,30)
        self.panel.reset_value("point_diameter_mm")
        self.assertAlmostEqual(self.panel.draft.points[2].position.diameter_mm,5)
        self.panel.segment_combo.setCurrentIndex(1)
        self.assertTrue(self.panel.draft.curves[2].curved)
        self.assertTrue(any(h[0].startswith("control:") for h in self.panel.canvas.handles()))
        self.panel.select("control:2:1")
        self.panel.move_control(2,1,8,25)
        self.assertAlmostEqual(self.panel.editors["control_diameter_mm"].value(),8)
        self.panel.select(identity);self.panel.remove(identity)
        self.assertEqual(len(self.panel.draft.points),3)

    def test_inverse_projection_handles_zoom_pan_and_mouse_centered_zoom(self):
        canvas=self.panel.canvas
        for view in ("side","front"):
            canvas.set_view(view)
            for zoom in (.5,1,10,40):
                canvas.zoom=zoom;canvas.pan=QPointF(31,-45)
                point=canvas.profile_to_screen(6.123,17.456)
                r,z=canvas.screen_to_profile(point)
                self.assertAlmostEqual(r,6.123);self.assertAlmostEqual(z,17.456)
                for identity,pos,kind in canvas.handles():
                    self.assertEqual(canvas.hit_test(pos),identity)
            canvas.zoom=2;canvas.pan=QPointF(13,27)
            mouse=QPointF(310,200)
            before=canvas.screen_to_profile(mouse)
            event=QWheelEvent(mouse,mouse,QPoint(),QPoint(0,120),Qt.MouseButton.NoButton,
                              Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
            canvas.wheelEvent(event)
            after=canvas.screen_to_profile(mouse)
            self.assertAlmostEqual(before[0],after[0]);self.assertAlmostEqual(before[1],after[1])

    def test_views_disable_editing_and_do_not_change_height(self):
        height=self.panel.draft.height_mm
        for view in ("three_quarter","top","free"):
            self.panel.canvas.set_view(view)
            self.assertFalse(self.panel.canvas.editable)
            self.assertFalse(self.panel.canvas.handles())
            self.assertFalse(self.panel.rows["base_diameter_mm"].isEnabled())
            self.assertFalse(self.panel.add_point_button.isEnabled())
        self.panel.canvas.set_view("side")
        self.assertTrue(self.panel.canvas.editable)
        self.assertTrue(self.panel.rows["base_diameter_mm"].isEnabled())
        self.assertEqual(self.panel.draft.height_mm,height)

    def test_canvas_gestures_edit_pan_and_free_rotation_are_separate(self):
        canvas=self.panel.canvas
        old=self.panel.draft
        handle=next(h[1] for h in canvas.handles() if h[0]=="base")
        QTest.mousePress(canvas,Qt.MouseButton.LeftButton,pos=handle.toPoint())
        QTest.mouseMove(canvas,(handle+QPointF(12,0)).toPoint())
        self.assertIsNone(canvas._drag_height_z)
        QTest.mouseRelease(canvas,Qt.MouseButton.LeftButton,pos=(handle+QPointF(12,0)).toPoint())
        self.assertGreater(self.panel.draft.base_diameter_mm,old.base_diameter_mm)
        before=self.panel.draft
        QTest.mousePress(canvas,Qt.MouseButton.MiddleButton,pos=QPoint(100,100))
        QTest.mouseMove(canvas,QPoint(120,130));QTest.mouseRelease(canvas,Qt.MouseButton.MiddleButton,pos=QPoint(120,130))
        self.assertEqual(self.panel.draft,before)
        self.assertNotEqual(canvas.pan,QPointF())
        canvas.set_view("three_quarter")
        QTest.mousePress(canvas,Qt.MouseButton.RightButton,pos=QPoint(100,100))
        QTest.mouseMove(canvas,QPoint(130,115));QTest.mouseRelease(canvas,Qt.MouseButton.RightButton,pos=QPoint(130,115))
        self.assertEqual(canvas.view,"free")
        self.assertEqual(self.panel.draft,before)

    def test_boundary_feedback_debounced_and_correct_field(self):
        self.panel.change_setting("maximum_foot_diameter_mm",30)
        row=self.panel.rows["maximum_foot_diameter_mm"]
        with patch.object(row,"set_error",wraps=row.set_error) as feedback:
            self.panel._begin_interaction()
            for width in (40,45,50):self.panel.move("base",width,8)
            self.assertEqual(feedback.call_count,1)
            self.assertAlmostEqual(self.panel.draft.base_diameter_mm,30,places=6)
            self.assertEqual(self.panel.settings.maximum_foot_diameter_mm,30)
            self.panel._end_interaction()
            QTest.qWait(750)
            self.assertEqual(feedback.call_count,2)
        self.panel.editors["base_diameter_mm"].setValue(35)
        self.assertIn("Fuß",self.panel.status_label.text())

    def test_angle_activation_rejected_atomically(self):
        old=self.panel.draft
        self.panel.change_setting("contraction_angle_deg",1)
        self.panel.checks["contraction_enabled"].setChecked(True)
        self.assertFalse(self.panel.settings.contraction_enabled)
        self.assertFalse(self.panel.checks["contraction_enabled"].isChecked())
        self.assertEqual(self.panel.draft.curves,old.curves)
        self.assertIn("Verjüngung",self.panel.status_label.text())

    def test_numeric_attempt_beyond_qt_range_reports_domain_limit(self):
        spin=self.panel.editors["base_diameter_mm"]
        spin.setFocus();self.app.processEvents()
        spin.validate("9999",4)
        self.app.processEvents()
        self.assertLessEqual(self.panel.draft.base_diameter_mm,self.panel.settings.maximum_diameter_mm+1e-6)
        self.assertIn("Maximaldurchmesser",self.panel.status_label.text())

    def test_numeric_step_beyond_hard_segment_range_is_reported(self):
        spin=self.panel.editors["circle_segments"]
        spin.setValue(720)
        spin.stepBy(1)
        self.app.processEvents()
        self.assertEqual(self.panel.settings.circle_segments,720)
        self.assertIn("Kreissegmentzahl",self.panel.status_label.text())

    def test_coupling_checkbox_and_control_sync(self):
        self.panel.insert(20)
        identity=self.panel.selected
        self.panel.move(identity,15,20)
        self.panel.smooth_checkbox.setChecked(True)
        self.assertTrue(self.panel.draft.points[2].smooth)
        self.panel.select("control:1:2")
        self.panel.move_control(1,2,12,18)
        a,b=self.panel.draft.curves[1:3]
        self.assertAlmostEqual(a.derivative(1,"radius_mm")/a.derivative(1,"z_mm"),b.derivative(0,"radius_mm")/b.derivative(0,"z_mm"))

    def test_colors_actual_layers_direction_and_visual_identity(self):
        p=self.panel
        before=p.draft.artifact_payload()
        p.change_setting("critical_layers_enabled",True)
        p.change_setting("target_layer_time_s",15)
        layer=self.reference.context.layers[7]
        self.assertEqual(p.canvas._object_color(layer),LayerRangeCanvas.layer_color(15,layer.total_time_s))
        p.change_setting("critical_layers_enabled",False)
        self.assertEqual(p.canvas._object_color(layer).name(),p.canvas.OBJECT_COLOR)
        p.change_setting("overhang_enabled",True);p.change_setting("overhang_angle_deg",10)
        self.assertEqual(p.canvas._surface_color(3).name(),p.canvas.TOWER_COLOR)
        p.insert(20);p.move(p.selected,30,20)
        self.assertEqual(p.canvas._surface_color(15).name(),"#e5484d")
        self.assertEqual(p.canvas._surface_color(30).name(),p.canvas.TOWER_COLOR)
        p.change_setting("overhang_enabled",False)
        self.assertEqual(p.canvas._surface_color(15).name(),p.canvas.TOWER_COLOR)

    def test_geometry_changes_preserve_view_and_object_cache(self):
        canvas=self.panel.canvas
        canvas.zoom=4;canvas.pan=QPointF(20,-60)
        canvas.grab()
        cache=canvas._object_cache
        self.panel.move("base",8,8)
        self.assertIs(canvas._object_cache,cache)
        self.assertEqual(canvas.zoom,4);self.assertEqual(canvas.pan,QPointF(20,-60))

    def test_visual_rotation_highlight_and_small_layout(self):
        before=self.panel.draft
        source_hash=self.request.source_artifact.original_sha256
        self.panel.rotation_slider.setValue(147)
        deadline=time.monotonic()+1
        while self.panel.canvas.object_rotation != 147 and time.monotonic()<deadline:
            self.app.processEvents();time.sleep(.01)
        self.panel.highlight_combo.setCurrentIndex(1)
        self.assertEqual(self.panel.canvas.object_rotation,147)
        self.assertEqual(self.panel.draft,before)
        self.assertEqual(self.request.source_artifact.original_sha256,source_hash)
        self.panel.resize(650,1100);self.app.processEvents()
        self.assertEqual(self.panel.splitter.orientation(),Qt.Orientation.Vertical)
        self.assertLessEqual(self.panel.canvas.width(),650)
        self.assertGreater(self.panel.settings_scroll.verticalScrollBar().maximum(),0)
        self.assertTrue(self.panel.canvas.grab().save(str(self.f.root/"small_editor.png")))


class ManualControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.f,self.service,ref,request,self.adapter=create_fixture(self,joint=True,count=100)
        self.window=MainWindow(user_data_root=self.f.root/"app",enable_update_check=False,enable_startup_slicer_discovery=False)
        self.addCleanup(self.window.close)
        w=self.window
        w.analysis_snapshot=self.f.snapshot
        w.source_artifact=request.source_artifact
        w.profile_match_result=SimpleNamespace(selected=SimpleNamespace(effective_profile=self.f.profile,bundle_id="manual"),
                                              user_confirmed=True,can_use_stl_mode=True,execution_slicer=self.f.profile.installation,inventory_fingerprint="fixture")
        w.slicer_service.adapter_for=Mock(return_value=self.adapter)
        self.controller=w.manual_controller
        self.controller.service=self.service
        base=self.controller.build_request()
        reference=self.service.prepare_reference(base)
        self.controller.reference=reference;self.controller._reference_request=base
        self.panel=w.manual_generation_panel
        self.panel.initialize(reference)
        self.panel.set_busy(False)
        self.controller.refresh()

    def wait_idle(self,timeout=5000):
        deadline=time.monotonic()+timeout/1000
        while self.controller.job_id is not None and time.monotonic()<deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertIsNone(self.controller.job_id,self.panel.status_label.text())

    def show_manual_footer(self):
        w=self.window
        w.workflow.set_slicer_step_visible(True)
        w.workflow.source_validation_succeeded("source.stl",analysis_complete=True)
        w.workflow.slicer_succeeded("Test slicer")
        w.workflow.complete_preparation()
        w.select_generation_mode(GenerationMode.MANUAL)
        w.resize(1450,1000);w.show()
        self.app.processEvents()

    def test_main_footer_routes_manual_generation_update_export_and_reset(self):
        c,p,w=self.controller,self.panel,self.window
        self.show_manual_footer()
        self.assertTrue(w.footer.isVisible())
        self.assertTrue(p.actions_host.isHidden())
        self.assertTrue(w.footer.isAncestorOf(p.status_label))
        self.assertTrue(w.footer.isAncestorOf(w.preview_button))
        automatic=w.collect_settings()
        w.preview_button.click();self.wait_idle()
        self.assertTrue(w.export_button.isVisible())
        self.assertFalse(w.preview_button.isVisible())
        p.move("base",10,8)
        self.assertEqual(w.preview_button.text(),"Kühlturm aktualisieren")
        self.assertTrue(w.export_button.isVisible())
        self.assertTrue(w.reset_button.isEnabled())
        yes=object()
        box=Mock();box._reset_yes_button=yes;box.clickedButton.return_value=yes
        with patch.object(w,"_create_reset_defaults_message_box",return_value=box):
            w.reset_button.click()
        self.assertEqual(p.draft,p.initial)
        self.assertEqual(w.collect_settings(),automatic)
        w.output_root_edit.setText(str(self.f.root/"footer_export"))
        with patch.object(w,"_show_export_success_dialog"):
            w.export_button.click();self.wait_idle()
        self.assertIsNotNone(c.session.export_result)
        self.assertFalse(w.export_button.isEnabled())
        self.assertTrue(w.open_output_button.isVisible())
        self.assertTrue(w.open_stl_button.isVisible())
        self.assertTrue(w.open_run_button.isVisible())

    def test_footer_uses_same_responsive_labels_and_wrapping_for_both_methods(self):
        c,p,w=self.controller,self.panel,self.window
        self.show_manual_footer()
        c.generate();self.wait_idle()
        p.move("base",8,8)
        w._last_export_report_result=SimpleNamespace(report_path=self.f.root/"report.json")
        w._refresh_last_export_report_action()
        for width in (1800,1100,760,650,1800):
            w.resize(width,1050)
            for _ in range(4):self.app.processEvents()
            w._update_responsive_action_labels()
            manual_labels=(w.open_output_button.text(),w.open_stl_button.text(),w.open_run_button.text(),w.export_button.text())
            manual_layout=w._footer_actions_layout_mode
            # Match exactly the same visible action set and primary label.
            w.generation_mode=GenerationMode.AUTOMATIC
            with patch.object(w,"_refresh_phase17_actions"):
                w.current_preview=SimpleNamespace()
                w._update_responsive_action_labels()
                automatic_labels=(w.open_output_button.text(),w.open_stl_button.text(),w.open_run_button.text(),w.export_button.text())
                self.assertEqual(manual_labels,automatic_labels)
                self.assertEqual(manual_layout,w._footer_actions_layout_mode)
            w.current_preview=None
            w.generation_mode=GenerationMode.MANUAL
            c.refresh_footer()

    def test_footer_cancel_stays_red_and_disables_until_job_is_released(self):
        from threading import Event
        from cooling_tower.preview import PreviewCancelled
        self.show_manual_footer()
        c,w=self.controller,self.window
        started=Event()
        def blocked_prepare(request,*,cancellation_event,progress_callback):
            started.set();cancellation_event.wait(5)
            raise PreviewCancelled()
        c.service.prepare=blocked_prepare
        w.preview_button.click()
        deadline=time.monotonic()+2
        while not started.is_set() and time.monotonic()<deadline:
            self.app.processEvents();time.sleep(.01)
        self.assertTrue(started.is_set())
        self.assertTrue(w.preview_action_control.property("cancelAction"))
        self.assertEqual(w.preview_button.text(),"Abbrechen")
        self.assertFalse(w.reset_button.isEnabled())
        w.preview_button.click()
        self.assertEqual(w.preview_button.text(),"Abbruch wird ausgeführt …")
        self.assertFalse(w.preview_button.isEnabled())
        self.wait_idle()
        self.assertEqual(w.preview_button.text(),"Kühlturm generieren")

    def test_main_preview_stays_still_when_settings_and_footer_feedback_expand(self):
        p,w=self.panel,self.window
        self.show_manual_footer()
        for _ in range(5):self.app.processEvents()
        bottom=p.preview_container.mapTo(w.settings_scroll.viewport(),QPoint(0,p.preview_container.height())).y()
        self.assertLessEqual(bottom,w.settings_scroll.viewport().height())
        rectangle=p.canvas.geometry()
        position=p.canvas.mapToGlobal(QPoint())
        p.feedback(GeometryError("maximum_diameter_mm","Eine ausführliche Grenzrückmeldung. "*12),"points")
        for _ in range(5):self.app.processEvents()
        self.assertEqual(p.canvas.geometry(),rectangle)
        self.assertEqual(p.canvas.mapToGlobal(QPoint()),position)

    def test_main_preview_controls_fit_without_overlap_after_resizing(self):
        p,w=self.panel,self.window
        self.show_manual_footer()
        for width,height in ((1450,1000),(720,1100),(1000,800),(1450,1000)):
            with self.subTest(width=width,height=height):
                w.resize(width,height)
                for _ in range(8):self.app.processEvents()
                layout=p.preview_container.layout()
                previous_bottom=-1
                for i in range(layout.count()):
                    item=layout.itemAt(i)
                    widget=item.widget()
                    if widget is not None and widget.isHidden():continue
                    rectangle=item.geometry()
                    self.assertGreater(rectangle.top(),previous_bottom)
                    self.assertLess(rectangle.bottom(),p.preview_container.height())
                    previous_bottom=rectangle.bottom()
                self.assertGreaterEqual(p.canvas.height(),p.canvas.minimumHeight())
                if width<1000:
                    self.assertLessEqual(p.settings_scroll.height(),360)
                    rectangle=p.canvas.geometry()
                    position=p.canvas.mapToGlobal(QPoint())
                    p.rows["maximum_diameter_mm"].set_error("Eine ausführliche Grenzrückmeldung. "*12)
                    for _ in range(4):self.app.processEvents()
                    self.assertEqual(p.canvas.geometry(),rectangle)
                    self.assertEqual(p.canvas.mapToGlobal(QPoint()),position)
                    p.rows["maximum_diameter_mm"].set_error(None)

    def test_states_draft_previous_result_export_identity_and_exact_restore(self):
        c,p=self.controller,self.panel
        self.assertEqual(p.generate_button.text(),"Kühlturm generieren")
        c.generate();self.wait_idle()
        self.assertIsNotNone(c.session.preview,p.status_label.text())
        self.assertFalse(p.export_button.isHidden())
        self.assertTrue(p.generate_button.isHidden())
        previous=c.session.preview
        draft=p.draft
        p.move("base",10,8)
        self.assertEqual(p.generate_button.text(),"Kühlturm aktualisieren")
        self.assertFalse(p.export_button.isHidden())
        self.assertIn("bisherigen",p.action_hint.text())
        p.commit(draft)
        self.assertTrue(p.generate_button.isHidden())
        p.move("base",10,8)
        self.adapter.fail=True
        c.generate();self.wait_idle()
        self.assertIs(c.session.preview,previous)
        self.assertIn("fehlgeschlagen",p.status_label.text())
        self.window.output_root_edit.setText(str(self.f.root/"exports"))
        with patch.object(self.window,"_show_export_success_dialog"):
            c.export();self.wait_idle()
        self.assertFalse(p.export_button.isEnabled())
        self.assertEqual(c.session.export_result.output_sha256,previous.artifact_sha256)
        self.assertIs(self.window._last_export_report_result,c.session.export_result)
        self.assertIsNone(self.window.last_export_result)
        self.assertIsNone(self.window._last_exported_preview_identity)

    def test_methods_settings_results_and_reset_independent(self):
        w,p=self.window,self.panel
        original=w.collect_settings()
        p.change_setting("target_layer_time_s",20);p.move("base",30,8)
        p.change_setting("circle_segments",48)
        self.assertEqual(w.collect_settings(),original)
        manual=p.draft
        w.target_time_spin.setValue(15)
        self.assertEqual(p.draft,manual)
        w.reset_defaults()
        self.assertEqual(p.draft,manual)
        p.reset_all()
        self.assertEqual(w.target_time_spin.value(),w.settings_store.load_defaults().target_layer_time_s)
        self.assertNotEqual(original.target_layer_time_s,20)
        self.assertIs(w.current_preview,w.generation_sessions[GenerationMode.AUTOMATIC].preview)

    def test_managed_jobs_lock_navigation_and_context_then_release_after_thread_end(self):
        c,p,w=self.controller,self.panel,self.window
        c.generate()
        self.assertFalse(w._generation_method_change_available())
        self.assertFalse(w.drop_zone.isEnabled())
        self.assertFalse(w.machine_profile_combo.isEnabled())
        self.assertFalse(p.settings_content.isEnabled())
        self.assertFalse(p.cancel_button.isHidden())
        c.cancel();c.cancel()
        self.wait_idle()
        self.assertFalse(w.background_job_manager.has_active(JobKind.PREVIEW))
        self.assertTrue(p.settings_content.isEnabled())
        self.assertIn("abgebrochen",p.status_label.text())
        self.assertIsNotNone(p.draft)

    def test_stale_callbacks_and_context_invalidation_dispose_result(self):
        c=self.controller
        fake=SimpleNamespace(dispose=Mock())
        c.succeeded(-999,fake)
        fake.dispose.assert_called_once()
        c.generate();self.wait_idle()
        old=c.session.preview
        c.invalidate_context()
        self.assertIsNone(old._temporary_owner)
        self.assertFalse(old.artifact_path.exists())
        self.assertIsNone(c.session.preview)
        self.assertIsNone(c.session.successful_request)
        self.assertIsNone(c.session.manual_draft)
        self.assertIsNone(self.panel.draft)

    def test_request_freezes_nested_profile_values_and_excludes_auto_ranges(self):
        c,w=self.controller,self.window
        request=c.build_request(self.panel.draft)
        before=request.signature()
        self.f.profile.effective_values["printable_area"][0][0]=33
        self.assertEqual(request.signature(),before)
        self.assertEqual(request.settings.excluded_layer_ranges,())

    def test_large_spatial_render_uses_managed_job_and_rejects_old_camera_frame(self):
        import numpy as np
        c,p,w=self.controller,self.panel,self.window
        reference=replace(c.reference,object_triangles=np.tile(c.reference.object_triangles,(600,1,1)))
        p.canvas.set_reference(reference)
        p.canvas.set_view("three_quarter")
        p.canvas.grab()
        deadline=time.monotonic()+5
        while not w.background_job_manager.has_active(JobKind.MANUAL_VIEW) and time.monotonic()<deadline:
            self.app.processEvents();time.sleep(.01)
        self.assertTrue(w.background_job_manager.has_active(JobKind.MANUAL_VIEW))
        p.canvas.set_view("side")
        while w.background_job_manager.has_active(JobKind.MANUAL_VIEW) and time.monotonic()<deadline:
            self.app.processEvents();time.sleep(.01)
        self.assertFalse(w.background_job_manager.has_active(JobKind.MANUAL_VIEW))
        self.assertEqual(p.canvas.view,"side")
        self.assertIsNone(p.canvas._spatial_key())

    def test_manual_export_summary_keeps_evidence_kind_when_reopened(self):
        from cooling_tower.manual.service import ManualExportService
        c,w=self.controller,self.window
        c.generate();self.wait_idle()
        result=ManualExportService().export(c.session.preview,c.session.successful_request,self.f.root/"summary_export")
        w._last_export_report_result=result
        with patch.object(w,"_show_internal_dialog_without_flash"):
            w.show_last_export_report()
        self.assertIn("gemeinsam geprüfte",w.export_success_achieved_label.text())
        self.assertIn("vollständigen gemeinsamen Slice",w.export_success_usage_label.text())

    def test_spatial_gcode_renderer_uses_original_paths_and_honors_cancellation(self):
        from threading import Event
        from cooling_tower.gui.manual_view_worker import render_spatial_object
        from cooling_tower.preview import PreviewCancelled
        p=self.panel
        reference=replace(self.controller.reference,object_triangles=None,silhouette=None)
        p.canvas.set_reference(reference)
        p.canvas.set_view("three_quarter")
        image=render_spatial_object(reference,p.canvas._spatial_frame(),p.draft.settings,Event())
        self.assertFalse(image.isNull())
        self.assertTrue(any(bytes(image.constBits())))
        event=Event();event.set()
        with self.assertRaises(PreviewCancelled):
            render_spatial_object(reference,p.canvas._spatial_frame(),p.draft.settings,event)

    def test_pending_spatial_render_cannot_start_during_window_shutdown(self):
        p,w=self.panel,self.window
        p.canvas.set_view("three_quarter")
        w._closing=True
        p.canvas._start_spatial_render()
        self.assertFalse(w.background_job_manager.has_active(JobKind.MANUAL_VIEW))
        w._closing=False

    def test_cancel_running_process_releases_tree_and_preserves_previous_result(self):
        from cooling_tower.slicers.process import create_slicer_process_runner
        from cooling_tower.slicers import SliceResult
        c,p,w=self.controller,self.panel,self.window
        c.generate();self.wait_idle()
        previous=c.session.preview
        original=p.draft
        p.move("base",8,8)
        marker=self.f.root/"process_started.txt"
        process_outcomes=[]
        def blocking_slice(request):
            script="import os,time,pathlib; pathlib.Path(r'"+str(marker)+"').write_text(str(os.getpid())); time.sleep(30)"
            outcome=create_slicer_process_runner("python_fake").run(sys.executable,("-c",script),working_directory=self.f.root,
                                                                    timeout_s=35,cancellation_event=request.cancellation_event)
            process_outcomes.append(outcome)
            return SliceResult(False,outcome.return_code,(),(),None,(),outcome.stdout,outcome.stderr,outcome.duration_s,cancelled=outcome.cancelled)
        self.adapter.slice_model=blocking_slice
        c.generate()
        deadline=time.monotonic()+5
        while not marker.exists() and time.monotonic()<deadline:
            self.app.processEvents();time.sleep(.01)
        self.assertTrue(marker.exists(),p.status_label.text())
        c.cancel();c.cancel();self.wait_idle()
        self.assertTrue(process_outcomes[0].cancelled)
        self.assertIsNotNone(process_outcomes[0].return_code)
        self.assertIs(c.session.preview,previous)
        self.assertNotEqual(p.draft,original)
        self.assertTrue(previous.artifact_path.exists())
        self.assertFalse(w.background_job_manager.active_jobs())

    def test_close_window_cancels_running_worker_and_releases_resources(self):
        from threading import Event
        from cooling_tower.preview import PreviewCancelled
        c=self.controller
        started=Event()
        def blocked_prepare(request,*,cancellation_event,progress_callback):
            started.set()
            cancellation_event.wait(5)
            raise PreviewCancelled()
        c.service.prepare=blocked_prepare
        c.generate()
        deadline=time.monotonic()+2
        while not started.is_set() and time.monotonic()<deadline:
            self.app.processEvents();time.sleep(.01)
        self.assertTrue(started.is_set())
        self.window.close();self.app.processEvents()
        self.assertFalse(self.window.background_job_manager.active_jobs())


if __name__ == "__main__":unittest.main()
