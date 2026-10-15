from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QGridLayout, QLabel


class PreparationRequirementsLayout(QGridLayout):
    """Show four status rows in reading-order columns only when all text fits."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: tuple[tuple[QLabel, QLabel], ...] = ()
        self._layout_signature = None

    def set_rows(self, rows: tuple[tuple[QLabel, QLabel], ...]) -> None:
        if len(rows) != 4:
            raise ValueError("The preparation checklist requires four rows.")
        self._rows = tuple(rows)
        self._apply_columns(self.parentWidget().width())
        self.invalidate()

    def _column_widths(self) -> tuple[int, int]:
        spacing = self.horizontalSpacing()
        widths = []
        for icon, label in self._rows:
            label.ensurePolished()
            margins = label.contentsMargins()
            text_width = max(
                label.fontMetrics().horizontalAdvance(label.text()),
                label.fontMetrics().boundingRect(label.text()).width(),
            )
            widths.append(
                icon.minimumWidth() + spacing + text_width
                + margins.left() + margins.right() + 2 * label.margin()
                + max(0, label.indent())
            )
        return max(widths[:2]), max(widths[2:])

    def _available_columns(self, width: int) -> tuple[bool, tuple[int, int]]:
        widths = self._column_widths()
        margins = self.contentsMargins()
        available = max(0, width - margins.left() - margins.right())
        gap = 3 * self.horizontalSpacing()
        return available >= sum(widths) + gap, widths

    def _apply_columns(self, width: int) -> None:
        if not self._rows:
            return
        two_column, widths = self._available_columns(width)
        signature = (two_column, widths)
        if signature == self._layout_signature:
            return
        self._layout_signature = signature
        while self.count():
            self.takeAt(0)
        for column in range(5):
            self.setColumnMinimumWidth(column, 0)
            self.setColumnStretch(column, 0)
        self.setColumnStretch(1, 1)
        if two_column:
            self.setColumnMinimumWidth(2, self.horizontalSpacing())
            self.setColumnStretch(4, 1)
            for offset, column_width in zip((0, 3), widths, strict=True):
                icon_width = self._rows[0][0].minimumWidth()
                self.setColumnMinimumWidth(
                    offset + 1,
                    column_width - icon_width - self.horizontalSpacing(),
                )
        for index, (icon, label) in enumerate(self._rows):
            row, column = (index % 2, (index // 2) * 3) if two_column else (index, 0)
            self.addWidget(icon, row, column)
            self.addWidget(label, row, column + 1)

    def setGeometry(self, rect) -> None:
        self._apply_columns(rect.width())
        super().setGeometry(rect)

    def hasHeightForWidth(self) -> bool:
        return bool(self._rows) or super().hasHeightForWidth()

    def heightForWidth(self, width: int) -> int:
        if not self._rows:
            return super().heightForWidth(width)
        two_column, column_widths = self._available_columns(width)
        margins = self.contentsMargins()
        available = max(1, width - margins.left() - margins.right())
        if two_column:
            extra = available - sum(column_widths) - 3 * self.horizontalSpacing()
            widths = (column_widths[0] + extra // 2,
                      column_widths[1] + extra - extra // 2)
        else:
            widths = (available,)
        heights = [0] * (2 if two_column else 4)
        for index, (icon, label) in enumerate(self._rows):
            row, column = (index % 2, index // 2) if two_column else (index, 0)
            text_width = max(1, widths[column] - icon.minimumWidth() - self.horizontalSpacing())
            height = max(icon.sizeHint().height(), label.heightForWidth(text_width))
            heights[row] = max(heights[row], height)
        return (sum(heights) + (len(heights) - 1) * self.verticalSpacing()
                + margins.top() + margins.bottom())

    def sizeHint(self) -> QSize:
        if not self._rows:
            return super().sizeHint()
        margins = self.contentsMargins()
        width = (sum(self._column_widths()) + 3 * self.horizontalSpacing()
                 + margins.left() + margins.right())
        # AlignTop uses this hint to bound the grid before distributing rows.
        # Its height must match the current arrangement, not the preferred width.
        current_width = self.parentWidget().contentsRect().width()
        return QSize(width, self.heightForWidth(current_width))

    def minimumSize(self) -> QSize:
        if not self._rows:
            return super().minimumSize()
        # A wide arrangement must never prevent the window from narrowing.
        margins = self.contentsMargins()
        width = max(icon.minimumWidth() + self.horizontalSpacing()
                    + label.minimumSizeHint().width() for icon, label in self._rows)
        height = max(max(icon.minimumSizeHint().height(), label.minimumSizeHint().height())
                     for icon, label in self._rows)
        return QSize(width + margins.left() + margins.right(),
                     2 * height + margins.top() + margins.bottom())
