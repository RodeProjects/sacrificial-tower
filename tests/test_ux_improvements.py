from __future__ import annotations

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("COOLING_TOWER_DISABLE_SLICER_DISCOVERY", "1")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QTextDocument, QTextFormat, QTextTable
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from cooling_tower.gui.main_window import MainWindow
from cooling_tower.gui.preview_dialog import PreviewDialog
from cooling_tower.gui.widgets import SourceDropZone
from cooling_tower.models import (
    BedBounds,
    CalibrationConfig,
    CalibrationMode,
    GenerationSettings,
    ProfileFeasibilityAssessment,
    SourceKind,
)
from cooling_tower.preview import (
    LineSegment3D,
    OutputMode,
    Point3D,
    PreviewExportService,
    PreviewRequest,
    PreviewScene,
    PreviewService,
    PreviewState,
)
from cooling_tower.services import GCodeAnalysisService, assess_tower_need


def _source_gcode() -> str:
    return """; ux regression fixture
G90
M83
M204 S1000
G1 Z0.20 F600
G1 X10 Y10 E0.4 F900
G1 X20 Y10 E0.4 F900
G1 Z0.40 F600
G1 X20 Y20 E0.4 F900
G1 X10 Y20 E0.4 F900
"""


def _preview_scene() -> PreviewScene:
    return PreviewScene(
        (
            LineSegment3D(
                Point3D(0.0, 0.0, 0.2),
                Point3D(10.0, 10.0, 0.2),
            ),
        ),
        (
            LineSegment3D(
                Point3D(20.0, 20.0, 0.0),
                Point3D(20.0, 20.0, 5.0),
            ),
        ),
        BedBounds(0.0, 100.0, 0.0, 100.0),
        (20.0, 20.0),
        1,
        1,
        5.0,
    )


class UxImprovementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "mein objekt.gcode"
        self.source.write_text(_source_gcode(), encoding="utf-8")
        self.snapshot = GCodeAnalysisService().analyze(self.source)

    def tearDown(self) -> None:
        self.app.processEvents()
        self.temporary.cleanup()

    def window(self) -> MainWindow:
        return MainWindow(user_settings_path=self.root / "user_settings.json")

    def ready_window(self) -> MainWindow:
        window = self.window()
        window.current_gcode_path = self.source.resolve()
        window.analysis_snapshot = self.snapshot
        window.tower_assessment = assess_tower_need(
            self.snapshot, window.collect_settings()
        )
        return window

    def request(self) -> PreviewRequest:
        return PreviewRequest(
            snapshot=self.snapshot,
            settings=GenerationSettings(),
            output_mode=OutputMode.STL,
            calibration_config=CalibrationConfig(mode=CalibrationMode.STL),
            maximum_object_segments=200,
        )

    def test_01_full_infill_hint_explains_object_specific_joint_project(self) -> None:
        window = self.window()
        hint = window.full_infill_info_button.toolTip()
        self.assertIn("<table", hint)
        self.assertIn("Sollte ich diese Einstellung aktivieren?", hint)
        self.assertIn("Welchen Druckertyp habe ich?", hint)
        self.assertIn("Aktiviert", hint)
        self.assertIn("Deaktiviert", hint)
        self.assertIn("nur für den Kühlturm", hint)
        self.assertIn("Bettschubser", hint)
        self.assertIn("Druckbett bewegt das Modell", hint)
        self.assertIn("CoreXY", hint)
        self.assertIn("Druckkopf übernimmt", hint)
        self.assertIn("<b>Aktivierung empfohlen.</b>", hint)
        self.assertIn("- Mehr Material", hint)
        self.assertIn("+ Schmalerer Turm", hint)
        self.assertIn("Vor- und Nachteile dieser Funktion:", hint)
        self.assertNotIn("oft schmalerer", hint.casefold())
        self.assertIn('align="left"', hint)
        self.assertEqual(hint.count("<tr>"), 3)
        self.assertNotIn("Aktuell aktiviert", hint)
        self.assertNotIn("Aktuell deaktiviert", hint)
        self.assertFalse(hasattr(window, "full_infill_hint"))
        window.close()

    def test_01b_full_infill_hint_preserves_selected_spacing_and_column_padding(self) -> None:
        window = self.window()
        document = QTextDocument()
        document.setHtml(window.full_infill_info_button.toolTip())
        blocks = {}
        block = document.firstBlock()
        while block.isValid():
            blocks[block.text()] = block.blockFormat()
            block = block.next()
        first_question = blocks["Sollte ich diese Einstellung aktivieren?"]
        type_question = blocks["Welchen Druckertyp habe ich?"]
        answer = next(
            format_
            for text, format_ in blocks.items()
            if "Bettschubser: Das Druckbett bewegt" in text
        )
        self.assertTrue(
            type_question.alignment() & Qt.AlignmentFlag.AlignLeft
        )
        self.assertEqual(first_question.bottomMargin(), 0)
        self.assertEqual(type_question.bottomMargin(), first_question.bottomMargin())
        self.assertEqual(answer.bottomMargin(), 8)
        hint = window.full_infill_info_button.toolTip()
        self.assertIn("Die 100%-Füllung gilt nur für den Kühlturm", hint)
        self.assertIn("temporäre Profilkopien", hint)
        self.assertIn("Die Originalprofile bleiben unverändert", hint)
        self.assertEqual(hint.count("<u>"), 3)
        self.assertEqual(hint.count("</u>"), 3)

        frames = document.rootFrame().begin()
        table = None
        while not frames.atEnd():
            frame = frames.currentFrame()
            if isinstance(frame, QTextTable):
                table = frame
                break
            frames += 1
        self.assertIsNotNone(table)
        layout = document.documentLayout()
        table_title_block = document.firstBlock()
        while (table_title_block.isValid()
               and "Vor- und Nachteile dieser Funktion:" not in table_title_block.text()):
            table_title_block = table_title_block.next()
        table_header = table.cellAt(0, 0).firstCursorPosition().block()
        last_row_bottom = max(
            layout.blockBoundingRect(
                table.cellAt(table.rows() - 1, column).firstCursorPosition().block()
            ).bottom()
            for column in range(table.columns())
        )
        final_paragraph = document.lastBlock()
        heading_to_table_gap = (
            layout.blockBoundingRect(table_header).top()
            - layout.blockBoundingRect(table_title_block).bottom()
        )
        table_to_final_gap = (
            layout.blockBoundingRect(final_paragraph).top() - last_row_bottom
        )
        self.assertEqual(heading_to_table_gap, 10)
        self.assertEqual(table_to_final_gap, 16)
        for row in range(table.rows()):
            first_cell = table.cellAt(row, 0).format()
            self.assertEqual(
                first_cell.property(QTextFormat.Property.TableCellLeftPadding),
                0,
            )
            for column in (1, 2):
                cell = table.cellAt(row, column).format()
                self.assertGreaterEqual(
                    cell.property(QTextFormat.Property.TableCellLeftPadding),
                    12,
                )
                self.assertGreaterEqual(
                    cell.property(QTextFormat.Property.TableCellRightPadding),
                    12,
                )
        window.close()

    def test_setting_info_icons_precede_controls(self) -> None:
        window = self.window()
        window.workflow.set_slicer_step_visible(True)
        window.workflow.source_validation_succeeded(
            "referenz.stl geprüft", analysis_complete=True
        )
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.resize(1300, 900)
        window.show()
        self.app.processEvents()
        for setting in window._setting_widgets.values():
            self.assertEqual(setting.info_button.width(), 19)
            self.assertEqual(setting.info_button.height(), 19)
            if not setting.isVisible() or setting.info_button.isHidden():
                continue
            info_right = setting.info_button.mapTo(
                window, setting.info_button.rect().topRight()
            ).x()
            text_control = (
                window.automatic_base_checkbox
                if setting.setting_name == "manual_base_width_mm"
                else setting.label
            )
            label_left = text_control.mapTo(
                window, text_control.rect().topLeft()
            ).x()
            self.assertEqual(label_left - info_right - 1, 10)
            self.assertLess(
                setting.info_button.mapTo(window, setting.info_button.rect().center()).x(),
                text_control.mapTo(window, text_control.rect().center()).x(),
            )
            self.assertLessEqual(
                abs(
                    setting.info_button.mapTo(window, setting.info_button.rect().center()).y()
                    - text_control.mapTo(window, text_control.rect().center()).y()
                ),
                1,
            )
        for info_button, checkbox in (
            (window.full_infill_info_button, window.full_infill_checkbox),
            (window.automatic_base_info_button, window.automatic_base_checkbox),
        ):
            self.assertEqual(info_button.width(), 19)
            self.assertEqual(info_button.height(), 19)
            self.assertEqual(
                checkbox.mapTo(window, checkbox.rect().topLeft()).x()
                - info_button.mapTo(window, info_button.rect().topRight()).x()
                - 1,
                10,
            )
            self.assertLess(
                info_button.mapTo(window, info_button.rect().center()).x(),
                checkbox.mapTo(window, checkbox.rect().topLeft()).x(),
                checkbox.objectName(),
            )
            self.assertLessEqual(
                abs(
                    info_button.mapTo(window, info_button.rect().center()).y()
                    - checkbox.mapTo(window, checkbox.rect().center()).y()
                ),
                1,
            )
        self.assertEqual(window.output_root_info_button.width(), 19)
        window.close()

    def test_01c_base_hint_explains_automatic_and_manual_width(self) -> None:
        window = self.window()
        hint = window.automatic_base_info_button.toolTip()
        document = QTextDocument()
        document.setHtml(hint)
        text = document.toPlainText()
        self.assertIn("0,21 mm Breite je 1 mm Original-Objekthöhe", text)
        self.assertIn("Automatische Standfußbreite", text)
        self.assertIn("Manuelle Standfußbreite", text)
        self.assertIn("mindestens 25 mm und höchstens 80 mm", text)
        self.assertIn("Grenzbereich: Manuell einstellbar zwischen 20 und 80mm.", text)
        self.assertIn(
            "Ein breiterer Standfuß verbessert Druckbett-Haftung und Turmstabilität",
            text,
        )
        self.assertNotIn("Eingabe:", text)
        self.assertNotIn("Empfehlung:", text)
        self.assertNotIn("% der Objekthöhe", text)
        self.assertNotIn("Fußrand", text)
        self.assertNotIn("verjüngt", text)
        self.assertEqual(hint.count("&#8226;"), 4)
        self.assertNotIn("<li>", hint)
        self.assertEqual(hint.count('margin-top:0; margin-bottom:0px;'), 2)

        window.analysis_snapshot = SimpleNamespace(maximum_print_z_mm=150.0)
        window._update_automatic_base_width_preview()
        self.assertEqual(window.automatic_base_info_button.toolTip(), hint)
        self.assertIn(
            "Manuell einstellbar zwischen 20 und 80 Millimetern",
            window.automatic_base_info_button.accessibleDescription(),
        )
        window.close()

    def test_rich_hint_popover_does_not_grow_when_switching_hints(self) -> None:
        window = self.window()
        window.show()
        self.app.processEvents()
        buttons = (
            window.full_infill_info_button,
            window.simulate_tower_without_supports_info_button,
            window.automatic_base_info_button,
            window._setting_widgets["target_layer_time_s"].info_button,
        )
        first_sizes = {}
        try:
            for _ in range(3):
                for button in buttons:
                    button.show_hint()
                    self.app.processEvents()
                    popover = window._bounded_hint_popover
                    size = popover.size()
                    if button.toolTip().lstrip().startswith("<"):
                        document = QTextDocument()
                        document.setDefaultFont(popover.label.font())
                        document.setDocumentMargin(0)
                        document.setHtml(button.toolTip())
                        document.setTextWidth(popover.label.width())
                        unused_height = popover.label.height() - document.size().height()
                        self.assertGreaterEqual(unused_height, 0)
                        self.assertLessEqual(
                            unused_height,
                            1,
                        )
                    if button in first_sizes:
                        self.assertEqual(size, first_sizes[button])
                    else:
                        first_sizes[button] = size
                    self.assertTrue(
                        popover.label.alignment() & Qt.AlignmentFlag.AlignTop
                    )
        finally:
            window.close()

    def test_01a_full_infill_checkbox_does_not_move_on_hover(self) -> None:
        window = self.window()
        window.resize(900, 800)
        window.show()
        self.app.processEvents()
        checkbox = window.full_infill_checkbox
        before_geometry = checkbox.geometry()
        before_hint = checkbox.sizeHint()

        QTest.mouseMove(checkbox, checkbox.rect().center())
        self.app.processEvents()

        self.assertEqual(checkbox.geometry(), before_geometry)
        self.assertEqual(checkbox.sizeHint(), before_hint)
        window.close()

    def test_02_source_information_rows_remove_action_and_progress(self) -> None:
        drop_zone = SourceDropZone()
        drop_zone.resize(900, SourceDropZone.EMPTY_MINIMUM_HEIGHT_PX)
        drop_zone.show()
        self.app.processEvents()
        empty_height = drop_zone.height()
        prompt_top = drop_zone.prompt_label.mapTo(drop_zone, QPoint(0, 0)).y()
        actions_top = drop_zone.actions_widget.mapTo(
            drop_zone, QPoint(0, 0)
        ).y()
        actions_bottom = actions_top + drop_zone.actions_widget.height()
        bottom_gap = drop_zone.height() - actions_bottom
        prompt_bottom = prompt_top + drop_zone.prompt_label.height()
        self.assertGreaterEqual(empty_height, 260)
        self.assertLessEqual(abs(prompt_top - bottom_gap), 2)
        self.assertGreaterEqual(actions_top - prompt_bottom, 18)
        self.assertTrue(drop_zone.info_widget.isHidden())
        self.assertFalse(drop_zone.prompt_label.isHidden())
        self.assertTrue(drop_zone.reload_button.isHidden())
        self.assertTrue(drop_zone.remove_button.isHidden())
        removed: list[bool] = []
        drop_zone.remove_requested.connect(lambda: removed.append(True))
        stl_source = (
            PROJECT_ROOT / "tests" / "fixtures" / "stl" / "test_model_manifold.stl"
        )
        self.assertTrue(drop_zone.set_file(stl_source))
        self.app.processEvents()
        self.assertEqual(
            drop_zone.status_value_label.text(),
            "STL-Modell erkannt – Geometrie wird geprüft",
        )
        self.assertEqual(drop_zone.file_name_label.text(), stl_source.name)
        self.assertNotEqual(drop_zone.file_size_label.text(), "–")
        self.assertEqual(drop_zone.file_path_label.text(), str(stl_source.resolve()))
        self.assertTrue(drop_zone.file_path_label.wordWrap())
        self.assertFalse(drop_zone.info_widget.isHidden())
        self.assertTrue(drop_zone.actions_widget.isHidden())
        drop_zone.set_status("Analyse abgeschlossen")
        drop_zone.set_analysis_state("ready")
        self.app.processEvents()
        self.assertEqual(drop_zone.remove_button.text(), "STL entfernen")
        self.assertTrue(drop_zone.remove_button.isEnabled())
        self.assertFalse(drop_zone.reload_button.isHidden())
        self.assertFalse(drop_zone.remove_button.isHidden())
        drop_zone.remove_button.click()
        self.assertEqual(removed, [True])
        drop_zone.clear_file()
        self.app.processEvents()
        self.assertFalse(drop_zone.remove_button.isEnabled())
        self.assertEqual(drop_zone.status_value_label.text(), "Keine Datei ausgewählt")
        self.assertTrue(drop_zone.info_widget.isHidden())
        self.assertTrue(drop_zone.reload_button.isHidden())
        self.assertTrue(drop_zone.remove_button.isHidden())
        self.assertGreaterEqual(drop_zone.height(), empty_height)
        drop_zone.close()

        window = self.window()
        window.show()
        self.assertIs(
            window.stl_validation_message.parent(),
            window.source_group.content_widget,
        )
        self.assertIs(
            window.stl_validation_details_toggle.parent(),
            window.source_group.content_widget,
        )
        source_layout = window.source_group.content_layout
        self.assertLess(
            source_layout.indexOf(window.drop_zone),
            source_layout.indexOf(window.stl_validation_details_toggle),
        )
        self.assertLess(
            source_layout.indexOf(window.stl_validation_details_toggle),
            source_layout.indexOf(window.stl_validation_details),
        )
        self.assertLess(
            source_layout.indexOf(window.stl_validation_details),
            source_layout.indexOf(window.stl_validation_message),
        )
        self.assertTrue(window.slicer_combo.property("important"))
        self.assertTrue(window.machine_profile_combo.property("important"))
        self.assertTrue(window.filament_profile_combo.property("important"))
        self.assertTrue(window.process_profile_combo.property("important"))
        self.assertIn(
            'QFrame#sourceDropZone[loaded="true"]',
            window.styleSheet(),
        )
        window.close()

    def test_02a_stl_rejected_and_ready_action_states_are_complete(self) -> None:
        source = (
            PROJECT_ROOT
            / "tests"
            / "fixtures"
            / "stl"
            / "test_model_manifold.stl"
        )
        drop_zone = SourceDropZone()
        reload_requests: list[bool] = []
        remove_requests: list[bool] = []
        drop_zone.reload_requested.connect(lambda: reload_requests.append(True))
        drop_zone.remove_requested.connect(lambda: remove_requests.append(True))

        self.assertTrue(drop_zone.set_file(source))
        drop_zone.set_analysis_state("rejected")
        self.app.processEvents()
        self.assertTrue(drop_zone.prompt_label.isHidden())
        self.assertFalse(drop_zone.info_widget.isHidden())
        self.assertFalse(drop_zone.browse_button.isHidden())
        self.assertFalse(drop_zone.reload_button.isHidden())
        self.assertFalse(drop_zone.remove_button.isHidden())
        self.assertTrue(drop_zone.remove_button.isEnabled())
        self.assertEqual(drop_zone.browse_button.text(), "Andere STL auswählen")
        self.assertEqual(drop_zone.reload_button.text(), "STL neu einlesen")
        self.assertEqual(drop_zone.remove_button.text(), "STL entfernen")
        reload_column = drop_zone.actions_layout.getItemPosition(
            drop_zone.actions_layout.indexOf(drop_zone.reload_button)
        )[1]
        remove_column = drop_zone.actions_layout.getItemPosition(
            drop_zone.actions_layout.indexOf(drop_zone.remove_button)
        )[1]
        self.assertGreater(remove_column, reload_column)
        drop_zone.reload_button.click()
        self.assertEqual(reload_requests, [True])

        drop_zone.set_analysis_state("ready")
        self.app.processEvents()
        self.assertTrue(drop_zone.property("completed"))
        self.assertFalse(drop_zone.info_widget.isHidden())
        self.assertFalse(drop_zone.browse_button.isHidden())
        self.assertFalse(drop_zone.reload_button.isHidden())
        self.assertFalse(drop_zone.remove_button.isHidden())
        self.assertEqual(drop_zone.remove_button.text(), "STL entfernen")
        drop_zone.remove_button.click()
        self.assertEqual(remove_requests, [True])

        drop_zone.set_analysis_state("preslice_failed")
        self.app.processEvents()
        self.assertFalse(drop_zone.info_widget.isHidden())
        self.assertTrue(drop_zone.browse_button.isEnabled())
        self.assertTrue(drop_zone.reload_button.isEnabled())
        self.assertTrue(drop_zone.remove_button.isEnabled())
        self.assertFalse(drop_zone.browse_button.isHidden())
        self.assertFalse(drop_zone.reload_button.isHidden())
        self.assertFalse(drop_zone.remove_button.isHidden())
        drop_zone.close()

    def test_03_reconstructed_configuration_starts_collapsed_and_fits_content(self) -> None:
        window = self.window()
        window.show()
        source = (self.root / "reconstructed.stl").resolve()
        source.write_text("solid x\nendsolid x\n", encoding="ascii")
        window.current_source_path = source
        window.current_source_kind = SourceKind.STL
        window.source_artifact = SimpleNamespace(
            original_path=source,
            matches_current_file=lambda: True,
        )
        window.stl_validation_result = SimpleNamespace(valid=True)
        window._update_preparation_requirements()
        items = tuple(
            SimpleNamespace(key=f"wert_{index}", raw_value=f"inhalt_{index}")
            for index in range(12)
        )
        snapshot = SimpleNamespace(metadata=SimpleNamespace(typed_config=items))
        window.slicer_group.show()
        window.preparation_tabs.setCurrentIndex(1)
        window._show_reconstructed_configuration(snapshot)
        self.app.processEvents()
        self.assertFalse(
            window.reconstructed_config_toggle.isVisibleTo(window)
        )
        window.slicer_analysis_details_toggle.click()
        self.app.processEvents()
        self.assertTrue(window.reconstructed_config_toggle.isVisible())
        self.assertFalse(window.reconstructed_config_toggle.isChecked())
        self.assertTrue(window.reconstructed_config_text.isHidden())

        window.reconstructed_config_toggle.click()
        self.app.processEvents()
        self.assertTrue(window.reconstructed_config_text.isVisible())
        self.assertIn("wert_11 = inhalt_11", window.reconstructed_config_text.toPlainText())
        self.assertEqual(
            window.reconstructed_config_text.verticalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )
        document_height = int(
            window.reconstructed_config_text.document().size().height()
        )
        self.assertGreaterEqual(
            window.reconstructed_config_text.height(), document_height
        )
        window.close()

    def test_04_prediction_requires_a_slicer_result(self) -> None:
        window = self.ready_window()
        window.profile_feasibility = ProfileFeasibilityAssessment(
            tower_required=True,
            feasible=True,
            estimated_minimum_combined_layer_time_s=9.25,
        )
        window._refresh_prediction()
        self.assertEqual(
            window.prediction_method_label.text(), "Slicer-Schätzung ausstehend"
        )
        self.assertIn("noch nicht vollständig berechenbar", window.prediction_label.text())
        self.assertEqual(
            window.prediction_value_labels["minimum"].text(),
            "Noch nicht berechenbar",
        )
        self.assertEqual(window.prediction_value_labels["shortfall"].text(), "–")

        window.preview_state = PreviewState.CURRENT
        window.current_preview = SimpleNamespace(
            minimum_verified_layer_time_s=10.5
        )
        window._refresh_prediction()
        slicer = window.prediction_method_label.text()
        self.assertEqual(slicer, "Slicer-gestützte Schätzung")
        for overly_certain_word in ("geprüft", "bestätigt", "garantiert"):
            self.assertNotIn(overly_certain_word, slicer.casefold())
        window.current_preview = None
        window.close()

    def test_05_embedded_preview_avoids_duplicate_progress_and_keeps_stale_state(self) -> None:
        window = self.window()
        dialog = window.preview_dialog
        dialog.show()
        self.app.processEvents()
        self.assertEqual(dialog.object_legend.text(), "■ Objekt")
        self.assertEqual(dialog.tower_legend.text(), "■ Kühlturm")
        self.assertEqual(dialog.bed_legend.text(), "■ Druckplatte")
        self.assertEqual(dialog.three_quarter_button.text(), "3/4-Ansicht")
        self.assertTrue(dialog.three_quarter_button.isHidden())

        dialog.set_building("Geometrie wird vorbereitet …")
        dialog.set_progress(48, "Werkzeugwege werden ausgewertet …")
        self.app.processEvents()
        self.assertEqual(dialog.progress.objectName(), "previewProgressBar")
        self.assertEqual(dialog.progress.value(), 48)
        self.assertEqual(dialog.progress.format(), "%p %")
        self.assertEqual(dialog.progress_status_icon.text(), "⏳")
        self.assertTrue(dialog.progress.isHidden())
        self.assertTrue(dialog.progress_status_widget.isHidden())
        stylesheet = window.styleSheet().casefold()
        self.assertIn("qprogressbar#previewprogressbar::chunk", stylesheet)
        self.assertIn("#8158c7", stylesheet)

        dialog.canvas.set_scene(_preview_scene())
        dialog.mark_stale()
        self.assertFalse(dialog.three_quarter_button.isHidden())
        self.assertEqual(dialog.state, PreviewState.STALE)
        self.assertIn("Veraltet", dialog.state_label.text())
        self.assertEqual(dialog.state_label.property("state"), "stale")

        window.current_preview = SimpleNamespace()
        window.preview_state = PreviewState.CURRENT
        window._invalidate_preview("Ein Wert wurde geändert.")
        self.assertTrue(window.preview_hint_label.isHidden())
        self.assertIn("Veraltet", dialog.state_label.text())
        self.assertNotIn(
            "nicht mehr aktuellen Vorschau",
            dialog.quality_label.text(),
        )
        window.current_preview = None
        window.close()

    def test_06_stale_preview_has_only_the_central_update_action(self) -> None:
        window = self.window()
        window.current_preview = SimpleNamespace()
        window.preview_state = PreviewState.STALE
        window._update_responsive_action_labels()
        self.assertFalse(hasattr(window, "_create_stale_preview_message_box"))
        self.assertEqual(window.preview_button.text(), "Kühlturm aktualisieren")
        self.assertTrue(window.export_button.isHidden())
        window.current_preview = None
        window.close()

    def test_07_reset_prompts_only_for_changes_and_has_two_short_actions(self) -> None:
        window = self.window()
        with patch.object(
            window, "_create_reset_defaults_message_box"
        ) as create_dialog:
            window.request_reset_defaults()
        create_dialog.assert_not_called()

        box = window._create_reset_defaults_message_box()
        buttons = [button.text() for button in box.buttons()]
        self.assertCountEqual(buttons, ["Ja", "Nein"])
        self.assertEqual(len(buttons), 2)
        self.assertIn("gehen dadurch verloren", box.text())
        box.close()

        window.close()

if __name__ == "__main__":
    unittest.main()
