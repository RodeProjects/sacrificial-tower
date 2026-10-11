import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from cooling_tower.manual.layer_snap import snap_layer_height


class ManualLayerSnapTests(unittest.TestCase):
    def test_variable_layers_use_actual_heights_and_bounded_floor_or_ceiling(self):
        tops=(.15,.35,.6,.7,1.0)
        self.assertEqual(snap_layer_height(.49,tops),.6)
        self.assertEqual(snap_layer_height(.49,tops,direction=-1),.35)
        self.assertEqual(snap_layer_height(.49,tops,direction=1),.6)
        self.assertEqual(snap_layer_height(.49,tops,lower=.4,upper=.65),.6)
        self.assertIsNone(snap_layer_height(.49,tops,lower=.4,upper=.5))
        self.assertIsNone(snap_layer_height(.49,()))

    def test_above_object_uses_last_spacing_without_exceeding_machine_height(self):
        tops=(.15,.35,.6,.7,1.0)
        self.assertAlmostEqual(snap_layer_height(1.42,tops),1.3)
        self.assertAlmostEqual(snap_layer_height(2,tops,upper=1.5),1.3)
        self.assertAlmostEqual(snap_layer_height(2,tops,lower=1.4,upper=1.7),1.6)
        self.assertIsNone(snap_layer_height(2,tops,lower=1.4,upper=1.5))
        self.assertAlmostEqual(snap_layer_height(.71,(.2,)),.8)
