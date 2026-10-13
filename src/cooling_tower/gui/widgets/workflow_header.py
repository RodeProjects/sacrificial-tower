from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QPointF, QSize, Qt
from PySide6.QtGui import QPainter, QPaintEvent, QResizeEvent, QTextLayout, QTextOption
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QLayout, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

from cooling_tower.gui.widgets.wrapping_layout import WrappingLayout


class _FactLabel(QLabel):
    """Wrap at word boundaries, and within unusually long file/profile names."""

    def _text_layout(self, width: int) -> tuple[QTextLayout, int]:
        layout = QTextLayout(self.text(), self.font())
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(option)
        layout.beginLayout()
        height = 0.0
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(max(1, width))
            line.setPosition(QPointF(0, height))
            height += line.height()
        layout.endLayout()
        return layout, math.ceil(height)

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        margins = self.contentsMargins()
        _, height = self._text_layout(width - margins.left() - margins.right())
        return height + margins.top() + margins.bottom()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, self.fontMetrics().height())

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        rectangle = self.contentsRect()
        layout, _ = self._text_layout(rectangle.width())
        layout.draw(painter, QPointF(rectangle.topLeft()))


class PreparationFactsButton(QPushButton):
    """Make the confirmation mark and all confirmed facts one shared action."""

    def __init__(self) -> None:
        super().__init__()
        self.setAccessibleName("Datei und Slicer vorbereiten")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        policy = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.content_layout = QHBoxLayout(self)
        self.content_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.content_layout.setContentsMargins(14, 10, 14, 10)
        self.content_layout.setSpacing(14)
        self.status_label = QLabel("⇧")
        self.status_label.setObjectName("preparationFactsStatus")
        self.status_label.setFixedWidth(42)
        self.status_label.setMinimumHeight(44)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.status_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.facts_widget = QWidget()
        self.facts_widget.setObjectName("workflowHeaderFacts")
        self.facts_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.facts_layout = QGridLayout(self.facts_widget)
        self.facts_layout.setContentsMargins(0, 0, 0, 0)
        self.facts_layout.setHorizontalSpacing(8)
        self.facts_layout.setVerticalSpacing(2)
        self.facts_layout.setColumnStretch(1, 1)
        self.fact_labels: dict[str, QLabel] = {}
        self._fact_keys: dict[str, QLabel] = {}
        names = ("Dateiname", "Slicer", "Maschinenprofil", "Filamentprofil", "Prozessprofil")
        for row, name in enumerate(names):
            key = QLabel(name + ":")
            key.setObjectName("workflowHeaderFactKey")
            key.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
            font = key.font()
            font.setBold(True)
            key.setFont(font)
            value = _FactLabel()
            value.setObjectName("workflowHeaderFactValue")
            value.setTextFormat(Qt.TextFormat.PlainText)
            value.setAccessibleName(name)
            policy = QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            policy.setHeightForWidth(True)
            value.setSizePolicy(policy)
            value.setMinimumWidth(0)
            value.setWordWrap(True)
            self.facts_layout.addWidget(key, row, 0)
            self.facts_layout.addWidget(value, row, 1)
            self._fact_keys[name] = key
            self.fact_labels[name] = value
            key.hide()
            value.hide()
        self.content_layout.addWidget(self.status_label, 0, Qt.AlignmentFlag.AlignVCenter)
        self.content_layout.addWidget(self.facts_widget, 1, Qt.AlignmentFlag.AlignVCenter)
        self.facts: tuple[tuple[str, str], ...] = ()
        self.facts_widget.hide()

    def set_facts(self, rows: tuple[tuple[str, str], ...]) -> None:
        self.facts = rows
        values = dict(rows)
        for name, label in self.fact_labels.items():
            value = values.get(name, "")
            label.setText(value)
            label.setToolTip(value)
            label.setVisible(name in values)
            self._fact_keys[name].setVisible(name in values)
        self.facts_widget.setVisible(bool(rows))
        description = "; ".join(f"{key}: {value}" for key, value in rows)
        self.setAccessibleDescription(description)
        self.facts_widget.setAccessibleDescription(description)
        self.setToolTip("Datei und Slicer vorbereiten" + ("\n" + description if rows else ""))
        self.status_label.setText("✓" if rows else "⇧")
        self.status_label.setProperty("confirmed", bool(rows))
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self.updateGeometry()

    def _insets(self) -> tuple[int, int]:
        margins = self.content_layout.contentsMargins()
        widget_margins = self.contentsMargins()
        return (
            margins.left() + margins.right() + widget_margins.left() + widget_margins.right(),
            margins.top() + margins.bottom() + widget_margins.top() + widget_margins.bottom(),
        )

    def _natural_facts_width(self) -> int:
        if not self.facts:
            return 0
        key_width = max(
            self._fact_keys[name].fontMetrics().horizontalAdvance(name + ":")
            for name, _ in self.facts
        )
        value_width = max(
            self.fact_labels[name].fontMetrics().horizontalAdvance(value)
            for name, value in self.facts
        )
        return key_width + value_width + self.facts_layout.horizontalSpacing()

    def sizeHint(self) -> QSize:  # noqa: N802
        horizontal, _ = self._insets()
        width = horizontal + self.status_label.width()
        if self.facts:
            width += self.content_layout.spacing() + self._natural_facts_width()
        return QSize(width, self.heightForWidth(width))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        horizontal, vertical = self._insets()
        width = horizontal + self.status_label.width()
        if self.facts:
            key_width = max(self._fact_keys[name].sizeHint().width() for name, _ in self.facts)
            width += self.content_layout.spacing() + key_width + 24
        return QSize(width, vertical + self.status_label.minimumHeight())

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        horizontal, vertical = self._insets()
        facts_width = max(1, width - horizontal - self.status_label.width() - self.content_layout.spacing())
        facts_height = self.facts_layout.totalHeightForWidth(facts_width) if self.facts else 0
        return vertical + max(self.status_label.minimumHeight(), facts_height)


