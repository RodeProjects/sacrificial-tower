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

from PySide6.QtCore import QEvent,QPointF,Qt,QPoint,QObject
from PySide6.QtGui import QWheelEvent,QFont,QFontDatabase,QColor,QImage,QPainter
from PySide6.QtWidgets import QApplication,QStyle,QStyleOptionSlider,QPushButton
from PySide6.QtTest import QTest
from cooling_tower.gui.main_window import MainWindow
from cooling_tower.gui.manual_panel import ManualGenerationPanel
from cooling_tower.gui.widgets.layer_range_canvas import LayerRangeCanvas
from cooling_tower.gui.background_jobs import JobKind
from cooling_tower.gui.generation_session import GenerationMode
from cooling_tower.manual.geometry import ManualSettings,move_point,GeometryError
from cooling_tower.preview import PreviewState
from test_manual_generation import create_fixture
from gui_lifecycle import dispose_test_widget


def preview_test_application():
    app=QApplication.instance() or QApplication([])
    previous_font=QFont(app.font())
    font_id=-1
    # The Windows offscreen plugin can start without system font discovery.
    # Use the same installed font as the application for meaningful layout QA.
    font_path=Path("C:/Windows/Fonts/segoeui.ttf")
    if os.name == "nt" and font_path.is_file():
        font_id=QFontDatabase.addApplicationFont(str(font_path))
        if font_id >= 0:
            app.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0],10))
    return app,previous_font,font_id


def restore_preview_test_application(app,previous_font,font_id):
    if font_id >= 0:
        QFontDatabase.removeApplicationFont(font_id)
    app.setFont(previous_font)
    app.processEvents()


def preview_row(panel,name):
    identity={"minimum_diameter_mm":"minimum_diameter_mm","maximum_diameter_mm":"maximum_diameter_mm",
              "maximum_foot_diameter_mm":"maximum_foot_diameter_mm","base_diameter_mm":"base",
              "foot_diameter_mm":"foot","foot_height_mm":"foot_height","height_mm":"top",
              "top_diameter_mm":"top_width"}.get(name)
    if identity is not None:panel.select(identity)
    return panel.point_editor.rows[name]


def enter_preview_value(panel,name,value):
    row=preview_row(panel,name)
    row.editor.setFocus();row.editor.selectAll()
    QTest.keyClicks(row.editor,str(value).replace(".",","))
    QTest.keyClick(row.editor,Qt.Key.Key_Return)
    return row


class ManualGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app,cls._previous_font,cls._test_font_id=preview_test_application()

    @classmethod
    def tearDownClass(cls):restore_preview_test_application(cls.app,cls._previous_font,cls._test_font_id)

    def setUp(self):
        self.f,self.service,self.reference,self.request,self.adapter=create_fixture(self,joint=True,count=200)
        self.panel=ManualGenerationPanel()
        self.panel.initialize(self.reference)
        self.panel.set_busy(False)
        self.panel.resize(1400,900)
        self.panel.show();self.app.processEvents()
        self.addCleanup(dispose_test_widget,self.panel)

    def test_normal_foot_default_is_limited_by_actual_bed_object_and_brim(self):
        from cooling_tower.models.calibration import BedBounds, BedGeometry, OccupiedBounds
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
        from cooling_tower.models.calibration import BedBounds, BedGeometry, OccupiedBounds
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

    def test_bidirectional_diameter_handles_and_numeric_values(self):
        enter_preview_value(self.panel,"base_diameter_mm",10)
        self.assertEqual(self.panel.draft.base_diameter_mm,10)
        self.panel.move("base",20,90)
        self.assertEqual(preview_row(self.panel,"base_diameter_mm").field.value,20)
        self.assertEqual(self.panel.draft.settings.foot_height_mm,8)
        self.panel.move("foot_height",999,10)
        self.assertEqual(self.panel.draft.base_diameter_mm,20)
        self.assertEqual(preview_row(self.panel,"foot_height_mm").field.value,10)
        self.panel.move("top",999,35)
        self.assertEqual(self.panel.draft.height_mm,35)
        self.assertEqual(self.panel.draft.points[-1].position.diameter_mm,20)

    def test_redundant_left_controls_are_absent_and_preview_point_actions_work(self):
        p=self.panel;c=p.canvas
        removed={"minimum_diameter_mm","maximum_diameter_mm","base_diameter_mm","foot_diameter_mm",
                 "maximum_foot_diameter_mm","foot_height_mm","height_mm","top_diameter_mm",
                 "point_diameter_mm","point_height_mm"}
        self.assertFalse(removed & p.rows.keys())
        buttons={button.text() for button in p.settings_content.findChildren(QPushButton)}
        self.assertFalse({"Punkt hinzufügen","Punkt entfernen"} & buttons)
        self.assertIn("control_diameter_mm",p.rows)
        self.assertIn("control_height_mm",p.rows)
        for view in ("side","front"):
            for key in (Qt.Key.Key_Delete,Qt.Key.Key_Backspace):
                with self.subTest(view=view,key=key):
                    c.set_view(view)
                    position=c.profile_to_screen(p.draft.radius_at_z(20),20).toPoint()
                    QTest.mouseDClick(c,Qt.MouseButton.LeftButton,pos=position)
                    identity=p.selected
                    self.assertEqual(len(p.draft.points),4)
                    enter_preview_value(p,"point_diameter_mm",15.123456)
                    self.assertAlmostEqual(p.draft.points[2].position.diameter_mm,15.123456)
                    c.setFocus();QTest.keyClick(c,key)
                    self.assertNotIn(identity,{point.identity for point in p.draft.points})
                    self.assertEqual(len(p.draft.points),3)
                    self.reference.context.validate(p.draft)

    def test_object_height_defines_foot_default_and_required_limit_growth_becomes_object_default(self):
        p=self.panel
        context=replace(self.reference.context,key="height-200",maximum_height_mm=300,
            layers=(replace(self.reference.context.layers[0],z_mm=.2),replace(self.reference.context.layers[-1],z_mm=200)))
        reference=replace(self.reference,context=context)
        preferences=replace(ManualSettings(),foot_diameter_mm=25,maximum_foot_diameter_mm=30)
        p.initialize(reference,preferences)
        physical_limit=context.maximum_foot_diameter_mm
        self.assertEqual((p.settings.foot_diameter_mm,p.settings.maximum_foot_diameter_mm),(52.5,physical_limit))
        self.assertEqual(p.default_value("foot_diameter_mm"),52.5)
        self.assertEqual(p.default_value("maximum_foot_diameter_mm"),physical_limit)
        self.assertFalse(preview_row(p,"foot_diameter_mm").reset.isEnabled())
        self.assertFalse(preview_row(p,"maximum_foot_diameter_mm").reset.isEnabled())
        p.move("top",5,40)
        self.assertEqual(p.default_value("foot_diameter_mm"),52.5)
        enter_preview_value(p,"foot_diameter_mm",30)
        self.assertEqual(p.settings.foot_diameter_mm,30)
        preview_row(p,"foot_diameter_mm").reset.click()
        self.assertEqual(p.settings.foot_diameter_mm,52.5)
        for view in ("side","bottom"):
            p.change_setting("maximum_foot_diameter_mm",52.5)
            p.canvas.set_view(view)
            p._move_from_canvas("foot",95,p.draft.first_layer_z_mm)
            self.assertEqual((p.settings.foot_diameter_mm,p.settings.maximum_foot_diameter_mm),(95,95))
            self.assertEqual(p.default_value("maximum_foot_diameter_mm"),95)
            self.assertFalse(preview_row(p,"maximum_foot_diameter_mm").reset.isEnabled())
            p.move("foot",90,p.draft.first_layer_z_mm)
            self.assertEqual(p.settings.maximum_foot_diameter_mm,95)
            p.change_setting("maximum_foot_diameter_mm",100)
            self.assertEqual(p.default_value("maximum_foot_diameter_mm"),95)
            self.assertTrue(preview_row(p,"maximum_foot_diameter_mm").reset.isEnabled())
            preview_row(p,"maximum_foot_diameter_mm").reset.click()
            self.assertEqual(p.settings.maximum_foot_diameter_mm,95)
            p.reset_tower()
            self.assertEqual((p.settings.foot_diameter_mm,p.settings.maximum_foot_diameter_mm),(52.5,95))
            p.move("foot",90,p.draft.first_layer_z_mm);p.reset_all()
            self.assertEqual((p.settings.foot_diameter_mm,p.settings.maximum_foot_diameter_mm),(52.5,95))
            self.assertFalse(p.can_reset_all())
        context=replace(context,key="height-100",layers=(*context.layers[:-1],replace(context.layers[-1],z_mm=100)))
        p.initialize(replace(reference,context=context),ManualSettings())
        self.assertEqual((p.default_value("foot_diameter_mm"),p.default_value("maximum_foot_diameter_mm")),(31.25,context.maximum_foot_diameter_mm))
        p.initialize(reference,replace(ManualSettings(),minimum_diameter_mm=50,maximum_diameter_mm=60))
        self.assertEqual((p.settings.foot_diameter_mm,p.default_value("foot_diameter_mm")),(52.5,52.5))
        enter_preview_value(p,"foot_diameter_mm",60)
        preview_row(p,"foot_diameter_mm").reset.click()
        self.assertEqual(p.settings.foot_diameter_mm,52.5)
        p.reset_tower()
        self.assertEqual(p.settings.foot_diameter_mm,52.5)
        self.assertFalse(p.can_reset_tower())

    def test_left_settings_use_two_sections_without_removed_controls(self):
        from PySide6.QtWidgets import QLabel, QCheckBox, QComboBox
        from cooling_tower.gui.widgets import SectionCard
        p=self.panel
        cards=p.settings_content.findChildren(SectionCard)
        self.assertEqual([card.title_label.text() for card in cards],
                         ["Turmform und Bearbeitung","Visuelle Prüfung"])
        self.assertNotIn("contraction_angle_deg",p.editors)
        self.assertNotIn("contraction_enabled",p.checks)
        self.assertFalse(p.settings_content.findChildren(QComboBox))
        texts=[widget.text() for cls in (QLabel,QCheckBox)
               for widget in p.settings_content.findChildren(cls)]
        for removed in ("Verjüngung begrenzen","Maximaler Verjüngungswinkel",
                        "Tangenten am ausgewählten Punkt koppeln","Kritische Original-Layer anzeigen"):
            self.assertNotIn(removed,texts)
        self.assertFalse(any("Die Farben vergleichen" in text or "Profilwert (90" in text for text in texts))

    def test_layer_time_controls_are_hidden_until_enabled_and_only_change_colors(self):
        p=self.panel
        before=p.draft.artifact_payload()
        self.assertTrue(p.color_settings.isHidden())
        self.assertFalse(p.color_range_slider.isVisible())
        p.color_enabled_checkbox.click()
        self.assertFalse(p.color_settings.isHidden())
        p.color_range_slider.request_value("red",6)
        self.assertEqual((p.settings.color_reference_time_s,p.settings.color_red_time_s),(9,6))
        p.color_range_slider.request_value("green",12)
        self.assertEqual((p.settings.color_reference_time_s,p.settings.color_red_time_s),(12,6))
        p.color_range_slider.request_value("red",3)
        self.assertEqual((p.settings.color_reference_time_s,p.settings.color_red_time_s),(12,3))
        p.color_range_slider.request_value("red",0)
        self.assertLess(p.settings.color_red_time_s,12)
        p.color_scale_spin.setValue(28)
        p.color_range_slider.request_value("green",20)
        self.assertLess(p.settings.color_red_time_s,20)
        self.assertEqual(p.settings.color_red_time_s,0)
        p.color_enabled_checkbox.click()
        self.assertTrue(p.color_settings.isHidden())
        p.color_enabled_checkbox.click()
        self.assertEqual(p.color_range_slider.green_time,20)
        self.assertEqual(p.draft.artifact_payload(),before)

    def test_color_fields_and_checkboxes_have_requested_layout_with_application_styles(self):
        from PySide6.QtWidgets import QLabel,QStyleOptionButton
        p=self.panel
        p.setStyleSheet((Path(__file__).resolve().parents[1]/"src/cooling_tower/gui/styles.qss").read_text(encoding="utf-8"))
        p.color_enabled_checkbox.click();self.app.processEvents()
        from PySide6.QtWidgets import QDoubleSpinBox
        self.assertEqual(p.color_settings.findChildren(QDoubleSpinBox),[p.color_scale_spin])
        self.assertEqual([item.text() for item in p.color_range_slider.zone_labels],["Rot","Übergang","Grün"])
        self.assertFalse(p.color_settings.findChildren(QPushButton))
        for checkbox in (p.checks["expansion_enabled"],p.color_enabled_checkbox):
            self.assertEqual(checkbox.layoutDirection(),Qt.LayoutDirection.RightToLeft)
            option=QStyleOptionButton();checkbox.initStyleOption(option)
            indicator=checkbox.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator,option,checkbox)
            contents=checkbox.style().subElementRect(QStyle.SubElement.SE_CheckBoxContents,option,checkbox)
            self.assertGreater(indicator.left(),contents.right())
            self.assertLess(checkbox.width(),checkbox.parentWidget().width()-30)

    def test_layer_time_settings_sync_after_undo_and_all_reset(self):
        p=self.panel
        preferences=replace(p.settings,color_reference_time_s=12,color_deficit_time_s=6,critical_layers_enabled=True)
        p.initialize(self.reference,preferences)
        self.assertEqual((p.color_range_slider.green_time,p.color_range_slider.red_time),(12,6))
        p.color_range_slider.request_value("red",30)
        p.undo()
        self.assertEqual(p.settings,preferences)
        self.assertEqual((p.color_range_slider.green_time,p.color_range_slider.red_time),(12,6))
        p.reset_all()
        self.assertTrue(p.color_settings.isHidden())
        self.assertEqual((p.settings.color_reference_time_s,p.settings.color_red_time_s),(9,5))

    def test_color_scale_and_points_follow_busy_state_and_all_reset(self):
        p=self.panel
        p.color_enabled_checkbox.click()
        p.color_scale_spin.setValue(28)
        p.color_range_slider.request_value("green",12)
        p.set_busy(True)
        self.assertFalse(p.color_scale_spin.isEnabled())
        self.assertFalse(p.color_range_slider.red_handle.isEnabled())
        p.color_range_slider.request_value("green",20)
        self.assertEqual(p.settings.color_reference_time_s,12)
        p.set_busy(False);p.reset_all()
        self.assertEqual((p.settings.color_reference_time_s,p.settings.color_red_time_s,p.settings.color_scale_max_time_s),(9,5,14))

    def test_tower_reset_preserves_options_and_restores_all_points_and_controls(self):
        p=self.panel
        original=p.draft
        for name,value in (("circle_segments",48),("maximum_diameter_mm",35),
                           ("maximum_foot_diameter_mm",50),("expansion_enabled",True),
                           ("expansion_angle_deg",15),("critical_layers_enabled",True),
                           ("color_reference_time_s",12),("color_deficit_time_s",6),
                           ("layer_snap_enabled",False),("overhang_enabled",False),
                           ("object_resolution_percent",5)):
            p.change_setting(name,value)
        p.full_infill_checkbox.setChecked(True)
        p.insert(20)
        p.move(p.selected,10,20)
        p.move_control(1,2,8,18)
        p.move("foot_height",25,7)
        p.move("foot",30,p.draft.first_layer_z_mm)
        p.move("top",10,30)
        preferences=p.settings
        p.reset_tower()
        self.assertEqual(p.settings,replace(preferences,foot_diameter_mm=original.foot_diameter_mm,
                                           foot_height_mm=original.settings.foot_height_mm))
        self.assertEqual(p.draft.points,original.points)
        self.assertEqual(p.draft.curves,original.curves)
        self.assertTrue(p.full_infill_checkbox.isChecked())
        self.assertFalse(p.can_reset_tower())
        self.assertTrue(p.can_reset_all())
        p.reset_all()
        self.assertEqual(p.draft,p.initial)
        self.assertFalse(p.full_infill_checkbox.isChecked())
        self.assertFalse(p.can_reset_all())

    def test_tower_reset_respects_tight_limits_and_retained_contraction_preferences(self):
        from cooling_tower.manual.geometry import initial_draft
        p=self.panel
        settings=replace(ManualSettings(),minimum_diameter_mm=10,maximum_diameter_mm=12,
                         maximum_foot_diameter_mm=11,foot_diameter_mm=11,contraction_enabled=True,
                         contraction_angle_deg=1)
        # Start from a valid narrow cylinder, then let the reset fit its foot.
        draft=initial_draft(replace(settings,maximum_foot_diameter_mm=12,contraction_enabled=False),
                            self.reference.context.layers,self.reference.context.maximum_height_mm,
                            self.reference.context.key,foot_diameter_mm=12)
        points=tuple(replace(point,position=replace(point.position,radius_mm=5)) for point in draft.points)
        curves=tuple(replace(curve,**{name:replace(getattr(curve,name),radius_mm=5)
                     for name in ("start","control1","control2","end")}) for curve in draft.curves)
        p.commit(replace(draft,settings=replace(settings,foot_diameter_mm=10),points=points,curves=curves))
        preferences=p.settings
        p.reset_tower()
        self.reference.context.validate(p.draft)
        self.assertEqual(p.settings,replace(preferences,foot_diameter_mm=p.draft.foot_diameter_mm))
        self.assertLessEqual(p.draft.foot_diameter_mm,11)
        self.assertEqual(p.draft.base_diameter_mm,10)
        self.assertFalse(p.can_reset_tower())

    def test_manual_field_feedback_shows_reason_for_two_seconds_and_preserves_canvas(self):
        from cooling_tower.gui.design_tokens import COLORS
        p=self.panel;row=p.rows["circle_segments"]
        normal_label=row.label.styleSheet();normal_editor=row.editor.styleSheet()
        geometry=row.geometry();canvas=p.canvas.geometry()
        p.feedback(GeometryError("circle_segments","Grenze überschritten"),"points")
        self.assertTrue(row.message_container.isVisible())
        self.assertTrue(row.message_label.isVisible())
        self.assertIn(COLORS["error"],row.label.styleSheet())
        self.assertIn(f"border-color: {COLORS['error']}",row.editor.styleSheet())
        self.assertNotIn("background",row.editor.styleSheet())
        self.assertFalse(row.editor.property("invalid"))
        self.assertEqual(row.editor.accessibleDescription(),"Grenze überschritten")
        animation=row._feedback_animation
        self.assertGreaterEqual(animation.duration(),2000)
        animation.setCurrentTime(1999)
        self.assertEqual(row._feedback_amount,1)
        p.feedback(GeometryError("circle_segments","Grenze weiter überschritten"),"points")
        self.assertEqual(animation.currentTime(),0)
        self.assertEqual(row.message_label.text(),"Grenze weiter überschritten")
        self.assertEqual(p.canvas.geometry(),canvas)
        animation.setCurrentTime(animation.duration())
        self.assertEqual(row._feedback_amount,0)
        self.assertEqual(row.label.styleSheet(),normal_label)
        self.assertEqual(row.editor.styleSheet(),normal_editor)
        p.feedback(GeometryError("circle_segments","Erneuter Versuch"),"points")
        self.assertEqual(row._feedback_amount,1)
        for candidate in p.rows.values():
            candidate.set_error("Grenze")
            self.assertFalse(candidate.message_container.isHidden())
            self.assertIn(COLORS["error"],candidate.label.styleSheet())
            candidate.set_error(None)

    def test_rotation_zero_is_centered_and_negative_angles_and_reset_work(self):
        from PySide6.QtWidgets import QStyle,QStyleOptionSlider
        p=self.panel;slider=p.rotation_slider
        option=QStyleOptionSlider();slider.initStyleOption(option)
        handle=slider.style().subControlRect(QStyle.ComplexControl.CC_Slider,option,QStyle.SubControl.SC_SliderHandle,slider)
        self.assertLessEqual(abs(handle.center().x()-slider.width()/2),2)
        slider.setValue(-47)
        deadline=time.monotonic()+1
        while p.canvas.object_rotation != -47 and time.monotonic()<deadline:QTest.qWait(20)
        self.assertEqual(p.canvas.object_rotation,-47)
        self.assertEqual(p.rotation_label.text(),"-47°")
        self.assertTrue(p.rotation_reset.isEnabled())
        QTest.keyClick(slider,Qt.Key.Key_Home);self.assertEqual(slider.value(),-180)
        QTest.keyClick(slider,Qt.Key.Key_End);self.assertEqual(slider.value(),180)
        p.rotation_reset.click()
        self.assertEqual((slider.value(),p.canvas.object_rotation),(0,0))
        self.assertFalse(p.rotation_reset.isEnabled())

    def test_rotation_track_click_jumps_directly_to_clicked_angle(self):
        p=self.panel;slider=p.rotation_slider
        option=QStyleOptionSlider();slider.initStyleOption(option)
        groove=slider.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,option,QStyle.SubControl.SC_SliderGroove,slider)
        for angle in (90,-90,180,-180,0):
            with self.subTest(angle=angle):
                position=QPoint(slider.snap_positions()[angle],groove.center().y())
                QTest.mouseClick(slider,Qt.MouseButton.LeftButton,pos=position)
                self.assertEqual(slider.value(),angle)
                self.assertEqual(p.rotation_label.text(),f"{angle}°")
                deadline=time.monotonic()+1
                while p.canvas.object_rotation != angle and time.monotonic()<deadline:QTest.qWait(20)
                self.assertEqual(p.canvas.object_rotation,angle)

    def test_rotation_track_press_allows_continued_dragging(self):
        slider=self.panel.rotation_slider
        option=QStyleOptionSlider();slider.initStyleOption(option)
        groove=slider.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,option,QStyle.SubControl.SC_SliderGroove,slider)
        positions=slider.snap_positions()
        start=QPoint(positions[90],groove.center().y())
        target=QPoint(positions[-90],groove.center().y())
        QTest.mousePress(slider,Qt.MouseButton.LeftButton,pos=start)
        self.assertTrue(slider.isSliderDown())
        self.assertEqual(slider.value(),90)
        QTest.mouseMove(slider,target)
        self.assertEqual(slider.value(),-90)
        QTest.mouseRelease(slider,Qt.MouseButton.LeftButton,pos=target)
        self.assertFalse(slider.isSliderDown())
        self.assertEqual(slider.value(),-90)

    def test_exact_silhouette_follows_all_views_and_rotation_and_reuses_picture_for_navigation(self):
        from cooling_tower.gui import manual_view_worker
        p=self.panel;c=p.canvas
        for view in ("side","front","top","bottom","free"):
            c.set_view(view);p.change_setting("object_resolution_percent",5)
            self.assertTrue(c._spatial_render_frame().exact_silhouette)
            c._object_cache=None
            with patch.object(manual_view_worker,"original_silhouette_path",wraps=manual_view_worker.original_silhouette_path) as contours:
                c.grab()
                self.assertEqual(contours.call_count,1)
                picture=c._object_cache
                c.pan+=QPointF(12,7);c.zoom*=1.2;c.grab()
                self.assertIs(c._object_cache,picture)
                contours.reset_mock()
                c.set_rotation(37 if c.object_rotation!=37 else -37);c.grab()
                self.assertIsNot(c._object_cache,picture)
                self.assertEqual(contours.call_count,1)

    def test_height_grip_snaps_to_object_top_and_layers_with_optional_continuous_drag(self):
        p=self.panel;canvas=p.canvas
        object_top=self.reference.context.layers[-1].z_mm
        for view in ("side","front"):
            canvas.set_view(view)
            canvas.zoom=8;canvas.pan=QPointF(17,-20)
            p.move("top",5,object_top)
            top=next(pos for name,pos,_ in canvas.handles() if name=="top")
            canvas.pan+=QPointF(0,canvas.height()/2-top.y())
            top=next(pos for name,pos,_ in canvas.handles() if name=="top")
            near=(top+QPointF(0,3)).toPoint()
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
            from cooling_tower.manual.layer_snap import snap_layer_height
            expected=snap_layer_height(canvas.screen_to_profile(QPointF(farther))[1],canvas._layer_tops)
            QTest.mousePress(canvas,Qt.MouseButton.LeftButton,pos=top.toPoint())
            QTest.mouseMove(canvas,farther)
            QTest.mouseRelease(canvas,Qt.MouseButton.LeftButton,pos=farther)
            self.assertAlmostEqual(p.draft.height_mm,expected)
            self.assertLess(p.draft.height_mm,object_top)
            self.assertIsNone(canvas._height_snap_z)
        enter_preview_value(p,"height_mm",object_top-.03)
        self.assertAlmostEqual(p.draft.height_mm,object_top-.03)
        self.assertIsNone(canvas._height_snap_z)
        p.checks["layer_snap_enabled"].setChecked(False)
        top=next(pos for name,pos,_ in canvas.handles() if name=="top")
        target=(top+QPointF(0,7)).toPoint()
        expected=canvas.screen_to_profile(QPointF(target))[1]
        QTest.mousePress(canvas,Qt.MouseButton.LeftButton,pos=top.toPoint())
        QTest.mouseMove(canvas,target)
        QTest.mouseRelease(canvas,Qt.MouseButton.LeftButton,pos=target)
        self.assertAlmostEqual(p.draft.height_mm,expected)
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
                    p.select("foot_height" if identity=="control:0:2" else "foot" if identity.startswith("control:") else identity)
                    canvas.fit_scene();canvas.zoom=2
                    handle=next(pos for name,pos,_ in canvas.handles() if name==identity)
                    canvas.pan+=QPointF(canvas.width()/2-handle.x(),canvas.height()/2-handle.y())
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

    def test_manual_width_limit_guide_flashes_expires_and_reappears_on_new_attempts(self):
        p=self.panel;c=p.canvas
        for view in ("side","front"):
            with self.subTest(view=view):
                p.reset_all();c.set_view(view)
                p.change_setting("maximum_diameter_mm",12)
                p.insert(20);identity=p.selected;c.fit_scene();c.grab()
                original_cache=c._object_cache
                handle=next(pos for name,pos,_ in c.handles() if name==identity).toPoint()
                target=handle+QPoint(round((12-5)/2*c.transform()[0])+8,0)
                QTest.mousePress(c,Qt.MouseButton.LeftButton,pos=handle)
                QTest.mouseMove(c,target)
                self.assertEqual(c._width_limit_setting,"maximum_diameter_mm")
                self.assertAlmostEqual(p.draft.points[2].position.diameter_mm,12)
                image=c.grab().toImage()
                position=c.profile_to_screen(6,12).toPoint()
                self.assertTrue(any(image.pixelColor(x,y).blue()>image.pixelColor(x,y).red()+70 and
                                    image.pixelColor(x,y).blue()>image.pixelColor(x,y).green()+35
                                    for x in range(position.x()-2,position.x()+3)
                                    for y in range(position.y()-2,position.y()+3)))
                # Drive the animation clock explicitly: runner timer ticks can
                # arrive late even while mouse events are processed normally.
                c._width_limit_animation.setCurrentTime(80)
                elapsed=c._width_limit_animation.currentTime()
                self.assertEqual(c._width_limit_opacity,1)
                QTest.mouseMove(c,target+QPoint(2,0))
                self.assertGreaterEqual(c._width_limit_animation.currentTime(),elapsed)
                c._width_limit_animation.setCurrentTime(c.WIDTH_LIMIT_GUIDE_DURATION_MS)
                self.assertIsNone(c._width_limit_setting)
                QTest.mouseMove(c,target+QPoint(4,0))
                self.assertEqual(c._width_limit_setting,"maximum_diameter_mm")
                QTest.mouseRelease(c,Qt.MouseButton.LeftButton,pos=target+QPoint(4,0))
                c._width_limit_animation.setCurrentTime(c.WIDTH_LIMIT_GUIDE_DURATION_MS)
                self.assertIsNone(c._width_limit_setting)
                handle=next(pos for name,pos,_ in c.handles() if name==identity).toPoint()
                QTest.mousePress(c,Qt.MouseButton.LeftButton,pos=handle)
                QTest.mouseMove(c,handle+QPoint(8,0))
                self.assertEqual(c._width_limit_setting,"maximum_diameter_mm")
                self.assertIs(c._object_cache,original_cache)
                QTest.mouseRelease(c,Qt.MouseButton.LeftButton,pos=handle+QPoint(8,0))
                c.set_view("top")
                self.assertIsNone(c._width_limit_setting)
                self.assertEqual(c._width_limit_opacity,0)
                self.assertEqual(c._width_limit_animation.state(),c._width_limit_animation.State.Stopped)

    def test_width_limit_guide_holds_for_350_ms_then_fades_for_200_ms(self):
        c=self.panel.canvas
        c.grab();original_image=c._object_image_cache
        c.set_width_limit_feedback("maximum_diameter_mm",41)
        self.assertEqual(c._width_limit_opacity,1)
        self.assertEqual(c._width_limit_animation.duration(),550)
        c._width_limit_animation.setCurrentTime(350)
        self.assertEqual(c._width_limit_opacity,1)
        c._width_limit_animation.setCurrentTime(450)
        self.assertAlmostEqual(c._width_limit_opacity,.5)
        c.grab()
        self.assertIs(c._object_image_cache,original_image)
        c._width_limit_animation.setCurrentTime(550)
        self.assertIsNone(c._width_limit_setting)
        self.assertEqual(c._width_limit_opacity,0)
        c.set_width_limit_feedback("maximum_diameter_mm",42)
        self.assertEqual(c._width_limit_opacity,1)
        c.set_view("top")
        self.assertIsNone(c._width_limit_setting)
        self.assertEqual(c._width_limit_opacity,0)

    def test_width_limit_guide_only_responds_to_horizontal_canvas_edits(self):
        p=self.panel;c=p.canvas
        p.change_setting("maximum_diameter_mm",12)
        p.insert(20);identity=p.selected
        p.move(identity,12,20)
        self.assertIsNone(c._width_limit_setting)
        with patch.object(c,"horizontal_drag_snaps",return_value=True):
            p._move_from_canvas("base",15,8)
            self.assertEqual(c._width_limit_setting,"maximum_diameter_mm")
            c._hide_width_limit_guide()
            p._move_from_canvas(identity,10,20)
            p._move_from_canvas(identity,12,20)
            self.assertEqual(c._width_limit_setting,"maximum_diameter_mm")
            p._move_from_canvas(identity,4,20)
            self.assertEqual(c._width_limit_setting,"minimum_diameter_mm")
            self.assertAlmostEqual(p.draft.points[2].position.diameter_mm,5)
            before=p.draft
            p.set_busy(True)
            p._move_from_canvas(identity,10,20)
            self.assertIs(p.draft,before)
            p.set_busy(False)
        c.invalidate_reference()
        self.assertIsNone(c._width_limit_setting)

    def test_fixed_base_tip_and_foot_show_their_own_width_limits_without_rendering_original_again(self):
        p=self.panel;c=p.canvas
        for view in ("side","front"):
            p.reset_all();c.set_view(view)
            p.change_setting("maximum_diameter_mm",12)
            p.change_setting("maximum_foot_diameter_mm",30)
            c.fit_scene();c.grab()
            picture=c._object_cache;image=c._object_image_cache
            with patch.object(c,"horizontal_drag_snaps",return_value=True):
                for identity,requested,value,setting in (
                    ("base",15,12,"maximum_diameter_mm"),
                    ("base",2,5,"minimum_diameter_mm"),
                    ("top_width",15,12,"maximum_diameter_mm"),
                    ("top_width",2,5,"minimum_diameter_mm"),
                    ("foot",2,5,"minimum_diameter_mm")):
                    with self.subTest(view=view,identity=identity,setting=setting):
                        c._hide_width_limit_guide();c._width_limit_last_request=None
                        actual="top" if identity=="top_width" else identity
                        point=next(point for point in p.draft.points if point.identity==actual)
                        p._move_from_canvas(identity,requested,point.position.z_mm)
                        self.assertEqual(c._width_limit_setting,setting)
                        self.assertEqual(c._width_limit_opacity,1)
                        point=next(point for point in p.draft.points if point.identity==actual)
                        self.assertAlmostEqual(point.position.diameter_mm,value)
                        start,end=c.width_limit_guide_geometry()
                        radius=getattr(p.settings,setting)/2
                        self.assertEqual(start,c.profile_to_screen(radius,0))
                        self.assertEqual(end.x(),start.x())
                        painter=Mock();c._draw_scales(painter)
                        axis=next(call.args for call in painter.drawLine.call_args_list
                                  if len(call.args)==2 and all(point.x()==c.width()-43 for point in call.args))
                        self.assertEqual(end.y(),axis[0].y())
                        c.grab()
                        self.assertIs(c._object_cache,picture)
                        self.assertIs(c._object_image_cache,image)

    def test_all_vertical_handles_snap_and_keep_free_numeric_heights(self):
        from cooling_tower.manual.layer_snap import snap_layer_height
        p=self.panel;canvas=p.canvas
        self.assertTrue(p.checks["layer_snap_enabled"].isChecked())
        p.insert(20);free=p.selected
        original=p.draft
        for view in ("side","front"):
            for identity in ("top","foot_height",free,"control:0:1","control:0:2"):
                with self.subTest(view=view,identity=identity):
                    p.commit(original);canvas.set_view(view)
                    p.select("foot_height" if identity=="control:0:2" else "foot" if identity.startswith("control:") else identity)
                    canvas.zoom=4
                    handle=next(pos for name,pos,_ in canvas.handles() if name==identity)
                    canvas.pan+=QPointF(0,canvas.height()/2-handle.y())
                    handle=next(pos for name,pos,_ in canvas.handles() if name==identity)
                    target=(handle+QPointF(0,25)).toPoint()
                    QTest.mousePress(canvas,Qt.MouseButton.LeftButton,pos=handle.toPoint())
                    QTest.mouseMove(canvas,target)
                    QTest.mouseRelease(canvas,Qt.MouseButton.LeftButton,pos=target)
                    height=canvas._vertical_handle_height(identity)
                    self.assertAlmostEqual(height,snap_layer_height(height,canvas._layer_tops))
        p.commit(original);p.select(free)
        enter_preview_value(p,"point_height_mm",20.07)
        self.assertAlmostEqual(canvas._vertical_handle_height(free),20.07)
        before=p.draft.artifact_payload()
        p.checks["layer_snap_enabled"].setChecked(False)
        self.assertEqual(p.draft.artifact_payload(),before)
        handle=next(pos for name,pos,_ in canvas.handles() if name==free)
        target=(handle+QPointF(0,13)).toPoint()
        expected=canvas.screen_to_profile(QPointF(target))[1]
        QTest.mousePress(canvas,Qt.MouseButton.LeftButton,pos=handle.toPoint())
        QTest.mouseMove(canvas,target)
        QTest.mouseRelease(canvas,Qt.MouseButton.LeftButton,pos=target)
        self.assertAlmostEqual(canvas._vertical_handle_height(free),expected)

    def test_layer_snap_stops_on_valid_layer_at_neighbors_and_preserves_radial_motion(self):
        p=self.panel;canvas=p.canvas
        p.insert(20);free=p.selected
        # The geometric 39.95 mm boundary lies between actual 0.2 mm layers.
        p.move(free,18,40,layer_snap=True)
        point=next(point.position for point in p.draft.points if point.identity==free)
        self.assertAlmostEqual(point.z_mm,39.8)
        self.assertAlmostEqual(point.diameter_mm,18)
        p.move_control(1,1,0,40,layer_snap=True)
        self.assertLess(min(abs(p.draft.curves[1].control1.z_mm-z) for z in canvas._layer_tops),1e-8)
        self.reference.context.validate(p.draft)

    def test_double_click_resets_curves_and_shows_facing_fixed_neighbor_anchors(self):
        p=self.panel;canvas=p.canvas
        p.insert(20);free=p.selected
        p.select("base")
        handle=next(pos for name,pos,_ in canvas.handles() if name==free).toPoint()
        before=p.draft
        QTest.mouseClick(canvas,Qt.MouseButton.LeftButton,pos=handle)
        self.assertEqual(p.selected,free)
        expected={"control:1:1","control:1:2","control:2:1","control:2:2"}
        self.assertEqual({name for name,_,kind in canvas.handles() if kind=="control"},expected)
        self.assertEqual(p.draft,before)
        QTest.mouseClick(canvas,Qt.MouseButton.LeftButton,pos=handle)
        self.assertEqual(p.draft,before)
        QTest.mouseDClick(canvas,Qt.MouseButton.LeftButton,pos=handle)
        self.assertEqual({name for name,_,kind in canvas.handles() if kind=="control"},expected)
        self.assertEqual(p.draft.points,before.points)
        p.select("control:1:2")
        self.assertEqual({name for name,_,kind in canvas.handles() if kind=="control"},expected)
        p.move_control(1,2,7,18)
        self.assertTrue(p.draft.curves[1].curved)
        p.select(free)
        QTest.mouseDClick(canvas,Qt.MouseButton.LeftButton,pos=handle)
        self.assertTrue(all(c.curved for c in p.draft.curves[1:]))
        self.assertEqual({name for name,_,kind in canvas.handles() if kind=="control"},expected)
        reset=p.draft
        QTest.mouseDClick(canvas,Qt.MouseButton.LeftButton,pos=handle)
        self.assertEqual(p.draft,reset)
        self.assertTrue(all(c.curved for c in p.draft.curves[1:]))
        for c in p.draft.curves[1:]:
            self.assertEqual(c.control1,c.start.lerp(c.end,1/3))
            self.assertEqual(c.control2,c.start.lerp(c.end,2/3))
        p.select("base");canvas.handles()
        self.assertEqual({name for name,_,kind in canvas.handles() if kind=="control"},
                         {"control:0:1","control:0:2","control:1:1","control:1:2"})

    def test_fixed_points_and_their_controls_keep_facing_neighbor_anchors(self):
        p=self.panel;c=p.canvas
        p.insert(20);first=p.selected
        p.insert(30)
        before=p.draft
        def controls():return {name for name,_,kind in c.handles() if kind=="control"}
        for view in ("side","front"):
            c.set_view(view)
            for identity,index in (("foot",0),("base",1),("foot_height",1),
                                   (first,2),("top",4),("top_width",4)):
                with self.subTest(view=view,point=identity):
                    p.select(identity)
                    expected={f"control:{i}:{n}" for i,n in ((index-1,1),(index,2))
                              if 0 <= i < len(p.draft.curves)}
                    self.assertTrue(expected <= controls())
                    self.assertEqual(p.draft,before)
            for segment in range(len(p.draft.curves)):
                for number in (1,2):
                    identity=f"control:{segment}:{number}"
                    owner=segment+(number==2)
                    with self.subTest(view=view,control=identity):
                        p.select(identity)
                        facing={f"control:{i}:{n}" for i,n in ((owner-1,1),(owner,2))
                                if 0 <= i < len(p.draft.curves)}
                        own={f"control:{i}:{n}" for i,n in ((owner-1,2),(owner,1))
                             if 0 <= i < len(p.draft.curves)}
                        self.assertTrue(facing | {identity} <= controls())
                        self.assertTrue(controls() <= facing | own)
                        self.assertEqual(p.draft,before)
            for identity in ("",*c.LIMITS):
                p.select(identity)
                self.assertFalse(controls())

    def test_profile_double_click_shows_own_and_facing_fixed_controls(self):
        p=self.panel;c=p.canvas
        for view in ("side","front"):
            with self.subTest(view=view):
                p.reset_all();c.set_view(view)
                position=c.profile_to_screen(p.draft.radius_at_z(20),20).toPoint()
                QTest.mouseDClick(c,Qt.MouseButton.LeftButton,pos=position)
                self.assertEqual(len(p.draft.points),4)
                self.assertEqual(p.draft.points[2].identity,p.selected)
                self.assertEqual({name for name,_,kind in c.handles() if kind=="control"},
                                 {"control:1:1","control:1:2","control:2:1","control:2:2"})
                self.assertFalse(any(curve.curved for curve in p.draft.curves[1:]))
                self.reference.context.validate(p.draft)
                points=p.draft.points
                # The newly exposed fixed controls stay selectable on a linear
                # segment, then edit that segment without moving its endpoints.
                for identity in ("control:1:1","control:2:2"):
                    p.select(p.draft.points[2].identity)
                    position=next(pos.toPoint() for name,pos,_ in c.handles() if name==identity)
                    QTest.mouseClick(c,Qt.MouseButton.LeftButton,pos=position)
                    self.assertEqual(p.selected,identity)
                    self.assertIn(identity,{name for name,_,_ in c.handles()})
                    QTest.mousePress(c,Qt.MouseButton.LeftButton,pos=position)
                    QTest.mouseMove(c,position+QPoint(10,0))
                    QTest.mouseRelease(c,Qt.MouseButton.LeftButton,pos=position+QPoint(10,0))
                    index=int(identity.split(":")[1])
                    self.assertTrue(p.draft.curves[index].curved)
                    self.assertEqual(p.draft.points,points)
                    self.reference.context.validate(p.draft)

    def test_profile_double_click_keeps_existing_neighbor_curves_and_shows_new_anchors(self):
        p=self.panel;c=p.canvas
        for view in ("side","front"):
            with self.subTest(view=view):
                p.reset_all();c.set_view(view)
                p.move_control(1,1,14,15)
                p.move_control(1,2,10,30)
                before=p.draft
                p.select("base")
                position=c.profile_to_screen(before.radius_at_z(24),24).toPoint()
                QTest.mouseDClick(c,Qt.MouseButton.LeftButton,pos=position)
                self.assertEqual(len(p.draft.points),4)
                self.assertEqual(p.draft.points[2].identity,p.selected)
                self.assertEqual(p.draft.curves[0],before.curves[0])
                self.assertTrue(all(curve.curved for curve in p.draft.curves[1:]))
                for z in range(8,41):
                    self.assertAlmostEqual(p.draft.radius_at_z(z),before.radius_at_z(z),places=10)
                self.assertEqual({name for name,_,kind in c.handles() if kind=="control"},
                                 {"control:1:1","control:1:2","control:2:1","control:2:2"})
                self.reference.context.validate(p.draft)

    def test_double_click_resets_fixed_point_curves_and_keeps_own_anchors_visible(self):
        p=self.panel;c=p.canvas
        for view,identities in (("side",("foot","foot_height","base","top","top_width")),
                                ("front",("foot","foot_height","base","top","top_width"))):
            for identity in identities:
                p.reset_all();c.set_view("side")
                original=p.draft
                p.move_control(0,1,14,3)
                p.move_control(1,2,7,30)
                c.set_view(view);p.select(identity)
                position=next(pos.toPoint() for name,pos,_ in c.handles() if name==identity)
                QTest.mouseDClick(c,Qt.MouseButton.LeftButton,pos=position)
                self.assertEqual(p.selected,identity)
                self.assertEqual(p.draft.points,original.points)
                if identity in {"foot","foot_height","base"}:
                    self.assertEqual(p.draft.curves[0],original.curves[0])
                if identity in {"base","top","top_width"}:
                    curve=p.draft.curves[-1]
                    self.assertTrue(curve.curved)
                    self.assertEqual(curve.control2,curve.start.lerp(curve.end,2/3))
                if view in {"side","front"}:
                    self.assertTrue(any(kind=="control" for _,_,kind in c.handles()))
                self.reference.context.validate(p.draft)

    def test_plan_views_ignore_curve_reset_double_clicks_and_omit_the_help_item(self):
        p=self.panel;c=p.canvas
        p.move_control(0,1,14,3);p.move_control(1,2,7,30)
        for view,identity in (("top","top_width"),("bottom","foot")):
            c.set_view(view)
            before=p.draft
            position=next(pos.toPoint() for name,pos,_ in c.handles() if name==identity)
            with patch.object(p,"reset_point_curves") as reset:
                QTest.mouseDClick(c,Qt.MouseButton.LeftButton,pos=position)
                reset.assert_not_called()
            self.assertEqual(p.draft,before)
            self.assertNotIn("Doppelklick",p.view_hint.text())

    def test_preview_hover_has_no_popup_hint_on_handles_or_empty_space(self):
        c=self.panel.canvas
        for view in ("side","front","top","bottom","free"):
            c.set_view(view)
            positions=[QPoint(100,100),*(pos.toPoint() for _,pos,_ in c.handles())]
            for position in positions:
                QTest.mouseMove(c,position)
                self.assertEqual(c.toolTip(),"")

    def test_profile_views_render_only_the_original_as_a_shaded_mesh_with_aligned_heights(self):
        import numpy as np
        from cooling_tower.gui.widgets import manual_canvas
        from cooling_tower.gui import manual_view_worker
        p=self.panel;c=p.canvas
        source=self.reference.object_triangles.copy()
        for view,yaw in (("side",0),("front",90)):
            c.set_view(view)
            p.change_setting("object_resolution_percent",15)
            c._object_cache=None
            with patch.object(c,"_tower_picture",wraps=c._tower_picture) as tower,\
                 patch.object(manual_view_worker,"draw_surface",wraps=manual_view_worker.draw_surface) as surfaces:
                c.grab()
                tower.assert_not_called()
                self.assertGreaterEqual(surfaces.call_count,len(source))
                self.assertIsNotNone(c._object_cache.material)
            frame=c._spatial_frame()
            self.assertEqual((frame.yaw,frame.pitch),(yaw,0))
            projected,_=frame.project(np.array([(*c._object_center,0),(*c._object_center,20)]))
            for z,point in zip((0,20),projected):
                self.assertAlmostEqual(point[1],c.profile_to_screen(0,z).y())
            self.assertTrue(p.resolution_host.isVisible())
            original=c._object_cache
            # The initial 75 % view may already be cached. Exercise an actual
            # cache miss here so this assertion checks resolution rendering.
            c._object_pictures.clear()
            with patch.object(manual_canvas,"render_spatial_object",wraps=manual_canvas.render_spatial_object) as render:
                p.resolution_slider.setValue(8 if view=="side" else 1);c.grab()
                self.assertEqual(render.call_count,1)
            self.assertIsNot(c._object_cache,original)
            np.testing.assert_array_equal(self.reference.object_triangles,source)

    def test_profile_tower_actions_reuse_original_surfaces_and_rotation_rebuilds_once_per_changed_value(self):
        p=self.panel;c=p.canvas
        for view in ("side","front"):
            p.reset_all();c.set_view(view);c.grab()
            original=c._object_cache
            with patch.object(c,"_render_object",wraps=c._render_object) as render:
                p.move("base",8,p.settings.foot_height_mm);c.grab()
                p.move("foot_height",8,9);c.grab()
                p.insert(20);free=p.selected;c.grab()
                p.reset_point_curves(free);c.grab()
                p.move_control(1,2,7,18);c.grab()
                p.remove(free);c.grab()
                p.change_setting("maximum_diameter_mm",50);c.grab()
                p.change_setting("circle_segments",60);c.grab()
                p.reset_tower();c.grab()
                p.reset_all();c.grab()
                render.assert_not_called()
                self.assertIs(c._object_cache,original)
                c.set_rotation(37);c.grab()
                self.assertEqual(render.call_count,1)
                rotated=c._object_cache
                c.set_rotation(37);c.grab();c.grab()
                self.assertEqual(render.call_count,1)
                self.assertIs(c._object_cache,rotated)
                c.set_rotation(38);c.grab();c.grab()
                self.assertEqual(render.call_count,2)

    def test_single_click_reveals_both_own_controls_after_dragging_linear_point(self):
        p=self.panel;c=p.canvas
        for view in ("side","front"):
            p.reset_all();c.set_view(view);p.insert(20);free=p.selected
            p.select("base")
            before=next(point.position for point in p.draft.points if point.identity==free)
            position=next(pos.toPoint() for name,pos,_ in c.handles() if name==free)
            QTest.mousePress(c,Qt.MouseButton.LeftButton,pos=position)
            QTest.mouseMove(c,position+QPoint(13,-7))
            QTest.mouseRelease(c,Qt.MouseButton.LeftButton,pos=position+QPoint(13,-7))
            after=next(point.position for point in p.draft.points if point.identity==free)
            self.assertNotEqual(after,before)
            self.assertFalse(any(curve.curved for curve in p.draft.curves[1:]))
            self.assertEqual({name for name,_,kind in c.handles() if kind=="control"},
                             {"control:1:1","control:1:2","control:2:1","control:2:2"})
            draft=p.draft
            position=next(pos.toPoint() for name,pos,_ in c.handles() if name==free)
            QTest.mouseClick(c,Qt.MouseButton.LeftButton,pos=position)
            self.assertEqual(p.draft,draft)
            self.assertEqual({name for name,_,kind in c.handles() if kind=="control"},
                             {"control:1:1","control:1:2","control:2:1","control:2:2"})
            self.reference.context.validate(p.draft)
            # Revealed controls must not capture the point's next drag.
            QTest.mousePress(c,Qt.MouseButton.LeftButton,pos=position)
            QTest.mouseMove(c,position+QPoint(-9,4))
            QTest.mouseRelease(c,Qt.MouseButton.LeftButton,pos=position+QPoint(-9,4))
            self.assertNotEqual(next(point.position for point in p.draft.points if point.identity==free),after)
            self.assertFalse(any(curve.curved for curve in p.draft.curves[1:]))
            self.assertEqual({name for name,_,kind in c.handles() if kind=="control"},
                             {"control:1:1","control:1:2","control:2:1","control:2:2"})

    def test_single_click_controls_follow_selected_point_and_can_edit_linear_segments(self):
        p=self.panel;c=p.canvas
        p.insert(20);first=p.selected
        p.insert(25);second=p.selected
        p.insert(30);third=p.selected
        p.select("base")
        before=p.draft
        for free,index in ((first,2),(second,3),(third,4)):
            position=next(pos.toPoint() for name,pos,_ in c.handles() if name==free)
            QTest.mouseClick(c,Qt.MouseButton.LeftButton,pos=position)
            self.assertEqual(p.draft,before)
            expected={f"control:{index-1}:1",f"control:{index-1}:2",
                      f"control:{index}:1",f"control:{index}:2"}
            self.assertEqual({name for name,_,kind in c.handles() if kind=="control"},
                             expected)
            for control in (f"control:{index-1}:2",f"control:{index}:1"):
                p.select(control)
                self.assertEqual({name for name,_,kind in c.handles() if kind=="control"},expected)
                self.assertEqual(p.draft,before)
        # Choose the next manual point through its newly visible facing control.
        p.select(first)
        control="control:2:2"
        position=next(pos.toPoint() for name,pos,_ in c.handles() if name==control)
        QTest.mousePress(c,Qt.MouseButton.LeftButton,pos=position)
        QTest.mouseMove(c,position+QPoint(13,0))
        QTest.mouseRelease(c,Qt.MouseButton.LeftButton,pos=position+QPoint(13,0))
        self.assertEqual(p.selected,control)
        self.assertEqual(p.draft.points,before.points)
        self.assertTrue(p.draft.curves[2].curved)
        self.assertFalse(p.draft.curves[3].curved)
        self.assertEqual({name for name,_,kind in c.handles() if kind=="control"},
                         {"control:2:1","control:2:2","control:3:1","control:3:2"})

    def test_double_click_existing_point_shows_controls_without_inserting(self):
        p=self.panel;canvas=p.canvas
        p.insert(20);free=p.selected
        handle=next(pos for name,pos,_ in canvas.handles() if name==free).toPoint()
        count=len(p.draft.points)
        QTest.mouseDClick(canvas,Qt.MouseButton.LeftButton,pos=handle)
        self.assertEqual(len(p.draft.points),count)
        self.assertEqual(p.selected,free)
        self.assertEqual({name for name,_,kind in canvas.handles() if kind=="control"},
                         {"control:1:1","control:1:2","control:2:1","control:2:2"})

    def test_right_click_removes_free_points_and_preserves_required_grips(self):
        p=self.panel;canvas=p.canvas
        for view in ("side","front"):
            canvas.set_view(view);p.insert(20);free=p.selected
            p.select("base")
            handle=next(pos for name,pos,_ in canvas.handles() if name==free).toPoint()
            QTest.mouseClick(canvas,Qt.MouseButton.RightButton,pos=handle)
            self.assertNotIn(free,{point.identity for point in p.draft.points})
            for identity in ("foot","base","top","foot_height","top_width"):
                before=p.draft
                handle=next(pos for name,pos,_ in canvas.handles() if name==identity).toPoint()
                QTest.mouseClick(canvas,Qt.MouseButton.RightButton,pos=handle)
                self.assertEqual(p.draft,before)

    def test_height_grip_has_generous_object_top_snap_across_neighbor_layers(self):
        p=self.panel;canvas=p.canvas
        object_top=self.reference.context.layers[-1].z_mm
        for view in ("side","front"):
            canvas.set_view(view);canvas.zoom=1.6
            p.move("top",5,object_top)
            top=next(pos for name,pos,_ in canvas.handles() if name=="top")
            canvas.pan+=QPointF(0,canvas.height()/2-top.y())
            top=next(pos for name,pos,_ in canvas.handles() if name=="top").toPoint()
            target=top+QPoint(0,10)
            self.assertLess(canvas.screen_to_profile(QPointF(target))[1],object_top-.2)
            QTest.mousePress(canvas,Qt.MouseButton.LeftButton,pos=top)
            QTest.mouseMove(canvas,target)
            self.assertEqual(p.draft.height_mm,object_top)
            self.assertEqual(canvas._height_snap_z,object_top)
            QTest.mouseRelease(canvas,Qt.MouseButton.LeftButton,pos=target)

    def test_resolution_changes_only_original_view_and_has_nine_stages(self):
        p=self.panel;canvas=p.canvas
        self.assertEqual((p.resolution_slider.minimum(),p.resolution_slider.maximum(),p.resolution_slider.value()),(1,9,8))
        self.assertEqual(p.settings.object_resolution_percent,75)
        canvas.set_view("free");canvas.grab()
        self.assertTrue(canvas._spatial_render_frame().exact_silhouette)
        original=canvas._object_cache;tower=canvas._tower_cache;key=canvas._spatial_key()
        artifact=p.draft.artifact_payload();source=self.reference.object_triangles.copy()
        p.resolution_slider.setValue(9);canvas.grab()
        self.assertEqual(p.settings.object_resolution_percent,100)
        self.assertNotEqual(canvas._spatial_key(),key)
        self.assertIsNot(canvas._object_cache,original)
        self.assertIs(canvas._tower_cache,tower)
        self.assertEqual(p.draft.artifact_payload(),artifact)
        import numpy as np
        np.testing.assert_array_equal(self.reference.object_triangles,source)
        cache=canvas._object_cache
        with patch.object(canvas,"_render_object",wraps=canvas._render_object) as render:
            p.highlight_buttons["object"].click();canvas.grab()
            self.assertEqual(canvas.highlight,"object")
            self.assertTrue(p.highlight_buttons["object"].isChecked())
            self.assertFalse(p.highlight_buttons["tower"].isChecked())
            render.assert_not_called()
        self.assertIs(canvas._object_cache,cache)
        p.set_busy(True)
        self.assertFalse(p.resolution_slider.isEnabled())
        p.set_busy(False)
        self.assertTrue(p.resolution_slider.isEnabled())

    def test_color_edits_reuse_geometry_and_render_without_worker_or_proxy(self):
        from cooling_tower.gui.widgets import manual_canvas
        p=self.panel;c=p.canvas
        c.grab()
        material=c._object_cache.material
        rings=c._rings;placement=c._placement;artifact=p.draft.artifact_payload()
        with patch.object(manual_canvas,"tessellate",side_effect=AssertionError("tower rebuilt")), \
             patch.object(manual_canvas,"render_spatial_object",side_effect=AssertionError("object rebuilt")), \
             patch.object(c,"_queue_spatial_render",side_effect=AssertionError("worker queued")):
            p.checks["critical_layers_enabled"].setChecked(True)
            for kind,value in (("green",12),("red",3)):
                p.color_range_slider.request_value(kind,value);c.grab()
                self.assertIs(c._object_cache.material,material)
                self.assertFalse(c._render_proxy)
                self.assertFalse(c._render_timer.isActive())
        self.assertIs(c._rings,rings)
        self.assertIs(c._placement,placement)
        self.assertEqual(p.draft.artifact_payload(),artifact)

    def test_color_point_keyboard_updates_immediately(self):
        p=self.panel
        p.checks["critical_layers_enabled"].setChecked(True)
        handle=p.color_range_slider.green_handle
        handle.setFocus();QTest.keyClick(handle,Qt.Key.Key_Right)
        self.assertEqual(p.settings.color_reference_time_s,9.1)
        self.assertTrue(handle.hasFocus())

    def test_resolution_slider_uses_requested_percentages(self):
        for stage,percent in enumerate((0,1,5,10,15,25,50,75,100),1):
            self.panel.resolution_slider.setValue(stage)
            self.assertEqual(self.panel.settings.object_resolution_percent,percent)
            self.assertEqual(self.panel.resolution_label.text(),f"{percent} %")

    def test_resolution_default_is_75_in_all_views_and_resets_keep_custom_choices(self):
        p=self.panel
        for view in ("side","top","bottom","free","front","top","side"):
            with self.subTest(view=view):
                p.canvas.set_view(view)
                expected=75
                self.assertEqual(p.settings.object_resolution_percent,expected)
                self.assertEqual(p.default_value("object_resolution_percent"),expected)
                self.assertFalse(p.resolution_reset.isEnabled())
                self.assertFalse(p.can_reset_all())
                p.change_setting("object_resolution_percent",25)
                self.assertTrue(p.can_reset_all())
                p.resolution_reset.click()
                self.assertEqual(p.settings.object_resolution_percent,expected)
                p.change_setting("object_resolution_percent",50)
                p.reset_all()
                self.assertEqual(p.settings.object_resolution_percent,expected)
                self.assertFalse(p.can_reset_all())
        p.change_setting("object_resolution_percent",50)
        for view in ("top","free","front"):
            p.canvas.set_view(view)
            self.assertEqual(p.settings.object_resolution_percent,50)
            self.assertTrue(p.resolution_reset.isEnabled())
        p.initialize(self.reference,replace(p.settings,object_resolution_percent=25))
        self.assertEqual(p.settings.object_resolution_percent,25)

    def test_zero_uses_exact_fast_silhouette_without_mesh_proxy_or_artifact_changes(self):
        import trimesh
        from cooling_tower.preview.mesh_silhouette import build_mesh_silhouette
        p=self.panel;c=p.canvas
        triangles=trimesh.creation.icosphere(subdivisions=5).triangles.copy()
        triangles.setflags(write=False)
        reference=replace(self.reference,object_triangles=triangles,object_silhouette=build_mesh_silhouette(triangles))
        p.initialize(reference)
        before=p.draft.artifact_payload()
        c.set_view("free")
        c._render_manager=Mock()
        try:
            with patch.object(c,"_queue_spatial_render",side_effect=AssertionError("unnecessary delayed proxy")):
                p.resolution_slider.setValue(1);c.grab()
            self.assertEqual(p.settings.object_resolution_percent,0)
            self.assertEqual(p.draft.artifact_payload(),before)
            self.assertFalse(c._render_proxy)
            picture=c._object_cache
            c.pan+=QPointF(12,10);c.zoom*=1.2;c.grab()
            self.assertIs(c._object_cache,picture)
        finally:c._render_manager=None

    def test_limit_grips_use_diameter_scale_and_drag_in_tenth_millimetres(self):
        p=self.panel;c=p.canvas
        p.change_setting("maximum_diameter_mm",50)
        p.change_setting("maximum_foot_diameter_mm",50)
        artifact=p.draft.artifact_payload()
        maxima=["maximum_diameter_mm","maximum_foot_diameter_mm"]
        for view,names in (("side",maxima),("front",maxima),
                           ("top",["maximum_diameter_mm"]),("bottom",["maximum_foot_diameter_mm"])):
            c.set_view(view)
            for name in names:
                p.change_setting(name,50)
                c.fit_scene()
                handle=next(pos for identity,pos,_ in c.handles() if identity==name)
                edge,limit=c.limit_geometry(name)
                self.assertEqual(handle,limit)
                if view in {"side","front"}:
                    self.assertAlmostEqual(c.screen_to_profile(handle)[0],25)
                else:
                    z=p.draft.height_mm if view=="top" else p.draft.points[0].position.z_mm
                    center=c._placement.center_x_mm,c._placement.center_y_mm
                    import numpy as np
                    axis,_=c._project_world(np.array([(center[0],center[1],z)]))
                    self.assertAlmostEqual(handle.x()-axis[0,0],25*c.transform()[0])
                self.assertAlmostEqual(edge.y(),limit.y())
                self.assertEqual(c.hit_test(handle),name)
                position=handle.toPoint()
                QTest.mousePress(c,Qt.MouseButton.LeftButton,pos=position)
                QTest.mouseMove(c,position+QPoint(13,-18))
                value=getattr(p.settings,name)
                self.assertAlmostEqual(value*10,round(value*10))
                self.assertGreater(value,50)
                self.assertIn(f"Ø {value:.2f} mm".replace(".",","),c.selected_handle_text())
                QTest.mouseRelease(c,Qt.MouseButton.LeftButton,pos=position+QPoint(13,-18))
                self.assertEqual(p.draft.artifact_payload(),artifact)
                self.assertEqual(preview_row(p,name).field.value,value)

    def test_minimum_measure_is_symmetric_and_drags_the_limit_in_tenths(self):
        p=self.panel;c=p.canvas
        p.move("base",20,8)
        original=p.draft.artifact_payload()
        for view in ("side","front"):
            c.set_view(view)
            left,right,left_end,right_end=c.minimum_measure_geometry()
            axis=c.profile_to_screen(0,0)
            self.assertAlmostEqual(axis.x()-left.x(),right.x()-axis.x())
            self.assertAlmostEqual(right.x()-left.x(),p.settings.minimum_diameter_mm*c.transform()[0])
            self.assertEqual((left.x(),right.x()),(left_end.x(),right_end.x()))
            self.assertEqual(left_end.y(),right_end.y())
            self.assertGreater(right_end.y(),axis.y())
            self.assertLess(right_end.y()+23,c.height())
            self.assertEqual(c.hit_test(right_end),"minimum_diameter_mm")
            target=right_end.toPoint()+QPoint(12,-10)
            QTest.mousePress(c,Qt.MouseButton.LeftButton,pos=right_end.toPoint())
            QTest.mouseMove(c,target)
            QTest.mouseRelease(c,Qt.MouseButton.LeftButton,pos=target)
            value=p.settings.minimum_diameter_mm
            self.assertGreater(value,5)
            self.assertAlmostEqual(value*10,round(value*10))
            self.assertEqual(preview_row(p,"minimum_diameter_mm").field.value,value)
            self.assertIn(f"Minimum: Ø {value:.2f} mm".replace(".",","),c.selected_handle_text())
            self.assertEqual(p.draft.artifact_payload(),original)
            left,right,left_end,right_end=c.minimum_measure_geometry()
            self.assertAlmostEqual(right.x()-left.x(),value*c.transform()[0])
            self.assertAlmostEqual(c.profile_to_screen(0,0).x()-left.x(),right.x()-c.profile_to_screen(0,0).x())
        p.move_limit("minimum_diameter_mm",100)
        self.assertEqual(p.settings.minimum_diameter_mm,p.settings.maximum_diameter_mm)
        self.assertEqual(p.draft.base_diameter_mm,p.settings.maximum_diameter_mm)
        self.assertNotEqual(p.draft.artifact_payload(),original)
        for view in ("top","bottom","free"):
            c.set_view(view)
            self.assertNotIn("minimum_diameter_mm",[name for name,_,_ in c.handles()])

    def test_minimum_drag_restores_original_positions_until_release_then_keeps_them(self):
        p=self.panel;c=p.canvas
        p.insert(20);p.move(p.selected,12,20)
        p.select("minimum_diameter_mm")
        original=p.draft
        scale=c.transform()[0]
        handle=c.minimum_measure_geometry()[-1].toPoint()
        def target(value):return handle+QPoint(round((value-original.settings.minimum_diameter_mm)*scale/2),0)
        QTest.mousePress(c,Qt.MouseButton.LeftButton,pos=handle)
        QTest.mouseMove(c,target(20))
        high=p.settings.minimum_diameter_mm
        self.assertGreater(high,19)
        self.assertTrue(all(point.position.diameter_mm>=high for point in p.draft.points))
        QTest.mouseMove(c,target(9))
        low=p.settings.minimum_diameter_mm
        self.assertLess(low,10)
        self.assertEqual(p.draft.points[2].position,original.points[2].position)
        self.assertEqual(p.draft.base_diameter_mm,low)
        QTest.mouseMove(c,handle)
        self.assertEqual(p.draft,original)
        QTest.mouseMove(c,target(20))
        QTest.mouseRelease(c,Qt.MouseButton.LeftButton,pos=target(20))
        committed=p.draft.artifact_payload()
        p.change_setting("minimum_diameter_mm",5)
        self.assertEqual(p.draft.artifact_payload(),committed)
        QTest.mousePress(c,Qt.MouseButton.LeftButton,pos=c.minimum_measure_geometry()[-1].toPoint())
        p.move_limit("minimum_diameter_mm",1)
        self.assertEqual(p.draft.artifact_payload(),committed)
        QTest.mouseRelease(c,Qt.MouseButton.LeftButton,pos=c.minimum_measure_geometry()[-1].toPoint())

    def test_minimum_numeric_edit_moves_form_immediately_and_base_cannot_move_minimum(self):
        p=self.panel
        p.move("foot",25,p.draft.first_layer_z_mm)
        enter_preview_value(p,"minimum_diameter_mm",30)
        self.assertEqual(p.draft.base_diameter_mm,30)
        self.assertEqual(p.draft.foot_diameter_mm,30)
        self.assertTrue(all(point.position.diameter_mm>=30 for point in p.draft.points))
        p.move("base",1,8)
        self.assertEqual(p.draft.base_diameter_mm,30)
        self.assertEqual(p.settings.minimum_diameter_mm,30)
        p.move_limit("minimum_diameter_mm",-10)
        self.assertEqual(p.settings.minimum_diameter_mm,1)
        enter_preview_value(p,"minimum_diameter_mm",.5)
        self.assertEqual(p.settings.minimum_diameter_mm,1)

    def test_minimum_drag_respects_each_maximum_without_expanding_it(self):
        p=self.panel
        for tower,foot in ((20,30),(40,30)):
            p.reset_all()
            p.move("foot",25,p.draft.first_layer_z_mm)
            p.change_setting("maximum_diameter_mm",tower)
            p.change_setting("maximum_foot_diameter_mm",foot)
            p.move_limit("minimum_diameter_mm",100)
            self.assertEqual(p.settings.minimum_diameter_mm,min(tower,foot))
            self.assertEqual((p.settings.maximum_diameter_mm,p.settings.maximum_foot_diameter_mm),(tower,foot))

    def test_minimum_measure_dashed_lines_fade_from_baseline_gray_to_light_gray(self):
        c=self.panel.canvas
        pen=c._minimum_measure_pen()
        self.assertEqual(pen.style(),Qt.PenStyle.DashLine)
        self.assertEqual(pen.widthF(),1)
        gradient=pen.brush().gradient()
        left,_,end,_=c.minimum_measure_geometry()
        self.assertEqual(gradient.start(),left)
        self.assertEqual(gradient.finalStop(),end)
        self.assertEqual(gradient.stops(),[(0.,QColor("#a3b1c0").darker(150)),(1.,QColor("#bec5ce"))])
        rectangle=c.minimum_measure_label_rect()
        self.assertGreaterEqual(rectangle.width(),c.fontMetrics().horizontalAdvance("Min. Turm-Ø")+8)
        self.assertLess(rectangle.bottom(),c.height())
        self.assertAlmostEqual(rectangle.center().x(),c.profile_to_screen(0,0).x())

    def test_straight_limit_guides_fade_from_tower_to_grip_in_each_view(self):
        c=self.panel.canvas
        for view in ("side","front","top","bottom"):
            c.set_view(view)
            c.grab()
            with patch("cooling_tower.gui.widgets.manual_canvas.QPainter") as painter:
                painter.return_value.font.return_value=QFont(c.font())
                painter.return_value.fontMetrics.return_value=c.fontMetrics()
                c.paintEvent(None)
            gradients=[call.args[0].brush().gradient() for call in painter.return_value.setPen.call_args_list
                       if hasattr(call.args[0],"brush") and call.args[0].brush().gradient() is not None]
            for identity,end,kind in c.limit_handles():
                if identity == "minimum_diameter_mm":continue
                start,_=c.limit_geometry(identity)
                gradient=next(g for g in gradients if g.start() == start and g.finalStop() == end)
                self.assertEqual(gradient.start(),start)
                self.assertEqual(gradient.finalStop(),end)
                self.assertEqual(gradient.stops(),[(0.,QColor("#a3b1c0").darker(150)),(1.,QColor("#bec5ce"))])

    def test_free_navigation_matches_automatic_drag_and_zoom_steps(self):
        from cooling_tower.gui.widgets.preview_canvas import PreviewCanvas
        c=self.panel.canvas;c.set_view("free")
        auto=PreviewCanvas();self.addCleanup(auto.close)
        auto.resize(c.size());auto.show();auto.set_navigation_enabled(True)
        self.app.processEvents()
        c.yaw_deg=auto.yaw_deg=-35
        c.pitch_deg=auto.pitch_deg=25
        c.pan=QPointF();auto.pan_x=auto.pan_y=0
        before=self.panel.draft
        def scroll(widget,delta):
            # The automatic preview now anchors zoom at the cursor; compare
            # shared gestures about its panned scene centre. The manual free
            # view keeps its centre zoom even with an off-centre cursor.
            anchor=(QPointF(auto.width()/2+auto.pan_x,auto.height()/2+auto.pan_y)
                    if widget is auto else QPointF(25,30))
            event=QWheelEvent(anchor,QPointF(widget.mapToGlobal(anchor.toPoint())),QPoint(),
                              QPoint(0,delta),Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,
                              Qt.ScrollPhase.NoScrollPhase,False)
            widget.wheelEvent(event)
        origin=QPoint(130,150)
        destination=origin+QPoint(80,60)
        for button in (Qt.MouseButton.LeftButton,Qt.MouseButton.RightButton,Qt.MouseButton.MiddleButton):
            for widget in (c,auto):
                QTest.mousePress(widget,button,pos=origin)
                scroll(widget,120)
                QTest.mouseMove(widget,destination)
                QTest.mouseRelease(widget,button,pos=destination)
            self.assertEqual(c.yaw_deg,auto.yaw_deg)
            self.assertEqual(c.pitch_deg,auto.pitch_deg)
            self.assertEqual((c.pan.x(),c.pan.y()),(auto.pan_x,auto.pan_y))
            self.assertEqual(c.zoom,auto.zoom)
        for zoom,delta in ((1,120),(1,-120),(49,120),(.051,-120)):
            c.zoom=auto.zoom=zoom
            for widget in (c,auto):
                scroll(widget,delta)
            self.assertEqual(c.zoom,auto.zoom)
            self.assertEqual((c.pan.x(),c.pan.y()),(auto.pan_x,auto.pan_y))
        self.assertEqual(self.panel.draft,before)

    def test_settings_rail_animates_without_changing_form_and_survives_reversal_and_resize(self):
        p=self.panel;rail=p.settings_collapse_button
        p.move("base",10,8);before=p.draft
        width=p.settings_pane.width();preview_width=p.preview_container.width()
        self.assertEqual(rail.height(),p.settings_scroll.height())
        self.assertEqual(rail.x(),p.settings_scroll.width())
        self.assertEqual(rail.arrowType(),Qt.ArrowType.LeftArrow)
        self.assertEqual(p._settings_animation.duration(),250)
        rail.click();QTest.qWait(90)
        self.assertTrue(p._settings_transitioning)
        self.assertLess(p.settings_pane.width(),width)
        self.assertGreater(p.settings_pane.width(),p.settings_pane.RAIL_WIDTH)
        QTest.qWait(220)
        self.assertTrue(p.settings_collapsed)
        self.assertEqual(p.settings_pane.width(),p.settings_pane.RAIL_WIDTH)
        self.assertTrue(p.settings_scroll.isHidden())
        self.assertEqual(rail.x(),0)
        self.assertEqual(rail.height(),p.splitter.height())
        self.assertEqual(rail.arrowType(),Qt.ArrowType.RightArrow)
        self.assertGreater(p.preview_container.width(),preview_width)
        p.resize(800,1050);self.app.processEvents()
        self.assertEqual(p.splitter.orientation(),Qt.Orientation.Horizontal)
        rail.click();QTest.qWait(310)
        self.assertFalse(p.settings_collapsed)
        self.assertEqual(p.splitter.orientation(),Qt.Orientation.Vertical)
        self.assertTrue(p.settings_scroll.isVisible())
        self.assertEqual(p.draft,before)
        bar=p.settings_scroll.verticalScrollBar();bar.setValue(bar.maximum())
        scroll_position=bar.value()
        rail.click();QTest.qWait(310);rail.click();QTest.qWait(310)
        self.assertEqual(bar.value(),scroll_position)
        rail.click();QTest.qWait(70);rail.click();QTest.qWait(310)
        self.assertFalse(p.settings_collapsed)
        self.assertFalse(p._settings_transitioning)
        self.assertTrue(p.settings_scroll.isVisible())
        self.assertEqual(p.draft,before)

    def test_original_bitmap_matches_direct_picture_pixels_and_reuses_only_valid_frames(self):
        import math
        p=self.panel;c=p.canvas
        p.change_setting("object_resolution_percent",100)
        for view in ("side","front","top","bottom","free"):
            c.set_view(view);c.grab()
            for highlight in ("both","object"):
                c.set_highlight(highlight)
                for ratio in (1.,2.):
                    with patch.object(c,"devicePixelRatioF",return_value=ratio):
                        cached=c._original_image()
                        direct=QImage(math.ceil(c.width()*ratio),math.ceil(c.height()*ratio),
                                      QImage.Format.Format_ARGB32_Premultiplied)
                        direct.setDevicePixelRatio(ratio);direct.fill(QColor("#e6ecf2"))
                        painter=QPainter(direct)
                        c._draw_spatial_picture(painter,c._object_cache,.28 if highlight=="object" else 1)
                        painter.end()
                        self.assertEqual(cached,direct)
                        self.assertIs(c._original_image(),cached)
        c.set_view("side");c.set_highlight("both");c.grab()
        picture=c._object_cache;bitmap=c._object_image_cache
        p.move("base",10,8);p.select("foot");c.grab()
        self.assertIs(c._object_cache,picture)
        self.assertIs(c._object_image_cache,bitmap)
        c.set_highlight("tower");c.grab()
        self.assertIs(c._object_image_cache,bitmap)
        for change in (lambda:setattr(c,"pan",QPointF(10,12)),
                       lambda:setattr(c,"zoom",1.5),lambda:c.resize(c.width()+20,c.height()),
                       lambda:c.set_highlight("object"),c.fit_scene):
            before=c._object_image_cache
            change();c.grab()
            self.assertIsNot(c._object_image_cache,before)
            self.assertIs(c._object_cache,picture)
        before=c._object_image_cache
        c.set_rotation(45);c.grab()
        self.assertIsNot(c._object_cache,picture)
        self.assertIsNot(c._object_image_cache,before)

    def test_fitted_tall_profile_uses_height_above_the_minimum_measure(self):
        p=self.panel;c=p.canvas
        _,_,reference,_,_=create_fixture(self,joint=True,count=600)
        p.initialize(reference)
        self.assertEqual(p.draft.height_mm,120)
        for view in ("side","front"):
            c.set_view(view)
            rectangle=c.plot_rect()
            top=c.profile_to_screen(0,120)
            bottom=c.profile_to_screen(0,0)
            self.assertGreaterEqual(top.y(),rectangle.top())
            self.assertTrue(abs(top.y()-rectangle.top())<1e-7 or
                            abs(c.transform()[0]*c._fit_width+c._profile_gap_px-rectangle.width())<1e-7)
            self.assertAlmostEqual(bottom.y(),rectangle.bottom())
            self.assertGreaterEqual(top.y(),c.view_controls.geometry().bottom()+19)
            self.assertEqual(c.height()-bottom.y(),52)
            self.assertLess(c.minimum_measure_geometry()[-1].y()+23,c.height())

    def test_initial_fit_of_short_profile_uses_height_and_centers_actual_bounds(self):
        from cooling_tower.models.calibration import OccupiedBounds
        p=self.panel;c=p.canvas
        _,_,reference,_,_=create_fixture(self,joint=True,count=490)
        triangles=reference.object_triangles.copy()
        triangles[:,:,:2]=5+(triangles[:,:,:2]-5)*4
        reference=replace(reference,object_triangles=triangles,
                          context=replace(reference.context,occupied_bounds=OccupiedBounds(105,145,105,145)))
        # Replacing a previously fitted reference must also fit the new draft.
        c.zoom=2;c.pan=QPointF(60,-40)
        p.initialize(reference);c.resize(976,790)
        self.assertEqual(c.zoom,1);self.assertEqual(c.pan,QPointF())
        self.assertEqual(c.view,"side")
        for view in ("side","front"):
            for rotation in (0,37,90):
                with self.subTest(view=view,rotation=rotation):
                    if view!="side" or rotation:c.set_view(view);c.set_rotation(rotation);c.fit_scene()
                    rect=c.plot_rect();scale=c.transform()[0]
                    from cooling_tower.gui.manual_view_worker import rotate_object
                    points=rotate_object(triangles.reshape(-1,3),reference.silhouette.center_xy,
                                         c._object_center,c.object_rotation)
                    projected,_=c._spatial_frame().project(points)
                    left=min(c.profile_to_screen(-p.draft.maximum_radius_mm,0).x(),projected[:,0].min())
                    right=max(*(position.x() for _,position,_ in c.limit_handles()),projected[:,0].max())
                    self.assertGreaterEqual(left,rect.left()-1e-7)
                    self.assertLessEqual(right,rect.right()+1e-7)
                    self.assertAlmostEqual((left+right)/2,rect.center().x())
                    if view=="front" or rotation in (0,90):
                        self.assertAlmostEqual(c.profile_to_screen(0,98).y(),rect.top())
                    else:
                        # A rotated square genuinely needs more horizontal room.
                        self.assertAlmostEqual(left,rect.left())
                        self.assertAlmostEqual(right,rect.right())
                    self.assertGreaterEqual(projected[:,1].min(),rect.top()-1e-7)
                    self.assertLessEqual(projected[:,1].max(),rect.bottom()+1e-7)
                    if view=="side":
                        self.assertAlmostEqual(projected[:,0].min()-max(point.x() for _,point,_ in c.handles()),15)
                    self.assertGreater(scale,0)

    def test_wide_original_limits_profile_fit_by_width_at_common_scale(self):
        from cooling_tower.models.calibration import BedBounds,BedGeometry,OccupiedBounds
        from cooling_tower.gui.manual_view_worker import rotate_object
        p=self.panel;c=p.canvas
        triangles=self.reference.object_triangles.copy()
        triangles[:,:,0]=5+(triangles[:,:,0]-5)*30
        bed=BedGeometry(BedBounds(0,1000,0,1000),((0,0),(1000,0),(1000,1000),(0,1000)))
        context=replace(self.reference.context,key="wide-original",bed_geometry=bed,
                        occupied_bounds=OccupiedBounds(350,650,495,505))
        reference=replace(self.reference,context=context,object_triangles=triangles)
        p.initialize(reference);c.resize(976,790)
        for view in ("side","front"):
            c.set_view(view);rect=c.plot_rect();scale=c.transform()[0]
            self.assertGreater(c.profile_to_screen(0,p.draft.height_mm).y(),rect.top()+50)
            self.assertAlmostEqual(scale*c._fit_width+c._profile_gap_px,rect.width())
            points=rotate_object(triangles.reshape(-1,3),reference.silhouette.center_xy,c._object_center,0)
            projected,_=c._spatial_frame().project(points)
            self.assertAlmostEqual(projected[:,1].max()-projected[:,1].min(),p.draft.height_mm*scale)
            self.assertGreaterEqual(projected[:,0].min(),rect.left()-1e-7)
            self.assertLessEqual(projected[:,0].max(),rect.right()+1e-7)

    def test_profile_fit_keeps_protruding_height_grips_visible_after_resize_and_zoom(self):
        from cooling_tower.gui.manual_view_worker import rotate_object
        p=self.panel;c=p.canvas
        p.change_setting("maximum_diameter_mm",25)
        p.change_setting("maximum_foot_diameter_mm",25)
        p.move("base",24,8)
        for view in ("side","front"):
            c.set_view(view)
            for width in (350,650,976):
                with self.subTest(view=view,width=width):
                    c.resize(width,790)
                    rectangle=c.plot_rect()
                    rightmost=max(point.x() for identity,point,_ in c.handles()
                                  if identity!="minimum_diameter_mm")
                    self.assertLessEqual(rightmost,rectangle.right()+1e-7)
                    if view=="side":
                        points=rotate_object(self.reference.object_triangles.reshape(-1,3),
                                             self.reference.silhouette.center_xy,c._object_center,0)
                        projected,_=c._spatial_frame().project(points)
                        self.assertAlmostEqual(projected[:,0].min()-rightmost,15)
                        self.assertLessEqual(projected[:,0].max(),rectangle.right()+1e-7)
                        gap=projected[:,0].min()-c.profile_to_screen(c._fitting_radius(),0).x()
                        c.zoom=2
                        projected,_=c._spatial_frame().project(points)
                        self.assertAlmostEqual(projected[:,0].min()-c.profile_to_screen(c._fitting_radius(),0).x(),2*gap)
                        c.zoom=1

    def test_scale_values_do_not_overlap_units_when_the_fitted_object_reaches_the_top(self):
        p=self.panel;c=p.canvas
        _,_,reference,_,_=create_fixture(self,joint=True,count=600)
        p.initialize(reference);c.fit_scene()
        image=QImage(c.width(),c.height(),QImage.Format.Format_ARGB32_Premultiplied)
        painter=QPainter(image)
        try:
            with patch.object(QPainter,"drawText") as draw:
                c._draw_scales(painter)
            labels=[(call.args[0],call.args[-1]) for call in draw.call_args_list]
            units=[rectangle for rectangle,text in labels if text in {"mm","Layer"}]
            values=[rectangle for rectangle,text in labels if text not in {"mm","Layer"}]
            self.assertTrue(values)
            self.assertFalse(any(unit.intersects(value) for unit in units for value in values))
            layer_rectangle=next(rectangle for rectangle,text in labels if text=="Layer")
            self.assertLess(layer_rectangle.right(),c.width()-43)
            self.assertTrue(all(rectangle.left()>c.width()-43 for rectangle,text in labels if text.isdigit()
                                and rectangle.left()>c.width()/2))
        finally:painter.end()

    def test_spatial_fit_contains_actual_segments_and_rotated_original_without_world_padding(self):
        import math
        import numpy as np
        from cooling_tower.gui.manual_view_worker import rotate_object
        p=self.panel;c=p.canvas
        _,_,reference,_,_=create_fixture(self,joint=True,count=600)
        p.initialize(reference)
        for view in ("top","bottom","free"):
            for rotation in (0,37,90):
                c.set_view(view);c.set_rotation(rotation);c.fit_scene()
                center=c._placement.center_x_mm,c._placement.center_y_mm
                count=p.settings.circle_segments
                tower=np.array([(center[0]+point.radius_mm*math.cos(math.tau*i/count),
                                 center[1]+point.radius_mm*math.sin(math.tau*i/count),point.z_mm)
                                for point in c._rings for i in range(count)])
                if view in {"top","bottom"}:
                    z=p.draft.points[-1 if view=="top" else 0].position.z_mm
                    radius=getattr(p.settings,"maximum_diameter_mm" if view=="top" else "maximum_foot_diameter_mm")/2
                    tower=np.concatenate((tower,[(center[0]+radius,center[1],z)]))
                source=rotate_object(reference.object_triangles.reshape(-1,3),reference.silhouette.center_xy,
                                     c._object_center,rotation)
                screen,_=c._project_world(np.concatenate((tower,source)))
                rectangle=c.plot_rect()
                low,high=screen.min(axis=0),screen.max(axis=0)
                self.assertGreaterEqual(low[0],rectangle.left()-1e-7)
                self.assertGreaterEqual(low[1],rectangle.top()-1e-7)
                self.assertLessEqual(high[0],rectangle.right()+1e-7)
                self.assertLessEqual(high[1],rectangle.bottom()+1e-7)
                self.assertTrue(abs(high[0]-low[0]-rectangle.width())<1e-7 or
                                abs(high[1]-low[1]-rectangle.height())<1e-7)

    def test_limit_grips_stop_at_profile_bounds_and_do_not_edit_when_busy(self):
        p=self.panel
        p.move("foot",25,p.draft.first_layer_z_mm)
        p.move("base",10.03,8)
        artifact=p.draft.artifact_payload()
        p.move_limit("maximum_diameter_mm",.1)
        self.assertEqual(p.settings.maximum_diameter_mm,10.1)
        p.move_limit("maximum_foot_diameter_mm",.1)
        self.assertEqual(p.settings.maximum_foot_diameter_mm,25)
        self.assertEqual(p.draft.artifact_payload(),artifact)
        p.move_limit("maximum_foot_diameter_mm",1200)
        self.assertEqual(p.settings.maximum_foot_diameter_mm,p.reference.context.maximum_foot_diameter_mm)
        p.set_busy(True);before=p.draft
        p.move_limit("maximum_diameter_mm",50)
        self.assertEqual(p.draft,before)
        self.assertFalse(p.canvas.handles())

    def test_limit_grip_click_and_vertical_motion_preserve_typed_precision(self):
        p=self.panel;c=p.canvas
        p.change_setting("maximum_diameter_mm",50.03)
        p.select("maximum_diameter_mm")
        before=p.draft
        position=next(pos.toPoint() for name,pos,_ in c.handles() if name==p.selected)
        QTest.mouseClick(c,Qt.MouseButton.LeftButton,pos=position)
        self.assertEqual(p.draft,before)
        QTest.mousePress(c,Qt.MouseButton.LeftButton,pos=position)
        QTest.mouseMove(c,position+QPoint(0,18))
        QTest.mouseRelease(c,Qt.MouseButton.LeftButton,pos=position+QPoint(0,18))
        self.assertEqual(p.draft,before)
        self.assertIn("50,03 mm",c.selected_handle_text())

    def test_spatial_tower_uses_all_segments_and_updates_without_object_resolution(self):
        p=self.panel;c=p.canvas
        p.change_setting("circle_segments",120)
        c.set_view("free")
        c._tower_render_key=None
        from cooling_tower.gui.widgets import manual_canvas
        with patch.object(manual_canvas,"draw_surface",wraps=manual_canvas.draw_surface) as surface:
            c.grab()
            self.assertEqual(surface.call_count,120*(len(c._display_rings())-1))
        tower=c._tower_cache
        p.change_setting("object_resolution_percent",5);c.grab()
        self.assertIs(c._tower_cache,tower)
        p.change_setting("object_resolution_percent",100);c.grab()
        self.assertIs(c._tower_cache,tower)
        p.move("top_width",6,p.draft.height_mm);c.grab()
        self.assertIsNot(c._tower_cache,tower)
        for view in ("side","front"):
            c.set_view(view)
            with patch.object(c,"_tower_picture",wraps=c._tower_picture) as spatial:
                c.grab()
                spatial.assert_not_called()

    def test_legend_uses_two_columns_of_four_when_space_allows(self):
        from cooling_tower.gui.widgets.manual_preview_info import ManualPreviewInformation
        info=ManualPreviewInformation()
        self.addCleanup(info.close)
        info.set_state("side",False)
        widths=[label.fontMetrics().horizontalAdvance(label.text())+row.layout().spacing()+row.layout().itemAt(0).widget().width()
                for row,label in zip(info.legend_rows,info.legend_labels)]
        needed=max(widths[:4])+max(widths[4:])+info.legend_grid.horizontalSpacing()
        info.resize(needed*2+89,300);info.show();self.app.processEvents()
        info.heightForWidth(info.width())
        self.assertEqual(info.legend_columns,2)
        self.assertEqual(len(info.legend_rows),8)
        for i,row in enumerate(info.legend_rows):
            index=info.legend_grid.indexOf(row)
            expected = (i%4,i//4)
            self.assertEqual(info.legend_grid.getItemPosition(index)[:2],expected)
        info.resize(max(100,needed*2-60),300);self.app.processEvents()
        info.heightForWidth(info.width())
        self.assertEqual(info.legend_columns,1)
        self.assertTrue(all(line.startswith("• ") for line in info.instructions.text().splitlines()))

    def test_wrapped_legend_entries_keep_text_and_swatch_on_the_same_top_line(self):
        from cooling_tower.gui.widgets.manual_preview_info import ManualPreviewInformation
        info=ManualPreviewInformation()
        self.addCleanup(info.close)
        widths=[label.fontMetrics().horizontalAdvance(label.text())+row.layout().spacing()+row.layout().itemAt(0).widget().width()
                for row,label in zip(info.legend_rows,info.legend_labels)]
        needed=max(widths[:4])+max(widths[4:])+info.legend_grid.horizontalSpacing()
        for width in (needed*2+29,needed*2+41):
            info.resize(width,300);info.show();self.app.processEvents()
            info.heightForWidth(info.width());self.app.processEvents()
            self.assertEqual(info.legend_columns,2)
            base,profile=info.legend_labels[3],info.legend_labels[7]
            self.assertGreater(base.heightForWidth(base.width()),base.fontMetrics().height())
            self.assertEqual(base.mapTo(info,QPoint()).y(),profile.mapTo(info,QPoint()).y())
            self.assertEqual(profile.mapTo(info,QPoint()).y(),info.swatches["profile"].mapTo(info,QPoint()).y())

    def test_preview_help_uses_requested_wording_without_periods_and_zoom_last(self):
        info=self.panel.preview_information
        for view in ("side","front","top","bottom","free"):
            info.set_state(view,False)
            lines=info.instructions.text().splitlines()
            if view in {"side","front"}:
                self.assertIn("• Shift + Ziehen: Punkt nur waagerecht/senkrecht verschieben",lines)
                lines=[line for line in lines if "Shift + Ziehen" not in line]
            self.assertEqual(lines[-2:],["• Mittlere Maustaste + Ziehen: Ansicht verschieben","• Mausrad: Zoom"])
            if view == "free":self.assertEqual(lines[0],"• Linke Maustaste: Ansicht drehen")
            self.assertTrue(all(not line.endswith(".") for line in lines))
            if view in {"side","front"}:
                self.assertEqual(lines[:4],["• Punkt/Ankerpunkt ziehen: Turmform ändern",
                    "• Doppelklick auf Turmprofil: Punkt hinzufügen",
                    "• Doppelklick auf Punkt: Bézierkurven zurücksetzen",
                    "• Rechtsklick auf manuellen Punkt: Punkt entfernen"])

    def test_preview_toolbar_rotation_and_two_columns_remain_in_order(self):
        p=self.panel
        p.canvas.set_view("free")
        for width,height in ((1400,1000),(720,1300),(1100,1000)):
            p.resize(width,height)
            for _ in range(4):self.app.processEvents()
            position=lambda widget:widget.mapTo(p.preview_container,QPoint())
            self.assertEqual(p.highlight_host.height(),p.resolution_host.height())
            self.assertEqual(p.highlight_host.height(),p.rotation_host.height())
            for title in (p.highlight_title,p.resolution_title,p.rotation_title):
                self.assertEqual(title.alignment(),Qt.AlignmentFlag.AlignCenter)
                self.assertEqual(position(title).y(),position(p.highlight_title).y())
            self.assertLess(position(p.highlight_host).x()+p.highlight_host.width(),position(p.resolution_host).x())
            self.assertLess(position(p.resolution_host).x()+p.resolution_host.width(),position(p.rotation_host).x())
            option=QStyleOptionSlider();p.rotation_slider.initStyleOption(option)
            style=p.rotation_slider.style()
            handle=style.subControlRect(QStyle.ComplexControl.CC_Slider,option,QStyle.SubControl.SC_SliderHandle,p.rotation_slider)
            p.resolution_slider.initStyleOption(option)
            resolution_handle=p.resolution_slider.style().subControlRect(
                QStyle.ComplexControl.CC_Slider,option,QStyle.SubControl.SC_SliderHandle,p.resolution_slider)
            self.assertEqual(handle.size(),resolution_handle.size())
            self.assertEqual(p.rotation_slider.mapTo(p.preview_container,QPoint(0,p.rotation_slider.tick_mark_top())).y(),
                             p.resolution_slider.mapTo(p.preview_container,QPoint(0,p.resolution_slider.tick_mark_top())).y())
            self.assertTrue(p.rotation_slider.rect().contains(handle))
            self.assertTrue(p.rotation_label.alignment() & Qt.AlignmentFlag.AlignLeft)
            for slider,label in ((p.resolution_slider,p.resolution_label),(p.rotation_slider,p.rotation_label)):
                self.assertEqual(position(label).x()-(position(slider).x()+slider.width()),3)
                slider.initStyleOption(option)
                grip=slider.style().subControlRect(QStyle.ComplexControl.CC_Slider,option,QStyle.SubControl.SC_SliderHandle,slider)
                self.assertLessEqual(abs(label.mapTo(p.preview_container,label.contentsRect().center()).y()-
                                         slider.mapTo(p.preview_container,grip.center()).y()),1)
            title_center=position(p.rotation_title).x()+p.rotation_title.width()//2
            slider_center=position(p.rotation_slider).x()+p.rotation_slider.width()//2
            self.assertLessEqual(abs(title_center-slider_center),1)
            self.assertEqual([label.text() for label in (p.rotation_end_labels.left,p.rotation_end_labels.middle,p.rotation_end_labels.right)],
                             ["-180°","0°","180°"])
            self.assertEqual(p.rotation_end_labels.left.styleSheet(),p.resolution_end_labels.faster.styleSheet())
            self.assertEqual(position(p.rotation_label).y(),position(p.resolution_label).y())
            self.assertEqual(position(p.rotation_label).y(),position(p.rotation_slider).y())
            self.assertEqual(p.rotation_label.height(),p.resolution_label.height())
            self.assertIs(p.fit_button.parentWidget(),p.canvas.view_controls)
            self.assertLessEqual(p.canvas.view_controls.geometry().right(),p.canvas.width()-8)
            self.assertLess(position(p.rotation_slider).y()+p.rotation_slider.height(),position(p.canvas).y())
            self.assertLess(position(p.canvas).y()+p.canvas.height(),position(p.preview_information).y())
            self.assertLess(p.preview_information.legend.geometry().right(),p.preview_information.controls.x())
            self.assertLess(p.preview_information.legend.geometry().right(),p.preview_information.separator.x())
            self.assertLess(p.preview_information.separator.x(),p.preview_information.controls.x())
            self.assertEqual(p.preview_information.instructions.x(),p.preview_information.controls_title.x())
        p.change_setting("critical_layers_enabled",True)
        swatch=p.preview_information.swatches["object"]
        self.assertTrue(swatch.split)
        image=swatch.grab().toImage()
        self.assertEqual(image.pixelColor(1,1).name(),"#e5484d")
        self.assertEqual(image.pixelColor(image.width()-2,image.height()-2).name(),"#41a878")
        p.change_setting("critical_layers_enabled",False)
        self.assertFalse(swatch.split)

    def test_scale_number_anchors_have_mirrored_edge_margins(self):
        painter=Mock()
        canvas=self.panel.canvas
        canvas._draw_scales(painter)
        calls=[call.args for call in painter.drawText.call_args_list]
        left=next(rect for rect,alignment,text in calls if alignment==Qt.AlignmentFlag.AlignRight and text not in {"mm","Layer"})
        right=next(rect for rect,alignment,text in calls if alignment==Qt.AlignmentFlag.AlignLeft and text!="Layer")
        self.assertAlmostEqual(left.right(),canvas.width()-right.left())

    def test_preview_view_buttons_align_right_wrap_in_two_rows_and_keep_geometry(self):
        p=self.panel;c=p.canvas;controls=c.view_controls
        before=p.draft
        for view,button in p.view_buttons.items():
            button.click()
            self.assertEqual(c.view,view)
            self.assertTrue(button.isChecked())
            self.assertEqual(p.draft.artifact_payload(),before.artifact_payload())
        c.set_view("side")
        for width,rows in ((1200,1),(360,2),(1200,1)):
            c.resize(width,500);controls.relayout()
            self.assertEqual(controls.rows,rows)
            self.assertEqual(controls.geometry().right(),c.width()-9)
            expected_y = p.canvas.history_controls.geometry().bottom()+8 if controls.x() <= p.canvas.history_controls.geometry().right()+8 else 8
            self.assertEqual(controls.y(),expected_y)
            self.assertFalse(controls.geometry().intersects(p.canvas.history_controls.geometry()))
            for i,button in enumerate(controls.buttons):
                index=controls.grid.indexOf(button)
                expected=(0,i) if rows==1 else divmod(i,3)
                self.assertEqual(controls.grid.getItemPosition(index)[:2],expected)
                self.assertEqual(button.height(),controls.button_height)
                self.assertGreaterEqual(button.height(),button.fontMetrics().height()+4)
            if rows==2:
                self.assertEqual(controls.width(),c.width()-16)
                self.assertFalse(c.caption_visible())
                painter=Mock();c._draw_scales(painter)
                headers=[call.args[0] for call in painter.drawText.call_args_list if call.args[2] in {"mm","Layer"}]
                self.assertTrue(all(rect.top()>controls.geometry().bottom() for rect in headers))
            else:
                self.assertTrue(c.caption_visible())
            self.assertEqual(p.fit_button.geometry().right(),controls.width()-1)
        c.zoom=2;c.pan=QPointF(20,30)
        p.fit_button.click()
        self.assertEqual(c.zoom,1)
        self.assertEqual(c.pan,QPointF())

    def test_fit_button_marks_changed_framing_and_clears_when_fitted(self):
        p=self.panel;c=p.canvas
        for view in ("side","front","top","bottom","free"):
            c.set_view(view)
            self.assertFalse(p.fit_button.property("needsFit"))
            start=QPoint(c.width()//2,c.height()//2)
            QTest.mousePress(c,Qt.MouseButton.MiddleButton,pos=start)
            QTest.mouseMove(c,start+QPoint(24,15))
            QTest.mouseRelease(c,Qt.MouseButton.MiddleButton,pos=start+QPoint(24,15))
            self.assertTrue(p.fit_button.property("needsFit"))
            p.fit_button.click()
            self.assertFalse(p.fit_button.property("needsFit"))
            event=QWheelEvent(QPointF(start),QPointF(start),QPoint(),QPoint(0,120),Qt.MouseButton.NoButton,
                              Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
            c.wheelEvent(event)
            self.assertTrue(p.fit_button.property("needsFit"))
            p.fit_button.click()
            c.resize(c.width()+20,c.height()+20);c.grab()
            c.set_highlight("object")
            p.change_setting("object_resolution_percent",100)
            self.assertFalse(p.fit_button.property("needsFit"))
        c.set_rotation(45)
        self.assertTrue(p.fit_button.property("needsFit"))
        p.fit_button.click()
        self.assertFalse(p.fit_button.property("needsFit"))
        start=QPoint(c.width()//2,c.height()//2)
        QTest.mousePress(c,Qt.MouseButton.RightButton,pos=start)
        QTest.mouseRelease(c,Qt.MouseButton.RightButton,pos=start+QPoint(24,15))
        self.assertTrue(p.fit_button.property("needsFit"))

    def test_resolution_controls_show_in_all_views_with_percentage_gradient(self):
        p=self.panel
        for view in ("side","top","front","bottom","free","side"):
            p.canvas.set_view(view);self.app.processEvents()
            self.assertTrue(p.resolution_host.isVisible())
        p.canvas.set_view("free");self.app.processEvents()
        slider=p.resolution_slider
        slider.resize(420,36);slider.setValue(8)
        image=slider.grab().toImage()
        # Sample the actual groove, away from the thumb. Most stage positions
        # must still be green, while the high-resolution end is red.
        for fraction in (.1,.3,.5):
            column=round((image.width()-1)*fraction)
            self.assertTrue(any(image.pixelColor(column,y).green()>image.pixelColor(column,y).red()
                                for y in range(image.height())))
        column=round((image.width()-1)*.95)
        self.assertTrue(any(image.pixelColor(column,y).red()>image.pixelColor(column,y).green()+60
                            for y in range(image.height())))

    def test_rotation_snap_labels_thin_in_groups_with_reading_space(self):
        labels=self.panel.rotation_end_labels
        seen=set()
        for width in (*range(600,49,-1),600):
            labels.resize(width,labels.height())
            self.app.processEvents()
            visible={angle for angle,label in labels.labels.items() if label.isVisible()}
            self.assertIn(visible,[set(range(-180,181,45)),set(range(-180,181,90)),{-180,0,180},set()])
            seen.add(len(visible))
            bounds=sorted((labels.labels[angle].geometry() for angle in visible),key=lambda rect:rect.left())
            for left,right in zip(bounds,bounds[1:]):
                self.assertGreaterEqual(right.left()-left.right()-1,12)
            positions=self.panel.rotation_slider.snap_positions(width)
            for angle in visible:
                label=labels.labels[angle]
                self.assertEqual(label.styleSheet(),self.panel.resolution_end_labels.faster.styleSheet())
                self.assertGreaterEqual(label.x(),0)
                self.assertLessEqual(label.x()+label.width(),width)
                if abs(angle)<180:
                    self.assertLessEqual(abs(label.geometry().center().x()-positions[angle]),1)
        self.assertEqual(seen,{0,3,5,9})
        self.assertTrue(all(label.isVisible() for label in labels.labels.values()))

    def test_resolution_end_labels_have_a_separate_line_and_hide_before_touching(self):
        p=self.panel;p.canvas.set_view("free");self.app.processEvents()
        heading=p.resolution_heading
        labels=p.resolution_end_labels
        threshold=labels.sizeHint().width()
        for width,visible in ((420,True),(threshold-1,False),(threshold,True),(65,False),(420,True)):
            labels.resize(width,labels.height());self.app.processEvents()
            self.assertEqual(labels.faster.isVisible(),visible)
            self.assertEqual(labels.precise.isVisible(),visible)
            self.assertEqual(heading.title.text(),"Auflösung (STL)")
            self.assertEqual((labels.faster.text(),labels.precise.text()),("Performance","Optik"))
            self.assertFalse(any(label.wordWrap() for label in (heading.title,labels.faster,labels.precise)))
            if visible:
                self.assertGreaterEqual(labels.precise.x()-labels.faster.geometry().right(),12)
            self.assertEqual(heading.info_button.height(),heading.title.fontMetrics().height())
            self.assertLess(heading.info_button.geometry().right(),heading.title.x())
            self.assertLessEqual(abs(heading.info_button.geometry().center().y()-heading.title.geometry().center().y()),1)
            self.assertIn("Nur für die Vorschau",heading.info_button.toolTip())
            self.assertIn("Originalqualität",heading.info_button.toolTip())
        heading_top=heading.mapTo(p.resolution_host,QPoint()).y()
        labels_top=labels.mapTo(p.resolution_host,QPoint()).y()
        slider_top=p.resolution_slider.mapTo(p.resolution_host,QPoint()).y()
        self.assertLess(heading_top,labels_top)
        self.assertLess(labels_top,slider_top)
        self.assertLessEqual(slider_top+p.resolution_slider.height(),p.resolution_host.height())
        self.assertLess(labels.faster.font().pointSizeF(),heading.title.font().pointSizeF())
        self.assertLess(len(heading.info_button.toolTip()),180)
        self.assertLessEqual(len(heading.info_button.toolTip().splitlines()),4)
        self.assertIn("0 %: Silhouette",heading.info_button.toolTip())
        self.assertEqual(p.resolution_slider.toolTip().splitlines()[:2],[
            "Performance → Optik:","0, 1, 5, 10, 15, 25, 50, 75, 100 %."])
        slider=p.resolution_slider
        slider.resize(420,36)
        with patch("cooling_tower.gui.widgets.manual_resolution_control.QPainter") as painter:
            slider.grab()
            marks=painter.return_value.drawLine.call_args_list
        self.assertEqual(len(marks),9)
        positions=[call.args[0] for call in marks]
        self.assertEqual(len(set(positions)),9)
        self.assertTrue(all(0 <= x < slider.width() for x in positions))
        p.change_setting("object_resolution_percent",50)
        self.assertTrue(p.resolution_reset.isEnabled())
        self.assertTrue(p.resolution_reset.property("modified"))
        p.set_busy(True)
        self.assertFalse(p.resolution_reset.isEnabled())
        p.set_busy(False)
        p.resolution_reset.click()
        self.assertEqual(p.settings.object_resolution_percent,75)
        self.assertFalse(p.resolution_reset.isEnabled())
        self.assertEqual(p.resolution_reset.size(),p.rotation_reset.size())

    def test_preview_highlight_buttons_have_equal_widths_and_all_actions_have_gradients(self):
        p=self.panel
        self.assertEqual(len({button.width() for button in p.highlight_buttons.values()}),1)
        self.assertTrue(all("qlineargradient" in button.styleSheet() for button in p.highlight_buttons.values()))
        self.assertIn("qlineargradient",p.canvas.view_controls.styleSheet())
        self.assertGreaterEqual(p.fit_button.height(),p.fit_button.fontMetrics().height()+8)

    def test_xray_controls_shrink_last_keep_equal_widths_and_shorten_the_title(self):
        p=self.panel;row=p.preview_tools;xray=p.highlight_host
        p.preview_container.layout().removeWidget(row)
        row.setParent(None);row.show()
        self.addCleanup(lambda:p.preview_container.layout().insertWidget(0,row))
        other_minimum=row._other_minimum_width()
        self.assertEqual([p.highlight_buttons[key].text() for key in ("tower","object")],
                         ["Turm","STL"])
        self.assertFalse(any(button.isChecked() for button in p.highlight_buttons.values()))
        self.assertFalse(p.highlight_group.exclusive())
        import math
        from PySide6.QtGui import QFontMetrics
        font=QFont(p.highlight_buttons["tower"].font());font.setBold(True)
        former_width=math.ceil((max(QFontMetrics(font).horizontalAdvance(text) for text in ("Turm","Beide","Objekt"))+12)*4/3)
        self.assertEqual(xray.preferred_button_width,math.ceil(former_width*6/5))
        for width,expected in ((other_minimum+xray.preferred_width+100,xray.preferred_width),
                               (other_minimum+xray.preferred_width,xray.preferred_width),
                               (other_minimum+xray.preferred_width-9,xray.preferred_width-9),
                               (other_minimum+xray.minimum_width,xray.minimum_width),
                               (other_minimum+xray.minimum_width-15,xray.minimum_width),
                               (other_minimum+xray.preferred_width+100,xray.preferred_width)):
            row.resize(width,row.height());self.app.processEvents()
            self.assertEqual(xray.width(),expected)
            widths={button.width() for button in p.highlight_buttons.values()}
            self.assertEqual(len(widths),1)
            self.assertGreaterEqual(min(widths),xray.minimum_button_width)
            self.assertEqual(len({button.y() for button in p.highlight_buttons.values()}),1)
            self.assertEqual(p.highlight_title.text(),"X-Ray (Transparenz)" if expected==xray.preferred_width else "X-Ray")
        for button in p.highlight_buttons.values():
            style=button.styleSheet()
            checked=style.rsplit("QPushButton:checked {",1)[1].split("}",1)[0]
            self.assertIn("background: qlineargradient",checked)
            self.assertIn("font-weight: bold",checked)
            self.assertNotIn("border:",checked)
            self.assertIn("border: 1px solid",style)

    def test_xray_buttons_make_only_the_named_surface_transparent_in_every_view(self):
        p=self.panel;c=p.canvas
        for view in ("side","front","top","bottom","free"):
            c.set_view(view);c.set_highlight("both");c.grab()
            original=c._object_cache
            tower=c._tower_cache
            for button,choice,object_opacity,tower_opacity in (("tower","tower",1,.35),("object","all",.28,.35),
                    ("tower","object",.28,1),("object","both",1,1)):
                with self.subTest(view=view,choice=choice):
                    p.highlight_buttons[button].click()
                    c._object_image_cache=None
                    with patch.object(c,"_draw_spatial_picture",wraps=c._draw_spatial_picture) as draw:
                        image=c.grab().toImage()
                    self.assertEqual(draw.call_args_list[0].args[2],object_opacity)
                    if view in {"top","bottom","free"}:
                        self.assertEqual(draw.call_args_list[1].args[2],tower_opacity)
                        self.assertIs(c._tower_cache,tower)
                    elif view=="side":
                        position=c.profile_to_screen(0,20).toPoint()
                        color=image.pixelColor(position)
                        if tower_opacity==1:
                            self.assertEqual(color.name(),c.TOWER_COLOR)
                        else:
                            self.assertGreater(color.blue(),QColor(c.TOWER_COLOR).blue()+60)
                    self.assertIs(c._object_cache,original)
                    self.assertEqual(c.highlight,choice)
                    self.assertEqual(p.highlight_buttons["tower"].isChecked(),choice in {"tower","all"})
                    self.assertEqual(p.highlight_buttons["object"].isChecked(),choice in {"object","all"})
                    for name,control in p.highlight_buttons.items():
                        inactive=control.styleSheet().split("QPushButton {",1)[1].split("}",1)[0]
                        self.assertIn("#fff6eb" if name=="tower" else "#f0f8fb",inactive)
                        self.assertIn("border-top-color",control.styleSheet())
                        self.assertIn("border-bottom-color",control.styleSheet())
                        inset=control.styleSheet().split("QPushButton:pressed, QPushButton:checked {",1)[1].split("}",1)[0]
                        self.assertIn("padding: 1px 4px 0 6px",inset)
                        self.assertIn("stop:0 #efbc75" if name=="tower" else "stop:0 "+c.OBJECT_COLOR,inset)
            p.highlight_buttons["tower"].click();p.highlight_buttons["object"].click()
            p.reset_all()
            self.assertEqual(c.highlight,"both")
            self.assertFalse(any(button.isChecked() for button in p.highlight_buttons.values()))

    def test_slider_grip_double_click_restores_manual_preview_defaults(self):
        p=self.panel
        for slider,value,expected in ((p.resolution_slider,3,8),(p.rotation_slider,57,0)):
            slider.setValue(value)
            self.app.processEvents()
            option=QStyleOptionSlider();slider.initStyleOption(option)
            handle=slider.style().subControlRect(QStyle.ComplexControl.CC_Slider,option,
                                                 QStyle.SubControl.SC_SliderHandle,slider)
            QTest.mouseClick(slider,Qt.MouseButton.LeftButton,pos=handle.center())
            QTest.mouseDClick(slider,Qt.MouseButton.LeftButton,pos=handle.center())
            QTest.qWait(30);self.app.processEvents()
            self.assertEqual(slider.value(),expected)
            self.assertFalse(slider.isSliderDown())
        self.assertEqual(p.settings.object_resolution_percent,75)
        self.assertEqual(p.resolution_label.text(),"75 %")
        self.assertEqual(p.canvas.object_rotation,0)
        self.assertEqual(p.rotation_label.text(),"0°")

    def test_rotation_slider_magnetically_snaps_every_45_degrees_only_while_dragged(self):
        p=self.panel;slider=p.rotation_slider
        self.assertEqual(slider.tickInterval(),45)
        self.assertEqual((slider.minimum(),slider.maximum(),slider.value()),(-180,180,0))
        slider.setSliderDown(True)
        for stop in range(-180,181,45):
            slider.setValue(stop+2 if stop<180 else stop-2)
            self.assertEqual(slider.value(),stop)
            self.assertEqual(p.rotation_label.text(),f"{stop}°")
        slider.setValue(17)
        self.assertEqual(slider.value(),17)
        slider.setValue(38)
        self.assertEqual(slider.value(),38)
        slider.setSliderDown(False)
        slider.setValue(47)
        self.assertEqual(slider.value(),47)
        deadline=time.monotonic()+1
        while p.canvas.object_rotation != 47 and time.monotonic()<deadline:
            QTest.qWait(20)
        self.assertEqual(p.canvas.object_rotation,47)

    def test_rotation_reset_uses_standard_size_style_and_modified_state(self):
        p=self.panel
        standard=p.rows["circle_segments"].reset_button
        self.assertEqual(p.rotation_reset.objectName(),standard.objectName())
        self.assertEqual(p.rotation_reset.size(),standard.size())
        self.assertEqual(p.rotation_reset.text(),standard.text())
        self.assertEqual(p.rotation_reset.styleSheet(),standard.styleSheet())
        self.assertFalse(p.rotation_reset.isEnabled())
        p.rotation_slider.setValue(47)
        self.assertTrue(p.rotation_reset.isEnabled())
        self.assertTrue(p.rotation_reset.property("modified"))
        p.rotation_reset.click()
        self.assertEqual(p.rotation_slider.value(),0)
        self.assertFalse(p.rotation_reset.isEnabled())
        self.assertFalse(p.rotation_reset.property("modified"))

    def test_selected_handle_shows_relevant_diameter_height_or_layer(self):
        p=self.panel;canvas=p.canvas
        for identity,expected in (("top_width","Spitze: Ø 5,00 mm"),("base","Grund: Ø 5,00 mm"),
                                  ("foot","Fuß: Ø 31,25 mm"),("foot_height","Layer: 40")):
            p.select(identity)
            self.assertEqual(canvas.selected_handle_text(),expected)
        p.insert(20);free=p.selected
        self.assertEqual(canvas.selected_handle_text(),"Layer: 100")
        p.checks["layer_snap_enabled"].setChecked(False)
        self.assertEqual(canvas.selected_handle_text(),"Höhe: 20,00 mm")
        p.select("foot_height")
        self.assertEqual(canvas.selected_handle_text(),"Höhe: 8,00 mm")
        p.select("control:0:1")
        self.assertEqual(canvas.information_identity(),"foot")
        self.assertIn("31,25 mm",canvas.selected_handle_text())
        p.move("base",10.3,8);p.select("base")
        self.assertEqual(canvas.selected_handle_text(),"Grund: Ø 10,30 mm")

    def test_horizontal_drags_snap_all_width_handles_to_tenths(self):
        p=self.panel;canvas=p.canvas
        p.insert(20);free=p.selected
        original=p.draft
        for snap_layers in (True,False):
            for view,identity in (("side","base"),("side","foot"),("side","top_width"),("side",free),
                                  ("side","control:0:1"),("side","control:0:2"),("front",free),
                                  ("top","top_width"),("bottom","foot")):
                with self.subTest(snap_layers=snap_layers,view=view,identity=identity):
                    p.commit(original);p.change_setting("layer_snap_enabled",snap_layers)
                    canvas.set_view(view);p.select("foot_height" if identity=="control:0:2" else "foot" if identity.startswith("control:") else identity)
                    handle=next(pos for name,pos,_ in canvas.handles() if name==identity)
                    canvas.pan+=QPointF(canvas.width()/2-handle.x(),canvas.height()/2-handle.y())
                    handle=next(pos for name,pos,_ in canvas.handles() if name==identity).toPoint()
                    before=canvas._vertical_handle_height(identity)
                    target=handle+QPoint(17,0)
                    QTest.mousePress(canvas,Qt.MouseButton.LeftButton,pos=handle)
                    QTest.mouseMove(canvas,target)
                    QTest.mouseRelease(canvas,Qt.MouseButton.LeftButton,pos=target)
                    diameter=canvas._horizontal_handle_radius(identity)*2
                    self.assertAlmostEqual(diameter*10,round(diameter*10))
                    self.assertEqual(canvas._vertical_handle_height(identity),before)
        p.commit(original);canvas.set_view("side");p.select(free);p.move(free,10.07,20)
        handle=next(pos for name,pos,_ in canvas.handles() if name==free).toPoint()
        QTest.mousePress(canvas,Qt.MouseButton.LeftButton,pos=handle)
        QTest.mouseMove(canvas,handle+QPoint(0,15))
        QTest.mouseRelease(canvas,Qt.MouseButton.LeftButton,pos=handle+QPoint(0,15))
        self.assertAlmostEqual(canvas._horizontal_handle_radius(free)*2,10.07)

    def test_horizontal_grid_stops_before_fractional_diameter_limit(self):
        p=self.panel
        p.change_setting("maximum_diameter_mm",10.07)
        p.move("base",11,8,diameter_snap=True)
        self.assertAlmostEqual(p.draft.base_diameter_mm,10)
        p.insert(20);free=p.selected
        p.move(free,12,25,diameter_snap=True,layer_snap=True)
        point=next(point.position for point in p.draft.points if point.identity==free)
        self.assertAlmostEqual(point.diameter_mm,10)
        self.assertAlmostEqual(point.z_mm,25)
        self.reference.context.validate(p.draft)

    def test_cached_surface_edges_and_nodes_keep_one_pixel_width_at_zoom(self):
        import numpy as np
        from PySide6.QtGui import QColor,QImage,QPainter,QPicture,QPolygonF
        from cooling_tower.gui.manual_view_worker import draw_surface
        picture=QPicture();painter=QPainter(picture)
        draw_surface(painter,QPolygonF([QPointF(1,1),QPointF(9,1),QPointF(1,9)]),QColor("#429baa"),1)
        painter.end()
        for scale in (1,5,15):
            with self.subTest(scale=scale):
                image=QImage(160,160,QImage.Format.Format_ARGB32_Premultiplied)
                image.fill(Qt.GlobalColor.transparent)
                painter=QPainter(image);painter.scale(scale,scale);painter.drawPicture(0,0,picture);painter.end()
                data=np.frombuffer(image.constBits(),dtype=np.uint8).reshape(160,160,4)
                ys,xs=np.nonzero(data[:,:,3])
                self.assertGreaterEqual(min(xs),scale-1)
                self.assertLessEqual(max(xs),9*scale+1)
                self.assertGreaterEqual(min(ys),scale-1)
                self.assertLessEqual(max(ys),9*scale+1)

    def test_two_visible_decimals_retain_exact_profile_coordinates(self):
        p=self.panel
        p.insert(20);identity=p.selected
        p.move(identity,12.345678,20.123456)
        for name,spin in p.editors.items():
            if name != "circle_segments":
                self.assertEqual(spin.textFromValue(12.345678),"12,35",name)
        self.assertEqual(preview_row(p,"point_diameter_mm").editor.text(),"12,35")
        self.assertAlmostEqual(p.draft.points[2].position.diameter_mm,12.345678)
        self.assertAlmostEqual(p.draft.points[2].position.z_mm,20.123456)
        before=p.draft.artifact_payload()
        preview_row(p,"point_diameter_mm").editor.setFocus();self.app.processEvents()
        p.canvas.setFocus();self.app.processEvents()
        self.assertEqual(p.draft.artifact_payload(),before)

    def test_settings_feedback_cannot_change_canvas_geometry(self):
        p=self.panel
        self.assertEqual(p.splitter.handleWidth(),1)
        self.assertEqual(p.settings_content.layout().contentsMargins().right(),0)
        self.assertEqual(p.preview_container.layout().contentsMargins().left(),14)
        for width,height in ((1400,900),(650,1100)):
            p.resize(width,height)
            self.app.processEvents()
            before=p.canvas.geometry()
            previous_scroll=p.settings_scroll.verticalScrollBar().maximum()
            p.rows["circle_segments"].set_error("Eine ausführliche Grenzrückmeldung. "*12)
            for _ in range(4):self.app.processEvents()
            self.assertEqual(p.canvas.geometry(),before)
            self.assertGreaterEqual(p.settings_scroll.verticalScrollBar().maximum(),previous_scroll)
            p.rows["circle_segments"].set_error(None)
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
        self.assertEqual((canvas._spatial_render_frame().yaw,canvas._spatial_render_frame().pitch),(90,0))
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
        from cooling_tower.gui.manual_view_worker import draw_surface
        with patch("cooling_tower.gui.manual_view_worker.draw_surface",wraps=draw_surface) as draw:
            image=render_spatial_object(self.reference,p.canvas._spatial_frame(),settings,Event())
        self.assertTrue(any(bytes(image.constBits())))
        self.assertEqual(len(draw.call_args_list),len(self.reference.object_triangles))
        self.assertTrue(all(call.args[2]==QColor(LayerRangeCanvas.OBJECT_COLOR) for call in draw.call_args_list))
        self.assertGreater(len({round(call.args[3],3) for call in draw.call_args_list}),1)

    def test_free_points_selection_removal_curve_and_reset(self):
        self.panel.insert(20)
        identity=self.panel.selected
        enter_preview_value(self.panel,"point_diameter_mm",30)
        self.assertEqual(self.panel.draft.points[2].position.diameter_mm,30)
        self.panel.reset_value("point_diameter_mm")
        self.assertAlmostEqual(self.panel.draft.points[2].position.diameter_mm,30)
        self.assertTrue(any(h[0].startswith("control:") for h in self.panel.canvas.handles()))
        self.panel.select("control:2:1")
        self.panel.move_control(2,1,8,25)
        self.assertTrue(self.panel.draft.curves[2].curved)
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

    def test_views_expose_only_their_allowed_handles_and_keep_geometry(self):
        p=self.panel;before=p.draft
        self.assertEqual([button.text() for button in p.view_buttons.values()],
                         ["Nebeneinander","Voreinander","Draufsicht","Untersicht","Freie 3D-Ansicht"])
        for view,identity,field in (("top","top_width","top_diameter_mm"),("bottom","foot","foot_diameter_mm")):
            p.canvas.set_view(view)
            limit="maximum_diameter_mm" if view=="top" else "maximum_foot_diameter_mm"
            self.assertEqual([h[0] for h in p.canvas.handles()],[identity,limit])
            self.assertTrue(preview_row(p,limit).isEnabled())
            self.assertTrue(preview_row(p,field).isEnabled())
            pos=p.canvas.handles()[0][1].toPoint()
            old=p.draft.points[-1 if view=="top" else 0].position
            QTest.mousePress(p.canvas,Qt.MouseButton.LeftButton,pos=pos)
            QTest.mouseMove(p.canvas,pos+QPoint(15,0))
            QTest.mouseRelease(p.canvas,Qt.MouseButton.LeftButton,pos=pos+QPoint(15,0))
            new=p.draft.points[-1 if view=="top" else 0].position
            self.assertGreater(new.radius_mm,old.radius_mm)
            self.assertEqual(new.z_mm,old.z_mm)
            p.commit(before)
        p.canvas.set_view("free")
        self.assertFalse(p.canvas.editable)
        self.assertFalse(p.canvas.handles())
        self.assertEqual((p.canvas.yaw_deg,p.canvas.pitch_deg),(-35,25))
        self.assertTrue(p.point_editor.isHidden())
        p.canvas.set_view("side")
        self.assertTrue(p.canvas.editable)
        self.assertTrue(preview_row(p,"base_diameter_mm").isEnabled())
        self.assertEqual(p.draft,before)

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
        self.assertEqual(self.panel.draft.artifact_payload(),before.artifact_payload())

    def test_boundary_feedback_survives_without_left_diameter_fields(self):
        self.panel.move("foot",25,self.panel.draft.first_layer_z_mm)
        self.panel.change_setting("maximum_foot_diameter_mm",30)
        self.panel._begin_interaction()
        for width in (40,45,50):self.panel.move("base",width,8)
        self.assertAlmostEqual(self.panel.draft.base_diameter_mm,40,places=6)
        self.assertEqual(self.panel.settings.maximum_foot_diameter_mm,42)
        self.assertIn("Maximaldurchmesser",self.panel.status_label.text())
        self.panel._end_interaction()
        row=enter_preview_value(self.panel,"base_diameter_mm",45)
        self.assertTrue(row.invalid)
        self.assertIn("Maximaldurchmesser",row.editor.toolTip())
        self.assertAlmostEqual(self.panel.draft.base_diameter_mm,40,places=6)

    def test_angle_activation_rejected_atomically(self):
        old=self.panel.draft
        self.panel.change_setting("contraction_angle_deg",1)
        self.panel.change_setting("contraction_enabled",True)
        self.assertFalse(self.panel.settings.contraction_enabled)
        self.assertNotIn("contraction_enabled",self.panel.checks)
        self.assertEqual(self.panel.draft.curves,old.curves)
        self.assertIn("Verjüngung",self.panel.status_label.text())

    def test_preview_numeric_attempt_beyond_range_is_rejected(self):
        old=self.panel.draft
        row=enter_preview_value(self.panel,"base_diameter_mm",9999)
        self.assertLessEqual(self.panel.draft.base_diameter_mm,self.panel.settings.maximum_diameter_mm+1e-6)
        self.assertEqual(self.panel.draft,old)
        self.assertTrue(row.invalid)
        self.assertIn("1000",row.editor.toolTip())

    def test_pending_feedback_is_cancelled_when_its_editor_is_deleted(self):
        panel=ManualGenerationPanel()
        panel.initialize(self.reference)
        panel.feedback(GeometryError("circle_segments","Test limit"),"points")
        with patch("sys.excepthook") as unhandled:
            panel.close()
            self.app.processEvents()
            panel.deleteLater()
            self.app.sendPostedEvents(None,QEvent.Type.DeferredDelete)
            QTest.qWait(750)
            unhandled.assert_not_called()

    def test_numeric_step_beyond_hard_segment_range_is_reported(self):
        spin=self.panel.editors["circle_segments"]
        spin.setValue(256)
        spin.stepBy(1)
        self.app.processEvents()
        self.assertEqual(self.panel.settings.circle_segments,256)
        self.assertEqual(self.panel.rows["circle_segments"].message_label.text(),"Max. Segmente = 256")

    def test_existing_coupled_tangents_remain_valid_when_editing_controls(self):
        self.panel.insert(20)
        identity=self.panel.selected
        self.panel.move(identity,15,20)
        from cooling_tower.manual.geometry import couple_point
        self.panel.commit(couple_point(self.panel.draft,identity,True))
        self.assertTrue(self.panel.draft.points[2].smooth)
        self.panel.select("control:1:2")
        self.panel.move_control(1,2,12,18)
        a,b=self.panel.draft.curves[1:3]
        self.assertAlmostEqual(a.derivative(1,"radius_mm")/a.derivative(1,"z_mm"),b.derivative(0,"radius_mm")/b.derivative(0,"z_mm"))

    def test_colors_actual_layers_direction_and_visual_identity(self):
        p=self.panel
        before=p.draft.artifact_payload()
        p.change_setting("critical_layers_enabled",True)
        p.color_scale_spin.setValue(28)
        p.change_setting("color_reference_time_s",15)
        layer=self.reference.context.layers[7]
        self.assertEqual(p.canvas._object_color(layer),LayerRangeCanvas.layer_time_color(15,p.settings.color_red_time_s,layer.total_time_s))
        p.change_setting("critical_layers_enabled",False)
        self.assertEqual(p.canvas._object_color(layer).name(),p.canvas.OBJECT_COLOR)
        p.change_setting("overhang_enabled",True);p.change_setting("overhang_angle_deg",10)
        self.assertEqual(p.canvas._surface_color(3).name(),p.canvas.TOWER_COLOR)
        p.insert(20);p.move(p.selected,30,20)
        self.assertEqual(p.canvas._surface_color(15).name(),"#e5484d")
        self.assertEqual(p.canvas._surface_color(30).name(),p.canvas.TOWER_COLOR)
        p.change_setting("overhang_enabled",False)
        self.assertEqual(p.canvas._surface_color(15).name(),p.canvas.TOWER_COLOR)

    def test_overhang_marking_starts_enabled_and_reset_restores_it(self):
        p=self.panel
        self.assertTrue(p.checks["overhang_enabled"].isChecked())
        self.assertTrue(p.draft.settings.overhang_enabled)
        artifact=p.draft.artifact_payload()
        p.checks["overhang_enabled"].setChecked(False)
        self.assertFalse(p.draft.settings.overhang_enabled)
        self.assertEqual(p.draft.artifact_payload(),artifact)
        p.reset_all()
        self.assertTrue(p.checks["overhang_enabled"].isChecked())
        self.assertTrue(p.draft.settings.overhang_enabled)

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
        self.panel.highlight_buttons["tower"].click()
        self.assertEqual(self.panel.canvas.object_rotation,147)
        self.assertEqual(self.panel.draft,before)
        self.assertEqual(self.request.source_artifact.original_sha256,source_hash)
        self.panel.resize(650,1100);self.app.processEvents()
        self.assertEqual(self.panel.splitter.orientation(),Qt.Orientation.Vertical)
        self.assertLessEqual(self.panel.canvas.width(),650)
        self.assertGreater(self.panel.settings_scroll.verticalScrollBar().maximum(),0)
        self.assertTrue(self.panel.canvas.grab().save(str(self.f.root/"small_editor.png")))


    def test_tip_width_is_independent_and_exposes_own_and_facing_neighbor_anchors(self):
        p=self.panel
        p.select("top_width")
        controls=[h for h in p.canvas.handles() if h[2]=="control"]
        self.assertEqual({h[0] for h in controls},{"control:1:1","control:1:2"})
        height=p.draft.height_mm
        p.move("top_width",14,999)
        self.assertEqual(p.draft.points[-1].position.diameter_mm,14)
        self.assertEqual(p.draft.height_mm,height)
        p.move("base",10,999)
        self.assertEqual(p.draft.points[-1].position.diameter_mm,14)
        p.select("control:1:2")
        p.move_control(1,2,12,30)
        self.assertTrue(p.draft.curves[-1].curved)
        self.assertEqual(p.draft.points[-1].position.diameter_mm,14)

    def test_boundary_keeps_both_permitted_axes_moving(self):
        p=self.panel
        p.insert(20);identity=p.selected
        p.move(identity,1,25)
        point=next(point.position for point in p.draft.points if point.identity==identity)
        self.assertAlmostEqual(point.diameter_mm,5,places=6)
        self.assertAlmostEqual(point.z_mm,25,places=6)
        p.move(identity,1,30)
        point=next(point.position for point in p.draft.points if point.identity==identity)
        self.assertAlmostEqual(point.z_mm,30,places=6)
        p.move(identity,18,100)
        point=next(point.position for point in p.draft.points if point.identity==identity)
        self.assertAlmostEqual(point.diameter_mm,18,places=6)
        self.assertLess(point.z_mm,p.draft.height_mm)
        p.move_control(1,1,0,18)
        self.assertAlmostEqual(p.draft.curves[1].control1.z_mm,18,places=6)

    def test_scales_zoom_pan_and_exact_layer_feedback(self):
        canvas=self.panel.canvas
        coarse_h,coarse_l=canvas.scale_ticks()
        self.assertTrue(coarse_h);self.assertTrue(coarse_l)
        self.assertGreater(coarse_l[1][0]-coarse_l[0][0],1)
        canvas.zoom=20
        z=self.reference.context.layers[60].z_mm
        canvas.pan+=QPointF(0,canvas.height()/2-canvas.profile_to_screen(0,z).y())
        fine_h,fine_l=canvas.scale_ticks()
        self.assertLess(fine_h[1][0]-fine_h[0][0],coarse_h[1][0]-coarse_h[0][0])
        self.assertTrue(any(b[0]-a[0]==1 for a,b in zip(fine_l,fine_l[1:])))
        for index,y,_ in fine_l:
            self.assertAlmostEqual(y,canvas.profile_to_screen(0,self.reference.context.layers[index-1].z_mm).y())
        canvas._drag_height_z=z
        self.assertIn("Höhe:",canvas.drag_height_text())
        self.assertIn("Layer: 61",canvas.drag_height_text())
        self.assertNotIn("Greiferhöhe",canvas.drag_height_text())
        canvas._drag_height_z=1000
        self.assertIn("Layer: –",canvas.drag_height_text())

    def test_spatial_surface_cache_survives_pan_zoom_resize_and_highlight(self):
        p=self.panel;canvas=p.canvas
        canvas.set_view("free");canvas.grab()
        cache=canvas._object_cache;key=canvas._spatial_key();tower=canvas._tower_cache
        start=QPoint(200,200)
        with patch.object(canvas,"_render_object",wraps=canvas._render_object) as render:
            QTest.mousePress(canvas,Qt.MouseButton.MiddleButton,pos=start)
            QTest.mouseMove(canvas,start+QPoint(45,35))
            QTest.mouseRelease(canvas,Qt.MouseButton.MiddleButton,pos=start+QPoint(45,35))
            canvas.grab()
            event=QWheelEvent(QPointF(310,200),QPointF(310,200),QPoint(),QPoint(0,120),
                             Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
            canvas.wheelEvent(event);canvas.grab()
            p.resize(1300,950);self.app.processEvents();canvas.grab()
            canvas.set_highlight("tower");canvas.grab()
            canvas.fit_scene();canvas.grab()
            render.assert_not_called()
        self.assertIs(canvas._object_cache,cache)
        self.assertIs(canvas._tower_cache,tower)
        self.assertEqual(canvas._spatial_key(),key)
        canvas.set_rotation(37);canvas.grab()
        self.assertNotEqual(canvas._spatial_key(),key)

    def test_seam_data_does_not_change_manual_preview_or_legend(self):
        from cooling_tower.preview import Point3D
        canvas = self.panel.canvas
        clean = replace(self.reference, source_data=replace(self.reference.source_data, seam_points=()))
        marked = replace(clean, source_data=replace(clean.source_data,
            seam_points=(Point3D(5, 5, .2), Point3D(5, 5, 20))))
        for view in ("side", "front", "free", "top", "bottom"):
            with self.subTest(view=view):
                canvas.set_view(view)
                canvas.set_reference(clean)
                expected = canvas.grab().toImage()
                canvas.set_reference(marked)
                self.assertEqual(canvas.grab().toImage(), expected)
        self.assertNotIn("Seams", [label.text() for label in self.panel.preview_information.legend_labels])

    def test_gcode_only_reference_keeps_static_views_and_layer_scales(self):
        canvas=self.panel.canvas
        reference=replace(self.reference,object_triangles=None,silhouette=None)
        canvas.set_reference(reference)
        self.assertIsNone(reference.object_triangles)
        for view in ("side","front"):
            canvas.set_view(view)
            self.assertFalse(canvas.grab().isNull())
            self.assertTrue(canvas.scale_ticks()[1])

    def test_fitting_rotated_gcode_never_changes_source_coordinates(self):
        import numpy as np
        canvas=self.panel.canvas
        reference=replace(self.reference,object_triangles=None,silhouette=None)
        canvas.set_reference(reference)
        source=canvas._object_array.copy()
        canvas.set_rotation(37)
        for view in ("side","front","free","top","bottom","free"):
            canvas.set_view(view)
            canvas.fit_scene()
            first=canvas.grab().toImage()
            canvas.fit_scene()
            self.assertEqual(canvas.grab().toImage(),first)
            np.testing.assert_array_equal(canvas._object_array,source)

    def test_proxy_and_completed_surfaces_keep_the_same_rotated_original(self):
        import numpy as np
        from cooling_tower.gui.manual_view_worker import render_spatial_object
        p=self.panel;canvas=p.canvas
        p.change_setting("object_resolution_percent",100)
        triangles=self.reference.object_triangles.copy()
        center=np.asarray(self.reference.silhouette.center_xy)
        triangles[:,:,0]=center[0]+(triangles[:,:,0]-center[0])*1.8
        triangles[:,:,1]=center[1]+(triangles[:,:,1]-center[1])*.4
        reference=replace(self.reference,object_triangles=np.tile(triangles,(600,1,1)))
        canvas.set_reference(reference)
        canvas.set_view("free")
        canvas._render_manager=object()
        try:
            with patch.object(canvas,"_queue_spatial_render"):
                for view in ("side","front","free","top","bottom"):
                    canvas.set_view(view)
                    for rotation in (0,37,90):
                        canvas.set_rotation(rotation)
                        canvas.fit_scene()
                        canvas.grab()
                        proxy=canvas._original_image().copy()
                        picture=render_spatial_object(reference,canvas._spatial_render_frame(),p.settings,None,vector=True)
                        canvas._spatial_succeeded(canvas._view_request_id,(canvas._spatial_key(),picture))
                        canvas.grab()
                        completed=canvas._original_image().copy()
                        def bounds(image):
                            data=np.frombuffer(image.constBits(),dtype=np.uint8).reshape(image.height(),image.bytesPerLine()//4,4)
                            # Compare only the original image, including its new
                            # blue backing. Toolbar/handles and tower occlusion
                            # cannot be used to measure original-object bounds.
                            mask=np.any(data[:,:,:3]!=np.array((242,236,230)),axis=2)
                            ys,xs=np.nonzero(mask)
                            self.assertTrue(len(xs))
                            return np.array((xs.min(),ys.min(),xs.max(),ys.max()))
                        np.testing.assert_allclose(bounds(proxy),bounds(completed),atol=3)
        finally:
            canvas._render_manager=None

    def test_manual_time_target_and_tolerance_have_no_controls_or_artifact_effect(self):
        p=self.panel
        self.assertNotIn("target_layer_time_s",p.rows)
        self.assertNotIn("layer_time_tolerance_s",p.rows)
        before=p.draft.artifact_payload()
        p.color_scale_spin.setValue(28)
        p.change_setting("color_reference_time_s",15)
        p.change_setting("color_deficit_time_s",6)
        self.assertEqual(p.draft.artifact_payload(),before)


class ManualControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app,cls._previous_font,cls._test_font_id=preview_test_application()

    @classmethod
    def tearDownClass(cls):restore_preview_test_application(cls.app,cls._previous_font,cls._test_font_id)

    def setUp(self):
        self.f,self.service,ref,request,self.adapter=create_fixture(self,joint=True,count=100)
        self.window=MainWindow(user_data_root=self.f.root/"app",enable_update_check=False,enable_startup_slicer_discovery=False)
        self.addCleanup(dispose_test_widget,self.window)
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

    def test_manual_generation_requires_current_source_and_confirmed_slicer_profiles(self):
        w,c,p=self.window,self.controller,self.panel
        for attribute, value in (("analysis_snapshot",None),("profile_match_result",None)):
            with self.subTest(attribute=attribute), patch.object(w,attribute,value), patch.object(c,"_start") as start:
                with self.assertRaisesRegex(ValueError,"Quelle, Slicer und Druckprofile"):
                    c.build_request(p.draft)
                c.generate()
                start.assert_not_called()
                self.assertIsNone(c.session.preview)
        for attribute, value in (("selected",None),("user_confirmed",False),("can_use_stl_mode",False)):
            with self.subTest(attribute=attribute), patch.object(w.profile_match_result,attribute,value), patch.object(c,"_start") as start:
                with self.assertRaisesRegex(ValueError,"Quelle, Slicer und Druckprofile"):
                    c.build_request(p.draft)
                c.generate()
                start.assert_not_called()
                self.assertIsNone(c.session.preview)
        self.assertIs(c.build_request(p.draft).adapter,self.adapter)

    def test_empty_manual_footer_is_only_as_high_as_its_buttons(self):
        p,w=self.panel,self.window
        self.show_manual_footer()
        for label in (p.status_label,p.result_label,p.action_hint):label.clear()
        p.progress.hide()
        self.controller.refresh_footer();w._fit_footer_height();self.app.processEvents()
        margins=w.footer_layout.contentsMargins()
        reset=w.reset_button.sizeHint().height();actions=w.main_actions_layout.sizeHint().height()
        expected=(reset+actions+w.footer_content_grid.verticalSpacing()*2+1 if w._footer_narrow_layout
                  else max(reset,actions))+margins.top()+margins.bottom()
        self.assertLessEqual(w.footer.height(),expected+2)
        self.assertTrue(w.manual_footer_status_widget.isHidden())
        p.status_label.setText("Eine längere Statusmeldung. "*20)
        self.controller.refresh_footer();w._fit_footer_height();self.app.processEvents()
        self.assertGreater(w.footer.height(),expected+20)
        p.status_label.clear();self.controller.refresh_footer();w._fit_footer_height();self.app.processEvents()
        self.assertLessEqual(w.footer.height(),expected+2)

    def test_manual_progress_and_step_stay_above_right_actions_after_resizing(self):
        from threading import Event
        from cooling_tower.preview import PreviewCancelled
        c,p,w=self.controller,self.panel,self.window
        self.show_manual_footer()
        c.generate();self.wait_idle()
        previous_summary=p.result_label.text()
        p.move("base",10,8)
        started=Event()
        def blocked_prepare(request,*,cancellation_event,progress_callback):
            progress_callback(45,"Gemeinsamer Prüfslice der festen Form …")
            started.set()
            cancellation_event.wait(5)
            raise PreviewCancelled()
        c.service.prepare=blocked_prepare
        w.preview_button.click()
        self.assertTrue(started.wait(2))
        for width in (1450,720,1450):
            with self.subTest(width=width):
                w.resize(width,1100)
                for _ in range(8):self.app.processEvents()
                self.assertTrue(w.footer_action_area.isAncestorOf(p.progress))
                self.assertTrue(w.footer_action_area.isAncestorOf(c._progress_status_label))
                self.assertTrue(w.footer_messages_content.isAncestorOf(p.status_label))
                self.assertFalse(w.footer_messages_content.isAncestorOf(p.progress))
                self.assertTrue(p.progress.isVisible())
                self.assertTrue(p.result_label.isHidden())
                self.assertTrue(c._result_notice.isHidden())
                self.assertEqual(p.progress.value(),45)
                self.assertIn("Gemeinsamer Prüfslice",c._progress_status_label.text())
                self.assertLess(p.progress.mapTo(w.footer_action_area,QPoint(0,p.progress.height())).y(),
                                c._progress_status_label.mapTo(w.footer_action_area,QPoint()).y())
                self.assertLess(c._progress_status_label.mapTo(w.footer_action_area,QPoint(0,c._progress_status_label.height())).y(),
                                w.preview_button.mapTo(w.footer_action_area,QPoint()).y())
        w.preview_button.click();self.wait_idle()
        self.assertTrue(p.progress.isHidden())
        self.assertTrue(p.result_label.isVisible())
        self.assertEqual(p.result_label.text(),previous_summary)
        self.assertIn("abgebrochen",p.status_label.text())
        self.assertTrue(w.footer_messages_content.isAncestorOf(p.status_label))
        self.assertEqual(c._progress_status_label.text(),"")

    def test_general_manual_information_stays_left_and_uses_tower_profile_instruction(self):
        c,p,w=self.controller,self.panel,self.window
        self.show_manual_footer()
        c.invalidate_context();c.ensure_context();self.wait_idle()
        self.assertEqual(p.status_label.text(),"Turmprofil doppelklicken, um freie Punkte hinzuzufügen.")
        for width in (1450,720,1450):
            w.resize(width,1100)
            for _ in range(8):self.app.processEvents()
            self.assertTrue(p.status_label.isVisible())
            self.assertTrue(w.footer_messages_content.isAncestorOf(p.status_label))
            self.assertFalse(w.footer_action_area.isAncestorOf(p.status_label))
            self.assertTrue(w.manual_footer_status_scroll.isHidden())
            self.assertTrue(w.manual_footer_message_widget.isVisible())
        c.generate();self.wait_idle()
        p.feedback(GeometryError("maximum_diameter_mm","Ungültiger Durchmesser"),"points")
        for _ in range(8):self.app.processEvents()
        self.assertTrue(p.status_label.isVisible())
        self.assertEqual(p.status_label.text(),"Ungültiger Durchmesser")
        self.assertTrue(w.footer_messages_content.isAncestorOf(p.status_label))
        self.assertTrue(w.footer_action_area.isAncestorOf(p.result_label))

    def test_manual_result_is_compact_and_preserved_with_evidence_and_warnings(self):
        c,p,w=self.controller,self.panel,self.window
        self.show_manual_footer()
        w.preview_button.click();self.wait_idle()
        result=c.session.preview
        self.assertIn(f"Erreichte Mindest-Layerzeit: {result.manual_evaluation.minimum_time_s:.3f} s",p.result_label.text())
        self.assertIn("Gemeinsamer Prüfslice",p.result_label.text())
        self.assertIn(f"{len(result.manual_evaluation.layer_times)} Layer",p.result_label.text())
        self.assertEqual(p.result_label.text().count("<br>"),1)
        self.assertEqual(p.status_label.text(),"")
        self.assertTrue(w.footer_action_area.isAncestorOf(p.result_label))
        self.assertEqual(c._result_warnings_label.text(),"\n".join(result.warnings))
        self.assertFalse(c._result_notice.is_expanded())
        previous_text=p.result_label.text()
        p.move("base",10,8)
        self.assertEqual(p.result_label.text(),previous_text)
        self.assertIn("bisherigen",p.action_hint.text())
        self.assertEqual(c.session.preview_state,PreviewState.STALE)
        w.generation_mode=GenerationMode.AUTOMATIC
        w._refresh_footer_auxiliary_visibility()
        self.assertTrue(w.manual_footer_status_scroll.isHidden())
        w.generation_mode=GenerationMode.MANUAL;c.refresh_footer()
        self.assertFalse(w.manual_footer_status_scroll.isHidden())
        self.assertEqual(p.result_label.text(),previous_text)
        c.invalidate_context()
        self.assertEqual(p.result_label.text(),"")
        self.assertTrue(c._result_notice.isHidden())

    def test_separate_manual_slice_summary_is_explicitly_a_prognosis(self):
        c,p,w=self.controller,self.panel,self.window
        w.source_artifact=None
        c.ensure_context();self.wait_idle()
        c.generate();self.wait_idle()
        self.assertFalse(c.session.preview.manual_evaluation.joint_sliced)
        self.assertIn("Prognostizierte Mindest-Layerzeit",p.result_label.text())
        self.assertIn("Separate Zeitprognose",p.result_label.text())
        self.assertNotIn("Erreichte",p.result_label.text())
        self.assertIn("keine gemeinsame Verifikation",c._result_warnings_label.text())

    def test_expanded_manual_result_details_scroll_and_collapse_back_to_summary(self):
        c,p,w=self.controller,self.panel,self.window
        self.show_manual_footer()
        c.generate();self.wait_idle()
        c._result_warnings_label.setText("Ausführlicher Hinweis zur Zeitbewertung. "*100)
        c.refresh_footer()
        for width in (1450,720):
            with self.subTest(width=width):
                w.resize(width,1100)
                for _ in range(8):self.app.processEvents()
                compact_height=w.footer.height()
                c._result_notice.set_expanded(True)
                for _ in range(8):self.app.processEvents()
                scroll=w.manual_footer_status_scroll
                self.assertGreater(scroll.verticalScrollBar().maximum(),0)
                self.assertTrue(w.export_button.isVisible())
                self.assertLessEqual(w.export_button.mapTo(w.footer,QPoint(0,w.export_button.height())).y(),w.footer.height())
                c._result_notice.set_expanded(False)
                for _ in range(8):self.app.processEvents()
                self.assertEqual(w.footer.height(),compact_height)
                self.assertEqual(scroll.verticalScrollBar().maximum(),0)
                self.assertTrue(p.result_label.isVisible())

    def test_long_manual_feedback_scrolls_without_covering_buttons(self):
        c,p,w=self.controller,self.panel,self.window
        self.show_manual_footer()
        for width in (1450,720,1450):
            with self.subTest(width=width):
                w.resize(width,1100)
                for _ in range(8):self.app.processEvents()
                empty_height=w.footer.height()
                p.status_label.setText("Eine ausführliche Meldung zum manuellen Lauf. "*100)
                c.refresh_footer()
                for _ in range(8):self.app.processEvents()
                scroll=w.footer_messages_scroll
                self.assertGreater(scroll.verticalScrollBar().maximum(),0)
                self.assertGreaterEqual(p.status_label.height(),p.status_label.heightForWidth(p.status_label.width()))
                self.assertLessEqual(scroll.mapTo(w.footer,QPoint(0,scroll.height())).y(),
                                     w.reset_button.mapTo(w.footer,QPoint()).y())
                for button in (w.preview_button,w.reset_button,w.tower_reset_button):
                    bottom=button.mapTo(w.footer,QPoint(0,button.height())).y()
                    self.assertLessEqual(bottom,w.footer.height())
                p.status_label.clear();c.refresh_footer()
                for _ in range(8):self.app.processEvents()
                self.assertTrue(scroll.isHidden())
                self.assertTrue(w.manual_footer_status_scroll.isHidden())
                self.assertEqual(w.footer.height(),empty_height)

    def test_narrow_manual_navigation_shows_recommendation_and_wide_hides_it(self):
        p,w=self.panel,self.window
        self.show_manual_footer()
        w.resize(700,1000);self.app.processEvents()
        self.assertTrue(w.generation_method_recommendation.isVisible())
        self.assertIn("Zweispaltige Ansicht empfohlen - Fenster verbreitern",w.generation_method_recommendation.text())
        self.assertIn("#b42318",w.generation_method_recommendation.styleSheet())
        self.assertFalse(hasattr(w,"generation_method_label"))
        self.assertEqual(w.generation_method_recommendation.alignment(),Qt.AlignmentFlag.AlignCenter)
        w.resize(1450,1000);self.app.processEvents()
        self.assertTrue(w.generation_method_navigation.isHidden())
        self.assertTrue(w.generation_method_recommendation.isHidden())

    def test_manual_outer_scrollbar_only_appears_for_actual_overflow_without_unused_pane_space(self):
        p,w=self.panel,self.window
        self.show_manual_footer()
        for width,height in ((1000,1394),(1450,1000),(720,800),(1000,1394)):
            w.resize(width,height)
            for _ in range(10):self.app.processEvents()
            scrollbar=w.settings_scroll.verticalScrollBar()
            self.assertEqual(scrollbar.isVisible(),scrollbar.maximum()>0)
            if height>1000 or width>1000:
                self.assertEqual(scrollbar.maximum(),0)
            else:
                self.assertGreater(scrollbar.maximum(),0)
            if p.splitter.orientation()==Qt.Orientation.Vertical:
                self.assertEqual(p.preview_container.y(),p.settings_scroll.height()+p.splitter.handleWidth())

    def test_all_reset_is_available_for_rotation_and_resolution_in_every_view(self):
        p,w=self.panel,self.window
        self.show_manual_footer()
        automatic=w.collect_settings()
        for view in ("side","front","top","bottom","free"):
            p.reset_all();p.canvas.set_view(view)
            with patch.object(p._rotation_timer,"start"):
                p.rotation_slider.setValue(47)
            self.assertEqual(p.canvas.object_rotation,0)
            self.assertTrue(w.reset_button.isEnabled())
            self.assertEqual(w.reset_button.text(),"Alles zurücksetzen")
            yes=object();box=Mock();box._reset_yes_button=yes;box.clickedButton.return_value=yes
            with patch.object(w,"_create_reset_defaults_message_box",return_value=box):
                w.reset_button.click()
            self.assertEqual(p.canvas.view,view)
            self.assertEqual(p.canvas.object_rotation,0)
            self.assertEqual(p.rotation_slider.value(),0)
            self.assertFalse(w.reset_button.isEnabled())
            p.change_setting("object_resolution_percent",50)
            self.assertTrue(w.reset_button.isEnabled())
            with patch.object(w,"_create_reset_defaults_message_box",return_value=box):
                w.reset_button.click()
            self.assertEqual(p.settings.object_resolution_percent,75)
            self.assertEqual(w.collect_settings(),automatic)

    def test_manual_results_and_export_report_do_not_rate_target_times(self):
        c,p,w=self.controller,self.panel,self.window
        c.generate();self.wait_idle()
        self.assertIn("Erreichte Mindest-Layerzeit",p.result_label.text())
        self.assertNotIn("Ziel",p.result_label.text())
        self.assertNotIn("Toleranz",p.result_label.text())
        from cooling_tower.manual.service import ManualExportService
        result=ManualExportService().export(c.session.preview,c.session.successful_request,self.f.root/"quantitative_export")
        report=result.user_report_path.read_text(encoding="utf-8")
        self.assertIn("Layerzeit",report)
        self.assertNotIn("Ziel-Layerzeit",report)
        self.assertNotIn("Toleranz",report)
        self.assertFalse(any("Mindest-Layerzeit" in warning for warning in c.session.preview.warnings))
        with patch.object(w,"_show_internal_dialog_without_flash"):
            w._show_export_success_dialog(result)
        self.assertEqual(w.export_success_deviation_label.text(),"")
        self.assertTrue(w.export_success_deviation_label.isHidden())

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

    def test_tower_reset_button_restores_only_form_and_preserves_settings_and_result(self):
        c,p,w=self.controller,self.panel,self.window
        self.show_manual_footer()
        automatic=w.collect_settings()
        p.change_setting("maximum_diameter_mm",35)
        p.change_setting("maximum_foot_diameter_mm",50)
        p.change_setting("object_resolution_percent",5)
        p.change_setting("layer_snap_enabled",False)
        p.move("foot",30,p.draft.first_layer_z_mm)
        p.move("foot_height",5,7)
        p.move("base",10,7)
        p.insert(12);p.reset_point_curves(p.selected)
        p.move("top",10,18)
        settings=p.settings
        c.generate();self.wait_idle()
        result=c.session.preview
        p.canvas.set_view("free");p.canvas.grab()
        original_cache=p.canvas._object_cache
        self.assertTrue(w.tower_reset_button.isEnabled())
        w.tower_reset_button.click()
        self.assertEqual(w.tower_reset_button.text(),"Turmform zurücksetzen")
        self.assertEqual((p.settings.maximum_diameter_mm,p.settings.maximum_foot_diameter_mm),(35,50))
        for name in ("object_resolution_percent","layer_snap_enabled","color_reference_time_s","overhang_angle_deg"):
            self.assertEqual(getattr(p.settings,name),getattr(settings,name))
        self.assertEqual([point.kind for point in p.draft.points],["foot","base","top"])
        self.assertEqual(p.draft.base_diameter_mm,ManualSettings().minimum_diameter_mm)
        self.assertEqual(p.draft.points[-1].position.diameter_mm,ManualSettings().minimum_diameter_mm)
        self.assertEqual(p.draft.height_mm,c.reference.context.layers[-1].z_mm)
        self.assertFalse(p.draft.curves[-1].curved)
        self.assertEqual(p.selected,"base")
        self.assertEqual(w.collect_settings(),automatic)
        self.assertIs(c.session.preview,result)
        self.assertEqual(c.session.preview_state,PreviewState.STALE)
        self.assertFalse(w.tower_reset_button.isEnabled())
        p.canvas.grab()
        self.assertIs(p.canvas._object_cache,original_cache)

    def test_tower_reset_button_stays_right_of_defaults_at_both_footer_widths(self):
        p,w=self.panel,self.window
        self.show_manual_footer()
        p.insert(12)
        for width in (1450,700):
            w.resize(width,1000)
            for _ in range(4):self.app.processEvents()
            a=w.reset_button.mapTo(w.footer_reset_host,QPoint())
            b=w.tower_reset_button.mapTo(w.footer_reset_host,QPoint())
            self.assertTrue(w.tower_reset_button.isVisible())
            self.assertGreaterEqual(b.x(),a.x()+w.reset_button.width())
            self.assertEqual(a.y(),b.y())
            self.assertEqual(w.reset_button.height(),w.tower_reset_button.height())
            self.assertLessEqual(b.x()+w.tower_reset_button.width(),w.footer_reset_host.width())
            if not w._footer_narrow_layout:
                reset_bottom=w.footer_reset_host.mapTo(w.footer,QPoint(0,w.footer_reset_host.height())).y()
                action_bottom=w.footer_action_area.mapTo(w.footer,QPoint(0,w.footer_action_area.height())).y()
                self.assertEqual(reset_bottom,action_bottom)
        w.generation_mode=GenerationMode.AUTOMATIC
        w._refresh_footer_auxiliary_visibility()
        self.assertTrue(w.tower_reset_button.isHidden())

    def test_footer_resets_distinguish_current_limits_from_default_settings(self):
        p,w=self.panel,self.window
        self.show_manual_footer()
        default=ManualSettings().minimum_diameter_mm
        for all_values in (False,True):
            p.move("base",20,8);p.move_limit("minimum_diameter_mm",12.3)
            p.select("minimum_diameter_mm")
            self.assertTrue(w.reset_button.isEnabled())
            self.assertTrue(w.tower_reset_button.isEnabled())
            if all_values:
                yes=object();box=Mock();box._reset_yes_button=yes;box.clickedButton.return_value=yes
                with patch.object(w,"_create_reset_defaults_message_box",return_value=box):
                    w.reset_button.click()
            else:
                w.tower_reset_button.click()
            expected=default if all_values else 12.3
            self.assertEqual(p.settings.minimum_diameter_mm,expected)
            self.assertEqual(preview_row(p,"minimum_diameter_mm").field.value,expected)
            self.assertEqual(p.draft.base_diameter_mm,expected)
            self.assertEqual(p.draft.points[-1].position.diameter_mm,expected)
            left,right,_,_=p.canvas.minimum_measure_geometry()
            self.assertAlmostEqual(right.x()-left.x(),expected*p.canvas.transform()[0])
            self.assertEqual(w.reset_button.isEnabled(),not all_values)
            self.assertFalse(w.tower_reset_button.isEnabled())

    def test_settings_scroll_position_survives_collapse_and_main_window_layout_callbacks(self):
        p,w=self.panel,self.window
        self.show_manual_footer();w.resize(1050,1394)
        for _ in range(8):self.app.processEvents()
        bar=p.settings_scroll.verticalScrollBar();bar.setValue(bar.maximum())
        original=bar.value()
        p.set_settings_collapsed(True);QTest.qWait(330)
        p.set_settings_collapsed(False);QTest.qWait(330)
        self.assertEqual(bar.value(),original)
        bar.triggerAction(bar.SliderAction.SliderSingleStepSub)
        requested=bar.value()
        self.assertFalse(p._settings_scroll_restore_pending)
        QTest.qWait(280)
        self.assertEqual(bar.value(),requested)

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
        self.assertFalse(w.tower_reset_button.isEnabled())
        before=self.panel.draft
        self.panel.reset_tower()
        self.assertEqual(self.panel.draft,before)
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

    def test_preparation_header_and_preview_do_not_jump_during_feedback_frames(self):
        p,w=self.panel,self.window
        self.show_manual_footer()
        rows=(("Dateiname","vasenform_wie_vorlage_120mm.stl"),
              ("Slicer","Anycubic Slicer Next 2.0.0.3"),
              ("Maschinenprofil","Anycubic Kobra 3 V2 0.4 nozzle - (Settings v2)"),
              ("Filamentprofil","PLA - Tecbears - Schwarz (matt)"),
              ("Prozessprofil","PLA - Tecbears - Schwarz (matt)"))
        w.workflow_group.set_split_summary_columns((),rows)
        class Recorder(QObject):
            def eventFilter(inner,widget,event):
                if event.type() in {QEvent.Type.Resize,QEvent.Type.Move,QEvent.Type.Paint}:
                    inner.frames.append((w.workflow_group.header.height(),p.canvas.mapToGlobal(QPoint()).y()))
                return False
        recorder=Recorder(w);recorder.frames=[]
        for widget in (w.workflow_group.header,p.canvas):widget.installEventFilter(recorder)
        for width,height in ((1429,1362),(1429,1394),(1400,1362),(1450,1000),(1250,1394)):
            w.resize(width,height);QTest.qWait(50)
            for label in (p.status_label,p.result_label,p.action_hint):label.clear()
            self.controller.refresh_footer();QTest.qWait(50)
            header=w.workflow_group.header
            self.assertEqual(header.minimumHeight(),header.maximumHeight())
            baseline=(header.height(),p.canvas.mapToGlobal(QPoint()).y())
            recorder.frames=[]
            p.feedback(GeometryError("maximum_diameter_mm",
                "Die vollständige Kurve überschreitet den Maximaldurchmesser."),"points")
            w.workflow_group.set_split_summary_columns((),rows)
            # A stable layout can require no paint at all; request one real
            # frame while still recording every move/resize during feedback.
            p.canvas.update()
            QTest.qWait(750)
            self.assertTrue(recorder.frames)
            self.assertEqual(set(recorder.frames),{baseline})

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
                    p.rows["circle_segments"].set_error("Eine ausführliche Grenzrückmeldung. "*12)
                    for _ in range(4):self.app.processEvents()
                    self.assertEqual(p.canvas.geometry(),rectangle)
                    self.assertEqual(p.canvas.mapToGlobal(QPoint()),position)
                    p.rows["circle_segments"].set_error(None)

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
        self.assertEqual(p.status_label.text(),"")
        self.assertIn("Erreichte Mindest-Layerzeit",p.result_label.text())
        self.assertNotIn("Gemeinsamer Prüfslice",p.result_label.text())
        self.assertNotIn("<br>",p.result_label.text())
        self.assertIs(self.window._last_export_report_result,c.session.export_result)
        self.assertIsNone(self.window.last_export_result)
        self.assertIsNone(self.window._last_exported_preview_identity)

    def test_methods_settings_results_and_reset_independent(self):
        w,p=self.window,self.panel
        original=w.collect_settings()
        p.color_scale_spin.setValue(28)
        p.change_setting("color_reference_time_s",20);p.move("base",30,8)
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
        old_key=p.canvas._spatial_key()
        p.canvas.set_view("side");p.canvas.grab()
        # Give cancellation and preparation of all three surface palettes their
        # own budget, and verify the completed render as well as thread release.
        self._wait_resolution_render(timeout=20)
        self.assertFalse(w.background_job_manager.has_active(JobKind.MANUAL_VIEW))
        self.assertEqual(p.canvas.view,"side")
        self.assertNotEqual(p.canvas._spatial_key(),old_key)
        self.assertEqual(p.canvas._object_render_key,p.canvas._spatial_key())

    def _large_resolution_reference(self):
        import trimesh
        from cooling_tower.preview.mesh_silhouette import build_mesh_silhouette
        mesh=trimesh.creation.icosphere(subdivisions=4,radius=5)
        mesh.apply_translation((5,5,5))
        triangles=mesh.triangles.copy();triangles.setflags(write=False)
        reference=replace(self.controller.reference,object_triangles=triangles,
                          object_silhouette=build_mesh_silhouette(triangles))
        self.panel.canvas.set_reference(reference)
        self.panel.canvas.set_view("free")

    def _wait_resolution_render(self,timeout=5):
        canvas=self.panel.canvas
        deadline=time.monotonic()+timeout
        while (canvas._render_proxy or canvas._render_job or canvas._render_timer.isActive()) and time.monotonic()<deadline:
            self.app.processEvents();time.sleep(.005)
        self.assertFalse(canvas._render_proxy,"Object preview was left pending without a completed render")
        self.assertIsNone(canvas._render_job)
        self.assertFalse(canvas._render_timer.isActive())
        self.assertEqual(canvas._object_render_key,canvas._spatial_key())

    def test_repeated_resolution_render_returns_from_zero_to_same_stage(self):
        self._large_resolution_reference()
        p=self.panel;c=p.canvas
        before=p.draft.artifact_payload()
        seen={}
        for stage in (0,5,0,5,0,1,0,1,0,75,0,75):
            if stage in seen:
                with patch.object(c,"_queue_spatial_render",side_effect=AssertionError("cached resolution queued again")):
                    p.change_setting("object_resolution_percent",stage);c.grab()
                self.assertIs(c._object_cache,seen[stage])
            else:
                p.change_setting("object_resolution_percent",stage);c.grab()
            self._wait_resolution_render(timeout=2)
            seen[stage]=c._object_cache
            self.assertEqual(p.draft.artifact_payload(),before)

    def test_resolution_render_cancels_active_job_and_ignores_stale_result(self):
        from threading import Event
        from PySide6.QtGui import QPicture
        from cooling_tower.gui import manual_view_worker
        self._large_resolution_reference()
        p=self.panel;c=p.canvas
        started,release=Event(),Event()
        self.addCleanup(release.set)
        original=manual_view_worker.render_spatial_object
        def paused(*args,**kwargs):
            if not started.is_set():
                started.set();release.wait(5)
            return original(*args,**kwargs)
        with patch.object(manual_view_worker,"render_spatial_object",side_effect=paused):
            p.change_setting("object_resolution_percent",5);c.grab()
            deadline=time.monotonic()+2
            while not started.is_set() and time.monotonic()<deadline:
                self.app.processEvents();time.sleep(.005)
            self.assertTrue(started.is_set())
            old_job,old_request,old_key=c._render_job,c._view_request_id,c._spatial_key()
            p.change_setting("object_resolution_percent",0);c.grab()
            self.assertTrue(self.window.background_job_manager.job(old_job).cancel_requested)
            self.assertFalse(c._render_proxy)
            p.change_setting("object_resolution_percent",5);c.grab()
            proxy=c._object_cache
            c._spatial_succeeded(old_request,(old_key,QPicture()))
            self.assertIs(c._object_cache,proxy)
            # Consume the pending timer while the cancelled job still owns its
            # thread. Its release must schedule the replacement afterwards.
            c._render_timer.stop();c._start_spatial_render()
            self.assertEqual(c._render_job,old_job)
            release.set()
            self._wait_resolution_render()

    def test_resolution_render_requeues_same_key_when_no_job_or_timer_exists(self):
        self._large_resolution_reference()
        p=self.panel;c=p.canvas
        p.change_setting("object_resolution_percent",5)
        c._render_desired=c._spatial_key();c._render_timer.stop()
        c.grab()
        self.assertTrue(c._render_timer.isActive())
        self._wait_resolution_render()

    def test_colors_changed_during_initial_render_reuse_that_job(self):
        from threading import Event
        from cooling_tower.gui import manual_view_worker
        self._large_resolution_reference()
        p=self.panel;c=p.canvas
        started,release=Event(),Event()
        self.addCleanup(release.set)
        original=manual_view_worker.render_spatial_object
        def paused(*args,**kwargs):
            started.set();release.wait(5)
            return original(*args,**kwargs)
        with patch.object(manual_view_worker,"render_spatial_object",side_effect=paused) as render:
            p.change_setting("object_resolution_percent",5);c.grab()
            deadline=time.monotonic()+2
            while not started.is_set() and time.monotonic()<deadline:
                self.app.processEvents();time.sleep(.005)
            self.assertTrue(started.is_set())
            job=c._render_job
            p.change_setting("critical_layers_enabled",True)
            p.color_range_slider.request_value("green",12);c.grab()
            self.assertEqual(c._render_job,job)
            self.assertFalse(self.window.background_job_manager.job(job).cancel_requested)
            release.set()
            self._wait_resolution_render()
            self.assertEqual(render.call_count,1)
            self.assertEqual(c._object_render_key,c._spatial_key())

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
