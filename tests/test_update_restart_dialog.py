from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QTimer
from PySide6.QtWidgets import QApplication, QDialog

from cooling_tower.gui.update_restart_dialog import UpdateRestartCountdownDialog


class UpdateRestartCountdownDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_countdown_uses_verified_download_wording_and_counts_to_one(self) -> None:
        dialog = UpdateRestartCountdownDialog(seconds=5)

        self.assertIn("erfolgreich heruntergeladen und geprüft", dialog.text())
        self.assertIn("in 5 Sekunden", dialog.text())
        self.assertIn(
            "bei erfolgreicher Installation automatisch neu gestartet",
            dialog.text(),
        )
        self.assertEqual(dialog._timer.interval(), 1000)

        for expected in (4, 3, 2):
            dialog._advance_countdown()
            self.assertIn(f"in {expected} Sekunden", dialog.text())
        dialog._advance_countdown()
        self.assertIn("in 1 Sekunde", dialog.text())

        dialog._advance_countdown()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)

    def test_countdown_rejects_a_non_positive_duration(self) -> None:
        with self.assertRaisesRegex(ValueError, "mindestens eine Sekunde"):
            UpdateRestartCountdownDialog(seconds=0)

    def test_cancel_button_rejects_countdown_before_installation(self) -> None:
        dialog = UpdateRestartCountdownDialog(seconds=10)
        QTimer.singleShot(0, dialog.cancel_button.click)
        self.assertEqual(dialog.exec_countdown(), QDialog.DialogCode.Rejected)
        self.assertFalse(dialog._timer.isActive())

    def test_countdown_closes_after_its_real_timer_expires(self) -> None:
        dialog = UpdateRestartCountdownDialog(seconds=1)
        started = time.monotonic()

        result = dialog.exec_countdown()

        elapsed = time.monotonic() - started
        self.assertEqual(result, QDialog.DialogCode.Accepted)
        self.assertGreaterEqual(elapsed, 0.8)
        self.assertLess(elapsed, 2.5)

    def test_restart_button_accepts_immediately_and_stops_timer(self) -> None:
        dialog = UpdateRestartCountdownDialog(seconds=10)
        self.addCleanup(dialog.close)
        dialog._timer.start()
        # Measure the synchronous button handler, excluding unrelated queued
        # GUI work left by other fixtures in the shared application event loop.
        started = time.monotonic()
        dialog.restart_button.click()
        self.assertLess(time.monotonic()-started, 0.8)
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.remaining_seconds, 10)
        self.assertFalse(dialog._timer.isActive())

    def test_restart_button_closes_the_modal_countdown_without_a_timer_tick(self) -> None:
        dialog = UpdateRestartCountdownDialog(seconds=10)
        self.addCleanup(dialog.close)
        QTimer.singleShot(0, dialog.restart_button.click)
        self.assertEqual(dialog.exec_countdown(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.remaining_seconds, 10)
        self.assertFalse(dialog._timer.isActive())

    def test_restart_button_is_blue_and_to_the_right_of_cancel(self) -> None:
        dialog = UpdateRestartCountdownDialog()
        self.addCleanup(dialog.close)
        dialog.setStyleSheet((SRC_ROOT/"cooling_tower/gui/styles.qss").read_text(encoding="utf-8"))
        dialog.show()
        self.app.processEvents()
        cancel = dialog.cancel_button.mapTo(dialog, QPoint())
        restart = dialog.restart_button.mapTo(dialog, QPoint())
        self.assertEqual(dialog.restart_button.text(), "Jetzt neu starten")
        self.assertEqual(dialog.restart_button.objectName(), "previewButton")
        self.assertGreater(restart.x(), cancel.x()+dialog.cancel_button.width())
        self.assertEqual(restart.y(), cancel.y())
        self.assertLess(dialog.width()-restart.x()-dialog.restart_button.width(), 20)


if __name__ == "__main__":
    unittest.main()
