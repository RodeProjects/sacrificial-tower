"""Cursor-anchored orthographic zoom, including pan and clamped zoom limits."""
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication
from cooling_tower.gui.widgets.preview_canvas import PreviewCanvas
from cooling_tower.models import BedBounds
from cooling_tower.preview import LineSegment3D, Point3D, PreviewScene
from gui_lifecycle import dispose_test_widget


class PreviewCursorZoomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.canvas = PreviewCanvas()
        self.canvas.resize(900, 650)
        self.points = (Point3D(-20, -10, 0), Point3D(15, 20, 40), Point3D(75, 50, 12))
        self.canvas.set_scene(PreviewScene(
            object_segments=(LineSegment3D(self.points[0], self.points[1]),),
            tower_segments=(LineSegment3D(self.points[1], self.points[2]),),
            bed_bounds=BedBounds(-100, 200, -50, 150), tower_center_xy_mm=(75, 50),
            source_segment_count=1, displayed_segment_count=1, tower_height_mm=40))
        self.canvas.set_navigation_enabled(True)

    def tearDown(self):
        dispose_test_widget(self.canvas)

    def wheel(self, point, delta, *, horizontal=0):
        event = QWheelEvent(point, QPointF(self.canvas.mapToGlobal(point.toPoint())), QPoint(),
            QPoint(horizontal, delta), Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase, False)
        self.canvas.wheelEvent(event)
        return event

    def projected(self):
        return [self.canvas._project(point, self.canvas._fit_parameters()) for point in self.points]

    def test_zoom_scales_about_cursor_after_pan_and_rotation_in_both_fit_modes(self):
        canvas = self.canvas
        for whole_bed in (False, True):
            for yaw, pitch in ((-38, 28), (50, -45), (0, -89)):
                for delta in (120, -120):
                    for anchor in (QPointF(120, 170), QPointF(760, 510)):
                        with self.subTest(whole_bed=whole_bed, yaw=yaw, pitch=pitch, delta=delta, anchor=anchor):
                            canvas.fit_scene() if whole_bed else canvas.fit_objects()
                            canvas.apply_camera_state({"yaw_deg": yaw, "pitch_deg": pitch,
                                "zoom": 2.3, "pan_x": 61.25, "pan_y": -37.5})
                            before = self.projected()
                            camera = canvas.camera_state()
                            event = self.wheel(anchor, delta)
                            ratio = canvas.zoom / camera["zoom"]
                            for old, new in zip(before, self.projected()):
                                expected = anchor + (old-anchor)*ratio
                                self.assertAlmostEqual(new.x(), expected.x(), places=8)
                                self.assertAlmostEqual(new.y(), expected.y(), places=8)
                            self.assertTrue(event.isAccepted())
                            self.assertEqual((canvas.yaw_deg, canvas.pitch_deg), (yaw, pitch))

    def test_world_point_under_cursor_stays_fixed_and_zoom_is_reversible(self):
        canvas = self.canvas
        canvas.apply_camera_state({"zoom": 1.7, "pan_x": 23.5, "pan_y": -18})
        initial = canvas.camera_state()
        cursor = self.projected()[1]
        changed = QSignalSpy(canvas.camera_changed)
        self.wheel(cursor, 120)
        actual = self.projected()[1]
        self.assertAlmostEqual(actual.x(), cursor.x(), places=8)
        self.assertAlmostEqual(actual.y(), cursor.y(), places=8)
        self.wheel(cursor, -120)
        for name, value in initial.items():
            self.assertAlmostEqual(canvas.camera_state()[name], value, places=8)
        self.assertEqual(changed.count(), 2)

    def test_clamped_zoom_uses_actual_factor_and_does_not_pan_at_limits(self):
        canvas = self.canvas
        anchor = QPointF(140, 260)
        for zoom, delta, expected_zoom in ((49, 120, 50), (50, 120, 50), (.052, -120, .05), (.05, -120, .05)):
            with self.subTest(zoom=zoom, delta=delta):
                canvas.apply_camera_state({"zoom": zoom, "pan_x": 74, "pan_y": -33})
                before = self.projected()
                self.wheel(anchor, delta)
                self.assertEqual(canvas.zoom, expected_zoom)
                for old, new in zip(before, self.projected()):
                    expected = anchor + (old-anchor)*(expected_zoom/zoom)
                    self.assertAlmostEqual(new.x(), expected.x(), places=7)
                    self.assertAlmostEqual(new.y(), expected.y(), places=7)
                if zoom == expected_zoom:
                    self.assertEqual((canvas.pan_x, canvas.pan_y), (74, -33))

    def test_locked_navigation_and_horizontal_wheel_do_not_change_camera(self):
        canvas = self.canvas
        initial = canvas.camera_state()
        canvas.set_navigation_enabled(False)
        event = self.wheel(QPointF(110, 140), 120)
        self.assertFalse(event.isAccepted())
        self.assertEqual(canvas.camera_state(), initial)
        canvas.set_navigation_enabled(True)
        changed = QSignalSpy(canvas.camera_changed)
        self.wheel(QPointF(110, 140), 0, horizontal=120)
        self.assertEqual(canvas.camera_state(), initial)
        self.assertEqual(changed.count(), 0)


if __name__ == "__main__":
    unittest.main()
