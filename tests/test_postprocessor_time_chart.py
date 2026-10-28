from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication
from cooling_tower.gui.widgets.postprocessor_time_chart import PostprocessorTimeChart
from gui_lifecycle import dispose_test_widget


class VerticalTimeChartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.chart = PostprocessorTimeChart()
        self.chart.resize(340, 520)
        self.chart.set_data((160,)+(3,)*543, (5,)*544, (0,)*544, tuple(.2*(i+1) for i in range(544)), 8)
        self.chart.show()
        self.app.processEvents()

    def tearDown(self):
        dispose_test_widget(self.chart)
        self.app.processEvents()

    def test_vertical_mapping_preserves_first_last_and_intermediate_layers(self):
        chart = self.chart
        self.assertGreater(chart.layer_y(1), chart.layer_y(544))
        for layer in (1, 2, 123, 300, 544):
            self.assertEqual(chart.layer_at(chart.layer_y(layer)), layer)
        self.assertEqual(chart.layer_at(-100), 544)
        self.assertEqual(chart.layer_at(10000), 1)

    def test_logarithmic_scale_preserves_extremes_and_expands_short_layer_times(self):
        chart = self.chart
        chart.set_normalized(False)
        logarithmic = chart.time_fraction(8)
        self.assertEqual(chart.time_fraction(0), 0)
        self.assertEqual(chart.time_fraction(chart._maximum), 1)
        chart.set_logarithmic(False)
        self.assertGreater(logarithmic, chart.time_fraction(8)*5)
        self.assertEqual(chart.original[0], 160)
        self.assertEqual(len(chart.original), 544)

    def test_normalization_default_uses_complete_layer_times_and_handles_ties(self):
        chart = self.chart
        cases = (((100, 5, 10), (0, 0, 0), (0, 0, 0), True),
            ((5, 20, 10), (20, 0, 0), (5, 0, 0), True),
            ((5, 20, 10), (0, 0, 0), (0, 0, 0), False),
            ((20, 20), (0, 0), (0, 0), False), ((100,), (0,), (0,), False), ((), (), (), False))
        for original, motion, waits, expected in cases:
            with self.subTest(original=original, motion=motion, waits=waits):
                chart.set_data(original, motion, waits, tuple(.2*(i+1) for i in range(len(original))), 8)
                self.assertEqual(chart.normalized, expected)
                self.assertEqual(chart.default_normalization(), expected)

    def test_normalization_changes_scale_without_removing_or_recalculating_data(self):
        chart = self.chart
        arrays = chart.original, chart.motion, chart.waits, chart.heights
        self.assertTrue(chart.normalized)
        self.assertAlmostEqual(chart._maximum, 8*1.05)
        chart.select_layer(1)
        self.assertEqual(chart.selected, 1)
        self.assertEqual(chart.layer_at(chart.layer_y(1)), 1)
        self.assertEqual(sum(seq[0] for seq in arrays[:3]), 165)
        chart.set_normalized(False)
        self.assertAlmostEqual(chart._maximum, 165*1.05)
        chart.set_normalized(True)
        self.assertAlmostEqual(chart._maximum, 8*1.05)
        for before, after in zip(arrays, (chart.original, chart.motion, chart.waits, chart.heights)):
            self.assertIs(before, after)

    def test_normalized_first_layer_is_uncoloured_even_when_selected(self):
        chart = self.chart
        chart.set_data((100, 5, 3), (20, 0, 0), (10, 0, 0), (.2, .4, .6), 8)
        chart.select_layer(1)
        def colours_in_first_layer():
            image = chart.grab().toImage()
            rect = chart.plot_rect()
            return {image.pixelColor(x, y).name() for x in range(round(rect.left())+2, round(rect.right())-2)
                for y in range(round(rect.bottom()-rect.height()/3)+3, round(rect.bottom())-3)}
        self.assertFalse(set(chart.COLORS) & colours_in_first_layer())
        chart.set_normalized(False)
        self.assertTrue(set(chart.COLORS) & colours_in_first_layer())

    def test_dense_normalized_overview_ignores_first_layer_when_choosing_bin_representative(self):
        chart = self.chart
        chart.resize(210, 160)
        indices, draw = [], chart._draw_bars
        def record(painter, index, y, height):
            # Retain only the index. A mock's call history would keep the
            # active native QPainter alive after its widget is disposed.
            indices.append(index)
            draw(painter, index, y, height)
        with patch.object(chart, "_draw_bars", new=record):
            chart.select_layer(544)
            chart.grab()
            self.assertNotIn(0, indices)
            self.assertTrue(any(1 <= index < 12 for index in indices))

    def test_scale_mode_changes_rebuild_plot_once_and_scrubbing_reuses_it(self):
        chart = self.chart
        chart.grab()
        with patch.object(chart, "_paint_plot", wraps=chart._paint_plot) as plotted:
            chart.set_normalized(False)
            chart.grab()
            self.assertEqual(plotted.call_count, 1)
            for layer in (1, 200, 544):
                chart.select_layer(layer)
                chart.grab()
            self.assertEqual(plotted.call_count, 1)

    def test_axis_drag_and_keyboard_select_the_exact_layer(self):
        chart = self.chart
        selected = QSignalSpy(chart.layer_selected)
        finished = QSignalSpy(chart.drag_finished)
        x = chart.plot_rect().right()
        QTest.mousePress(chart, Qt.MouseButton.LeftButton, pos=QPointF(x, chart.layer_y(100)).toPoint())
        QTest.mouseMove(chart, QPointF(x, chart.layer_y(300)).toPoint())
        QTest.mouseRelease(chart, Qt.MouseButton.LeftButton, pos=QPointF(x, chart.layer_y(500)).toPoint())
        # Pixel rounding can cover two layers on a dense overview. The exact
        # numeric editor and keyboard remain available for every layer.
        self.assertLessEqual(abs(chart.selected-500), 1)
        self.assertGreaterEqual(selected.count(), 2)
        self.assertEqual(finished.count(), 1)
        QTest.keyClick(chart, Qt.Key.Key_Home)
        self.assertEqual(chart.selected, 1)
        QTest.keyClick(chart, Qt.Key.Key_Up)
        self.assertEqual(chart.selected, 2)
        QTest.keyClick(chart, Qt.Key.Key_End)
        self.assertEqual(chart.selected, 544)

    def test_scrubbing_does_not_rebuild_the_scale_and_overview(self):
        chart = self.chart
        chart.grab()
        with patch.object(chart, "_paint_plot", wraps=chart._paint_plot) as plotted:
            for layer in range(1, 40):
                chart.select_layer(layer)
                chart.grab()
            self.assertEqual(plotted.call_count, 0)
            chart.set_logarithmic(False)
            chart.grab()
            self.assertEqual(plotted.call_count, 1)

    def test_only_minimum_time_marker_has_a_hover_hint(self):
        chart = self.chart
        QTest.mouseMove(chart, chart.plot_rect().center().toPoint())
        self.assertEqual(chart.toolTip(), "")
        marker = chart.target_marker().boundingRect().center().toPoint()
        QTest.mouseMove(chart, marker)
        self.assertEqual(chart.toolTip(), "Eingestellte Mindest-Layerzeit: 8.00 s")
        selected = chart.selected
        QTest.mouseClick(chart, Qt.MouseButton.LeftButton, pos=marker)
        self.assertEqual(chart.selected, selected)
        QTest.mouseMove(chart, chart.plot_rect().center().toPoint())
        self.assertEqual(chart.toolTip(), "")

    def test_minimum_time_triangle_follows_scale_and_resize(self):
        chart = self.chart
        for logarithmic in (True, False):
            chart.set_logarithmic(logarithmic)
            for width in (210, 340):
                chart.resize(width, 520)
                rect = chart.plot_rect()
                marker = chart.target_marker().boundingRect()
                self.assertAlmostEqual(marker.center().x(), rect.left()+chart.time_fraction(8)*rect.width())
                self.assertAlmostEqual(marker.top(), rect.bottom()+1)
                self.assertTrue(chart.rect().contains(marker.toAlignedRect()))


if __name__ == "__main__":
    unittest.main()
