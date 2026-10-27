from __future__ import annotations

import os
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QLineF
from PySide6.QtWidgets import QApplication

from cooling_tower.gui.widgets.preview_canvas import PreviewCanvas
from cooling_tower.gui.widgets.preview_projection import LineProjectionCache
from cooling_tower.models import BedBounds
from cooling_tower.preview import LineSegment3D, Point3D, PreviewScene
from gui_lifecycle import dispose_test_widget


def segments(count=1000, offset=0.0):
    return tuple(LineSegment3D(
        Point3D(offset+i % 53-.12345, i % 29+.98765, (i % 10+1)*.2),
        Point3D(offset+i % 53+1.23456, i % 29-1.54321, (i % 10+1)*.2),
    ) for i in range(count))


def scene(lines):
    return PreviewScene(lines, (), BedBounds(-30, 230, -20, 220), (0, 0),
        len(lines), len(lines), 2)


class ScalarCanvas(PreviewCanvas):
    """Original projection through two QPointF wrappers per stroke."""

    def _line_blocks(self, lines, parameters, context, *, maximum_lines=None):
        import math
        stride = max(1, math.ceil(len(lines)/maximum_lines)) if maximum_lines else 1
        projected = tuple(QLineF(self._project(line.start, parameters, context),
            self._project(line.end, parameters, context)) for line in lines[::stride])
        return tuple(projected[i:i+self.LINE_BLOCK_SIZE]
            for i in range(0, len(projected), self.LINE_BLOCK_SIZE))


class PreviewProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def canvas(self, cls=PreviewCanvas):
        canvas = cls()
        canvas.resize(740, 530)
        canvas.set_scene(scene(segments()))
        self.addCleanup(dispose_test_widget, canvas)
        return canvas

    def test_scalar_and_vector_coordinates_match_exactly_at_every_stride(self):
        canvas = self.canvas()
        for count in (17, 1000, 6000):
            source = segments(count)
            for yaw, pitch in ((-38, 28), (123.75, -89), (0, 0), (90, 89)):
                canvas.yaw_deg, canvas.pitch_deg = yaw, pitch
                context = canvas._projection_context()
                for maximum in (None, 300, 32):
                    with self.subTest(count=count, yaw=yaw, maximum=maximum):
                        parameters = (.137, -3.91, 106.17)
                        expected = ScalarCanvas._line_blocks(canvas, source, parameters, context,
                            maximum_lines=maximum)
                        actual = canvas._line_blocks(source, parameters, context,
                            maximum_lines=maximum)
                        self.assertEqual(actual, expected)

    def test_navigation_reuses_source_arrays_and_scene_replacement_releases_them(self):
        canvas = self.canvas()
        first = canvas._prepare_line_frame()
        points = next(iter(canvas._line_projection.entries.values()))[1]
        self.assertFalse(points.flags.writeable)
        for yaw, zoom, pan in ((15, 1.3, 3), (95, .9, -11)):
            canvas.yaw_deg, canvas.zoom, canvas.pan_x = yaw, zoom, pan
            changed = canvas._prepare_line_frame()
            self.assertNotEqual(first.object_blocks, changed.object_blocks)
            self.assertIs(next(iter(canvas._line_projection.entries.values()))[1], points)
        canvas.set_scene(scene(segments(offset=10)))
        self.assertEqual(canvas._line_projection.size_bytes, 0)
        self.assertFalse(canvas._line_projection.entries)
        canvas._prepare_line_frame()
        self.assertIsNot(next(iter(canvas._line_projection.entries.values()))[1], points)
        canvas.set_scene(None)
        self.assertFalse(canvas._line_projection.entries)

    def test_coordinate_cache_evicts_by_bytes_and_retains_recent_sources(self):
        canvas = self.canvas()
        cache = LineProjectionCache()
        cache.BUDGET_BYTES = 2*300*6*8
        context, parameters = canvas._projection_context(), canvas._fit_parameters()
        sources = [segments(300, i) for i in range(3)]
        for source in sources[:2]:
            cache.project(source, 1, parameters, context)
        cache.project(sources[0], 1, parameters, context)
        cache.project(sources[2], 1, parameters, context)
        self.assertEqual([key[0] for key in cache.entries], [id(sources[0]), id(sources[2])])
        self.assertLessEqual(cache.size_bytes, cache.BUDGET_BYTES)
        cache.project(segments(1000), 1, parameters, context)
        self.assertEqual(len(cache.entries), 2)
        cache.clear()
        self.assertEqual(cache.size_bytes, 0)

    def test_coordinate_cache_limits_entries_and_separates_sampling_strides(self):
        canvas = self.canvas()
        cache = LineProjectionCache()
        context, parameters = canvas._projection_context(), canvas._fit_parameters()
        source = segments(300)
        full = cache.project(source, 1, parameters, context)
        sampled = cache.project(source, 2, parameters, context)
        self.assertEqual(full[::2].tolist(), sampled.tolist())
        for i in range(20):
            cache.project(segments(300, i), 1, parameters, context)
        self.assertEqual(len(cache.entries), cache.MAXIMUM_ENTRIES)
        self.assertEqual(cache.size_bytes, sum(points.nbytes for _source, points in cache.entries.values()))

    def test_fit_bounds_survive_pan_zoom_resize_but_follow_camera_and_scene(self):
        canvas = self.canvas()
        canvas._fit_parameters()
        with patch.object(canvas, "_projected_bounds", wraps=canvas._projected_bounds) as bounds:
            canvas.pan_x, canvas.pan_y, canvas.zoom = 17, -23, 1.3
            canvas._fit_parameters()
            canvas.resize(850, 630)
            canvas._fit_parameters()
            self.assertEqual(bounds.call_count, 0)
            canvas.yaw_deg += 15
            canvas._fit_parameters()
            self.assertEqual(bounds.call_count, 1)
            canvas.fit_scene(emit=False)
            canvas._fit_parameters()
            self.assertEqual(bounds.call_count, 2)
            canvas.set_scene(scene(segments(offset=100)))
            canvas._fit_parameters()
            self.assertEqual(bounds.call_count, 3)

    def test_rendered_pixels_match_scalar_projection_with_layers_and_routes(self):
        fast, reference = self.canvas(), self.canvas(ScalarCanvas)
        model, tower, brim = segments(2000), segments(3000, 80), segments(300, 78)
        routes = segments(500, 40)
        value = replace(scene(model), tower_segments=tower, brim_segments=brim,
            tower_center_xy_mm=(100, 15), wait_travel_segments=routes,
            tower_travel_segments=routes, wait_travel_layer_indices=tuple(i % 10 for i in range(500)),
            tower_travel_layer_indices=tuple(i % 10 for i in range(500)),
            layer_z_mm=tuple((i+1)*.2 for i in range(10)))
        for canvas in (fast, reference):
            canvas.set_layer_context_enabled(True)
            canvas.set_scene(value)
            canvas.navigation_toggle.hide()
            canvas.navigation_status_label.hide()
            canvas.set_wait_travel_visible(True)
            canvas.set_tower_travel_visible(True)
            canvas.set_cumulative_travel_visible(True)
        for yaw, pitch, height in ((-38, 28, None), (123.75, -28, .8), (90, -89, 1.4)):
            for canvas in (fast, reference):
                canvas.yaw_deg, canvas.pitch_deg = yaw, pitch
                canvas.zoom, canvas.pan_x, canvas.pan_y = 1.1, 10, -5
                canvas.set_layer_height(height)
            self.assertEqual(fast.grab().toImage(), reference.grab().toImage())


if __name__ == "__main__":
    unittest.main()
