from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("COOLING_TOWER_DISABLE_SLICER_DISCOVERY", "1")

from PySide6.QtWidgets import QApplication

from cooling_tower.diagnostics import DiagnosticJournal
from cooling_tower.gui.main_window import MainWindow
from cooling_tower.support_report import SupportReportService


class SupportReportServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.created_at = datetime(
            2026,
            7,
            31,
            16,
            42,
            5,
            tzinfo=timezone(timedelta(hours=2)),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_bundle_contains_report_manifest_and_sanitized_diagnostics(self) -> None:
        log_root = self.root / "logs"
        journal = DiagnosticJournal(log_root / "background_jobs.jsonl")
        journal.start_session()
        journal.record(
            "slicer_discovery_completed",
            gui_state="not_found",
            message=(
                "Kein verwendbarer Slicer erkannt; Eingabe "
                "D:\\Private\\Modelle\\geheim.gcode von "
                "tester@example.com über https://example.test/support "
                "an 192.168.1.25"
            ),
            command=["D:\\Programme\\slicer.exe", "--token", "privat"],
            source_profile_fingerprint="a" * 64,
        )
        log_root.mkdir(parents=True, exist_ok=True)
        (log_root / "application_runtime.log").write_text(
            "Unstrukturierter Rohtext von Max Mustermann darf nicht hinein.\n"
            "Traceback (most recent call last):\n"
            '  File "D:\\Private\\Quellcode\\intern.py", line 42, '
            "in auswerten\n"
            "RuntimeError: Fehler für tester@example.com in "
            "D:\\Private\\Modelle\\geheim.gcode\n",
            encoding="utf-8",
        )
        service = SupportReportService(
            self.root,
            diagnostic_journal=journal,
            now_provider=lambda: self.created_at,
        )

        bundle = service.create_bundle(
            title="Slicer wird bei tester@example.com nicht erkannt",
            description=(
                "Nach dem Start bleibt geheim.gcode leer. API-Key=topsecret; "
                "Kontakt +49 170 1234567."
            ),
            application_context={
                "workflow_stage": "degraded",
                "source_path": "D:\\Private\\Modelle\\geheim.gcode",
                "nested": {
                    "safe_state": "failed",
                    "hostname": "PRIVATE-PC",
                    "request_id": "private-request",
                },
            },
        )

        self.assertEqual(
            bundle.path.parent,
            (self.root / "output" / "support_reports").resolve(),
        )
        self.assertEqual(
            bundle.path.name,
            "SacrificialTower_Problembericht_2026-07-31_16-42-05.zip",
        )
        with zipfile.ZipFile(bundle.path) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {"problembericht.txt", "diagnose.log", "manifest.json"},
            )
            report = archive.read("problembericht.txt").decode("utf-8")
            diagnostics = archive.read("diagnose.log").decode("utf-8")
            manifest = json.loads(archive.read("manifest.json"))

        self.assertIn("31.07.2026 um 16:42:05 Uhr", report)
        self.assertIn("tester@example.com", report)
        self.assertIn("geheim.gcode", report)
        self.assertIn("API-Key=topsecret", report)
        self.assertIn("+49 170 1234567", report)
        self.assertIn("slicer_discovery_completed", diagnostics)
        self.assertIn("Kein verwendbarer Slicer erkannt", diagnostics)
        self.assertIn('"workflow_stage": "degraded"', diagnostics)
        self.assertIn("<entfernter-pfad>", diagnostics)
        self.assertIn("<entfernte-url>", diagnostics)
        self.assertIn("<entfernte-netzwerkadresse>", diagnostics)
        self.assertIn("Traceback-Rahmen: Zeile 42, Funktion auswerten", diagnostics)
        self.assertIn("Ausnahmetyp: RuntimeError", diagnostics)
        self.assertIn('"safe_state": "failed"', diagnostics)
        self.assertNotIn("D:\\Private", diagnostics)
        self.assertNotIn("tester@example.com", diagnostics)
        self.assertNotIn("geheim.gcode", diagnostics)
        self.assertNotIn("intern.py", diagnostics)
        self.assertNotIn("Max Mustermann", diagnostics)
        self.assertNotIn("PRIVATE-PC", diagnostics)
        self.assertNotIn("private-request", diagnostics)
        self.assertNotIn("source_profile_fingerprint", diagnostics)
        self.assertNotIn("privat", diagnostics)
        self.assertEqual(manifest["report_id"], bundle.report_id)
        self.assertEqual(manifest["support_report_schema_version"], 2)
        self.assertFalse(manifest["privacy"]["raw_logs_included"])
        self.assertFalse(manifest["privacy"]["user_files_included"])
        self.assertTrue(manifest["privacy"]["user_text_stored_verbatim"])
        self.assertFalse(manifest["transmitted"])

    def test_same_second_uses_readable_numeric_suffix(self) -> None:
        service = SupportReportService(
            self.root,
            now_provider=lambda: self.created_at,
        )
        first = service.create_bundle(title="Fehler", description="Beschreibung")
        second = service.create_bundle(title="Fehler", description="Beschreibung")

        self.assertNotEqual(first.path, second.path)
        self.assertEqual(
            second.path.name,
            "SacrificialTower_Problembericht_2026-07-31_16-42-05_2.zip",
        )

    def test_technical_diagnostics_filter_common_identifiers_and_secrets(self) -> None:
        log_root = self.root / "logs"
        journal = DiagnosticJournal(log_root / "background_jobs.jsonl")
        journal.start_session()
        sensitive_lines = (
            "/home/alice/models/private_part.stl\n"
            "\\\\fileserver\\private\\customer.3mf\n"
            "https://support.example.test/ticket/4711\n"
            "alice@example.test\n"
            "10.23.45.67\n"
            "2001:db8::1234\n"
            "00:11:22:33:44:55\n"
            "access_token=very-secret-value\n"
            "github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890\n"
            + "b" * 64
        )
        journal.record("qt_message", message=sensitive_lines)
        service = SupportReportService(
            self.root,
            diagnostic_journal=journal,
            now_provider=lambda: self.created_at,
        )

        bundle = service.create_bundle(
            title="Benutzereingabe bleibt sichtbar",
            description=sensitive_lines,
            application_context={"visible_error": sensitive_lines},
        )
        with zipfile.ZipFile(bundle.path) as archive:
            report = archive.read("problembericht.txt").decode("utf-8")
            diagnostics = archive.read("diagnose.log").decode("utf-8")

        self.assertIn(sensitive_lines, report)
        for sensitive_value in (
            "/home/alice",
            "fileserver",
            "customer.3mf",
            "support.example.test",
            "alice@example.test",
            "10.23.45.67",
            "2001:db8::1234",
            "00:11:22:33:44:55",
            "very-secret-value",
            "github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890",
            "b" * 64,
        ):
            self.assertNotIn(sensitive_value, diagnostics)
        self.assertIn("<entfernter-pfad>", diagnostics)
        self.assertIn("<entfernte-url>", diagnostics)
        self.assertIn("<entfernte-e-mail>", diagnostics)
        self.assertIn("<entfernte-netzwerkadresse>", diagnostics)
        self.assertIn("<entferntes-geheimnis>", diagnostics)
        self.assertIn("<entfernte-kennung>", diagnostics)

    def test_only_two_most_recent_sessions_are_copied(self) -> None:
        log_root = self.root / "logs"
        log_root.mkdir(parents=True)
        entries = [
            {
                "session_id": session,
                "event": marker,
                "job_id": f"private-{session}",
            }
            for session, marker in (
                ("old", "NICHT_AUFNEHMEN"),
                ("previous", "VORHERIGE_SITZUNG"),
                ("current", "AKTUELLE_SITZUNG"),
            )
        ]
        (log_root / "background_jobs.jsonl").write_text(
            "".join(json.dumps(entry) + "\n" for entry in entries),
            encoding="utf-8",
        )
        service = SupportReportService(
            self.root,
            now_provider=lambda: self.created_at,
        )

        bundle = service.create_bundle(title="Fehler", description="Beschreibung")
        with zipfile.ZipFile(bundle.path) as archive:
            diagnostics = archive.read("diagnose.log").decode("utf-8")

        self.assertNotIn("NICHT_AUFNEHMEN", diagnostics)
        self.assertIn("VORHERIGE_SITZUNG", diagnostics)
        self.assertIn("AKTUELLE_SITZUNG", diagnostics)
        self.assertNotIn('"session_id"', diagnostics)
        self.assertNotIn("private-previous", diagnostics)
        self.assertIn('"session": "Sitzung-1"', diagnostics)
        self.assertIn('"session": "Sitzung-2"', diagnostics)


class SupportReportDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.app.processEvents()
        self.temporary.cleanup()

    def test_menu_dialog_creates_zip_and_opens_its_folder(self) -> None:
        window = MainWindow(
            user_data_root=self.root,
            enable_update_check=False,
        )
        with patch("cooling_tower.gui.main_window.open_directory") as open_mock:
            window.support_report_action.trigger()
            self.app.processEvents()
            dialog = window.support_report_dialog
            self.assertTrue(dialog.isVisible())
            self.assertIn(
                "wird nicht automatisch übertragen",
                dialog.findChild(
                    type(dialog.result_label), "supportReportIntroduction"
                ).text(),
            )
            privacy_text = dialog.findChild(
                type(dialog.result_label), "supportReportPrivacyText"
            ).text()
            self.assertNotIn("nach Möglichkeit", privacy_text)
            self.assertTrue(privacy_text.startswith("Wichtig:"))
            self.assertIn("Rohlogs", privacy_text)
            self.assertIn("unverändert im Klartext", privacy_text)
            self.assertIn(
                "keine persönlichen oder sensiblen Daten",
                privacy_text,
            )
            self.assertIn("vor der Weitergabe", privacy_text)
            dialog.summary_edit.setText("Slicer fehlt")
            dialog.description_edit.setPlainText(
                "Die Slicer-Liste bleibt nach dem Programmstart leer."
            )
            dialog.create_button.click()
            self.app.processEvents()

            self.assertIsNotNone(dialog.last_bundle_path)
            assert dialog.last_bundle_path is not None
            self.assertTrue(dialog.last_bundle_path.is_file())
            self.assertIn("erfolgreich erstellt", dialog.result_label.text())

            dialog.open_folder_button.click()
            open_mock.assert_called_once_with(
                (self.root / "output" / "support_reports").resolve()
            )
        window.close()

    def test_required_report_fields_are_validated(self) -> None:
        window = MainWindow(
            user_data_root=self.root,
            enable_update_check=False,
        )
        dialog = window.support_report_dialog
        dialog.create_button.click()

        self.assertTrue(dialog.summary_edit.property("invalid"))
        self.assertTrue(dialog.description_edit.property("invalid"))
        self.assertIn("Bitte füllen Sie", dialog.result_label.text())
        self.assertEqual(
            list((self.root / "output").rglob("*.zip"))
            if (self.root / "output").exists()
            else [],
            [],
        )
        window.close()
