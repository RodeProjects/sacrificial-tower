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
from cooling_tower.models import SourceKind
from cooling_tower.services import SourceRecognitionError, recognize_source


def binary_stl() -> bytes:
    triangle = struct.pack(
        "<12fH",
        0.0, 0.0, 1.0,
        0.0, 0.0, 0.0,
        1.0, 0.0, 0.0,
        0.0, 1.0, 0.0,
        0,
    )
    return b"binary-test".ljust(80, b"\0") + struct.pack("<I", 1) + triangle


class SourceRecognitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_recognizes_ascii_and_binary_stl(self) -> None:
        ascii_stl = self.root / "ascii.stl"
        binary = self.root / "binary.stl"
        ascii_stl.write_text(
            "solid part\nfacet normal 0 0 1\nouter loop\n"
            "vertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\n"
            "endloop\nendfacet\nendsolid part\n",
            encoding="ascii",
        )
        binary.write_bytes(binary_stl())
        self.assertEqual(recognize_source(ascii_stl).format_description, "ASCII-STL")
        self.assertEqual(recognize_source(binary).format_description, "Binär-STL")

    def test_rejects_gcode_empty_unsupported_and_damaged_sources(self) -> None:
        gcode = self.root / "part.gcode"
        empty = self.root / "empty.stl"
        unsupported = self.root / "part.3mf"
        damaged = self.root / "damaged.stl"
        gcode.write_text("G90\nG1 X1 Y1 E1\n", encoding="ascii")
        empty.write_bytes(b"")
        unsupported.write_bytes(b"data")
        damaged.write_bytes(b"not an stl")
        for path in (gcode, empty, unsupported, damaged):
            with self.subTest(path=path.name):
                with self.assertRaises(SourceRecognitionError):
                    recognize_source(path)


class SourceDropZoneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_zone_accepts_only_stl_and_exposes_stl_kind(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gcode = root / "part.gcode"
            stl = root / "part.stl"
            gcode.write_text("G90\nG1 X1 Y1 E1\n", encoding="ascii")
            stl.write_bytes(binary_stl())
            zone = SourceDropZone()
            self.assertFalse(zone.set_file(gcode))
            self.assertTrue(zone.set_file(stl))
            self.assertIs(zone.selected_kind, SourceKind.STL)
            self.assertEqual(zone.file_type_label.text(), "Binär-STL")
            self.assertEqual(zone.browse_button.text(), "Andere STL auswählen")

    def test_valid_drag_stays_highlighted_until_leave_or_drop(self) -> None:
        class UrlStub:
            def __init__(self, path: Path) -> None:
                self.path = path

            def isLocalFile(self) -> bool:  # noqa: N802
                return True

            def toLocalFile(self) -> str:  # noqa: N802
                return str(self.path)

        class DragEventStub:
            def __init__(self, path: Path) -> None:
                self._urls = [UrlStub(path)]
                self.accepted = False

            def mimeData(self):  # noqa: N802
                return self

            def urls(self):
                return self._urls

            def acceptProposedAction(self) -> None:  # noqa: N802
                self.accepted = True

            def ignore(self) -> None:
                self.accepted = False

            def accept(self) -> None:
                self.accepted = True

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "part.stl"
            source.write_bytes(binary_stl())
            zone = SourceDropZone()

            enter_event = DragEventStub(source)
            zone.dragEnterEvent(enter_event)
            self.assertTrue(enter_event.accepted)
            self.assertTrue(zone.property("dragActive"))

            move_event = DragEventStub(source)
            zone.dragMoveEvent(move_event)
            self.assertTrue(move_event.accepted)
            self.assertTrue(zone.property("dragActive"))

            leave_event = DragEventStub(source)
            zone.dragLeaveEvent(leave_event)
            self.assertTrue(leave_event.accepted)
            self.assertFalse(zone.property("dragActive"))

            self.assertTrue(zone.set_file(source))
            for state in ("analyzing", "ready", "rejected"):
                zone.set_analysis_state(state)
                state_event = DragEventStub(source)
                zone.dragEnterEvent(state_event)
                self.assertTrue(state_event.accepted)
                self.assertTrue(zone.property("dragActive"), state)
                zone.dragLeaveEvent(state_event)
                self.assertFalse(zone.property("dragActive"), state)

            zone.dragEnterEvent(DragEventStub(source))
            drop_event = DragEventStub(source)
            zone.dropEvent(drop_event)
            self.assertTrue(drop_event.accepted)
            self.assertFalse(zone.property("dragActive"))
            zone.close()


if __name__ == "__main__":
    unittest.main()
