"""Bounded source-coordinate cache for lossless vectorized line projection."""
from collections import OrderedDict
from itertools import islice

import numpy as np


class LineProjectionCache:
    BUDGET_BYTES = 8 * 1024 * 1024
    MAXIMUM_ENTRIES = 8
    MINIMUM_LINES = 256

    def __init__(self):
        self.entries = OrderedDict()
        self.size_bytes = 0

    def clear(self):
        self.entries.clear()
        self.size_bytes = 0

    def project(self, segments, stride, parameters, context):
        key = (id(segments), stride)
        entry = self.entries.get(key)
        if entry is None:
            count = len(range(0, len(segments), stride))
            points = np.fromiter(
                (value for segment in islice(segments, 0, None, stride)
                    for point in (segment.start, segment.end)
                    for value in (point.x, point.y, point.z)),
                dtype=np.float64, count=count*6,
            ).reshape(count, 2, 3)
            points.flags.writeable = False
            if points.nbytes <= self.BUDGET_BYTES:
                while self.entries and (self.size_bytes+points.nbytes > self.BUDGET_BYTES
                        or len(self.entries) >= self.MAXIMUM_ENTRIES):
                    _key, (_source, old_points) = self.entries.popitem(last=False)
                    self.size_bytes -= old_points.nbytes
                # Keep the immutable source alive to prevent identity reuse.
                self.entries[key] = segments, points
                self.size_bytes += points.nbytes
        else:
            self.entries.move_to_end(key)
            _source, points = entry
        scale, offset_x, offset_y = parameters
        x = points[:, :, 0]-context.center_x
        y = points[:, :, 1]-context.center_y
        projected = np.empty((len(points), 2, 2), dtype=np.float64)
        # Keep the scalar projection's operation order, including its rounding.
        projected[:, :, 0] = (context.cosine_yaw*x-context.sine_yaw*y)*scale+offset_x
        projected[:, :, 1] = -(context.cosine_pitch*points[:, :, 2]
            - context.sine_pitch*(context.sine_yaw*x+context.cosine_yaw*y))*scale+offset_y
        return projected.reshape(-1, 4)
