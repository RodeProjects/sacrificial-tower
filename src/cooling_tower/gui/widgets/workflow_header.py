from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QPoint, QPointF, QSize, Qt, Signal
from PySide6.QtGui import QPainter, QPaintEvent, QResizeEvent, QTextLayout, QTextOption
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QLayout, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from cooling_tower.gui.widgets.header_update_controls import HeaderUpdateControls


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
    """Keep the five confirmed facts together in a compact corner action."""

    NAMES = ("Dateiname", "Slicer", "Maschinenprofil", "Filamentprofil", "Prozessprofil")

    def __init__(self) -> None:
        super().__init__()
        self.setAccessibleName("Datei und Slicer vorbereiten")
        self.setToolTip("Datei- und Slicereinstellungen ändern")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        policy = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.content_layout = QHBoxLayout(self)
        self.content_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.content_layout.setContentsMargins(6, 3, 8, 4)
        self.content_layout.setSpacing(8)
        self.status_label = QLabel("⇧")
        self.status_label.setObjectName("preparationFactsStatus")
        self.status_label.setFixedWidth(26)
        self.status_label.setMinimumHeight(32)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.status_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.facts_widget = QWidget()
        self.facts_widget.setObjectName("workflowHeaderFacts")
        self.facts_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.facts_layout = QGridLayout(self.facts_widget)
        self.facts_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.facts_layout.setContentsMargins(0, 0, 0, 0)
        self.facts_layout.setHorizontalSpacing(6)
        self.facts_layout.setVerticalSpacing(0)
        self.facts_layout.setColumnStretch(1, 1)
        self.fact_labels: dict[str, QLabel] = {}
        self._fact_keys: dict[str, QLabel] = {}
        for row, name in enumerate(self.NAMES):
            key = QLabel(name + ":")
            key.setObjectName("workflowHeaderFactKey")
            key.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
            key.setIndent(0)
            font = key.font()
            font.setBold(True)
            key.setFont(font)
            value = _FactLabel()
            value.setObjectName("workflowHeaderFactValue")
            value.setTextFormat(Qt.TextFormat.PlainText)
            value.setIndent(0)
            value.setAccessibleName(name)
            policy = QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            policy.setHeightForWidth(True)
            value.setSizePolicy(policy)
            value.setMinimumWidth(0)
            value.setWordWrap(True)
            for label in (key, value):
                label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                label.hide()
            self.facts_layout.addWidget(key, row, 0)
            self.facts_layout.addWidget(value, row, 1)
            self._fact_keys[name] = key
            self.fact_labels[name] = value
        self.content_layout.addWidget(self.status_label, 0, Qt.AlignmentFlag.AlignVCenter)
        self.content_layout.addWidget(self.facts_widget, 1)
        self.facts: tuple[tuple[str, str], ...] = ()
        self.facts_widget.hide()

    def set_facts(self, rows: tuple[tuple[str, str], ...]) -> None:
        self.facts = rows
        margins = (7, 7, 7, 8) if rows else (6, 3, 8, 4)
        self.content_layout.setContentsMargins(*margins)
        values = dict(rows)
        for name, label in self.fact_labels.items():
            label.setText(values.get(name, ""))
            label.setVisible(name in values)
            self._fact_keys[name].setVisible(name in values)
        self.facts_widget.setVisible(bool(rows))
        description = "; ".join(f"{key}: {value}" for key, value in rows)
        self.setAccessibleDescription(description)
        self.facts_widget.setAccessibleDescription(description)
        self.status_label.setText("" if rows else "⇧")
        self.status_label.setVisible(not rows)
        self.setProperty("confirmed", bool(rows))
        self.status_label.setProperty("confirmed", bool(rows))
        for widget in (self, self.status_label):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        self.updateGeometry()

    def _insets(self) -> tuple[int, int]:
        margins = self.content_layout.contentsMargins()
        widget_margins = self.contentsMargins()
        return (
            margins.left() + margins.right() + widget_margins.left() + widget_margins.right(),
            margins.top() + margins.bottom() + widget_margins.top() + widget_margins.bottom(),
        )

    def preferred_width(self) -> int:
        horizontal, _ = self._insets()
        width = horizontal
        if self.facts:
            keys = max(self._fact_keys[name].sizeHint().width() for name, _ in self.facts)
            values = max(math.ceil(self.fact_labels[name]._text_layout(100000)[0].lineAt(0).naturalTextWidth()) + 1 for name, _ in self.facts)
            width += keys + self.facts_layout.horizontalSpacing()
            width += min(values, self.fontMetrics().horizontalAdvance("M") * 38)
        else:
            width += self.status_label.width()
        return width

    def sizeHint(self) -> QSize:  # noqa: N802
        width = self.preferred_width()
        return QSize(width, self.heightForWidth(width))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, 32)

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        horizontal, vertical = self._insets()
        available = max(1, width - horizontal)
        height = self.facts_layout.totalHeightForWidth(available) if self.facts else 0
        return vertical + (height if self.facts else self.status_label.minimumHeight())


