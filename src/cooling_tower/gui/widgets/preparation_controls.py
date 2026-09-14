from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Callable
from PySide6.QtCore import QEasingCurve, QParallelAnimationGroup, QPoint, QPropertyAnimation, Qt, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QLabel, QStackedWidget, QTabWidget, QWidget, QPushButton, QFrame, QHBoxLayout, QProgressBar

class _SequentialPreparationTabs(QTabWidget):
    """Guarded preparation pages with a directional card transition."""

    step_blocked = Signal(int)
    transition_started = Signal(int, int, int)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        transition_duration_ms: int = 500,
    ) -> None:
        super().__init__(parent)
        self.transition_duration_ms = max(0, int(transition_duration_ms))
        self._effective_transition_duration_ms = (
            0
            if os.environ.get("QT_QPA_PLATFORM", "").casefold()
            == "offscreen"
            else self.transition_duration_ms
        )
        self._step_guard: Callable[[int], bool] | None = None
        self._transition_targets: tuple[QWidget, ...] = ()
        self._transition_prepare: Callable[[], None] | None = None
        self._transition_animation: QParallelAnimationGroup | None = None
        self._transition_viewport: QWidget | None = None
        self._transition_overlays: list[QLabel] = []
        self._pending_transition_index: int | None = None
        self.last_transition: tuple[int, int, int] | None = None
        self.last_blocked_index: int | None = None

    def set_step_guard(self, guard: Callable[[int], bool]) -> None:
        self._step_guard = guard

    def set_transition_targets(
        self,
        targets: tuple[QWidget, ...],
        prepare_layout: Callable[[], None],
    ) -> None:
        self._transition_targets = targets
        self._transition_prepare = prepare_layout

    def can_navigate_to(self, index: int) -> bool:
        return (
            0 <= index < self.count()
            and (self._step_guard is None or self._step_guard(index))
        )

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802 - Qt API
        if self._transition_animation is not None:
            return
        current_index = super().currentIndex()
        if index == current_index:
            return
        if not self.can_navigate_to(index):
            self.last_blocked_index = index
            self.step_blocked.emit(index)
            return
        self.last_blocked_index = None
        self.last_transition = (
            current_index,
            index,
            self.transition_duration_ms,
        )
        self.transition_started.emit(
            current_index,
            index,
            self.transition_duration_ms,
        )
        if (
            current_index < 0
            or self._effective_transition_duration_ms <= 0
            or not self.isVisible()
        ):
            super().setCurrentIndex(index)
            return
        self._animate_to(index)

    def _animate_to(self, index: int) -> None:
        stack = self.findChild(QStackedWidget)
        old_index = super().currentIndex()
        if (
            stack is None
            or stack.width() <= 0
            or not (0 <= old_index < len(self._transition_targets))
            or not (0 <= index < len(self._transition_targets))
        ):
            super().setCurrentIndex(index)
            return
        self._finish_transition()
        old_target = self._transition_targets[old_index]
        new_target = self._transition_targets[index]
        old_pixmap = old_target.grab()
        old_position = old_target.mapTo(stack, QPoint(0, 0))
        old_tab_height = self.height()

        # Lay out and capture the target page synchronously while signals are
        # blocked.  No paint event can expose it before the old page is
        # restored, and currentChanged is emitted only after the animation.
        signals_were_blocked = self.blockSignals(True)
        try:
            super().setCurrentIndex(index)
            if self._transition_prepare is not None:
                self._transition_prepare()
            new_pixmap = new_target.grab()
            new_position = new_target.mapTo(stack, QPoint(0, 0))
            new_tab_height = self.height()
            super().setCurrentIndex(old_index)
            if self._transition_prepare is not None:
                self._transition_prepare()
        finally:
            self.blockSignals(signals_were_blocked)

        if old_pixmap.isNull() or new_pixmap.isNull():
            super().setCurrentIndex(index)
            return

        viewport_width = max(old_pixmap.width(), new_pixmap.width())
        viewport_left = max(0, (stack.width() - viewport_width) // 2)
        viewport_top = min(old_position.y(), new_position.y())
        viewport_bottom = max(
            old_position.y() + old_pixmap.height(),
            new_position.y() + new_pixmap.height(),
        )
        viewport_height = max(1, viewport_bottom - viewport_top)
        self.setFixedHeight(max(old_tab_height, new_tab_height))

        viewport = QWidget(stack)
        viewport.setObjectName("preparationTransitionViewport")
        viewport.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        viewport.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            True,
        )
        viewport.setGeometry(
            viewport_left,
            viewport_top,
            viewport_width,
            viewport_height,
        )
        viewport.show()
        viewport.raise_()
        self._transition_viewport = viewport

        direction = 1 if index > old_index else -1
        old_overlay = QLabel(viewport)
        new_overlay = QLabel(viewport)
        for overlay, pixmap in (
            (old_overlay, old_pixmap),
            (new_overlay, new_pixmap),
        ):
            overlay.setObjectName("preparationTransitionOverlay")
            overlay.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents,
                True,
            )
            overlay.setPixmap(
                pixmap
            )
            overlay.resize(pixmap.size())
            overlay.show()
            overlay.raise_()
        old_start = QPoint(
            old_position.x() - viewport_left,
            old_position.y() - viewport_top,
        )
        new_end = QPoint(
            new_position.x() - viewport_left,
            new_position.y() - viewport_top,
        )
        old_overlay.move(old_start)
        new_overlay.move(
            new_end + QPoint(direction * viewport_width, 0)
        )
        self._transition_overlays = [old_overlay, new_overlay]
        self._pending_transition_index = index

        animation_group = QParallelAnimationGroup(self)
        for overlay, end_position in (
            (
                old_overlay,
                old_start + QPoint(-direction * viewport_width, 0),
            ),
            (new_overlay, new_end),
        ):
            animation = QPropertyAnimation(overlay, b"pos", animation_group)
            animation.setDuration(self._effective_transition_duration_ms)
            animation.setStartValue(overlay.pos())
            animation.setEndValue(end_position)
            animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
            animation_group.addAnimation(animation)
        animation_group.finished.connect(self._complete_transition)
        self._transition_animation = animation_group
        animation_group.start()

    def _complete_transition(self) -> None:
        index = self._pending_transition_index
        self._finish_transition()
        if index is None:
            return
        super().setCurrentIndex(index)
        if self._transition_prepare is not None:
            self._transition_prepare()

    def _finish_transition(self) -> None:
        animation = self._transition_animation
        self._transition_animation = None
        self._pending_transition_index = None
        if animation is not None:
            animation.stop()
            animation.deleteLater()
        for overlay in self._transition_overlays:
            overlay.hide()
            overlay.deleteLater()
        self._transition_overlays.clear()
        viewport = self._transition_viewport
        self._transition_viewport = None
        if viewport is not None:
            viewport.hide()
            viewport.deleteLater()


