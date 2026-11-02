from pathlib import Path
import sys, tempfile, unittest
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from cooling_tower.native_project.print_space import NativePrintSpace, _expand_row
from cooling_tower.calibration.gcode_integration import parse_bed_geometry


class NativePrintSpaceTests(unittest.TestCase):
    def test_bit_dilation_fills_both_directions_including_zero(self):
        for radius in range(12):
            bits = (1 << 20) | (1 << 60)
            expected = 0
            for offset in range(-radius, radius+1):
                expected |= bits << offset if offset >= 0 else bits >> -offset
            self.assertEqual(_expand_row(bits, radius), expected)

    def test_nearest_valid_position_uses_real_radius_and_preserves_interior_obstacles(self):
        bed = parse_bed_geometry({'printable_area':['0x0','200x0','200x200','0x200']})
        rows = [0] * 201
        # A complete wipe footprint occupies the space to the model's left.
        for y in range(90, 121):
            rows[y] = ((1 << 21)-1) << 75
        for y in range(100, 111):
            rows[y] |= ((1 << 11)-1) << 100
        space = NativePrintSpace(tuple(rows), (0.,0.), 1., 201, (105.,105.), 2, .3)
        small = space.place(bed, 6., clearance=5., edge_clearance=5.)
        large = space.place(bed, 20., clearance=5., edge_clearance=5.)
        first = small.center_x_mm, small.center_y_mm
        second = large.center_x_mm, large.center_y_mm
        self.assertLess(sum((a-105)**2 for a in first), sum((a-105)**2 for a in second))
        for position, radius in ((first,6.),(second,20.)):
            for box in ((75,95,90,120),(100,110,100,110)):
                dx = max(box[0]-position[0], 0., position[0]-box[1])
                dy = max(box[2]-position[1], 0., position[1]-box[3])
                self.assertGreater(dx*dx+dy*dy, (radius+5)**2)
            self.assertGreaterEqual(min(*position,200-position[0],200-position[1]), radius+5)

    def test_no_free_space_is_reported_without_placing_over_originals(self):
        bed = parse_bed_geometry({'printable_area':['0x0','50x0','50x50','0x50']})
        space = NativePrintSpace(tuple([(1 << 51)-1]*51), (0.,0.), 1.,51,(25.,25.),1,.3)
        with self.assertRaisesRegex(ValueError, 'kein gültiger'):
            space.place(bed, 10., clearance=5.,edge_clearance=5.)


if __name__ == '__main__':
    unittest.main()
