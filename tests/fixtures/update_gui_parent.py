"""Isolated real Qt parent for the native update integration test."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from cooling_tower.diagnostics import DiagnosticJournal
from cooling_tower.gui.main_window import MainWindow
from cooling_tower.gui.update_restart_dialog import UpdateRestartCountdownDialog
from cooling_tower.update import UpdateInfo, UpdateService

work, installer = map(Path, sys.argv[1:])
app = QApplication([])
app.setQuitOnLastWindowClosed(True)
journal = DiagnosticJournal(work / "userdata/logs/background_jobs.jsonl")
journal.start_session()
service = UpdateService(temporary_root=installer.parent.parent)
window = MainWindow(user_data_root=work / "userdata", update_service=service,
                    enable_update_check=False, enable_startup_slicer_discovery=False,
                    diagnostic_journal=journal)
window.available_update = UpdateInfo("9.9.9", "", hashlib.sha256(installer.read_bytes()).hexdigest(), installer.stat().st_size)
window._update_download_request_id = 9
window.show()


def start():
    workflow = window.workflow
    workflow.set_slicer_step_visible(True)
    workflow.source_validation_succeeded("test.stl", analysis_complete=True)
    workflow.slicer_succeeded("Testslicer")
    assert workflow.complete_preparation()
    def click_restart():
        dialogs = [widget for widget in app.topLevelWidgets() if isinstance(widget, UpdateRestartCountdownDialog)]
        assert len(dialogs) == 1
        dialogs[0].restart_button.click()
    QTimer.singleShot(30, click_restart)
    window._on_update_download_succeeded(9, installer)


def timeout():
    window._cancel_update_installation()
    window.close()
    app.exit(2)


QTimer.singleShot(0, start)
QTimer.singleShot(20000, timeout)
code = app.exec()
journal.close_session()
raise SystemExit(code)
