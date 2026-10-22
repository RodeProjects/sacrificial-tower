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
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("COOLING_TOWER_DISABLE_SLICER_DISCOVERY", "1")

from PySide6.QtCore import QPoint, QRect, QSequentialAnimationGroup, Qt, QUrlQuery
from PySide6.QtGui import QColor, QFont, QTextDocument
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton, QTextEdit

from gui_lifecycle import dispose_test_widget
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
        bundle = service.create_bundle()
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
            "SacrificialTower_Diagnosepaket_2026-07-31_16-42-05.zip",
        )
        with zipfile.ZipFile(bundle.path) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {"hinweise.txt", "diagnose.log", "manifest.json"},
            )
            report = archive.read("hinweise.txt").decode("utf-8")
            diagnostics = archive.read("diagnose.log").decode("utf-8")
            manifest = json.loads(archive.read("manifest.json"))

        self.assertIn("31.07.2026 um 16:42:05 Uhr", report)
        self.assertIn("keine Problembeschreibung", report)
        self.assertIn("direkt im GitHub-Formular beschreiben", report)
        self.assertNotIn("tester@example.com", report)
        self.assertNotIn("geheim.gcode", report)
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
        self.assertEqual(manifest["support_report_schema_version"], 4)
        self.assertEqual(set(manifest["files"]), {"hinweise.txt", "diagnose.log", "manifest.json"})
        self.assertFalse(manifest["privacy"]["raw_logs_included"])
        self.assertFalse(manifest["privacy"]["user_files_included"])
        self.assertFalse(manifest["privacy"]["user_text_included"])
        self.assertNotIn("user_text_stored_verbatim", manifest["privacy"])
        self.assertFalse(manifest["transmitted"])

    def test_same_second_uses_readable_numeric_suffix(self) -> None:
        service = SupportReportService(
            self.root,
            now_provider=lambda: self.created_at,
        )
        first = service.create_bundle()
        second = service.create_bundle()

        self.assertNotEqual(first.path, second.path)
        self.assertEqual(
            second.path.name,
            "SacrificialTower_Diagnosepaket_2026-07-31_16-42-05_2.zip",
        )

    def test_new_technical_bundle_preserves_existing_user_report_zip(self) -> None:
        service = SupportReportService(self.root, now_provider=lambda: self.created_at)
        directory = service.ensure_output_directory()
        previous = directory / "SacrificialTower_Problembericht_2026-07-31_16-42-05.zip"
        with zipfile.ZipFile(previous, "w") as archive:
            archive.writestr("problembericht.txt", "Private Beschreibung aus einem alten Paket")
            archive.writestr("manifest.json", '{"support_report_schema_version": 3}')
        original = previous.read_bytes()
        bundle = service.create_bundle()
        self.assertEqual(previous.read_bytes(), original)
        self.assertNotEqual(previous, bundle.path)
        with zipfile.ZipFile(bundle.path) as archive:
            self.assertNotIn("problembericht.txt", archive.namelist())
            for name in archive.namelist():
                self.assertNotIn("Private Beschreibung", archive.read(name).decode("utf-8"))

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
        bundle = SupportReportService(self.root).create_bundle()
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
            return service.create_bundle()
        with ThreadPoolExecutor(max_workers=4) as pool:
            bundles = list(pool.map(export, range(8)))
        self.assertEqual(len({bundle.path for bundle in bundles}), 8)
        for index, bundle in enumerate(bundles):
            with zipfile.ZipFile(bundle.path) as archive:
                self.assertIn(bundle.report_id, archive.read("hinweise.txt").decode("utf-8"))
                self.assertEqual(json.loads(archive.read("manifest.json"))["report_id"], bundle.report_id)

    def test_failed_zip_write_leaves_no_partial_or_replaced_bundle(self) -> None:
        service = SupportReportService(self.root, now_provider=lambda: self.created_at)
        previous = service.create_bundle()
        original = previous.path.read_bytes()
        with patch("cooling_tower.support_report.zipfile.ZipFile.writestr", side_effect=OSError("full")):
            with self.assertRaises(OSError):
                service.create_bundle()
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
            service.create_bundle()
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
            application_context={"visible_error": sensitive_lines},
        )
        with zipfile.ZipFile(bundle.path) as archive:
            report = archive.read("hinweise.txt").decode("utf-8")
            diagnostics = archive.read("diagnose.log").decode("utf-8")

        self.assertNotIn(sensitive_lines, report)
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

        bundle = service.create_bundle()
        with zipfile.ZipFile(bundle.path) as archive:
            diagnostics = archive.read("diagnose.log").decode("utf-8")

        self.assertNotIn('"event_sequence": 1,', diagnostics)
        self.assertIn('"event_sequence": 2', diagnostics)
        self.assertIn('"event_sequence": 3', diagnostics)
        self.assertNotIn('"session_id"', diagnostics)
        self.assertNotIn("private-previous", diagnostics)
        self.assertIn('"session": "Sitzung-1"', diagnostics)
        self.assertIn('"session": "Sitzung-2"', diagnostics)


