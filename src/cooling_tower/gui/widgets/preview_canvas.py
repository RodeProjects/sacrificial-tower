from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import QWidget

from cooling_tower.preview import Point3D, PreviewScene


class PreviewCanvas(QWidget):
    """Small software-rendered 3D view without an external OpenGL runtime."""

    camera_changed = Signal(object)
    BED_COLOR = "#667080"
    OBJECT_COLOR = "#67b7c7"
    TOWER_COLOR = "#ff9e4f"
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

    def set_scene(self, scene: PreviewScene | None) -> None:
        self.scene = scene
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

    def _raw_project(self, point: Point3D) -> tuple[float, float]:
        scene = self.scene
        if scene is None:
            return point.x, -point.z
        bed = scene.bed_bounds
        center_x = (bed.minimum_x_mm + bed.maximum_x_mm) / 2.0
        center_y = (bed.minimum_y_mm + bed.maximum_y_mm) / 2.0
        x = point.x - center_x
        y = point.y - center_y
        yaw = math.radians(self.yaw_deg)
        pitch = math.radians(self.pitch_deg)
        rotated_x = math.cos(yaw) * x - math.sin(yaw) * y
        rotated_y = math.sin(yaw) * x + math.cos(yaw) * y
        projected_y = math.cos(pitch) * point.z - math.sin(pitch) * rotated_y
        return rotated_x, -projected_y

    def _fit_parameters(self) -> tuple[float, float, float]:
        scene = self.scene
        if scene is None:
            return 1.0, self.width() / 2.0, self.height() / 2.0
        if self._fit_whole_bed:
            bed = scene.bed_bounds
            z_max = max(1.0, scene.tower_height_mm)
            fit_points = tuple(
                Point3D(x, y, z)
                for x in (bed.minimum_x_mm, bed.maximum_x_mm)
                for y in (bed.minimum_y_mm, bed.maximum_y_mm)
                for z in (0.0, z_max)
            )
        else:
            segments = (*scene.object_segments, *scene.tower_segments)
            fit_points = tuple(
                point
                for segment in segments
                for point in (segment.start, segment.end)
            )
            if not fit_points:
                bed = scene.bed_bounds
                fit_points = (
                    Point3D(bed.minimum_x_mm, bed.minimum_y_mm, 0.0),
                    Point3D(bed.maximum_x_mm, bed.maximum_y_mm, 1.0),
                )
        projected = tuple(self._raw_project(point) for point in fit_points)
        minimum_x = min(item[0] for item in projected)
        maximum_x = max(item[0] for item in projected)
        minimum_y = min(item[1] for item in projected)
        maximum_y = max(item[1] for item in projected)
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
    ) -> QPointF:
        raw_x, raw_y = self._raw_project(point)
        scale, offset_x, offset_y = parameters
        return QPointF(raw_x * scale + offset_x, raw_y * scale + offset_y)

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
        parameters = self._fit_parameters()
        bed = scene.bed_bounds
        bed_points = (
            Point3D(bed.minimum_x_mm, bed.minimum_y_mm, 0.0),
            Point3D(bed.maximum_x_mm, bed.minimum_y_mm, 0.0),
            Point3D(bed.maximum_x_mm, bed.maximum_y_mm, 0.0),
            Point3D(bed.minimum_x_mm, bed.maximum_y_mm, 0.0),
        )
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor(self.BED_COLOR), 1.3))
        for index, point in enumerate(bed_points):
            painter.drawLine(
                self._project(point, parameters),
                self._project(bed_points[(index + 1) % 4], parameters),
            )

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(QPen(QColor(self.OBJECT_COLOR), 1.0))
        object_segments = scene.object_segments
        stride = max(1, math.ceil(len(object_segments) / 32_000))
        for segment in object_segments[::stride]:
            painter.drawLine(
                self._project(segment.start, parameters),
                self._project(segment.end, parameters),
            )

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor(self.TOWER_COLOR), 1.5))
        for segment in scene.tower_segments:
            painter.drawLine(
                self._project(segment.start, parameters),
                self._project(segment.end, parameters),
            )
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
