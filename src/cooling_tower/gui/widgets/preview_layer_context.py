"""Bounded raster checkpoints for already projected lower-layer geometry."""
from bisect import bisect_right
from collections import OrderedDict
from itertools import chain, islice
import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap


def layer_context_colour(color, *, subdued=True):
    color = QColor(color)
    grey = .2126*color.red()+.7152*color.green()+.0722*color.blue()
    return (QColor(*(round(component*.85+grey*.15) for component in (color.red(), color.green(), color.blue())))
        if subdued else color)


class LowerLayerFrames:
    BUDGET_BYTES = 32 * 1024 * 1024

    def __init__(self, width, height, ratio, sources, *, subdued=True):
        self.width, self.height, self.ratio = width, height, ratio
        self.sources, levels = [], set()
        for source in sources:
            segments, blocks, color, line_width, maximum, *extra = source
            heights = extra[0] if extra else ()
            stride = max(1, math.ceil(len(segments)/maximum)) if maximum else 1
            by_height = {}
            line_heights = (islice(heights, 0, None, stride) if heights else
                (segment.end.z for segment in islice(segments, 0, None, stride)))
            for z, line in zip(line_heights, chain.from_iterable(blocks)):
                by_height.setdefault(z, []).append(line)
            # Validate and merge each distinct height once, not every stroke.
            by_height = {z: lines for z, lines in by_height.items() if math.isfinite(z)}
            levels.update(by_height)
            self.sources.append((by_height, layer_context_colour(color, subdued=subdued), line_width))
        self.levels = sorted(levels)
        image_bytes = max(1, round(width*ratio)*round(height*ratio)*4)
        self.maximum_frames = max(0, min(6, self.BUDGET_BYTES//image_bytes-2))
        self.stride = max(1, math.ceil(len(self.levels)/(self.maximum_frames+1)))
        self.frames = OrderedDict()
        self._last_cut, self._last_frame = None, None

    def _empty(self):
        frame = QPixmap(max(1, round(self.width*self.ratio)), max(1, round(self.height*self.ratio)))
        frame.setDevicePixelRatio(self.ratio)
        frame.fill(Qt.GlobalColor.transparent)
        return frame

    def _draw(self, frame, first, last):
        painter = QPainter(frame)
        try:
            for by_height, color, width in self.sources:
                painter.setPen(QPen(color, width))
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, width > 1)
                block = []
                for z in self.levels[first:last]:
                    for line in by_height.get(z, ()):
                        block.append(line)
                        if len(block) == 4096:
                            painter.drawLines(tuple(block))
                            block.clear()
                if block:
                    painter.drawLines(tuple(block))
        finally:
            painter.end()

    def before(self, z):
        cut = bisect_right(self.levels, z-.001)
        if not cut:
            return None
        if cut == self._last_cut:
            return self._last_frame
        checkpoint = cut//self.stride*self.stride if self.maximum_frames else 0
        if checkpoint and checkpoint not in self.frames:
            earlier = max((index for index in self.frames if index < checkpoint), default=0)
            frame = self.frames[earlier].copy() if earlier else self._empty()
            self._draw(frame, earlier, checkpoint)
            self.frames[checkpoint] = frame
            while len(self.frames) > self.maximum_frames:
                self.frames.popitem(last=False)
        if checkpoint:
            self.frames.move_to_end(checkpoint)
            frame = self.frames[checkpoint] if checkpoint == cut else self.frames[checkpoint].copy()
        else:
            frame = self._empty()
        if checkpoint != cut:
            self._draw(frame, checkpoint, cut)
        self._last_cut, self._last_frame = cut, frame
        return frame
