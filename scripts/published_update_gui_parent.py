"""Drive the released previous version's original Qt updater in an isolated job."""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument("--source", type=Path, required=True)
parser.add_argument("--work", type=Path, required=True)
parser.add_argument("--previous-version", required=True)
parser.add_argument("--version", required=True)
args = parser.parse_args()
sys.path.insert(0, str(args.source / "src"))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from cooling_tower.diagnostics import DiagnosticJournal
from cooling_tower.gui.main_window import MainWindow
from cooling_tower.gui.update_restart_dialog import UpdateRestartCountdownDialog
from cooling_tower.update import UpdateError, UpdateService, parse_update_manifest
from cooling_tower.update_channel import DEFAULT_UPDATE_MANIFEST_URL
from cooling_tower.update_installation import UpdateInstallationAttempt
from cooling_tower.version import APP_VERSION

assert APP_VERSION == args.previous_version, "Original released source version differs"
downloads = args.work / "downloads"
downloads.mkdir()
service = UpdateService(temporary_root=downloads, timeout_s=60)
info = service.check_for_update(APP_VERSION)
assert info and info.version == args.version, "Published version transition missing"
assert service.check_for_update(args.version) is None, "Current version offered again"
with service._opener(service._request(DEFAULT_UPDATE_MANIFEST_URL, "application/json"), timeout=60) as response:
    raw = json.loads(response.read())
raw["release_notes"] += " altered acceptance fixture"
try:
    parse_update_manifest(json.dumps(raw))
except UpdateError as error:
    assert error.code == "update_manifest_signature_invalid"
else:
    raise AssertionError("Altered real published signature accepted")

# Real downloaded bytes must also be rejected before any launch when the
# expected digest differs. The launch stub makes this negative case harmless.
downloaded = service.download_installer(info)
launches = []
def forbidden_launch(*arguments, **keywords):
    launches.append(True)
    raise AssertionError("Integrity failure reached process launch")
attempt = UpdateInstallationAttempt(
    downloaded, replace(info, sha256="0" * 64), args.work / "negative-logs",
    popen=forbidden_launch,
).start()
deadline = time.monotonic() + 20
while attempt.poll()[0] == "starting" and time.monotonic() < deadline:
    time.sleep(0.05)
assert attempt.poll()[0] == "failed" and not launches, "Digest guard failed"
attempt.cancel()
service.discard_installer(downloaded)

app = QApplication([])
app.setQuitOnLastWindowClosed(True)
user_data = args.work / "userdata"
user_data.mkdir(exist_ok=True)
(user_data / "update-data-canary.txt").write_text("preserve this test data", encoding="utf-8")
journal = DiagnosticJournal(user_data / "logs/background_jobs.jsonl")
journal.start_session()
window = MainWindow(
    user_data_root=user_data, update_service=service,
    enable_update_check=True, enable_startup_slicer_discovery=False,
    diagnostic_journal=journal,
)
window.show()
clicked = False
restarted = False
def drive():
    global clicked, restarted
    if window.available_update is not None and not clicked:
        assert window.available_update.version == args.version
        clicked = True
        window.update_button.click()
    for widget in app.topLevelWidgets():
        if isinstance(widget, UpdateRestartCountdownDialog) and not restarted:
            restarted = True
            widget.restart_button.click()
def timeout():
    window._cancel_update_installation()
    window.close()
    app.exit(2)
timer = QTimer()
timer.timeout.connect(drive)
timer.start(100)
def prepare_test_workflow():
    workflow = window.workflow
    workflow.set_slicer_step_visible(True)
    workflow.source_validation_succeeded("acceptance-test.stl", analysis_complete=True)
    workflow.slicer_succeeded("Testslicer")
    assert workflow.complete_preparation()
QTimer.singleShot(0, prepare_test_workflow)
QTimer.singleShot(150000, timeout)
code = app.exec()
journal.close_session()
assert code == 0 and clicked and restarted, "Real updater GUI did not finish its handoff"
(args.work / "gui-result.json").write_text(json.dumps({
    "previous_version": APP_VERSION, "version": args.version,
    "manifest_url": DEFAULT_UPDATE_MANIFEST_URL,
    "signature_tampering_blocked": True, "digest_mismatch_blocked_before_launch": True,
    "current_version_not_offered": True, "real_download_and_restart_clicked": True,
}), encoding="utf-8")
