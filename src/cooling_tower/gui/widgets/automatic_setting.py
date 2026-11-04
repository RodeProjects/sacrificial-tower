"""Shared inline Auto control for numeric settings."""
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QCheckBox, QLabel
from cooling_tower.gui.design_tokens import METRICS


class _AutomaticLabelMinimum(QObject):
    """Reserve the complete styled name before the shared gap to Auto."""

    def __init__(self, row):
        super().__init__(row)
        self.label = row.label
        self.label.installEventFilter(self)
        self.refresh()

    def refresh(self):
        self.label.setMinimumWidth(max(150, self.label.fontMetrics().horizontalAdvance(self.label.text())))

    def eventFilter(self, watched, event):  # noqa: N802
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange, QEvent.Type.Polish):
            self.refresh()
        return False


def add_automatic_control(row, checkbox=None):
    checkbox = checkbox if checkbox is not None else QCheckBox()
    checkbox.setAccessibleName(row.label.text() + " automatisch berechnen")
    row.label.setWordWrap(False)
    row._automatic_label_minimum = _AutomaticLabelMinimum(row)
    grid = row.layout()
    for widget in (row.editor, row.reset_button, row.range_label, row.message_container):
        grid.removeWidget(widget)
    label = QLabel("Auto")
    label.setContentsMargins(METRICS.form_auto_label_gap_px - METRICS.form_control_gap_px, 0, 0, 0)
    label.setBuddy(checkbox)
    center = Qt.AlignmentFlag.AlignVCenter
    grid.addWidget(label, 0, 2, Qt.AlignmentFlag.AlignRight | center)
    grid.addWidget(checkbox, 0, 3, center)
    grid.addWidget(row.editor, 0, 4, Qt.AlignmentFlag.AlignRight | center)
    grid.addWidget(row.reset_button, 0, 5, center)
    grid.addWidget(row.range_label, 1, 1, 1, 4, Qt.AlignmentFlag.AlignRight)
    grid.addWidget(row.message_container, 2, 0, 1, 6)
    return checkbox
