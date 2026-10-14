from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QEasingCurve, QObject, QPauseAnimation, QPropertyAnimation, Qt
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect, QLabel, QStackedWidget, QWidget


class ContentTransition(QObject):
    """Fade the old body out before fading the updated body in."""

    _INPUT_EVENTS = frozenset({
        QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
        QEvent.Type.MouseButtonDblClick, QEvent.Type.MouseMove, QEvent.Type.Wheel,
        QEvent.Type.KeyPress, QEvent.Type.KeyRelease, QEvent.Type.Shortcut,
        QEvent.Type.ShortcutOverride, QEvent.Type.InputMethod, QEvent.Type.ContextMenu,
        QEvent.Type.TouchBegin, QEvent.Type.TouchUpdate, QEvent.Type.TouchEnd,
        QEvent.Type.TouchCancel, QEvent.Type.TabletPress, QEvent.Type.TabletMove,
        QEvent.Type.TabletRelease, QEvent.Type.NativeGesture,
        QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.DragLeave, QEvent.Type.Drop,
    })

    def __init__(
        self, stack: QStackedWidget, *, duration_ms: int, pause_ms: int = 0,
    ) -> None:
        super().__init__(stack)
        self.stack = stack
        self.duration_ms = duration_ms
        self.pause_ms = pause_ms
        self._animation: QPropertyAnimation | QPauseAnimation | None = None
        self._overlay: QLabel | None = None
        self._page: QWidget | None = None
        self._input_blocked = False

    def run(self, change: Callable[[], None]) -> None:
        self.cancel()
        if self.duration_ms <= 0 or not self.stack.isVisible():
            change()
            return
        snapshot = self.stack.grab()
        page = self.stack.currentWidget()
        if page is None:
            change()
            return
        self._page = page
        self._block_input()
        hidden_page = QGraphicsOpacityEffect(page)
        hidden_page.setOpacity(0.0)
        page.setGraphicsEffect(hidden_page)
        overlay = QLabel(self.stack)
        overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        overlay.setPixmap(snapshot)
        overlay.setGeometry(self.stack.rect())
        overlay.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        overlay.setStyleSheet("background: transparent; border: none; padding: 0;")
        outgoing = QGraphicsOpacityEffect(overlay)
        outgoing.setOpacity(1.0)
        overlay.setGraphicsEffect(outgoing)
        self._overlay = overlay
        overlay.show()
        overlay.raise_()
        self._animate(outgoing, 1.0, 0.0, lambda: self._pause_before_fade_in(change))

    def _pause_before_fade_in(self, change: Callable[[], None]) -> None:
        if self.pause_ms <= 0:
            self._fade_in(change)
            return
        if self._animation is not None:
            self._animation.deleteLater()
        pause = QPauseAnimation(self.pause_ms, self)
        pause.finished.connect(lambda: self._fade_in(change))
        self._animation = pause
        pause.start()

    def _fade_in(self, change: Callable[[], None]) -> None:
        # Header/footer visibility can resize the stack. Apply those changes
        # only between the fades, while neither page is being painted.
        self.cancel()
        change()
        page = self.stack.currentWidget()
        if page is None or not self.stack.isVisible():
            return
        self._page = page
        self._block_input()
        incoming = QGraphicsOpacityEffect(page)
        incoming.setOpacity(0.0)
        page.setGraphicsEffect(incoming)
        self._animate(incoming, 0.0, 1.0, self.cancel)

    def _animate(
        self, effect: QGraphicsOpacityEffect, start: float, end: float,
        finished: Callable[[], None],
    ) -> None:
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(max(1, self.duration_ms // 2))
        animation.setStartValue(start)
        animation.setEndValue(end)
        animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        animation.finished.connect(finished)
        self._animation = animation
        animation.start()

    def _block_input(self) -> None:
        # Disabling the stack makes Qt paint both the QLabel snapshot and the
        # incoming controls in disabled colours. Filter input without changing
        # widget state, so the animation changes only their opacity.
        QApplication.instance().installEventFilter(self)
        self._input_blocked = True

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if self._input_blocked and event.type() in self._INPUT_EVENTS:
            target = watched
            while target is not None and not isinstance(target, QWidget):
                target = target.parent()
            if target is not None and (target is self.stack or self.stack.isAncestorOf(target)):
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def cancel(self) -> None:
        if self._input_blocked:
            QApplication.instance().removeEventFilter(self)
            self._input_blocked = False
        if self._animation is not None:
            self._animation.stop()
            self._animation.deleteLater()
            self._animation = None
        if self._overlay is not None:
            self._overlay.hide()
            self._overlay.deleteLater()
            self._overlay = None
        if self._page is not None:
            self._page.setGraphicsEffect(None)
            self._page = None
