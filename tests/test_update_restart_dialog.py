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

    def test_countdown_closes_after_its_real_timer_expires(self) -> None:
        dialog = UpdateRestartCountdownDialog(seconds=1)
        started = time.monotonic()

        result = dialog.exec_countdown()

        elapsed = time.monotonic() - started
        self.assertEqual(result, QDialog.DialogCode.Accepted)
        self.assertGreaterEqual(elapsed, 0.8)
        self.assertLess(elapsed, 2.5)


if __name__ == "__main__":
    unittest.main()
