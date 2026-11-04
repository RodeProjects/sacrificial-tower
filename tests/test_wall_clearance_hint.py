import unittest
import math
import re

from cooling_tower.tower.wall_clearance import wall_clearance_hint


class WallClearanceHintTests(unittest.TestCase):
    def values(self, **overrides):
        return {'outer_wall_line_width': '0.42', 'inner_wall_line_width': '0.45',
                'minimum_sparse_infill_area': '20', 'sparse_infill_density': '12%', **overrides}

    def test_five_mm_needs_a_larger_actionable_diameter_for_small_area_rule(self):
        hint = wall_clearance_hint(self.values(), 'anycubic_slicer_next', 1, 5)
        self.assertIn('mindestens 6,0 mm einstellen', hint)
        self.assertLess(len(hint), 110)
        self.assertEqual(wall_clearance_hint(self.values(), 'anycubic_slicer_next', 1, 6), '')

    def test_more_walls_and_larger_area_require_larger_outer_diameter(self):
        self.assertIn('6,9 mm', wall_clearance_hint(self.values(), 'orca_slicer', 2, 5))
        self.assertIn('8,9 mm', wall_clearance_hint(self.values(minimum_sparse_infill_area='50'), 'orca_slicer', 1, 5))

    def test_percent_widths_use_slicer_reference(self):
        values = {'nozzle_diameter': ['0.4'], 'layer_height': '0.2', 'line_width': '150%',
                  'minimum_sparse_infill_area': '20', 'solid_infill_below_area': '20',
                  'fill_density': '12%', 'sparse_infill_density': '12%'}
        self.assertIn('7,5 mm', wall_clearance_hint(values, 'orca_slicer', 2, 5))
        self.assertIn('6,3 mm', wall_clearance_hint(values, 'prusa_slicer', 2, 5))

    def test_manual_polygon_and_rounding_leave_more_than_threshold_area(self):
        for segments in (4, 6, 30, 256):
            for walls in (1, 2, 5):
                with self.subTest(segments=segments, walls=walls):
                    hint = wall_clearance_hint(self.values(), 'orca_slicer', walls, 3,
                                               circle_segments=segments)
                    recommended = float(re.search(r'([0-9]+,[0-9]+) mm', hint)[1].replace(',', '.'))
                    # Independently recover the regular polygon from its apothem
                    # after removing the walls. Its inner area must exceed 20 mm².
                    apothem = recommended / 2 * math.cos(math.pi / segments) - (.42 + (walls - 1) * .45)
                    remaining_area = segments * apothem**2 * math.tan(math.pi / segments)
                    self.assertGreater(remaining_area, 20)
                    self.assertEqual(wall_clearance_hint(self.values(), 'orca_slicer', walls, recommended,
                                                        circle_segments=segments), '')

    def test_zero_density_ignores_area_rule_and_safe_diameters_have_no_warning(self):
        self.assertEqual(wall_clearance_hint(self.values(sparse_infill_density='0%'), 'orca_slicer', 1, 5), '')
        self.assertEqual(wall_clearance_hint(self.values(minimum_sparse_infill_area='0'), 'orca_slicer', 2, 5), '')

    def test_full_infill_and_missing_width_are_not_given_a_false_threshold(self):
        self.assertIn('100 % Füllung', wall_clearance_hint({'fill_density': '100%'}, 'prusa_slicer', 2, 5))
        self.assertIn('nicht bestimmbar', wall_clearance_hint({}, '', 2, 5))
        self.assertIn('nicht bestimmbar', wall_clearance_hint(self.values(minimum_sparse_infill_area='invalid'), 'orca_slicer', 2, 5))
