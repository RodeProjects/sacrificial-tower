from __future__ import annotations

from PySide6.QtCore import QEvent,QRect, QSize, Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget
from cooling_tower.gui.design_tokens import METRICS


class GenerationModeGrid(QWidget):
    """Three method cards, then a leading card over a pair, then one column."""

    def __init__(self) -> None:
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._cards = ()
        self._laying_out = False
        self.column_count = 0
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self.refresh_card_heights)
        self._spacing = METRICS.card_spacing_px
        self.setMaximumWidth(1100)

    def set_cards(self, preprocessor, automatic, manual):
        self._cards = preprocessor, automatic, manual
        for card in self._cards:
            card.setParent(self)
            card.show()
        QWidget.setTabOrder(preprocessor, automatic)
        QWidget.setTabOrder(automatic, manual)
        self.refresh_card_heights()

    def _card_width(self):
        return max(360, *(card.title_label.minimumSizeHint().width()+
            card.layout().contentsMargins().left()+card.layout().contentsMargins().right()
            for card in self._cards))

    def columns_for_width(self, width):
        card_width, gap = self._card_width(), self._spacing
        return 3 if width >= 3*card_width+2*gap else 2 if width >= 2*card_width+gap else 1

    def _card_rectangles(self):
        if not self._cards:
            return ()
        width, gap = self.width(), self._spacing
        columns = self.columns_for_width(width)
        if columns == 3:
            positions = tuple((i*(width+gap)//3, (i+1)*(width+gap)//3-gap) for i in range(3))
            height = max(card.heightForWidth(right-left) for card, (left, right) in zip(self._cards, positions))
            return tuple(QRect(left, 0, right-left, height) for left, right in positions)
        if columns == 2:
            first_width = (width-gap)//2
            second_width = width-gap-first_width
            top_height = self._cards[0].heightForWidth(width)
            bottom_height = max(self._cards[1].heightForWidth(first_width), self._cards[2].heightForWidth(second_width))
            return (QRect(0, 0, width, top_height),
                QRect(0, top_height+gap, first_width, bottom_height),
                QRect(first_width+gap, top_height+gap, second_width, bottom_height))
        rectangles, y = [], 0
        for card in self._cards:
            height = card.heightForWidth(width)
            rectangles.append(QRect(0, y, width, height))
            y += height+gap
        return tuple(rectangles)

    def content_height_hint(self):
        return max((rect.bottom()+1 for rect in self._card_rectangles()), default=0)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.maximumWidth(), self.content_height_hint())

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, self.content_height_hint())

    def refresh_card_heights(self) -> None:
        """Keep styled cards inside the grid, including their rounded edges."""
        if self._laying_out or not self._cards:
            return
        self._laying_out = True
        try:
            self.setMaximumWidth(3*self._card_width()+2*self._spacing)
            self.column_count = self.columns_for_width(self.width())
            rectangles = self._card_rectangles()
            for card, rect in zip(self._cards, rectangles):
                card._fit_wrapped_text(rect.width())
                card.setGeometry(rect)
            self.setMinimumHeight(self.content_height_hint())
            self.updateGeometry()
        finally:
            self._laying_out = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.schedule_card_refresh()

    def schedule_card_refresh(self):
        # Child resize callbacks can run inside Qt's current layout pass.
        # Reflow afterwards so that pass cannot restore stale row heights.
        if not self._laying_out:
            self._refresh_timer.start(0)


class _ExportTag(QLabel):
    """Keep export formats on one line with a stable, unabridged size hint."""

    def __init__(self, text: str, parent: QWidget) -> None:
        super().__init__(text, parent)
        self.full_text = text
        self.setObjectName("generationModeExportTag")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(False)
        self.setIndent(0)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def sizeHint(self) -> QSize:  # noqa: N802
        self.ensurePolished()
        margins = self.contentsMargins()
        return QSize(
            self.fontMetrics().horizontalAdvance(self.full_text) + margins.left() + margins.right(),
            self.fontMetrics().height() + margins.top() + margins.bottom(),
        )

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, self.sizeHint().height())

    def _fit_text(self) -> None:
        metrics = self.fontMetrics()
        width = max(0, self.contentsRect().width())
        if metrics.horizontalAdvance(self.full_text) <= width:
            self.setText(self.full_text)
            return
        name, separator, extension = self.full_text.rpartition(" (")
        suffix = separator + extension
        # Preserve the complete format suffix when shortening the file name.
        if separator and metrics.horizontalAdvance("…" + suffix) <= width:
            name_width = width - metrics.horizontalAdvance(suffix)
            self.setText(metrics.elidedText(name, Qt.TextElideMode.ElideRight, name_width) + suffix)
        else:
            self.setText(metrics.elidedText(self.full_text, Qt.TextElideMode.ElideMiddle, width))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_text()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in {QEvent.Type.FontChange, QEvent.Type.StyleChange} and hasattr(self, "full_text"):
            self.updateGeometry()
            self._fit_text()


