from __future__ import annotations

import math
import os
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


from PySide6.QtCore import QLineF, QPoint
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from cooling_tower.gui.widgets import PreviewCanvas
from cooling_tower.models import BedBounds
from cooling_tower.preview import LineSegment3D, Point3D, PreviewScene


def make_segments(count: int, *, offset: float = 0.0):
    return tuple(
        LineSegment3D(
            Point3D(
                offset + float(index % 200),
                float((index // 200) % 200),
                float(index % 500) / 10.0,
            ),
            Point3D(
                offset + float(index % 200) + 1.0,
                float((index // 200) % 200) + 1.0,
                float(index % 500) / 10.0,
            ),
        )
        for index in range(count)
    )


def make_scene(
    object_count: int = 10,
    tower_count: int = 4,
    *,
    offset: float = 0.0,
) -> PreviewScene:
    return PreviewScene(
        object_segments=make_segments(object_count, offset=offset),
        tower_segments=make_segments(tower_count, offset=offset + 210.0),
        bed_bounds=BedBounds(0.0, 240.0, 0.0, 240.0),
        tower_center_xy_mm=(220.0, 10.0),
        source_segment_count=object_count,
        displayed_segment_count=object_count,
        tower_height_mm=50.0,
    )


class PreviewLineBatchingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_prepared_blocks_are_bounded_complete_and_reused(self) -> None:
        canvas = PreviewCanvas()
        scene = make_scene(object_count=9_000, tower_count=4_200)
        canvas.set_scene(scene)

        prepared = canvas._prepare_line_frame()

        self.assertEqual(sum(map(len, prepared.bed_blocks)), 4)
        self.assertEqual(sum(map(len, prepared.object_blocks)), 9_000)
        self.assertEqual(sum(map(len, prepared.tower_blocks)), 4_200)
        for block in (
            *prepared.bed_blocks,
            *prepared.object_blocks,
            *prepared.tower_blocks,
        ):
            self.assertGreater(len(block), 0)
            self.assertLessEqual(len(block), canvas.LINE_BLOCK_SIZE)
        self.assertIs(canvas._prepare_line_frame(), prepared)
        canvas.close()

    def test_camera_size_fit_and_scene_changes_rebuild_the_frame(self) -> None:
        canvas = PreviewCanvas()
        canvas.resize(800, 600)
        canvas.set_scene(make_scene())
        initial = canvas._prepare_line_frame()

        canvas.yaw_deg += 1.0
        rotated = canvas._prepare_line_frame()
        self.assertIsNot(rotated, initial)

        canvas.fit_scene(emit=False)
        fitted = canvas._prepare_line_frame()
        self.assertIsNot(fitted, rotated)

        canvas.resize(900, 600)
        resized = canvas._prepare_line_frame()
        self.assertIsNot(resized, fitted)

        canvas.set_scene(make_scene(offset=3.0))
        replaced = canvas._prepare_line_frame()
        self.assertIsNot(replaced, resized)
        canvas.close()

    def test_object_sampling_limit_preserves_the_existing_stride_contract(
        self,
    ) -> None:
        canvas = PreviewCanvas()
        scene = make_scene(object_count=64_001, tower_count=0)
        canvas.set_scene(scene)

        prepared = canvas._prepare_line_frame()
        stride = math.ceil(
            len(scene.object_segments) / canvas.MAXIMUM_OBJECT_DRAW_LINES
        )
        expected_count = len(range(0, len(scene.object_segments), stride))

        self.assertLessEqual(
            sum(map(len, prepared.object_blocks)),
            canvas.MAXIMUM_OBJECT_DRAW_LINES,
        )
        self.assertEqual(
            sum(map(len, prepared.object_blocks)),
            expected_count,
        )
        canvas.close()

    def test_draws_each_block_with_one_bulk_call(self) -> None:
        class RecordingPainter:
            def __init__(self) -> None:
                self.bulk_calls: list[tuple[QLineF, ...]] = []

            def drawLines(self, lines) -> None:  # noqa: N802
                self.bulk_calls.append(tuple(lines))

            def drawLine(self, _line) -> None:  # noqa: N802
                raise AssertionError("Individual drawing must not be used")

        blocks = (
            (QLineF(0.0, 0.0, 1.0, 1.0), QLineF(1.0, 1.0, 2.0, 2.0)),
            (QLineF(2.0, 2.0, 3.0, 3.0),),
        )
        painter = RecordingPainter()

        PreviewCanvas._draw_line_blocks(painter, blocks)  # type: ignore[arg-type]

        self.assertEqual(tuple(map(len, painter.bulk_calls)), (2, 1))

    def test_unsupported_bulk_overload_uses_controlled_fallback(self) -> None:
        class FallbackPainter:
            def __init__(self) -> None:
                self.individual_calls: list[QLineF] = []

            def drawLines(self, _lines) -> None:  # noqa: N802
                raise TypeError("synthetic unsupported overload")

            def drawLine(self, line) -> None:  # noqa: N802
                self.individual_calls.append(line)

        block = (
            QLineF(0.0, 0.0, 1.0, 1.0),
            QLineF(1.0, 1.0, 2.0, 2.0),
        )
        painter = FallbackPainter()

        PreviewCanvas._draw_line_blocks(
            painter,  # type: ignore[arg-type]
            (block,),
        )

        self.assertEqual(painter.individual_calls, list(block))

    def test_unrelated_painter_errors_are_not_hidden(self) -> None:
        class BrokenPainter:
            def drawLines(self, _lines) -> None:  # noqa: N802
                raise RuntimeError("synthetic painter failure")

        with self.assertRaisesRegex(RuntimeError, "synthetic painter failure"):
            PreviewCanvas._draw_line_blocks(
                BrokenPainter(),  # type: ignore[arg-type]
                ((QLineF(0.0, 0.0, 1.0, 1.0),),),
            )

    def test_empty_scene_renders_safely_with_only_the_bed(self) -> None:
        canvas = PreviewCanvas()
        canvas.resize(640, 480)
        canvas.set_scene(make_scene(object_count=0, tower_count=0))
        image = QImage(640, 480, QImage.Format.Format_ARGB32)
        painter = QPainter(image)

        canvas.render(painter, QPoint())
        painter.end()

        prepared = canvas._prepare_line_frame()
        self.assertEqual(sum(map(len, prepared.bed_blocks)), 4)
        self.assertEqual(prepared.object_blocks, ())
        self.assertEqual(prepared.tower_blocks, ())
        canvas.close()

    def test_rotation_keeps_all_prepared_coordinates_finite(self) -> None:
        canvas = PreviewCanvas()
        canvas.set_scene(make_scene(object_count=200, tower_count=50))

        for yaw, pitch in ((-38.0, 28.0), (90.0, 0.0), (0.0, 89.0)):
            canvas.yaw_deg = yaw
            canvas.pitch_deg = pitch
            prepared = canvas._prepare_line_frame()
            for line in (
                line
                for blocks in (
                    prepared.bed_blocks,
                    prepared.object_blocks,
                    prepared.tower_blocks,
                )
                for block in blocks
                for line in block
            ):
                self.assertTrue(
                    all(
                        math.isfinite(value)
                        for value in (line.x1(), line.y1(), line.x2(), line.y2())
                    )
                )
        canvas.close()

    def test_invalid_block_limits_are_rejected(self) -> None:
        canvas = PreviewCanvas()
        segments = make_segments(1)
        context = canvas._projection_context()
        parameters = canvas._fit_parameters(context)
        original = canvas.LINE_BLOCK_SIZE
        canvas.LINE_BLOCK_SIZE = 0
        try:
            with self.assertRaisesRegex(ValueError, "LINE_BLOCK_SIZE"):
                canvas._line_blocks(segments, parameters, context)
        finally:
            canvas.LINE_BLOCK_SIZE = original
        with self.assertRaisesRegex(ValueError, "maximum_lines"):
            canvas._line_blocks(
                segments,
                parameters,
                context,
                maximum_lines=0,
            )
        canvas.close()


if __name__ == "__main__":
    unittest.main()
