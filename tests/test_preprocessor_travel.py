from __future__ import annotations

import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cooling_tower.calibration.gcode_integration import parse_bed_geometry
from cooling_tower.preprocessor_travel import safe_travel_path, segments_cross


class PreprocessorTravelTests(unittest.TestCase):
    def geometry(self):
        return parse_bed_geometry({"bed_shape": ["0x0", "200x0", "200x200", "0x200"],
            "bed_exclude_area": ["80x50", "120x50", "120x150", "80x150"]})

    def test_shortest_direct_route_without_an_obstacle(self):
        self.assertEqual(safe_travel_path((20, 20), (180, 20), self.geometry()), ((20, 20), (180, 20)))

    def test_routes_around_exclusion_and_reverses_safely(self):
        geometry = self.geometry()
        path = safe_travel_path((30, 100), (170, 100), geometry)
        self.assertGreater(len(path), 2)
        self.assertEqual(path[0], (30, 100))
        self.assertEqual(path[-1], (170, 100))
        self.assertGreater(sum(math.dist(a, b) for a, b in zip(path, path[1:])), 140)
        obstacle = geometry.excluded_polygons[0]
        for a, b in zip(path, path[1:]):
            for i, point in enumerate(obstacle):
                self.assertFalse(segments_cross(a, b, point, obstacle[i-1]))

    def test_invalid_destination_and_disconnected_bed_fail(self):
        geometry = self.geometry()
        with self.assertRaises(ValueError):
            safe_travel_path((30, 100), (100, 100), geometry)
        with self.assertRaises(ValueError):
            safe_travel_path((30, 100), (220, 100), geometry)

    def test_concave_bed_does_not_allow_a_shortcut_outside_bed(self):
        geometry = parse_bed_geometry({"bed_shape": ["0x0", "200x0", "200x60", "60x60", "60x200", "0x200"]})
        path = safe_travel_path((30, 170), (170, 30), geometry)
        self.assertGreater(len(path), 2)

    def test_scientific_notation_preserves_circular_bed_coordinates(self):
        geometry = parse_bed_geometry({"bed_shape": "100x0,7.0e-15x100,-100x1.4e-14,-2.0e-14x-100"})
        self.assertEqual(len(geometry.printable_polygon), 4)
        self.assertEqual(geometry.printable_polygon[1], (7e-15, 100))
        self.assertEqual(geometry.bounds.minimum_x_mm, -100)
        self.assertEqual(geometry.bounds.maximum_y_mm, 100)


if __name__ == "__main__":
    unittest.main()
