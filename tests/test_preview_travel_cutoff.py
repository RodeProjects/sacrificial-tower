from dataclasses import replace
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QLineF
from PySide6.QtWidgets import QApplication

from cooling_tower.gui.widgets.preview_canvas import PreviewCanvas
from cooling_tower.models import BedBounds
from cooling_tower.preview import LineSegment3D, Point3D, PreviewScene
from gui_lifecycle import dispose_test_widget


class PreviewTravelCutoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def canvas(self, *, context=False):
        canvas = PreviewCanvas()
        self.addCleanup(dispose_test_widget, canvas)
        canvas.resize(700, 500)
        canvas.set_layer_context_enabled(context)
        routes = tuple(LineSegment3D(Point3D(10, y, z), Point3D(40, y, z))
            for y, z in ((20, 1.6), (40, 1.8), (60, .1), (80, .2)))
        tower_routes = tuple(LineSegment3D(Point3D(80, s.start.y, s.start.z),
            Point3D(110, s.end.y, s.end.z)) for s in routes)
        canvas.set_scene(PreviewScene((), (), BedBounds(0, 140, 0, 100), (100, 90), 0, 0, .8,
            wait_travel_segments=routes, tower_travel_segments=tower_routes,
            wait_travel_layer_indices=(0, 1, 2, 3), tower_travel_layer_indices=(0, 1, 2, 3),
            layer_z_mm=(.2, .4, .6, .8)))
        canvas.yaw_deg, canvas.pitch_deg = 0, 45
        canvas.set_travel_visible(True)
        canvas.set_all_travel_visible(True)
        return canvas

    def test_all_routes_stop_at_owning_layer_with_and_without_layer_indices(self):
        for indexed in (True, False):
            with self.subTest(indexed=indexed):
                canvas = self.canvas()
                routes = canvas.scene.wait_travel_segments
                if not indexed:
                    routes = tuple(LineSegment3D(Point3D(10, s.start.y, z), Point3D(40, s.end.y, z))
                        for s, z in zip(routes, canvas.scene.layer_z_mm))
                    canvas.set_scene(replace(canvas.scene, wait_travel_segments=routes,
                        wait_travel_layer_indices=()))
                for layer in (3, 1, 2, 4):
                    canvas.set_layer_height(canvas.scene.layer_z_mm[layer-1])
                    frame = canvas._prepare_line_frame()
                    expected = tuple(QLineF(canvas._project(s.start, canvas._fit_parameters()),
                        canvas._project(s.end, canvas._fit_parameters())) for s in routes[:layer])
                    self.assertEqual(tuple(line for block in frame.wait_travel_blocks for line in block), expected)
                canvas.set_layer_height(None)
                self.assertEqual(sum(map(len, canvas._prepare_line_frame().wait_travel_blocks)), 4)

    def test_all_routes_render_only_selected_and_lower_layers_and_reuse_projection(self):
        canvas = self.canvas(context=True)
        canvas._prepare_line_frame()
        lower = canvas._lower_layer_frames
        with patch.object(canvas, "_line_blocks", wraps=canvas._line_blocks) as projected:
            for layer in (3, 1, 2, 4):
                canvas.set_layer_height(canvas.scene.layer_z_mm[layer-1])
                frame = canvas._prepare_line_frame()
                self.assertIs(canvas._lower_layer_frames, lower)
                for segments, blocks in ((canvas.scene.wait_travel_segments, frame.wait_travel_blocks),
                        (canvas.scene.tower_travel_segments, frame.tower_travel_blocks)):
                    selected = segments[layer-1]
                    expected = QLineF(canvas._project(selected.start, canvas._fit_parameters()),
                        canvas._project(selected.end, canvas._fit_parameters()))
                    self.assertEqual(tuple(line for block in blocks for line in block), (expected,))
                    image = frame.lower_layers.toImage() if frame.lower_layers is not None else None
                    for index, segment in enumerate(segments):
                        point = canvas._project(Point3D((segment.start.x+segment.end.x)/2,
                            segment.start.y, segment.start.z), canvas._fit_parameters())
                        alpha = max(image.pixelColor(round(point.x())+dx, round(point.y())+dy).alpha()
                            for dx in (-1, 0, 1) for dy in (-1, 0, 1)) if image is not None else 0
                        self.assertEqual(alpha > 0, index < layer-1)
            self.assertFalse(any(call.args[0] is segments for call in projected.call_args_list
                for segments in (canvas.scene.wait_travel_segments, canvas.scene.tower_travel_segments)))
        canvas.reset_layer_colours()
        self.assertEqual(sum(map(len, canvas._prepare_line_frame().wait_travel_blocks)), 1)
        canvas.set_layer_height(None)
        frame = canvas._prepare_line_frame()
        self.assertIsNone(frame.lower_layers)
        self.assertEqual(sum(map(len, frame.wait_travel_blocks)), 4)
        self.assertEqual(sum(map(len, frame.tower_travel_blocks)), 4)


if __name__ == "__main__":
    unittest.main()
