from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cooling_tower.gui.export_history import (
    AMBIGUOUS_LATEST_EXPORT,
    NO_EXPORT_FOLDER,
    NO_VALID_EXPORT_FOLDER,
    resolve_latest_export_directory,
)


class ExportHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_export(
        self,
        name: str,
        created_at: str,
    ) -> Path:
        directory = self.root / name
        directory.mkdir()
        artifact = directory / "tower.stl"
        artifact.write_text("solid tower\nendsolid tower\n", encoding="utf-8")
        (directory / "export_summary.txt").write_text(
            "Export erfolgreich\n",
            encoding="utf-8",
        )
        (directory / "export_report.json").write_text(
            json.dumps(
                {
                    "report_type": "cooling_tower_export_diagnostics",
                    "created_at": created_at,
                    "summary": {"export_succeeded": True},
                    "output": {"path": str(artifact)},
                }
            ),
            encoding="utf-8",
        )
        return directory.resolve()

    def test_missing_and_incomplete_export_folders_have_clear_reasons(self) -> None:
        missing = resolve_latest_export_directory(self.root / "missing")
        self.assertIsNone(missing.directory)
        self.assertEqual(missing.unavailable_reason, NO_EXPORT_FOLDER)

        (self.root / "unrelated-folder").mkdir()
        incomplete = resolve_latest_export_directory(self.root)
        self.assertIsNone(incomplete.directory)
        self.assertEqual(
            incomplete.unavailable_reason,
            NO_VALID_EXPORT_FOLDER,
        )

    def test_latest_complete_export_is_selected_by_export_time(self) -> None:
        self._write_export("newer-modification", "2026-07-30T09:00:00+02:00")
        latest = self._write_export(
            "latest-export",
            "2026-07-30T10:00:00+02:00",
        )

        resolution = resolve_latest_export_directory(self.root)

        self.assertEqual(resolution.directory, latest)
        self.assertIsNone(resolution.unavailable_reason)

    def test_exact_latest_tie_is_not_guessed(self) -> None:
        first = self._write_export("first", "2026-07-30T10:00:00+02:00")
        second = self._write_export("second", "2026-07-30T10:00:00+02:00")
        tied_timestamp_ns = 1_800_000_000_000_000_000
        for directory in (first, second):
            report = directory / "export_report.json"
            os.utime(report, ns=(tied_timestamp_ns, tied_timestamp_ns))

        ambiguous = resolve_latest_export_directory(self.root)
        preferred = resolve_latest_export_directory(
            self.root,
            preferred_directory=second,
        )

        self.assertIsNone(ambiguous.directory)
        self.assertEqual(
            ambiguous.unavailable_reason,
            AMBIGUOUS_LATEST_EXPORT,
        )
        self.assertEqual(preferred.directory, second)
        self.assertIsNone(preferred.unavailable_reason)


if __name__ == "__main__":
    unittest.main()
