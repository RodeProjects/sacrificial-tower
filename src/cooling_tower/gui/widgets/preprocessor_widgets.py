"""Compact coordinates, colour keys and a content-sized postprocessor footer."""
from PySide6.QtCore import QEvent, QRect, QTimer, Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QLayout, QStyle, QStyleOptionSpinBox, QWidget

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
