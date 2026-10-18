"""Exception boundary for slicer entry points and queued GUI results."""
from __future__ import annotations

from functools import wraps


def guard_slicer_operation(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        if self._closing:
            return None
        try:
            return method(self, *args, **kwargs)
        except Exception as error:
            self._handle_slicer_operation_error(error, operation=method.__name__)
            return None

    return guarded
