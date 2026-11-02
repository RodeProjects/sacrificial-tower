"""Independent native-project footer sizing."""
from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtWidgets import QWidget
from cooling_tower.gui.design_tokens import METRICS


class NativeFooter(QWidget):
    """Measure live wrapped messages, progress and actions after layout changes."""

    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(self.fit_content)

    def watch_content(self, columns, action_area, widgets, *, fit_actions=None):
        self.columns, self.action_area = columns, action_area
        self._fit_actions = fit_actions
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
        if self._fit_actions is not None:
            narrow = self._fit_actions(max(0, self.width()-margins.left()-margins.right()))
            breakpoint = self.width()+1 if narrow else 1
        else:
            breakpoint = max(METRICS.responsive_breakpoint_px, 2*self.action_area.minimumSizeHint().width()+12)
        if breakpoint != self._breakpoint:
            self._breakpoint = breakpoint
            self.columns.set_breakpoint(breakpoint)
        layout.activate()
        self.columns.layout().activate()
        # Stacking adds a divider and a second layout gap between the areas.
        height = max(self.columns.content_height_hint(), self.columns.layout().minimumSize().height())
        if self.columns.height() != height:
            self.columns.setFixedHeight(height)
        required = height + margins.top() + margins.bottom()
        if self.height() != required:
            self.setFixedHeight(required)
        layout.activate()
