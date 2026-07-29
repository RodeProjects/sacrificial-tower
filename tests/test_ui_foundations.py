from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("COOLING_TOWER_DISABLE_SLICER_DISCOVERY", "1")

from PySide6.QtCore import QLocale, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QDoubleSpinBox, QLabel

from cooling_tower.gui.design_tokens import METRICS
from cooling_tower.gui.background_jobs import JobKind
from cooling_tower.gui.main_window import MainWindow
from cooling_tower.gui.workflow_controller import (
    WorkflowController,
    WorkflowStage,
)
from cooling_tower.gui.widgets import (
    NumericSettingWidget,
    ResponsiveCardGrid,
    SectionCard,
    SectionState,
)


EXPECTED_STATE_IDS = {
    "no_gcode",
    "gcode_analysis",
    "gcode_ready",
    "slicer_search",
    "slicer_ready",
    "slicer_unavailable",
    "configuration_ready",
    "geometry_valid",
    "geometry_invalid",
    "preview_running",
    "preview_current",
    "preview_stale",
    "export_running",
    "export_success",
    "responsive_scaled",
}


class UiFoundationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.app.processEvents()
        self.temporary.cleanup()

    def test_numeric_settings_use_german_format_on_english_systems(self) -> None:
        previous_locale = QLocale()
        QLocale.setDefault(
            QLocale(
                QLocale.Language.English,
                QLocale.Country.UnitedStates,
            )
        )
        editor = QDoubleSpinBox()
        editor.setDecimals(2)
        try:
            widget = NumericSettingWidget(
                setting_name="test_value",
                label="Testwert",
                editor=editor,
                default_provider=lambda: 0.0,
            )
            editor.setValue(12.5)
            self.assertEqual(editor.locale().decimalPoint(), ",")
            self.assertEqual(editor.text(), "12,50")
            widget.close()
        finally:
            QLocale.setDefault(previous_locale)

    def test_acceptance_matrix_covers_all_agreed_states_and_rules(self) -> None:
        path = PROJECT_ROOT / "tests" / "references" / "ui_overhaul_acceptance.json"
        matrix = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(matrix["schema_version"], 1)
        self.assertEqual(matrix["animation_duration_ms"], METRICS.animation_duration_ms)
        self.assertEqual(matrix["responsive_breakpoint_px"], METRICS.responsive_breakpoint_px)
        self.assertEqual({state["id"] for state in matrix["states"]}, EXPECTED_STATE_IDS)
        self.assertEqual(len(matrix["states"]), len(EXPECTED_STATE_IDS))
        self.assertIn(
            "preview_progress_is_mirrored_in_both_windows",
            matrix["global_rules"],
        )
        self.assertIn("slicer_sources_are_read_only", matrix["global_rules"])

    def test_section_card_supports_summary_status_badge_and_keyboard_toggle(self) -> None:
        card = SectionCard(
            "Testbereich",
            summary="Kurzinformation",
            collapsible=True,
            expanded=True,
            state=SectionState.SUCCESS,
        )
        body_label = QLabel("Inhalt")
        card.content_layout.addWidget(body_label)
        card.set_badge("1 Fehler", severity="error")
        card.show()
        self.app.processEvents()

        self.assertEqual(card.summary(), "Kurzinformation")
        self.assertEqual(card.property("state"), "success")
        self.assertEqual(card.status_icon.text(), "✓")
        self.assertEqual(card.badge_label.property("severity"), "error")
        self.assertTrue(card.content_widget.isVisible())

        spy = QSignalSpy(card.toggled)
        card.header.setFocus()
        QTest.keyClick(card.header, Qt.Key.Key_Space)
        QTest.qWait(METRICS.animation_duration_ms + 30)
        self.assertFalse(card.isChecked())
        self.assertTrue(card.content_widget.isHidden())
        self.assertEqual(spy.count(), 1)
        card.close()

    def test_responsive_grid_switches_between_two_columns_and_stack(self) -> None:
        grid = ResponsiveCardGrid(breakpoint_px=800)
        left = QLabel("Links")
        right = QLabel("Rechts")
        grid.add_pair(left, right)

        grid.resize(1000, 400)
        grid.show()
        self.app.processEvents()
        left_pos = grid.grid.getItemPosition(grid.grid.indexOf(left))
        right_pos = grid.grid.getItemPosition(grid.grid.indexOf(right))
        self.assertTrue(grid.is_two_column())
        self.assertEqual(left_pos[:2], (0, 0))
        self.assertEqual(right_pos[:2], (0, 1))

        grid.resize(700, 400)
        self.app.processEvents()
        left_pos = grid.grid.getItemPosition(grid.grid.indexOf(left))
        right_pos = grid.grid.getItemPosition(grid.grid.indexOf(right))
        self.assertFalse(grid.is_two_column())
        self.assertEqual(left_pos[:2], (0, 0))
        self.assertEqual(right_pos[:2], (1, 0))
        grid.close()

    def test_main_window_uses_common_cards_and_symmetric_inner_gutters(self) -> None:
        settings_path = Path(self.temporary.name) / "settings.json"
        window = MainWindow(user_settings_path=settings_path)
        self.assertIsInstance(window.source_group, SectionCard)
        self.assertIsInstance(window.slicer_group, SectionCard)
        self.assertIsInstance(window.timing_group, SectionCard)
        self.assertIsInstance(window.geometry_group, SectionCard)
        self.assertIsInstance(window.stability_group, SectionCard)
        margins = window.content_layout.contentsMargins()
        self.assertEqual(margins.left(), METRICS.content_gutter_px)
        self.assertEqual(margins.right(), METRICS.content_gutter_px)

        window.resize(720, 900)
        window.show()
        self.app.processEvents()
        self.assertEqual(window.settings_scroll.horizontalScrollBar().maximum(), 0)
        window.close()

    def test_progressive_workflow_reveals_each_stage_in_order(self) -> None:
        host = QLabel()
        source = SectionCard("G-Code", collapsible=True)
        slicer = SectionCard("Slicer", collapsible=True)
        first = QLabel("Einstellungen")
        second = QLabel("Ergebnis")
        source.setParent(host)
        slicer.setParent(host)
        first.setParent(host)
        second.setParent(host)
        controller = WorkflowController(
            source_card=source,
            slicer_card=slicer,
            downstream_widgets=(first, second),
            parent=host,
            duration_ms=0,
        )

        controller.reset()
        self.assertEqual(controller.stage, WorkflowStage.WAITING_FOR_GCODE)
        self.assertFalse(source.isHidden())
        self.assertTrue(slicer.isHidden())
        self.assertTrue(first.isHidden())

        controller.begin_analysis()
        self.assertEqual(source.summary(), "Analyse läuft")
        controller.analysis_succeeded("datei.gcode · 12 Layer")
        self.app.processEvents()
        self.assertEqual(controller.stage, WorkflowStage.GCODE_READY)
        self.assertFalse(source.isChecked())
        self.assertFalse(slicer.isHidden())

        controller.begin_slicer_search()
        controller.slicer_succeeded("Erkannter Slicer")
        self.app.processEvents()
        self.assertEqual(controller.stage, WorkflowStage.READY)
        self.assertFalse(slicer.isChecked())
        self.assertFalse(first.isHidden())
        self.assertFalse(second.isHidden())

    def test_manual_expansion_is_not_overridden_after_auto_completion(self) -> None:
        host = QLabel()
        source = SectionCard("G-Code", collapsible=True, parent=host)
        slicer = SectionCard("Slicer", collapsible=True, parent=host)
        downstream = QLabel("Einstellungen", host)
        controller = WorkflowController(
            source_card=source,
            slicer_card=slicer,
            downstream_widgets=(downstream,),
            parent=host,
            duration_ms=0,
        )
        controller.reset()
        controller.analysis_succeeded("bereit")
        controller.slicer_succeeded("Slicer")
        slicer.setChecked(True)
        controller.slicer_succeeded("Slicer")
        self.assertTrue(slicer.isChecked())

    def test_missing_slicer_keeps_analytical_workflow_available(self) -> None:
        host = QLabel()
        source = SectionCard("G-Code", collapsible=True, parent=host)
        slicer = SectionCard("Slicer", collapsible=True, parent=host)
        downstream = QLabel("Einstellungen", host)
        controller = WorkflowController(
            source_card=source,
            slicer_card=slicer,
            downstream_widgets=(downstream,),
            parent=host,
            duration_ms=0,
        )
        controller.reset()
        controller.analysis_succeeded("bereit")
        controller.slicer_unavailable("Kein Slicer")
        self.assertEqual(controller.stage, WorkflowStage.DEGRADED)
        self.assertEqual(slicer.state(), SectionState.WARNING)
        self.assertTrue(slicer.isChecked())
        self.assertFalse(downstream.isHidden())

    def test_main_window_starts_with_only_the_gcode_workflow_card(self) -> None:
        settings_path = Path(self.temporary.name) / "settings.json"
        window = MainWindow(user_settings_path=settings_path)
        window.show()
        self.app.processEvents()
        self.assertTrue(window.source_group.isVisible())
        self.assertTrue(window.slicer_group.isHidden())
        self.assertTrue(window.ready_grid.isHidden())
        for widget in (
            window.stl_notice_frame,
            window.timing_group,
            window.prediction_frame,
            window.geometry_settings_group,
            window.geometry_group,
            window.stability_group,
        ):
            self.assertFalse(widget.isVisible())
        self.assertFalse(
            window.background_job_manager.has_active(JobKind.SLICER_DISCOVERY)
        )
        window.close()

    def test_slicer_progress_has_percentage_symbol_and_german_step(self) -> None:
        settings_path = Path(self.temporary.name) / "settings.json"
        window = MainWindow(user_settings_path=settings_path)
        window._set_slicer_progress(
            40,
            "Installierte Slicer werden geprüft …",
            icon="⌛",
            state="running",
        )
        self.assertEqual(window.slicer_progress_bar.value(), 40)
        self.assertEqual(window.slicer_progress_bar.format(), "%p %")
        self.assertIn("Slicer", window.slicer_progress_status_label.text())
        self.assertEqual(window.slicer_progress_icon_label.text(), "⌛")
        window.close()


if __name__ == "__main__":
    unittest.main()
