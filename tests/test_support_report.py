from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
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
    def test_clipboard_crash_report_omits_raw_update_error_details(self):
        from cooling_tower.support_report import previous_crash_report_for_export
        first = DiagnosticJournal(self.root / "logs/background_jobs.jsonl")
        first.start_session()
        first.record("update_installer_launch_failed", target_version="9.9.9", winerror=225,
                     error_message="private user content", traceback="private source path",
                     installer_log_path="C:/private/setup.log", attempt_id="private token")
        second = DiagnosticJournal(first.log_path)
        second.start_session()
        exported = previous_crash_report_for_export(second)
        self.assertIn("update_installer_launch_failed", exported)
        self.assertIn("225", exported)
        self.assertNotIn("private", exported)
        self.assertNotIn("attempt_id", exported)
        self.assertIn("private user content", first.log_path.read_text())
        second.close_session()

    def test_next_session_bundle_includes_previous_update_failure_and_setup_stage(self):
        from cooling_tower.update_installation import recover_update_outcomes
        logs = self.root / "logs"
        first = DiagnosticJournal(logs / "background_jobs.jsonl")
        first.start_session()
        first.record("update_installer_launch_failed", target_version="9.9.9", winerror=225)
        first.close_session()
        native_logs = logs / "updates"
        native_logs.mkdir()
        (native_logs / "update-test.status").write_text(
            "protocol=1\nversion=9.9.9\nstage=ready\nstage=setup_failed\n")
        (native_logs / "update-test.log").write_text("private raw installer data")
        second = DiagnosticJournal(logs / "background_jobs.jsonl")
        second.start_session()
        recover_update_outcomes(native_logs, second, "0.8.14")
        service = SupportReportService(self.root, diagnostic_journal=second)
        bundle = service.create_bundle(title="Update fehlgeschlagen", description="Fehler aus vorheriger Sitzung")
        with zipfile.ZipFile(bundle.path) as archive:
            diagnostics = archive.read("diagnose.log").decode("utf-8")
        self.assertIn("update_installer_launch_failed", diagnostics)
        self.assertIn("update_previous_outcome", diagnostics)
        self.assertIn("setup_failed", diagnostics)
        self.assertIn("9.9.9", diagnostics)
        self.assertIn("225", diagnostics)
        self.assertNotIn("private raw installer data", diagnostics)
        second.close_session()

    def test_update_diagnostics_keep_native_codes_and_drop_local_raw_details(self):
        service = SupportReportService(Path(self.temporary.name))
        result = service._sanitize_journal_entry({
            "event": "update_installer_launch_failed", "target_version": "0.8.14",
            "winerror": 225, "errno": 13, "http_status": 403,
            "error_message": "private personal text", "installer_log_path": "C:/Users/private/setup.log",
            "attempt_id": "user identifying token", "return_code": 0xC0000005,
        }, session_alias="session-1")
        self.assertEqual(result["event"], "update_installer_launch_failed")
        self.assertEqual(result["winerror"], 225)
        self.assertEqual(result["errno"], 13)
        self.assertEqual(result["http_status"], 403)
        self.assertEqual(result["target_version"], "0.8.14")
        self.assertNotIn("private", json.dumps(result))
        self.assertNotIn("attempt_id", result)

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
        self.assertNotIn("Kein verwendbarer Slicer erkannt", diagnostics)
        self.assertIn('"workflow_stage": "degraded"', diagnostics)
        self.assertIn("<Freitext ausgelassen>", diagnostics)
        self.assertIn("Traceback-Rahmen: Zeile 42", diagnostics)
        self.assertIn("Ausnahmetyp: RuntimeError", diagnostics)
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
        self.assertEqual(manifest["support_report_schema_version"], 3)
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

    def test_arbitrary_names_are_excluded_even_in_nested_keys_and_allowed_fields(self) -> None:
        private = "Erika Musterfrau geheime Krankengeschichte"
        journal = DiagnosticJournal(self.root / "logs/background_jobs.jsonl")
        journal.start_session()
        journal.record(
            "profile_matching_finished", message=private, reason=private,
            error_type=private, worker_class=private, product_name=private,
            active_jobs=[{private: 42, "job_kind": "preview", "state": private}],
            profile_name=private, result_code=private,
        )
        bundle = SupportReportService(self.root, diagnostic_journal=journal).create_bundle(
            title="Fehler", description="Keine persönlichen Angaben",
            application_context={
                private: {"state": "ready"}, "profile_name": private,
                "profile": {"status_text": private, private: True, "state": "matched"},
                "settings": {"target_layer_time_s": 10.0, private: "ready"},
                "active_background_jobs": [{"job_kind": "preview", "state": "running"}],
                "visible_error": private,
            },
        )
        with zipfile.ZipFile(bundle.path) as archive:
            exported = "\n".join(archive.read(name).decode("utf-8") for name in archive.namelist())
        self.assertNotIn(private, exported)
        self.assertIn("Profil 1", exported)
        self.assertIn('"target_layer_time_s": 10.0', exported)
        self.assertIn('"job_kind": "preview"', exported)
        self.assertIn('"state": "matched"', exported)

    def test_no_technical_field_passes_arbitrary_text_or_object_representations(self) -> None:
        from cooling_tower.support_report import _JOURNAL_SAFE_KEYS
        from cooling_tower.support_privacy import CONTEXT_KEYS, SETTING_KEYS

        class PrivateObject:
            def __str__(self):
                raise AssertionError("Object representation must not be exported")

            __repr__ = __str__

        service = SupportReportService(self.root)
        private = "Erika Musterfrau: persönliche medizinische Angaben"
        for key in _JOURNAL_SAFE_KEYS | CONTEXT_KEYS | SETTING_KEYS:
            with self.subTest(key=key):
                exported = json.dumps(service._sanitize_context_value({key: private}), ensure_ascii=False)
                self.assertNotIn(private, exported)
                service._sanitize_context_value({key: PrivateObject()})
        cyclic = {"profile": None}
        cyclic["profile"] = cyclic
        self.assertIn("Verschachtelung ausgelassen", json.dumps(service._sanitize_context_value(cyclic)))

    def test_malformed_logs_and_untrusted_traceback_names_do_not_leak(self) -> None:
        logs = self.root / "logs"
        logs.mkdir()
        (logs / "background_jobs.jsonl").write_text(
            'not json\n[]\n{"event": "PRIVATE-NAME", "utc_time": "PERSONAL"}\n',
            encoding="utf-8",
        )
        (logs / "application_runtime.log").write_text(
            '  File "C:/private/health.py", line 42, in ErikaPrivat\n'
            'ErikaPrivateError: health data\nRuntimeError: PRIVATE-MESSAGE\n', encoding="utf-8",
        )
        bundle = SupportReportService(self.root).create_bundle(title="Fehler", description="Text")
        with zipfile.ZipFile(bundle.path) as archive:
            diagnostics = archive.read("diagnose.log").decode("utf-8")
        for private in ("PRIVATE-NAME", "PERSONAL", "health", "Erika", "PRIVATE-MESSAGE"):
            self.assertNotIn(private, diagnostics)
        self.assertIn("Traceback-Rahmen: Zeile 42", diagnostics)
        self.assertIn("Ausnahmetyp: RuntimeError", diagnostics)
        self.assertIn("unknown_event", diagnostics)

    def test_concurrent_exports_do_not_replace_each_other(self) -> None:
        service = SupportReportService(self.root, now_provider=lambda: self.created_at)
        def export(index):
            return service.create_bundle(title=f"Fehler {index}", description=f"Bericht {index}")
        with ThreadPoolExecutor(max_workers=4) as pool:
            bundles = list(pool.map(export, range(8)))
        self.assertEqual(len({bundle.path for bundle in bundles}), 8)
        for index, bundle in enumerate(bundles):
            with zipfile.ZipFile(bundle.path) as archive:
                self.assertIn(f"Bericht {index}", archive.read("problembericht.txt").decode("utf-8"))

    def test_failed_zip_write_leaves_no_partial_or_replaced_bundle(self) -> None:
        service = SupportReportService(self.root, now_provider=lambda: self.created_at)
        previous = service.create_bundle(title="Vorhanden", description="Erhalten")
        original = previous.path.read_bytes()
        with patch("cooling_tower.support_report.zipfile.ZipFile.writestr", side_effect=OSError("full")):
            with self.assertRaises(OSError):
                service.create_bundle(title="Fehler", description="Text")
        self.assertEqual(previous.path.read_bytes(), original)
        self.assertEqual(list(service.output_directory.iterdir()), [previous.path])

    def test_logs_outside_own_directory_and_external_output_are_rejected(self) -> None:
        external = self.root / "external"
        external.mkdir()
        source = external / "slicer-profile.json"
        source.write_text('{"name":"Private Profile"}', encoding="utf-8")
        original = source.read_bytes()
        service = SupportReportService(self.root / "app")
        with self.assertRaises(OSError):
            service._read_log_tail(source, 100)
        service.output_directory = external / "output"
        with self.assertRaises(ValueError):
            service.create_bundle(title="Fehler", description="Text")
        self.assertFalse(service.output_directory.exists())
        self.assertEqual(source.read_bytes(), original)

    def test_large_logs_and_collections_are_bounded_before_export(self) -> None:
        logs = self.root / "logs"
        logs.mkdir()
        path = logs / "background_jobs.jsonl"
        path.write_bytes(b"sensitive-prefix" + b"x" * 100 + b'\n{"event":"session_started"}\n')
        service = SupportReportService(self.root)
        tail, truncated = service._read_log_tail(path, 50)
        self.assertTrue(truncated)
        self.assertEqual(tail, b'{"event":"session_started"}\n')
        self.assertEqual(len(service._sanitize_context_value([None] * 1000)), 100)
        self.assertIsNone(service._sanitize_context_value({"duration_s": float("nan")})["duration_s"])
        self.assertEqual(service._sanitize_context_value({"return_code": 0xC0000142})["return_code"], 0xC0000142)
        with self.assertRaises(ValueError):
            service.create_bundle(title="x" * 501, description="Text")

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
        self.assertIn("<Freitext ausgelassen>", diagnostics)

    def test_only_two_most_recent_sessions_are_copied(self) -> None:
        log_root = self.root / "logs"
        log_root.mkdir(parents=True)
        entries = [
            {
                "session_id": session,
                "event": "session_started",
                "event_sequence": {"old": 1, "previous": 2, "current": 3}[session],
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

        self.assertNotIn('"event_sequence": 1,', diagnostics)
        self.assertIn('"event_sequence": 2', diagnostics)
        self.assertIn('"event_sequence": 3', diagnostics)
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
            self.assertIn("öffentlich", privacy_text)
            self.assertIn("issues/new/choose", dialog.issue_link.text())
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
