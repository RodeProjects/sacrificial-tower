from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QFontDatabase, QTextDocument
from PySide6.QtWidgets import QApplication, QLabel

from cooling_tower.gui.generation_panel import GenerationPanel, RESULT_SUMMARY_TEXTS
from gui_lifecycle import dispose_test_widget


class GenerationMetricsLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.font_ids = []
        for name in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf", "seguisym.ttf"):
            path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
            if path.is_file():
                font_id = QFontDatabase.addApplicationFont(str(path))
                if font_id >= 0:
                    cls.font_ids.append(font_id)

    @classmethod
    def tearDownClass(cls):
        for font_id in cls.font_ids:
            QFontDatabase.removeApplicationFont(font_id)

    def setUp(self):
        self.panel = GenerationPanel(ROOT / "src/cooling_tower/gui/assets/tower_gen_finished.webp")
        self.addCleanup(dispose_test_widget, self.panel)
        self.panel.setStyleSheet((ROOT / "src/cooling_tower/gui/styles.qss").read_text(encoding="utf-8"))
        self.panel.set_context(("Turmfüllung: 100 %", "Turmstützen: deaktiviert"))
        self.panel.begin(10, .25, 5, 12)
        self.panel.start_slice(5, 12)
        self.panel.set_achieved(9.85)
        self.panel.mark_finished(paused=True, can_continue=True)

    def resize_panel(self, width):
        self.panel.setFixedWidth(width)
        self.settle()

    def settle(self):
        for _ in range(5):
            self.app.processEvents()
            self.panel.resize(self.panel.width(), self.panel.heightForWidth(self.panel.width()))
        self.app.processEvents()

    def assert_cells_fit(self):
        panel = self.panel
        cells = [*panel.metric_cards, panel.result_summary]
        if not panel.manual_hint_cell.isHidden():
            cells.append(panel.manual_hint_cell)
            widths = [cell.width() for cell in cells]
            self.assertLessEqual(max(widths) - min(widths), 1)
            self.assertEqual(panel.metric_cards[0].width(), panel.manual_hint_cell.width())
            self.assertEqual(panel.metric_cards[1].width(), panel.result_summary.width())
            self.assertEqual(panel.metric_cards[1].x(), panel.result_summary.x())
        bounds = panel.metrics_group.rect()
        for index, cell in enumerate(cells):
            self.assertTrue(bounds.contains(cell.geometry()), (bounds, cell.geometry()))
            for other in cells[index + 1:]:
                self.assertFalse(cell.geometry().intersects(other.geometry()))
            for label in cell.findChildren(QLabel):
                if not label.isHidden():
                    self.assertGreaterEqual(label.height(), label.heightForWidth(label.width()))
        self.assertEqual(panel.metrics_group.height(), panel.metrics_layout.heightForWidth(bounds.width()))
        bottom = panel.metrics_group.mapTo(panel.result_widget, QPoint()).y() + bounds.height()
        if not panel.result_actions.isHidden():
            self.assertEqual(panel.result_actions.y(), bottom)

    def assert_lines_do_not_wrap(self):
        for card in (*self.panel.metric_cards, self.panel.result_summary):
            for label in card.findChildren(QLabel):
                doc = QTextDocument()
                doc.setDocumentMargin(0)
                doc.setDefaultFont(label.font())
                if label.textFormat() == Qt.TextFormat.RichText:
                    doc.setHtml(label.text())
                else:
                    doc.setPlainText(label.text())
                self.assertLessEqual(doc.idealWidth(), label.contentsRect().width())

    def test_three_columns_are_equal_and_switch_before_reserved_content_would_wrap(self):
        panel = self.panel
        boundary = panel.metrics_layout.sizeHint().width()
        for width in (1200, 1000, 900, 800, boundary + 2, boundary + 1, boundary):
            self.resize_panel(width)
            cells = [*panel.metric_cards, panel.result_summary]
            self.assertEqual(panel.result_summary.y(), 0)
            self.assertLessEqual(max(cell.width() for cell in cells) - min(cell.width() for cell in cells), 1)
            self.assertEqual(sum(cell.width() for cell in cells), width)
            self.assertEqual(cells[0].x(), 0)
            self.assertEqual(cells[1].x(), cells[0].width())
            self.assertEqual(cells[2].x(), cells[0].width() + cells[1].width())
            self.assert_lines_do_not_wrap()
        self.resize_panel(boundary - 1)
        self.assertGreater(panel.result_summary.y(), 0)
        self.assert_cells_fit()

    def test_compact_view_has_four_equal_width_cells_and_restores_the_hint(self):
        panel = self.panel
        hint = panel.manual_mode_hint
        self.resize_panel(440)
        time, deviation = panel.metric_cards
        summary, manual = panel.result_summary, panel.manual_hint_cell
        self.assertIs(hint.parentWidget(), manual)
        self.assertEqual(time.y(), deviation.y())
        self.assertEqual(deviation.x(), time.width())
        self.assertEqual(time.width() + deviation.width(), 440)
        self.assertEqual(manual.geometry(), QRect(0, time.height(), 440 - summary.width(), summary.height()))
        self.assertEqual(summary.x(), manual.width())
        self.assertEqual(summary.y(), time.height())
        self.assertEqual(summary.x(), deviation.x())
        self.assertEqual([cell.width() for cell in (time, deviation, summary, manual)], [220] * 4)
        self.assert_cells_fit()
        self.resize_panel(1000)
        self.assertIs(panel.manual_mode_hint, hint)
        self.assertIs(hint.parentWidget(), panel.result_actions)
        self.assertEqual(summary.y(), 0)
        self.assertTrue(manual.isHidden())
        self.assert_cells_fit()

    def test_bottom_assessment_reserves_the_widest_status_from_the_start(self):
        panel = self.panel
        self.resize_panel(520)
        previous = panel.result_summary.width()
        for text in RESULT_SUMMARY_TEXTS:
            with self.subTest(text=text):
                panel.result_label.setText(text)
                self.settle()
                self.assertGreater(panel.result_summary.y(), 0)
                self.assertEqual(panel.result_summary.width(), previous)
                document = QTextDocument()
                document.setDocumentMargin(0)
                document.setDefaultFont(panel.result_label.font())
                document.setPlainText(text)
                self.assertLessEqual(document.idealWidth(), panel.result_label.contentsRect().width())
                self.assertEqual(panel.manual_hint_cell.width(), 520 - previous)
                self.assert_cells_fit()

    def test_status_changes_do_not_reflow_at_the_same_window_width(self):
        panel = self.panel
        boundary = panel.metrics_layout.sizeHint().width()
        for width, compact in ((boundary, False), (boundary - 1, True), (520, True), (1000, False)):
            self.resize_panel(width)
            previous = panel.result_summary.geometry()
            for value in (9.85, 8.94, 11.94, 9.7, 10.3, 9.3, 10.7, 10):
                with self.subTest(width=width, value=value):
                    panel.set_achieved(value)
                    self.settle()
                    self.assertEqual(panel.result_summary.y() > 0, compact)
                    self.assertEqual(panel.result_summary.geometry(), previous)
                    self.assertIs(panel.manual_mode_hint.parentWidget(),
                                  panel.manual_hint_cell if compact else panel.result_actions)
                    self.assert_cells_fit()

    def test_toolbar_triggers_compact_layout_before_it_can_wrap_the_hint(self):
        panel = self.panel
        # Wider actions can make the toolbar the limiting row even with equal metric columns.
        panel.setStyleSheet(panel.styleSheet() + "\nQWidget#generationResultActions QPushButton "
                           "{padding-left:80px; padding-right:80px;}")
        self.resize_panel(1400)
        required = panel.result_actions.minimum_unwrapped_width()
        self.assertGreater(required, panel.metrics_layout.sizeHint().width())
        self.resize_panel(required)
        self.assertEqual(panel.result_summary.y(), 0)
        hint = panel.manual_mode_hint
        document = QTextDocument()
        document.setDocumentMargin(0)
        document.setDefaultFont(hint.font())
        document.setHtml(hint.text())
        self.assertLessEqual(document.idealWidth(), hint.contentsRect().width())
        self.resize_panel(required - 1)
        self.assertGreater(panel.result_summary.y(), 0)
        self.assertIs(hint.parentWidget(), panel.manual_hint_cell)
        self.assert_cells_fit()
        # Hint relocation must not remove the trigger and immediately switch back.
        for _ in range(3):
            self.settle()
            self.assertGreater(panel.result_summary.y(), 0)
        panel.continue_button.hide()
        self.settle()
        self.assertEqual(panel.result_summary.y(), 0)
        panel.continue_button.show()
        self.settle()
        self.assertGreater(panel.result_summary.y(), 0)
        self.assert_cells_fit()

    def test_narrow_and_wide_views_have_no_clipping_or_empty_height(self):
        for width in (1000, 800, 650, 600, 521, 520, 419, 420, 321, 320, 281, 280, 520, 1000):
            with self.subTest(width=width):
                self.resize_panel(width)
                self.assert_cells_fit()

    def test_joint_slice_hint_and_actions_keep_their_visibility_after_relocation(self):
        panel = self.panel
        panel.begin(10, .25, 0, 12)
        self.resize_panel(520)
        self.assertTrue(panel.manual_mode_hint.isHidden())
        panel.start_slice(0, 12)
        self.settle()
        self.assertFalse(panel.manual_mode_hint.isHidden())
        self.assertIs(panel.manual_mode_hint.parentWidget(), panel.manual_hint_cell)
        self.assertTrue(panel.result_actions.isHidden())
        panel.accept_button.show()
        self.settle()
        self.assertFalse(panel.result_actions.isHidden())
        self.assertFalse(panel.manual_mode_hint.isHidden())
        self.assert_cells_fit()

    def test_first_joint_slice_shares_spare_width_before_any_text_would_wrap(self):
        panel = self.panel
        panel.begin(15, .25, 0, 12)
        panel.start_slice(0, 12)
        self.resize_panel(830)
        boundary = panel.metrics_layout.sizeHint().width()
        self.assertLess(boundary, 830)
        for width in (830, 800, boundary + 1, boundary, 830):
            with self.subTest(width=width):
                self.resize_panel(width)
                self.assertEqual(panel.result_summary.y(), 0)
                self.assertEqual(sum(cell.width() for cell in (*panel.metric_cards, panel.result_summary)), width)
                self.assertGreater(panel.metric_cards[0].width(), panel.metric_cards[1].width())
                self.assertIs(panel.manual_mode_hint.parentWidget(), panel.result_actions)
                self.assert_lines_do_not_wrap()
                self.assert_cells_fit()
        self.resize_panel(boundary - 1)
        self.assertGreater(panel.result_summary.y(), 0)
        self.assertIs(panel.manual_mode_hint.parentWidget(), panel.manual_hint_cell)
        self.assert_cells_fit()

    def test_first_measurement_restores_equal_columns_and_a_new_run_shares_space_again(self):
        panel = self.panel
        panel.begin(15, .25, 0, 12)
        panel.start_slice(0, 12)
        self.resize_panel(830)
        self.assertGreater(panel.metric_cards[0].width(), panel.metric_cards[1].width())
        candidate = SimpleNamespace(evaluation=SimpleNamespace(
            layer_timings=(SimpleNamespace(combined_layer_time_s=14.85),)))
        panel.complete_slice(1, 12, candidate, 15)
        self.settle()
        widths = [cell.width() for cell in (*panel.metric_cards, panel.result_summary)]
        self.assertEqual(panel.result_summary.y(), 0)
        self.assertLessEqual(max(widths) - min(widths), 1)
        self.assert_cells_fit()
        panel.begin(15, .25, 0, 12)
        panel.start_slice(0, 12)
        self.settle()
        self.assertEqual(panel.result_summary.y(), 0)
        self.assertGreater(panel.metric_cards[0].width(), panel.metric_cards[1].width())
        self.assert_lines_do_not_wrap()
        self.assert_cells_fit()
        panel.resume_waiting()
        self.settle()
        self.assertTrue(panel.manual_mode_hint.isHidden())
        panel.start_slice(3, 12)
        self.settle()
        self.assertFalse(panel.manual_mode_hint.isHidden())
        self.assert_cells_fit()


if __name__ == "__main__":
    unittest.main()
