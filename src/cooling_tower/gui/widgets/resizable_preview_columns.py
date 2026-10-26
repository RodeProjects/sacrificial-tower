"""Edge-attached settings and preview with a draggable, responsive divider."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSplitter, QSplitterHandle, QVBoxLayout, QWidget

from cooling_tower.gui.design_tokens import METRICS
from cooling_tower.gui.widgets.responsive_card_grid import ResponsiveCardGrid


class _PreviewHandle(QSplitterHandle):
    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self.setCursor(Qt.CursorShape.SplitHCursor)
        self.setToolTip("Ziehen, um Einstellungen und Vorschau zu verbreitern. Doppelklick: gleiche Breite.")
        self.setAccessibleName("Breite von Einstellungen und Vorschau ändern")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)

    def enterEvent(self, event):  # noqa: N802
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):  # noqa: N802
        super().leaveEvent(event)
        self.update()

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.splitter().center_requested.emit()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#dbe9f4" if self.underMouse() else "#edf1f5"))
        painter.setPen(QPen(QColor("#4382b4" if self.underMouse() else "#bac7d4"), 1))
        x = self.width() // 2
        painter.drawLine(x, 0, x, self.height())
        # A small permanent grip makes the divider discoverable before hovering.
        painter.setPen(QPen(QColor("#6d879c"), 1))
        for offset in (-1, 1):
            painter.drawLine(x + offset * 2, 18, x + offset * 2, 44)


class _PreviewSplitter(QSplitter):
    center_requested = Signal()

    def createHandle(self):  # noqa: N802
        return _PreviewHandle(self.orientation(), self)


class ResizablePreviewColumns(QWidget):
    layout_changed = Signal()

    def __init__(self, left, right):
        super().__init__()
        self.left, self.right = left, right
        self._two_column = None
        self._ratio = None
        self._laying_out = False
        self.stack = QVBoxLayout(self)
        self.stack.setContentsMargins(0, 0, 0, 0)
        self.stack.setSpacing(0)
        self.stack.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.splitter = _PreviewSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.setObjectName("preprocessorSplitter")
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(7)
        self.splitter.setOpaqueResize(True)
        self.splitter.splitterMoved.connect(self._moved)
        self.splitter.center_requested.connect(self.center_columns)
        self.refresh_layout()

    def is_two_column(self):
        return bool(self._two_column)

    def _moved(self, *_):
        if not self._laying_out and self._two_column:
            sizes = self.splitter.sizes()
            self._ratio = sizes[0] / max(1, sum(sizes))
            self.layout_changed.emit()

    def center_columns(self):
        """Reset to an exact half, retaining that half through later resizes."""
        self._ratio = 0.5
        self._apply_ratio()
        self.layout_changed.emit()

    def _apply_ratio(self):
        if self._two_column:
            self.stack.activate()
            width = max(2, self.splitter.width() - self.splitter.handleWidth())
            left_width = (self.left.minimumSizeHint().width() if self._ratio is None
                else int(width * self._ratio))
            self.splitter.setSizes([left_width, width - left_width])

    def refresh_layout(self):
        minimum_pair_width = (self.left.minimumSizeHint().width()
            + self.right.minimumSizeHint().width() + self.splitter.handleWidth())
        two_column = self.width() >= max(METRICS.responsive_breakpoint_px, minimum_pair_width)
        if two_column == self._two_column:
            if self._ratio is None:
                self._apply_ratio()
            return
        self._laying_out = True
        self._two_column = two_column
        if two_column:
            self.stack.removeWidget(self.right)
            self.stack.removeWidget(self.left)
            self.splitter.addWidget(self.left)
            self.splitter.addWidget(self.right)
            self.stack.addWidget(self.splitter)
            self.splitter.show()
            self._apply_ratio()
        else:
            self.stack.removeWidget(self.splitter)
            self.right.setParent(self)
            self.left.setParent(self)
            self.splitter.hide()
            self.stack.addWidget(self.right)
            self.stack.addWidget(self.left)
        self.left.show()
        self.right.show()
        self._laying_out = False
        self.updateGeometry()

    def content_height_hint(self):
        widgets = (self.left, self.right)
        heights = [ResponsiveCardGrid._height_for_width(widget,
            widget.width() if self._two_column else self.width()) for widget in widgets]
        return max(heights) if self._two_column else sum(heights)

    def sizeHint(self):  # noqa: N802
        return QSize(1040, self.content_height_hint())

    def minimumSizeHint(self):  # noqa: N802
        return QSize(0, self.content_height_hint())

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self.refresh_layout()
        if self._two_column:
            # Scrollbar changes also resize the container. Reapply the chosen
            # fraction instead of letting QSplitter distribute that delta by
            # the unrelated preferred widths of its children.
            self._apply_ratio()
