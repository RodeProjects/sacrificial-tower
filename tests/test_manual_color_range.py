"""Real pointer/keyboard behavior, collisions and scale-only updates."""
import unittest
from dataclasses import replace
from unittest.mock import patch

from PySide6.QtCore import QPoint,QEvent,Qt
from PySide6.QtTest import QTest,QSignalSpy
from PySide6.QtGui import QColor
import test_manual_gui as gui
from cooling_tower.gui.widgets.layer_time_color_controls import LayerTimeColorControls
from cooling_tower.gui.widgets.layer_range_canvas import LayerRangeCanvas


class ManualColorRangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app,cls.font,cls.font_id=gui.preview_test_application()

    @classmethod
    def tearDownClass(cls):gui.restore_preview_test_application(cls.app,cls.font,cls.font_id)

    def setUp(self):
        self.controls=LayerTimeColorControls()
        self.controls.resize(440,220);self.controls.show()
        self.controls.color_enabled_checkbox.setChecked(True)
        self.app.processEvents()
        self.slider=self.controls.range_slider
        self.addCleanup(gui.dispose_test_widget,self.controls)

    def enter_scale(self,text):
        spin=self.controls.scale_spin
        spin.setFocus();spin.selectAll();QTest.keyClicks(spin,text)
        QTest.keyClick(spin,Qt.Key.Key_Return);self.app.processEvents()

    def press_handle(self,kind):
        handle=self.slider.red_handle if kind=="red" else self.slider.green_handle
        origin=handle.mapToGlobal(handle.rect().center())
        start=self.slider.threshold(kind)
        QTest.mousePress(handle,Qt.MouseButton.LeftButton,pos=handle.rect().center())
        return handle,origin,start

    def move_handle(self,drag,time):
        handle,origin,start=drag
        delta=round((time-start)*self.slider.track_rect().width()/self.slider.maximum_time)
        point=handle.mapFromGlobal(origin+QPoint(delta,0))
        QTest.mouseMove(handle,point);self.app.processEvents()
        return handle.mapFromGlobal(origin+QPoint(delta,0))

    def test_red_pointer_snap_has_hysteresis_visible_feedback_and_releases_freely(self):
        slider=self.slider;slider.set_original_minimum(7.24)
        drag=self.press_handle("red")
        step=slider.maximum_time/slider.track_rect().width()
        self.move_handle(drag,7.24-4*step)
        self.assertEqual(slider.red_time,7.2)
        self.assertEqual(slider.snapped_kind,"red")
        self.assertFalse(slider.minimum_marker.isHidden())
        self.assertTrue(slider.minimum_marker.snapped)
        self.assertEqual(slider.minimum_marker.grab().toImage().pixelColor(6,7),QColor("#1769aa"))
        self.assertAlmostEqual(slider.minimum_marker.x()+slider.minimum_marker.width()/2,slider.x_for_time(7.24),delta=1)
        self.move_handle(drag,7.24+8*step)
        self.assertEqual(slider.red_time,7.2)
        point=self.move_handle(drag,7.24+13*step)
        self.assertGreater(slider.red_time,7.2)
        self.assertIsNone(slider.snapped_kind)
        QTest.mouseRelease(drag[0],Qt.MouseButton.LeftButton,pos=point)
        self.assertFalse(slider.minimum_marker.snapped)
        self.assertTrue(self.controls.notice_label.isHidden())

    def test_both_grips_snap_to_rounded_minimum_without_changing_the_measurement(self):
        for kind,minimum,expected in (("red",.364,.4),("red",7.25,7.3),("green",7.24,7.2)):
            with self.subTest(kind=kind,minimum=minimum):
                self.slider.set_values(6,10,14);self.slider.set_original_minimum(minimum)
                drag=self.press_handle(kind);point=self.move_handle(drag,minimum)
                self.assertEqual(self.slider.threshold(kind),expected)
                self.assertEqual(self.slider.original_minimum_time,minimum)
                self.assertEqual(self.slider.snapped_kind,kind)
                QTest.mouseRelease(drag[0],Qt.MouseButton.LeftButton,pos=point)
                self.assertEqual(self.slider.threshold(kind),expected)
                self.assertIsNone(self.slider.snapped_kind)
        self.assertIn("7,24 s",self.slider.minimum_marker.toolTip())
        self.assertIn("Rastpunkt für Farbgrenzen: 7,2 s",self.slider.minimum_marker.toolTip())

    def test_snapping_never_crosses_other_grip_or_green_minimum(self):
        for kind,minimum,red,green,expected in (("red",7.24,6,7.1,7.1),
                ("green",7.24,7.3,10,7.3),("green",2.364,1,10,3)):
            with self.subTest(kind=kind,minimum=minimum):
                self.slider.set_values(red,green,14);self.slider.set_original_minimum(minimum)
                drag=self.press_handle(kind);point=self.move_handle(drag,minimum)
                self.assertEqual(self.slider.threshold(kind),expected)
                self.assertIsNone(self.slider.snapped_kind)
                self.assertLessEqual(self.slider.red_time,self.slider.green_time)
                self.assertGreaterEqual(self.slider.green_time,3)
                QTest.mouseRelease(drag[0],Qt.MouseButton.LeftButton,pos=point)
        self.assertTrue(self.controls.notice_label.isHidden())

    def test_click_keyboard_loading_and_scaling_do_not_snap(self):
        slider=self.slider;slider.set_original_minimum(7.24);slider.set_values(7.1,10,14)
        drag=self.press_handle("red")
        QTest.mouseMove(drag[0],drag[0].mapFromGlobal(drag[1]))
        QTest.mouseRelease(drag[0],Qt.MouseButton.LeftButton,pos=drag[0].mapFromGlobal(drag[1]))
        self.assertEqual(slider.red_time,7.1)
        for expected in (7.2,7.3):
            QTest.keyClick(slider.red_handle,Qt.Key.Key_Right)
            self.assertEqual(slider.red_time,expected)
            self.assertIsNone(slider.snapped_kind)
        slider.request_value("red",7.1)
        self.assertEqual(slider.red_time,7.1)
        slider.set_original_minimum(7.12);self.enter_scale("20")
        self.assertEqual(slider.red_time,7.1)
        self.assertIsNone(slider.snapped_kind)

    def test_moving_away_from_a_nearby_minimum_never_pulls_the_grip_back(self):
        slider=self.slider;slider.set_original_minimum(7.24);slider.set_values(7.1,10,14)
        drag=self.press_handle("red")
        point=self.move_handle(drag,7.0)
        self.assertEqual(slider.red_time,7.0)
        self.assertIsNone(slider.snapped_kind)
        QTest.mouseRelease(drag[0],Qt.MouseButton.LeftButton,pos=point)
        self.assertEqual(slider.red_time,7.0)
        self.assertIsNone(slider.snapped_kind)

    def test_unavailable_minimum_does_not_snap_and_context_changes_clear_feedback(self):
        slider=self.slider
        for minimum in (None,15):
            slider.set_values(6,10,14);slider.set_original_minimum(minimum)
            drag=self.press_handle("red");point=self.move_handle(drag,7.24)
            self.assertIsNone(slider.snapped_kind)
            QTest.mouseRelease(drag[0],Qt.MouseButton.LeftButton,pos=point)
        slider.set_values(6,10,14);slider.set_original_minimum(7.24)
        drag=self.press_handle("red");point=self.move_handle(drag,7.24)
        self.assertEqual(slider.snapped_kind,"red")
        self.controls.setEnabled(False)
        self.assertIsNone(slider.snapped_kind)
        self.assertEqual(slider.red_time,7.2)
        self.controls.setEnabled(True)
        QTest.mouseRelease(drag[0],Qt.MouseButton.LeftButton,pos=point)
        slider.set_values(6,10,14)
        drag=self.press_handle("red");self.move_handle(drag,7.24)
        self.assertEqual(slider.snapped_kind,"red")
        slider.set_values(3,3,3)
        self.assertIsNone(slider.snapped_kind)
        QTest.mouseRelease(drag[0],Qt.MouseButton.LeftButton,pos=drag[0].rect().center())

    def test_requested_title_and_only_one_numeric_input(self):
        from PySide6.QtWidgets import QAbstractSpinBox
        self.assertEqual(self.controls.color_enabled_checkbox.text(),"Layerzeit-Einfärbungen aktivieren")
        self.assertEqual(self.controls.findChildren(QAbstractSpinBox),[self.controls.scale_spin])
        self.assertTrue(self.controls.notice_label.isHidden())

    def test_scale_changes_ratios_without_changing_either_color_time(self):
        slider=self.slider;times=QSignalSpy(self.controls.times_changed)
        before=slider.x_for_time(6)-slider.track_rect().left()
        self.enter_scale("28")
        self.assertEqual((slider.red_time,slider.green_time,slider.maximum_time),(6,10,28))
        self.assertAlmostEqual(slider.x_for_time(6)-slider.track_rect().left(),before/2)
        self.assertEqual(times.count(),0)

    def test_scale_clamps_and_reports_bounds_and_bad_text(self):
        self.enter_scale("2")
        self.assertEqual(self.controls.scale_spin.value(),3)
        self.assertIn("Min. Skalenende = 3 s",self.controls.notice_label.text())
        self.assertEqual((self.slider.red_time,self.slider.green_time),(3,3))
        self.enter_scale("20.5")
        self.assertEqual(self.slider.maximum_time,20.5)
        self.assertIn("20,5",self.controls.scale_spin.text())
        self.assertTrue(self.controls.notice_label.isHidden())
        self.controls.scale_spin.setFocus();self.controls.scale_spin.selectAll()
        QTest.keyClicks(self.controls.scale_spin,"abc");self.app.processEvents()
        self.assertFalse(self.controls.notice_label.isHidden())
        self.controls.notice_timer.timeout.emit()
        self.assertTrue(self.controls.notice_label.isHidden())

    def test_bounds_cannot_cross_or_escape_track(self):
        slider=self.slider
        for kind,value,expected in (("red",11,10),("red",-1,0),("green",40,14),("green",1,3)):
            slider.request_value(kind,value)
            self.assertEqual(slider.threshold(kind),expected)
            self.assertLessEqual(slider.red_time,slider.green_time)
            self.assertTrue(self.controls.notice_label.isHidden())
        slider.request_value("red",1)
        self.assertTrue(self.controls.notice_label.isHidden())

    def test_original_minimum_arrow_is_below_bar_at_actual_time_without_editing(self):
        slider=self.slider;before=slider.grab().toImage()
        slider.set_original_minimum(7.2);self.app.processEvents()
        marker=slider.minimum_marker
        self.assertFalse(marker.isHidden());self.assertTrue(slider.minimum_information.isHidden())
        self.assertGreater(marker.y(),slider.track_rect().bottom())
        self.assertAlmostEqual(marker.x()+marker.width()/2,slider.x_for_time(7.2),delta=1)
        self.assertEqual(marker.toolTip(),"Min. Layerzeit der STL: 7,2 s\nRastpunkt für Farbgrenzen: 7,2 s")
        state=(slider.red_time,slider.green_time,slider.maximum_time)
        QTest.mousePress(marker,Qt.MouseButton.LeftButton,pos=marker.rect().center())
        QTest.mouseMove(marker,marker.rect().center()+QPoint(30,0))
        QTest.mouseRelease(marker,Qt.MouseButton.LeftButton,pos=marker.rect().center())
        self.assertEqual((slider.red_time,slider.green_time,slider.maximum_time),state)
        # The entire quantitative color bar retains its existing colors.
        from cooling_tower.gui.widgets.hint_popover import hide_window_hint
        hide_window_hint(marker)
        after=slider.grab().toImage();track=slider.track_rect()
        for time in (1,8,12):
            x,y=round(slider.x_for_time(time)),round(track.center().y())
            self.assertEqual(after.pixelColor(x,y),before.pixelColor(x,y))

    def test_minimum_information_replaces_outside_or_colliding_arrows_below_all_values(self):
        slider=self.slider
        for minimum in (0,6,10,14,15,1e308):
            with self.subTest(minimum=minimum):
                slider.set_original_minimum(minimum);self.app.processEvents()
                self.assertTrue(slider.minimum_marker.isHidden())
                self.assertFalse(slider.minimum_information.isHidden())
                for item in (slider.red_handle,slider.green_handle,slider.red_label,slider.green_label,slider.zero_label,slider.end_spin):
                    self.assertGreater(slider.minimum_information.y(),item.geometry().bottom())
                self.assertLess(slider.minimum_information.geometry().bottom(),slider.height())
        slider.set_original_minimum(7.2)
        self.assertFalse(slider.minimum_marker.isHidden());self.assertTrue(slider.minimum_information.isHidden())

    def test_short_layer_time_uses_available_space_next_to_the_zero_guide(self):
        self.controls.setFixedWidth(320)
        self.slider.set_original_minimum(.364);self.app.processEvents()
        self.assertFalse(self.slider.minimum_marker.isHidden())
        self.assertTrue(self.slider.minimum_information.isHidden())
        self.assertAlmostEqual(self.slider.minimum_marker.geometry().center().x(),self.slider.x_for_time(.364),delta=1)
        self.controls.setFixedWidth(220);self.app.processEvents()
        self.assertTrue(self.slider.minimum_marker.isHidden())
        self.assertEqual(self.slider.minimum_information.text(),"Min. Layerzeit der STL: 0,364 s")
        self.assertFalse(self.slider.minimum_information.isHidden())
        self.controls.setFixedWidth(320);self.app.processEvents()
        self.assertFalse(self.slider.minimum_marker.isHidden())
        self.assertTrue(self.slider.minimum_information.isHidden())

    def test_minimum_fallback_updates_on_resize_scale_and_grip_changes(self):
        slider=self.slider;slider.set_original_minimum(7.2)
        self.assertFalse(slider.minimum_marker.isHidden())
        self.controls.setFixedWidth(220);self.app.processEvents()
        self.assertTrue(slider.minimum_marker.isHidden());self.assertFalse(slider.minimum_information.isHidden())
        self.controls.setFixedWidth(440);self.app.processEvents()
        self.assertFalse(slider.minimum_marker.isHidden())
        slider.request_value("red",7.2)
        self.assertTrue(slider.minimum_marker.isHidden())
        slider.request_value("red",6)
        self.assertFalse(slider.minimum_marker.isHidden())
        self.enter_scale("5")
        self.assertTrue(slider.minimum_marker.isHidden());self.assertIn("7,2 s",slider.minimum_information.text())
        self.enter_scale("14")
        slider.set_values(6,10,14)
        self.assertFalse(slider.minimum_marker.isHidden());self.assertTrue(slider.minimum_information.isHidden())

    def test_unknown_minimum_is_hidden_and_hover_closes_when_arrow_no_longer_fits(self):
        slider=self.slider
        for value in (None,-1,True,"7",float("nan"),float("inf")):
            slider.set_original_minimum(value)
            self.assertTrue(slider.minimum_marker.isHidden());self.assertTrue(slider.minimum_information.isHidden())
        slider.set_original_minimum(7.2)
        spy=QSignalSpy(slider.minimum_marker.hint_shown)
        self.app.sendEvent(slider.minimum_marker,QEvent(QEvent.Type.Enter))
        self.assertEqual(spy.count(),1);self.assertIn("7,2 s",spy.at(0)[0])
        slider.request_value("red",7.2)
        self.assertTrue(self.controls._bounded_hint_popover.isHidden())

    def test_handle_limits_are_quiet_and_leave_box_error_feedback_until_its_timeout(self):
        self.enter_scale("61")
        notice=self.controls.notice_label.text()
        self.slider.green_handle.setFocus()
        for _ in range(4):QTest.keyClick(self.slider.green_handle,Qt.Key.Key_End)
        self.assertEqual(self.slider.green_time,60)
        self.assertEqual(self.controls.notice_label.text(),notice)
        self.controls.notice_timer.timeout.emit()
        QTest.keyClick(self.slider.green_handle,Qt.Key.Key_Right)
        self.assertEqual(self.slider.green_time,60)
        self.assertTrue(self.controls.notice_label.isHidden())

    def test_close_grab_points_and_labels_never_overlap_or_escape(self):
        for width in (220,320,440):
            self.controls.setFixedWidth(width);self.app.processEvents()
            for red,green,end in ((6,6.1,14),(0,3,3600),(9.9,10,10),(29.9,30,3600),(3,3,3),(10,10,14),(60,60,60)):
                self.slider.set_values(red,green,end,limit=max(60,end));self.app.processEvents()
                a,b=self.slider.red_handle.geometry(),self.slider.green_handle.geometry()
                self.assertFalse(a.intersects(b))
                self.assertGreaterEqual(a.left(),0);self.assertLess(b.right(),self.slider.width())
                labels=(self.slider.zero_label,self.slider.red_label,self.slider.green_label,self.slider.end_spin)
                for i,first in enumerate(labels):
                    for second in labels[i+1:]:self.assertFalse(first.geometry().intersects(second.geometry()))
                for i,first in enumerate(self.slider.zone_labels):
                    for second in self.slider.zone_labels[i+1:]:
                        if first.isVisible() and second.isVisible():
                            self.assertFalse(first.geometry().intersects(second.geometry()))

    def test_only_colliding_axis_endpoints_move_below_fixed_threshold_values(self):
        slider=self.slider
        normal={item:item.pos() for item in (slider.zero_label,slider.end_spin,slider.red_label,slider.green_label)}
        normal_height=slider.height()
        for red,green,left_moves,right_moves in ((0,10,True,False),(6,14,False,True),(0,14,True,True)):
            slider.set_values(red,green,14);self.app.processEvents()
            for item in (slider.red_label,slider.green_label):self.assertEqual(item.y(),normal[item].y())
            for item,moves in ((slider.zero_label,left_moves),(slider.end_spin,right_moves)):
                self.assertEqual(item.x(),normal[item].x())
                if moves:self.assertGreater(item.y(),max(slider.red_label.geometry().bottom(),slider.green_label.geometry().bottom()))
                else:self.assertEqual(item.y(),normal[item].y())
            for item in (slider.zero_label,slider.end_spin,slider.red_label,slider.green_label):
                self.assertGreaterEqual(item.y(),0)
                self.assertLess(item.geometry().bottom(),slider.height())
        slider.set_values(6,10,14);self.app.processEvents()
        self.assertEqual(slider.height(),normal_height)
        for item,position in normal.items():self.assertEqual(item.pos(),position)

    def test_outer_guides_are_longer_and_reach_shifted_axis_values(self):
        slider=self.slider
        def has_guide_at(image,x,y):
            self.assertNotEqual(image.pixelColor(round(x),round(y)),image.pixelColor(round(x)+2,round(y)))
        image=slider.grab().toImage();track=slider.track_rect()
        for x in (track.left(),track.right()):has_guide_at(image,x,track.bottom()+16)
        slider.set_values(0,14,14);self.app.processEvents();image=slider.grab().toImage()
        for item,x in ((slider.zero_label,track.left()),(slider.end_spin,track.right())):
            has_guide_at(image,x,item.y()-5)

    def test_scale_clips_only_green_when_red_is_already_below_new_end(self):
        self.slider.set_values(6.04,10.04,14)
        self.enter_scale("10")
        self.assertEqual((self.slider.red_time,self.slider.green_time,self.slider.maximum_time),(6.04,10,10))

    def test_lower_scale_end_moves_affected_bounds_and_leaves_them_ordered(self):
        changes=QSignalSpy(self.controls.scale_changed)
        for end,red,green in ((8,6,8),(6,6,6),(3,3,3)):
            self.slider.set_values(6,10,14)
            self.enter_scale(str(end))
            self.assertEqual((self.slider.red_time,self.slider.green_time,self.slider.maximum_time),(red,green,end))
            self.assertTrue(self.controls.notice_label.isHidden())
        self.assertEqual(changes.count(),3)
        self.assertEqual(changes.at(2),[3.,3.,0.])

    def test_mouse_step_at_smallest_scale_end_reports_three_seconds(self):
        self.enter_scale("3")
        self.controls.scale_spin.stepDown()
        self.assertEqual(self.slider.maximum_time,3)
        self.assertIn("Min. Skalenende = 3 s",self.controls.notice_label.text())

    def test_zone_ends_are_fixed_and_transition_tracks_the_fade_center(self):
        for red,green,end in ((6,10,14),(3,8,14),(0,3,3600),(2.9,3,3)):
            self.slider.set_values(red,green,end,limit=max(60,end));self.app.processEvents()
            left,transition,right=self.slider.zone_labels
            self.assertAlmostEqual(left.x(),self.slider.track_rect().left(),delta=1)
            self.assertAlmostEqual(right.x()+right.width(),self.slider.track_rect().right(),delta=1)
            if transition.isVisible():
                center=(self.slider.x_for_time(red)+self.slider.x_for_time(green))/2
                self.assertAlmostEqual(transition.x()+transition.width()/2,center,delta=1)
            self.assertEqual(self.slider.zero_label.text(),"0 s")

    def test_drag_close_handle_starts_without_jump_then_moves_correct_boundary(self):
        self.slider.set_values(6,6.1,14);self.app.processEvents()
        handle=self.slider.red_handle
        center=handle.rect().center()
        QTest.mousePress(handle,Qt.MouseButton.LeftButton,pos=center)
        QTest.mouseMove(handle,center)
        self.assertEqual(self.slider.red_time,6)
        QTest.mouseMove(handle,center-QPoint(30,0))
        QTest.mouseRelease(handle,Qt.MouseButton.LeftButton,pos=handle.rect().center())
        self.assertLess(self.slider.red_time,6)
        self.assertEqual(self.slider.green_time,6.1)

    def test_hover_changes_point_and_its_marker_together(self):
        slider=self.slider;handle=slider.red_handle
        handle.clearFocus()
        self.app.sendEvent(handle,QEvent(QEvent.Type.Leave));before=slider.grab().toImage()
        self.app.sendEvent(handle,QEvent(QEvent.Type.Enter));after=slider.grab().toImage()
        x=round(slider.x_for_time(slider.red_time));y=round(slider.track_rect().center().y())
        self.assertNotEqual(before.pixelColor(x,y),after.pixelColor(x,y))
        self.assertEqual(after.pixelColor(x,y),QColor("#1769aa"))
        self.assertTrue(handle.hovered)

    def test_keyboard_changes_by_tenth_and_track_click_does_not_move_points(self):
        self.slider.red_handle.setFocus()
        QTest.keyClick(self.slider.red_handle,Qt.Key.Key_Right)
        self.assertEqual(self.slider.red_time,6.1)
        QTest.mouseClick(self.slider,Qt.MouseButton.LeftButton,pos=self.slider.track_rect().center().toPoint())
        self.assertEqual(self.slider.red_time,6.1)

    def test_scale_default_limit_clamps_typed_and_step_attempts_to_sixty(self):
        self.assertEqual(self.controls.scale_spin.maximum(),60)
        self.enter_scale("61")
        self.assertEqual(self.slider.maximum_time,60)
        self.assertIn("Max. Skalenende = 60 s",self.controls.notice_label.text())
        self.controls.clear_notice();self.controls.scale_spin.stepUp()
        self.assertEqual(self.slider.maximum_time,60)
        self.assertIn("Max. Skalenende = 60 s",self.controls.notice_label.text())

    def test_extended_object_limit_survives_dragging_and_keyboard_edits(self):
        self.slider.set_values(6,10,14,limit=123.4)
        self.enter_scale("150")
        self.assertEqual(self.slider.maximum_time,123.4)
        self.assertIn("Max. Skalenende = 123,4 s",self.controls.notice_label.text())
        self.slider.request_value("red",7)
        self.assertEqual(self.controls.scale_spin.maximum(),123.4)
        self.assertEqual(self.slider.maximum_time,123.4)

    def test_gradient_matches_model_and_no_white_handle_inside_bar(self):
        image=self.slider.grab().toImage();y=round(self.slider.track_rect().center().y())
        for time in (1,8,12):
            expected=LayerRangeCanvas.layer_time_color(10,6,time)
            actual=image.pixelColor(round(self.slider.x_for_time(time)),y)
            self.assertLessEqual(max(abs(a-b) for a,b in zip(expected.getRgb(),actual.getRgb())),2)
        for handle in (self.slider.red_handle,self.slider.green_handle):
            self.assertGreater(handle.geometry().top(),self.slider.track_rect().bottom())


class ManualColorRangeIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app,cls.font,cls.font_id=gui.preview_test_application()

    @classmethod
    def tearDownClass(cls):gui.restore_preview_test_application(cls.app,cls.font,cls.font_id)

    def setUp(self):gui.ManualGuiTests.setUp(self)

    def test_original_minimum_snap_updates_preview_settings_and_is_one_undo_action(self):
        from cooling_tower.gui.widgets import manual_canvas
        p=self.panel
        layers=tuple(replace(layer,total_time_s=7.24 if i==0 else 20)
                     for i,layer in enumerate(self.reference.context.layers))
        reference=replace(self.reference,context=replace(self.reference.context,layers=layers))
        p.initialize(reference);p.color_enabled_checkbox.click();p.canvas.grab()
        before=p.settings;artifact=p.draft.artifact_payload()
        slider=p.color_range_slider;handle=slider.red_handle
        origin=handle.mapToGlobal(handle.rect().center())
        delta=round((7.24-slider.red_time)*slider.track_rect().width()/slider.maximum_time)
        with patch.object(manual_canvas,"tessellate",side_effect=AssertionError("snap rebuilt tower geometry")):
            QTest.mousePress(handle,Qt.MouseButton.LeftButton,pos=handle.rect().center())
            point=handle.mapFromGlobal(origin+QPoint(delta,0))
            QTest.mouseMove(handle,point);p.canvas.grab()
            self.assertEqual(p.settings.color_red_time_s,7.2)
            self.assertEqual(slider.snapped_kind,"red")
            self.assertTrue(slider.minimum_marker.snapped)
            self.assertFalse(slider.minimum_marker.isHidden())
            QTest.mouseRelease(handle,Qt.MouseButton.LeftButton,pos=handle.mapFromGlobal(origin+QPoint(delta,0)))
        self.assertEqual(p.draft.artifact_payload(),artifact)
        self.assertIsNone(slider.snapped_kind)
        p.undo();self.assertEqual(p.settings,before)

    def test_scale_edit_reuses_object_tower_and_placement(self):
        from cooling_tower.gui.widgets import manual_canvas
        p=self.panel;c=p.canvas;p.color_enabled_checkbox.click();c.grab()
        cache=c._object_cache;rings=c._rings;placement=c._placement;artifact=p.draft.artifact_payload()
        with patch.object(manual_canvas,"tessellate",side_effect=AssertionError("tower rebuilt")), \
             patch.object(c,"_render_object",side_effect=AssertionError("original rebuilt")):
            p.color_scale_spin.setValue(28);c.grab()
        self.assertEqual(p.settings.color_scale_max_time_s,28)
        self.assertIs(c._object_cache,cache);self.assertIs(c._rings,rings);self.assertIs(c._placement,placement)
        self.assertEqual(p.draft.artifact_payload(),artifact)

    def test_drag_is_one_undo_action_and_resets_keep_their_scope(self):
        p=self.panel;p.color_enabled_checkbox.click();slider=p.color_range_slider
        start=p.settings;handle=slider.red_handle;center=handle.rect().center()
        QTest.mousePress(handle,Qt.MouseButton.LeftButton,pos=center)
        for delta in (-10,-20,-30):QTest.mouseMove(handle,center+QPoint(delta,0))
        QTest.mouseRelease(handle,Qt.MouseButton.LeftButton,pos=handle.rect().center())
        self.assertNotEqual(p.settings,start)
        p.undo();self.assertEqual(p.settings,start)
        p.color_scale_spin.setValue(28);p.reset_tower()
        self.assertEqual(p.settings.color_scale_max_time_s,28)
        p.reset_all();self.assertEqual(p.settings.color_scale_max_time_s,14)

    def test_shrinking_scale_commits_times_atomically_and_undo_restores_all_three(self):
        from cooling_tower.gui.widgets import manual_canvas
        p=self.panel;c=p.canvas;p.color_enabled_checkbox.click();c.grab()
        before=p.settings;rings=c._rings;placement=c._placement;artifact=p.draft.artifact_payload()
        with patch.object(manual_canvas,"tessellate",side_effect=AssertionError("tower rebuilt")):
            p.color_scale_spin.setValue(3);c.grab()
        self.assertEqual((p.settings.color_red_time_s,p.settings.color_reference_time_s,p.settings.color_scale_max_time_s),(3,3,3))
        self.assertIs(c._rings,rings);self.assertIs(c._placement,placement)
        self.assertEqual(p.draft.artifact_payload(),artifact)
        p.undo();self.assertEqual(p.settings,before)
        self.assertEqual((p.color_range_slider.red_time,p.color_range_slider.green_time,p.color_scale_spin.value()),(5,9,14))

    def test_increasing_scale_preserves_historical_subtenth_fade_precision(self):
        p=self.panel
        settings=replace(p.settings,color_reference_time_s=10.0123456789,color_deficit_time_s=.0123456789)
        p.initialize(self.reference,settings)
        p.color_scale_spin.setValue(28)
        self.assertEqual(p.settings.color_reference_time_s,settings.color_reference_time_s)
        self.assertEqual(p.settings.color_deficit_time_s,settings.color_deficit_time_s)

    def reference_with_longest_layer(self,maximum):
        layers=tuple(replace(layer,total_time_s=maximum if i==0 else 2.)
                     for i,layer in enumerate(self.reference.context.layers))
        context=replace(self.reference.context,key=self.reference.context.key+str(maximum),layers=layers)
        return replace(self.reference,context=context)

    def test_object_limit_uses_the_actual_longest_layer_and_does_not_auto_expand_scale(self):
        p=self.panel
        for actual,limit in ((59,60),(60,60),(60.09,60),(123.49,123.4),(7200.5,7200.5)):
            with self.subTest(actual=actual):
                p.initialize(self.reference_with_longest_layer(actual),replace(p.settings,color_scale_max_time_s=14))
                self.assertEqual(p.color_scale_spin.maximum(),limit)
                self.assertEqual(p.settings.color_scale_max_time_s,14)
                p.color_scale_spin.setValue(limit+10)
                self.assertEqual(p.settings.color_scale_max_time_s,limit)
                self.assertEqual(p.color_range_slider.maximum_time,limit)
                self.assertEqual((p.settings.color_red_time_s,p.settings.color_reference_time_s),(5,9))

    def test_object_change_clamps_loaded_preferences_and_keeps_undo_in_range(self):
        p=self.panel
        p.initialize(self.reference_with_longest_layer(120),replace(p.settings,color_scale_max_time_s=5000))
        self.assertEqual(p.settings.color_scale_max_time_s,120)
        p.color_scale_spin.setValue(80);p.undo()
        self.assertEqual(p.settings.color_scale_max_time_s,120)
        p.initialize(self.reference,p.settings)
        self.assertEqual(p.color_scale_spin.maximum(),60)
        self.assertEqual(p.settings.color_scale_max_time_s,60)
        p.change_setting("color_scale_max_time_s",5000)
        self.assertEqual(p.settings.color_scale_max_time_s,60)
        p.color_scale_spin.setValue(20);p.undo()
        self.assertEqual(p.settings.color_scale_max_time_s,60)
        self.assertEqual(p.color_range_slider.maximum_time,60)

    def test_green_and_scale_share_sixty_or_the_original_maximum_after_object_change(self):
        p=self.panel
        for actual,limit in ((30,60),(123.49,123.4),(7200.5,7200.5)):
            with self.subTest(actual=actual):
                p.initialize(self.reference_with_longest_layer(actual))
                p.color_scale_spin.setValue(limit)
                p.color_range_slider.request_value("green",limit+10)
                self.assertEqual(p.settings.color_reference_time_s,limit)
                self.assertEqual(p.settings.color_scale_max_time_s,limit)
                self.assertTrue(p.layer_time_controls.notice_label.isHidden())
        p.color_range_slider.request_value("red",100)
        p.initialize(self.reference,p.settings)
        self.assertEqual(p.settings.color_reference_time_s,60)
        self.assertEqual(p.settings.color_scale_max_time_s,60)
        self.assertEqual(p.settings.color_red_time_s,60)

    def test_joined_boundaries_have_two_operable_points_and_restore_transition(self):
        slider=self.panel.color_range_slider;p=self.panel;p.color_enabled_checkbox.click()
        slider.request_value("red",10)
        self.assertEqual(p.settings.color_deficit_time_s,0)
        self.assertEqual((slider.red_time,slider.green_time),(9,9))
        self.assertTrue(slider.zone_labels[1].isHidden())
        self.assertFalse(slider.red_handle.geometry().intersects(slider.green_handle.geometry()))
        slider.green_handle.setFocus();QTest.keyClick(slider.green_handle,Qt.Key.Key_Right)
        self.assertEqual((slider.red_time,slider.green_time),(9,9.1))
        self.assertFalse(slider.zone_labels[1].isHidden())
        QTest.keyClick(slider.green_handle,Qt.Key.Key_Left)
        self.assertEqual((slider.red_time,slider.green_time),(9,9))
        self.assertTrue(slider.zone_labels[1].isHidden())
        handle=slider.red_handle;center=handle.rect().center()
        QTest.mousePress(handle,Qt.MouseButton.LeftButton,pos=center)
        QTest.mouseMove(handle,center-QPoint(30,0))
        QTest.mouseRelease(handle,Qt.MouseButton.LeftButton,pos=handle.rect().center())
        self.assertLess(slider.red_time,slider.green_time)
        self.assertFalse(slider.zone_labels[1].isHidden())

    def test_joined_boundaries_draw_a_hard_color_split_and_shared_hover_marker(self):
        slider=self.panel.color_range_slider;self.panel.color_enabled_checkbox.click()
        slider.request_value("red",10)
        image=slider.grab().toImage();y=round(slider.track_rect().center().y())
        self.assertEqual(image.pixelColor(round(slider.x_for_time(8)),y),QColor(LayerRangeCanvas.CRITICAL_COLOR))
        self.assertEqual(image.pixelColor(round(slider.x_for_time(11)),y),QColor(LayerRangeCanvas.OBJECT_COLOR))
        for handle in (slider.red_handle,slider.green_handle):
            handle.setFocus();image=slider.grab().toImage()
            self.assertEqual(image.pixelColor(round(slider.x_for_time(9)),y),QColor("#1769aa"))

    def test_marker_uses_actual_original_minimum_and_reuses_it_during_color_edits(self):
        from cooling_tower.gui import manual_panel
        p=self.panel
        reference=self.reference_with_longest_layer(90)
        layers=tuple(replace(layer,total_time_s=7.2 if i==1 else 20) for i,layer in enumerate(reference.context.layers))
        reference=replace(reference,context=replace(reference.context,layers=layers))
        p.initialize(reference)
        self.assertEqual(p.color_range_slider.original_minimum_time,7.2)
        original=p.draft.artifact_payload()
        with patch.object(manual_panel,"minimum_original_layer_time",side_effect=AssertionError("layer times rescanned")):
            p.color_range_slider.request_value("red",7.2)
            self.assertFalse(p.color_range_slider.minimum_information.isHidden())
            p.color_range_slider.request_value("red",6)
            p.color_scale_spin.setValue(20)
        self.assertEqual(p.color_range_slider.original_minimum_time,7.2)
        self.assertEqual(p.draft.artifact_payload(),original)
        p.initialize(self.reference_with_longest_layer(90))
        self.assertEqual(p.color_range_slider.original_minimum_time,2)