class HeaderMethodSelection(QWidget):
    """A single edge-attached element with two integrated method actions."""

    method_selected = Signal(str)

    def __init__(self, button_height: int) -> None:
        super().__init__()
        self.setObjectName("headerMethodSelection")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.heading = QLabel("Erstellungsmethode")
        self.heading.setObjectName("headerMethodHeading")
        self.heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.heading.setFixedHeight(button_height)
        layout.addWidget(self.heading)
        self.buttons_layout = QHBoxLayout()
        self.buttons_layout.setContentsMargins(0, 0, 0, 0)
        self.buttons_layout.setSpacing(0)
        self.group = QButtonGroup(self)
        self.buttons: dict[str, QPushButton] = {}
        for mode, text in (("automatic", "Automatisch"), ("manual", "Manuell"), ("preprocessor", "Präprozessor")):
            button = QPushButton(text)
            button.setObjectName("headerMethodButton")
            button.setProperty("generationMode", mode)
            button.setCheckable(True)
            button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedHeight(button_height)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setToolTip("Präprozessor öffnen" if mode == "preprocessor" else f"{text}e Turmerstellung öffnen")
            button.clicked.connect(button.clearFocus)
            self.group.addButton(button)
            self.buttons[mode] = button
            self.buttons_layout.addWidget(button, 1)
        self.group.buttonClicked.connect(
            lambda button: self.method_selected.emit(button.property("generationMode"))
        )
        layout.addLayout(self.buttons_layout)

    def set_active_mode(self, mode: str | None) -> None:
        self.group.setExclusive(False)
        for name, button in self.buttons.items():
            button.setChecked(name == mode)
            button.setAccessibleDescription("Aktive Methode" if name == mode else "")
        self.group.setExclusive(True)


