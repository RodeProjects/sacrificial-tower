from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from dataclasses import asdict
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("COOLING_TOWER_DISABLE_SLICER_DISCOVERY", "1")

from PySide6.QtWidgets import QApplication

from cooling_tower.gui.main_window import MainWindow
from cooling_tower.preview import OutputMode, PreviewExportResult, PreviewState


class ExportSessionUiTests(unittest.TestCase):
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
        return MainWindow(user_settings_path=self.root / "settings.json")

    def export_result(self, name: str = "tower.stl") -> PreviewExportResult:
        export_dir = self.root / "export"
        return PreviewExportResult(
            output_mode=OutputMode.STL,
            run_directory=export_dir,
            output_path=export_dir / name,
            report_path=export_dir / "report.json",
            user_report_path=export_dir / "summary.txt",
            calibrated=True,
            slicer_optimized=True,
            minimum_verified_layer_time_s=14.9,
            source_sha256="source",
            output_sha256="output",
            target_layer_time_s=15.0,
        )

    def test_success_report_can_be_reopened_without_export(self) -> None:
        window = self.window()
        try:
            window._export_request_id = 4
            window.current_preview = SimpleNamespace(
                request_signature="generation-a",
                artifact_sha256="tower-a",
                dispose=lambda: None,
            )
            window.preview_state = PreviewState.CURRENT
            result = self.export_result()

            window._on_export_succeeded(4, result)
            self.app.processEvents()
            self.assertEqual(
                window._last_exported_preview_identity,
                ("generation-a", "tower-a"),
            )
            self.assertEqual(window.export_success_cancel_button.text(), "Schließen")
            self.assertEqual(
                window.last_export_report_button.text(),
                "Letzten Exportbericht öffnen",
            )
            self.assertFalse(window.last_export_report_button.isHidden())
            self.assertEqual(
                window.last_export_report_button.accessibleName(),
                "Letzten Exportbericht öffnen",
            )

            window.export_success_cancel_button.click()
            self.assertFalse(window.export_success_dialog.isVisible())
            with patch.object(window, "start_export") as start_export:
                window.last_export_report_button.click()
                self.app.processEvents()
                start_export.assert_not_called()
            self.assertTrue(window.export_success_dialog.isVisible())
            self.assertIn("tower.stl", window.export_success_summary_label.text())
        finally:
            window.close()

    def test_slicer_check_hint_is_hidden_only_for_postprocessor_reports(self) -> None:
        window = self.window()
        try:
            for method, visible in (("automatic", True), ("postprocessor", False),
                    ("manual", True), ("postprocessor", False), ("automatic", True)):
                with self.subTest(method=method):
                    result = SimpleNamespace(**(asdict(self.export_result("model.gcode")) |
                        {"generation_method":method, "output_mode":OutputMode.GCODE, "joint_sliced":False}))
                    window._show_export_success_dialog(result)
                    self.assertEqual(not window.export_success_check_hint.isHidden(), visible)
                    self.assertFalse(window.export_success_usage_label.isHidden())
                    window.export_success_dialog.close()
        finally:
            window.close()

    def test_export_lock_tracks_tower_revision_within_one_generation(self) -> None:
        window = self.window()
        try:
            window.current_preview = SimpleNamespace(
                request_signature="generation-a",
                artifact_sha256="tower-a",
                dispose=lambda: None,
            )
            window.preview_state = PreviewState.CURRENT
            window._last_exported_preview_identity = ("generation-a", "tower-a")
            self.assertTrue(window._current_preview_was_exported())

            window.current_preview = SimpleNamespace(
                request_signature="generation-a",
                artifact_sha256="better-tower-a",
                dispose=lambda: None,
            )
            self.assertFalse(window._current_preview_was_exported())
            with patch.object(window, "_export_block_reason", return_value=None):
                window._refresh_phase17_actions()
            self.assertTrue(window.export_button.isEnabled())
            self.assertTrue(window.joint_generation_dialog.export_button.isEnabled())

            window._last_exported_preview_identity = (
                "generation-a", "better-tower-a"
            )
            self.assertTrue(window._current_preview_was_exported())
            with patch.object(window, "_export_block_reason", return_value=None):
                window._refresh_phase17_actions()
            self.assertFalse(window.export_button.isEnabled())
            self.assertFalse(window.joint_generation_dialog.export_button.isEnabled())

            window.current_preview = SimpleNamespace(
                request_signature="generation-a",
                artifact_sha256="tower-a",
                dispose=lambda: None,
            )
            self.assertFalse(window._current_preview_was_exported())

            request = SimpleNamespace(signature=lambda: "generation-a")
            with (
                patch.object(window, "validate_form"),
                patch.object(window, "_refresh_stl_availability"),
                patch.object(window, "_current_preview_request", return_value=request),
                patch.object(window.background_job_manager, "start_job") as start_job,
            ):
                window.export_button.setEnabled(True)
                window.start_export()
            start_job.assert_called_once()
            self.assertFalse(window.export_button.isEnabled())

            window._last_exported_preview_identity = ("generation-a", "tower-a")
            window.export_button.setEnabled(True)
            with (
                patch.object(window, "validate_form"),
                patch.object(window, "_refresh_stl_availability"),
                patch.object(window, "_current_preview_request", return_value=request),
                patch.object(window.background_job_manager, "start_job") as start_job,
            ):
                window.start_export()
            start_job.assert_not_called()
            self.assertFalse(window.export_button.isEnabled())
        finally:
            window.close()

    def test_exported_generation_notice_preserves_preview_meaning(self) -> None:
        window = self.window()
        try:
            with patch.object(window, "_setting_feedback_is_available", return_value=True):
                window._set_export_button_state(
                    False, "Dieser Generierungsstand wurde bereits exportiert."
                )
            self.assertEqual(
                window.export_availability_label.text(),
                "Erneuter Export nicht nötig: Dieser Generierungsstand wurde bereits exportiert.",
            )
            self.assertFalse(window.export_button.isEnabled())
        finally:
            window.close()

    def test_report_action_uses_its_own_column_and_two_readable_lines(self) -> None:
        window = self.window()
        try:
            report_index = window.main_actions_layout.indexOf(
                window.last_export_report_button
            )
            _row, column, _row_span, _column_span = (
                window.main_actions_layout.getItemPosition(report_index)
            )
            export_folder_index = window.main_actions_layout.indexOf(
                window.open_stl_button
            )
            _row, export_folder_column, _row_span, _column_span = (
                window.main_actions_layout.getItemPosition(export_folder_index)
            )
            self.assertEqual(column, export_folder_column + 1)
            self.assertEqual(
                window.last_export_report_button.text().splitlines(),
                ["Letzten Exportbericht öffnen"],
            )
            self.assertGreaterEqual(
                window.last_export_report_button.sizeHint().height(),
                window.last_export_report_button.fontMetrics().lineSpacing(),
            )
            window.show()
            window.footer.show()
            window.footer_action_area.show()
            for widget in (
                window.open_output_button,
                window.open_stl_button,
                window.last_export_report_button,
                window.preview_action_control,
                window.preview_button,
            ):
                widget.show()
            window.export_button.hide()
            for width in (760, 1040, 1100, 1400):
                window.resize(width, 800)
                self.app.processEvents()
                widgets = (
                    window.open_output_button,
                    window.open_stl_button,
                    window.last_export_report_button,
                    window.preview_action_control,
                )
                bounds = [
                    widget.geometry().translated(
                        widget.parentWidget().mapTo(window, widget.pos())
                        - widget.pos()
                    )
                    for widget in widgets
                ]
                self.assertTrue(all(rect.right() < window.width() for rect in bounds))
                positions = {
                    widget: window.main_actions_layout.getItemPosition(
                        window.main_actions_layout.indexOf(widget)
                    )[:2]
                    for widget in widgets
                }
                report_row = positions[window.last_export_report_button][0]
                folder_row = positions[window.open_output_button][0]
                if window._footer_actions_layout_mode in {
                    "report_above", "report_and_action_same_row",
                    "report_and_action_above",
                }:
                    self.assertLess(report_row, folder_row)
                    self.assertLessEqual(
                        bounds[2].bottom(), min(bounds[0].top(), bounds[1].top())
                    )
                else:
                    self.assertEqual(report_row, folder_row)
        finally:
            window.close()

    def test_button_styles_use_matching_gradients_and_flat_disabled_state(self) -> None:
        style = (SRC_ROOT / "cooling_tower" / "gui" / "styles.qss").read_text(
            encoding="utf-8"
        )
        self.assertIn("QPushButton#exportButton {", style)
        self.assertIn("stop: 0 #35a66c", style)
        self.assertIn("stop: 1 #247f52", style)
        self.assertIn("QPushButton#previewButton {", style)
        self.assertIn("stop: 0 #2f7fb7", style)
        self.assertIn("stop: 1 #1769aa", style)
        self.assertIn("QPushButton:disabled {", style)
        self.assertIn("background: #edf0f2", style)


if __name__ == "__main__":
    unittest.main()
