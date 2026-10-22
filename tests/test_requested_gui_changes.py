from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, PropertyMock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("COOLING_TOWER_DISABLE_SLICER_DISCOVERY", "1")

from PySide6.QtCore import QEvent, QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from cooling_tower.application import append_runtime_diagnostic
from cooling_tower.preview import PreviewState
from cooling_tower.gui.design_tokens import METRICS
from cooling_tower.gui.main_window import (
    MainWindow,
    _concise_operation_failure_reason,
)
from cooling_tower.gui.export_worker import ExportWorker
from cooling_tower.gui.widgets import FooterNoticeDropdown
from cooling_tower.models import SlicerFamily
from cooling_tower.preview import OutputMode, PreviewExportResult
from cooling_tower.slicers.base import classify_profile_source
from cooling_tower.slicers import (
    SlicerCapability,
    SlicerDiscoveryResult,
    SlicerDiscoverySource,
    SlicerGuiState,
    SlicerInstallation,
    SlicerSupportLevel,
)
from cooling_tower.version import APP_VERSION, APP_VERSION_LABEL
from cooling_tower.update import UpdateInfo
from gui_lifecycle import dispose_test_widget


class RequestedGuiChangesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.app.processEvents()

    def window(self) -> MainWindow:
        window = MainWindow(user_settings_path=self.root / "settings.json")
        self.addCleanup(dispose_test_widget, window)
        return window

    def complete_source_step(self, window: MainWindow) -> None:
        window.workflow.set_slicer_step_visible(True)
        window.workflow.source_validation_succeeded(
            "referenz.stl geprüft",
            analysis_complete=True,
        )

    def test_preview_and_export_failures_have_short_visible_causes(self) -> None:
        message = (
            "Das gemeinsame Objekt-/Turm-Projekt konnte nicht sicher geslicet "
            "werden. Slicer-Ausgabe: sparse_infill_pattern: grid doesn't work "
            "at 100%% density"
        )
        reason = _concise_operation_failure_reason(message)
        self.assertEqual(
            reason,
            "Das gewählte Füllmuster ist mit 100 % Turmfüllung nicht kompatibel.",
        )

        window = self.window()
        try:
            window._preview_request_id = 7
            window._on_preview_failed(7, message, "Technische Details")
            self.assertEqual(
                window.status_label.text(),
                f"Vorschau fehlgeschlagen: {reason}",
            )

            window._export_request_id = 8
            with patch.object(window, "_write_gui_error_log"):
                window._on_export_failed(8, message, "Technische Details")
            self.assertEqual(
                window.status_label.text(),
                f"Export fehlgeschlagen: {reason}",
            )
        finally:
            window.close()

    def test_generic_slicer_errors_are_omitted_from_preview_footer(self) -> None:
        from cooling_tower.gui.main_window import _preview_failure_footer_reason
        from cooling_tower.gui.user_messages import german_user_message

        message = (
            "Das gemeinsame Objekt-/Turm-Projekt konnte nicht sicher geslicet "
            "werden. Slicer-Ausgabe: Errors"
        )
        expected = (
            "Das gemeinsame Objekt-/Turm-Projekt konnte nicht sicher geslicet werden."
        )
        self.assertEqual(
            _preview_failure_footer_reason(message),
            expected,
        )
        self.assertEqual(german_user_message(message), expected)
        self.assertIn(
            "Bambu Studio konnte dem gemeinsamen Projekt keine gültige Düse zuordnen.",
            _preview_failure_footer_reason(
                "Das Projekt konnte nicht geslicet werden. "
                "Slicer-Ausgabe: No valid nozzle found"
            ),
        )
        self.assertIn(
            "Slicer-Ausgabe: Unexpected profile key mismatch",
            _preview_failure_footer_reason(
                "Das Projekt konnte nicht geslicet werden. "
                "Slicer-Ausgabe: Unexpected profile key mismatch"
            ),
        )

        window = self.window()
        try:
            window._preview_request_id = 10
            window._on_preview_failed(10, message, "")
            self.assertNotIn("Slicer-Ausgabe: Errors", window.status_label.text())
            self.assertNotIn("Slicer-Ausgabe: Errors", window.preview_dialog.state_label.text())
        finally:
            window.close()

    def test_bambu_nozzle_failure_has_specific_short_german_cause(self) -> None:
        message = (
            "Das gemeinsame Objekt-/Turm-Projekt konnte nicht sicher geslicet "
            "werden. Slicer-Ausgabe: No valid nozzle found. Please check "
            "nozzle count."
        )
        expected = (
            "Bambu Studio konnte dem gemeinsamen Projekt keine gültige "
            "Düse zuordnen."
        )
        self.assertEqual(_concise_operation_failure_reason(message), expected)

        window = self.window()
        try:
            window._export_request_id = 9
            with patch.object(window, "_write_gui_error_log"):
                window._on_export_failed(9, message, "Technische Details")
            self.assertEqual(
                window.status_label.text(),
                f"Export fehlgeschlagen: {expected}",
            )
            self.assertEqual(window.result_label.text(), expected)
        finally:
            window.close()

    def test_export_reuses_the_current_generation_without_slicer_work(self) -> None:
        request = SimpleNamespace(signature=lambda: "current")
        window = self.window()
        preview = SimpleNamespace(request_signature="current")
        window.current_preview = preview
        window.preview_state = window.preview_state.CURRENT
        window.export_button.setEnabled(True)
        try:
            with (
                patch.object(window, "validate_form"),
                patch.object(window, "_refresh_stl_availability"),
                patch.object(
                    window,
                    "_current_preview_request",
                    return_value=request,
                ) as current_request,
                patch.object(
                    window.background_job_manager,
                    "start_job",
                ) as start_job,
            ):
                window.start_export()

            current_request.assert_called_once_with()
            worker = start_job.call_args.kwargs["worker"]
            self.assertIs(worker.preview, preview)
            self.assertIs(worker.request, request)
            self.assertFalse(hasattr(worker, "preview_service"))
            self.assertFalse(hasattr(worker, "fallback_request"))
            self.assertFalse(window._bambu_multinozzle_tower_only_export_active)
            self.assertIn(
                "ohne erneute Slicer-Läufe",
                window.status_label.text(),
            )
        finally:
            window.current_preview = None
            window.close()

    def test_export_worker_never_regenerates_or_falls_back(self) -> None:
        primary_request = SimpleNamespace()
        preview = SimpleNamespace()
        export_service = Mock()
        export_service.export.side_effect = RuntimeError("write failed")
        worker = ExportWorker(
            4,
            preview,
            primary_request,
            self.root,
            export_service,
        )
        succeeded: list[PreviewExportResult] = []
        failed: list[str] = []
        worker.succeeded.connect(lambda _request_id, result: succeeded.append(result))
        worker.failed.connect(
            lambda _request_id, message, _details: failed.append(message)
        )

        worker.run()

        self.assertEqual(succeeded, [])
        self.assertEqual(failed, ["write failed"])
        export_service.export.assert_called_once_with(
            preview,
            primary_request,
            self.root,
        )

    def test_successful_export_offers_the_folder_without_opening_it(self) -> None:
        window = self.window()
        window.show()
        output = self.root / "tower.stl"
        result = PreviewExportResult(
            output_mode=OutputMode.STL,
            run_directory=self.root,
            output_path=output,
            report_path=self.root / "report.json",
            user_report_path=self.root / "summary.txt",
            calibrated=True,
            slicer_optimized=True,
            minimum_verified_layer_time_s=14.9,
            source_sha256="source",
            output_sha256="output",
            target_layer_time_s=15.0,
            calibration_time_tolerance_s=0.2,
            project_path=self.root / "druckprojekt.3mf",
        )
        window._export_request_id = 3
        window.warning_text.setPlainText("• Veralteter technischer Hinweis")
        window._refresh_issue_panels()
        with patch(
            "cooling_tower.gui.main_window.open_directory"
        ) as open_export_directory:
            window._on_export_succeeded(3, result)
            self.app.processEvents()
            open_export_directory.assert_not_called()
            self.assertTrue(window.export_success_dialog.isVisible())
            self.assertEqual(
                window.export_success_deviation_label.text(),
                "Abweichung: -0,1 Sekunden "
                "(innerhalb der Toleranz von ±0,2 Sekunden)",
            )
            self.assertEqual(
                window.export_success_achieved_label.text(),
                "Erreichte Layerzeit: 14,9 von 15 Sekunden",
            )
            self.assertEqual(
                window.export_success_achieved_label.parentWidget().layout().spacing(),
                0,
            )
            self.assertIn(
                "innerhalb der Toleranz von ±0,2 Sekunden",
                window.export_success_deviation_label.text(),
            )
            self.assertIn(
                "(innerhalb der Toleranz",
                window.export_success_deviation_label.text(),
            )
            self.assertFalse(window.warning_text.toPlainText())
            self.assertTrue(window.notice_panel.isHidden())
            self.assertFalse(window.result_label.text())
            self.assertFalse(window.result_label.toolTip())
            saved = window.export_success_summary_label.text()
            self.assertIn("Gespeichert:</p>", saved)
            self.assertIn("<li><b>tower.stl</b></li>", saved)
            self.assertIn("<li><b>druckprojekt.3mf</b></li>", saved)
            usage = window.export_success_usage_label.text()
            self.assertIn("Turm-STL manuell", usage)
            self.assertIn(".3MF-Datei", usage)
            self.assertNotIn("druckprojekt.3mf", usage)
            self.assertIn("Druckobjekt und Kühlturm", usage)
            self.assertIn("inklusive aller simulierten Einstellungen", usage)
            self.assertIn(
                "<b>Wichtig:</b>",
                window.export_success_check_hint.text(),
            )
            self.assertIn(
                "Nachträgliche Änderungen",
                window.export_success_check_hint.text(),
            )
            self.assertIn(
                "zu Abweichungen",
                window.export_success_check_hint.text(),
            )
            window.export_success_open_button.click()
            open_export_directory.assert_called_once_with(self.root.resolve())
        self.assertFalse(window.export_success_dialog.isVisible())
        window.close()

    def test_export_dialog_reports_amount_outside_layer_time_tolerance(self) -> None:
        window = self.window()
        try:
            result = PreviewExportResult(
                output_mode=OutputMode.STL,
                run_directory=self.root,
                output_path=self.root / "tower.stl",
                report_path=self.root / "report.json",
                user_report_path=self.root / "summary.txt",
                calibrated=True,
                slicer_optimized=True,
                minimum_verified_layer_time_s=14.5,
                source_sha256="source",
                output_sha256="output",
                target_layer_time_s=15.0,
                calibration_time_tolerance_s=0.2,
            )
            with patch.object(
                window,
                "_show_internal_dialog_without_flash",
            ):
                window._show_export_success_dialog(result)
            self.assertEqual(
                window.export_success_deviation_label.text(),
                "Abweichung: -0,5 Sekunden "
                "(außerhalb der Toleranz von ±0,2 Sekunden)",
            )
            dialog_layout = window.export_success_dialog.layout()
            self.assertEqual(dialog_layout.contentsMargins().top(), 11)
            self.assertEqual(window.export_success_header_layout.spacing(), 7)
            self.assertIn(
                "<li><b>tower.stl</b></li>",
                window.export_success_summary_label.text(),
            )
        finally:
            window.close()

    def test_footer_status_and_result_wrap_at_wide_layout_boundary(self) -> None:
        window = self.window()
        try:
            window.resize(1182, 900)
            window.show()
            long_status = (
                "Export fehlgeschlagen: Der gemeinsame Präzisionslauf konnte "
                "die ausgewählten Projekt- und Profildaten nicht übernehmen."
            )
            long_result = (
                "Bambu Studio konnte dem gemeinsamen Projekt keine gültige "
                "Düse zuordnen; die Quelldatei selbst ist weiterhin gültig."
            )
            window._set_main_status(long_status, icon="✕", state="error")
            window.result_label.setText(long_result)
            window._schedule_footer_height_update()
            for _ in range(8):
                self.app.processEvents()

            for label in (window.status_label, window.result_label):
                self.assertTrue(label.wordWrap())
                self.assertGreater(label.width(), 0)
                required_height = label.heightForWidth(label.width())
                self.assertGreater(
                    required_height,
                    label.fontMetrics().height(),
                )
                self.assertGreaterEqual(label.height(), required_height)
            self.assertLessEqual(
                window.footer_messages_content.width(),
                window.footer_messages_scroll.viewport().width(),
            )
        finally:
            window.close()

    def test_step_one_stl_hints_colour_only_their_headings(self) -> None:
        stylesheet = (
            PROJECT_ROOT / "src" / "cooling_tower" / "gui" / "styles.qss"
        ).read_text(encoding="utf-8")
        for severity, colour in (
            ("error", "#b42318"),
            ("warning", "#9b6411"),
            ("success", "#176b45"),
        ):
            block_start = stylesheet.index(
                f'QLabel#stlFeedbackTitle[severity="{severity}"]'
            )
            block = stylesheet[
                block_start:stylesheet.index("}", block_start)
            ]
            self.assertIn(f"color: {colour};", block)
        block_start = stylesheet.index('QLabel#stlValidationMessage,')
        block = stylesheet[block_start:stylesheet.index("}", block_start)]
        self.assertIn("background: transparent;", block)
        self.assertIn("border: none;", block)
        self.assertIn("color: #506371;", block)

    @staticmethod
    def write_export_folder(
        output_root: Path,
        name: str,
        created_at: str,
    ) -> Path:
        folder = output_root / name
        folder.mkdir(parents=True)
        output_path = folder / "tower.stl"
        output_path.write_text("solid tower\nendsolid tower\n", encoding="utf-8")
        (folder / "export_summary.txt").write_text(
            "Export erfolgreich\n",
            encoding="utf-8",
        )
        (folder / "export_report.json").write_text(
            json.dumps(
                {
                    "report_type": "cooling_tower_export_diagnostics",
                    "created_at": created_at,
                    "summary": {"export_succeeded": True},
                    "output": {"path": str(output_path)},
                }
            ),
            encoding="utf-8",
        )
        return folder

    def test_header_shows_current_version_below_action_icons(self) -> None:
        window = self.window()
        window.show()
        self.app.processEvents()

        self.assertRegex(APP_VERSION, r"^\d+\.\d+\.\d+$")
        self.assertEqual(window.version_label.text(), APP_VERSION_LABEL)
        self.assertEqual(window.version_label.objectName(), "versionLabel")
        self.assertNotIn("alpha", window.version_label.text().casefold())
        self.assertNotIn("alpha", window.version_label.toolTip().casefold())
        self.assertGreater(
            window.version_label.mapTo(window, QPoint(0, 0)).y(),
            window.options_button.mapTo(window, QPoint(0, 0)).y(),
        )
        # The existing menu/version group centers the menu above the label.
        self.assertLessEqual(
            abs(
                window.version_label.mapTo(window, QPoint()).x() + window.version_label.width() / 2
                - window.options_button.mapTo(window, QPoint()).x() - window.options_button.width() / 2
            ),
            1,
        )
        window.close()

    def test_update_button_appears_below_version_only_for_an_update(self) -> None:
        window = self.window()
        window.show()
        self.app.processEvents()
        self.assertTrue(window.update_button.isHidden())

        window._update_check_request_id = 7
        window._on_update_check_succeeded(
            7,
            UpdateInfo(
                version="0.4.2",
                installer_url=(
                    "https://github.com/RodeProjects/"
                    "sacrificial-tower/releases/download/v0.4.2/"
                    "SacrificialTowerSetup-0.4.2.exe"
                ),
                sha256="0" * 64,
                size_bytes=123,
            ),
        )
        self.app.processEvents()
        self.assertFalse(window.update_button.isHidden())
        self.assertGreater(
            window.update_button.mapTo(window, QPoint(0, 0)).y(),
            window.version_label.mapTo(window, QPoint(0, 0)).y() + window.version_label.height(),
        )

        window._on_update_check_succeeded(7, None)
        self.assertTrue(window.update_button.isHidden())
        window.close()

    def test_verified_update_counts_down_before_installer_and_shutdown(self) -> None:
        window = self.window()
        window._update_download_request_id = 9
        installer = self.root / "SacrificialTowerSetup-test.exe"
        events: list[str] = []
        attempt = Mock()
        attempt.poll.return_value = ("starting", "")
        attempt.commit.side_effect = lambda: events.append("freigeben")

        with (
            patch(
                "cooling_tower.gui.main_window.UpdateRestartCountdownDialog"
            ) as dialog_type,
            patch.object(
                window.update_service,
                "start_installation",
                side_effect=lambda *_args, **_kwargs: (events.append("installer"), attempt)[1],
            ),
            patch.object(
                QApplication,
                "quit",
                side_effect=lambda *_args: events.append("beenden"),
            ),
        ):
            dialog_type.return_value.exec_countdown.side_effect = (
                lambda: events.append("countdown")
            )
            window._on_update_download_succeeded(9, installer)

        dialog_type.assert_called_once_with(window, seconds=10)
        self.assertEqual(events, ["countdown", "installer"])
        attempt.commit.assert_not_called()
        window._cancel_update_installation()
        attempt.cancel.assert_called_once()
        window.close()

    def test_slicer_titles_are_left_aligned(self) -> None:
        window = self.window()
        for label in window._slicer_width_labels:
            self.assertTrue(label.alignment() & Qt.AlignmentFlag.AlignLeft)
            self.assertFalse(label.alignment() & Qt.AlignmentFlag.AlignRight)
        window.close()

    def test_slicer_support_hint_precedes_title_and_opens_on_hover(self) -> None:
        window = self.window()
        window.resize(1400, 1000)
        window.show()
        icon = window.slicer_support_info_button
        label = window.slicer_selection_label
        layout = label.parentWidget().layout()
        self.assertEqual(layout.indexOf(icon), 0)
        self.assertEqual(layout.indexOf(label), 1)
        self.assertEqual(icon.height(), METRICS.setting_info_diameter_px)
        self.app.sendEvent(icon, QEvent(QEvent.Type.Enter))
        popover = window._bounded_hint_popover
        self.assertFalse(popover.isHidden())
        for product in ("Anycubic Slicer Next", "Bambu Studio", "PrusaSlicer", "OrcaSlicer"):
            self.assertIn(product, popover.label.text())
        for placeholder in ("Cura", "Creality Print", "Simplify3D"):
            self.assertNotIn(placeholder, popover.label.text())
        for phrase in ("1-Personen-Entwicklung", "Verständnis", "GitHub-Issue", "Support Diagnose …", "Burgermenü"):
            self.assertIn(phrase, popover.label.text())
        self.app.sendEvent(icon, QEvent(QEvent.Type.Leave))
        self.assertTrue(popover.isHidden())
        self.assertEqual(window.support_report_action.text(), "Support Diagnose …")
        window.support_report_action.trigger()
        self.assertTrue(window.support_report_dialog.isVisible())
        window.close()

    def test_slicer_support_hint_tracks_active_modules_and_escapes_names(self) -> None:
        from cooling_tower.gui.texts import slicer_support_hint_html

        modules = (SimpleNamespace(product_name="Neuer Slicer <Test>", implemented=True),
                   SimpleNamespace(product_name="Platzhalter", implemented=False))
        with patch('cooling_tower.slicers.detection.registry.detection_modules', return_value=modules):
            hint = slicer_support_hint_html()
        self.assertIn("Neuer Slicer &lt;Test&gt;", hint)
        self.assertNotIn("Platzhalter", hint)

    def test_slicer_header_stays_compact_and_profiles_remain_accessible(self) -> None:
        window = self.window()
        window.machine_profile_combo.addItem("Kobra 3 V2")
        window.process_profile_combo.addItem("0,20 mm Standard")
        window.filament_profile_combo.addItem("PLA Schwarz")
        installation = SlicerInstallation(
            adapter_id="requested-ui-test",
            product_name="Testslicer",
            version="1.0",
            executable_path=self.root / "slicer.exe",
            verified=True,
            capabilities=frozenset(),
            discovery_source=SlicerDiscoverySource.KNOWN_PATH,
            family=SlicerFamily.OTHER,
        )

        window.show()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window._automatically_selected_slicer_key = installation.identity_key
        with patch.object(
            type(window),
            "selected_slicer_installation",
            new_callable=PropertyMock,
            return_value=installation,
        ):
            window._set_slicer_header_summary(installation)
        self.app.processEvents()

        self.assertEqual(
            window.slicer_group.summary_label.text(),
            installation.display_name,
        )
        self.assertEqual(
            window.slicer_group.title_note_label.text(),
            "(automatisch erkannt)",
        )
        self.assertFalse(window.slicer_group.title_note_label.isHidden())
        self.assertFalse(
            window.slicer_group.title_note_label.isVisibleTo(window)
        )
        self.assertEqual(
            window.slicer_group.title_note_label.palette().color(
                window.slicer_group.title_note_label.foregroundRole()
            ).name(),
            "#176b45",
        )
        self.assertTrue(window.slicer_group.summary_note_label.isHidden())
        self.assertEqual(
            window.slicer_auto_detected_label.text(),
            "(automatisch erkannt)",
        )
        self.assertFalse(window.slicer_auto_detected_label.isHidden())
        self.assertFalse(window.slicer_auto_detected_label.font().bold())
        self.assertTrue(window.slicer_group.header.isHidden())
        self.assertEqual(window.slicer_group.header.height(), 0)
        self.assertEqual(
            window.slicer_group.header.height(),
            window.source_group.header.height(),
        )
        self.assertEqual(
            window.preparation_step_heading_labels[1].text(),
            "Slicer-Einstellungen",
        )
        self.assertFalse(
            window.preparation_step_heading_labels[1].isVisibleTo(window)
        )
        accessible = window.slicer_selector_column.accessibleDescription()
        self.assertIn(f"Slicer: {installation.display_name}", accessible)
        self.assertIn("Maschinenprofil: Kobra 3 V2", accessible)
        self.assertIn("Filamentprofil: PLA Schwarz", accessible)
        self.assertIn("Prozessprofil: 0,20 mm Standard", accessible)
        self.assertTrue(
            window.slicer_group.title_label.alignment()
            & Qt.AlignmentFlag.AlignLeft
        )
        left_layout = window.slicer_group.header_left.layout()
        self.assertTrue(left_layout.alignment() & Qt.AlignmentFlag.AlignLeft)
        self.assertEqual(
            window.slicer_group.title_label.text(),
            "Slicer-Einstellungen",
        )
        self.assertTrue(window.slicer_group.toggle_button.isHidden())
        window._automatically_selected_slicer_key = None
        with patch.object(
            type(window),
            "selected_slicer_installation",
            new_callable=PropertyMock,
            return_value=installation,
        ):
            window._refresh_slicer_auto_detection_label()
        self.assertTrue(window.slicer_auto_detected_label.isHidden())
        window.close()

    def test_regular_card_headers_keep_the_standard_height(self) -> None:
        window = self.window()
        window.resize(1200, 1000)
        window.show()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        self.app.processEvents()

        for card in (
            window.timing_group,
            window.geometry_group,
            window.stability_group,
            window.overhang_group,
        ):
            self.assertEqual(
                card.header.height(),
                METRICS.card_header_height_px,
            )
        window.close()

    def test_profile_dropdowns_show_all_grouped_presets_with_scrollbars(self) -> None:
        window = self.window()
        self.assertIs(
            window.profile_filter_label.parentWidget(),
            window.slicer_information_column,
        )
        selector_layout = window.slicer_selectors_layout
        self.assertLess(
            selector_layout.indexOf(window.machine_profile_label),
            selector_layout.indexOf(window.filament_profile_label),
        )
        self.assertLess(
            selector_layout.indexOf(window.filament_profile_label),
            selector_layout.indexOf(window.process_profile_label),
        )
        records = tuple(
            SimpleNamespace(
                name=f"Profil {index:02d}",
                profile_id=f"profile-{index:02d}",
                path=self.root / f"profile-{index:02d}.json",
                source="user" if index < 7 else "system",
            )
            for index in range(14)
        )
        result = SimpleNamespace(
            selected=None,
            machine_options=records,
            process_options=records,
            filament_options=records,
        )

        window._populate_profile_combos(result)

        for combo in (
            window.machine_profile_combo,
            window.process_profile_combo,
            window.filament_profile_combo,
        ):
            with self.subTest(combo=combo.objectName()):
                profile_paths = tuple(
                    combo.itemData(index)
                    for index in range(combo.count())
                    if isinstance(combo.itemData(index), str)
                )
                self.assertEqual(len(profile_paths), len(records))
                self.assertEqual(combo.itemText(0), "- User presets -")
                self.assertEqual(combo.itemText(8), "- System presets -")
                self.assertEqual(combo.maxVisibleItems(), 10)
                self.assertEqual(
                    combo.view().verticalScrollBarPolicy(),
                    Qt.ScrollBarPolicy.ScrollBarAsNeeded,
                )
                self.assertFalse(combo.model().item(0).isEnabled())
                self.assertFalse(combo.model().item(8).isEnabled())
                self.assertTrue(
                    all(
                        "[" not in combo.itemText(index)
                        for index in range(combo.count())
                        if isinstance(combo.itemData(index), str)
                    )
                )

        requests = []
        window.profile_match_result = result
        window.start_profile_matching = lambda **kwargs: requests.append(kwargs)
        window.machine_profile_combo.setCurrentIndex(2)
        self.assertEqual(requests, [])
        self.assertFalse(window.profile_confirm_button.isEnabled())
        self.assertIn("gültigen STL", window.profile_confirm_button.toolTip())
        self.assertTrue(window.profile_status_label.isHidden())
        window.filament_profile_combo.setCurrentIndex(2)
        self.assertEqual(requests, [])
        window.close()

    def test_profile_origin_uses_real_storage_location(self) -> None:
        installation = SlicerInstallation(
            adapter_id="origin-test",
            product_name="Testslicer",
            version="1.0",
            executable_path=self.root / "install" / "slicer.exe",
            verified=True,
            capabilities=frozenset(),
            discovery_source=SlicerDiscoverySource.KNOWN_PATH,
            family=SlicerFamily.OTHER,
        )
        bundled = (
            self.root
            / "install"
            / "resources"
            / "profiles"
            / "bundled.json"
        )
        user_created = (
            self.root
            / "appdata"
            / "Testslicer"
            / "user"
            / "default"
            / "custom.json"
        )
        mirrored_system = (
            self.root
            / "appdata"
            / "Testslicer"
            / "system"
            / "mirrored.json"
        )

        self.assertEqual(
            classify_profile_source(installation, bundled, "user"),
            "system",
        )
        self.assertEqual(
            classify_profile_source(installation, user_created, "system"),
            "user",
        )
        self.assertEqual(
            classify_profile_source(installation, mirrored_system, "user"),
            "system",
        )

        anycubic = replace(
            installation,
            adapter_id="anycubic_slicer_next",
        )
        anycubic_system_mirror = (
            self.root
            / "appdata"
            / "AnycubicSlicerNext"
            / "user"
            / "default"
            / "process"
            / "mirrored.json"
        )
        anycubic_account_preset = (
            self.root
            / "appdata"
            / "AnycubicSlicerNext"
            / "user"
            / "489681"
            / "process"
            / "custom.json"
        )
        anycubic_local_preset = anycubic_system_mirror.with_name("local.json")
        anycubic_system_mirror.parent.mkdir(parents=True)
        anycubic_system_mirror.write_text("{}", encoding="utf-8")
        anycubic_system_mirror.with_suffix(".info").write_text(
            "sync_info =\n"
            "user_id =\n"
            "setting_id =\n"
            "base_id = GP004\n",
            encoding="utf-8",
        )
        anycubic_local_preset.write_text("{}", encoding="utf-8")
        anycubic_local_preset.with_suffix(".info").write_text(
            "sync_info = update\n"
            "user_id =\n"
            "setting_id =\n"
            "base_id = GP004\n",
            encoding="utf-8",
        )
        self.assertEqual(
            classify_profile_source(
                anycubic,
                anycubic_system_mirror,
                "user",
            ),
            "system",
        )
        self.assertEqual(
            classify_profile_source(
                anycubic,
                anycubic_account_preset,
                "user",
            ),
            "user",
        )
        self.assertEqual(
            classify_profile_source(
                anycubic,
                anycubic_local_preset,
                "user",
            ),
            "user",
        )
        bambu = replace(installation, adapter_id="bambu_studio")
        self.assertEqual(
            classify_profile_source(
                bambu,
                anycubic_system_mirror,
                "user",
            ),
            "user",
        )

    def test_only_explicit_user_profiles_use_the_user_category(self) -> None:
        records = tuple(
            SimpleNamespace(
                name=source.title(),
                profile_id=source,
                path=self.root / f"{source}.json",
                source=source,
            )
            for source in ("user", "system", "project", "session", "temporary")
        )

        groups = dict(MainWindow._profile_option_groups(records))

        self.assertEqual(
            tuple(record.source for record in groups["- User presets -"]),
            ("user",),
        )
        self.assertEqual(
            tuple(record.source for record in groups["- System presets -"]),
            ("system",),
        )
        self.assertEqual(
            {record.source for record in groups["- Other presets -"]},
            {"project", "session", "temporary"},
        )

    def test_generation_uses_one_fixed_high_quality_slice_budget(self) -> None:
        window = self.window()
        window.show()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        self.app.processEvents()

        self.assertFalse(hasattr(window, "slicer_iterations_spin"))
        self.assertFalse(hasattr(window, "preview_iteration_slider"))
        self.assertNotIn("slicer_iterations", window._setting_widgets)
        self.assertFalse(hasattr(window, "preview_fast_button"))
        self.assertFalse(hasattr(window, "preview_precise_button"))
        self.assertFalse(hasattr(window, "preview_quality_panel"))
        config = window._calibration_config()
        self.assertEqual(config.maximum_iterations, 18)
        self.assertEqual(config.minimum_joint_slices, 3)
        self.assertEqual(config.maximum_joint_slices, 12)
        self.assertTrue(
            window.preview_action_control.isAncestorOf(
                window.preview_button
            )
        )
        self.assertLessEqual(
            window.preview_action_control.width(),
            window.export_button.width(),
        )
        self.assertGreaterEqual(window.preview_action_control.width(), 176)
        self.assertEqual(window.preview_button.text(), "Kühlturm generieren")

        self.assertEqual(
            window.maximum_expansion_angle_spin.property("validationMinimum"),
            20.0,
        )
        window.maximum_expansion_angle_spin.setValue(40.0)
        self.assertTrue(
            window.maximum_expansion_angle_setting.message_label.isHidden()
        )
        window.maximum_expansion_angle_spin.setValue(28.0)
        self.app.processEvents()
        warning = window.maximum_expansion_angle_setting.message_label
        self.assertFalse(warning.isHidden())
        self.assertIn("Vorsicht", warning.text())
        self.assertEqual(
            warning.text(),
            "Vorsicht: Der aktuelle Aufweitungswinkel erzeugt einen sehr starken Überhang.",
        )
        window.maximum_expansion_angle_spin.setValue(20.0)
        self.assertTrue(window.validate_form())
        window.close()

    def test_prediction_and_geometry_headers_use_the_unified_framing(self) -> None:
        window = self.window()
        window.resize(1200, 900)
        window.show()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        for _ in range(5):
            self.app.processEvents()

        self.assertFalse(hasattr(window, "prediction_advice_label"))
        self.assertFalse(hasattr(window, "slicer_prediction_button"))
        self.assertTrue(
            window.prediction_frame.isAncestorOf(window.preview_dialog)
        )
        self.assertFalse(window.preview_dialog.isWindow())

        header = window.geometry_group.header
        self.assertEqual(header.width(), window.geometry_split.width())
        self.assertTrue(window.geometry_calculation_section.isHidden())

        stylesheet = window.styleSheet()
        self.assertIn(
            "QFrame#sectionCard[expanded=\"true\"] > "
            "QFrame#sectionCardHeader",
            stylesheet,
        )
        self.assertIn("border-bottom-left-radius: 0;", stylesheet)
        self.assertIn("border-bottom-right-radius: 0;", stylesheet)
        self.assertIn(
            "QFrame#geometryCalculationHeader {",
            stylesheet,
        )
        window.close()

    def test_main_scroll_range_ends_at_the_standard_bottom_margin(self) -> None:
        window = self.window()
        window.resize(760, 900)
        window.show()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        for _ in range(8):
            self.app.processEvents()

        window.resize(1700, 900)
        for _ in range(8):
            self.app.processEvents()

        self.assertEqual(
            window.ready_grid.height(),
            max(
                window.ready_left_column.height(),
                window.prediction_frame.height(),
            ),
        )
        bottom_space = (
            window.settings_content.height()
            - window.ready_grid.mapTo(
                window.settings_content, window.ready_grid.rect().bottomLeft()
            ).y()
            - 1
        )
        standard_margin = window.content_layout.contentsMargins().bottom()
        if window.settings_scroll.verticalScrollBar().maximum() > 0:
            self.assertEqual(bottom_space, standard_margin)
        else:
            # A short page grows to the viewport; its trailing stretch may
            # add free space below the regular margin.
            self.assertGreaterEqual(bottom_space, standard_margin)
        window.close()

    def test_geometry_card_fits_content_and_headers_meet_the_boundaries(self) -> None:
        window = self.window()
        window.resize(1700, 900)
        window.show()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        for _ in range(8):
            self.app.processEvents()

        geometry = window.geometry_settings_group
        split = window.geometry_split
        self.assertEqual(
            geometry.content_widget.height(),
            split.height(),
        )
        self.assertLessEqual(
            abs(
                geometry.height()
                - geometry.header.height()
                - geometry.body_divider.height()
                - split.height()
            ),
            2,
        )

        subsections = (
            window.timing_group,
            window.geometry_group,
        )
        self.assertTrue(
            all(subsection.width() == split.width() for subsection in subsections)
        )
        self.assertEqual(
            [subsection.y() for subsection in subsections],
            sorted(subsection.y() for subsection in subsections),
        )
        window.close()

    def test_numeric_fields_keep_uniform_units_when_focused_and_edited(self) -> None:
        window = self.window()
        window.show()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        self.app.processEvents()
        expected_units = {
            "target_layer_time_s": "Sek.",
            "minimum_outer_diameter_mm": "mm",
            "maximum_outer_diameter_mm": "mm",
            "manual_base_width_mm": "mm",
            "circle_segments": "",
            "maximum_expansion_angle_deg": "°",
            "maximum_contraction_angle_deg": "°",
            "local_reference_window": "Layer",
        }
        self.assertEqual(set(window._setting_widgets), set(expected_units))
        for name, setting in window._setting_widgets.items():
            with self.subTest(setting=name):
                self.assertNotIn("[", setting.label.text())
                self.assertEqual(setting.unit_label.text(), expected_units[name])
                self.assertEqual(setting.unit_label.width(), 44)
                self.assertEqual(
                    setting.unit_label.geometry().right() + 1,
                    setting.editor.width() - 24,
                )

        target = window._setting_widgets["target_layer_time_s"]
        target.editor.setFocus()
        target.editor.selectAll()
        target.editor.lineEdit().setText("23")
        self.app.processEvents()
        self.assertTrue(target.unit_label.isVisible())
        self.assertEqual(target.unit_label.text(), "Sek.")
        self.assertEqual(target.unit_label.width(), 44)
        self.assertGreaterEqual(target.editor.lineEdit().width(), 67)
        self.assertEqual(
            window._setting_widgets[
                "maximum_outer_diameter_mm"
            ].label.text(),
            "Maximaler Turmdurchmesser",
        )
        window.close()

    def test_footer_actions_require_successful_gcode_and_slicer_stages(self) -> None:
        window = self.window()
        window.show()
        actions = (
            window.open_output_button,
            window.open_stl_button,
            window.reset_button,
            window.preview_action_control,
            window.export_button,
        )
        self.assertTrue(all(action.isHidden() for action in actions))

        self.complete_source_step(window)
        self.assertTrue(all(action.isHidden() for action in actions))
        window.workflow.slicer_unavailable("Kein Slicer verfügbar")
        self.assertTrue(all(action.isHidden() for action in actions))
        window.workflow.slicer_succeeded("Testslicer")
        self.assertTrue(all(action.isHidden() for action in actions))
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        self.assertTrue(all(action.isVisible() for action in actions[:-1]))
        self.assertTrue(window.export_button.isHidden())
        window.close()

    def test_stl_guide_is_an_icon_hint_without_a_box(self) -> None:
        window = self.window()
        self.assertIn("STL-Modell", window.source_guide.text())
        self.assertEqual(
            window.source_guide.text(),
            "Wähle das STL-Modell aus, für das ein Kühlturm erstellt werden soll.",
        )
        self.assertEqual(window.source_guide_icon.text(), "ℹ")
        self.assertIs(
            window.source_guide_icon.parentWidget(),
            window.source_guide_row,
        )
        self.assertEqual(
            window.source_guide_row.layout().contentsMargins().left(),
            0,
        )
        window.close()

    def test_ready_sections_stay_open_without_changing_advanced_collapse_state(self) -> None:
        window = self.window()
        window.resize(1300, 900)
        window.show()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        self.app.processEvents()

        window.geometry_group.setChecked(False)
        window.geometry_settings_group.setChecked(False)
        window.timing_group.setChecked(False)
        window.prediction_frame.setChecked(False)
        self.app.processEvents()
        collapsed_height = window.ready_grid.height()
        self.assertGreater(
            window.geometry_settings_group.height(),
            window.geometry_settings_group.header.height(),
        )

        window.timing_group.setChecked(True)
        self.app.processEvents()
        self.assertGreater(window.timing_group.height(), 54)
        self.assertEqual(window.ready_grid.height(), collapsed_height)
        self.assertTrue(window.timing_group.isVisible())
        self.assertTrue(window.geometry_settings_group.isChecked())
        self.assertTrue(window.prediction_frame.isChecked())
        self.assertFalse(window.geometry_group.isChecked())

        timing_open_height = window.ready_grid.height()
        window.prediction_frame.setChecked(True)
        self.app.processEvents()
        self.assertGreater(window.prediction_frame.height(), 54)
        self.assertEqual(window.ready_grid.height(), timing_open_height)
        self.assertTrue(window.geometry_settings_group.isChecked())
        self.assertFalse(window.geometry_group.isChecked())
        window.close()

    def test_automatic_sections_meet_window_edges_and_share_full_height_divider(self) -> None:
        window = self.window()
        self.addCleanup(window.close)
        window.resize(1400, 1000)
        window.show()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        for width in (1400, 760, 1400):
            window.resize(width, 1000)
            for _ in range(8):
                self.app.processEvents()
            settings = window.geometry_settings_group
            preview = window.prediction_frame
            divider = window.ready_columns_divider
            viewport = window.settings_scroll.viewport()
            self.assertEqual(window.ready_grid.width(), viewport.width())
            for section in (settings, preview):
                self.assertFalse(section.isCheckable())
                self.assertTrue(section.toggle_button.isHidden())
                self.assertEqual(section.contentsMargins().left(), 0)
                self.assertEqual(section.contentsMargins().right(), 0)
                image = section.header.grab().toImage()
                self.assertEqual(image.pixelColor(0, 0), image.pixelColor(20, 0))
                self.assertEqual(
                    image.pixelColor(image.width() - 1, 0),
                    image.pixelColor(image.width() - 20, 0),
                )
            top_section = settings if width == 1400 else preview
            self.assertEqual(top_section.mapTo(viewport, QPoint(0, 0)).y(), 0)
            self.assertEqual(
                top_section.mapTo(window, QPoint(0, 0)).y(),
                window.main_header.geometry().bottom() + 1,
            )
            self.assertEqual(window.workflow_header.divider_shadow.y(), top_section.mapTo(window, QPoint(0, 0)).y())
            if width == 1400:
                self.assertTrue(divider.isVisible())
                self.assertEqual(divider.width(), 1)
                self.assertEqual(divider.x(), window.ready_left_column.geometry().right() + 1)
                self.assertEqual(preview.x(), divider.geometry().right() + 1)
                self.assertEqual(preview.geometry().right() + 1, viewport.width())
                self.assertEqual(divider.height(), max(settings.height(), preview.height()))
                window.geometry_group.toggle()
                for _ in range(5):
                    self.app.processEvents()
                self.assertEqual(divider.height(), max(settings.height(), preview.height()))
            else:
                self.assertTrue(divider.isHidden())
                self.assertEqual(settings.width(), viewport.width())
                self.assertEqual(preview.width(), viewport.width())
                self.assertEqual(window.ready_left_column.y(), preview.geometry().bottom() + 1)
        # The divider must also follow the settings surface if it grows taller.
        settings.setFixedHeight(preview.height() + 80)
        window.ready_left_column.layout().invalidate()
        window._refresh_ready_grid_layout()
        for _ in range(5):
            self.app.processEvents()
        self.assertGreater(settings.height(), preview.height())
        self.assertEqual(divider.height(), settings.height())

    def test_geometry_fields_share_one_named_section(self) -> None:
        window = self.window()
        self.addCleanup(window.close)
        self.assertEqual(window.geometry_group.title(), "Erweiterte Turmeinstellungen")
        for name in ("manual_base_width_mm", "maximum_expansion_angle_deg", "maximum_contraction_angle_deg"):
            self.assertTrue(window.geometry_group.isAncestorOf(window._setting_widgets[name]))
        self.assertFalse(window.geometry_group.isAncestorOf(window._setting_widgets["local_reference_window"]))
        self.assertTrue(window.stability_group.isHidden())
        self.assertTrue(window.overhang_group.isHidden())

    def test_advanced_settings_toggle_resizes_outer_card_without_bottom_gap(self) -> None:
        window = self.window()
        self.addCleanup(window.close)
        window.resize(1400, 900)
        window.show()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        self.app.processEvents()

        advanced = window.geometry_group
        outer = window.geometry_settings_group
        self.assertTrue(advanced.isChecked())
        self.assertTrue(advanced.toggle_button.isVisible())
        self.assertTrue(advanced.toggle_button.isChecked())
        self.assertTrue(window.timing_group.header.isHidden())
        self.assertTrue(window.timing_group.body_divider.isHidden())
        self.assertTrue(window.timing_group.isAncestorOf(window.full_infill_checkbox))
        expanded_height = outer.height()

        QTest.mouseClick(advanced.header, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertFalse(advanced.isChecked())
        self.assertTrue(advanced.content_widget.isHidden())
        self.assertFalse(advanced.toggle_button.isChecked())
        self.assertLess(outer.height(), expanded_height)
        self.assertLessEqual(
            outer.height() - outer.header.height() - outer.body_divider.height()
            - window.timing_group.height() - advanced.header.height(),
            2,
        )

        outer.setChecked(False)
        self.app.processEvents()
        outer.setChecked(True)
        self.app.processEvents()
        self.assertFalse(advanced.isChecked())
        QTest.mouseClick(advanced.toggle_button, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertTrue(advanced.isChecked())
        self.assertTrue(advanced.toggle_button.isChecked())
        self.assertGreater(outer.height(), expanded_height - 2)

    def test_single_column_prediction_order_survives_state_and_width_changes(
        self,
    ) -> None:
        window = self.window()
        window.resize(1400, 900)
        window.show()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        for _ in range(6):
            self.app.processEvents()

        grid = window.ready_grid
        self.assertTrue(grid.is_two_column())
        self.assertEqual(
            grid.grid.getItemPosition(
                grid.grid.indexOf(window.ready_left_column)
            )[:2],
            (0, 0),
        )
        self.assertEqual(
            grid.grid.getItemPosition(
                grid.grid.indexOf(window.prediction_frame)
            )[:2],
            (0, 2),
        )
        preserved_target = window.target_time_spin.value()

        window.resize(800, 900)
        for _ in range(8):
            self.app.processEvents()
        self.assertFalse(grid.is_two_column())
        self.assertEqual(
            grid.grid.getItemPosition(
                grid.grid.indexOf(window.prediction_frame)
            )[:2],
            (0, 0),
        )
        self.assertEqual(
            grid.grid.getItemPosition(
                grid.grid.indexOf(window.ready_left_column)
            )[:2],
            (1, 0),
        )
        self.assertLess(
            window.prediction_frame.mapTo(
                window.settings_content, QPoint(0, 0)
            ).y(),
            window.timing_group.mapTo(
                window.settings_content, QPoint(0, 0)
            ).y(),
        )
        self.assertIs(window.window_pages.currentWidget(), window.main_surface)
        self.assertTrue(
            window.preparation_workspace_layout.indexOf(window.workflow_group) >= 0
        )
        self.assertTrue(window.workflow_group.isHidden())

        window.geometry_settings_group.setChecked(False)
        window.prediction_frame.setChecked(False)
        window.timing_group.setChecked(False)
        window.prediction_frame.setChecked(True)
        window.timing_group.setChecked(True)
        for _ in range(5):
            self.app.processEvents()
        self.assertGreater(
            window.prediction_frame.height(),
            window.prediction_frame.header.height(),
        )
        self.assertGreater(
            window.timing_group.height(),
            window.timing_group.header.height(),
        )
        self.assertEqual(
            window.settings_scroll.horizontalScrollBar().maximum(),
            0,
        )

        window.resize(1400, 900)
        for _ in range(8):
            self.app.processEvents()
        self.assertTrue(grid.is_two_column())
        self.assertEqual(
            grid.grid.getItemPosition(
                grid.grid.indexOf(window.ready_left_column)
            )[:2],
            (0, 0),
        )
        self.assertEqual(
            grid.grid.getItemPosition(
                grid.grid.indexOf(window.prediction_frame)
            )[:2],
            (0, 2),
        )
        self.assertEqual(window.target_time_spin.value(), preserved_target)
        window.close()

    def test_inline_errors_expand_layout_without_overlapping_fields(self) -> None:
        window = self.window()
        window.resize(800, 900)
        window.show()
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        for _ in range(5):
            self.app.processEvents()
        height_before = window.geometry_settings_group.height()

        window.maximum_outer_spin.setValue(1001.0)
        window.validate_form()
        for _ in range(6):
            self.app.processEvents()
        self.assertGreater(window.geometry_settings_group.height(), height_before)
        self.assertTrue(
            window._setting_widgets[
                "maximum_outer_diameter_mm"
            ].message_label.isVisible()
        )
        self.assertTrue(window.validation_label.text().strip())

        visible_rows: list[tuple[str, QRect]] = []
        for name, setting in window._setting_widgets.items():
            if not setting.isVisible():
                continue
            origin = setting.mapTo(window, QPoint(0, 0))
            visible_rows.append(
                (name, QRect(origin, setting.size()))
            )
        overlaps = [
            (left_name, right_name)
            for index, (left_name, left_rect) in enumerate(visible_rows)
            for right_name, right_rect in visible_rows[index + 1 :]
            if left_rect.intersects(right_rect)
        ]
        self.assertEqual(overlaps, [])
        window.close()

    def test_footer_notices_are_priority_sorted_in_one_scrollable_column(self) -> None:
        window = self.window()
        window.resize(2000, 900)
        window.show()
        window._set_export_button_state(True)
        window.warning_text.setPlainText("Ein Warnhinweis")
        window._refresh_issue_panels()
        for _ in range(5):
            self.app.processEvents()

        self.assertEqual(
            window._active_footer_notice_severities,
            ("warning",),
        )
        self.assertTrue(window.notice_panel.is_expanded())

        window._set_export_button_state(False, "Testvoraussetzung fehlt.")
        for _ in range(5):
            self.app.processEvents()
        self.assertTrue(window.action_availability_widget.isHidden())
        self.assertFalse(window.export_availability_label.text())
        self.assertEqual(
            window._active_footer_notice_severities,
            ("warning",),
        )

        window.validation_label.setText("Fehlerhinweis " * 120)
        window._static_error_causes = ["Fehler"]
        window._refresh_issue_panels()
        for _ in range(5):
            self.app.processEvents()
        self.assertEqual(
            window._active_footer_notice_severities,
            ("error", "warning"),
        )
        for panel in (window.error_panel, window.notice_panel):
            self.assertFalse(panel.is_expanded())
        self.assertLess(
            window.footer_notice_layout.indexOf(window.error_panel),
            window.footer_notice_layout.indexOf(window.notice_panel),
        )

        extra_error = FooterNoticeDropdown(
            "✕  Zusätzliche Fehlergruppe",
            severity="error",
        )
        extra_details = QLabel("Zusätzliche Details " * 80)
        extra_details.setWordWrap(True)
        extra_error.content_layout.addWidget(extra_details)
        window._register_footer_notice("error", extra_error)
        extra_error.show()
        for _ in range(3):
            self.app.processEvents()
        self.assertFalse(extra_error.is_expanded())
        self.assertLess(
            window.error_panel.y(),
            extra_error.y(),
        )

        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        window.error_panel.set_expanded(True)
        extra_error.set_expanded(True)
        for _ in range(8):
            self.app.processEvents()
        self.assertEqual(window.footer.height(), 350)
        self.assertEqual(
            window.footer.maximumHeight(),
            350,
        )
        self.assertGreater(
            window.footer_messages_scroll.verticalScrollBar().maximum(), 0
        )
        window.close()

    def test_footer_folder_actions_have_distinct_persistent_targets(self) -> None:
        window = self.window()
        output_root = self.root / "output-root"
        window.output_root_edit.setText(str(output_root))
        with patch(
            "cooling_tower.gui.main_window.open_directory"
        ) as open_directory_mock:
            window.open_output_directory()
            open_directory_mock.assert_called_once_with(output_root.resolve())
        self.assertTrue(output_root.is_dir())

        window._export_request_id = 11
        first_folder = self.write_export_folder(
            output_root,
            "export-1",
            "2026-07-30T10:00:01+02:00",
        )
        second_folder = self.write_export_folder(
            output_root,
            "export-2",
            "2026-07-30T10:00:02+02:00",
        )
        for folder in (first_folder, second_folder):
            result = SimpleNamespace(
                output_mode=OutputMode.STL,
                calibrated=True,
                slicer_optimized=True,
                output_path=folder / "tower.stl",
                user_report_path=folder / "summary.txt",
            )
            window._on_export_succeeded(11, result)
        window.last_export_result = None
        with patch(
            "cooling_tower.gui.main_window.open_directory"
        ) as open_directory_mock:
            window.open_stl_directory()
            open_directory_mock.assert_called_once_with(
                second_folder.resolve()
            )
        self.assertEqual(window.open_output_button.text(), "Alle Exporte öffnen")
        self.assertEqual(window.open_stl_button.text(), "Letzten Export öffnen")
        self.assertTrue(window.open_stl_button.isEnabled())
        window.close()

    def test_footer_shortens_actions_in_order_and_restores_full_labels_after_split(self) -> None:
        window = self.window()
        window.workflow.set_slicer_step_visible(True)
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        window.show()
        for _ in range(5):
            self.app.processEvents()

        window.current_preview = SimpleNamespace(dispose=lambda: None)
        window.preview_state = PreviewState.CURRENT
        window._joint_generation_paused = True
        with patch.object(window, "_export_block_reason", return_value=None), patch.object(
            window, "_current_preview_was_exported", return_value=False
        ):
            stages = []
            saw_action_wrap = False
            for width in range(2600, 719, -25):
                window.resize(width, 900)
                window._refresh_phase17_actions()
                self.app.processEvents()
                stage = (
                    window._footer_narrow_layout,
                    window.open_output_button.text(),
                    window.open_stl_button.text(),
                    window.preview_button.text(),
                    window.export_button.text(),
                )
                if stage not in stages:
                    stages.append(stage)
                buttons = (
                    window.open_output_button,
                    window.open_stl_button,
                    window.preview_action_control,
                    window.export_button,
                )
                for index, button in enumerate(buttons):
                    self.assertGreaterEqual(button.width(), button.sizeHint().width())
                    self.assertTrue(
                        window.footer_action_area.rect().contains(button.geometry())
                    )
                    for other in buttons[index + 1:]:
                        self.assertFalse(button.geometry().intersects(other.geometry()))
                self.assertLess(
                    window.preview_action_control.geometry().right(),
                    window.export_button.geometry().left(),
                )
                if window._footer_actions_layout_mode == "action_below":
                    saw_action_wrap = True
                    self.assertGreater(
                        window.preview_action_control.geometry().top(),
                        window.open_output_button.geometry().bottom(),
                    )
            self.assertTrue(saw_action_wrap)
            self.assertEqual(stages, [
                (False, "Alle Exporte öffnen", "Letzten Export öffnen",
                 "Generierung abbrechen", "Kühlturm exportieren"),
                (False, "Alle Exporte", "Letzter Export",
                 "Generierung abbrechen", "Kühlturm exportieren"),
                (False, "Alle Exporte", "Letzter Export",
                 "Abbrechen", "Exportieren"),
                (True, "Alle Exporte öffnen", "Letzten Export öffnen",
                 "Generierung abbrechen", "Kühlturm exportieren"),
                (True, "Alle Exporte", "Letzter Export",
                 "Generierung abbrechen", "Kühlturm exportieren"),
                (True, "Alle Exporte", "Letzter Export",
                 "Abbrechen", "Exportieren"),
            ])
        window.close()

    def test_footer_shortens_export_report_before_right_actions_in_both_layouts(self) -> None:
        window = self.window()
        window.workflow.set_slicer_step_visible(True)
        self.complete_source_step(window)
        window.workflow.slicer_succeeded("Testslicer")
        window.workflow.complete_preparation()
        window.automatic_generation_card.click()
        window.show()
        window.current_preview = SimpleNamespace(dispose=lambda: None)
        window.preview_state = PreviewState.CURRENT
        window._joint_generation_paused = True
        window._last_export_report_result = SimpleNamespace()
        window._refresh_last_export_report_action()

        with patch.object(window, "_export_block_reason", return_value=None), patch.object(
            window, "_current_preview_was_exported", return_value=False
        ):
            stages = []
            for width in range(4500, 719, -25):
                window.resize(width, 900)
                window._refresh_phase17_actions()
                self.app.processEvents()
                self.assertTrue(window.open_run_button.isVisible())
                stage = (
                    window._footer_narrow_layout,
                    window.open_output_button.text(),
                    window.open_run_button.text(),
                    window.preview_button.text(),
                    window.export_button.text(),
                )
                if stage not in stages:
                    stages.append(stage)
                buttons = (
                    window.open_output_button,
                    window.open_stl_button,
                    window.open_run_button,
                    window.preview_action_control,
                    window.export_button,
                )
                for index, button in enumerate(buttons):
                    self.assertGreaterEqual(button.width(), button.sizeHint().width())
                    self.assertTrue(
                        window.footer_action_area.rect().contains(button.geometry())
                    )
                    for other in buttons[index + 1:]:
                        self.assertFalse(button.geometry().intersects(other.geometry()))
            self.assertEqual(stages, [
                (False, "Alle Exporte öffnen", "Letzten Exportbericht öffnen",
                 "Generierung abbrechen", "Kühlturm exportieren"),
                (False, "Alle Exporte öffnen", "Exportbericht öffnen",
                 "Generierung abbrechen", "Kühlturm exportieren"),
                (False, "Alle Exporte öffnen", "Exportbericht",
                 "Generierung abbrechen", "Kühlturm exportieren"),
                (False, "Alle Exporte", "Exportbericht",
                 "Generierung abbrechen", "Kühlturm exportieren"),
                (False, "Alle Exporte", "Exportbericht",
                 "Abbrechen", "Exportieren"),
                (True, "Alle Exporte öffnen", "Letzten Exportbericht öffnen",
                 "Generierung abbrechen", "Kühlturm exportieren"),
                (True, "Alle Exporte öffnen", "Exportbericht öffnen",
                 "Generierung abbrechen", "Kühlturm exportieren"),
                (True, "Alle Exporte öffnen", "Exportbericht",
                 "Generierung abbrechen", "Kühlturm exportieren"),
                (True, "Alle Exporte", "Exportbericht",
                 "Generierung abbrechen", "Kühlturm exportieren"),
                (True, "Alle Exporte", "Exportbericht",
                 "Abbrechen", "Exportieren"),
            ])
            self.assertEqual(
                window.open_run_button.accessibleName(),
                "Letzten Exportbericht öffnen",
            )
        window.close()

    def test_latest_export_button_explains_disabled_state_and_rechecks(self) -> None:
        window = self.window()
        output_root = self.root / "exports"
        window.output_root_edit.setText(str(output_root))

        self.assertFalse(window.open_stl_button.isEnabled())
        self.assertEqual(
            window.open_stl_button.toolTip(),
            "Kein Exportordner gefunden.",
        )
        self.assertTrue(
            window.open_stl_button.testAttribute(
                Qt.WidgetAttribute.WA_AlwaysShowToolTips
            )
        )

        latest = self.write_export_folder(
            output_root,
            "20260730_100000_referenz",
            "2026-07-30T10:00:00+02:00",
        )
        window._refresh_folder_action_states(rescan=True)
        self.assertTrue(window.open_stl_button.isEnabled())
        self.assertEqual(
            window.open_stl_button.toolTip(),
            "Den Ordner des zuletzt erstellten Exports öffnen",
        )

        with patch(
            "cooling_tower.gui.main_window.open_directory"
        ) as open_directory_mock:
            window.open_stl_directory()
            open_directory_mock.assert_called_once_with(latest.resolve())

        (latest / "export_report.json").unlink()
        with patch(
            "cooling_tower.gui.main_window.open_directory"
        ) as open_directory_mock:
            window.open_stl_directory()
            open_directory_mock.assert_not_called()
        self.assertFalse(window.open_stl_button.isEnabled())
        self.assertEqual(
            window.open_stl_button.toolTip(),
            "Kein gültiger Exportordner gefunden.",
        )
        window.close()

    def test_slicer_dropdown_keeps_every_verified_installation(self) -> None:
        window = self.window()
        installations = tuple(
            SlicerInstallation(
                adapter_id=f"adapter-{index:02d}",
                product_name=f"Slicer {index:02d}",
                version="1.0",
                executable_path=self.root / f"slicer-{index:02d}.exe",
                verified=True,
                capabilities=frozenset({SlicerCapability.CLI_SLICE}),
                support_level=SlicerSupportLevel.FULL,
                discovery_source=SlicerDiscoverySource.KNOWN_PATH,
                family=SlicerFamily.OTHER,
            )
            for index in range(14)
        )
        result = SlicerDiscoveryResult(
            installations=installations,
            recommended_key=installations[0].identity_key,
            gui_state=SlicerGuiState.AVAILABLE,
            message="14 Slicer erkannt.",
        )

        window._slicer_request_id = 7
        window._on_slicer_discovery_succeeded(7, result)

        self.assertEqual(window.slicer_combo.count(), len(installations))
        self.assertEqual(window.slicer_combo.maxVisibleItems(), 10)
        self.assertEqual(
            window.slicer_combo.view().verticalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAsNeeded,
        )
        self.assertEqual(
            {
                window.slicer_combo.itemData(index)
                for index in range(window.slicer_combo.count())
            },
            {installation.identity_key for installation in installations},
        )
        window.close()

    def test_every_numeric_setting_has_an_explanatory_info_button(self) -> None:
        window = self.window()
        self.assertTrue(window._setting_widgets)
        for setting_name, setting in window._setting_widgets.items():
            with self.subTest(setting_name=setting_name):
                self.assertFalse(setting.info_button.isHidden())
                self.assertTrue(setting.info_button.toolTip().strip())
                self.assertIn(
                    setting.label.text(),
                    setting.info_button.accessibleName(),
                )
        self.assertTrue(window.automatic_base_info_button.toolTip().strip())
        self.assertTrue(window.output_root_info_button.toolTip().strip())
        window.close()

    def test_manual_base_reset_is_in_the_same_row_as_its_editor(self) -> None:
        window = self.window()
        setting = window._setting_widgets["manual_base_width_mm"]
        layout = setting.layout()
        editor_position = layout.getItemPosition(
            layout.indexOf(window.manual_base_width_spin)
        )
        reset_position = layout.getItemPosition(
            layout.indexOf(window.automatic_base_reset_button)
        )
        self.assertEqual(editor_position[0], reset_position[0])
        self.assertEqual(reset_position[1], editor_position[1] + 1)
        window.automatic_base_checkbox.setChecked(False)
        self.app.processEvents()
        self.assertFalse(window.automatic_base_reset_button.isHidden())
        window.close()

    def test_prediction_rows_expose_visible_value_icons(self) -> None:
        window = self.window()
        self.assertEqual(
            set(window.prediction_value_icons),
            set(window.prediction_value_labels),
        )
        self.assertTrue(
            all(label.text().strip() for label in window.prediction_value_icons.values())
        )
        window.close()

    def test_runtime_diagnostics_are_appended(self) -> None:
        log_path = self.root / "runtime.log"
        append_runtime_diagnostic("first-source", "first detail", log_path)
        append_runtime_diagnostic("second-source", "second detail", log_path)
        content = log_path.read_text(encoding="utf-8")
        self.assertIn("[first-source]", content)
        self.assertIn("first detail", content)
        self.assertIn("[second-source]", content)
        self.assertIn("second detail", content)


if __name__ == "__main__":
    unittest.main()
