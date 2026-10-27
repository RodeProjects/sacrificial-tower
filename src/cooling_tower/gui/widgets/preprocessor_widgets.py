"""Compact coordinates, colour keys and a content-sized postprocessor footer."""
from PySide6.QtCore import QEvent, QRect, QSize, QTimer, Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QLayout, QSizePolicy, QStyle, QStyleOptionSpinBox, QWidget

from cooling_tower.gui.design_tokens import METRICS
from cooling_tower.gui.widgets.manual_preview_info import LegendSwatch
from cooling_tower.gui.widgets.preview_canvas import PreviewCanvas
from cooling_tower.gui.widgets.committed_numeric_inputs import CommittedSpinBox


class CoordinatePair(QFrame):
    """A single two-line field, with independently accessible X/Y editors."""

    def __init__(self, x_editor, y_editor):
        super().__init__()
        self.setObjectName("coordinatePair")
        self.setFixedWidth(METRICS.form_editor_width_px)
        self.setStyleSheet("QFrame#coordinatePair { border: 1px solid #b8c5d1; border-radius: 6px; background: white; }"
            "QFrame#coordinatePair QDoubleSpinBox { border: none; border-radius: 0; min-height: 0; padding: 0 2px; }"
            "QFrame#coordinatePair QDoubleSpinBox:disabled { background: #edf1f5; color: #7a8794; }"
            "QFrame#coordinatePair QLabel { border: none; background: transparent; padding: 0; }")
        grid = QGridLayout(self)
        grid.setContentsMargins(6, 0, 0, 0)
        grid.setSpacing(0)
        self.axis_labels = []
        for i, (axis, colour, editor) in enumerate((("X", PreviewCanvas.X_AXIS_COLOR, x_editor),
                ("Y", PreviewCanvas.Y_AXIS_COLOR, y_editor))):
            label = QLabel(axis)
            label.setStyleSheet(f"color: {colour}; font-weight: bold;")
            label.setBuddy(editor)
            label.setFixedWidth(16)
            self.axis_labels.append(label)
            editor.setFixedSize(METRICS.form_editor_width_px - 24, 34)
            editor.setSuffix(" mm")
            grid.addWidget(label, i * 2, 0)
            grid.addWidget(editor, i * 2, 1)
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet("background: #d6dee8; border: none;")
        grid.addWidget(line, 1, 0, 1, 2)
        self.setFixedHeight(71)


class _LegendFlowLayout(QLayout):
    """Wrap whole legend entries in reading order at their natural widths."""

    def __init__(self, parent):
        super().__init__(parent)
        self._items = []
        self.setContentsMargins(0, 3, 0, 3)
        self.setSpacing(15)
        self._vertical_spacing = 5

    def addItem(self, item):  # noqa: N802
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def hasHeightForWidth(self):  # noqa: N802
        return True

    def heightForWidth(self, width):  # noqa: N802
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def minimumSize(self):  # noqa: N802
        size = QSize(0, 0)
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left()+margins.right(), margins.top()+margins.bottom())

    def sizeHint(self):  # noqa: N802
        margins = self.contentsMargins()
        width = sum(item.sizeHint().width() for item in self._items)
        width += max(0, len(self._items)-1)*self.spacing()+margins.left()+margins.right()
        return QSize(width, self.heightForWidth(width))

    def setGeometry(self, rect):  # noqa: N802
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def _arrange(self, rect, *, apply):
        margins = self.contentsMargins()
        left, top = rect.x()+margins.left(), rect.y()+margins.top()
        right = rect.x()+rect.width()-margins.right()
        x, y, row_height = left, top, 0
        sizes = [item.sizeHint().expandedTo(item.minimumSize()) for item in self._items]
        single_column = right-left <= max((size.width() for size in sizes), default=0)
        for item, size in zip(self._items, sizes):
            if x > left and (single_column or x+size.width() > right):
                x, y, row_height = left, y+row_height+self._vertical_spacing, 0
            if apply:
                item.setGeometry(QRect(x, y, size.width(), size.height()))
            x += size.width()+self.spacing()
            row_height = max(row_height, size.height())
        return y+row_height+margins.bottom()-rect.y()


class FlowColourLegend(QWidget):
    """A preview legend that uses the full row before wrapping each entry."""

    def __init__(self, entries):
        super().__init__()
        layout = _LegendFlowLayout(self)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.swatches, self.labels, self.entries = [], [], []
        for title, colour in entries:
            entry = QWidget(self)
            row = QHBoxLayout(entry)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            swatch, label = LegendSwatch(colour), QLabel(title)
            swatch.setAccessibleName(title)
            row.addWidget(swatch)
            row.addWidget(label)
            layout.addWidget(entry)
            self.swatches.append(swatch)
            self.labels.append(label)
            self.entries.append(entry)


