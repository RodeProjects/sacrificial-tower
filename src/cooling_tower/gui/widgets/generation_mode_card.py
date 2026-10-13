from __future__ import annotations

from PySide6.QtCore import QEvent,QRect, QSize, Qt
from PySide6.QtWidgets import QLabel, QPushButton, QSizePolicy, QVBoxLayout
from cooling_tower.gui.widgets.responsive_card_grid import ResponsiveCardGrid


class GenerationModeGrid(ResponsiveCardGrid):
    """Prefer a centered, bounded row, while allowing it to shrink and stack."""

    def __init__(self) -> None:
        super().__init__(breakpoint_px=800)
        self.setMaximumWidth(980)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.maximumWidth(), super().sizeHint().height())

    def refresh_card_heights(self) -> None:
        """Keep styled cards inside the grid, including their rounded edges."""
        self.grid.invalidate()
        self.setMinimumHeight(self.content_height_hint())
        self.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refresh_card_heights()


class GenerationModeCard(QPushButton):
    """A whole-card action with wrapping text and standard keyboard support."""

    def __init__(self, title: str, description: str, action: str) -> None:
        super().__init__()
        self.setProperty("generationModeCard", True)
        self.setAccessibleName(title)
        self.setAccessibleDescription(description + " " + action)
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

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(360, max(self.minimumHeight(), self.heightForWidth(360)))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, self.minimumHeight())

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        layout = self.layout()
        margins = layout.contentsMargins()
        inner = max(1,width-margins.left()-margins.right())
        labels = (self.title_label,self.description_label,self.action_label)
        height = sum(self._label_height(label,inner) for label in labels)
        return max(190,height+margins.top()+margins.bottom()+layout.spacing()*(layout.count()-1))

    @staticmethod
    def _label_height(label,width):
        margins = label.contentsMargins()
        inner = max(1,width-margins.left()-margins.right())
        rectangle = label.fontMetrics().boundingRect(QRect(0,0,inner,100000),Qt.TextFlag.TextWordWrap,label.text())
        return rectangle.height()+margins.top()+margins.bottom()+2

    def _fit_wrapped_text(self):
        margins = self.layout().contentsMargins()
        width = max(1,self.width()-margins.left()-margins.right())
        for label in (self.title_label,self.description_label,self.action_label):
            label.setMinimumHeight(self._label_height(label,width))
        height = self.heightForWidth(self.width())
        if height != self.minimumHeight():
            self.setMinimumHeight(height)
            # Styling can increase the height after the enclosing grid was
            # measured. Update its minimum too; a stale parent allocation
            # must never clip the card after polishing or a width change.
            parent = self.parentWidget()
            if isinstance(parent, GenerationModeGrid):
                parent.refresh_card_heights()

    def resizeEvent(self,event):
        self._fit_wrapped_text()
        super().resizeEvent(event)

    def changeEvent(self,event):
        super().changeEvent(event)
        if event.type() in {QEvent.Type.FontChange,QEvent.Type.StyleChange} and hasattr(self,"action_label"):
            self._fit_wrapped_text()
