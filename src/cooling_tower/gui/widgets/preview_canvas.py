from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import chain

from PySide6.QtCore import QLineF, QPoint, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import QWidget

from cooling_tower.preview import LineSegment3D, Point3D, PreviewScene


_LineBlock = tuple[QLineF, ...]
_LineBlocks = tuple[_LineBlock, ...]


@dataclass(frozen=True, slots=True)
class _ProjectionContext:
    center_x: float
    center_y: float
    cosine_yaw: float
    sine_yaw: float
    cosine_pitch: float
    sine_pitch: float

    def project_raw(self, point: Point3D) -> tuple[float, float]:
        x = point.x - self.center_x
        y = point.y - self.center_y
        rotated_x = self.cosine_yaw * x - self.sine_yaw * y
        rotated_y = self.sine_yaw * x + self.cosine_yaw * y
        projected_y = self.cosine_pitch * point.z - self.sine_pitch * rotated_y
        return rotated_x, -projected_y


@dataclass(frozen=True, slots=True)
class _PreparedLineFrame:
    key: tuple[object, ...]
    bed_blocks: _LineBlocks
    object_blocks: _LineBlocks
    tower_blocks: _LineBlocks


class PreviewCanvas(QWidget):
    """Small software-rendered 3D view without an external OpenGL runtime."""

    camera_changed = Signal(object)
    BED_COLOR = "#667080"
    OBJECT_COLOR = "#67b7c7"
    TOWER_COLOR = "#ff9e4f"
    MAXIMUM_OBJECT_DRAW_LINES = 32_000
    LINE_BLOCK_SIZE = 4_096
    # Ein Mausradschritt Abstand: gleicher Faktor wie die interaktive
    # Radsteuerung, sowohl initial als auch über „Seitenansicht“.
    SIDE_VIEW_ZOOM = 1.0 / 1.15

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("previewCanvas")
        self.setMinimumSize(520, 420)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.scene: PreviewScene | None = None
        self.yaw_deg = -38.0
        self.pitch_deg = 28.0
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self._last_mouse: QPoint | None = None
        self._drag_button = Qt.MouseButton.NoButton
        self._fit_whole_bed = False
        self._prepared_frame: _PreparedLineFrame | None = None

    def set_scene(self, scene: PreviewScene | None) -> None:
        self.scene = scene
        self._prepared_frame = None
        self.fit_objects(emit=False)
        self.update()

    def camera_state(self) -> dict[str, float]:
        return {
            "yaw_deg": self.yaw_deg,
            "pitch_deg": self.pitch_deg,
            "zoom": self.zoom,
            "pan_x": self.pan_x,
            "pan_y": self.pan_y,
        }

    def apply_camera_state(self, values: object) -> None:
        if not isinstance(values, dict):
            return
        try:
            yaw = float(values.get("yaw_deg", self.yaw_deg))
            pitch = float(values.get("pitch_deg", self.pitch_deg))
            zoom = float(values.get("zoom", self.zoom))
            pan_x = float(values.get("pan_x", self.pan_x))
            pan_y = float(values.get("pan_y", self.pan_y))
        except (TypeError, ValueError):
            return
        if not all(math.isfinite(value) for value in (yaw, pitch, zoom, pan_x, pan_y)):
            return
        self.yaw_deg = yaw
        self.pitch_deg = max(-89.0, min(89.0, pitch))
        self.zoom = max(0.05, min(50.0, zoom))
        self.pan_x = pan_x
        self.pan_y = pan_y
        self.update()

    def reset_camera(self) -> None:
        self.yaw_deg = -38.0
        self.pitch_deg = 28.0
        self.fit_objects(emit=False)
        self._emit_camera()

    def fit_scene(self, *, emit: bool = True) -> None:
        """Fit the complete print bed into view."""

        self._fit_whole_bed = True
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.update()
        if emit:
            self._emit_camera()

    def fit_objects(self, *, emit: bool = True) -> None:
        """Fit the reference object and tower, keeping them easy to inspect."""

        self._fit_whole_bed = False
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.update()
        if emit:
            self._emit_camera()

    def front_view(self) -> None:
        self.yaw_deg = 0.0
        self.pitch_deg = 0.0
        self.fit_objects(emit=False)
        self._emit_camera()

    def side_view(self) -> None:
        self.yaw_deg = 90.0
        self.pitch_deg = 0.0
        self.fit_objects(emit=False)
        # Zwei Mausradstufen weiter heraus als die automatische Anpassung.
        # So bleibt in der initialen Seitenansicht sichtbar Luft um hohe Türme.
        self.zoom = self.SIDE_VIEW_ZOOM
        self._emit_camera()

    def top_view(self) -> None:
        """Look vertically down onto the print bed and fitted objects."""

        self.yaw_deg = 0.0
        # Keep one degree of distance from the projection singularity while
        # remaining visually indistinguishable from a vertical top-down view.
        self.pitch_deg = 89.0
        self.fit_objects(emit=False)
        self._emit_camera()

    def _emit_camera(self) -> None:
        self.update()
        self.camera_changed.emit(self.camera_state())

    def _projection_context(self) -> _ProjectionContext:
        scene = self.scene
        if scene is None:
            return _ProjectionContext(0.0, 0.0, 1.0, 0.0, 1.0, 0.0)
        bed = scene.bed_bounds
        center_x = (bed.minimum_x_mm + bed.maximum_x_mm) / 2.0
        center_y = (bed.minimum_y_mm + bed.maximum_y_mm) / 2.0
        yaw = math.radians(self.yaw_deg)
        pitch = math.radians(self.pitch_deg)
        return _ProjectionContext(
            center_x,
            center_y,
            math.cos(yaw),
            math.sin(yaw),
            math.cos(pitch),
            math.sin(pitch),
        )

    def _raw_project(self, point: Point3D) -> tuple[float, float]:
        return self._projection_context().project_raw(point)

    @staticmethod
    def _projected_bounds(
        points: Iterable[Point3D],
        context: _ProjectionContext,
    ) -> tuple[float, float, float, float] | None:
        minimum_x = math.inf
        maximum_x = -math.inf
        minimum_y = math.inf
        maximum_y = -math.inf
        found_point = False
        for point in points:
            raw_x, raw_y = context.project_raw(point)
            minimum_x = min(minimum_x, raw_x)
            maximum_x = max(maximum_x, raw_x)
            minimum_y = min(minimum_y, raw_y)
            maximum_y = max(maximum_y, raw_y)
            found_point = True
        if not found_point:
            return None
        return minimum_x, maximum_x, minimum_y, maximum_y

    def _fit_parameters(
        self,
        context: _ProjectionContext | None = None,
    ) -> tuple[float, float, float]:
        scene = self.scene
        if scene is None:
            return 1.0, self.width() / 2.0, self.height() / 2.0
        context = context or self._projection_context()
        if self._fit_whole_bed:
            bed = scene.bed_bounds
            z_max = max(1.0, scene.tower_height_mm)
            fit_points: Iterable[Point3D] = (
                Point3D(x, y, z)
                for x in (bed.minimum_x_mm, bed.maximum_x_mm)
                for y in (bed.minimum_y_mm, bed.maximum_y_mm)
                for z in (0.0, z_max)
            )
        else:
            fit_points = (
                point
                for segment in chain(
                    scene.object_segments,
                    scene.tower_segments,
                )
                for point in (segment.start, segment.end)
            )
        bounds = self._projected_bounds(fit_points, context)
        if bounds is None:
            bed = scene.bed_bounds
            bounds = self._projected_bounds(
                (
                    Point3D(bed.minimum_x_mm, bed.minimum_y_mm, 0.0),
                    Point3D(bed.maximum_x_mm, bed.maximum_y_mm, 1.0),
                ),
                context,
            )
        if bounds is None:  # Defensive: the fallback above always has points.
            return 1.0, self.width() / 2.0, self.height() / 2.0
        minimum_x, maximum_x, minimum_y, maximum_y = bounds
        span_x = max(1.0, maximum_x - minimum_x)
        span_y = max(1.0, maximum_y - minimum_y)
        scale = min(
            max(1.0, self.width() - 40.0) / span_x,
            max(1.0, self.height() - 40.0) / span_y,
        ) * self.zoom
        center_x = (minimum_x + maximum_x) / 2.0
        center_y = (minimum_y + maximum_y) / 2.0
        offset_x = self.width() / 2.0 - center_x * scale + self.pan_x
        offset_y = self.height() / 2.0 - center_y * scale + self.pan_y
        return scale, offset_x, offset_y

    def _project(
        self,
        point: Point3D,
        parameters: tuple[float, float, float],
        context: _ProjectionContext | None = None,
    ) -> QPointF:
        context = context or self._projection_context()
        raw_x, raw_y = context.project_raw(point)
        scale, offset_x, offset_y = parameters
        return QPointF(raw_x * scale + offset_x, raw_y * scale + offset_y)

    def _frame_key(self, scene: PreviewScene) -> tuple[object, ...]:
        return (
            id(scene),
            self.width(),
            self.height(),
            self.yaw_deg,
            self.pitch_deg,
            self.zoom,
            self.pan_x,
            self.pan_y,
            self._fit_whole_bed,
        )

    def _line_blocks(
        self,
        segments: tuple[LineSegment3D, ...],
        parameters: tuple[float, float, float],
        context: _ProjectionContext,
        *,
        maximum_lines: int | None = None,
    ) -> _LineBlocks:
        if not segments:
            return ()
        if self.LINE_BLOCK_SIZE < 1:
            raise ValueError("LINE_BLOCK_SIZE must be at least one.")
        stride = 1
        if maximum_lines is not None:
            if maximum_lines < 1:
                raise ValueError("maximum_lines must be at least one.")
            stride = max(1, math.ceil(len(segments) / maximum_lines))
        blocks: list[_LineBlock] = []
        current: list[QLineF] = []
        for index in range(0, len(segments), stride):
            segment = segments[index]
            current.append(
                QLineF(
                    self._project(segment.start, parameters, context),
                    self._project(segment.end, parameters, context),
                )
            )
            if len(current) == self.LINE_BLOCK_SIZE:
                blocks.append(tuple(current))
                current = []
        if current:
            blocks.append(tuple(current))
        return tuple(blocks)

    def _prepare_line_frame(self) -> _PreparedLineFrame:
        scene = self.scene
        if scene is None:
            raise RuntimeError("A preview scene is required to prepare line blocks.")
        key = self._frame_key(scene)
        prepared = self._prepared_frame
        if prepared is not None and prepared.key == key:
            return prepared

        context = self._projection_context()
        parameters = self._fit_parameters(context)
        bed = scene.bed_bounds
        bed_points = (
            Point3D(bed.minimum_x_mm, bed.minimum_y_mm, 0.0),
            Point3D(bed.maximum_x_mm, bed.minimum_y_mm, 0.0),
            Point3D(bed.maximum_x_mm, bed.maximum_y_mm, 0.0),
            Point3D(bed.minimum_x_mm, bed.maximum_y_mm, 0.0),
        )
        bed_segments = tuple(
            LineSegment3D(point, bed_points[(index + 1) % 4])
            for index, point in enumerate(bed_points)
        )
        prepared = _PreparedLineFrame(
            key=key,
            bed_blocks=self._line_blocks(bed_segments, parameters, context),
            object_blocks=self._line_blocks(
                scene.object_segments,
                parameters,
                context,
                maximum_lines=self.MAXIMUM_OBJECT_DRAW_LINES,
            ),
            tower_blocks=self._line_blocks(
                scene.tower_segments,
                parameters,
                context,
            ),
        )
        self._prepared_frame = prepared
        return prepared

    @staticmethod
    def _draw_line_blocks(painter: QPainter, blocks: _LineBlocks) -> None:
        for block in blocks:
            try:
                painter.drawLines(block)
            except (OverflowError, TypeError):
                # Compatibility fallback for Qt bindings that reject a
                # sequence overload despite supporting individual QLineF.
                for line in block:
                    painter.drawLine(line)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#171a20"))
        scene = self.scene
        if scene is None:
            painter.setPen(QColor("#aeb7c5"))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "Noch keine Vorschau erstellt",
            )
            return
        prepared = self._prepare_line_frame()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor(self.BED_COLOR), 1.3))
        self._draw_line_blocks(painter, prepared.bed_blocks)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(QPen(QColor(self.OBJECT_COLOR), 1.0))
        self._draw_line_blocks(painter, prepared.object_blocks)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor(self.TOWER_COLOR), 1.5))
        self._draw_line_blocks(painter, prepared.tower_blocks)
        painter.setPen(QColor("#d9e0ea"))
        painter.drawText(
            12,
            22,
            f"Objekt: {scene.displayed_segment_count:,} / "
            f"{scene.source_segment_count:,} Segmente · "
            f"Turmhöhe: {scene.tower_height_mm:.2f} mm",
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._last_mouse = event.position().toPoint()
        self._drag_button = event.button()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._last_mouse is None:
            return
        current = event.position().toPoint()
        delta = current - self._last_mouse
        self._last_mouse = current
        if self._drag_button == Qt.MouseButton.LeftButton:
            self.yaw_deg -= delta.x() * 0.45
            self.pitch_deg = max(
                -89.0,
                min(89.0, self.pitch_deg + delta.y() * 0.35),
            )
        else:
            self.pan_x += delta.x()
            self.pan_y += delta.y()
        self._emit_camera()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._last_mouse = None
        self._drag_button = Qt.MouseButton.NoButton
        event.accept()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        self.zoom = max(0.05, min(50.0, self.zoom * factor))
        self._emit_camera()
        event.accept()