@dataclass(frozen=True, slots=True)
class _PreparationState:
    """One immutable snapshot used by every preparation UI affordance."""

    source_selected: bool
    source_accepted: bool
    slicer_detected: bool
    profiles_loaded: bool
    profiles_confirmed: bool
    model_analyzed: bool

    @property
    def step1_completed(self) -> bool:
        return self.source_selected and self.source_accepted

    @property
    def step2_completed(self) -> bool:
        return all(
            (
                self.slicer_detected,
                self.profiles_loaded,
                self.profiles_confirmed,
                self.model_analyzed,
            )
        )

    @property
    def preparation_completed(self) -> bool:
        return self.step1_completed and self.step2_completed

    def requirements(self) -> dict[str, bool]:
        return {
            "source_selected": self.source_selected,
            "source_validated": self.source_accepted,
            "slicer_detected": self.slicer_detected,
            "profiles_loaded": self.profiles_loaded,
            "profiles_confirmed": self.profiles_confirmed,
            "model_analyzed": self.model_analyzed,
        }


class _PreparationStepSelector(QPushButton):
    """Step selector that exposes its hover state to the complete card."""

    hover_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._progress_value = 0
        self.progress_label = QLabel("0 %", self)
        self.progress_label.setObjectName("preparationStepProgressLabel")
        self.progress_label.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight
        )
        self.progress_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            True,
        )
        # Progress belongs to the preparation as a whole.  The value remains
        # available for accessibility and compatibility, but is no longer
        # painted as a separate per-step bar.
        self.progress_label.hide()

    def set_progress_value(self, value: int) -> None:
        """Update the step progress exposed to accessibility and tests."""

        progress_value = max(0, min(100, int(value)))
        if progress_value == self._progress_value:
            return
        self._progress_value = progress_value
        self.progress_label.setText(f"{progress_value} %")
        self.update()

    @property
    def progress_value(self) -> int:
        """Return the percentage fulfilled inside this preparation step."""

        return self._progress_value

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        label_width = 44
        self.progress_label.setGeometry(
            max(0, self.width() - label_width - 7),
            4,
            label_width,
            15,
        )
        self.progress_label.raise_()

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().paintEvent(event)

    def enterEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self.hover_changed.emit(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self.hover_changed.emit(False)
        super().leaveEvent(event)


class _PreparationRequirementsPanel(QFrame):
    """Passive prerequisite summary inside one preparation step."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)


class _ConfirmationProgressBar(QProgressBar):
    """Progress bar with stable, readable text and a larger activity glyph."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._display_format = ""
        self.setTextVisible(False)
        self.overlay = QWidget(self)
        self.overlay.setObjectName("profileConfirmationProgressOverlay")
        self.overlay.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            True,
        )
        overlay_layout = QHBoxLayout(self.overlay)
        overlay_layout.setContentsMargins(8, 0, 8, 0)
        overlay_layout.setSpacing(6)
        overlay_layout.addStretch(1)
        self.text_label = QLabel()
        self.text_label.setObjectName("profileConfirmationProgressText")
        self.text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.activity_label = QLabel()
        self.activity_label.setObjectName("profileConfirmationActivity")
        self.activity_label.setFixedWidth(28)
        self.activity_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        activity_font = self.activity_label.font()
        activity_font.setPointSizeF(max(17.0, activity_font.pointSizeF() + 7.0))
        activity_font.setBold(True)
        self.activity_label.setFont(activity_font)
        overlay_layout.addWidget(self.text_label)
        overlay_layout.addWidget(self.activity_label)
        overlay_layout.addStretch(1)

    def setFormat(self, text: str) -> None:  # noqa: N802
        self._display_format = str(text)
        super().setFormat(text)
        self._sync_overlay_text()

    def setValue(self, value: int) -> None:  # noqa: N802
        super().setValue(value)
        self._sync_overlay_text()

    def set_activity_frame(self, frame: str) -> None:
        self.activity_label.setText(str(frame))
        self.activity_label.update()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.overlay.setGeometry(self.rect())

    def _sync_overlay_text(self) -> None:
        if not hasattr(self, "text_label"):
            return
        text = self._display_format
        if "%p" in text and self.maximum() > self.minimum():
            text = text.replace("%p", str(self.value()))
        self.text_label.setText(text)
