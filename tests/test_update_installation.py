from __future__ import annotations

import hashlib
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cooling_tower.diagnostics import DiagnosticJournal
from cooling_tower.update import UpdateError, UpdateInfo, UpdateService
from cooling_tower.update_installation import (
    UpdateInstallationAttempt, installer_command, recover_update_outcomes,
)


class FakeSignals:
    def __init__(self, _attempt_id, ready=True):
        self.is_ready = ready
        self.signalled = []
        self.closed = False

    def ready(self):
        return self.is_ready

    def signal(self, kind):
        self.signalled.append(kind)

    def close(self):
        self.closed = True


class FakeProcess:
    pid = 1234
    returncode = None

    def poll(self):
        return self.returncode


class UpdateInstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.installer = self.root / "SacrificialTowerSetup-9.9.9.exe"
        self.installer.write_bytes(b"verified installer")
        self.info = UpdateInfo("9.9.9", "https://example.invalid", hashlib.sha256(self.installer.read_bytes()).hexdigest(), self.installer.stat().st_size)
        self.journal = DiagnosticJournal(self.root / "journal.jsonl")
        self.signals = FakeSignals("")
        self.process = FakeProcess()
        self.attempts = []

    def tearDown(self):
        for attempt in self.attempts:
            attempt.cancel()
            attempt._thread.join(2)
        self.temp.cleanup()

    def attempt(self, **kwargs):
        attempt = UpdateInstallationAttempt(
            self.installer, self.info, self.root / "logs", journal=self.journal,
            signals_factory=lambda _: self.signals, popen=kwargs.pop("popen", lambda *a, **k: self.process),
            **kwargs)
        attempt.log_root.mkdir(parents=True, exist_ok=True)
        attempt.status_path.write_text(f"protocol=1\nattempt={attempt.attempt_id}\nversion=9.9.9\nstage=ready\n")
        self.attempts.append(attempt)
        return attempt.start()

    def wait_state(self, attempt, state):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            current, _ = attempt.poll()
            if current == state:
                return
            time.sleep(0.01)
        self.fail(f"Expected {state}, got {attempt.poll()}")

    def test_launch_waits_for_setup_ack_and_requires_explicit_commit(self):
        self.signals.is_ready = False
        attempt = self.attempt()
        time.sleep(0.1)
        self.assertEqual(attempt.poll()[0], "starting")
        with self.assertRaises(UpdateError):
            attempt.commit()
        self.assertNotIn("commit", self.signals.signalled)
        self.signals.is_ready = True
        self.wait_state(attempt, "ready")
        attempt.commit()
        attempt._thread.join(2)
        self.assertEqual(attempt.state, "committed")
        self.assertEqual(self.signals.signalled, ["commit"])
        self.assertTrue(self.signals.closed)

    def test_changed_installer_is_never_executed(self):
        self.installer.write_bytes(b"tampered")
        with patch("cooling_tower.update_installation.subprocess.Popen") as launch:
            attempt = self.attempt(popen=launch)
            self.wait_state(attempt, "failed")
            launch.assert_not_called()
        self.assertIn("update_installer_integrity_failed", self.journal.log_path.read_text())

    def test_early_exit_including_unknown_code_is_logged(self):
        self.process.returncode = 0xC0000005
        attempt = self.attempt()
        self.wait_state(attempt, "failed")
        log = self.journal.log_path.read_text()
        self.assertIn("update_installer_exited_early", log)
        self.assertIn(str(0xC0000005), log)
        self.assertNotIn("commit", self.signals.signalled)

    def test_access_denied_logs_native_error_without_committing(self):
        def denied(*args, **kwargs):
            error = PermissionError("local-only path")
            error.winerror = 5
            raise error
        attempt = self.attempt(popen=denied)
        self.wait_state(attempt, "failed")
        log = self.journal.log_path.read_text()
        self.assertIn('"winerror": 5', log)
        self.assertIn("update_installer_launch_failed", log)

    def test_suspended_process_creation_can_time_out_without_blocking_caller(self):
        entered, release = threading.Event(), threading.Event()
        def suspended(*args, **kwargs):
            entered.set()
            release.wait(3)
            return self.process
        attempt = self.attempt(popen=suspended)
        try:
            self.assertTrue(entered.wait(2))
            attempt.started -= 100
            started = time.monotonic()
            self.assertEqual(attempt.poll()[0], "failed")
            self.assertLess(time.monotonic() - started, 0.25)
            self.assertIn("cancel", self.signals.signalled)
            with self.assertRaises(UpdateError):
                attempt.commit()
        finally:
            release.set()
            attempt._thread.join(2)
        self.assertNotIn("commit", self.signals.signalled)

    def test_cancel_after_ready_prevents_later_commit(self):
        attempt = self.attempt()
        self.wait_state(attempt, "ready")
        attempt.cancel()
        with self.assertRaises(UpdateError):
            attempt.commit()
        self.assertIn("cancel", self.signals.signalled)

    def test_event_without_visible_matching_status_is_not_a_valid_handoff(self):
        self.signals.is_ready = False
        attempt = self.attempt()
        attempt.status_path.unlink()
        self.signals.is_ready = True
        self.wait_state(attempt, "failed")
        self.assertIn("update_installer_ack_inconsistent", self.journal.log_path.read_text())
        self.assertNotIn("commit", self.signals.signalled)

    def test_command_uses_persistent_log_and_never_forces_applications_closed(self):
        command = installer_command(self.installer, "a" * 32, self.root / "setup.log", self.root / "setup.status")
        self.assertIn("/NOCLOSEAPPLICATIONS", command)
        self.assertIn("/NORESTARTAPPLICATIONS", command)
        self.assertNotIn("/CLOSEAPPLICATIONS", command)
        self.assertNotIn("/FORCECLOSEAPPLICATIONS", command)
        self.assertIn(f"/LOG={self.root / 'setup.log'}", command)

    def test_service_rejects_installer_outside_own_download(self):
        with self.assertRaisesRegex(UpdateError, "Downloadordner"):
            UpdateService(temporary_root=self.root).start_installation(self.installer, self.info, self.root / "logs")

    def test_service_never_launches_an_installer_without_handoff_support(self):
        old_info = UpdateInfo("0.8.13", "", self.info.sha256, self.info.size_bytes)
        with patch("cooling_tower.update_installation.UpdateInstallationAttempt.start") as start:
            with self.assertRaisesRegex(UpdateError, "sichere Updateübergabe"):
                UpdateService(temporary_root=self.root).start_installation(self.installer, old_info, self.root / "logs")
        start.assert_not_called()

    def test_download_worker_logs_failures_before_the_download_loop(self):
        from cooling_tower.gui.update_worker import UpdateDownloadWorker
        from unittest.mock import Mock
        error = PermissionError("local-only filesystem details")
        error.winerror = 225
        service = Mock()
        service.download_installer.side_effect = error
        worker = UpdateDownloadWorker(1, self.info, service)
        events = []
        worker.set_diagnostic_callback(lambda event, **fields: events.append((event, fields)))
        worker.run()
        failure = next(fields for event, fields in events if event == "update_download_failed")
        self.assertEqual(failure["winerror"], 225)
        self.assertEqual(failure["error_type"], "PermissionError")
        self.assertIn("PermissionError", failure["traceback"])

    def test_recovery_retains_only_known_fixed_stages(self):
        folder = self.root / "updates"
        folder.mkdir()
        (folder / "update-test.status").write_text("protocol=1\nversion=9.9.9\nstage=ready\nstage=private user content\nstage=setup_failed\n")
        self.assertEqual(recover_update_outcomes(folder, self.journal, "9.9.8"), ["setup_failed"])
        log = self.journal.log_path.read_text()
        self.assertIn("update_previous_outcome", log)
        self.assertNotIn("private user content", log)


if __name__ == "__main__":
    unittest.main()
