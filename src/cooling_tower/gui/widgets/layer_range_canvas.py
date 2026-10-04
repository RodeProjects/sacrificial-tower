"""Side-view layer heatmap with layer-snapped range editing."""
from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
import math

import numpy as np

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QLabel, QWidget

from cooling_tower.models.layer_ranges import LayerRange


class LayerRangeCanvas(QWidget):
    range_committed = Signal(int, int, int)  # previous index (-1 = new), start, end
    selection_changed = Signal(int)
    remove_requested = Signal(int)
    rotation_changed = Signal(int)
    fit_available_changed = Signal(bool)
    OBJECT_COLOR = "#41a878"
    CRITICAL_COLOR = "#e5484d"
    BACKGROUND_COLOR = "#e6ecf2"
    BORDER_COLOR = "#9eafbf"
    SELECTION_COLOR = "#c6ddee"
    SELECTION_BORDER_COLOR = "#6f9fc4"
    SELECTION_TEXT_COLOR = "#245d88"
    JOIN_COLOR = "#c9e8d6"
    JOIN_BORDER_COLOR = "#4f9b73"
    JOIN_TEXT_COLOR = "#176b45"

    def __init__(self, layers, segments, parent=None, *, silhouette=None):
        super().__init__(parent)
        self.setObjectName("layerRangeCanvas")
        self.setMinimumSize(360, 360)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAccessibleName("Originalobjekt: Bereiche mit Greifern bearbeiten")
        self.layers = tuple(layers)
        self.tops = tuple(layer.z_mm for layer in layers)
        self.bottoms = (0.0,) + self.tops[:-1]
        self.ranges: tuple[LayerRange, ...] = ()
        self.selected = -1
        self.target_time_s = 10.0
        self.gradient_start_deficit_s = 0.0
        self.gradient_full_deficit_s = 1.0
        self.zoom = 1.0
        self.pan = 0.0
        self.pan_x = 0.0
        self._drag = None
        self._draft: LayerRange | None = None
        self._hovered_handle = None
        self._joining_indices: frozenset[int] = frozenset()
        self.join_hint = QLabel("Bereiche verbinden", self)
        self.join_hint.setObjectName("rangeJoinHint")
        self.join_hint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.join_hint.setStyleSheet(
            f"background: {self.JOIN_COLOR}; color: {self.JOIN_TEXT_COLOR}; "
            f"border: 1px solid {self.JOIN_BORDER_COLOR}; border-radius: 5px; padding: 5px 9px;"
        )
        self.join_hint.hide()
        self._background = None
        self._segments = tuple(segments)
        self._silhouette = silhouette
        self.yaw_deg = 0
        self._intervals = self._build_intervals(self._segments)
        self._minimum_x = min(a for row in self._intervals for a, _ in row)
        self._maximum_x = max(b for row in self._intervals for _, b in row)

    def sizeHint(self):
        return QSize(580, 560)

    def _build_intervals(self, segments):
        if self._silhouette is not None:
            center = np.asarray(self._silhouette.center_xy)
            direction = np.asarray((math.cos(math.radians(self.yaw_deg)), -math.sin(math.radians(self.yaw_deg))))
            rows = []
            for section in self._silhouette.segments_xy:
                if not len(section):
                    rows.append(())
                    continue
                projected = (section - center) @ direction
                a, b = projected.min(axis=1), projected.max(axis=1)
                order = np.argsort(a)
                a, b = a[order], np.maximum.accumulate(b[order])
                starts = np.r_[0, np.flatnonzero(a[1:] > b[:-1] + .05) + 1]
                ends = np.r_[starts[1:] - 1, len(a) - 1]
                rows.append(tuple(zip(a[starts], b[ends])))
            return tuple(rows)
        # Approximate outer envelopes only when full STL cuts are unavailable.
        # Rotate about the object's own vertical axis.
        points = [point for segment in segments for point in (segment.start, segment.end)]
        if not points:
            raise ValueError("Die Objektvorschau benötigt Druckbahnen aus dem Pre-Slice.")
        center_x = (max(p.x for p in points) + min(p.x for p in points)) / 2
        center_y = (max(p.y for p in points) + min(p.y for p in points)) / 2
        cosine, sine = math.cos(math.radians(self.yaw_deg)), math.sin(math.radians(self.yaw_deg))
        def project(point):
            return (point.x - center_x) * cosine - (point.y - center_y) * sine
        rows = [[] for _ in self.layers]
        for segment in segments:
            z = (segment.start.z + segment.end.z) / 2.0
            position = min(len(rows) - 1, bisect_left(self.tops, z - 1e-5))
            a, b = project(segment.start), project(segment.end)
            rows[position].append((min(a, b), max(a, b)))
        merged = []
        for row in rows:
            intervals = []
            for a, b in sorted(row):
                if intervals and a <= intervals[-1][1] + 0.05:
                    intervals[-1] = (intervals[-1][0], max(b, intervals[-1][1]))
                else:
                    intervals.append((a, b))
            # Sampled printing paths are not a solid silhouette. This fallback
            # uses their outer envelope; the main window supplies exact STL cuts.
            merged.append(((intervals[0][0], intervals[-1][1]),) if intervals else ())
        known = [i for i, row in enumerate(merged) if row]
        # The shared 3D data is sampled. Interpolate missing silhouettes only;
        # times and selection always use every actual original layer.
        for i, row in enumerate(merged):
            if row:
                continue
            j = bisect_left(known, i)
            left, right = known[max(0, j - 1)], known[min(j, len(known) - 1)]
            fraction = 0.0 if left == right else (self.tops[i] - self.tops[left]) / (self.tops[right] - self.tops[left])
            a = merged[left][0][0] * (1 - fraction) + merged[right][0][0] * fraction
            b = merged[left][-1][1] * (1 - fraction) + merged[right][-1][1] * fraction
            merged[i] = ((a, b),)
        return tuple(merged)

    def set_target_time(self, value):
        self.target_time_s = value
        self._background = None
        self.update()

    def set_color_thresholds(self, start, full):
        if not math.isfinite(start) or not math.isfinite(full) or not 0 <= start < full:
            raise ValueError("Die Farbgrenzen müssen endlich sein und 0 ≤ Beginn < vollständig Rot erfüllen.")
        self.gradient_start_deficit_s, self.gradient_full_deficit_s = start, full
        self._background = None
        self.update()

    def set_ranges(self, ranges, selected=-1):
        self.ranges = tuple(ranges)
        self.selected = selected
        self._draft = None
        self._hovered_handle = None
        self._clear_join_hint()
        self.update()

    def _clear_join_hint(self):
        self._joining_indices = frozenset()
        self.join_hint.hide()

    def _update_join_hint(self, point):
        if self._draft is None:
            self._clear_join_hint()
            return
        start, end = self._draft
        others = frozenset(index for index, (a, b) in enumerate(self.ranges)
                           if index != self.selected and start <= b + 1 and end >= a - 1)
        self._joining_indices = others | {self.selected if self.selected >= 0 else len(self.ranges)} if others else frozenset()
        if not others:
            self.join_hint.hide()
            return
        self.join_hint.adjustSize()
        x = min(self.width() - self.join_hint.width() - 8, max(8, round(point.x()) + 16))
        y = min(self.height() - self.join_hint.height() - 8, max(8, round(point.y()) - self.join_hint.height() - 14))
        self.join_hint.move(x, y)
        self.join_hint.show()
        self.join_hint.raise_()

    def fit_object(self):
        self.zoom, self.pan, self.pan_x = 1.0, 0.0, 0.0
        self._background = None
        self._refresh_fit_available()
        self.update()

    def _refresh_fit_available(self):
        fitted = (math.isclose(self.zoom, 1.0, rel_tol=0, abs_tol=1e-9)
                  and math.isclose(self.pan, 0.0, rel_tol=0, abs_tol=1e-6)
                  and math.isclose(self.pan_x, 0.0, rel_tol=0, abs_tol=1e-6))
        self.fit_available_changed.emit(not fitted)

    def set_rotation(self, angle):
        angle = round(angle)
        if angle == self.yaw_deg:
            return
        self.yaw_deg = angle
        self._intervals = self._build_intervals(self._segments)
        self._minimum_x = min(a for row in self._intervals for a, _ in row)
        self._maximum_x = max(b for row in self._intervals for _, b in row)
        self._background = None
        self.rotation_changed.emit(angle)
        self.update()

    def _horizontal_spacing(self):
        # Below 500 px, spend the spare outer margins on the object instead.
        # Keep enough room for every layer digit and the full-size controls.
        compact = min(1.0, max(0.0, (500 - self.width()) / 260))
        minimum_left = 6 + self.fontMetrics().horizontalAdvance(str(len(self.layers))) + 4
        normal_left = max(58, minimum_left)
        left = normal_left + (minimum_left - normal_left) * compact
        axis_gap = 8 - 4 * compact
        handle_gap = 12 - 8 * compact
        remove_gap = 8 - 4 * compact
        outer_right = 32 - 28 * compact
        right = handle_gap + 30 + remove_gap + 26 + outer_right
        return left, right, axis_gap, handle_gap, remove_gap

    def plot_rect(self):
        left, right, _, _, _ = self._horizontal_spacing()
        return QRectF(left, 30, max(1, self.width() - left - right), max(1, self.height() - 64))

    def layer_title_rect(self):
        left, _, _, _, _ = self._horizontal_spacing()
        normal_left = max(58, 6 + self.fontMetrics().horizontalAdvance(str(len(self.layers))) + 4)
        return QRectF(6 + normal_left - left, 5, self.fontMetrics().horizontalAdvance("Layer") + 2, 20)

    def _scale(self):
        rect = self.plot_rect()
        return self.zoom * min(rect.width() / max(1, self._maximum_x - self._minimum_x), rect.height() / max(0.01, self.tops[-1]))

    def x_for_position(self, x):
        center = (self._minimum_x + self._maximum_x) / 2.0
        return self.plot_rect().center().x() + self.pan_x + (x - center) * self._scale()

    def y_for_z(self, z):
        rect = self.plot_rect()
        return rect.bottom() + self.pan - z * self._scale()

    def layer_at_y(self, y):
        z = (self.plot_rect().bottom() + self.pan - y) / self._scale()
        return min(len(self.layers), max(1, bisect_left(self.tops, z) + 1))

    def range_rect(self, span):
        start, end = span
        top, bottom = self.y_for_z(self.tops[end - 1]), self.y_for_z(self.bottoms[start - 1])
        return QRectF(self.plot_rect().left(), top, self.plot_rect().width(), max(1, bottom - top))

    def handle_rects(self, span):
        rect = self.range_rect(span)
        _, _, _, handle_gap, _ = self._horizontal_spacing()
        x = rect.right() + handle_gap
        # Keep the two boundary grips reachable even for a single-layer range.
        upper = min(rect.top(), rect.center().y() - 9)
        lower = max(rect.bottom(), rect.center().y() + 9)
        return QRectF(x, upper - 7, 30, 14), QRectF(x, lower - 7, 30, 14)

    @classmethod
    def layer_color(cls, target, actual, start_deficit_s=0.0, full_deficit_s=1.0):
        ratio = min(1.0, max(0.0, (target - actual - start_deficit_s) / (full_deficit_s - start_deficit_s)))
        green, red = QColor(cls.OBJECT_COLOR), QColor(cls.CRITICAL_COLOR)
        return QColor(*(round(a + (b - a) * ratio) for a, b in zip(green.getRgb()[:3], red.getRgb()[:3])))

    def _render_background(self):
        pixmap = QPixmap(self.size())
        pixmap.fill(QColor(self.BACKGROUND_COLOR))
        painter = QPainter(pixmap)
        rect = self.plot_rect()
        painter.setPen(QPen(QColor("#cbd6e1"), 1))
        painter.drawLine(QPointF(rect.left(), self.y_for_z(0)), QPointF(rect.right(), self.y_for_z(0)))
        painter.setPen(QColor("#526274"))
        _, _, axis_gap, _, _ = self._horizontal_spacing()
        for position in sorted({0, len(self.layers) // 4, len(self.layers) // 2, len(self.layers) * 3 // 4, len(self.layers) - 1}):
            y = self.y_for_z(self.tops[position])
            if 12 <= y <= self.height() - 10:
                painter.drawText(QRectF(0, y - 10, rect.left() - axis_gap, 20), Qt.AlignmentFlag.AlignRight, str(position + 1))
        painter.drawText(self.layer_title_rect(), "Layer")
        painter.setClipRect(QRectF(rect.left(), 0, rect.width(), self.height()))
        paths = defaultdict(QPainterPath)
        for position, intervals in enumerate(self._intervals):
            y = self.y_for_z(self.tops[position])
            height = max(0.7, self.y_for_z(self.bottoms[position]) - y)
            if y > self.height() or y + height < 0:
                continue
            color = self.layer_color(self.target_time_s, self.layers[position].total_time_s,
                                     self.gradient_start_deficit_s, self.gradient_full_deficit_s)
            for a, b in intervals:
                paths[color.rgb()].addRect(QRectF(self.x_for_position(a), y, max(0.7, self.x_for_position(b) - self.x_for_position(a)), height))
        painter.setPen(Qt.PenStyle.NoPen)
        for color, path in paths.items():
            # Dense layers overlap by a fraction of a pixel. Odd-even filling
            # would punch stripes out of neighboring rectangles of one color.
            path.setFillRule(Qt.FillRule.WindingFill)
            painter.fillPath(path, QColor.fromRgb(color))
        painter.end()
        self._background = pixmap

    def paintEvent(self, event):
        if self._background is None or self._background.size() != self.size():
            self._render_background()
        painter = QPainter(self)
        outline = QPainterPath()
        outline.addRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 6, 6)
        painter.setClipPath(outline)
        painter.drawPixmap(0, 0, self._background)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        spans = list(self.ranges)
        if self._draft is not None:
            if self.selected >= 0:
                spans[self.selected] = self._draft
            else:
                spans.append(self._draft)
        for index, span in enumerate(spans):
            rect = self.range_rect(span)
            selected = index == self.selected or self._draft == span
            joining = index in self._joining_indices
            border_color = self.JOIN_BORDER_COLOR if joining else self.SELECTION_BORDER_COLOR
            fill_color = QColor(self.JOIN_COLOR if joining else self.SELECTION_COLOR)
            fill_color.setAlpha(160 if joining or selected else 125)
            painter.fillRect(rect, fill_color)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(border_color), 2 if selected or joining else 1))
            painter.drawRect(rect)
            for action, grip in zip(("end", "start"), self.handle_rects(span)):
                highlighted = self.isEnabled() and (
                    self._hovered_handle == (index, action)
                    or (index == self.selected and self._drag is not None and self._drag[0] == action)
                )
                grip_color = QColor(border_color)
                if highlighted:
                    grip_color = grip_color.darker(115)
                painter.setPen(QPen(QColor(border_color), 2 if highlighted else 1))
                painter.setBrush(grip_color)
                painter.drawRoundedRect(grip, 4, 4)
                painter.setPen(QPen(QColor("#ffffff"), 1))
                painter.drawLine(grip.center() + QPointF(-7, 0), grip.center() + QPointF(7, 0))
                painter.setPen(QPen(QColor(border_color), 1))
            if selected:
                label = f"Ausschlussbereich {index + 1} · Layer {span[0]}–{span[1]}"
                label_width = min(self.fontMetrics().horizontalAdvance(label) + 20, rect.width() - 12)
                label_height = 22
                if self.fontMetrics().horizontalAdvance(label) + 20 > label_width:
                    label = f"Ausschlussbereich {index + 1}\nLayer {span[0]}–{span[1]}"
                    label_height = self.fontMetrics().height() * 2 + 6
                label_y = min(self.height() - label_height - 2, max(4, rect.center().y() - label_height / 2))
                label_rect = QRectF(rect.left() + 6, label_y, label_width, label_height)
                painter.fillRect(label_rect, QColor(255, 255, 255, 235))
                painter.setPen(QColor(self.JOIN_TEXT_COLOR if joining else self.SELECTION_TEXT_COLOR))
                painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, label)
                delete_rect = self.delete_rect(span)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#b42318"))
                painter.drawRoundedRect(delete_rect, 4, 4)
                painter.setPen(QColor("#ffffff"))
                painter.drawText(delete_rect, Qt.AlignmentFlag.AlignCenter, "×")
        painter.setClipping(False)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(self.BORDER_COLOR), 1))
        painter.drawPath(outline)
        painter.end()

    def delete_rect(self, span):
        y = min(self.height() - 28, max(4, self.range_rect(span).center().y() - 12))
        _, _, _, handle_gap, remove_gap = self._horizontal_spacing()
        return QRectF(self.plot_rect().right() + handle_gap + 30 + remove_gap, y, 26, 24)

    def _hit(self, point):
        order = sorted(range(len(self.ranges)), key=lambda i: i == self.selected, reverse=True)
        for index in order:
            span = self.ranges[index]
            if index == self.selected and self.delete_rect(span).contains(point):
                return index, "delete"
            upper, lower = self.handle_rects(span)
            if upper.contains(point):
                return index, "end"
            if lower.contains(point):
                return index, "start"
            if self.range_rect(span).adjusted(0, -3, 0, 3).contains(point):
                return index, "move"
        return -1, "new"

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self._drag = ("rotate", event.position().x(), self.yaw_deg)
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            return
        if event.button() == Qt.MouseButton.MiddleButton:
            self._drag = ("pan", event.position(), (self.pan_x, self.pan))
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.setFocus()
        index, action = self._hit(event.position())
        if action == "delete":
            self.remove_requested.emit(index)
            return
        self.selected = index
        self.selection_changed.emit(index)
        layer = self.layer_at_y(event.position().y())
        initial = (layer, layer) if index < 0 else self.ranges[index]
        self._drag = (action, layer, initial)
        self._draft = initial
        self._update_join_hint(event.position())
        self.update()

    def mouseMoveEvent(self, event):
        if self._drag is None:
            index, action = self._hit(event.position())
            hovered = (index, action) if action in {"start", "end"} else None
            if hovered != self._hovered_handle:
                self._hovered_handle = hovered
                self.update()
            self.setCursor(Qt.CursorShape.CrossCursor if action == "new" else
                           Qt.CursorShape.SizeVerCursor if action in {"start", "end"} else
                           Qt.CursorShape.SizeAllCursor if action == "move" else
                           Qt.CursorShape.PointingHandCursor if action == "delete" else Qt.CursorShape.ArrowCursor)
            if hovered is not None:
                boundary = self.ranges[index][0 if action == "start" else 1]
                self.setToolTip(f"{'Untere' if action == 'start' else 'Obere'} Grenze verschieben · Layer {boundary}")
                return
            number = self.layer_at_y(event.position().y())
            layer = self.layers[number - 1]
            self.setToolTip(f"Layer {number} · {layer.z_mm:.3f} mm · {layer.total_time_s:.3f} s · Defizit {max(0, self.target_time_s - layer.total_time_s):.3f} s")
            return
        action, anchor, initial = self._drag
        if action == "pan":
            self.pan_x = initial[0] + event.position().x() - anchor.x()
            self.pan = initial[1] + event.position().y() - anchor.y()
            self._background = None
            self._refresh_fit_available()
        elif action == "rotate":
            angle = (initial + (event.position().x() - anchor) * 0.6 + 180) % 360 - 180
            self.set_rotation(angle)
        else:
            layer = self.layer_at_y(event.position().y())
            start, end = initial
            if action == "new":
                self._draft = (min(anchor, layer), max(anchor, layer))
            elif action == "start":
                self._draft = (min(layer, end), end)
            elif action == "end":
                self._draft = (start, max(layer, start))
            else:
                delta = max(1 - start, min(len(self.layers) - end, layer - anchor))
                self._draft = (start + delta, end + delta)
            self._update_join_hint(event.position())
        self.update()

    def leaveEvent(self, event):
        if self._hovered_handle is not None:
            self._hovered_handle = None
            self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drag is None:
            return
        action = self._drag[0]
        if action not in {"pan", "rotate"}:
            # Include the actual release point (Qt may coalesce mouse moves).
            self.mouseMoveEvent(event)
        span, index = self._draft, self.selected
        self._drag, self._draft = None, None
        self._clear_join_hint()
        if action not in {"pan", "rotate"} and span is not None:
            self.range_committed.emit(index, *span)
        self.update()

    def wheelEvent(self, event):
        if self._drag is not None:
            event.accept()
            return
        x, y = event.position().x(), event.position().y()
        old = self.zoom
        self.zoom = min(40, max(1, self.zoom * 1.2 ** (event.angleDelta().y() / 120)))
        baseline = self.plot_rect().bottom() + self.pan
        self.pan += (baseline - y) * (self.zoom / old - 1)
        center = self.plot_rect().center().x() + self.pan_x
        self.pan_x += (center - x) * (self.zoom / old - 1)
        if self.zoom == 1:
            self.pan, self.pan_x = 0, 0
        self._refresh_fit_available()
        self._background = None
        self.update()
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            if self._drag is None:
                super().keyPressEvent(event)
                return
            self._drag, self._draft = None, None
            self._clear_join_hint()
            self.update()
            event.accept()
            return
        if 0 <= self.selected < len(self.ranges):
            if event.key() in {Qt.Key.Key_Delete, Qt.Key.Key_Backspace}:
                self.remove_requested.emit(self.selected)
                return
            if event.key() in {Qt.Key.Key_Up, Qt.Key.Key_Down}:
                start, end = self.ranges[self.selected]
                delta = (10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1) * (1 if event.key() == Qt.Key.Key_Up else -1)
                delta = max(1 - start, min(len(self.layers) - end, delta))
                self.range_committed.emit(self.selected, start + delta, end + delta)
                return
        super().keyPressEvent(event)