class SupportEntryPointTests(unittest.TestCase):
    def test_security_policy_has_direct_contact_and_links_with_a_branch(self) -> None:
        from cooling_tower.legal_documents import legal_profile
        text = (PROJECT_ROOT / ".github/SECURITY.md").read_text(encoding="utf-8")
        email = legal_profile()["provider_email"]
        self.assertIn(f"[{email}](mailto:{email})", text)
        self.assertIn("https://github.com/RodeProjects/sacrificial-tower/blob/main/legal/privacy.md", text)
        self.assertNotIn("../legal/", text)
        self.assertNotIn("../config/", text)

    def test_github_form_names_are_german(self) -> None:
        for filename, title in (
            ("01-bug.yml", "Fehler melden"),
            ("02-feature.yml", "Funktion vorschlagen"),
            ("03-question.yml", "Sonstige Frage"),
        ):
            with self.subTest(filename=filename):
                text = (PROJECT_ROOT / ".github/ISSUE_TEMPLATE" / filename).read_text(encoding="utf-8")
                self.assertEqual(text.splitlines()[0], f'name: "{title}"')


class SupportReportDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.window = MainWindow(user_data_root=self.root, enable_update_check=False)
        self.window.support_report_dialog.pages._effective_transition_duration_ms = 25

    def tearDown(self) -> None:
        dispose_test_widget(self.window)
        self.app.processEvents()
        self.temporary.cleanup()

    def wait_for_page(self, dialog, index: int) -> None:
        if dialog.pages.currentIndex() != index or dialog.pages._transition_animation is not None:
            changed = QSignalSpy(dialog.pages.currentChanged)
            self.assertTrue(changed.wait(1000), "Seitenübergang wurde nicht abgeschlossen")
        self.assertEqual(dialog.pages.currentIndex(), index)
        self.assertIsNone(dialog.pages._transition_animation)
        self.app.processEvents()

    def show_topic(self, topic="bug"):
        self.window.support_report_action.trigger()
        QTest.qWait(60)
        dialog = self.window.support_report_dialog
        if dialog.pages.currentIndex() == 1:
            if dialog.selected_topic == topic:
                return dialog
            dialog.back_button.click()
            self.wait_for_page(dialog, 0)
        dialog.topic_buttons[topic].click()
        self.wait_for_page(dialog, 1)
        return dialog

    def test_selection_opens_directly_without_radio_buttons_or_external_services(self) -> None:
        self.window.support_report_action.trigger()
        QTest.qWait(60)
        dialog = self.window.support_report_dialog
        self.assertEqual(len(dialog.topic_buttons), 6)
        self.assertEqual(dialog.pages.currentIndex(), 0)
        self.assertFalse(any(button.text() == "Weiter" for button in dialog.findChildren(QPushButton)))
        self.assertFalse(dialog.back_button.isVisible())
        columns = (("bug", "question", "feature"), ("review", "support", "contact"))
        rectangles = [dialog.topic_buttons[key].geometry() for column in columns for key in column]
        self.assertEqual(len({rectangle.left() for rectangle in rectangles}), 2)
        self.assertEqual(len({rectangle.width() for rectangle in rectangles}), 1)
        for column in columns:
            tops = [dialog.topic_buttons[key].geometry().top() for key in column]
            self.assertEqual(tops, sorted(set(tops)))
        for left, right in zip(*columns):
            left_rect = dialog.topic_buttons[left].geometry()
            right_rect = dialog.topic_buttons[right].geometry()
            self.assertLess(left_rect.right(), right_rect.left())
            self.assertEqual(left_rect.top(), right_rect.top())
            self.assertEqual(left_rect.height(), right_rect.height())
        with patch("cooling_tower.gui.support_report_dialog.QDesktopServices.openUrl") as external:
            dialog.pages.setCurrentIndex(1)
            self.assertEqual(dialog.pages.currentIndex(), 0)
            QTest.mouseClick(dialog.topic_buttons["feature"], Qt.MouseButton.LeftButton)
            dialog.topic_buttons["question"].click()
            self.assertFalse(any(button.isCheckable() for button in dialog.topic_buttons.values()))
            self.assertFalse(dialog.findChildren(QLabel, "supportTopicIndicator"))
            self.assertEqual(dialog.selected_topic, "feature")
            self.wait_for_page(dialog, 1)
            self.assertTrue(dialog.route_contents["feature"].isVisible())
            self.assertFalse(dialog.bug_content.isVisible())
            self.assertIsNone(dialog.last_bundle_path)
            external.assert_not_called()
            dialog.back_button.click()
            self.assertFalse(dialog.back_button.isVisible())
            self.wait_for_page(dialog, 0)
            self.assertEqual(dialog.pages.currentIndex(), 0)
            self.assertEqual(dialog.selected_topic, "feature")

    def test_topic_card_can_be_opened_with_enter(self) -> None:
        self.window.support_report_action.trigger()
        QTest.qWait(60)
        dialog = self.window.support_report_dialog
        card = dialog.topic_buttons["question"]
        card.setFocus()
        QTest.keyClick(card, Qt.Key.Key_Return)
        self.wait_for_page(dialog, 1)
        self.assertEqual(dialog.pages.currentIndex(), 1)
        self.assertEqual(dialog.selected_topic, "question")

    def test_question_and_feature_open_their_exact_forms_without_diagnostics(self) -> None:
        for topic, filename, caption in (
            ("question", "03-question.yml", "Frage auf GitHub stellen"),
            ("feature", "02-feature.yml", "Funktion auf GitHub vorschlagen"),
        ):
            with self.subTest(topic=topic), patch.object(
                self.window.support_report_dialog.service, "create_bundle"
            ) as create, patch("cooling_tower.gui.support_report_dialog.QDesktopServices.openUrl") as external:
                dialog = self.show_topic(topic)
                self.assertFalse(dialog.create_button.isVisible())
                self.assertFalse(dialog.open_folder_button.isVisible())
                self.assertFalse(dialog.skip_button.isVisible())
                external.assert_not_called()
                button = getattr(dialog, topic + "_button")
                self.assertEqual(button.text(), caption)
                self.assertAlmostEqual(
                    button.geometry().center().x(), button.parentWidget().rect().center().x(), delta=1,
                )
                button.click()
                external.assert_called_once()
                url = external.call_args.args[0]
                self.assertEqual(url.host(), "github.com")
                self.assertEqual(url.path(), "/RodeProjects/sacrificial-tower/issues/new")
                self.assertEqual(QUrlQuery(url).queryItemValue("template"), filename)
                create.assert_not_called()

    def test_review_is_a_local_placeholder_without_platform_links(self) -> None:
        with patch("cooling_tower.gui.support_report_dialog.QDesktopServices.openUrl") as external:
            dialog = self.show_topic("review")
            notice = dialog.route_contents["review"].findChild(QLabel, "supportReviewPlaceholder")
            self.assertIn("Aktuell gibt es noch keine Plattformen", notice.text())
            self.assertIn("passenden Links", notice.text())
            self.assertIn("\nSobald Bewertungsmöglichkeiten", notice.text())
            self.assertFalse(dialog.route_contents["review"].findChildren(QPushButton))
            self.assertFalse(dialog.create_button.isVisible())
            stars = dialog.route_contents["review"].findChildren(QLabel, "supportReviewStar")
            self.assertEqual(len(stars), 5)
            self.assertEqual(len({star.y() for star in stars}), 1)
            self.assertTrue(all(star.width() == star.height() == 20 for star in stars))
            self.assertEqual([star.x() for star in stars], sorted({star.x() for star in stars}))
            external.assert_not_called()

    def test_support_reuses_amount_dialog_only_after_explicit_click(self) -> None:
        with patch("cooling_tower.gui.support_report_dialog.QDesktopServices.openUrl") as external:
            self.window.support_report_action.trigger()
            QTest.qWait(60)
            dialog = self.window.support_report_dialog
            geometry = dialog.frameGeometry()
            transitions = QSignalSpy(dialog.pages.transition_started)
            visible_when_requested = []
            dialog.voluntary_support_requested.connect(lambda: visible_when_requested.append(dialog.isVisible()))
            self.assertIsNone(self.window._voluntary_support_dialog)
            dialog.topic_buttons["support"].click()
            self.assertFalse(dialog.isVisible())
            self.assertEqual(visible_when_requested, [False])
            self.assertIsNotNone(self.window._voluntary_support_dialog)
            self.assertTrue(self.window._voluntary_support_dialog.isVisible())
            self.assertEqual(dialog.pages.currentIndex(), 0)
            self.assertIsNone(dialog.selected_topic)
            self.assertEqual(dialog.frameGeometry(), geometry)
            self.assertEqual(transitions.count(), 0)
            self.assertNotIn("support", dialog.route_contents)
            self.assertFalse(hasattr(dialog, "coffee_button"))
            external.assert_not_called()

    def test_other_requests_open_email_only_after_explicit_contact_click(self) -> None:
        with patch("cooling_tower.gui.support_report_dialog.QDesktopServices.openUrl") as external, patch.object(
            self.window.support_report_dialog.service, "create_bundle"
        ) as create:
            dialog = self.show_topic("contact")
            external.assert_not_called()
            self.assertFalse(dialog.create_button.isVisible())
            self.assertFalse(dialog.skip_button.isVisible())
            introduction = dialog.route_contents["contact"].findChild(QLabel, "supportRouteDescription")
            self.assertEqual(introduction.text(),
                "Für andere oder vertrauliche Anliegen können Sie mich gerne per E-Mail kontaktieren.")
            subtitle = dialog.route_contents["contact"].findChild(QLabel, "supportReportIntroduction")
            self.assertEqual(subtitle.text(), "Direkter Kontakt zum Entwickler")
            guidance = dialog.route_contents["contact"].findChild(QLabel, "supportContactGuidanceText").text()
            for text in ("Fehler melden", "Frage stellen", "Funktion vorschlagen", "GitHub-Formular"):
                self.assertIn(text, guidance)
            self.assertEqual(dialog.contact_button.accessibleName(), "florian.rode@outlook.com")
            self.assertEqual(dialog.contact_button.findChild(QLabel, "supportContactLinkText").text(),
                             "florian.rode@outlook.com")
            self.assertFalse(dialog.contact_button.findChild(QLabel, "supportContactLinkIcon").pixmap().isNull())
            icon = dialog.contact_button.findChild(QLabel, "supportContactLinkIcon")
            address = dialog.contact_button.findChild(QLabel, "supportContactLinkText")
            self.assertEqual(dialog.contact_button.toolTip(), "")
            self.assertGreaterEqual(address.width(), address.sizeHint().width())
            self.assertGreaterEqual(address.x() - icon.geometry().right() - 1, 8)
            self.assertAlmostEqual(icon.geometry().center().y(), address.geometry().center().y(), delta=1)
            self.assertFalse(dialog.route_contents["contact"].findChildren(QLabel, "supportContactAddress"))
            self.assertAlmostEqual(
                dialog.contact_button.geometry().center().x(),
                dialog.contact_button.parentWidget().rect().center().x(), delta=1,
            )
            dialog.contact_button.click()
            external.assert_called_once()
            url = external.call_args.args[0]
            self.assertEqual(url.toString(), "mailto:florian.rode@outlook.com")
            self.assertFalse(url.hasQuery())
            create.assert_not_called()

    def test_close_and_escape_reopen_selection_and_preserve_existing_bundle(self) -> None:
        dialog = self.show_topic()
        dialog.create_button.click()
        original_path = dialog.last_bundle_path
        with patch.object(dialog.service, "create_bundle") as create:
            for index, topic in enumerate(dialog.route_contents):
                with self.subTest(topic=topic):
                    self.show_topic(topic)
                    if index % 2:
                        QTest.keyClick(dialog, Qt.Key.Key_Escape)
                    else:
                        dialog.close_button.click()
                    QTest.qWait(30)
                    self.assertFalse(dialog.isVisible())
                    self.window.support_report_action.trigger()
                    QTest.qWait(60)
                    self.assertEqual(dialog.pages.currentIndex(), 0)
                    self.assertIsNone(dialog.selected_topic)
                    self.assertFalse(dialog.back_button.isVisible())
                    self.assertFalse(dialog.skip_button.isVisible())
                    self.assertFalse(dialog.scroll.verticalScrollBar().isVisible())
                    self.assertEqual(dialog.last_bundle_path, original_path)
                    self.assertTrue(original_path.is_file())
            create.assert_not_called()

    def test_back_and_other_topics_preserve_created_bundle_and_avoid_recreation(self) -> None:
        dialog = self.show_topic()
        with patch.object(dialog.service, "create_bundle", wraps=dialog.service.create_bundle) as create:
            dialog.create_button.click()
            original_path = dialog.last_bundle_path
            original = original_path.read_bytes()
            self.show_topic("question")
            self.show_topic("bug")
            self.assertEqual(dialog.last_bundle_path, original_path)
            self.assertEqual(original_path.read_bytes(), original)
            self.assertTrue(dialog.open_folder_button.isEnabled())
            self.assertFalse(dialog.skip_button.isVisible())
            create.assert_called_once()

    def test_bug_can_go_directly_to_form_without_creating_bundle(self) -> None:
        dialog = self.show_topic()
        self.assertTrue(dialog.skip_button.isVisible())
        with patch("cooling_tower.gui.support_report_dialog.QDesktopServices.openUrl") as external:
            dialog.skip_button.click()
            self.assertEqual(QUrlQuery(external.call_args.args[0]).queryItemValue("template"), "01-bug.yml")
        self.assertIsNone(dialog.last_bundle_path)

    def test_sequential_fades_in_both_directions_clean_up_on_resize_and_close(self) -> None:
        self.window.support_report_action.trigger()
        QTest.qWait(60)
        dialog = self.window.support_report_dialog
        dialog.pages._effective_transition_duration_ms = 80
        self.assertEqual(dialog.pages.transition_duration_ms, self.window.preparation_tabs.transition_duration_ms)
        dialog.topic_buttons["bug"].click()
        self.assertIsNotNone(dialog.pages._transition_animation)
        self.assertFalse(dialog.back_button.isEnabled())
        self.assert_sequential_fade(dialog)
        dialog.pages.setCurrentIndex(0)
        self.wait_for_page(dialog, 1)
        self.assertEqual(dialog.pages.currentIndex(), 1)
        self.assertEqual(dialog.pages.last_transition, (0, 1, 400))
        dialog.back_button.click()
        self.assertIsNotNone(dialog.pages._transition_animation)
        self.assertFalse(dialog.back_button.isVisible())
        self.assert_sequential_fade(dialog)
        self.assertFalse(dialog.back_button.isVisible())
        dialog.resize(dialog.width() + 20, dialog.height() + 20)
        QTest.qWait(30)
        self.assertEqual(dialog.pages.currentIndex(), 0)
        self.assertIsNone(dialog.pages._transition_animation)
        self.assertEqual(dialog.pages.last_transition, (1, 0, 400))
        self.assertEqual(dialog.pages.maximumHeight(), 16777215)
        dialog.topic_buttons["bug"].click()
        self.assertIsNotNone(dialog.pages._transition_animation)
        dialog.close()
        QTest.qWait(30)
        self.assertIsNone(dialog.pages._transition_animation)
        self.assertFalse(dialog.pages._transition_overlays)
        self.window.support_report_action.trigger()
        QTest.qWait(60)
        self.assertFalse(dialog.back_button.isVisible())
        self.assertEqual(dialog.pages.currentIndex(), 0)
        self.assertIsNone(dialog.selected_topic)

    def assert_sequential_fade(self, dialog) -> None:
        animation = dialog.pages._transition_animation
        self.assertIsInstance(animation, QSequentialAnimationGroup)
        self.assertEqual(animation.animationCount(), 2)
        animation.pause()
        outgoing, incoming = dialog.pages._transition_overlays
        positions = (outgoing.pos(), incoming.pos())
        duration = animation.duration()
        animation.setCurrentTime(duration // 4)
        self.assertGreater(outgoing.graphicsEffect().opacity(), 0.0)
        self.assertLess(outgoing.graphicsEffect().opacity(), 1.0)
        self.assertEqual(incoming.graphicsEffect().opacity(), 0.0)
        animation.setCurrentTime(duration // 2)
        self.assertEqual(outgoing.graphicsEffect().opacity(), 0.0)
        self.assertEqual(incoming.graphicsEffect().opacity(), 0.0)
        animation.setCurrentTime(3 * duration // 4)
        self.assertEqual(outgoing.graphicsEffect().opacity(), 0.0)
        self.assertGreater(incoming.graphicsEffect().opacity(), 0.0)
        self.assertLess(incoming.graphicsEffect().opacity(), 1.0)
        self.assertEqual((outgoing.pos(), incoming.pos()), positions)
        animation.resume()

    def test_dialog_layout_is_complete_and_stable_on_every_open(self) -> None:
        dialog = self.window.support_report_dialog
        expected_geometry = None
        for opening in range(3):
            with self.subTest(opening=opening):
                self.show_topic()
                initial_size = dialog.size()
                QTest.qWait(80)
                self.assertEqual(dialog.size(), initial_size)
                self.assertEqual(dialog.layout().geometry(), dialog.rect())
                positions = [button.mapTo(dialog.content, QPoint(0, 0)).y() for button in (
                    dialog.create_button, dialog.open_folder_button, dialog.issue_button
                )]
                self.assertEqual(positions, sorted(set(positions)))
                for label in dialog.content.findChildren(QLabel):
                    if label.isVisible() and label.wordWrap():
                        self.assertGreaterEqual(
                            label.height(), label.heightForWidth(label.width()), label.objectName()
                        )
                button_bottom = dialog.close_button.geometry().bottom()
                self.assertEqual(
                    dialog.height() - button_bottom - 1,
                    dialog.layout().contentsMargins().bottom(),
                )
                image = dialog.grab().toImage().scaled(dialog.size())
                for y in range(button_bottom + 1, dialog.height()):
                    self.assertEqual(
                        image.pixelColor(dialog.close_button.geometry().center().x(), y),
                        QColor("#f5f8fb"),
                    )
                geometry = (dialog.size(), dialog.close_button.geometry())
                if expected_geometry is None:
                    expected_geometry = geometry
                self.assertEqual(geometry, expected_geometry)
                dialog.close()

    def test_two_columns_full_width_notices_and_content_height_on_reopen(self) -> None:
        dialog = self.show_topic()
        button_rects = []
        for button, hint_name in (
            (dialog.create_button, "supportReportCreateHint"),
            (dialog.open_folder_button, "supportReportReviewHint"),
            (dialog.issue_button, "supportReportIssueHint"),
        ):
            hint = dialog.findChild(QLabel, hint_name)
            self.assertLess(hint.geometry().right(), button.geometry().left())
            button_rects.append(button.geometry())
        self.assertEqual(len({rect.left() for rect in button_rects}), 1)
        self.assertEqual(len({rect.right() for rect in button_rects}), 1)
        account = dialog.findChild(QLabel, "supportReportAccountHint")
        self.assertLess(account.geometry().left(), button_rects[0].left())
        self.assertGreaterEqual(account.geometry().right(), button_rects[0].right())
        summary = dialog.findChild(QLabel, "supportReportPrivacySummary")
        self.assertTrue(summary.isVisible())
        self.assertLess(dialog.privacy_info.geometry().right(), button_rects[0].left())

        initial_height = dialog.height()
        dialog.create_button.click()
        dialog.close()
        self.window.support_report_action.trigger()
        QTest.qWait(80)
        self.assertEqual(dialog.pages.currentIndex(), 0)
        dialog = self.show_topic()
        height_limit = dialog.screen().availableGeometry().height() - 60
        self.assertGreaterEqual(dialog.height(), initial_height)
        if initial_height < height_limit:
            self.assertGreater(dialog.height(), initial_height)
        if dialog.height() < height_limit:
            self.assertFalse(dialog.scroll.verticalScrollBar().isVisible())
            self.assertLessEqual(account.geometry().bottom(), dialog.content.height())

    def test_menu_creates_bundle_without_inputs_then_opens_folder_and_github(self) -> None:
        with patch.object(self.window.support_report_dialog, "_open_directory") as open_mock, patch(
            "cooling_tower.gui.support_report_dialog.QDesktopServices.openUrl"
        ) as open_url:
            dialog = self.show_topic()
            self.assertFalse(dialog.findChildren(QLineEdit))
            self.assertFalse(dialog.findChildren(QTextEdit))
            self.assertFalse(dialog.open_folder_button.isEnabled())
            self.assertTrue(dialog.issue_button.isEnabled())
            self.assertEqual(dialog.issue_button.text(), "Fehler auf GitHub melden")
            create_hint = dialog.findChild(QLabel, "supportReportCreateHint").text()
            self.assertIn("Optional", create_hint)
            self.assertIn("hilfreich bei der Fehlersuche", create_hint)
            self.assertIn("bleibt lokal", create_hint)
            privacy = dialog.privacy_info.accessibleDescription()
            self.assertIn("sind öffentlich", privacy)
            self.assertIn("Rohlogs", privacy)
            self.assertNotIn("unverändert im Klartext", privacy)
            self.assertFalse(dialog.issue_button.icon().isNull())
            self.assertIn("ZIP bei Bedarf anhängen", dialog.issue_hint.text())
            self.assertIn("Meldung absenden", dialog.issue_hint.text())
            self.assertIn("öffentlich", dialog.bug_content.findChild(QLabel, "supportReportAccountHint").text())
            self.assertFalse(dialog.result_label.isVisible())
            initial_size = dialog.size()
            space_below = dialog.screen().availableGeometry().bottom() - dialog.frameGeometry().bottom() - 20
            dialog.create_button.click()
            QTest.qWait(80)
            self.assertTrue(dialog.last_bundle_path.is_file())
            self.assertTrue(dialog.open_folder_button.isEnabled())
            self.assertEqual(dialog.width(), initial_size.width())
            self.assertGreaterEqual(dialog.height(), initial_size.height())
            if space_below > 0:
                self.assertGreater(dialog.height(), initial_size.height())
            if dialog.frameGeometry().bottom() < dialog.screen().availableGeometry().bottom() - 20:
                self.assertFalse(dialog.scroll.verticalScrollBar().isVisible())
            self.assertIn("noch nicht gesendet", dialog.result_label.text())
            self.assertIn("Schritt 2", dialog.result_label.text())
            review_hint = dialog.findChild(QLabel, "supportReportReviewHint").text()
            self.assertIn("ZIP aus Schritt 1", review_hint)
            self.assertIn("alle Dateien", review_hint)
            self.assertIn("Entpacken ist nur bei Bedarf nötig", privacy)
            document = QTextDocument()
            document.setHtml(dialog.result_label.text())
            filename = document.find(dialog.last_bundle_path.name)
            self.assertFalse(filename.isNull())
            self.assertGreaterEqual(filename.charFormat().fontWeight(), QFont.Weight.Bold)
            with zipfile.ZipFile(dialog.last_bundle_path) as archive:
                self.assertNotIn("problembericht.txt", archive.namelist())
                self.assertIn("hinweise.txt", archive.namelist())
            open_url.assert_not_called()
            open_mock.assert_not_called()
            dialog.open_folder_button.click()
            open_mock.assert_called_once_with((self.root / "output/support_reports").resolve())
            dialog.issue_button.click()
            open_url.assert_called_once()
            self.assertTrue(open_url.call_args.args[0].path().endswith("/issues/new"))
            self.assertEqual(QUrlQuery(open_url.call_args.args[0]).queryItemValue("template"), "01-bug.yml")

    def test_privacy_details_are_accessible_and_do_not_replace_visible_warnings(self) -> None:
        dialog = self.show_topic()
        self.assertIn("Nicht garantiert anonym", dialog.findChild(QLabel, "supportReportPrivacySummary").text())
        self.assertIn("öffentlich", dialog.bug_content.findChild(QLabel, "supportReportAccountHint").text())
        self.assertIn("persönliche Daten", dialog.findChild(QLabel, "supportReportReviewHint").text())
        initial_size = dialog.size()
        dialog.privacy_info.setFocus()
        QTest.keyClick(dialog.privacy_info, Qt.Key.Key_Space)
        self.app.processEvents()
        popover = dialog._bounded_hint_popover
        self.assertTrue(popover.isVisible())
        self.assertEqual(popover.label.text(), dialog.privacy_info.accessibleDescription())
        self.assertTrue(dialog.rect().contains(popover.geometry()))
        self.assertEqual(dialog.size(), initial_size)
        dialog.back_button.click()
        self.assertFalse(popover.isVisible())
        self.wait_for_page(dialog, 0)
        self.show_topic()
        dialog.privacy_info.click()
        self.assertTrue(popover.isVisible())
        dialog.close()
        self.assertFalse(popover.isVisible())

    def test_content_scrolls_in_small_window_and_fits_again_when_enlarged(self) -> None:
        dialog = self.show_topic()
        dialog.resize(620, 360)
        QTest.qWait(80)
        self.assertTrue(dialog.scroll.verticalScrollBar().isVisible())
        self.assertFalse(dialog.scroll.horizontalScrollBar().isVisible())
        dialog.create_button.click()
        QTest.qWait(80)
        self.assertEqual(dialog.width(), 620)
        self.assertGreater(dialog.height(), 360)
        dialog.resize(620, 360)
        QTest.qWait(80)
        self.assertTrue(dialog.scroll.verticalScrollBar().isVisible())
        self.assertTrue(dialog.close_button.isVisible())
        dialog.resize(900, 1000)
        QTest.qWait(80)
        self.assertFalse(dialog.scroll.verticalScrollBar().isVisible())
        self.assertFalse(dialog.scroll.horizontalScrollBar().isVisible())
        for label in dialog.content.findChildren(QLabel):
            if label.isVisible() and label.wordWrap():
                self.assertGreaterEqual(label.height(), label.heightForWidth(label.width()), label.objectName())

    def test_creation_failure_keeps_retry_and_previous_bundle_available(self) -> None:
        dialog = self.show_topic()
        with patch.object(dialog.service, "create_bundle", side_effect=OSError("full")):
            dialog.create_button.click()
        self.assertIsNone(dialog.last_bundle_path)
        self.assertIn("konnte nicht erstellt werden", dialog.result_label.text())
        self.assertTrue(dialog.create_button.isEnabled())
        self.assertFalse(dialog.open_folder_button.isEnabled())
        dialog.create_button.click()
        previous_path = dialog.last_bundle_path
        self.assertTrue(previous_path.is_file())
        with patch.object(dialog.service, "create_bundle", side_effect=OSError("full")):
            dialog.create_button.click()
        self.assertEqual(dialog.last_bundle_path, previous_path)
        self.assertTrue(previous_path.is_file())
        self.assertTrue(dialog.open_folder_button.isEnabled())
        self.assertTrue(dialog.create_button.isEnabled())

    def test_bundle_filename_is_escaped_and_failure_is_displayed_as_plain_text(self) -> None:
        dialog = self.show_topic()
        filename = "Diagnose <privat> & geprüft.zip"
        with patch.object(dialog.service, "create_bundle", return_value=SimpleNamespace(path=self.root / filename)):
            dialog.create_button.click()
        document = QTextDocument()
        document.setHtml(dialog.result_label.text())
        self.assertIn(filename, document.toPlainText())
        self.assertIn("&lt;privat&gt; &amp;", dialog.result_label.text())
        with patch.object(dialog.service, "create_bundle", side_effect=OSError("Fehler <b>unverändert</b>")):
            dialog.create_button.click()
        self.assertEqual(dialog.result_label.textFormat(), Qt.TextFormat.PlainText)
        self.assertIn("<b>unverändert</b>", dialog.result_label.text())

    def test_tallest_page_sets_initial_top_and_all_content_changes_keep_it_fixed(self) -> None:
        self.window.support_report_action.trigger()
        QTest.qWait(80)
        dialog = self.window.support_report_dialog
        initial_frame = dialog.frameGeometry()
        initial_size = dialog.size()
        dialog = self.show_topic()
        self.assertEqual(dialog.frameGeometry().topLeft(), initial_frame.topLeft())
        self.assertGreater(dialog.height(), initial_size.height())
        # The initial compact selection starts where the tallest page is centred.
        available = dialog.screen().availableGeometry()
        if (dialog.frameGeometry().top() > available.top() + 20
                and dialog.frameGeometry().bottom() < available.bottom() - 20):
            self.assertAlmostEqual(
                dialog.frameGeometry().center().y(), self.window.frameGeometry().center().y(), delta=2,
            )
        for topic in ("question", "feature", "review", "contact", "bug"):
            dialog = self.show_topic(topic)
            self.assertEqual(dialog.frameGeometry().topLeft(), initial_frame.topLeft())
            self.assertEqual(dialog.width(), initial_size.width())
        dialog.create_button.click()
        QTest.qWait(60)
        self.assertEqual(dialog.frameGeometry().topLeft(), initial_frame.topLeft())
        dialog.move(dialog.frameGeometry().topLeft() + QPoint(12, 10))
        dialog.resize(760, dialog.height())
        moved_position = dialog.frameGeometry().topLeft()
        self.window._resize_support_report_dialog()
        self.assertEqual(dialog.frameGeometry().topLeft(), moved_position)
        self.assertEqual(dialog.width(), 760)
        with patch.object(dialog.service, "create_bundle", side_effect=OSError("Fehler " * 80)):
            dialog.create_button.click()
        self.assertEqual(dialog.frameGeometry().topLeft(), moved_position)
        self.assertEqual(dialog.width(), 760)

    def test_small_screen_keeps_top_fixed_and_scrolls_only_when_needed(self) -> None:
        available = QRect(0, 0, 900, 460)
        screen = SimpleNamespace(availableGeometry=lambda: available)
        dialog = self.window.support_report_dialog
        with patch.object(self.window, "screen", return_value=screen), patch.object(dialog, "screen", return_value=screen):
            self.window.support_report_action.trigger()
            QTest.qWait(80)
            position = dialog.frameGeometry().topLeft()
            self.assertFalse(dialog.scroll.verticalScrollBar().isVisible())
            self.show_topic()
            QTest.qWait(60)
            self.assertEqual(dialog.frameGeometry().topLeft(), position)
            self.assertLessEqual(dialog.frameGeometry().bottom(), available.bottom())
            self.assertTrue(dialog.scroll.verticalScrollBar().isVisible())
            self.show_topic("review")
            self.assertEqual(dialog.frameGeometry().topLeft(), position)
            self.assertFalse(dialog.scroll.verticalScrollBar().isVisible())
