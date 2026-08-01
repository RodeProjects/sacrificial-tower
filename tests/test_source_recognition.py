from __future__ import annotations

import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from cooling_tower.gui.widgets import SourceDropZone
from cooling_tower.gui.main_window import MainWindow
from cooling_tower.gui.workflow_controller import WorkflowStage
from cooling_tower.models import SourceKind
from cooling_tower.services import SourceRecognitionError, recognize_source


def binary_stl() -> bytes:
    triangle = struct.pack(
        "<12fH",
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0,
    )
    return b"binary-test".ljust(80, b"\0") + struct.pack("<I", 1) + triangle


class SourceRecognitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_recognizes_gcode_ascii_stl_and_binary_stl(self) -> None:
        gcode = self.root / "part.gcode"
        ascii_stl = self.root / "ascii.stl"
        binary = self.root / "binary.stl"
        gcode.write_text("; generated\nG90\nG1 X1 Y2 E0.3\n", encoding="ascii")
        ascii_stl.write_text(
            "solid part\nfacet normal 0 0 1\nouter loop\n"
            "vertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\n"
            "endloop\nendfacet\nendsolid part\n",
            encoding="ascii",
        )
        binary.write_bytes(binary_stl())
        self.assertIs(recognize_source(gcode).source_kind, SourceKind.GCODE)
        self.assertEqual(recognize_source(ascii_stl).format_description, "ASCII-STL")
        self.assertEqual(recognize_source(binary).format_description, "Binär-STL")

    def test_rejects_empty_unsupported_renamed_and_damaged_sources(self) -> None:
        empty = self.root / "empty.gcode"
        unsupported = self.root / "part.3mf"
        renamed = self.root / "renamed.stl"
        damaged = self.root / "damaged.stl"
        empty.write_bytes(b"")
        unsupported.write_bytes(b"data")
        renamed.write_text("G90\nG1 X1 Y1 E1\n", encoding="ascii")
        damaged.write_bytes(b"not an stl")
        for path in (empty, unsupported, renamed, damaged):
            with self.subTest(path=path.name):
                with self.assertRaises(SourceRecognitionError):
                    recognize_source(path)


class SourceDropZoneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_one_zone_accepts_both_types_and_exposes_detected_kind(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gcode = root / "part.gcode"
            stl = root / "part.stl"
            gcode.write_text("G90\nG1 X1 Y1 E1\n", encoding="ascii")
            stl.write_bytes(binary_stl())
            zone = SourceDropZone()
            selected: list[tuple[str, str]] = []
            zone.source_selected.connect(
                lambda path, kind: selected.append((path, kind))
            )
            self.assertTrue(zone.set_file(gcode))
            self.assertIs(zone.selected_kind, SourceKind.GCODE)
            self.assertTrue(zone.set_file(stl))
            self.assertIs(zone.selected_kind, SourceKind.STL)
            self.assertEqual(zone.file_type_label.text(), "Binär-STL")
            self.assertEqual([item[1] for item in selected], ["gcode", "stl"])

    def test_main_window_routes_stl_without_starting_gcode_analysis(self) -> None:
        fixture = (
            PROJECT_ROOT
            / "tests"
            / "fixtures"
            / "stl"
            / "test_model_manifold.stl"
        )
        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow(
                user_settings_path=Path(directory) / "settings.json",
                enable_update_check=False,
            )
            try:
                self.assertTrue(window.drop_zone.set_file(fixture))
                self.assertIs(window.current_source_kind, SourceKind.STL)
                self.assertIsNone(window.current_gcode_path)
                self.assertIs(
                    window.workflow.stage,
                    WorkflowStage.VALIDATING_STL,
                )
                self.assertIsNone(window.analysis_snapshot)
            finally:
                window.close()
                window.deleteLater()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
