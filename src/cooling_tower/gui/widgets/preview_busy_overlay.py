"""Native, clock-driven preview animation independent of Python worker frames."""
from PySide6.QtCore import QByteArray, QElapsedTimer, QEvent, Qt
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from cooling_tower.gui.widgets.activity_progress_bar import ActivityProgressBar
from cooling_tower.gui.widgets.preview_busy_svg import busy_svg


class PreviewBusyOverlay(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._busy = self._subdued = False
        self._protected_region = None
        self._clock = QElapsedTimer()
        self._scene_dirty = True
        self._rebuilding = False
        self.surface = QSvgWidget(self)
        # The SVG contains one frozen scene image. Opaque native painting keeps
        # Qt from calling the Python canvas again underneath every animation frame.
        self.surface.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.surface.setStyleSheet("background: #171a20; border: none;")
        self.panel = QFrame(self)
        self.panel.setObjectName("previewBusyPanel")
        self.panel.setStyleSheet("QFrame#previewBusyPanel { background: rgba(24, 34, 47, 240); border: 1px solid #486176; border-radius: 10px; }"
            "QFrame#previewBusyPanel QLabel { color: #d9e9f5; background: transparent; border: none; }")
        layout = QVBoxLayout(self.panel)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        self.title = QLabel()
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title)
        self.progress = ActivityProgressBar()
        self.progress.setObjectName("mainProgressBar")
        self.progress.setStyleSheet("QProgressBar { background: #263c50; border: 1px solid #526f85; border-radius: 5px; }"
            "QProgressBar::chunk { background: #286f9d; border-radius: 4px; }")
        self.progress.setRange(0, 100)
        layout.addWidget(self.progress)
        self.step = QLabel()
        self.step.setTextFormat(Qt.TextFormat.PlainText)
        self.step.setWordWrap(True)
        self.step.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.step)
        parent.installEventFilter(self)
        self.hide()

    def invalidate_background(self):
        self._scene_dirty = True

    def refresh_background(self):
        self.invalidate_background()
        if self._busy:
            self._reload_scene()

    def set_busy(self, active, *, percent=0, step="", title="Berechnung läuft", subdued=False, protected_region=None):
        changed = active != self._busy
        self._scene_dirty |= subdued != self._subdued
        self._subdued, self._protected_region = subdued, protected_region
        self.title.setText(title)
        self.progress.setValue(percent)
        self.step.setText(step)
        if changed:
            self._busy = active
            if active:
                self._clock.start()
                self._scene_dirty = True
            else:
                self.hide()
                self._clock.invalidate()
        if active:
            self._position()
            if self._scene_dirty:
                self._reload_scene()
            self.panel.setVisible(not subdued)
            self.show()
            self.raise_()
            self.panel.raise_()

    def _position(self):
        self.setGeometry(self.parentWidget().rect())
        self.surface.setGeometry(self.rect())
        width = min(520, max(180, self.width()-40))
        self.panel.setFixedWidth(width)
        self.panel.layout().activate()
        height = self.panel.heightForWidth(width) if self.panel.hasHeightForWidth() else self.panel.sizeHint().height()
        self.panel.setGeometry((self.width()-width)//2, (self.height()-height)//2, width, height)

    def _reload_scene(self):
        if self._rebuilding or self.width() <= 0 or self.height() <= 0:
            return
        self._rebuilding = True
        visible = self.isVisible()
        try:
            self.hide()
            background = self.parentWidget().grab().toImage()
            protected = self._protected_region() if self._subdued and self._protected_region is not None else None
            svg = busy_svg(background, self.width(), self.height(), elapsed_ms=max(0, self._clock.elapsed()), protected=protected)
            self.surface.load(QByteArray(svg))
            self.surface.renderer().setFramesPerSecond(60)
            self.surface.renderer().setAnimationEnabled(self._busy and self.parentWidget().isVisible())
            self._scene_dirty = False
        finally:
            self._rebuilding = False
            if visible:
                self.show()

    def eventFilter(self, watched, event):  # noqa: N802
        if event.type() == QEvent.Type.Resize:
            self._position()
            if self._busy:
                self.refresh_background()
        return super().eventFilter(watched, event)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self.surface.renderer().setAnimationEnabled(self._busy)

    def hideEvent(self, event):  # noqa: N802
        self.surface.renderer().setAnimationEnabled(False)
        super().hideEvent(event)
