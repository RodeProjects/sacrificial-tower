from __future__ import annotations

from math import ceil

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt
from PySide6.QtGui import QFontMetrics, QTextDocument
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QVBoxLayout, QWidget


class HintPopover(QFrame):
    """A compact hint bubble that is always clipped to its owning window."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("hintPopover")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # The popover can overlap its small trigger in compact dialogs.  It
        # must never become the mouse target there, otherwise Qt alternates
        # Enter/Leave events on the trigger while the pointer is still over
        # the information icon and the hint visibly flickers.
        self.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            True,
        )
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        self.label = QLabel(self)
        self.label.setObjectName("hintPopoverText")
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.label)

        self.hide()

    def show_for(self, target: QWidget, text: str, *, duration_ms: int = 15_000,
                 unwrapped_line: str | None = None) -> None:
        hint = text.strip()
        owner = self.parentWidget()
        if not hint or owner is None:
            self.hide()
            return

        self.label.setMinimumHeight(0)
        self.label.setMaximumHeight(16777215)
        self.label.setText(hint)
        self.label.ensurePolished()
        available = owner.rect().adjusted(8, 8, -8, -8)
        anchor = QRect(
            target.mapTo(owner, QPoint(0, 0)),
            target.size(),
        )
        metrics = QFontMetrics(self.label.font())
        natural_width = metrics.horizontalAdvance(hint.replace("\n", " ")) + 30
        line_width = metrics.horizontalAdvance(unwrapped_line) + 30 if unwrapped_line else 0
        attractive_limit = min(max(520, line_width), available.width())
        if anchor.center().x() >= available.center().x():
            edge_capacity = max(180, anchor.right() - available.left() + 1)
        else:
            edge_capacity = max(180, available.right() - anchor.left() + 1)
        # A requested complete line may extend past the anchor; final placement
        # still keeps the entire bubble inside the owning window.
        edge_capacity = max(edge_capacity, line_width)
        width = max(180, min(natural_width, attractive_limit, edge_capacity))
        self.label.setFixedWidth(max(120, width - 24))
        if hint.startswith("<"):
            # QLabel can underestimate wrapped HTML by one or more lines,
            # especially when a table is followed by another paragraph.
            # Measure the complete document at the label's actual width.
            document = QTextDocument()
            document.setDefaultFont(self.label.font())
            document.setDocumentMargin(0)
            document.setHtml(hint)
            document.setTextWidth(self.label.width())
            self.label.setFixedHeight(ceil(document.size().height()))
        self.adjustSize()

        if anchor.center().x() >= available.center().x():
            x = anchor.right() - self.width() + 1
        else:
            x = anchor.left()
        x = max(available.left(), min(x, available.right() - self.width() + 1))
        y = anchor.bottom() + 7
        if y + self.height() > available.bottom() + 1:
            y = anchor.top() - self.height() - 7
        y = max(available.top(), min(y, available.bottom() - self.height() + 1))

        self.move(x, y)
        self.raise_()
        self.show()

    def hide_hint(self) -> None:
        """Hide the bubble immediately when its trigger is no longer hovered."""

        self.hide()


def show_window_hint(
    target: QWidget,
    text: str,
    *,
    duration_ms: int = 15_000,
    unwrapped_line: str | None = None,
) -> HintPopover | None:
    """Show a reusable popover inside ``target``'s top-level window."""

    owner = target.window()
    if not isinstance(owner, QWidget):
        return None
    popover = getattr(owner, "_bounded_hint_popover", None)
    if not isinstance(popover, HintPopover):
        popover = HintPopover(owner)
        setattr(owner, "_bounded_hint_popover", popover)
    popover.show_for(target, text, duration_ms=duration_ms, unwrapped_line=unwrapped_line)
    return popover


def hide_window_hint(target: QWidget) -> None:
    """Hide the reusable hint popover belonging to ``target``'s window."""

    owner = target.window()
    popover = getattr(owner, "_bounded_hint_popover", None)
    if isinstance(popover, HintPopover):
        popover.hide_hint()


class WindowHintController(QObject):
    """Replace native tooltips below one window with bounded popovers."""

    def __init__(self, root: QWidget) -> None:
        super().__init__(root)
        self.root = root
        self._active_target: QWidget | None = None
        application = QApplication.instance()
        if application is not None:
            application.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if not isinstance(watched, QWidget):
            return super().eventFilter(watched, event)
        try:
            belongs_to_window = watched is self.root or self.root.isAncestorOf(watched)
        except RuntimeError:
            # Qt can emit final application events after the native window was
            # already destroyed (notably during interpreter shutdown).
            self.dispose()
            return False
        if not belongs_to_window:
            return super().eventFilter(watched, event)
        if event.type() == QEvent.Type.Leave and watched is self._active_target:
            hide_window_hint(watched)
            self._active_target = None
            return super().eventFilter(watched, event)
        if event.type() != QEvent.Type.ToolTip:
            return super().eventFilter(watched, event)
        hint = watched.toolTip().strip()
        # Locked wizard actions deliberately remain disabled, but still need
        # the same bounded explanation as their corresponding step selector.
        # Qt continues to deliver tooltip events for disabled child widgets.
        if not hint:
            return super().eventFilter(watched, event)
        show_window_hint(watched, hint)
        self._active_target = watched
        event.accept()
        return True

    def dispose(self) -> None:
        if self._active_target is not None:
            hide_window_hint(self._active_target)
            self._active_target = None
        application = QApplication.instance()
        if application is not None:
            application.removeEventFilter(self)
