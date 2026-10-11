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
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(12)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("generationModeCardTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.description_label = QLabel(description)
        self.description_label.setObjectName("generationModeCardDescription")
        self.action_label = QLabel(action)
        self.action_label.setObjectName("generationModeCardAction")
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
        self.setMinimumHeight(self.heightForWidth(self.width()))

    def resizeEvent(self,event):
        self._fit_wrapped_text()
        super().resizeEvent(event)

    def changeEvent(self,event):
        super().changeEvent(event)
        if event.type() in {QEvent.Type.FontChange,QEvent.Type.StyleChange} and hasattr(self,"action_label"):
            self._fit_wrapped_text()
