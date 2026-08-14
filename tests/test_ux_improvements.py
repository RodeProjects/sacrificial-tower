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
        window.full_infill_checkbox.setChecked(True)
        self.assertEqual(
            window.full_infill_hint.text(),
            "Der gemeinsame Testslice und das exportierte 3MF weisen im "
            "Slicer nur dem Kühlturm objektspezifisch 100 % Fülldichte zu.",
        )
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

    def test_05_preview_has_legend_fit_label_purple_progress_and_stale_state(self) -> None:
        window = self.window()
        dialog = window.preview_dialog
        dialog.show()
        self.app.processEvents()
        self.assertEqual(dialog.object_legend.text(), "■ Objekt")
        self.assertEqual(dialog.tower_legend.text(), "■ Kühlturm")
        self.assertEqual(dialog.bed_legend.text(), "■ Druckplatte")
        self.assertEqual(dialog.fit_button.text(), "Gesamte Druckplatte anzeigen")

        dialog.set_building("Geometrie wird vorbereitet …")
        dialog.set_progress(48, "Werkzeugwege werden ausgewertet …")
        self.app.processEvents()
        self.assertEqual(dialog.progress.objectName(), "previewProgressBar")
        self.assertEqual(dialog.progress.value(), 48)
        self.assertEqual(dialog.progress.format(), "%p %")
        self.assertEqual(dialog.progress_status_icon.text(), "⏳")
        self.assertGreater(
            dialog.progress_status_widget.mapTo(dialog, QPoint(0, 0)).y(),
            dialog.progress.mapTo(dialog, QPoint(0, 0)).y(),
        )
        stylesheet = window.styleSheet().casefold()
        self.assertIn("qprogressbar#previewprogressbar::chunk", stylesheet)
        self.assertIn("#8158c7", stylesheet)

        dialog.canvas.set_scene(_preview_scene())
        dialog.mark_stale()
        self.assertEqual(dialog.state, PreviewState.STALE)
        self.assertIn("Vorschau nicht mehr aktuell", dialog.state_label.text())
        self.assertEqual(dialog.state_label.property("state"), "stale")

        window.current_preview = SimpleNamespace()
        window.preview_state = PreviewState.CURRENT
        window._invalidate_preview("Ein Wert wurde geändert.")
        self.assertIn("Vorschau nicht mehr aktuell", window.preview_hint_label.text())
        self.assertEqual(window.preview_hint_label.property("state"), "stale")
        window.current_preview = None
        window.close()

    def test_06_stale_preview_dialog_has_exactly_the_three_requested_actions(self) -> None:
        window = self.window()
        box = window._create_stale_preview_message_box()
        buttons = [button.text() for button in box.buttons()]
        self.assertCountEqual(buttons, ["Ja", "Vorschau aktualisieren", "Nein"])
        self.assertEqual(len(buttons), 3)
        self.assertIs(box.defaultButton(), box._stale_no_button)
        box.close()
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
