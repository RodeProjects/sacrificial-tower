from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("COOLING_TOWER_DISABLE_SLICER_DISCOVERY", "1")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from cooling_tower.gui.main_window import MainWindow
from cooling_tower.gui.widgets import SectionState
from cooling_tower.gui.workflow_controller import WorkflowStage


class PreparationWorkflowUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.app.processEvents()
        self.temporary.cleanup()

    def window(self) -> MainWindow:
        return MainWindow(
            user_settings_path=self.root / "settings.json",
            enable_update_check=False,
        )

    def test_completed_header_uses_one_column_with_filename_first(self) -> None:
        window = self.window()
        window.resize(1400, 900)
        window.show()
        window.current_source_path = self.root / "modell.stl"
        installation = SimpleNamespace(
            display_name="Test Slicer",
            identity_key="test-slicer",
        )
        window.slicer_discovery_result = SimpleNamespace(
            installations=(installation,)
        )
        window._populating_slicer_combo = True
        window.slicer_combo.clear()
        window.slicer_combo.addItem(
            installation.display_name,
            installation.identity_key,
        )
        window._populating_slicer_combo = False
        window._populating_profile_combos = True
        for combo, text in (
            (window.machine_profile_combo, "Drucker A"),
            (window.filament_profile_combo, "PLA"),
            (window.process_profile_combo, "Qualität"),
        ):
            combo.clear()
            combo.addItem(text)
        window._populating_profile_combos = False

        window._refresh_preparation_header_summary(True)
        self.app.processEvents()

        left = window.workflow_group.split_summary_left
        right = window.workflow_group.split_summary_right
        self.assertNotIn("Dateiname", left.text())
        self.assertNotIn("Dateityp", left.text())
        self.assertTrue(left.isHidden())
        summary = right.text()
        expected_order = (
            "Dateiname",
            "modell.stl",
            "Slicer",
            "Test Slicer",
            "Maschinenprofil",
            "Filamentprofil",
            "Prozessprofil",
        )
        positions = [summary.index(value) for value in expected_order]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn("Dateityp", summary)

        self.assertLessEqual(right.width(), right.sizeHint().width() + 1)
        self.assertLessEqual(
            abs(
                right.geometry().right()
                - window.workflow_group.split_summary_widget.rect().right()
            ),
            1,
        )

        long_name = (
            "DiesIstEinBeispiel_FürEinenLangenDateinamen_"
            "UndDieserKönnteNochVielLängerSein.stl"
        )
        window.current_source_path = self.root / long_name
        window.resize(720, 900)
        window._refresh_preparation_header_summary(True)
        QTest.qWait(30)
        self.app.processEvents()
        narrow_summary = right.text()
        self.assertIn("...", narrow_summary)
        self.assertIn(".stl", narrow_summary)
        self.assertNotIn(long_name, narrow_summary)
        self.assertEqual(right.toolTip(), long_name)
        window.close()

    def test_wide_and_narrow_preparation_layout_keep_required_order(self) -> None:
        window = self.window()
        window.resize(1400, 900)
        window.show()
        QTest.qWait(30)
        self.app.processEvents()

        split = window.preparation_split
        self.assertTrue(split.is_two_column())
        self.assertEqual(
            split.grid.getItemPosition(split.grid.indexOf(window.source_group)),
            (0, 0, 1, 1),
        )
        self.assertEqual(
            split.grid.getItemPosition(split.grid.indexOf(window.slicer_group)),
            (0, 2, 1, 1),
        )
        self.assertTrue(window.preparation_vertical_divider.isVisibleTo(window))
        self.assertTrue(window.preparation_horizontal_divider.isHidden())
        self.assertEqual(
            window.workflow_group.content_layout.contentsMargins(),
            window.geometry_settings_group.content_layout.contentsMargins(),
        )
        source_margins = window.source_group.content_layout.contentsMargins()
        slicer_margins = window.slicer_group.content_layout.contentsMargins()
        self.assertEqual(
            (
                source_margins.left(),
                source_margins.top(),
                source_margins.right(),
                source_margins.bottom(),
            ),
            (20, 10, 15, 10),
        )
        self.assertEqual(
            (
                slicer_margins.left(),
                slicer_margins.top(),
                slicer_margins.right(),
                slicer_margins.bottom(),
            ),
            (15, 10, 20, 10),
        )
        self.assertEqual(
            window.source_group.header.height(),
            window.slicer_group.header.height(),
        )
        window.source_group.set_state(SectionState.ERROR)
        self.app.processEvents()
        self.assertEqual(
            window.source_group.status_icon.height(),
            max(18, window.source_group.title_label.sizeHint().height()),
        )
        window.source_group.set_state(SectionState.ACTIVE)
        source_progress_y = window.gcode_progress_bar.mapTo(
            window.workflow_group,
            QPoint(0, 0),
        ).y()
        slicer_progress_y = window.slicer_progress_bar.mapTo(
            window.workflow_group,
            QPoint(0, 0),
        ).y()
        self.assertEqual(source_progress_y, slicer_progress_y)
        self.assertLess(
            window.workflow_group.content_layout.indexOf(
                window.preparation_overview
            ),
            window.workflow_group.content_layout.indexOf(
                window.preparation_split
            ),
        )
        window.workflow_group.set_split_summary_columns(
            (("Dateiname", "modell.stl"), ("Dateityp", "Binär-STL")),
            (
                ("Slicer", "Test Slicer"),
                ("Maschinenprofil", "Drucker A"),
                ("Filamentprofil", "PLA"),
                ("Prozessprofil", "Qualität"),
            ),
        )
        self.app.processEvents()
        self.assertFalse(window.workflow_group.split_summary_widget.isHidden())
        self.assertIn("modell.stl", window.workflow_group.split_summary_left.text())
        self.assertIn("Drucker A", window.workflow_group.split_summary_right.text())
        self.assertTrue(
            window.workflow_group.split_summary_left.alignment()
            & Qt.AlignmentFlag.AlignRight
        )
        self.assertIn(
            'td align="right"',
            window.workflow_group.split_summary_left.text(),
        )
        self.assertIn(
            'td align="left"',
            window.workflow_group.split_summary_right.text(),
        )
        self.assertGreater(
            window.workflow_group.header.height(),
            window.source_group.header.height(),
        )
        window.resize(720, 900)
        QTest.qWait(50)
        self.app.processEvents()
        self.assertTrue(window.workflow_group.split_summary_left.isHidden())
        self.assertFalse(window.workflow_group.split_summary_right.isHidden())
        window.resize(1400, 900)
        QTest.qWait(50)
        self.app.processEvents()
        self.assertFalse(window.workflow_group.split_summary_left.isHidden())
        window.workflow_group.set_split_summary_columns((), ())
        requirements = window.preparation_requirements
        self.assertTrue(requirements.is_two_column())
        self.assertEqual(requirements.grid.count(), 2)
        self.assertEqual(
            requirements.grid.getItemPosition(
                requirements.grid.indexOf(
                    window.preparation_source_requirements
                )
            ),
            (0, 0, 1, 1),
        )
        self.assertEqual(
            requirements.grid.getItemPosition(
                requirements.grid.indexOf(
                    window.preparation_slicer_requirements
                )
            ),
            (0, 1, 1, 1),
        )
        wide_requirements_height = requirements.minimumHeight()
        source_keys = (
            "source_selected",
            "source_analyzed",
            "profiles_source_validated",
        )
        slicer_keys = (
            "slicer_detected",
            "profiles_loaded",
            "profiles_confirmed",
        )
        self.assertTrue(
            all(
                window.preparation_requirement_rows[key][0].parent()
                is window.preparation_source_requirements
                for key in source_keys
            )
        )
        self.assertTrue(
            all(
                window.preparation_requirement_rows[key][0].parent()
                is window.preparation_slicer_requirements
                for key in slicer_keys
            )
        )

        window.resize(800, 900)
        QTest.qWait(50)
        self.app.processEvents()
        self.assertFalse(split.is_two_column())
        self.assertEqual(
            split.grid.getItemPosition(split.grid.indexOf(window.source_group)),
            (0, 0, 1, 3),
        )
        self.assertEqual(
            split.grid.getItemPosition(
                split.grid.indexOf(window.preparation_horizontal_divider)
            ),
            (1, 0, 1, 3),
        )
        self.assertEqual(
            split.grid.getItemPosition(split.grid.indexOf(window.slicer_group)),
            (2, 0, 1, 3),
        )
        self.assertTrue(window.preparation_vertical_divider.isHidden())
        self.assertTrue(window.preparation_horizontal_divider.isVisibleTo(window))
        self.assertFalse(requirements.is_two_column())
        self.assertEqual(requirements.grid.count(), 2)
        self.assertEqual(
            requirements.grid.getItemPosition(
                requirements.grid.indexOf(
                    window.preparation_slicer_requirements
                )
            ),
            (0, 0, 1, 2),
        )
        self.assertEqual(
            requirements.grid.getItemPosition(
                requirements.grid.indexOf(
                    window.preparation_source_requirements
                )
            ),
            (1, 0, 1, 2),
        )
        self.assertGreater(
            requirements.minimumHeight(),
            wide_requirements_height,
        )
        for card in (window.source_group, window.slicer_group):
            margins = card.content_layout.contentsMargins()
            self.assertEqual(
                (
                    margins.left(),
                    margins.top(),
                    margins.right(),
                    margins.bottom(),
                ),
                (20, 10, 20, 10),
            )
        window.close()

    def test_progress_blocks_are_first_and_details_are_secondary(self) -> None:
        window = self.window()
        self.assertEqual(
            window.source_group.content_layout.indexOf(window.gcode_progress_bar),
            0,
        )
        self.assertEqual(
            window.slicer_group.content_layout.indexOf(window.slicer_progress_bar),
            0,
        )
        self.assertTrue(window.gcode_progress_bar.isHidden())
        self.assertTrue(window.slicer_progress_bar.isHidden())
        window.gcode_progress_bar.show()
        window._set_slicer_progress(
            40,
            "Profile werden geladen",
            icon="⌛",
            state="running",
        )
        self.assertFalse(window.gcode_progress_bar.isHidden())
        self.assertFalse(window.slicer_progress_bar.isHidden())
        window._finish_source_progress(completed=True)
        window._set_slicer_progress(
            100,
            "Profile geladen",
            icon="✓",
            state="success",
        )
        self.assertTrue(window.gcode_progress_bar.isHidden())
        self.assertTrue(window.slicer_progress_bar.isHidden())
        self.assertTrue(window.slicer_analysis_details.isHidden())

        self.assertEqual(window.preparation_progress_bar.value(), 0)
        self.assertEqual(len(window.preparation_requirement_rows), 6)
        for icon, _label in window.preparation_requirement_rows.values():
            self.assertEqual(icon.text(), "✕")

        layout = window.slicer_selectors_layout
        ordered_widgets = (
            window.slicer_selection_label,
            window.slicer_combo,
            window.machine_profile_label,
            window.machine_profile_combo,
            window.filament_profile_label,
            window.filament_profile_combo,
            window.process_profile_label,
            window.process_profile_combo,
        )
        indices = [layout.indexOf(widget) for widget in ordered_widgets]
        self.assertEqual(indices, sorted(indices))

        window.slicer_analysis_details_toggle.click()
        self.app.processEvents()
        self.assertFalse(window.slicer_analysis_details.isHidden())
        self.assertIn(
            "ausblenden",
            window.slicer_analysis_details_toggle.accessibleName(),
        )
        window.close()

    def test_detail_disclosures_stay_at_the_bottom_of_both_columns(self) -> None:
        window = self.window()
        window.resize(1400, 900)
        window.show()
        window.stl_validation_details_toggle.show()
        window._refresh_preparation_section_layout()
        QTest.qWait(30)
        self.app.processEvents()

        for group, toggle in (
            (window.source_group, window.stl_validation_details_toggle),
            (window.slicer_group, window.slicer_analysis_details_toggle),
        ):
            bottom_gap = (
                group.content_widget.rect().bottom()
                - toggle.geometry().bottom()
            )
            self.assertLessEqual(
                bottom_gap,
                group.content_layout.contentsMargins().bottom() + 1,
            )
        self.assertEqual(
            window.stl_validation_details_toggle.mapTo(window, QPoint(0, 0)).y(),
            window.slicer_analysis_details_toggle.mapTo(window, QPoint(0, 0)).y(),
        )
        window.close()

    def test_only_double_success_unlocks_and_collapses_the_workflow(self) -> None:
        window = self.window()
        window.show()
        self.app.processEvents()
        gated_actions = (
            window.open_output_button,
            window.open_stl_button,
            window.preview_action_control,
            window.export_button,
        )
        self.assertTrue(all(widget.isHidden() for widget in gated_actions))

        window.workflow.source_validation_succeeded(
            "modell.stl · Geometrie gültig",
            analysis_complete=False,
        )
        window.workflow.slicer_succeeded("Testslicer")
        self.assertIs(window.workflow.stage, WorkflowStage.DISCOVERING_SLICER)
        self.assertTrue(window.workflow_group.isChecked())
        self.assertTrue(all(widget.isHidden() for widget in gated_actions))

        window.workflow.reset()
        window.workflow.analysis_succeeded("modell.gcode · 20 Layer")
        self.assertIs(window.workflow.stage, WorkflowStage.DISCOVERING_SLICER)
        self.assertTrue(window.workflow_group.isChecked())
        self.assertTrue(all(widget.isHidden() for widget in gated_actions))

        window.workflow.slicer_unavailable("Kein Slicer bestätigt")
        self.assertIs(window.workflow.stage, WorkflowStage.DEGRADED)
        self.assertIs(window.workflow_group.state(), SectionState.WARNING)
        self.assertTrue(window.workflow_group.isChecked())
        self.assertTrue(all(widget.isHidden() for widget in gated_actions))

        window.workflow.slicer_succeeded("Testslicer")
        self.app.processEvents()
        self.assertIs(window.workflow.stage, WorkflowStage.READY)
        self.assertIs(window.workflow_group.state(), SectionState.SUCCESS)
        self.assertEqual(window.workflow_group.status_icon.text(), "✓")
        self.assertEqual(
            window.workflow_group.summary(),
            "Vorbereitung abgeschlossen",
        )
        self.assertFalse(window.workflow_group.isChecked())
        self.assertTrue(all(widget.isVisible() for widget in gated_actions))

        window.workflow.begin_analysis()
        self.app.processEvents()
        self.assertIs(window.workflow.stage, WorkflowStage.ANALYZING_GCODE)
        self.assertTrue(window.workflow_group.isChecked())
        self.assertTrue(all(widget.isHidden() for widget in gated_actions))
        window.close()


if __name__ == "__main__":
    unittest.main()
