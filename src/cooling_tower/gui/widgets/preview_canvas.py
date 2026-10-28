from __future__ import annotations

import math
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass, replace
from itertools import chain
from pathlib import Path

from PySide6.QtCore import QLineF, QPoint, QPointF, QSize, QTimer, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QIcon,
    QMouseEvent,
    QMoveEvent,
    QPainter,
    QPen,
    QPixmap,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import QToolButton, QWidget

from cooling_tower.preview import LineSegment3D, Point3D, PreviewScene
from cooling_tower.gui.design_tokens import PREVIEW_SEAM_COLOR
from cooling_tower.gui.widgets.preview_busy_overlay import PreviewBusyOverlay
from cooling_tower.gui.widgets.preview_layer_context import LowerLayerFrames, layer_context_colour
from cooling_tower.gui.widgets.preview_projection import LineProjectionCache


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
    brim_blocks: _LineBlocks
    wait_travel_blocks: _LineBlocks
    tower_travel_blocks: _LineBlocks
    wait_position: QPointF | None
    brim_back_blocks: _LineBlocks = ()
    brim_front_blocks: _LineBlocks = ()
    lower_layers: QPixmap | None = None
    lower_brim_front_blocks: _LineBlocks = ()
    seam_blocks: _LineBlocks = ()

    @property
    def travel_blocks(self) -> _LineBlocks:
        return self.wait_travel_blocks + self.tower_travel_blocks


