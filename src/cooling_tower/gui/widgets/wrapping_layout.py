from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtWidgets import QLayout


class WrappingLayout(QLayout):
    """Keep each widget together and wrap whole groups when width runs out."""

    def __init__(self, parent=None, *, spacing=6):
        super().__init__(parent)
        self._items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item):
        self._items.append(item)
        self.invalidate()

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            item = self._items.pop(index)
            self.invalidate()
            return item
        return None

    def expandingDirections(self):
        return Qt.Orientation.Horizontal

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def sizeHint(self):
        margins = self.contentsMargins()
        return QSize(sum(item.sizeHint().width() for item in self._items)
                     + max(0, len(self._items) - 1) * self.spacing()
                     + margins.left() + margins.right(),
                     max((item.sizeHint().height() for item in self._items), default=0)
                     + margins.top() + margins.bottom())

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def _arrange(self, rect, *, apply):
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        rows, row, used = [], [], 0
        for item in self._items:
            width = min(item.sizeHint().width(), max(item.minimumSize().width(), area.width()))
            if row and used + self.spacing() + width > area.width():
                rows.append(row)
                row, used = [], 0
            row.append((item, width))
            used += width + (self.spacing() if len(row) > 1 else 0)
        if row:
            rows.append(row)
        y = area.top()
        for row in rows:
            extra = max(0, area.width() - sum(width for _, width in row)
                        - self.spacing() * (len(row) - 1))
            expanding = [item for item, width in row
                         if item.expandingDirections() & Qt.Orientation.Horizontal
                         and item.maximumSize().width() > width]
            widths = [width + (extra // len(expanding) if item in expanding else 0)
                      for item, width in row]
            heights = [item.heightForWidth(width) if item.hasHeightForWidth()
                       else item.sizeHint().height() for (item, _), width in zip(row, widths)]
            height = max(heights, default=0)
            x = area.left()
            if apply:
                for (item, _), width, item_height in zip(row, widths, heights):
                    item.setGeometry(QRect(x, y + (height - item_height) // 2, width, item_height))
                    x += width + self.spacing()
            y += height + self.spacing()
        return y - (self.spacing() if rows else 0) - rect.top() + margins.bottom()
