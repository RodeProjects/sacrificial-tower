"""Result columns that share spare space before the first joint measurement."""
from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Signal
from PySide6.QtWidgets import QLayout

from cooling_tower.gui.widgets.generation_text_metrics import unwrapped_card_width


class GenerationMetricsLayout(QLayout):
    layout_changed = Signal()

    def __init__(self, cards, summary, hint_cell, actions, parent, *, summary_text_variants=None):
        super().__init__(parent)
        self.cards = cards
        self.summary = summary
        self.hint_cell = hint_cell
        self.actions = actions
        self.summary_text_variants = summary_text_variants
        self.flexible_columns = False
        self._items = []
        self._compact = None
        self._arranging = False
        self.setContentsMargins(0, 0, 0, 0)
        for widget in (*cards, summary, hint_cell):
            self.addWidget(widget)

    def addItem(self, item):  # noqa: N802
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def minimumSize(self):  # noqa: N802
        # Wrapped QLabel size hints must not impose their old, narrower heights.
        return QSize(0, 0)

    def sizeHint(self):  # noqa: N802
        minimums = [*(unwrapped_card_width(card) for card in self.cards),
                    unwrapped_card_width(self.summary, self.summary_text_variants)]
        width = sum(minimums) if self.flexible_columns else 3 * max(minimums)
        return QSize(width, self.heightForWidth(width))

    def hasHeightForWidth(self):  # noqa: N802
        return True

    def heightForWidth(self, width):  # noqa: N802
        *_, top_height, bottom_height = self._plan(max(1, width))
        return top_height + bottom_height

    def _plan(self, width):
        time_min, deviation_min = map(unwrapped_card_width, self.cards)
        summary_width = unwrapped_card_width(self.summary, self.summary_text_variants)
        minimums = (time_min, deviation_min, summary_width)
        minimum_width = sum(minimums) if self.flexible_columns else 3 * max(minimums)
        compact = width < max(minimum_width, self.actions.minimum_unwrapped_width())
        if compact:
            time_width = (width + 1) // 2
            deviation_width = summary_width = width // 2
            hint_margins = self.hint_cell.layout().contentsMargins()
            hint_padding = hint_margins.left() + hint_margins.right() + 1
        elif self.flexible_columns:
            time_width, deviation_width, summary_width = self._fit_columns(width, minimums)
        else:
            # Distribute indivisible logical pixels without leaving a gap at either edge.
            time_width = (width + 2) // 3
            deviation_width = (width + 1) // 3
            summary_width = width // 3
        top_height = max(
            card.layout().totalHeightForWidth(max(1, cell_width))
            for card, cell_width in zip(self.cards, (time_width, deviation_width))
        )
        summary_height = self.summary.layout().totalHeightForWidth(summary_width)
        if compact:
            hint_width = max(1, width - summary_width - hint_padding)
            hint_height = 0
            if not self.actions.manual_hint.isHidden():
                hint_height = self.actions.manual_hint.heightForWidth(hint_width)
                hint_height += hint_margins.top() + hint_margins.bottom() + 1
            bottom_height = max(summary_height, hint_height)
        else:
            top_height = max(top_height, summary_height)
            bottom_height = 0
        return compact, time_width, deviation_width, summary_width, top_height, bottom_height

    @staticmethod
    def _fit_columns(width, minimums):
        """Keep columns as equal as possible while retaining every unwrapped line."""
        widths = [0] * len(minimums)
        remaining = list(range(len(minimums)))
        while remaining:
            share, extra = divmod(width, len(remaining))
            fixed = [index for index in remaining if minimums[index] > share]
            if not fixed:
                for offset, index in enumerate(remaining):
                    widths[index] = share + (offset < extra)
                break
            for index in fixed:
                widths[index] = minimums[index]
                width -= widths[index]
                remaining.remove(index)
        return widths

    def setGeometry(self, rect):  # noqa: N802
        super().setGeometry(rect)
        if self._arranging:
            return
        self._arranging = True
        try:
            compact, time_width, deviation_width, summary_width, top_height, bottom_height = self._plan(max(1, rect.width()))
            changed = compact != self._compact
            self._compact = compact
            self.hint_cell.setVisible(compact)
            self.actions.set_hint_container(self.hint_cell if compact else None)
            x, y = rect.x(), rect.y()
            self.cards[0].setGeometry(QRect(x, y, time_width, top_height))
            self.cards[1].setGeometry(QRect(x + time_width, y, deviation_width, top_height))
            self.summary.setGeometry(QRect(rect.right() + 1 - summary_width,
                                           y + top_height if compact else y,
                                           summary_width, bottom_height if compact else top_height))
            if compact:
                self.hint_cell.setGeometry(QRect(x, y + top_height, rect.width() - summary_width, bottom_height))
            if changed:
                for card, divider in zip(self.cards, (True, not compact)):
                    card.setProperty("dividerRight", divider)
                    card.style().unpolish(card)
                    card.style().polish(card)
                    card.update()
                self.layout_changed.emit()
        finally:
            self._arranging = False
