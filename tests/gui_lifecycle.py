"""Release the native Qt objects belonging to a completed GUI fixture."""

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid


def dispose_test_widget(widget: QWidget) -> None:
    """Close and delete one fixture without touching other live test widgets."""
    if not isValid(widget):
        return
    if not getattr(widget, "_closing", False) and not widget.close():
        raise AssertionError("Das GUI-Testfenster konnte nicht geschlossen werden.")
    widget.deleteLater()
    QApplication.sendPostedEvents(widget, QEvent.Type.DeferredDelete)
