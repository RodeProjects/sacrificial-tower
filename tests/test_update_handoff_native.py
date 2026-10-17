"""Exercise the real Inno gate without installing files or touching the real app."""
from __future__ import annotations

import os
import hashlib
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cooling_tower.update import UpdateInfo
from cooling_tower.update_installation import WindowsUpdateSignals, UpdateInstallationAttempt, installer_command


@unittest.skipUnless(os.name == "nt", "Windows-only Inno handoff")
class NativeUpdateHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        candidates = [ROOT / "build/tools/InnoSetup/ISCC.exe", ROOT / "build/inno-portable/compiler/ISCC.exe"]
        if os.environ.get("INNO_ROOT"):
            candidates.insert(0, Path(os.environ["INNO_ROOT"]) / "ISCC.exe")
        compiler = next((path for path in candidates if path.is_file()), None)
        if compiler is None:
            raise unittest.SkipTest("Pinned Inno Setup compiler unavailable")
        parent = ROOT / "build" / "update-handoff-tests"
        parent.mkdir(parents=True, exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(dir=parent)
        cls.work = Path(cls.temp.name)
        result = subprocess.run([str(compiler), "/Q", f"/O{cls.work}", str(ROOT / "tests/fixtures/update_handoff.iss")],
                                capture_output=True, text=True, timeout=60)
        if result.returncode:
            cls.temp.cleanup()
            raise AssertionError(result.stdout + result.stderr)
        cls.installer = cls.work / "handoff-test.exe"

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_00_first_start_requires_a_visible_ack_even_during_security_scanning(self):
        """A scanner may first execute a fresh PE in a virtual filesystem.

        Exercise the production controller on that first launch as well. A
        virtual-only acknowledgement must be rejected, never mistaken for a
        completed launch. No scanner configuration or exclusions are changed.
        """
        install_root = self.work / "first-start"
        install_root.mkdir()
        payload = install_root / "update_payload.txt"
        payload.write_text("old application payload")
        parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(90)"],
                                  creationflags=subprocess.CREATE_NO_WINDOW)
        processes = []
        def launch(command, **kwargs):
            command = [f"/STUPDATEPARENT={parent.pid}" if item.startswith("/STUPDATEPARENT=") else item for item in command]
            process = subprocess.Popen([*command, f"/DIR={install_root}"], **kwargs)
            processes.append(process)
            return process
        info = UpdateInfo("9.9.9", "", hashlib.sha256(self.installer.read_bytes()).hexdigest(), self.installer.stat().st_size)
        attempt = UpdateInstallationAttempt(self.installer, info, self.work, popen=launch).start()
        try:
            deadline = time.monotonic() + 45
            while attempt.poll()[0] == "starting" and time.monotonic() < deadline:
                time.sleep(0.05)
            state, message = attempt.poll()
            if state == "failed":
                self.assertIn("Startmeldung", message)
                self.assertFalse(attempt._status_acknowledged())
            else:
                self.assertEqual(state, "ready", message)
            attempt.cancel()
            self.assertEqual(payload.read_text(), "old application payload")
            self.assertFalse((install_root / "restart-marker.txt").exists())
        finally:
            attempt.cancel()
            parent.terminate()
            parent.wait(timeout=5)
            attempt._thread.join(5)
            for process in processes:
                process.wait(timeout=10)

    def exercise(self, action):
        attempt_id = uuid.uuid4().hex
        signals = WindowsUpdateSignals(attempt_id)
        parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(90)"],
                                  creationflags=subprocess.CREATE_NO_WINDOW)
        status = self.work / f"update-{attempt_id}.status"
        install_root = self.work / attempt_id
        install_root.mkdir()
        payload = install_root / "update_payload.txt"
        payload.write_text("old application payload")
        command = installer_command(self.installer, attempt_id, self.work / f"update-{attempt_id}.log", status)
        command.append(f"/DIR={install_root}")
        command = [f"/STUPDATEPARENT={parent.pid}" if arg.startswith("/STUPDATEPARENT=") else arg for arg in command]
        setup = None
        try:
            setup = subprocess.Popen(command, creationflags=subprocess.CREATE_NO_WINDOW)
            deadline = time.monotonic() + 30
            while not signals.ready() and time.monotonic() < deadline and setup.poll() is None:
                time.sleep(0.05)
            self.assertTrue(signals.ready(), f"Setup did not acknowledge: exit={setup.poll()}")
            self.assertNotIn("install_started", status.read_text())
            self.assertEqual(payload.read_text(), "old application payload")
            if action == "commit":
                signals.signal("commit")
                time.sleep(0.15)
                self.assertIsNone(setup.poll())
                self.assertNotIn("install_started", status.read_text())
            elif action == "cancel":
                signals.signal("cancel")
            parent.terminate()
            parent.wait(timeout=5)
            code = setup.wait(timeout=30)
            content = status.read_text()
            if action == "commit":
                self.assertEqual(code, 0)
                self.assertIn("stage=parent_exited", content)
                self.assertIn("stage=setup_completed", content)
                self.assertLess(content.index("parent_exited"), content.index("install_started"))
                self.assertIn("new application payload", payload.read_text())
                deadline = time.monotonic() + 5
                while not (install_root / "restart-marker.txt").exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertIn("stage=restart_started", content)
                self.assertTrue((install_root / "restart-marker.txt").exists())
            else:
                self.assertNotEqual(code, 0)
                self.assertNotIn("install_started", content)
                self.assertIn("handoff_cancelled", content)
                self.assertEqual(payload.read_text(), "old application payload")
                self.assertFalse((install_root / "restart-marker.txt").exists())
        finally:
            signals.signal("cancel")
            if parent.poll() is None:
                parent.terminate()
                parent.wait(timeout=5)
            if setup is not None and setup.poll() is None:
                try:
                    setup.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    setup.kill()
                    setup.wait(timeout=5)
            signals.close()

    def test_commit_alone_does_not_install_before_parent_exit(self):
        self.exercise("commit")

    def test_cancel_prevents_file_replacement(self):
        self.exercise("cancel")

    def test_parent_death_without_commit_does_not_install(self):
        self.exercise("parent_death")

    def test_real_gui_restart_click_exits_parent_then_installs_and_restarts(self):
        work = self.work / "real-gui"
        download = work / "downloads/sacrificial-tower-update-e2e"
        download.mkdir(parents=True)
        installer = download / "SacrificialTowerSetup-9.9.9.exe"
        shutil.copyfile(self.installer, installer)
        installed = download / "unused"
        installed.mkdir()
        payload = installed / "update_payload.txt"
        payload.write_text("old application payload")
        environment = dict(os.environ, QT_QPA_PLATFORM="offscreen", COOLING_TOWER_DISABLE_SLICER_DISCOVERY="1")
        parent = subprocess.run([sys.executable, str(ROOT / "tests/fixtures/update_gui_parent.py"), str(work), str(installer)],
                                capture_output=True, text=True, timeout=40, env=environment,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(parent.returncode, 0, parent.stdout + parent.stderr)
        journal = (work / "userdata/logs/background_jobs.jsonl").read_text(encoding="utf-8")
        self.assertIn("update_handoff_committed", journal)
        self.assertIn("update_shutdown_completed", journal)
        deadline = time.monotonic() + 15
        while not (installed / "restart-marker.txt").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertIn("new application payload", payload.read_text())
        self.assertTrue((installed / "restart-marker.txt").exists())
        status = next((work / "userdata/logs/updates").glob("*.status")).read_text()
        self.assertIn("stage=parent_exited", status)
        self.assertIn("stage=setup_completed", status)
        self.assertIn("stage=restart_started", status)