class WorkflowHeader(QWidget):
    """Prefer title, preparation facts button and method action in one row."""

    def __init__(self, title: QLabel, subtitle: QLabel) -> None:
        super().__init__()
        self.setObjectName("workflowHeader")
        self.grid = QGridLayout(self)
        self.grid.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(12)
        self.grid.setColumnStretch(1, 1)
        self.brand_widget = QWidget()
        brand_layout = QVBoxLayout(self.brand_widget)
        brand_layout.setContentsMargins(0, 0, 0, 0)
        brand_layout.setSpacing(4)
        brand_layout.addWidget(title)
        brand_layout.addWidget(subtitle)
        self.actions_widget = QWidget()
        policy = QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.actions_widget.setSizePolicy(policy)
        self.actions_layout = WrappingLayout(self.actions_widget, spacing=8)
        self.actions_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.preparation_button = PreparationFactsButton()
        self.facts_widget = self.preparation_button.facts_widget
        self.fact_labels = self.preparation_button.fact_labels
        self.facts: tuple[tuple[str, str], ...] = ()
        self._actions: list[tuple[QPushButton, str, str]] = []
        self._actions_visible = False
        self._refreshing = False
        self.preparation_button.hide()
        self.grid.addWidget(self.brand_widget, 0, 0)
        self.grid.addWidget(self.actions_widget, 0, 1)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, super().minimumSizeHint().height())

    def add_action(self, button: QPushButton, full: str, compact: str) -> None:
        self._actions.append((button, full, compact))
        self.actions_layout.addWidget(button)
        self.refresh_layout()

    def set_actions_visible(self, visible: bool) -> None:
        self._actions_visible = visible
        if self._actions:
            self._actions[0][0].setVisible(visible)
        if not visible:
            for button, _, _ in self._actions[1:]:
                button.hide()
        self.preparation_button.setVisible(visible or bool(self.facts))
        self.refresh_layout()

    def set_facts(self, rows: tuple[tuple[str, str], ...]) -> None:
        self.facts = rows
        self.preparation_button.set_facts(rows)
        self.preparation_button.setVisible(self._actions_visible or bool(rows))
        self.refresh_layout()

    def refresh_layout(self) -> None:
        if self._refreshing:
            return
        self._refreshing = True
        try:
            actions = [action for action in self._actions if not action[0].isHidden()]
            for button, full, _compact in actions:
                button.setText(full)
            gap = self.actions_layout.spacing()
            available = max(1, self.width())
            brand_width = self.brand_widget.sizeHint().width()
            preparation_visible = not self.preparation_button.isHidden()
            preparation_width = self.preparation_button.sizeHint().width() if preparation_visible else 0

            def required_width() -> int:
                count = len(actions) + int(preparation_visible)
                return (
                    preparation_width
                    + sum(button.sizeHint().width() for button, _, _ in actions)
                    + gap * max(0, count - 1)
                )

            if brand_width + self.grid.horizontalSpacing() + required_width() > available:
                for button, _full, compact in actions:
                    button.setText(compact)
            inline = (
                brand_width + self.grid.horizontalSpacing() + required_width() <= available
            )
            action_width = max(1, available - brand_width - self.grid.horizontalSpacing()) if inline else available
            self.preparation_button.setFixedWidth(min(preparation_width, action_width))
            while self.actions_layout.count():
                self.actions_layout.takeAt(0)
            if preparation_visible:
                self.actions_layout.addWidget(self.preparation_button)
            for button, _, _ in actions:
                self.actions_layout.addWidget(button)
            self.actions_widget.setVisible(preparation_visible or bool(actions))
            self.grid.removeWidget(self.brand_widget)
            self.grid.removeWidget(self.actions_widget)
            self.grid.addWidget(self.brand_widget, 0, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            if inline:
                self.grid.addWidget(self.actions_widget, 0, 1)
            else:
                self.grid.addWidget(self.actions_widget, 1, 0, 1, 2)
            self.grid.invalidate()
            self.updateGeometry()
        finally:
            self._refreshing = False

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.refresh_layout()

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        super().changeEvent(event)
        if (
            hasattr(self, "_refreshing")
            and event.type() in {QEvent.Type.FontChange, QEvent.Type.StyleChange}
        ):
            self.refresh_layout()
