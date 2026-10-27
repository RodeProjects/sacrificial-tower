from dataclasses import replace
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QLineF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from cooling_tower.gui.widgets.preview_canvas import PreviewCanvas
from cooling_tower.gui.widgets.preview_layer_context import LowerLayerFrames
from cooling_tower.models import BedBounds
from cooling_tower.preview import LineSegment3D, Point3D, PreviewScene


def rectangle(x, y, width, z):
    points = tuple(Point3D(x+dx, y+dy, z) for dx, dy in ((0, 0), (width, 0), (width, width), (0, width)))
    return tuple(LineSegment3D(p, points[(i+1)%4]) for i, p in enumerate(points))


class LayerContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def scene(self):
        model = tuple(segment for z in range(1, 121) for segment in rectangle(80, 80, 10, z*.2))
        tower = tuple(segment for z in range(1, 121) for segment in rectangle(30, 130, 6, z*.2))
        return PreviewScene(model, tower, BedBounds(0, 220, 0, 220), (33, 133), len(model), len(model)+len(tower), 24,
            layer_z_mm=tuple(i*.2 for i in range(1, 121)))

    def test_raster_context_contains_only_layers_below_the_selection_and_cache_is_bounded(self):
        segments = tuple(LineSegment3D(Point3D(10, z*10, z), Point3D(70, z*10, z)) for z in range(1, 9))
        lines = tuple(QLineF(s.start.x, s.start.y, s.end.x, s.end.y) for s in segments)
        context = LowerLayerFrames(100, 100, 1, ((segments, (lines,), "#67b7c7", 1, None),))
        self.assertIsNone(context.before(1))
        image = context.before(3).toImage()
        self.assertGreater(image.pixelColor(40, 10).alpha(), 0)
        self.assertGreater(image.pixelColor(40, 20).alpha(), 0)
        self.assertEqual(image.pixelColor(40, 30).alpha(), 0)
        for z in (7, 4, 8, 5, 3, 6, 9):
            context.before(z)
        self.assertLessEqual(len(context.frames), context.maximum_frames)
        same = context.before(9)
        self.assertIs(context.before(9), same)

    def test_layer_changes_reuse_projected_context_and_click_restores_normal_scene(self):
        canvas = PreviewCanvas()
        canvas.set_layer_context_enabled(True)
        canvas.set_navigation_default(True)
        canvas.resize(700, 500)
        canvas.set_scene(self.scene())
        canvas.show()
        canvas.grab()
        lower = canvas._lower_layer_frames
        with patch.object(canvas, "_line_blocks", wraps=canvas._line_blocks) as projected:
            for layer in (20, 40, 60, 80, 100):
                canvas.set_layer_height(layer*.2)
                frame = canvas._prepare_line_frame()
                self.assertIsNotNone(frame.lower_layers)
                self.assertIs(canvas._lower_layer_frames, lower)
            # Only selected-layer blocks are projected; complete source arrays
            # are retained in the shared context from the normal scene.
            self.assertTrue(all(len(call.args[0]) < 50 for call in projected.call_args_list))
        with patch.object(canvas, "_line_blocks", wraps=canvas._line_blocks) as projected:
            QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.rect().center())
            self.assertIsNone(canvas._layer_z)
            self.assertIsNone(canvas._prepare_line_frame().lower_layers)
            self.assertEqual(projected.call_count, 0)
        canvas.close()

    def test_lower_travels_use_print_layer_indices_instead_of_lifted_endpoint_height(self):
        segments = tuple(LineSegment3D(Point3D(10, y, z), Point3D(70, y, z))
            for y, z in ((10, 1.6), (20, 1.8), (30, .2)))
        lines = tuple(QLineF(10, y, 70, y) for y in (10, 20, 30))
        context = LowerLayerFrames(80, 80, 1, ((segments, (lines,), "#bc98f4", 1, None, (.2, .4, .6)),))
        image = context.before(.4).toImage()
        self.assertGreater(image.pixelColor(40, 10).alpha(), 0)
        self.assertEqual(image.pixelColor(40, 20).alpha(), 0)
        self.assertEqual(image.pixelColor(40, 30).alpha(), 0)

    def test_sampled_context_uses_matching_heights_and_discards_invalid_route_layers(self):
        segments = tuple(LineSegment3D(Point3D(10, 10+i*10, 5), Point3D(70, 10+i*10, 5))
            for i in range(5))
        lines = tuple(QLineF(10, y, 70, y) for y in (10, 30, 50))
        context = LowerLayerFrames(80, 80, 1, (
            (segments, (lines,), "#bc98f4", 1, 3, (.2, .4, float("inf"), .8, 1.0)),))
        self.assertEqual(context.levels, [.2, 1.0])
        image = context.before(.6).toImage()
        self.assertGreater(image.pixelColor(40, 10).alpha(), 0)
        self.assertEqual(image.pixelColor(40, 30).alpha(), 0)
        self.assertEqual(image.pixelColor(40, 50).alpha(), 0)

    def test_cumulative_travels_reuse_projection_while_layer_and_navigation_stay_selected(self):
        canvas = PreviewCanvas()
        canvas.set_layer_context_enabled(True)
        canvas.set_layer_selection_persistent(True)
        canvas.set_navigation_default(True)
        scene = self.scene()
        travels = tuple(LineSegment3D(Point3D(80, 80, z+.6), Point3D(30, 130, z+.6)) for z in scene.layer_z_mm)
        scene = replace(scene, wait_travel_segments=travels, wait_travel_layer_indices=tuple(range(120)))
        canvas.set_scene(scene)
        canvas.set_wait_travel_visible(True)
        canvas.set_cumulative_travel_visible(True)
        canvas.resize(700, 500)
        canvas.show()
        canvas.grab()
        lower = canvas._lower_layer_frames
        with patch.object(canvas, "_line_blocks", wraps=canvas._line_blocks) as projected:
            for layer in (20, 40, 60, 80):
                canvas.set_layer_height(layer*.2)
                frame = canvas._prepare_line_frame()
                self.assertIsNotNone(frame.lower_layers)
                self.assertIs(canvas._lower_layer_frames, lower)
                self.assertEqual(sum(len(block) for block in frame.wait_travel_blocks), 1)
            self.assertTrue(all(len(call.args[0]) < 50 for call in projected.call_args_list))
        self.assertEqual(len(lower.sources), 4)
        self.assertEqual(set(lower.sources[-1][0]), set(scene.layer_z_mm))
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.rect().center())
        self.assertEqual(canvas._layer_z, 16)
        self.assertTrue(canvas._cumulative_travel)
        canvas.close()

    def test_three_quarter_yaw_maximizes_side_by_side_separation_and_follows_geometry(self):
        canvas = PreviewCanvas()
        scene = self.scene()
        canvas.set_scene(scene)
        def score(angle, scene):
            from math import cos, sin, radians
            c, s = cos(radians(angle)), sin(radians(angle))
            a = [p.x*c-p.y*s for line in scene.object_segments for p in (line.start, line.end)]
            b = [p.x*c-p.y*s for line in scene.tower_segments for p in (line.start, line.end)]
            gap = max(min(b)-max(a), min(a)-max(b))
            return gap/(max(max(a), max(b))-min(min(a), min(b)))
        yaw = canvas.separated_yaw()
        self.assertGreater(score(yaw, scene), score(-38, scene)+.2)
        self.assertGreaterEqual(score(yaw, scene)+.001, max(score(angle, scene) for angle in range(0, 180, 3)))
        shifted = replace(scene, tower_segments=tuple(rectangle(130, 30, 6, 1)), tower_center_xy_mm=(133, 33))
        canvas.set_scene(shifted)
        self.assertNotAlmostEqual(canvas.separated_yaw(), yaw, delta=10)
        canvas.close()


if __name__ == "__main__":
    unittest.main()