class WorkflowHeader(QWidget):
    """Anchor facts and tools to the edges and center the optional brand."""

    def __init__(
        self, title: QLabel, subtitle: QLabel, tools: QWidget, *,
        button_height: int, edge_padding: int = 22,
        update_controls: HeaderUpdateControls | None = None,
        menu_version: QWidget | None = None,
    ) -> None:
        super().__init__()
        self.setObjectName("workflowHeader")
        self.title_label = title
        self.subtitle_label = subtitle
        self.button_height = button_height
        self.edge_padding = edge_padding
        self.tools_widget = tools
        self.update_controls = update_controls
        self.menu_version = menu_version
        self._menu_alignments = (
            tuple(menu_version.layout().itemAt(i).alignment() for i in range(menu_version.layout().count()))
            if menu_version is not None else ()
        )
        self._update_layout_active = False
        self.layout_state = "full"
        self.grid = QGridLayout(self)
        self.grid.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(12)
        self.grid.setVerticalSpacing(0)
        self.grid.setColumnStretch(1, 1)
        # The brand is positioned independently of the columns: it follows
        # the window center until it reaches the confirmed facts on the left.
        self.brand_widget = QWidget(self)
        brand_layout = QVBoxLayout(self.brand_widget)
        brand_layout.setContentsMargins(0, 0, 0, 0)
        brand_layout.setSpacing(4)
        for label in (title, subtitle):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setWordWrap(False)
            brand_layout.addWidget(label)
        self.preparation_button = PreparationFactsButton()
        self.actions_widget = QWidget()
        self.actions_layout = QVBoxLayout(self.actions_widget)
        self.actions_layout.setContentsMargins(0, 0, 0, 0)
        self.actions_layout.setSpacing(0)
        self.method_selection = HeaderMethodSelection(button_height)
        self.actions_layout.addWidget(self.method_selection)
        self.method_selection.hide()
        self.generation_mode: str | None = None
        self._methods_visible = True
        self.right_widget = QWidget()
        right_layout = QHBoxLayout(self.right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        self.tools_slot = QWidget()
        self.tools_slot_layout = QVBoxLayout(self.tools_slot)
        self.tools_slot_layout.setContentsMargins(0, 0, edge_padding, 0)
        self.tools_slot_layout.addWidget(tools, 0, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        if update_controls is not None:
            update_controls.setParent(self.tools_slot)
        tools.layout().setContentsMargins(0, edge_padding, 0, 0)
        right_layout.addWidget(self.actions_widget, 0, Qt.AlignmentFlag.AlignTop)
        right_layout.addWidget(self.tools_slot, 0, Qt.AlignmentFlag.AlignTop)
        self.separator = QFrame(self)
        self.separator.setObjectName("workflowHeaderDivider")
        self.separator.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.separator.hide()
        self.divider_shadow = QWidget(self)
        self.divider_shadow.setObjectName("workflowHeaderDividerShadow")
        self.divider_shadow.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.divider_shadow.hide()
        self.facts_widget = self.preparation_button.facts_widget
        self.fact_labels = self.preparation_button.fact_labels
        self.facts: tuple[tuple[str, str], ...] = ()
        self._actions_visible = False
        self._refreshing = False
        self.preparation_button.hide()
        self.actions_widget.hide()
        self.grid.addWidget(self.preparation_button, 0, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.grid.addWidget(self.right_widget, 0, 2, Qt.AlignmentFlag.AlignRight)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, super().minimumSizeHint().height())

    def set_shadow_overlay_parent(self, parent: QWidget) -> None:
        """Paint the divider shadow over the following page without a layout gap."""
        self.divider_shadow.setParent(parent)
        self.refresh_layout()

    def set_generation_mode(self, mode: str | None, *, visible: bool = True) -> None:
        self.generation_mode = mode
        self._methods_visible = visible
        self.method_selection.set_active_mode(mode)
        self.refresh_layout()

    def set_actions_visible(self, visible: bool) -> None:
        self._actions_visible = visible
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
            methods_visible = self._actions_visible and self._methods_visible and self.generation_mode is not None
            self.method_selection.setVisible(methods_visible)
            self.actions_widget.setVisible(methods_visible)
            # Apply the height after stylesheet polishing, which otherwise
            # replaces QPushButton's minimum height with its compact text hint.
            for button in self.method_selection.buttons.values():
                button.ensurePolished()
                button.setFixedHeight(self.button_height)
            cell_width = max(
                button.sizeHint().width()
                for button in self.method_selection.buttons.values()
            )
            for button in self.method_selection.buttons.values():
                button.setMinimumWidth(cell_width)
            self.method_selection.buttons_layout.invalidate()
            self.method_selection.layout().invalidate()
            self.actions_layout.invalidate()
            tools_layout = self.tools_widget.layout()
            tools_content_height = self.tools_widget.sizeHint().height() - tools_layout.contentsMargins().top()
            update_visible = self.update_controls is not None and not self.update_controls.button.isHidden()
            if self.update_controls is not None:
                self.update_controls.setVisible(update_visible)
            if self.menu_version is not None and (update_visible or self._update_layout_active):
                for index, alignment in enumerate(self._menu_alignments):
                    self.menu_version.layout().itemAt(index).setAlignment(
                        Qt.AlignmentFlag.AlignHCenter if update_visible else alignment
                    )
                self.menu_version.layout().invalidate()
            for index in range(tools_layout.count()):
                tools_layout.itemAt(index).setAlignment(
                    Qt.AlignmentFlag.AlignHCenter if methods_visible or update_visible else Qt.AlignmentFlag.AlignRight
                )
            if update_visible:
                # Keep menu and version centered over the complete strip so
                # revealing the cancel button does not move either of them.
                self.tools_slot_layout.setContentsMargins(0, 0, 0, 0)
                self.tools_slot.setFixedWidth(max(
                    self.update_controls.preferred_width(),
                    self.tools_widget.sizeHint().width(),
                ))
            else:
                self.tools_slot_layout.setContentsMargins(0, 0, 0 if methods_visible else self.edge_padding, 0)
                self.tools_slot.setFixedWidth(
                    self.tools_widget.sizeHint().width() + self.edge_padding + (8 if methods_visible else 0)
                )
            self.right_widget.layout().invalidate()
            available = max(1, self.width())
            right_width = self.right_widget.sizeHint().width()
            preparation_visible = not self.preparation_button.isHidden()
            card_width = min(self.preparation_button.preferred_width(), max(1, available - right_width - 12)) if preparation_visible else 0
            gap = self.grid.horizontalSpacing()
            left_limit = card_width + gap if preparation_visible else 0
            right_limit = available - right_width - gap
            brand_width = self.brand_widget.sizeHint().width()
            brand_x = min(max((available - brand_width) // 2, left_limit), right_limit - brand_width)
            text_fits = brand_x >= left_limit
            self.layout_state = "full" if text_fits else "brand_hidden"
            self.brand_widget.setVisible(text_fits)
            self.grid.setColumnMinimumWidth(0, card_width)
            self.grid.setColumnMinimumWidth(2, right_width)
            self.preparation_button.setFixedWidth(card_width)
            brand_height = self.brand_widget.sizeHint().height()
            card_height = self.preparation_button.heightForWidth(card_width) if preparation_visible else 0
            actions_height = max(card_height, 2 * self.button_height) if methods_visible else 0
            if methods_visible:
                # Grow the caption, keeping the method buttons at their normal
                # height and their lower edge on the common header divider.
                self.method_selection.heading.setFixedHeight(actions_height - self.button_height)
                self.method_selection.layout().invalidate()
                self.actions_layout.invalidate()
            tools_top = max(0, (card_height - tools_content_height) // 2) if preparation_visible else self.edge_padding
            tools_layout.setContentsMargins(0, tools_top, 0, 0)
            # Alignment can change while these insets remain identical (for
            # example when opening the cards), so invalidate it explicitly.
            tools_layout.invalidate()
            self.tools_slot.setFixedHeight(max(card_height, actions_height, tools_content_height + tools_top))
            self.right_widget.layout().invalidate()
            tools_height = self.tools_slot.height()
            visible_brand_height = brand_height if text_fits else 0
            # Before confirmation the former lower page inset belongs to the
            # header now. Keep the brand's existing top/bottom breathing space
            # while allowing the preparation surface to touch the divider.
            center_inset = self.edge_padding if not preparation_visible else 0
            header_height = max(
                visible_brand_height + center_inset if text_fits else 0, tools_height,
                card_height, actions_height,
            )
            if preparation_visible:
                tools_top = max(0,(header_height-tools_content_height)//2)
                tools_layout.setContentsMargins(0,tools_top,0,0)
                tools_layout.invalidate()
            if update_visible:
                # Keep the menu's existing top position. Only extend the lower
                # edge when the compact update row cannot fit beneath it.
                header_height = max(
                    header_height, tools_top + tools_content_height + 4 + self.update_controls.HEIGHT,
                )
                self.tools_slot.setFixedHeight(header_height)
                self.update_controls.setGeometry(
                    0, header_height - self.update_controls.HEIGHT,
                    self.tools_slot.width(), self.update_controls.HEIGHT,
                )
                self.update_controls.layout().activate()
                if preparation_visible:
                    self.preparation_button.setMinimumHeight(header_height)
                if methods_visible:
                    self.method_selection.heading.setFixedHeight(header_height - self.button_height)
                    self.method_selection.layout().invalidate()
                    self.actions_layout.invalidate()
                self.right_widget.layout().invalidate()
            elif self._update_layout_active:
                self.preparation_button.setMinimumHeight(0)
            self._update_layout_active = update_visible
            header_height += center_inset
            self.tools_slot.setFixedHeight(header_height)
            if preparation_visible:
                self.preparation_button.setFixedHeight(header_height)
            if methods_visible:
                self.method_selection.heading.setFixedHeight(header_height-self.button_height)
                self.method_selection.layout().invalidate()
            if update_visible:
                self.update_controls.move(0,header_height-self.update_controls.HEIGHT)
            self.grid.setRowMinimumHeight(0, header_height)
            self.grid.invalidate()
            self.grid.activate()
            hint = self.brand_widget.sizeHint()
            self.brand_widget.setGeometry(
                brand_x, (header_height - hint.height()) // 2,
                hint.width(), hint.height(),
            )
            self.separator.setGeometry(0, max(0, header_height - 1), available, 1)
            self.separator.show()
            shadow_origin = self.mapTo(self.divider_shadow.parentWidget(), QPoint(0,header_height))
            self.divider_shadow.setGeometry(shadow_origin.x(),shadow_origin.y(),available,8)
            self.divider_shadow.show()
            self.divider_shadow.raise_()
            self.separator.raise_()
            self.updateGeometry()
        finally:
            self._refreshing = False

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.refresh_layout()

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        super().changeEvent(event)
        if hasattr(self, "_refreshing") and event.type() in {
            QEvent.Type.FontChange, QEvent.Type.StyleChange, QEvent.Type.DevicePixelRatioChange,
        }:
            self.refresh_layout()
