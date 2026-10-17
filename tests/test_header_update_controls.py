from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("COOLING_TOWER_DISABLE_SLICER_DISCOVERY", "1")

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QDialog

from cooling_tower.gui.background_jobs import JobKind
from cooling_tower.gui.main_window import MainWindow
from cooling_tower.update import UpdateInfo
from gui_lifecycle import dispose_test_widget


class HeaderUpdateControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        cls.font_ids = []
        for name in ("segoeui.ttf", "seguisym.ttf"):
            font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
            if font.is_file():
                cls.font_ids.append(QFontDatabase.addApplicationFont(str(font)))

    @classmethod
    def tearDownClass(cls) -> None:
        for font_id in cls.font_ids:
            if font_id >= 0:
                QFontDatabase.removeApplicationFont(font_id)

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.window = MainWindow(
            user_settings_path=Path(self.temporary.name) / "settings.json",
            enable_update_check=False, enable_startup_slicer_discovery=False,
        )
        self.window.show()
        self.settle()

    def tearDown(self) -> None:
        dispose_test_widget(self.window)
        self.app.processEvents()
        self.temporary.cleanup()

    def settle(self) -> None:
        for _ in range(5):
            self.app.processEvents()

    def rect(self, widget) -> QRect:
        return QRect(widget.mapTo(self.window.workflow_header, QPoint()), widget.size())

    def offer_update(self) -> None:
        self.window._update_check_request_id = 7
        self.window._on_update_check_succeeded(7, UpdateInfo(
            version="0.9.99", installer_url="https://example.invalid/installer.exe",
            sha256="0" * 64, size_bytes=123,
        ))
        self.settle()

    def start_download(self) -> None:
        with patch.object(self.window.background_job_manager, "start_job") as start:
            self.window.update_button.click()
        self.assertEqual(start.call_args.kwargs["kind"], JobKind.UPDATE_DOWNLOAD)
        self.settle()

    def prepare_methods(self) -> None:
        workflow = self.window.workflow
        workflow.set_slicer_step_visible(True)
        workflow.source_validation_succeeded("modell.stl", analysis_complete=True)
        workflow.slicer_succeeded("Testslicer")
        workflow.complete_preparation()
        self.window.automatic_generation_card.click()
        self.window.workflow_header.set_facts((
            ("Dateiname", "modell.stl"), ("Slicer", "Testslicer"),
            ("Maschinenprofil", "Maschine"), ("Filamentprofil", "Filament"),
            ("Prozessprofil", "Prozess"),
        ))
        self.settle()

    def assert_update_alignment(self) -> None:
        window = self.window
        blue = self.rect(window.update_button)
        strip = self.rect(window.header_update_controls)
        for widget in (window.options_button, window.version_label):
            self.assertLessEqual(abs(self.rect(widget).center().x() - strip.center().x()), 1)
        self.assertLess(self.rect(window.version_label).bottom(), blue.top())
        self.assertEqual(self.rect(window.header_update_controls).right(), window.workflow_header.width() - 1)
        if window.workflow_header.separator.isVisible():
            self.assertEqual(blue.bottom(), window.workflow_header.separator.y())
        if window.workflow_header.facts:
            self.assertTrue(window.preparation_open_button.status_label.isHidden())
            self.assertEqual(self.rect(window.preparation_open_button).bottom(),window.workflow_header.separator.y())
        if window.header_method_selection.isVisible():
            self.assertEqual(self.rect(window.header_method_selection).bottom(),window.workflow_header.separator.y())
        if not window.update_cancel_button.isHidden():
            self.assertEqual(self.rect(window.update_cancel_button).bottom(),window.workflow_header.separator.y())

    def test_confirmed_facts_have_extra_vertical_space_and_grow_the_shared_header(self) -> None:
        self.prepare_methods()
        w=self.window
        for width in (1450,720,1450):
            with self.subTest(width=width):
                w.resize(width,1000);self.settle()
                button=w.preparation_open_button
                self.assertTrue(button.status_label.isHidden())
                self.assertEqual(button.status_label.text(),"")
                self.assertEqual(button.content_layout.contentsMargins().top(),7)
                self.assertEqual(button.content_layout.contentsMargins().bottom(),8)
                self.assertEqual(button.content_layout.contentsMargins().left(),7)
                self.assertEqual(button.content_layout.contentsMargins().right(),7)
                rows=[QRect(label.mapTo(button,QPoint()),label.size()) for label in w.workflow_header.fact_labels.values()]
                self.assertGreaterEqual(min(row.top() for row in rows),7)
                self.assertGreaterEqual(button.height()-max(row.bottom() for row in rows)-1,8)
                self.assertEqual(button.height(),w.workflow_header.height())
                self.assertEqual(self.rect(w.header_method_selection).bottom(),w.workflow_header.separator.y())
                for widget in (w.options_button,w.version_label):
                    self.assertTrue(w.workflow_header.rect().contains(self.rect(widget)))

    def test_header_without_confirmed_facts_keeps_its_previous_spacing_and_restores_it(self) -> None:
        w=self.window
        header=w.workflow_header
        self.assertEqual(header.preparation_button.content_layout.contentsMargins().top(),3)
        self.assertEqual(header.preparation_button.content_layout.contentsMargins().bottom(),4)
        baseline=(header.height(),self.rect(w.title_label),self.rect(w.subtitle_label),
                  self.rect(w.options_button),self.rect(w.version_label))
        header.set_facts((("Dateiname","modell.stl"),("Slicer","Testslicer"),
                          ("Maschinenprofil","Maschine"),("Filamentprofil","Filament"),
                          ("Prozessprofil","Prozess")))
        self.settle()
        header.set_facts(())
        self.settle()
        self.assertTrue(header.preparation_button.isHidden())
        self.assertEqual(header.preparation_button.content_layout.contentsMargins().top(),3)
        self.assertEqual(header.preparation_button.content_layout.contentsMargins().bottom(),4)
        self.assertEqual((header.height(),self.rect(w.title_label),self.rect(w.subtitle_label),
                          self.rect(w.options_button),self.rect(w.version_label)),baseline)

    def test_offer_and_download_are_edge_attached_and_restore_original_layout(self) -> None:
        for methods in (False, True):
            if methods:
                self.prepare_methods()
            for width in (1450, 720):
                with self.subTest(methods=methods, width=width):
                    self.window.resize(width, 1000)
                    self.settle()
                    baseline = tuple(self.rect(w) for w in (
                        self.window.options_button, self.window.version_label,
                    ))
                    baseline_height = self.window.workflow_header.height()
                    self.offer_update()
                    self.assert_update_alignment()
                    self.assertEqual(self.window.update_button.text(), "Aktualisieren")
                    for widget, previous in zip((self.window.options_button, self.window.version_label), baseline):
                        self.assertGreaterEqual(self.rect(widget).top(), previous.top())
                    self.assertLessEqual(self.window.workflow_header.height() - baseline_height, 30)
                    offered_width = self.window.header_update_controls.width()
                    offered_height = self.window.workflow_header.height()
                    offered_method = self.rect(self.window.header_method_selection)
                    offered_menu_version = tuple(self.rect(w) for w in (
                        self.window.options_button, self.window.version_label,
                    ))
                    blue_color = self.window.update_button.grab().toImage().pixelColor(3, 3)
                    self.start_download()
                    for percent in (0, 57, 100):
                        self.window._on_update_download_progress(self.window._update_download_request_id, percent)
                        self.settle()
                        self.assertEqual(self.window.update_button.text(), f"Lädt... {percent}%")
                        self.assert_update_alignment()
                        self.assertEqual(tuple(self.rect(w) for w in (
                            self.window.options_button, self.window.version_label,
                        )), offered_menu_version)
                        blue = self.rect(self.window.update_button)
                        cancel = self.rect(self.window.update_cancel_button)
                        self.assertEqual(blue.right() + 1, cancel.left())
                        self.assertEqual(blue.top(), cancel.top())
                        self.assertEqual(cancel.width(), cancel.height())
                        self.assertFalse(self.window.update_cancel_button.icon().isNull())
                        self.assertEqual(self.window.header_update_controls.width(), offered_width)
                        self.assertEqual(self.window.workflow_header.height(), offered_height)
                        if methods:
                            self.assertEqual(self.rect(self.window.header_method_selection), offered_method)
                            self.assertEqual(offered_method.right() + 1, blue.left())
                        self.assertEqual(self.window.update_button.grab().toImage().pixelColor(3, 3), blue_color)
                    self.window._update_download_cancel_requested = True
                    self.window._on_update_download_finished(self.window._update_download_request_id)
                    self.settle()
                    self.assertEqual(self.window.update_button.text(), "Aktualisieren")
                    self.assertTrue(self.window.update_cancel_button.isHidden())
                    self.assertTrue(self.window.update_button.isEnabled())
                    self.assert_update_alignment()
                    self.window._on_update_check_succeeded(7, None)
                    self.settle()
                    self.assertTrue(self.window.header_update_controls.isHidden())
                    self.assertEqual(self.window.workflow_header.height(), baseline_height)
                    self.assertEqual(tuple(self.rect(w) for w in (
                        self.window.options_button, self.window.version_label,
                    )), baseline)

    def test_cancel_requests_worker_cancellation_and_ignores_late_progress(self) -> None:
        self.offer_update()
        self.start_download()
        with (
            patch.object(self.window.background_job_manager, "has_active", return_value=True),
            patch.object(self.window.background_job_manager, "cancel_jobs") as cancel,
        ):
            self.window.update_cancel_button.click()
        cancel.assert_called_once_with(JobKind.UPDATE_DOWNLOAD, reason="user_request")
        self.assertFalse(self.window.update_cancel_button.isEnabled())
        text = self.window.update_button.text()
        self.window._on_update_download_progress(self.window._update_download_request_id, 80)
        self.assertEqual(self.window.update_button.text(), text)
        self.window._on_update_download_finished(self.window._update_download_request_id)
        self.settle()
        self.assertEqual(self.window.update_button.text(), "Aktualisieren")
        self.assertTrue(self.window.update_cancel_button.isHidden())

    def test_failed_check_restores_layout_and_stale_check_does_not_hide_update(self) -> None:
        baseline = self.rect(self.window.options_button)
        self.offer_update()
        self.window._on_update_check_failed(6, "offline", "")
        self.assertFalse(self.window.update_button.isHidden())
        self.window._on_update_check_failed(7, "offline", "")
        self.settle()
        self.assertTrue(self.window.header_update_controls.isHidden())
        self.assertEqual(self.rect(self.window.options_button), baseline)

    def begin_installation(self, state="starting"):
        self.offer_update()
        attempt = Mock()
        attempt.poll.return_value = (state, "test error")
        attempt.log_path = Path(self.temporary.name) / "setup.log"
        with (
            patch("cooling_tower.gui.main_window.UpdateRestartCountdownDialog.exec_countdown",
                  return_value=QDialog.DialogCode.Accepted),
            patch.object(self.window.update_service, "start_installation", return_value=attempt) as start,
        ):
            self.window._on_update_download_succeeded(0, Path(self.temporary.name) / "setup.exe")
        start.assert_called_once()
        return attempt

    def test_restart_click_starts_async_handoff_and_leaves_ui_responsive(self):
        from PySide6.QtCore import QTimer
        from PySide6.QtTest import QTest
        attempt = self.begin_installation()
        ticks = []
        timer = QTimer(self.window)
        timer.timeout.connect(lambda: ticks.append(1))
        timer.start(10)
        QTest.qWait(150)
        self.assertGreater(len(ticks), 1)
        self.assertTrue(self.window.isVisible())
        self.assertTrue(self.window._update_install_dialog.isVisible())
        attempt.commit.assert_not_called()
        self.window._cancel_update_installation()
        attempt.cancel.assert_called_once()
        self.assertIsNone(self.window._update_install_dialog)
        self.assertFalse(self.window._closing)

    def test_early_setup_failure_keeps_program_open_and_displays_log_location(self):
        self.begin_installation("failed")
        with patch.object(self.window, "_show_update_error") as error:
            self.window._poll_update_installation()
        self.assertIn("setup.log", error.call_args.args[0])
        self.assertTrue(self.window.isVisible())
        self.assertTrue(self.window.update_button.isEnabled())
        self.assertIsNone(self.window._update_install_attempt)

    def test_failed_settings_save_does_not_authorize_installer(self):
        import time
        attempt = self.begin_installation("ready")
        self.window._update_install_timer.stop()
        self.window._update_shutdown_started = time.monotonic()
        with (
            patch.object(self.window.settings_store, "save", side_effect=OSError("write failed")),
            patch.object(self.window, "_show_update_error") as error,
        ):
            self.assertFalse(self.window.close())
        attempt.commit.assert_not_called()
        attempt.cancel.assert_called_once()
        self.assertTrue(self.window.isVisible())
        self.assertFalse(self.window._closing)
        error.assert_called_once()

    def test_ready_installer_commits_only_after_settings_and_jobs_are_safe(self):
        import time
        attempt = self.begin_installation("ready")
        self.window._update_install_timer.stop()
        self.window._update_shutdown_started = time.monotonic()
        with patch.object(self.window, "_save_user_settings", wraps=self.window._save_user_settings) as save:
            self.assertTrue(self.window.close())
        save.assert_called_once_with(strict=True)
        attempt.commit.assert_called_once()
        attempt.cancel.assert_not_called()
        self.assertFalse(self.window.isVisible())

    def test_cancel_invalidates_already_queued_close(self):
        attempt = self.begin_installation("ready")
        self.window._poll_update_installation()
        self.window._cancel_update_installation()
        self.settle()
        self.assertTrue(self.window.isVisible())
        attempt.commit.assert_not_called()

    def test_setup_failure_at_commit_keeps_window_and_hint_controller_usable(self):
        import time
        attempt = self.begin_installation("ready")
        attempt.commit.side_effect = RuntimeError("setup exited")
        self.window._update_install_timer.stop()
        self.window._update_shutdown_started = time.monotonic()
        with (
            patch.object(self.window._hint_controller, "dispose") as dispose,
            patch.object(self.window, "_show_update_error") as error,
        ):
            self.assertFalse(self.window.close())
            dispose.assert_not_called()
        attempt.cancel.assert_called_once()
        self.assertTrue(self.window.isVisible())
        self.assertFalse(self.window._closing)
        error.assert_called_once()

    def test_busy_jobs_are_cancelled_without_blocking_gui_and_timeout_aborts_update(self):
        attempt = self.begin_installation("ready")
        self.window._update_install_timer.stop()
        job = Mock(job_id="test-job")
        with (
            patch.object(self.window.background_job_manager, "active_jobs", return_value=[job]),
            patch.object(self.window.background_job_manager, "cancel_job") as cancel,
            patch.object(self.window, "_show_update_error") as error,
        ):
            self.window._poll_update_installation()
            cancel.assert_called_once_with("test-job", reason="application_shutdown")
            self.window._update_shutdown_started -= 60
            self.window._poll_update_installation()
        attempt.cancel.assert_called_once()
        attempt.commit.assert_not_called()
        self.assertTrue(self.window.isVisible())
        error.assert_called_once()

    def test_update_from_confirmed_file_and_profiles_in_creation_overview(self):
        workflow = self.window.workflow
        workflow.set_slicer_step_visible(True)
        workflow.source_validation_succeeded("modell.stl", analysis_complete=True)
        workflow.slicer_succeeded("Testslicer")
        self.assertTrue(workflow.complete_preparation())
        self.settle()
        self.assertTrue(self.window.automatic_generation_card.isVisible())
        attempt = self.begin_installation("ready")
        with patch.object(self.window, "close", wraps=self.window.close) as close:
            self.window._poll_update_installation()
            self.settle()
        close.assert_called_once()
        attempt.commit.assert_called_once()
        attempt.cancel.assert_not_called()
        self.assertFalse(self.window.isVisible())

    def test_real_background_worker_is_released_before_install_commit(self):
        import threading
        import time
        from PySide6.QtCore import Signal, Slot
        from PySide6.QtTest import QTest
        from cooling_tower.gui.worker_contract import CancelableWorker

        entered = threading.Event()
        class WaitingWorker(CancelableWorker):
            finished = Signal(int)
            @Slot()
            def run(self):
                entered.set()
                self.cancellation_event.wait(5)
                self.finished.emit(99)

        worker = WaitingWorker()
        self.window.background_job_manager.start_job(kind=JobKind.PROFILE_MATCH, worker=worker, request_id=99)
        deadline = time.monotonic() + 3
        while not entered.is_set() and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertTrue(entered.is_set())
        attempt = self.begin_installation("ready")
        active_at_commit = []
        attempt.commit.side_effect = lambda: active_at_commit.append(self.window.background_job_manager.active_jobs())
        self.window._poll_update_installation()
        deadline = time.monotonic() + 3
        while self.window.isVisible() and time.monotonic() < deadline:
            QTest.qWait(20)
        self.assertTrue(worker.cancellation_event.is_set())
        self.assertEqual(len(active_at_commit), 1)
        self.assertFalse(active_at_commit[0])
        self.assertFalse(self.window.isVisible())


if __name__ == "__main__":
    unittest.main()
