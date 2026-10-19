"""Prevent native repainting of partially updated widget trees."""
from contextlib import contextmanager


@contextmanager
def suspended_widget_updates(widget):
    """Restore painting after a batch, including nesting and failure paths."""
    enabled = widget.updatesEnabled()
    if enabled:
        widget.setUpdatesEnabled(False)
    try:
        yield
    finally:
        if enabled:
            widget.setUpdatesEnabled(True)
            widget.update()
