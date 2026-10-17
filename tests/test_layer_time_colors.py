import sys
import unittest
from pathlib import Path
from dataclasses import replace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from PySide6.QtGui import QColor
from cooling_tower.gui.widgets.layer_range_canvas import LayerRangeCanvas
from cooling_tower.manual.geometry import ManualSettings,GeometryError,validate_settings,manual_color_scale_limit,minimum_original_layer_time


class LayerTimeColorTests(unittest.TestCase):
    def test_original_minimum_is_unrounded_and_ignores_unknown_invalid_measurements(self):
        from types import SimpleNamespace
        for times,expected in (((),None),((False,None,-1,"2",float("inf"),float("nan")),None),
                ((10,7.23456789,20),7.23456789),((2,0,3),0)):
            layers=tuple(SimpleNamespace(total_time_s=value) for value in times)
            self.assertEqual(minimum_original_layer_time(layers),expected)

    def test_scale_limit_ignores_unknown_invalid_times_and_rounds_inside_object_maximum(self):
        from types import SimpleNamespace
        for times,expected in (((),60),((0,-1,True,None,"100",float("nan"),float("inf")),60),
                ((61.29,30,60),61.2),((30,7200.5,10),7200.5),((1e308,),1e308)):
            with self.subTest(times=times):
                layers=tuple(SimpleNamespace(total_time_s=value) for value in times)
                self.assertEqual(manual_color_scale_limit(layers),expected)

    def test_layer_time_deficit_green_to_red_and_clamped_endpoints(self):
        settings=ManualSettings()
        self.assertEqual((settings.color_reference_time_s,settings.color_deficit_time_s,settings.color_red_time_s),(10,4,6))
        green,red=QColor(LayerRangeCanvas.OBJECT_COLOR),QColor(LayerRangeCanvas.CRITICAL_COLOR)
        for actual in (10,11,20,100):
            self.assertEqual(LayerRangeCanvas.layer_time_color(10,6,actual),green)
        for actual in (0,4,6):
            self.assertEqual(LayerRangeCanvas.layer_time_color(10,6,actual),red)
        middle=LayerRangeCanvas.layer_time_color(10,6,8)
        self.assertEqual(middle,QColor(*(round((a+b)/2) for a,b in zip(green.getRgb()[:3],red.getRgb()[:3]))))
        self.assertLess(LayerRangeCanvas.layer_time_color(10,6,9).red(),middle.red())
        self.assertGreater(LayerRangeCanvas.layer_time_color(10,6,7).red(),middle.red())

    def test_range_editor_deficit_mapping_retains_its_color_direction(self):
        for start,full in ((0,1),(.2,.8),(1.9,2)):
            for actual in (0,8,9,9.5,9.9,10,12):
                self.assertEqual(LayerRangeCanvas.layer_time_color(10-start,10-full,actual),
                                 LayerRangeCanvas.layer_color(10,actual,start,full))

    def test_deficit_requires_valid_type_and_nonnegative_seconds(self):
        for value in (True,"6",None,{},float("nan"),float("inf"),-1,10.1,60.1):
            with self.subTest(value=value),self.assertRaises(GeometryError):
                validate_settings(replace(ManualSettings(),color_deficit_time_s=value))
        for value in (0,.001,6,10):
            validate_settings(replace(ManualSettings(),color_deficit_time_s=value))

    def test_equal_bounds_use_a_hard_boundary_and_green_includes_the_exact_time(self):
        for time in (0,3,6,60,120):
            for actual in (time-1,time-.0001):
                self.assertEqual(LayerRangeCanvas.layer_time_color(time,time,actual),QColor(LayerRangeCanvas.CRITICAL_COLOR))
            for actual in (time,time+.0001,time+1):
                self.assertEqual(LayerRangeCanvas.layer_time_color(time,time,actual),QColor(LayerRangeCanvas.OBJECT_COLOR))
