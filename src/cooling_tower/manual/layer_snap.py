"""Actual source-layer heights, continued above the object at its last spacing."""
from bisect import bisect_left, bisect_right
import math


def snap_layer_height(height, tops, *, lower=0.0, upper=math.inf, direction=0):
    """Nearest valid layer, or floor/ceiling toward a movement boundary.

    No interpolated layer is invented within variable-height source layers.
    Return None when the allowed interval contains no layer.
    """
    if not tops or lower > upper:
        return None
    height = max(lower, min(upper, height))
    first, stop = bisect_left(tops, lower-1e-8), bisect_right(tops, upper+1e-8)
    index = bisect_left(tops, height)
    candidates = {tops[i] for i in (first, stop-1, index-1, index) if first <= i < stop}
    step = tops[-1]-tops[-2] if len(tops) > 1 else tops[-1]
    if step > 0 and upper > tops[-1]:
        minimum = max(1, math.ceil((lower-tops[-1]-1e-8)/step))
        maximum = math.floor((upper-tops[-1]+1e-8)/step) if math.isfinite(upper) else math.inf
        position = (height-tops[-1])/step
        for n in (minimum, math.floor(position), math.ceil(position)):
            if minimum <= n <= maximum:
                candidates.add(tops[-1]+n*step)
    if direction < 0:
        candidates = {z for z in candidates if z <= height+1e-8}
    elif direction > 0:
        candidates = {z for z in candidates if z >= height-1e-8}
    return min(candidates, key=lambda z: (abs(z-height), z)) if candidates else None