class ColourLegend(QWidget):
    def __init__(self, entries, *, columns=3, column_major=False, horizontal_spacing=16, compact=False):
        super().__init__()
        if compact:
            entries_widget = QWidget(self)
            outer = QHBoxLayout(self)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.addWidget(entries_widget, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            outer.addStretch(1)
            grid = QGridLayout(entries_widget)
            grid.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
        else:
            grid = QGridLayout(self)
        grid.setContentsMargins(0, 3, 0, 3)
        grid.setHorizontalSpacing(horizontal_spacing)
        grid.setVerticalSpacing(5)
        if compact:
            grid.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.swatches, self.labels = [], []
        self._grid, self._entry_rows = grid, []
        self._columns, self._column_major = columns, column_major
        entries = tuple(entries)
        rows = max(1, (len(entries)+columns-1)//columns)
        for i, (title, colour) in enumerate(entries):
            row = QHBoxLayout()
            row.setSpacing(6)
            swatch, label = LegendSwatch(colour), QLabel(title)
            swatch.setAccessibleName(title)
            row.addWidget(swatch)
            row.addWidget(label)
            row.addStretch(1)
            grid.addLayout(row, i % rows if column_major else i // columns,
                i // rows if column_major else i % columns)
            self.swatches.append(swatch)
            self.labels.append(label)
            self._entry_rows.append(row)

    def intrinsic_width(self, columns):
        rows = max(1, (len(self._entry_rows)+columns-1)//columns)
        widths = [0]*columns
        for i, row in enumerate(self._entry_rows):
            column = i//rows if self._column_major else i % columns
            widths[column] = max(widths[column], row.minimumSize().width())
        margins = self._grid.contentsMargins()
        return sum(widths)+(columns-1)*self._grid.horizontalSpacing()+margins.left()+margins.right()

    def set_columns(self, columns):
        if columns == self._columns:
            return
        self._columns = columns
        rows = max(1, (len(self._entry_rows)+columns-1)//columns)
        for row in self._entry_rows:
            self._grid.removeItem(row)
        for i, row in enumerate(self._entry_rows):
            self._grid.addLayout(row, i % rows if self._column_major else i//columns,
                i//rows if self._column_major else i % columns)
        self._grid.invalidate()
        self._grid.activate()
        self.layout().invalidate()
        self.updateGeometry()


class LayerNumberSpinBox(CommittedSpinBox):
    """Fit the current integer and native controls, without reserving a unit area."""

    def __init__(self):
        super().__init__()
        self.setProperty("manualCompactInput", True)
        self.setWrapping(False)
        self._fitting = False
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(self.fit_text)
        self.lineEdit().textChanged.connect(self.fit_text)
        self.valueChanged.connect(self.fit_text)
        self.fit_text()

    def fit_text(self, *_):
        if self.lineEdit() is None or getattr(self, "_fitting", False):
            return
        self._fitting = True
        option = QStyleOptionSpinBox()
        self.initStyleOption(option)
        # Styled spin boxes reserve space differently at their actual width.
        # A synthetic 400px rectangle underestimates the native arrow column.
        option.rect = QRect(0, 0, self.width(), max(36, self.height()))
        editor = self.style().subControlRect(QStyle.ComplexControl.CC_SpinBox, option,
            QStyle.SubControl.SC_SpinBoxEditField, self)
        margins = self.lineEdit().textMargins()
        chrome = self.width()-editor.width()+margins.left()+margins.right()+10
        text = _[0] if _ and isinstance(_[0], str) else self.lineEdit().text()
        width = max(48, self.lineEdit().fontMetrics().horizontalAdvance(text or "1")+chrome)
        if self.width() != width:
            self.setFixedWidth(width)
        self._fitting = False

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self._fit_timer.start(0)

    def changeEvent(self, event):  # noqa: N802
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange, QEvent.Type.LocaleChange):
            self.fit_text()
            if hasattr(self, "_fit_timer"):
                self._fit_timer.start(0)


class PreprocessorFooter(QWidget):
    """Measure live wrapped messages, progress and actions after layout changes."""

    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(self.fit_content)

    def watch_content(self, columns, action_area, widgets):
        self.columns, self.action_area = columns, action_area
        self._breakpoint = None
        for widget in (self, columns, *widgets):
            widget.installEventFilter(self)
        self._fit_timer.start(0)

    def eventFilter(self, watched, event):  # noqa: N802
        if event.type() in (QEvent.Type.LayoutRequest, QEvent.Type.Show, QEvent.Type.Hide, QEvent.Type.Resize):
            self._fit_timer.start(0)
        return super().eventFilter(watched, event)

    def fit_content(self):
        if not hasattr(self, "columns") or not self.isVisible():
            return
        layout = self.layout()
        margins = layout.contentsMargins()
        breakpoint = max(METRICS.responsive_breakpoint_px, 2*self.action_area.minimumSizeHint().width()+12)
        if breakpoint != self._breakpoint:
            self._breakpoint = breakpoint
            self.columns.set_breakpoint(breakpoint)
        layout.activate()
        self.columns.layout().activate()
        height = self.columns.content_height_hint()
        if self.columns.height() != height:
            self.columns.setFixedHeight(height)
        required = height + margins.top() + margins.bottom()
        if self.height() != required:
            self.setFixedHeight(required)
        layout.activate()