class PreviewCanvas(QWidget):
    """Small software-rendered 3D view without an external OpenGL runtime."""

    camera_changed = Signal(object)
    navigation_enabled_changed = Signal(bool)
    layer_highlight_cleared = Signal()
    BED_COLOR = "#667080"
    OBJECT_COLOR = "#67b7c7"
    TOWER_COLOR = "#ff9e4f"
    BRIM_COLOR = "#4979b5"
    WAIT_POSITION_COLOR = "#ffe48a"
    WAIT_TRAVEL_COLOR = "#bc98f4"
    TOWER_TRAVEL_COLOR = "#38489b"
    SEAM_COLOR = PREVIEW_SEAM_COLOR
    X_AXIS_COLOR = "#f07575"
    Y_AXIS_COLOR = "#75d18c"
    Z_AXIS_COLOR = "#75a9f0"
    MAXIMUM_OBJECT_DRAW_LINES = 32_000
    LINE_BLOCK_SIZE = 4_096
    # Ein Mausradschritt Abstand: gleicher Faktor wie die interaktive
    # Radsteuerung, sowohl initial als auch über „Seitenansicht“.
    SIDE_VIEW_ZOOM = 1.0 / 1.15
    RESIZE_RENDER_DELAY_MS = 180

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("previewCanvas")
        self.setMinimumSize(520, 420)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.scene: PreviewScene | None = None
        self._seam_segments = ()
        self.yaw_deg = -38.0
        self.pitch_deg = 28.0
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self._last_mouse: QPoint | None = None
        self._drag_button = Qt.MouseButton.NoButton
        self._navigation_enabled = False
        self._navigation_default = False
        self._rotation_drag_inverted = False
        self._layer_context_enabled = False
        self._layer_colours_highlight = True
        self._layer_selection_persistent = False
        self._cumulative_travel = False
        self._all_travel_visible = False
        self._all_travel_blocks = OrderedDict()
        self._lower_layer_frames = self._lower_layer_key = None
        self._lower_brim_front_source = ((), ())
        self._lower_brim_front_range = (math.inf, -math.inf)
        self._separated_yaw = None
        self._fit_whole_bed = False
        self._wait_position_visible = True
        self._wait_travel_visible = False
        self._tower_travel_visible = False
        self._layer_z = None
        self._travel_layer_z = None
        self._fit_cache_key = self._fit_cache_value = None
        self._fit_bounds_key = self._fit_bounds = None
        self._layer_index = OrderedDict()
        self._line_projection = LineProjectionCache()
        self._prepared_frame: _PreparedLineFrame | None = None
        self._normal_prepared: _PreparedLineFrame | None = None
        self._rendered_frame: QPixmap | None = None
        self._rendered_frame_key: tuple[object, ...] | None = None
        self._resize_render_timer = QTimer(self)
        self._resize_render_timer.setSingleShot(True)
        self._resize_render_timer.setInterval(self.RESIZE_RENDER_DELAY_MS)
        self._resize_render_timer.timeout.connect(self._finish_deferred_resize)

        asset_root = Path(__file__).resolve().parents[1] / "assets"
        self.navigation_toggle = QToolButton(self)
        self.navigation_toggle.setObjectName("previewNavigationToggle")
        self.navigation_toggle.setCheckable(True)
        self.navigation_toggle.setAutoRaise(False)
        self.navigation_toggle.setFixedSize(34, 34)
        self.navigation_toggle.setIconSize(QSize(20, 20))
        self.navigation_toggle.setIcon(
            QIcon(str(asset_root / "preview_navigation_locked.svg"))
        )
        self.navigation_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.navigation_toggle.toggled.connect(self.set_navigation_enabled)
        self.navigation_toggle.hide()
        self.navigation_status_label = QToolButton(self)
        self.navigation_status_label.setObjectName("previewNavigationStatus")
        self.navigation_status_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.navigation_status_label.clicked.connect(
            lambda: self.set_navigation_enabled(not self.navigation_enabled)
        )
        self.navigation_status_label.setMinimumHeight(30)
        self.navigation_status_label.hide()
        self._navigation_overlay_parent: QWidget = self
        self._navigation_upward_offset = 0
        self.set_navigation_enabled(False)
        self.busy_overlay = PreviewBusyOverlay(self)

    def set_busy(self, active, *, percent=0, step=""):
        self.busy_overlay.set_busy(active, percent=percent, step=step, title="G-Code und Vorschau werden erzeugt")

    def set_navigation_overlay_parent(
        self, parent: QWidget, *, upward_offset: int = 0
    ) -> None:
        """Allow navigation controls to straddle the canvas header safely."""

        self._navigation_overlay_parent = parent
        self._navigation_upward_offset = max(0, upward_offset)
        self.navigation_toggle.setParent(parent)
        self.navigation_status_label.setParent(parent)
        self._position_navigation_toggle()
        self.navigation_toggle.raise_()
        self.navigation_status_label.raise_()

    def set_scene(
        self,
        scene: PreviewScene | None,
        *,
        preserve_view: bool = False,
    ) -> None:
        # Each host mode chooses whether newly generated previews start with
        # navigation enabled; existing automatic previews retain their default.
        self.set_navigation_enabled(self._navigation_default)
        self.scene = scene
        self._seam_segments = tuple(LineSegment3D(point, point) for point in scene.seam_points) if scene else ()
        self._lower_layer_frames = self._lower_layer_key = None
        self._separated_yaw = None
        self._fit_cache_key = None
        self._fit_bounds_key = self._fit_bounds = None
        self._layer_index.clear()
        self._line_projection.clear()
        self._all_travel_blocks.clear()
        self._layer_z = None
        self._travel_layer_z = None
        self._prepared_frame = None
        self._normal_prepared = None
        self._invalidate_rendered_frame()
        if not preserve_view:
            self.fit_objects(emit=False)
        has_scene = scene is not None
        self.navigation_toggle.setVisible(has_scene)
        self.navigation_status_label.setVisible(has_scene)
        self._position_navigation_toggle()
        self.navigation_toggle.raise_()
        self.navigation_status_label.raise_()
        self.update()

    @property
    def navigation_enabled(self) -> bool:
        return self._navigation_enabled

    def set_navigation_default(self, enabled):
        self._navigation_default = bool(enabled)
        self.set_navigation_enabled(enabled)

    def set_rotation_drag_inverted(self, inverted):
        """Choose the drag sense for a preview's camera orientation."""
        self._rotation_drag_inverted = bool(inverted)

    def set_layer_context_enabled(self, enabled):
        self._layer_context_enabled = bool(enabled)
        self._lower_layer_frames = self._lower_layer_key = None
        self._prepared_frame = None
        self._normal_prepared = None
        self._invalidate_rendered_frame()
        self.update()

    def set_layer_selection_persistent(self, enabled):
        self._layer_selection_persistent = bool(enabled)

    def clear_layer_highlight(self, *, force=False):
        if self._layer_selection_persistent and not force:
            return
        if self._layer_context_enabled and self._layer_z is not None:
            self.set_layer_height(None)
            self.layer_highlight_cleared.emit()

    def set_navigation_enabled(self, enabled: bool) -> None:
        """Enable deliberate mouse navigation while keeping page scrolling safe."""

        self.clear_layer_highlight()
        enabled = bool(enabled)
        changed = enabled != self._navigation_enabled
        self._navigation_enabled = enabled
        if self.navigation_toggle.isChecked() != enabled:
            self.navigation_toggle.blockSignals(True)
            self.navigation_toggle.setChecked(enabled)
            self.navigation_toggle.blockSignals(False)

        asset_root = Path(__file__).resolve().parents[1] / "assets"
        icon_name = (
            "preview_navigation_enabled.svg"
            if enabled
            else "preview_navigation_locked.svg"
        )
        self.navigation_toggle.setIcon(QIcon(str(asset_root / icon_name)))
        self.navigation_toggle.setProperty("navigationEnabled", enabled)
        if enabled:
            hint = (
                "Navigation aktiviert – ziehen zum Drehen oder Verschieben, "
                "Mausrad zum Zoomen. Klicken zum Deaktivieren."
            )
            accessible_name = "Vorschau-Navigation deaktivieren"
            status_text = "Navigation aktiviert"
            status_state = "enabled"
        else:
            hint = (
                "Navigation deaktiviert – die Vorschau reagiert nicht auf "
                "Ziehen oder Scrollen. Klicken zum Aktivieren."
            )
            accessible_name = "Vorschau-Navigation aktivieren"
            status_text = "Navigation deaktiviert"
            status_state = "disabled"
        self.navigation_toggle.setToolTip(hint)
        self.navigation_toggle.setAccessibleName(accessible_name)
        self.navigation_toggle.setAccessibleDescription(hint)
        self.navigation_status_label.setText(status_text)
        self.navigation_status_label.setToolTip(hint)
        self.navigation_status_label.setAccessibleName(accessible_name)
        self.navigation_status_label.setProperty("state", status_state)
        style = self.navigation_toggle.style()
        style.unpolish(self.navigation_toggle)
        style.polish(self.navigation_toggle)
        status_style = self.navigation_status_label.style()
        status_style.unpolish(self.navigation_status_label)
        status_style.polish(self.navigation_status_label)
        self.navigation_status_label.adjustSize()
        self._position_navigation_toggle()
        if not enabled:
            self._last_mouse = None
            self._drag_button = Qt.MouseButton.NoButton
        if changed:
            self.navigation_enabled_changed.emit(enabled)

    def _position_navigation_toggle(self) -> None:
        margin = 10
        canvas_origin = self.mapTo(
            self._navigation_overlay_parent, QPoint(0, 0)
        )
        x = canvas_origin.x() + margin
        y = canvas_origin.y() + margin - self._navigation_upward_offset
        self.navigation_toggle.move(x, y)
        self.navigation_status_label.move(
            self.navigation_toggle.geometry().right() + 7,
            y
            + max(
                0,
                (
                    self.navigation_toggle.height()
                    - self.navigation_status_label.height()
                )
                // 2,
            ),
        )

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
        self._invalidate_rendered_frame()
        self.update()

    def reset_camera(self) -> None:
        self.three_quarter_view()

    def three_quarter_view(self) -> None:
        """Show the objects in the default perspective inspection view."""

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
        # The side view follows the object/tower placement. Its front view
        # must therefore be orthogonal to that same reference direction.
        self.yaw_deg = self._side_by_side_yaw_deg() - 90.0
        self.pitch_deg = 0.0
        self.fit_objects(emit=False)
        self._emit_camera()

    def side_view(self) -> None:
        self.yaw_deg = self._side_by_side_yaw_deg()
        self.pitch_deg = 0.0
        self.fit_objects(emit=False)
        # Zwei Mausradstufen weiter heraus als die automatische Anpassung.
        # So bleibt in der initialen Seitenansicht sichtbar Luft um hohe Türme.
        self.zoom = self.SIDE_VIEW_ZOOM
        self._emit_camera()

    @staticmethod
    def _xy_bounds(
        segments: Iterable[LineSegment3D],
    ) -> tuple[float, float, float, float] | None:
        minimum_x = math.inf
        maximum_x = -math.inf
        minimum_y = math.inf
        maximum_y = -math.inf
        found = False
        for segment in segments:
            for point in (segment.start, segment.end):
                minimum_x = min(minimum_x, point.x)
                maximum_x = max(maximum_x, point.x)
                minimum_y = min(minimum_y, point.y)
                maximum_y = max(maximum_y, point.y)
                found = True
        if not found:
            return None
        return minimum_x, maximum_x, minimum_y, maximum_y

    @staticmethod
    def _interval_gap(
        first_minimum: float,
        first_maximum: float,
        second_minimum: float,
        second_maximum: float,
    ) -> float:
        return max(
            0.0,
            second_minimum - first_maximum,
            first_minimum - second_maximum,
        )

    def _side_by_side_yaw_deg(self) -> float:
        """Choose a horizontal projection that separates object and tower."""

        scene = self.scene
        if scene is None:
            return 90.0
        object_bounds = self._xy_bounds(scene.object_segments)
        tower_bounds = self._xy_bounds(chain(scene.tower_segments, scene.brim_segments))
        if object_bounds is None or tower_bounds is None:
            return 90.0

        object_min_x, object_max_x, object_min_y, object_max_y = object_bounds
        object_center_x = (object_min_x + object_max_x) / 2.0
        object_center_y = (object_min_y + object_max_y) / 2.0
        tower_center_x, tower_center_y = scene.tower_center_xy_mm
        closest_object_x = min(
            max(tower_center_x, object_min_x),
            object_max_x,
        )
        closest_object_y = min(
            max(tower_center_y, object_min_y),
            object_max_y,
        )

        def yaw_for_vector(delta_x: float, delta_y: float) -> float | None:
            if math.hypot(delta_x, delta_y) <= 1e-9:
                return None
            return math.degrees(math.atan2(-delta_y, delta_x))

        candidates = [0.0, -90.0]
        nearest_yaw = yaw_for_vector(
            tower_center_x - closest_object_x,
            tower_center_y - closest_object_y,
        )
        center_yaw = yaw_for_vector(
            tower_center_x - object_center_x,
            tower_center_y - object_center_y,
        )
        for candidate in (nearest_yaw, center_yaw):
            if candidate is not None and all(
                abs(candidate - existing) > 1e-9
                for existing in candidates
            ):
                candidates.append(candidate)

        def projected_interval(
            segments: Iterable[LineSegment3D],
            yaw_deg: float,
        ) -> tuple[float, float]:
            yaw = math.radians(yaw_deg)
            cosine = math.cos(yaw)
            sine = math.sin(yaw)
            values = (
                cosine * point.x - sine * point.y
                for segment in segments
                for point in (segment.start, segment.end)
            )
            first = next(values)
            minimum = maximum = first
            for value in values:
                minimum = min(minimum, value)
                maximum = max(maximum, value)
            return minimum, maximum

        def separation_score(yaw_deg: float) -> float:
            object_minimum, object_maximum = projected_interval(
                scene.object_segments,
                yaw_deg,
            )
            tower_minimum, tower_maximum = projected_interval(
                chain(scene.tower_segments, scene.brim_segments),
                yaw_deg,
            )
            gap = self._interval_gap(
                object_minimum,
                object_maximum,
                tower_minimum,
                tower_maximum,
            )
            if gap <= 0.0:
                overlap = min(object_maximum, tower_maximum) - max(
                    object_minimum,
                    tower_minimum,
                )
                gap = -max(0.0, overlap)
            total_span = max(object_maximum, tower_maximum) - min(
                object_minimum,
                tower_minimum,
            )
            return gap / max(total_span, 1e-9)

        # Keep the exported 3MF's X/Y axes in the normal side view whenever
        # either bed axis separates the two objects. A diagonal camera angle
        # can make the same unchanged STL appear rotated in the preview.
        # Only use an oblique view for corner placements where both cardinal
        # projections overlap.
        cardinal_yaws = (0.0, -90.0)
        selected_yaw = max(cardinal_yaws, key=separation_score)
        if separation_score(selected_yaw) <= 0.0:
            selected_yaw = max(candidates, key=separation_score)

        # A projection and the same projection rotated by 180 degrees have an
        # identical separation score, but reverse the visual order. Keep the
        # source object predictably on the left and the generated tower on the
        # right in both the initial and explicit side views.
        object_interval = projected_interval(
            scene.object_segments,
            selected_yaw,
        )
        tower_interval = projected_interval(
            chain(scene.tower_segments, scene.brim_segments),
            selected_yaw,
        )
        object_center = sum(object_interval) / 2.0
        tower_center = sum(tower_interval) / 2.0
        if object_center > tower_center:
            selected_yaw += 180.0
        return (selected_yaw + 180.0) % 360.0 - 180.0

    def separated_yaw(self):
        """Maximize the horizontal gap using exact projected footprint extrema."""
        if self._separated_yaw is not None:
            return self._separated_yaw
        scene = self.scene
        if scene is None or not scene.object_segments or not scene.tower_segments:
            return -38.0

        def hull(segments):
            points = sorted({(p.x, p.y) for s in segments for p in (s.start, s.end)})
            if len(points) <= 2:
                return points
            def cross(a, b, c):
                return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
            halves = []
            for ordered in (points, reversed(points)):
                half = []
                for point in ordered:
                    while len(half) >= 2 and cross(half[-2], half[-1], point) <= 0:
                        half.pop()
                    half.append(point)
                halves.extend(half[:-1])
            return halves

        model = hull(scene.object_segments)
        tower = hull(chain(scene.tower_segments, scene.brim_segments))
        def interval(points, angle):
            cosine, sine = math.cos(math.radians(angle)), math.sin(math.radians(angle))
            values = [cosine*x-sine*y for x, y in points]
            return min(values), max(values)
        def score(angle):
            a, b = interval(model, angle), interval(tower, angle)
            gap = max(b[0]-a[1], a[0]-b[1])
            span = max(a[1], b[1])-min(a[0], b[0])
            return gap/max(1e-9, span)
        coarse = max(range(0, 180, 3), key=score)
        best = max((coarse-3+i*.25 for i in range(25)), key=score)
        if sum(interval(model, best)) > sum(interval(tower, best)):
            best += 180
        self._separated_yaw = (best+180) % 360-180
        return self._separated_yaw

    def top_view(self) -> None:
        """Look vertically down onto the print bed and fitted objects."""

        self.yaw_deg = 0.0
        # Keep one degree of distance from the projection singularity while
        # remaining visually indistinguishable from a vertical top-down view.
        self.pitch_deg = 89.0
        self.fit_objects(emit=False)
        self.zoom = 1.0 / 1.2
        self._emit_camera()

    def _emit_camera(self) -> None:
        self.clear_layer_highlight()
        self._invalidate_rendered_frame()
        self.update()
        self.camera_changed.emit(self.camera_state())

    def _invalidate_rendered_frame(self) -> None:
        self._resize_render_timer.stop()
        self._rendered_frame = None
        self._rendered_frame_key = None

    def _finish_deferred_resize(self) -> None:
        """Reproject the scene once after continuous widget resizing ends."""

        self._rendered_frame = None
        self._rendered_frame_key = None
        self.update()

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
        cache_key = (id(scene), self.width(), self.height(), context, self._fit_whole_bed,
            self.zoom, self.pan_x, self.pan_y)
        if cache_key == self._fit_cache_key:
            return self._fit_cache_value
        bounds_key = (id(scene), context, self._fit_whole_bed)
        if bounds_key == self._fit_bounds_key:
            bounds = self._fit_bounds
        else:
            bounds = self._projection_bounds(scene, context)
            self._fit_bounds_key, self._fit_bounds = bounds_key, bounds
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
        self._fit_cache_key = cache_key
        self._fit_cache_value = scale, offset_x, offset_y
        return self._fit_cache_value

    def _projection_bounds(
        self, scene: PreviewScene, context: _ProjectionContext,
    ) -> tuple[float, float, float, float]:
        """Exact camera-space bounds, independent of viewport, zoom and pan."""
        wait_top = (Point3D(*scene.wait_position_xy_mm,
            (scene.object_height_mm or scene.tower_height_mm)+scene.wait_height_offset_mm),
            ) if scene.wait_position_xy_mm is not None else ()
        if self._fit_whole_bed:
            bed = scene.bed_bounds
            z_max = max(1.0, scene.tower_height_mm,
                scene.object_height_mm or 0.0, *(point.z for point in chain(scene.wait_points, wait_top)))
            fit_points: Iterable[Point3D] = (
                Point3D(x, y, z)
                for x in (bed.minimum_x_mm, bed.maximum_x_mm)
                for y in (bed.minimum_y_mm, bed.maximum_y_mm)
                for z in (0.0, z_max)
            )
        else:
            segment_points = (
                point
                for segment in chain(
                    scene.object_segments,
                    scene.tower_segments,
                    scene.brim_segments,
                    scene.travel_segments or chain(scene.wait_travel_segments, scene.tower_travel_segments),
                )
                for point in (segment.start, segment.end)
            )
            # Visibility changes must not move the objects or the camera. Keep
            # the independent wait marker in the same fixed projection bounds.
            fit_points = chain(segment_points, scene.wait_points, wait_top)
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
        assert bounds is not None  # The fallback above always has points.
        return bounds

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
            self.devicePixelRatioF(),
            self.yaw_deg,
            self.pitch_deg,
            self.zoom,
            self.pan_x,
            self.pan_y,
            self._fit_whole_bed,
            self._wait_position_visible,
            self._wait_travel_visible,
            self._tower_travel_visible,
            self._layer_z,
            self._cumulative_travel,
            self._all_travel_visible,
            self._travel_layer_z,
            self._layer_colours_highlight,
        )

    def set_layer_height(self, z):
        """Filter one planar deposition layer without changing camera or fitting."""
        self._layer_z = z
        self._layer_colours_highlight = True
        self._invalidate_rendered_frame()
        self.update()

    def reset_layer_colours(self):
        """Restore visible layer colours without moving the camera or cutoff."""
        if self._layer_z is not None and self._layer_colours_highlight:
            self.set_layer_transparency_enabled(False)

    def set_layer_transparency_enabled(self, enabled):
        """Toggle the existing subdued lower-layer colours and opacity."""
        if self._layer_colours_highlight != bool(enabled):
            self._layer_colours_highlight = bool(enabled)
            self._invalidate_rendered_frame()
            self.update()

    def set_travel_layer_height(self, z):
        """Keep the chosen route layer even when the model has normal colours."""
        self._travel_layer_z = z
        self._invalidate_rendered_frame()
        self.update()

    def _layer_segments(self, segments, indices=(), *, height=None, through=False):
        height = self._layer_z if height is None else height
        if height is None:
            return segments
        key = id(segments), id(indices)
        entry = self._layer_index.get(key)
        if entry is None:
            buckets = {}
            use_indices = bool(indices) and self.scene is not None and len(indices) == len(segments)
            for number, segment in enumerate(segments):
                if use_indices:
                    index = indices[number]
                    if index >= len(self.scene.layer_z_mm):
                        continue
                    z = self.scene.layer_z_mm[index]
                else:
                    z = segment.end.z
                buckets.setdefault(math.floor(z*1000), []).append((number, segment, z))
            entry = segments, indices, buckets
            self._layer_index[key] = entry
            while len(self._layer_index) > 8:
                self._layer_index.popitem(last=False)
        self._layer_index.move_to_end(key)
        bucket = math.floor(height*1000)
        if through:
            return tuple(segment for value in sorted(entry[2]) if value <= bucket+1
                for _number, segment, z in entry[2][value] if z <= height+.001)
        nearby = chain.from_iterable(entry[2].get(value, ()) for value in (bucket-1, bucket, bucket+1))
        return tuple(segment for _number, segment, z in sorted(nearby) if abs(z-height) < .001)

    def _travel_segments(self, segments, indices):
        if self._all_travel_visible:
            # The context frame already contains routes below the selection.
            return self._layer_segments(segments, indices,
                through=not self._layer_context_enabled)
        return self._layer_segments(segments, indices, height=self._travel_layer_z,
            through=self._cumulative_travel and self._layer_z is None)

    def _travel_line_blocks(self, segments, indices, parameters, context):
        if not self._all_travel_visible or self._layer_z is not None:
            return self._line_blocks(self._travel_segments(segments, indices), parameters, context,
                maximum_lines=self.MAXIMUM_OBJECT_DRAW_LINES)
        # Complete route geometry is reusable when no layer cutoff is active.
        key = (id(self.scene), id(segments), parameters, context)
        if key not in self._all_travel_blocks:
            self._all_travel_blocks[key] = self._line_blocks(segments, parameters, context,
                maximum_lines=self.MAXIMUM_OBJECT_DRAW_LINES)
        self._all_travel_blocks.move_to_end(key)
        while len(self._all_travel_blocks) > 2:
            self._all_travel_blocks.popitem(last=False)
        return self._all_travel_blocks[key]

    def set_travel_visible(self, visible: bool) -> None:
        """Toggle both route groups while preserving the independent marker."""
        self._wait_travel_visible = self._tower_travel_visible = bool(visible)
        self._invalidate_rendered_frame()
        self.update()

    def set_wait_position_visible(self, visible: bool) -> None:
        self._wait_position_visible = bool(visible)
        self._invalidate_rendered_frame()
        self.update()

    def set_wait_travel_visible(self, visible: bool) -> None:
        self._wait_travel_visible = bool(visible)
        self._invalidate_rendered_frame()
        self.update()

    def set_tower_travel_visible(self, visible: bool) -> None:
        self._tower_travel_visible = bool(visible)
        self._invalidate_rendered_frame()
        self.update()

    def set_cumulative_travel_visible(self, visible: bool) -> None:
        self._cumulative_travel = bool(visible)
        self._invalidate_rendered_frame()
        self.update()

    def set_all_travel_visible(self, visible: bool) -> None:
        """Show enabled travel groups up to the selected layer, or all without a cutoff."""
        self._all_travel_visible = bool(visible)
        self._invalidate_rendered_frame()
        self.update()

    def _wait_marker_position(self) -> Point3D | None:
        scene = self.scene
        if scene is None or scene.wait_position_xy_mm is None:
            return None
        if self._layer_z is not None:
            for point, index in zip(scene.wait_points, scene.wait_point_layer_indices):
                if index < len(scene.layer_z_mm) and abs(scene.layer_z_mm[index] - self._layer_z) < .001:
                    return Point3D(*scene.wait_position_xy_mm, point.z)
            return Point3D(*scene.wait_position_xy_mm, self._layer_z + scene.wait_height_offset_mm)
        height = (scene.wait_points[-1].z if scene.wait_points else
            (scene.object_height_mm or scene.tower_height_mm) + scene.wait_height_offset_mm)
        return Point3D(*scene.wait_position_xy_mm, height)

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
        if len(range(0, len(segments), stride)) >= self._line_projection.MINIMUM_LINES:
            coordinates = self._line_projection.project(segments, stride, parameters, context)
            size = self.LINE_BLOCK_SIZE
            return tuple(
                tuple(QLineF(*row) for row in coordinates[start:start+size].tolist())
                for start in range(0, len(coordinates), size)
            )
        blocks: list[_LineBlock] = []
        current: list[QLineF] = []
        scale, offset_x, offset_y = parameters
        cx, cy = context.center_x, context.center_y
        cosine, sine = context.cosine_yaw, context.sine_yaw
        pitch_cosine, pitch_sine = context.cosine_pitch, context.sine_pitch
        for index in range(0, len(segments), stride):
            segment = segments[index]
            a, b = segment.start, segment.end
            ax, ay, bx, by = a.x-cx, a.y-cy, b.x-cx, b.y-cy
            # Preserve the projection's arithmetic and line order while
            # avoiding two temporary QPointF wrappers per displayed stroke.
            current.append(QLineF(
                (cosine*ax-sine*ay)*scale+offset_x,
                -(pitch_cosine*a.z-pitch_sine*(sine*ax+cosine*ay))*scale+offset_y,
                (cosine*bx-sine*by)*scale+offset_x,
                -(pitch_cosine*b.z-pitch_sine*(sine*bx+cosine*by))*scale+offset_y,
            ))
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
        if self._layer_context_enabled and self._layer_z is None and self._normal_prepared is not None and self._normal_prepared.key == key:
            self._prepared_frame = self._normal_prepared
            return self._prepared_frame

        context = self._projection_context()
        parameters = self._fit_parameters(context)
        bed = scene.bed_bounds
        bed_points = (
            Point3D(bed.minimum_x_mm, bed.minimum_y_mm, 0.0),
            Point3D(bed.maximum_x_mm, bed.minimum_y_mm, 0.0),
            Point3D(bed.maximum_x_mm, bed.maximum_y_mm, 0.0),
            Point3D(bed.minimum_x_mm, bed.maximum_y_mm, 0.0),
        )
        polygons = (
            (scene.bed_geometry.printable_polygon, *scene.bed_geometry.excluded_polygons)
            if scene.bed_geometry is not None else
            (tuple((point.x, point.y) for point in bed_points),)
        )
        bed_segments = tuple(
            LineSegment3D(Point3D(*point, 0), Point3D(*polygon[(index + 1) % len(polygon)], 0))
            for polygon in polygons for index, point in enumerate(polygon)
        )
        wait_position = self._wait_marker_position() if self._wait_position_visible else None
        # Older scenes may contain a single unclassified route list.
        tower_travel = scene.tower_travel_segments if (scene.wait_travel_segments or scene.tower_travel_segments) else scene.travel_segments
        brim = self._layer_segments(scene.brim_segments)
        brim_blocks = self._line_blocks(brim, parameters, context)
        back_brim, front_brim = self._brim_depth_groups(brim, brim_blocks, context)
        prepared = _PreparedLineFrame(
            key=key,
            seam_blocks=self._line_blocks(self._layer_segments(self._seam_segments), parameters, context),
            bed_blocks=self._line_blocks(bed_segments, parameters, context),
            object_blocks=self._line_blocks(
                self._layer_segments(scene.object_segments),
                parameters,
                context,
                maximum_lines=self.MAXIMUM_OBJECT_DRAW_LINES,
            ),
            tower_blocks=self._line_blocks(
                self._layer_segments(scene.tower_segments),
                parameters,
                context,
            ),
            brim_blocks=brim_blocks,
            brim_back_blocks=back_brim[1],
            brim_front_blocks=front_brim[1],
            wait_travel_blocks=(self._travel_line_blocks(scene.wait_travel_segments,
                scene.wait_travel_layer_indices, parameters, context) if self._wait_travel_visible else ()),
            tower_travel_blocks=(self._travel_line_blocks(tower_travel,
                scene.tower_travel_layer_indices, parameters, context) if self._tower_travel_visible else ()),
            wait_position=self._project(wait_position, parameters, context) if wait_position is not None else None,
        )
        if self._layer_context_enabled:
            layer_key = (id(scene), self.width(), self.height(), self.devicePixelRatioF(), context, parameters,
                self._cumulative_travel, self._all_travel_visible, self._wait_travel_visible,
                self._tower_travel_visible, self._layer_colours_highlight)
            if layer_key != self._lower_layer_key:
                full = self._layer_z is None
                sources = []
                for segments, blocks, color, width, maximum in (
                    (scene.object_segments, prepared.object_blocks, self.OBJECT_COLOR, 1.0, self.MAXIMUM_OBJECT_DRAW_LINES),
                    (scene.tower_segments, prepared.tower_blocks, self.TOWER_COLOR, 1.5, None)):
                    if not full:
                        blocks = self._line_blocks(segments, parameters, context, maximum_lines=maximum)
                    sources.append((segments, blocks, color, width, maximum))
                if self._seam_segments:
                    seam_blocks = prepared.seam_blocks if full else self._line_blocks(self._seam_segments, parameters, context)
                    sources.append((self._seam_segments, seam_blocks, self.SEAM_COLOR, 3, None,
                        (), True))
                if not full:
                    back_brim, front_brim = self._brim_depth_groups(scene.brim_segments,
                        self._line_blocks(scene.brim_segments, parameters, context), context)
                # The first-layer brim lies outside the tower's footprint.
                # Its far half belongs behind the tower, its near half in front.
                # The near brim must be drawn after all tower layers, including
                # layers added to an earlier raster checkpoint while scrubbing.
                sources.insert(1, (back_brim[0], back_brim[1], self.BRIM_COLOR, 1.3, None))
                self._lower_brim_front_source = front_brim
                heights = tuple(segment.end.z for segment in front_brim[0])
                self._lower_brim_front_range = (min(heights, default=math.inf), max(heights, default=-math.inf))
                if self._cumulative_travel or self._all_travel_visible:
                    for segments, indices, visible, color, full_blocks in (
                            (scene.wait_travel_segments, scene.wait_travel_layer_indices, self._wait_travel_visible,
                                self.WAIT_TRAVEL_COLOR, prepared.wait_travel_blocks),
                            (tower_travel, scene.tower_travel_layer_indices, self._tower_travel_visible,
                                self.TOWER_TRAVEL_COLOR, prepared.tower_travel_blocks)):
                        if visible:
                            complete = full and (self._all_travel_visible or self._travel_layer_z is None or not scene.layer_z_mm
                                or self._travel_layer_z >= scene.layer_z_mm[-1])
                            blocks = full_blocks if complete else self._line_blocks(segments, parameters, context,
                                maximum_lines=self.MAXIMUM_OBJECT_DRAW_LINES)
                            # Route heights include Z-hops. Their owning print
                            # layer, rather than endpoint Z, defines the cutoff.
                            heights = tuple(scene.layer_z_mm[i] if 0 <= i < len(scene.layer_z_mm) else math.inf
                                for i in indices) if len(indices) == len(segments) else ()
                            sources.append((segments, blocks, color, 1.0, self.MAXIMUM_OBJECT_DRAW_LINES, heights))
                self._lower_layer_frames = LowerLayerFrames(self.width(), self.height(), self.devicePixelRatioF(), sources,
                    subdued=self._layer_colours_highlight)
                self._lower_layer_key = layer_key
            if self._layer_z is not None:
                first, last = self._lower_brim_front_range
                front_segments, front_blocks = self._lower_brim_front_source
                cutoff = self._layer_z-.001
                if first >= cutoff:
                    front_blocks = ()
                elif last >= cutoff:
                    lines = tuple(line for segment, line in zip(front_segments, chain.from_iterable(front_blocks))
                        if segment.end.z < cutoff)
                    front_blocks = tuple(lines[i:i+self.LINE_BLOCK_SIZE] for i in range(0, len(lines), self.LINE_BLOCK_SIZE))
                prepared = replace(prepared, lower_layers=self._lower_layer_frames.before(self._layer_z),
                    lower_brim_front_blocks=front_blocks)
        self._prepared_frame = prepared
        if self._layer_context_enabled and self._layer_z is None:
            self._normal_prepared = prepared
        return prepared

    def _brim_depth_groups(self, segments, blocks, context):
        """Split at the camera's depth plane through the circular tower axis.

        The generated foot contracts above the brim. A brim outside that foot
        can overlap its silhouette only on the corresponding near/far side.
        This keeps occlusion correct with four batched draws, without sorting
        all tower strokes or issuing thousands of per-line painter calls.
        """
        cx, cy = self.scene.tower_center_xy_mm
        groups = (([], []), ([], []))  # far, near: world segments and projected lines
        for segment, line in zip(segments, chain.from_iterable(blocks)):
            a, b = segment.start, segment.end
            da = context.sine_yaw*(a.x-cx)+context.cosine_yaw*(a.y-cy)
            db = context.sine_yaw*(b.x-cx)+context.cosine_yaw*(b.y-cy)
            if da >= -1e-10 and db >= -1e-10:
                parts = ((0, segment, line),)
            elif da <= 1e-10 and db <= 1e-10:
                parts = ((1, segment, line),)
            else:
                t = da/(da-db)
                middle = Point3D(a.x+(b.x-a.x)*t, a.y+(b.y-a.y)*t, a.z+(b.z-a.z)*t)
                projected = line.pointAt(t)
                first = int(da < 0)
                parts = ((first, LineSegment3D(a, middle), QLineF(line.p1(), projected)),
                    (1-first, LineSegment3D(middle, b), QLineF(projected, line.p2())))
            for index, world, projected in parts:
                groups[index][0].append(world)
                groups[index][1].append(projected)
        return tuple((tuple(world), tuple(tuple(lines[i:i+self.LINE_BLOCK_SIZE])
            for i in range(0, len(lines), self.LINE_BLOCK_SIZE))) for world, lines in groups)

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
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                "Noch kein Kühlturm generiert.\nDie Vorschau erscheint nach der Generierung.",
            )
            return

        current_key = self._frame_key(scene)
        if (
            self._rendered_frame is not None
            and self._rendered_frame_key is not None
            and self._rendered_frame_key[0] == current_key[0]
            and self._rendered_frame_key[3:] == current_key[3:]
            and (
                self._rendered_frame_key == current_key
                or self._resize_render_timer.isActive()
            )
        ):
            painter.drawPixmap(self.rect(), self._rendered_frame)
            return

        pixel_ratio = max(1.0, self.devicePixelRatioF())
        frame = QPixmap(
            max(1, round(self.width() * pixel_ratio)),
            max(1, round(self.height() * pixel_ratio)),
        )
        frame.setDevicePixelRatio(pixel_ratio)
        frame.fill(QColor("#171a20"))
        frame_painter = QPainter(frame)
        prepared = self._prepare_line_frame()
        frame_painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        frame_painter.setPen(QPen(QColor(self.BED_COLOR), 1.3))
        self._draw_line_blocks(frame_painter, prepared.bed_blocks)
        if prepared.lower_layers is not None:
            frame_painter.save()
            frame_painter.setOpacity(.65 if self._layer_colours_highlight else 1.)
            frame_painter.drawPixmap(0, 0, prepared.lower_layers)
            frame_painter.restore()

        frame_painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        frame_painter.setPen(QPen(QColor(self.OBJECT_COLOR), 1.0))
        self._draw_line_blocks(frame_painter, prepared.object_blocks)

        frame_painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        frame_painter.setPen(QPen(QColor(self.BRIM_COLOR), 1.3))
        self._draw_line_blocks(frame_painter, prepared.brim_back_blocks)
        frame_painter.setPen(QPen(QColor(self.TOWER_COLOR), 1.5))
        self._draw_line_blocks(frame_painter, prepared.tower_blocks)
        frame_painter.setPen(QPen(QColor(self.BRIM_COLOR), 1.3))
        self._draw_line_blocks(frame_painter, prepared.brim_front_blocks)
        frame_painter.setPen(QPen(QColor(self.SEAM_COLOR), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for block in prepared.seam_blocks:
            frame_painter.drawPoints(tuple(line.p1() for line in block))
        if prepared.lower_brim_front_blocks:
            frame_painter.save()
            frame_painter.setOpacity(.65 if self._layer_colours_highlight else 1.)
            frame_painter.setPen(QPen(layer_context_colour(self.BRIM_COLOR, subdued=self._layer_colours_highlight), 1.3))
            self._draw_line_blocks(frame_painter, prepared.lower_brim_front_blocks)
            frame_painter.restore()
        for blocks, color in ((prepared.wait_travel_blocks, self.WAIT_TRAVEL_COLOR),
                (prepared.tower_travel_blocks, self.TOWER_TRAVEL_COLOR)):
            frame_painter.setPen(QPen(QColor(color), 1.0, Qt.PenStyle.DashLine))
            self._draw_line_blocks(frame_painter, blocks)
        if prepared.wait_position is not None:
            marker = prepared.wait_position
            frame_painter.setPen(QPen(QColor(self.WAIT_POSITION_COLOR), 2.0))
            frame_painter.drawEllipse(marker, 5, 5)
            frame_painter.drawText(marker + QPointF(9, -7), "Warten")
        if scene.bed_geometry is not None:
            context = self._projection_context()
            parameters = self._fit_parameters(context)
            origin = self._project(Point3D(0, 0, 0), parameters, context)
            length = min(30.0, (scene.bed_bounds.maximum_x_mm-scene.bed_bounds.minimum_x_mm) / 8)
            for label, color, endpoint in (("X+", self.X_AXIS_COLOR, Point3D(length, 0, 0)),
                    ("Y+", self.Y_AXIS_COLOR, Point3D(0, length, 0)),
                    ("Z+", self.Z_AXIS_COLOR, Point3D(0, 0, length))):
                point = self._project(endpoint, parameters, context)
                frame_painter.setPen(QPen(QColor(color), 1.5))
                frame_painter.drawLine(QLineF(origin, point))
                frame_painter.drawText(point + QPointF(4, -4), label)
        frame_painter.end()
        self._rendered_frame = frame
        self._rendered_frame_key = current_key
        painter.drawPixmap(0, 0, frame)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._normal_prepared = None
        self._position_navigation_toggle()
        self.navigation_toggle.raise_()
        self.navigation_status_label.raise_()
        if self.scene is not None and self._rendered_frame is not None:
            self._resize_render_timer.start()

    def moveEvent(self, event: QMoveEvent) -> None:  # noqa: N802
        super().moveEvent(event)
        self._position_navigation_toggle()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.clear_layer_highlight()
        if not self._navigation_enabled:
            event.ignore()
            return
        self._last_mouse = event.position().toPoint()
        self._drag_button = event.button()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self._navigation_enabled:
            event.ignore()
            return
        if self._last_mouse is None:
            event.ignore()
            return
        current = event.position().toPoint()
        delta = current - self._last_mouse
        self._last_mouse = current
        if self._drag_button == Qt.MouseButton.LeftButton:
            direction = -1 if self._rotation_drag_inverted else 1
            self.yaw_deg -= delta.x() * 0.45 * direction
            self.pitch_deg = max(
                -89.0,
                min(89.0, self.pitch_deg + delta.y() * 0.35 * direction),
            )
        else:
            self.pan_x += delta.x()
            self.pan_y += delta.y()
        self._emit_camera()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self._navigation_enabled:
            event.ignore()
            return
        self._last_mouse = None
        self._drag_button = Qt.MouseButton.NoButton
        event.accept()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        self.clear_layer_highlight()
        if not self._navigation_enabled:
            event.ignore()
            return
        delta = event.angleDelta().y()
        if not delta:
            event.accept()
            return
        old_zoom = self.zoom
        factor = 1.15 if delta > 0 else 1.0 / 1.15
        self.zoom = max(0.05, min(50.0, old_zoom * factor))
        ratio = self.zoom / old_zoom
        anchor = event.position()
        # Zoom about the current cursor position, including an existing pan.
        # Use the clamped ratio so reaching a zoom limit cannot shift the view.
        self.pan_x += (self.width() / 2.0 + self.pan_x - anchor.x()) * (ratio - 1.0)
        self.pan_y += (self.height() / 2.0 + self.pan_y - anchor.y()) * (ratio - 1.0)
        self._emit_camera()
        event.accept()
