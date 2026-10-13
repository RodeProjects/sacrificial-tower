import math
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cooling_tower.calibration.gcode_integration import _circle_fits_bed
from cooling_tower.manual.placement import largest_tower_envelope, maximum_foot_diameter, available_radius
from cooling_tower.models.calibration import BedBounds, BedGeometry, OccupiedBounds
from cooling_tower.preview import PreviewCancelled


class ManualPlacementTests(unittest.TestCase):
    def bed(self,polygon=None,excluded=()):
        polygon=polygon or ((0,0),(220,0),(220,220),(0,220))
        return BedGeometry(BedBounds(min(p[0] for p in polygon),max(p[0] for p in polygon),
                                    min(p[1] for p in polygon),max(p[1] for p in polygon)),polygon,excluded)

    def test_maximum_uses_free_corners_and_exact_object_gap(self):
        bed=self.bed();occupied=OccupiedBounds(90,130,90,130)
        radius,x,y=largest_tower_envelope(bed,occupied)
        optimum=(90*math.sqrt(2)-.3)/(1+math.sqrt(2))
        self.assertAlmostEqual(radius,optimum,delta=.0021)
        self.assertTrue(_circle_fits_bed((x,y),radius,0,bed))
        distance=math.hypot(max(90-x,0,x-130),max(90-y,0,y-130))
        self.assertGreaterEqual(distance-radius,.3-1e-9)
        self.assertEqual(maximum_foot_diameter(bed,occupied,3),math.floor((radius-3)*200)/100)

    def test_polygon_and_exclusions_remain_hard_limits(self):
        bed=self.bed(((0,0),(180,0),(180,80),(100,80),(100,180),(0,180)),
                     (((0,0),(40,0),(40,65),(0,65)),))
        occupied=OccupiedBounds(65,95,100,140)
        radius,x,y=largest_tower_envelope(bed,occupied)
        self.assertTrue(_circle_fits_bed((x,y),radius,0,bed))
        for gx in range(0,181,10):
            for gy in range(0,181,10):
                self.assertGreaterEqual(radius+.0021,available_radius(bed,occupied,gx,gy))

    def test_no_space_and_brim_return_no_positive_diameter(self):
        bed=self.bed()
        self.assertEqual(maximum_foot_diameter(bed,OccupiedBounds(0,220,0,220),0),0)
        self.assertEqual(maximum_foot_diameter(bed,OccupiedBounds(0,10,0,10),111),0)

    def test_object_outside_center_leaves_full_bed_circle(self):
        self.assertEqual(maximum_foot_diameter(self.bed(),OccupiedBounds(0,10,0,10),0),220)

    def test_polygon_search_is_cancelable_and_does_not_cache_partial_results(self):
        from cooling_tower.manual import placement
        bed=self.bed(((0,0),(180,0),(180,80),(100,80),(100,180),(0,180)))
        occupied=OccupiedBounds(66,96,101,141)
        event=Mock();event.is_set.side_effect=[False,True]
        with self.assertRaises(PreviewCancelled):largest_tower_envelope(bed,occupied,event)
        self.assertNotIn((bed,occupied),placement._envelopes)


if __name__ == "__main__":
    unittest.main()
