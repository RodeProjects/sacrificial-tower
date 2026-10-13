import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from PySide6.QtCore import QPoint,QPointF,Qt,QObject,QEvent
from PySide6.QtTest import QTest
from PySide6.QtGui import QImage,QPainter
from PySide6.QtWidgets import QWidget
from cooling_tower.gui.manual_panel import ManualGenerationPanel
from cooling_tower.gui.design_tokens import COLORS
from test_manual_generation import create_fixture
from test_manual_gui import preview_test_application,restore_preview_test_application


class ManualPointEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app,cls.font,cls.font_id=preview_test_application()

    @classmethod
    def tearDownClass(cls):restore_preview_test_application(cls.app,cls.font,cls.font_id)

    def setUp(self):
        _,_,reference,_,_=create_fixture(self,joint=True,count=200)
        self.panel=ManualGenerationPanel();self.panel.initialize(reference)
        self.panel.resize(1400,900);self.panel.show();self.app.processEvents()
        self.addCleanup(self.panel.close)

    def type_value(self,row,text):
        row.editor.setFocus();row.editor.selectAll();QTest.keyClicks(row.editor,text)

    def test_each_handle_exposes_only_its_editable_coordinates_and_reset_defaults(self):
        p=self.panel;p.insert(20);free=p.selected
        mapping={"foot":("foot_diameter_mm",),"base":("base_diameter_mm",),
            "foot_height":("foot_height_mm",),"top":("height_mm",),"top_width":("top_diameter_mm",),
            "minimum_diameter_mm":("minimum_diameter_mm",),"maximum_diameter_mm":("maximum_diameter_mm",),
            "maximum_foot_diameter_mm":("maximum_foot_diameter_mm",),free:("point_diameter_mm","point_height_mm"),
            "control:0:1":("foot_diameter_mm",)}
        for identity,names in mapping.items():
            with self.subTest(identity=identity):
                p.select(identity);p.canvas.grab()
                self.assertEqual(tuple(p.point_editor.rows),names)
                caption=p.canvas.selected_handle_text()
                self.assertEqual(p.point_editor.caption.text(),caption.partition(":")[2].strip() if caption.startswith("Layer:") else "")
                for name,row in p.point_editor.rows.items():self.assertEqual(row.field.default,p.default_value(name))

    def test_live_validation_enter_confirmation_preserves_editor_and_exact_value(self):
        p=self.panel;p.insert(20)
        row=p.point_editor.rows["point_diameter_mm"];old=p.draft
        self.type_value(row,"1")
        self.assertTrue(row.invalid);self.assertIn(COLORS["error"],row.editor.styleSheet())
        QTest.keyClick(row.editor,Qt.Key.Key_Return)
        self.assertEqual(p.draft,old);self.assertEqual(row.pulse_color.name(),COLORS["error"])
        self.type_value(row,"12,345678")
        self.assertFalse(row.invalid);self.assertEqual(p.draft,old)
        with patch.object(p,"generate_requested") as generate:
            QTest.keyClick(row.editor,Qt.Key.Key_Return);generate.emit.assert_not_called()
        self.assertIs(p.point_editor.rows["point_diameter_mm"],row)
        self.assertAlmostEqual(p.draft.points[2].position.diameter_mm,12.345678)
        self.assertEqual(row.editor.text(),"12,35")
        self.assertEqual(row.pulse_color.name(),COLORS["success"])
        self.assertIn(COLORS["success"],row.editor.styleSheet())
        row.animation.setCurrentTime(450);self.assertAlmostEqual(row.amount,.5)
        row.animation.setCurrentTime(550);self.assertEqual(row.amount,0)
        self.assertTrue(p.point_editor.isVisible())
        self.assertIsNone(row.field.default);self.assertTrue(row.reset.isHidden())
        self.assertTrue(p.rows["point_diameter_mm"].reset_button.isHidden())
        old=p.draft;row.reset_value();p.reset_value("point_diameter_mm")
        self.assertEqual(p.draft,old)

    def test_invalid_heights_and_nonfinite_text_never_mutate_and_empty_restores_previous(self):
        p=self.panel;p.insert(20);row=p.point_editor.rows["point_height_mm"];old=p.draft
        for text in ("1000","0","nan","inf","abc"):
            self.type_value(row,text);self.assertTrue(row.invalid)
            QTest.keyClick(row.editor,Qt.Key.Key_Return);self.assertEqual(p.draft,old)
        self.type_value(row,"20,071234");QTest.keyClick(row.editor,Qt.Key.Key_Return)
        self.assertAlmostEqual(p.draft.points[2].position.z_mm,20.071234)
        old=p.draft
        row.editor.selectAll();QTest.keyClick(row.editor,Qt.Key.Key_Backspace)
        QTest.keyClick(row.editor,Qt.Key.Key_Return)
        self.assertEqual(p.draft,old);self.assertEqual(row.editor.text(),"20,07")

    def test_same_or_empty_control_submission_does_not_activate_straight_curve(self):
        p=self.panel;p.insert(20);p.canvas._revealed_control_anchor=p.selected;p.select("control:1:2")
        row=p.point_editor.rows["point_height_mm"];old=p.draft
        self.assertFalse(old.curves[1].curved)
        QTest.keyClick(row.editor,Qt.Key.Key_Return);self.assertEqual(p.draft,old)
        row.editor.selectAll();QTest.keyClick(row.editor,Qt.Key.Key_Backspace)
        QTest.keyClick(row.editor,Qt.Key.Key_Return);self.assertEqual(p.draft,old)

    def test_dirty_input_survives_other_changes_and_busy_disables_commit(self):
        p=self.panel;p.select("base");row=p.point_editor.rows["base_diameter_mm"]
        self.type_value(row,"12,3");p.change_setting("circle_segments",48)
        self.assertEqual(row.editor.text(),"12,3");old=p.draft
        p.set_busy(True);self.assertFalse(row.editor.isEnabled())
        self.assertFalse(p._apply_point_value("base_diameter_mm",12.3));self.assertEqual(p.draft,old)
        p.set_busy(False);QTest.keyClick(row.editor,Qt.Key.Key_Return)
        self.assertEqual(p.draft.base_diameter_mm,12.3)

    def test_initial_values_do_not_remain_red_when_reference_preparation_finishes(self):
        p=self.panel;reference=p.reference
        p.set_busy(True);p.initialize(reference);p.set_busy(False);p.select("base")
        row=p.point_editor.rows["base_diameter_mm"]
        self.assertFalse(row.invalid)
        self.assertNotIn(COLORS["error"],row.editor.styleSheet())
        text=row.editor.text();p.select("foot");p.select("base")
        self.assertEqual(p.point_editor.rows["base_diameter_mm"].editor.text(),text)
        self.assertFalse(p.point_editor.rows["base_diameter_mm"].invalid)

    def test_fields_share_tight_content_width_grow_shrink_and_keep_column_alignment(self):
        p=self.panel;p.insert(20);editor=p.point_editor
        diameter=editor.rows["point_diameter_mm"];height=editor.rows["point_height_mm"]
        original=p.draft
        self.type_value(diameter,"10,00");self.type_value(height,"100,00")
        self.app.processEvents()
        wide=height.editor.width()
        self.assertEqual(diameter.editor.width(),wide)
        self.assertEqual(wide,max(row.editor.required_width() for row in editor.rows.values()))
        self.assertEqual(diameter.editor.mapTo(editor,QPoint()).x(),height.editor.mapTo(editor,QPoint()).x())
        self.assertEqual(diameter.reset.mapTo(editor,QPoint()).x(),height.reset.mapTo(editor,QPoint()).x())
        self.assertTrue(height.reset.isHidden());self.assertTrue(diameter.reset.isHidden())
        self.type_value(height,"10,00");self.app.processEvents()
        self.assertLess(height.editor.width(),wide)
        self.assertEqual(diameter.editor.width(),height.editor.width())
        self.assertEqual(p.draft,original)
        self.assertAlmostEqual(editor.caption.x(),diameter.editor.mapTo(editor,QPoint()).x()+4,delta=1)
        self.assertEqual(editor.caption_name.x(),diameter.label.mapTo(editor,QPoint()).x())

    def test_unit_is_inside_each_field_and_empty_confirmation_restores_value_and_width(self):
        p=self.panel;p.select("base");editor=p.point_editor;row=editor.rows["base_diameter_mm"]
        self.app.processEvents();old=p.draft;width=row.editor.width()
        self.assertIs(row.editor.unit.parentWidget(),row.editor)
        self.assertEqual(row.editor.unit.text(),"mm")
        self.assertTrue(row.editor.rect().contains(row.editor.unit.geometry()))
        self.assertNotIn("mm",row.editor.text())
        row.editor.selectAll();QTest.keyClick(row.editor,Qt.Key.Key_Backspace)
        self.assertLess(row.editor.width(),width)
        QTest.keyClick(row.editor,Qt.Key.Key_Return)
        self.assertEqual(p.draft,old);self.assertEqual(row.editor.width(),width)

    def test_external_changes_and_reset_resize_all_fields_together(self):
        p=self.panel;p.insert(20);editor=p.point_editor
        p.move(p.selected,12.345678,9)
        row=editor.rows["point_diameter_mm"];height=editor.rows["point_height_mm"]
        self.app.processEvents();wide=row.editor.width()
        self.assertEqual(row.editor.width(),height.editor.width())
        p.move(p.selected,9,9);self.app.processEvents()
        self.assertLess(row.editor.width(),wide)
        self.assertEqual(row.editor.width(),height.editor.width())

    def test_two_decimal_display_keeps_precise_values_valid_on_unchanged_enter_and_reset(self):
        from dataclasses import replace
        p=self.panel
        p.initialize(p.reference,replace(p.settings,minimum_diameter_mm=5.004321));p.select("base")
        row=p.point_editor.rows["base_diameter_mm"]
        self.assertEqual(row.editor.text(),"5,00")
        self.assertFalse(row.invalid)
        old=p.draft
        QTest.keyClick(row.editor,Qt.Key.Key_Return)
        self.assertEqual(p.draft,old)
        self.assertFalse(row.invalid)
        p.insert(20);identity=p.selected
        p.move(identity,21.060426,20.071234)
        diameter=p.point_editor.rows["point_diameter_mm"];height=p.point_editor.rows["point_height_mm"]
        self.assertEqual(diameter.editor.text(),"21,06")
        self.assertEqual(height.editor.text(),"20,07")
        old=p.draft
        QTest.keyClick(diameter.editor,Qt.Key.Key_Return)
        self.assertEqual(p.draft,old)
        self.assertIsNone(diameter.field.default);self.assertTrue(diameter.reset.isHidden())
        self.assertFalse(diameter.invalid)

    def test_initial_editor_has_no_selection_and_inserted_points_have_no_reset(self):
        p=self.panel
        self.assertEqual((p.selected,p.canvas.selected),("",""))
        self.assertTrue(p.point_editor.isHidden())
        self.assertFalse(any(name.startswith("control:") for name,_,_ in p.canvas.handles()))
        p.insert(20);identity=p.selected;p.move(identity,20,22)
        for name,row in p.point_editor.rows.items():
            self.assertIsNone(row.field.default);self.assertTrue(row.reset.isHidden())
            self.assertTrue(p.rows[name].reset_button.isHidden())
        p.select("base")
        self.assertFalse(p.point_editor.rows["base_diameter_mm"].reset.isHidden())
        self.assertFalse(p.rows["point_diameter_mm"].reset_button.isHidden())

    def test_control_selection_keeps_owner_fields_and_position_until_obstructed(self):
        p=self.panel;c=p.canvas;p.insert(20);identity=p.selected
        p.move(identity,20,20);c._revealed_control_anchor=identity;p._sync();c.grab()
        editor=p.point_editor;rows=dict(editor.rows);box=editor.geometry()
        p.select("control:1:2");c.grab()
        self.assertEqual(editor.identity,identity);self.assertEqual(editor.geometry(),box)
        self.assertIs(editor.rows["point_height_mm"],rows["point_height_mm"])
        p.move_control(1,2,18,16);c.grab()
        self.assertEqual(editor.geometry(),box)
        self.assertEqual(editor.rows["point_height_mm"].editor.text(),"20,00")
        row=editor.rows["point_diameter_mm"];self.type_value(row,"22,00")
        QTest.keyClick(row.editor,Qt.Key.Key_Return)
        self.assertEqual(next(point.position.diameter_mm for point in p.draft.points if point.identity==identity),22)
        p.select("control:0:2");self.assertEqual(editor.identity,"base")
        self.assertEqual(tuple(editor.rows),("base_diameter_mm",))
        p.select(f"control:{len(p.draft.curves)-1}:2")
        self.assertEqual(editor.identity,"top_width");self.assertEqual(tuple(editor.rows),("top_diameter_mm",))

    def test_info_box_moves_only_if_a_handle_enters_its_clearance(self):
        p=self.panel;c=p.canvas;p.insert(20);identity=p.selected
        c._revealed_control_anchor=identity;p.select("control:1:2");c.grab()
        editor=p.point_editor;before=editor.geometry();original=c.handles()
        blocked=QPointF(before.left()+5,before.center().y())
        with patch.object(c,"handles",return_value=[(name,blocked if name=="control:1:2" else pos,kind) for name,pos,kind in original]):
            editor.reposition();moved=editor.geometry()
            self.assertNotEqual(moved,before)
            editor.reposition();self.assertEqual(editor.geometry(),moved)
        editor.reposition();self.assertEqual(editor.geometry(),moved)

    def test_height_strokes_use_longer_gradient_tethers_and_restricted_vertical_drag(self):
        p=self.panel;c=p.canvas
        for identity in ("top","foot_height"):
            start,end=c.height_handle_geometry(identity)
            self.assertEqual(end.x()-start.x(),33);self.assertEqual(end.y(),start.y())
            handle=next(pos for name,pos,_ in c.handles() if name==identity)
            self.assertEqual(handle,end);self.assertEqual(c.hit_test(handle),identity)
            pen=c._limit_guide_pen(start,end);brush=pen.brush();gradient=brush.gradient()
            self.assertLess(gradient.stops()[0][1].lightness(),gradient.stops()[-1][1].lightness())
            width=p.draft.points[-1 if identity=="top" else 1].position.diameter_mm
            p.move(identity,100,30 if identity=="top" else 9)
            self.assertEqual(p.draft.points[-1 if identity=="top" else 1].position.diameter_mm,width)
            c.grab()

    def test_insertion_hover_covers_both_contours_and_both_sides_with_shared_distance(self):
        p=self.panel;c=p.canvas;old=p.draft
        for view in ("side","front"):
            c.set_view(view)
            for side in (-1,1):
                contour=c.profile_to_screen(side*p.draft.radius_at_z(20),20)
                for offset in (-32,32):
                    mouse=contour+QPointF(offset,0);offered=c.insertion_at(mouse)
                    self.assertIsNotNone(offered)
                    self.assertAlmostEqual(offered[0].y(),contour.y())
                    self.assertAlmostEqual(offered[0].x(),c.profile_to_screen(p.draft.radius_at_z(20),20).x())
                    self.assertAlmostEqual(offered[1],20)
                self.assertIsNone(c.insertion_at(contour+QPointF(side*34,0)))
        self.assertEqual(p.draft,old)

    def test_insertion_hover_excludes_foot_nearby_nodes_busy_and_invalid_context(self):
        from cooling_tower.manual.geometry import GeometryError
        p=self.panel;c=p.canvas
        for z in (4,8.01,p.draft.height_mm-.01):
            pos=c.profile_to_screen(-p.draft.radius_at_z(z),z)
            self.assertIsNone(c.insertion_at(pos))
        p.insert(20)
        self.assertIsNone(c.insertion_at(c.profile_to_screen(-p.draft.radius_at_z(20.05),20.05)))
        pos=c.profile_to_screen(-p.draft.radius_at_z(25),25);old=p.draft
        with patch.object(p.reference.context.__class__,"validate",side_effect=GeometryError("technical_bed","blocked")):
            self.assertIsNone(c.insertion_at(pos))
        self.assertEqual(p.draft,old)
        p.set_busy(True);self.assertIsNone(c.insertion_at(pos));p.set_busy(False)
        for view in ("top","bottom","free"):
            c.set_view(view);self.assertIsNone(c.insertion_at(pos))

    def test_hover_is_subtle_nonmutating_and_double_click_inserts_the_offered_point(self):
        p=self.panel;c=p.canvas;old=p.draft
        contour=c.profile_to_screen(p.draft.radius_at_z(20),20)
        left=c.profile_to_screen(-p.draft.radius_at_z(20),20)
        mouse=(left-QPointF(25,0)).toPoint()
        QTest.mouseMove(c,mouse);self.assertIsNotNone(c._insertion_preview)
        self.assertAlmostEqual(c._insertion_preview[0].x(),contour.x())
        self.assertEqual(p.draft,old)
        offered_height=c._insertion_preview[1]
        QTest.mouseDClick(c,Qt.MouseButton.LeftButton,pos=mouse)
        self.assertEqual(len(p.draft.points),4)
        self.assertAlmostEqual(p.draft.points[2].position.z_mm,offered_height)
        self.assertIsNone(c._insertion_preview)

    def test_foot_contour_is_purple_and_foot_handles_remain_separate(self):
        from PySide6.QtGui import QColor
        p=self.panel;c=p.canvas;image=c.grab().toImage()
        identities={name for name,_,_ in c.handles()}
        self.assertTrue({"foot","foot_height"}<=identities)
        target=QColor(c.COLORS["foot"])
        position=c.profile_to_screen(p.draft.radius_at_z(4),4).toPoint()
        distance=lambda color:sum(abs(a-b) for a,b in zip(color.getRgb()[:3],target.getRgb()[:3]))
        self.assertLess(min(distance(image.pixelColor(position.x()+dx,position.y()+dy))
            for dx in range(-2,3) for dy in range(-2,3)),40)

    def shift_drag_move(self,position,shift=True):
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication
        c=self.panel.canvas
        event=QMouseEvent(QEvent.Type.MouseMove,QPointF(position),QPointF(c.mapToGlobal(position.toPoint())),
                         Qt.MouseButton.NoButton,Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.ShiftModifier if shift else Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(c,event)

    def test_shift_locks_exact_original_coordinate_for_free_points_and_controls(self):
        from cooling_tower.manual.geometry import ManualSettings
        p=self.panel;normal=p.reference
        for identity_kind in ("point","control"):
            for delta in (QPointF(12,3),QPointF(2,-12)):
                with self.subTest(identity_kind=identity_kind,delta=delta):
                    p.initialize(normal,ManualSettings())
                    p.insert(20);identity=p.selected;p.move(identity,21.060426,20.071234)
                    p.segment_combo.setCurrentIndex(1)
                    if identity_kind=="control":identity="control:2:1"
                    p.select(identity);c=p.canvas
                    handle=next(pos for name,pos,_ in c.handles() if name==identity)
                    start=QPointF(handle.toPoint())
                    old_radius=c._horizontal_handle_radius(identity);old_height=c._vertical_handle_height(identity)
                    QTest.mousePress(c,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.ShiftModifier,pos=start.toPoint())
                    self.shift_drag_move(start+delta)
                    if abs(delta.x())>abs(delta.y()):
                        self.assertEqual(c._vertical_handle_height(identity),old_height)
                        self.assertNotEqual(c._horizontal_handle_radius(identity),old_radius)
                    else:
                        self.assertEqual(c._horizontal_handle_radius(identity),old_radius)
                        self.assertNotEqual(c._vertical_handle_height(identity),old_height)
                    QTest.mouseRelease(c,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.ShiftModifier,pos=(start+delta).toPoint())
                    self.assertIsNone(c.constrained_drag_origin())

    def test_shift_axis_changes_relative_to_drag_start_and_release_restores_two_axes(self):
        p=self.panel;p.insert(20);identity=p.selected;p.move(identity,20.060426,20.071234)
        c=p.canvas;start=next(pos.toPoint() for name,pos,_ in c.handles() if name==identity)
        radius=c._horizontal_handle_radius(identity);height=c._vertical_handle_height(identity)
        QTest.mousePress(c,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.ShiftModifier,pos=start)
        self.shift_drag_move(QPointF(start)+QPointF(2,-12))
        self.assertEqual(c._horizontal_handle_radius(identity),radius)
        self.shift_drag_move(QPointF(start)+QPointF(20,-4))
        self.assertEqual(c._vertical_handle_height(identity),height)
        self.assertNotEqual(c._horizontal_handle_radius(identity),radius)
        self.shift_drag_move(QPointF(start)+QPointF(16,-10),shift=False)
        self.assertNotEqual(c._vertical_handle_height(identity),height)
        self.assertNotEqual(c._horizontal_handle_radius(identity),radius)
        QTest.mouseRelease(c,Qt.MouseButton.LeftButton,pos=start+QPoint(16,-10))

    def test_shift_locked_coordinate_survives_width_limit_and_never_changes_fixed_grip_axes(self):
        p=self.panel;p.insert(20);identity=p.selected;p.move(identity,20,20.071234)
        c=p.canvas;start=next(pos.toPoint() for name,pos,_ in c.handles() if name==identity)
        height=c._vertical_handle_height(identity)
        QTest.mousePress(c,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.ShiftModifier,pos=start)
        self.shift_drag_move(QPointF(start)+QPointF(1000,-5))
        self.assertEqual(c._vertical_handle_height(identity),height)
        self.assertLessEqual(c._horizontal_handle_radius(identity)*2,p.settings.maximum_diameter_mm)
        self.assertGreaterEqual(c._horizontal_handle_radius(identity)*2,p.settings.maximum_diameter_mm-.1)
        QTest.mouseRelease(c,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.ShiftModifier,pos=start+QPoint(1000,-5))
        p.select("top_width");start=next(pos.toPoint() for name,pos,_ in c.handles() if name=="top_width")
        height=p.draft.height_mm
        QTest.mousePress(c,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.ShiftModifier,pos=start)
        self.shift_drag_move(QPointF(start)+QPointF(5,15))
        self.assertEqual(p.draft.height_mm,height);self.assertIsNone(c._drag_axis)
        QTest.mouseRelease(c,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.ShiftModifier,pos=start+QPoint(5,15))

    def test_empty_click_deselects_without_changes_and_navigation_drag_preserves_selection(self):
        p=self.panel;c=p.canvas;p.insert(20);free=p.selected
        c._revealed_control_anchor=free;c.grab();old=p.draft;cache=c._object_cache
        blank=QPoint(65,85)
        QTest.mousePress(c,Qt.MouseButton.LeftButton,pos=blank)
        QTest.mouseMove(c,blank+QPoint(12,8));QTest.mouseRelease(c,Qt.MouseButton.LeftButton,pos=blank+QPoint(12,8))
        self.assertEqual(p.selected,free)
        QTest.mouseClick(c,Qt.MouseButton.LeftButton,pos=blank)
        self.assertEqual((p.selected,c.selected),("",""));self.assertFalse(p.point_editor.isVisible())
        self.assertFalse(any(name.startswith("control:") for name,_,_ in c.handles()))
        self.assertEqual(p.draft,old);self.assertIs(c._object_cache,cache)

    def test_editor_stays_right_of_nearby_grips_caption_level_and_fits_viewport(self):
        p=self.panel;c=p.canvas;p.insert(20);c._revealed_control_anchor=p.selected
        c.grab();editor=p.point_editor
        anchor=next(pos for name,pos,_ in c.handles() if name==p.selected)
        self.assertLess(editor.caption.y(),editor.fields_scroll.y())
        self.assertAlmostEqual(editor.geometry().bottom(),anchor.y()+17,delta=1)
        for _,position,_ in c.handles():
            if editor.y()-9<=position.y()<=editor.geometry().bottom()+9:
                self.assertGreater(editor.x(),position.x()+8)
        c.pan+=QPointF(0,-10000);c.grab()
        self.assertGreaterEqual(editor.y(),0);self.assertLessEqual(editor.geometry().bottom(),c.height())
        self.assertTrue(editor.isVisible())
        c.pan=QPointF();c.fit_scene();p.select("top");self.app.processEvents();c.grab()
        row=editor.rows["height_mm"]
        self.assertTrue(row.editor.isVisible())
        self.assertGreaterEqual(editor.y()+editor.fields_scroll.y(),c.view_controls.geometry().bottom())
        self.assertLessEqual(editor.geometry().bottom(),c.height())

    def test_group_background_round_corners_unique_values_and_readable_reset_icon(self):
        p=self.panel;p.insert(20);self.app.processEvents();editor=p.point_editor
        self.assertTrue(editor.caption.isVisible());self.assertEqual(editor.caption_name.text(),"Layer:")
        image=QImage(editor.size(),QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent);painter=QPainter(image)
        editor.render(painter,QPoint(),renderFlags=QWidget.RenderFlag.DrawChildren);painter.end()
        self.assertEqual(image.pixelColor(0,0).alpha(),0)
        self.assertGreater(image.pixelColor(3,15).alpha(),235)
        for row in editor.rows.values():
            self.assertFalse(row.reset.icon().isNull());self.assertEqual(row.reset.text(),"")
            icon=row.reset.icon().pixmap(14,14).toImage()
            self.assertTrue(any(icon.pixelColor(x,y).alpha()>100 for x in range(icon.width()) for y in range(icon.height())))
        p.select("base");self.app.processEvents()
        self.assertFalse(editor.caption.isVisible());self.assertEqual(editor.caption.text(),"")
        self.assertEqual(tuple(editor.rows),("base_diameter_mm",))

    def test_bezier_limits_show_body_foot_minimum_and_height_guides_with_normal_fade(self):
        p=self.panel;c=p.canvas
        for index,n,diameter,z,setting in ((1,1,300,15,"maximum_diameter_mm"),
                (0,1,750,2,"maximum_foot_diameter_mm"),(1,1,-300,15,"minimum_diameter_mm"),
                (0,1,2,2,"minimum_diameter_mm"),(0,2,2,6,"minimum_diameter_mm")):
            p.reset_all();p._control_from_canvas(index,n,diameter,z)
            self.assertIn(setting,c._width_limit_settings)
            self.assertEqual(c._width_limit_opacity,1)
            c._width_limit_animation.setCurrentTime(450);self.assertAlmostEqual(c._width_limit_opacity,.5)
            c._width_limit_animation.setCurrentTime(550);self.assertFalse(c._width_limit_settings)
        p.reset_all();p._control_from_canvas(0,1,20,100)
        self.assertTrue(c._control_height_limits)

    def test_fixed_foot_controls_stop_at_minimum_diameter_and_show_both_guides(self):
        p=self.panel;c=p.canvas
        for view in ("side","front"):
            for n in (1,2):
                with self.subTest(view=view,control=n):
                    p.reset_all();c.set_view(view)
                    control=getattr(p.draft.curves[0],f"control{n}")
                    with patch.object(c,"horizontal_drag_snaps",return_value=True):
                        p._control_from_canvas(0,n,2,control.z_mm)
                    self.assertAlmostEqual(getattr(p.draft.curves[0],f"control{n}").diameter_mm,p.settings.minimum_diameter_mm)
                    self.assertGreaterEqual(min(p.draft.curves[0].radius_extrema())*2,p.settings.minimum_diameter_mm-1e-8)
                    self.assertEqual(c._width_limit_settings,("minimum_diameter_mm",))
                    self.assertEqual(c._width_limit_opacity,1)
                    left=c.width_limit_guide_geometry(left=True)[0]
                    right=c.width_limit_guide_geometry()[0]
                    self.assertAlmostEqual((left.x()+right.x())/2,c.profile_to_screen(0,0).x())
                    c._width_limit_animation.setCurrentTime(550)
                    self.assertFalse(c._width_limit_settings)
                    with patch.object(c,"horizontal_drag_snaps",return_value=True):
                        p._control_from_canvas(0,n,1,control.z_mm)
                    self.assertEqual(c._width_limit_opacity,1)

    def test_mouse_drag_of_both_foot_controls_stops_at_minimum(self):
        p=self.panel;c=p.canvas
        for view in ("side","front"):
            for n in (1,2):
                with self.subTest(view=view,control=n):
                    p.reset_all();c.set_view(view);p.select(f"control:0:{n}")
                    start=next(point.toPoint() for identity,point,_ in c.handles() if identity==p.selected)
                    QTest.mousePress(c,Qt.MouseButton.LeftButton,pos=start)
                    self.assertEqual(c._drag[1],f"control:0:{n}")
                    target=start-QPoint(60,0)
                    QTest.mouseMove(c,target)
                    QTest.mouseRelease(c,Qt.MouseButton.LeftButton,pos=target)
                    self.assertAlmostEqual(getattr(p.draft.curves[0],f"control{n}").diameter_mm,p.settings.minimum_diameter_mm)
                    self.assertEqual(c._width_limit_settings,("minimum_diameter_mm",))

    def test_coupled_bezier_attempt_shows_both_violated_widths(self):
        p=self.panel;c=p.canvas;p.insert(20);p.move(p.selected,20,20)
        p.smooth_checkbox.setChecked(True)
        p._control_from_canvas(1,2,200,17)
        self.assertEqual(set(c._width_limit_settings),{"minimum_diameter_mm","maximum_diameter_mm"})

    def test_unchanged_point_box_does_not_keep_repainting_the_preview(self):
        class PaintCounter(QObject):
            count=0
            def eventFilter(self,watched,event):
                if event.type()==QEvent.Type.Paint:self.count+=1
                return False
        p=self.panel;p.insert(20);QTest.qWait(80)
        counter=PaintCounter();p.canvas.installEventFilter(counter)
        QTest.qWait(150)
        self.assertLessEqual(counter.count,1)


if __name__=="__main__":unittest.main()
