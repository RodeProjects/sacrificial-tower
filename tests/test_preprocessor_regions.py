"""Drag masks preserve the complete placement constraints without point rescans."""
from dataclasses import replace
from threading import Event
from types import SimpleNamespace
import unittest

import numpy as np

import test_preprocessor as fixture
from cooling_tower.models import BedBounds, BedGeometry
from cooling_tower.preprocessor_placement import OriginalMotionIndex, _Move
from cooling_tower.preprocessor_regions import PlacementRegions
from cooling_tower.preview.toolpath import PreviewCancelled


class PlacementRegionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.PreprocessorTests()
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def context_and_settings(self):
        context = self.fixture.service.placement_context(self.fixture.request())
        centre, wait, _ = context.resolve()
        settings = replace(context.settings, automatic_position=False, automatic_wait_position=False,
            center_x_mm=centre[0], center_y_mm=centre[1], wait_x_mm=wait[0], wait_y_mm=wait[1])
        return context, settings

    def test_green_cells_and_corners_pass_exact_checks_for_both_handles(self):
        context, settings = self.context_and_settings()
        for kind in ("tower", "wait"):
            regions = context.regions.regions(kind, settings)
            self.assertIn(0, regions.states)
            self.assertIn(1, regions.states)
            b = regions.bounds
            dx = (b.maximum_x_mm-b.minimum_x_mm)/regions.columns
            dy = (b.maximum_y_mm-b.minimum_y_mm)/regions.rows
            green = np.flatnonzero(np.frombuffer(regions.states, dtype=np.uint8))
            for i in green[::max(1, len(green)//30)]:
                x, y = i % regions.columns, i // regions.columns
                centre = (b.minimum_x_mm+(x+.5)*dx, b.maximum_y_mm-(y+.5)*dy)
                for ox, oy in ((0, 0), (-dx/2, -dy/2), (-dx/2, dy/2), (dx/2, -dy/2), (dx/2, dy/2)):
                    self.assertTrue(context.position_valid(kind, (centre[0]+ox, centre[1]+oy), settings))

    def test_reuses_source_fields_and_checks_the_frozen_counterpart(self):
        context, settings = self.context_and_settings()
        fields = context.regions.prepare(settings.edge_clearance_mm)
        moves_examined = context.regions.index.examined_moves
        first = context.regions.regions("tower", settings)
        moved = replace(settings, wait_x_mm=30, wait_y_mm=30)
        second = context.regions.regions("tower", moved)
        self.assertNotEqual(first.states, second.states)
        self.assertEqual(first, context.regions.regions("tower", settings))
        invalid_other = replace(settings, wait_x_mm=105, wait_y_mm=105)
        self.assertEqual(set(context.regions.regions("tower", invalid_other).states), {0})
        self.assertIs(context.regions.prepare(settings.edge_clearance_mm), fields)
        self.assertEqual(context.regions.index.examined_moves, moves_examined)

    def test_immediate_lookup_never_waits_for_an_active_preparation(self):
        context, settings = self.context_and_settings()
        self.assertIsNone(context.regions.immediate_regions("tower", settings))
        self.assertIsNone(context.regions._primitives)
        context.regions.prepare(settings.edge_clearance_mm)
        context.regions._lock.acquire()
        try:
            self.assertIsNone(context.regions.immediate_regions("tower", settings))
        finally:
            context.regions._lock.release()
        regions = context.regions.immediate_regions("tower", settings)
        self.assertIsNotNone(regions)
        self.assertEqual(regions, context.regions.regions("tower", settings))

    def test_cancelled_build_does_not_publish_partial_fields(self):
        context, settings = self.context_and_settings()
        event = Event()
        event.set()
        with self.assertRaises(PreviewCancelled):
            context.regions.prepare(settings.edge_clearance_mm, event=event)
        self.assertFalse(context.regions._fields)
        self.assertIn(1, context.regions.regions("tower", settings).states)
        for edge in (6, 7, 8, 9):
            context.regions.prepare(edge)
        self.assertEqual(len(context.regions._fields), 3)

    def test_profile_keepout_reachability_is_prepared_once_and_green_stays_safe(self):
        request = self.fixture.request()
        request.profile.effective_values["bed_exclude_area"] = ["0x0", "20x0", "20x20", "0x20"]
        context = self.fixture.service.placement_context(request)
        centre, wait, _ = context.resolve()
        settings = replace(context.settings, automatic_position=False, automatic_wait_position=False,
            center_x_mm=centre[0], center_y_mm=centre[1], wait_x_mm=wait[0], wait_y_mm=wait[1])
        self.assertFalse(context.regions._simple_bed)
        for kind in ("tower", "wait"):
            regions = context.regions.regions(kind, settings)
            b = regions.bounds
            green = np.flatnonzero(np.frombuffer(regions.states, dtype=np.uint8))
            self.assertTrue(len(green))
            for i in green[::max(1, len(green)//20)]:
                point = (b.minimum_x_mm+(i % regions.columns+.5)*(b.maximum_x_mm-b.minimum_x_mm)/regions.columns,
                    b.maximum_y_mm-(i // regions.columns+.5)*(b.maximum_y_mm-b.minimum_y_mm)/regions.rows)
                self.assertTrue(context.position_valid(kind, point, settings))

    def test_unreachable_original_layer_endpoints_leave_no_green_cells(self):
        text = fixture.make_gcode().replace("G1 X100 Y100 E", "G1 X-20 Y100 E")
        context = self.fixture.service.placement_context(self.fixture.request(text))
        for kind in ("tower", "wait"):
            self.assertEqual(set(context.regions.regions(kind, context.settings).states), {0})

    def test_unsampled_arcs_lower_moves_and_gantry_match_original_checks(self):
        geometry = BedGeometry(BedBounds(0, 220, 0, 220), ((0, 0), (220, 0), (220, 220), (0, 220)))
        head = SimpleNamespace(radius_mm=12, lower_radius_mm=5, clearance_height_mm=10)
        # Different chronology and radii at the same XY must retain the
        # strictest constraint; the arc's full conservative bounds survive.
        moves = [
            _Move((100, 100), (110, 110), 1, 1, 0, True, 10, (100, 100, 110, 110)),
            _Move((110, 110), (100, 100), 4, 30, 0, False, 20, (100, 100, 110, 110)),
            _Move((150, 150), (151, 151), 3, 3, 4, True, 30, (146, 146, 155, 155)),
        ]
        index = OriginalMotionIndex(moves)
        provider = PlacementRegions(geometry, index, reserved_radius=8, tower_radius_at_z=lambda z: 8,
            height=40, model_margin=4, wait_margin=5, head=head, reachable=lambda p=None, **kw: True)
        provider.prepare(5)
        points = np.array([(x, y) for x in range(15, 206, 7) for y in range(15, 206, 7)], dtype=float)
        for kind in ("tower", "wait"):
            actual = provider._clear(kind, points, 5, 0, None)
            for point, valid in zip(points, actual):
                if kind == "tower":
                    expected = index.model_clear(point, 12, lambda z: 12, height=40) and index.tower_rejection(
                        point, 8, head_radius=12, lower_head_radius=5, head_height=10, gantry_height=10) is None
                else:
                    expected = index.model_clear(point, 5, lambda z: 5)
                self.assertEqual(bool(valid), expected, (kind, point))


if __name__ == "__main__":
    unittest.main()