class GenerationModeCard(QPushButton):
    """A whole-card action with wrapping text and standard keyboard support."""

    def __init__(self, title: str, description: str, action: str, *, exports: tuple[str, ...]) -> None:
        super().__init__()
        self.setProperty("generationModeCard", True)
        self.setAccessibleName(title)
        export_description = "Im Export enthalten: " + ", ".join(exports)
        self.setAccessibleDescription(description + " " + export_description + ". " + action)
        self.setToolTip(export_description)
        self.setMinimumHeight(190)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 24)
        layout.setSpacing(14)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("generationModeCardTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.description_label = QLabel(description)
        self.description_label.setObjectName("generationModeCardDescription")
        self.description_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.action_label = QLabel(action)
        self.action_label.setObjectName("generationModeCardAction")
        self.action_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for label in (self.title_label, self.description_label, self.action_label):
            label.setWordWrap(True)
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            layout.addWidget(label)
        layout.insertStretch(2, 1)
        self.export_group = QWidget(self)
        self.export_group.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.export_group.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        export_layout = QVBoxLayout(self.export_group)
        export_layout.setContentsMargins(0, 0, 0, 0)
        export_layout.setSpacing(6)
        self.export_heading = QLabel("Im Export enthalten", self.export_group)
        self.export_heading.setObjectName("generationModeExportHeading")
        self.export_heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        export_layout.addWidget(self.export_heading)
        self.export_row = QWidget(self.export_group)
        tag_layout = QHBoxLayout(self.export_row)
        tag_layout.setContentsMargins(0, 0, 0, 0)
        tag_layout.setSpacing(6)
        tag_layout.addStretch(1)
        self.export_tags = tuple(_ExportTag(text, self.export_row) for text in exports)
        for tag in self.export_tags:
            tag_layout.addWidget(tag)
        tag_layout.addStretch(1)
        export_layout.addWidget(self.export_row)
        layout.insertWidget(3, self.export_group)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(360, max(self.minimumHeight(), self.heightForWidth(360)))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, self.minimumHeight())

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        layout = self.layout()
        margins = layout.contentsMargins()
        inner = max(1,width-margins.left()-margins.right())
        labels = (self.title_label,self.description_label,self.action_label)
        height = sum(self._label_height(label,inner) for label in labels) + self.export_group.sizeHint().height()
        return max(190,height+margins.top()+margins.bottom()+layout.spacing()*(layout.count()-1))

    @staticmethod
    def _label_height(label,width):
        margins = label.contentsMargins()
        inner = max(1,width-margins.left()-margins.right())
        rectangle = label.fontMetrics().boundingRect(QRect(0,0,inner,100000),Qt.TextFlag.TextWordWrap,label.text())
        return rectangle.height()+margins.top()+margins.bottom()+2

    def _fit_wrapped_text(self, card_width=None):
        card_width = self.width() if card_width is None else card_width
        margins = self.layout().contentsMargins()
        width = max(1,card_width-margins.left()-margins.right())
        for label in (self.title_label,self.description_label,self.action_label):
            label.setMinimumHeight(self._label_height(label,width))
        height = self.heightForWidth(card_width)
        if height != self.minimumHeight():
            self.setMinimumHeight(height)
            # Styling can increase the height after the enclosing grid was
            # measured. Update its minimum too; a stale parent allocation
            # must never clip the card after polishing or a width change.
            parent = self.parentWidget()
            if isinstance(parent, GenerationModeGrid):
                parent.schedule_card_refresh()

    def resizeEvent(self,event):
        self._fit_wrapped_text()
        super().resizeEvent(event)

    def _set_action_hover(self, hovered: bool) -> None:
        self.action_label.setProperty("cardHover", hovered)
        style = self.action_label.style()
        style.unpolish(self.action_label)
        style.polish(self.action_label)
        self.action_label.update()

    def enterEvent(self, event):
        super().enterEvent(event)
        self._set_action_hover(True)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._set_action_hover(False)

    def changeEvent(self,event):
        super().changeEvent(event)
        if event.type() in {QEvent.Type.FontChange,QEvent.Type.StyleChange} and hasattr(self,"action_label"):
            self._fit_wrapped_text()
