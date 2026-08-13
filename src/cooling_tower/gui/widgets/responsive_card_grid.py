from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QGridLayout, QSizePolicy, QWidget

from cooling_tower.gui.design_tokens import METRICS


@dataclass(slots=True)
class _GridEntry:
    left: QWidget
    right: QWidget | None = None
    equal_height: bool = True
    stacked_right_first: bool = False


class ResponsiveCardGrid(QWidget):
    """Two-column card grid that stacks entries below the shared breakpoint."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        breakpoint_px: int = METRICS.responsive_breakpoint_px,
        horizontal_spacing_px: int = METRICS.card_spacing_px,
        vertical_spacing_px: int = METRICS.card_spacing_px,
    ) -> None:
        super().__init__(parent)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Maximum,
        )
        self._breakpoint_px = breakpoint_px
        self._horizontal_spacing_px = max(0, int(horizontal_spacing_px))
        self._vertical_spacing_px = max(0, int(vertical_spacing_px))
        self._entries: list[_GridEntry] = []
        self._two_column: bool | None = None
        self._vertical_separator: QWidget | None = None
        self._stacked_separator: QWidget | None = None
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(self._horizontal_spacing_px)
        self.grid.setVerticalSpacing(self._vertical_spacing_px)
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(1, 1)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop)

    def add_pair(
        self,
        left: QWidget,
        right: QWidget,
        *,
        equal_height: bool = True,
        stacked_right_first: bool = False,
    ) -> None:
        self._entries.append(
            _GridEntry(
                left,
                right,
                equal_height=equal_height,
                stacked_right_first=stacked_right_first,
            )
        )
        self._relayout(force=True)

    def add_full_width(self, widget: QWidget) -> None:
        self._entries.append(_GridEntry(widget))
        self._relayout(force=True)

    def set_vertical_separator(self, separator: QWidget | None) -> None:
        """Use an explicit divider between paired columns in wide layouts."""

        if self._vertical_separator is not None:
            self._vertical_separator.hide()
        self._vertical_separator = separator
        if separator is not None:
            separator.setParent(self)
        self._relayout(force=True)

    def set_stacked_separator(self, separator: QWidget | None) -> None:
        """Use an explicit divider between paired rows in narrow layouts."""

        if self._stacked_separator is not None:
            self._stacked_separator.hide()
        self._stacked_separator = separator
        if separator is not None:
            separator.setParent(self)
        self._relayout(force=True)

    def set_breakpoint(self, breakpoint_px: int) -> None:
        self._breakpoint_px = max(1, int(breakpoint_px))
        self._relayout(force=True)

    def refresh_layout(self) -> None:
        """Rebuild item positions after an external row state changed."""

        self._relayout(force=True)

    def is_two_column(self) -> bool:
        return bool(self._two_column)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt virtual API
        # Read the layout directly so a full-width collapsible row's current
        # height is immediately visible to the scroll area's parent layout.
        return self.grid.sizeHint()

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt virtual API
        # A two-column layout's calculated minimum width is the sum of both
        # child minima. Publishing that width creates a circular constraint:
        # the widget can then never become narrow enough to cross its stacking
        # breakpoint after a window was wide once. The vertical minimum remains
        # useful, while width zero lets the parent drive responsive relayout.
        return QSize(0, self.grid.minimumSize().height())

    def content_height_hint(self) -> int:
        """Return the live height needed by the current responsive layout.

        ``QGridLayout.sizeHint()`` can retain the geometry from a previously
        collapsed row.  Asking every card for its height at the width it will
        actually receive keeps independent collapsible rows able to grow again
        and avoids padding the grid with stale size-hint data.
        """

        spacing = max(0, self.grid.verticalSpacing())
        available_width = max(1, self.width())
        separator_width = (
            self._vertical_separator.sizeHint().width()
            if self._vertical_separator is not None
            else 0
        )
        horizontal_spacing = max(0, self.grid.horizontalSpacing())
        if self.is_two_column():
            column_width = max(
                1,
                (
                    available_width
                    - separator_width
                    - horizontal_spacing
                )
                // 2,
            )
        else:
            column_width = available_width

        row_heights: list[int] = []
        for entry in self._entries:
            left_hidden = entry.left.isHidden()
            right_hidden = entry.right is None or entry.right.isHidden()
            if left_hidden and right_hidden:
                continue
            if left_hidden and entry.right is not None:
                row_heights.append(
                    self._height_for_width(
                        entry.right,
                        available_width,
                    )
                )
                continue
            left_height = self._height_for_width(
                entry.left,
                available_width if entry.right is None else column_width,
            )
            if right_hidden:
                row_heights.append(left_height)
                continue
            right_height = self._height_for_width(
                entry.right,
                column_width,
            )
            if self.is_two_column():
                row_heights.append(max(left_height, right_height))
            else:
                row_heights.extend((left_height, right_height))

        if not row_heights:
            return 0
        return sum(row_heights) + spacing * (len(row_heights) - 1)

    @staticmethod
    def _height_for_width(widget: QWidget, width: int) -> int:
        if widget.hasHeightForWidth():
            preferred = widget.heightForWidth(max(1, width))
        else:
            preferred = widget.sizeHint().height()
        preferred = max(preferred, widget.minimumHeight())
        if widget.maximumHeight() < 16777215:
            preferred = min(preferred, widget.maximumHeight())
        return max(0, preferred)

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self, *, force: bool = False) -> None:
        two_column = self.width() >= self._breakpoint_px
        if not force and two_column == self._two_column:
            return
        self._two_column = two_column
        self.setProperty("twoColumn", two_column)
        style = self.style()
        style.unpolish(self)
        style.polish(self)

        while self.grid.count():
            self.grid.takeAt(0)

        separator = self._vertical_separator
        stacked_separator = self._stacked_separator
        if separator is None:
            self.grid.setHorizontalSpacing(self._horizontal_spacing_px)
            self.grid.setColumnStretch(0, 1)
            self.grid.setColumnStretch(1, 1)
            self.grid.setColumnStretch(2, 0)
        else:
            # Subsection headers meet the one-pixel separator directly. Their
            # body layouts retain their own padding independently.
            self.grid.setHorizontalSpacing(0)
            self.grid.setColumnStretch(0, 1)
            self.grid.setColumnStretch(1, 0)
            self.grid.setColumnStretch(2, 1)

        row = 0
        for entry in self._entries:
            if entry.right is None:
                self.grid.addWidget(
                    entry.left,
                    row,
                    0,
                    1,
                    3 if separator is not None else 2,
                )
                row += 1
                continue
            if two_column:
                if stacked_separator is not None:
                    stacked_separator.hide()
                alignment = (
                    Qt.AlignmentFlag.AlignTop
                    if not entry.equal_height
                    else Qt.Alignment()
                )
                self.grid.addWidget(entry.left, row, 0, alignment)
                if separator is None:
                    self.grid.addWidget(
                        entry.right,
                        row,
                        1,
                        alignment,
                    )
                else:
                    separator.show()
                    self.grid.addWidget(separator, row, 1)
                    self.grid.addWidget(
                        entry.right,
                        row,
                        2,
                        alignment,
                    )
                row += 1
            else:
                if separator is not None:
                    separator.hide()
                span = 3 if separator is not None else 2
                first, second = (
                    (entry.right, entry.left)
                    if entry.stacked_right_first
                    else (entry.left, entry.right)
                )
                self.grid.addWidget(first, row, 0, 1, span)
                if stacked_separator is not None:
                    stacked_separator.show()
                    self.grid.addWidget(stacked_separator, row + 1, 0, 1, span)
                    self.grid.addWidget(second, row + 2, 0, 1, span)
                    row += 3
                else:
                    self.grid.addWidget(second, row + 1, 0, 1, span)
                    row += 2
        self.updateGeometry()
