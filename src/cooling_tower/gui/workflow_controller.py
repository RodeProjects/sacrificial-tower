from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QWidget
from cooling_tower.gui.widgets import SectionCard, SectionState


class WorkflowStage(str, Enum):
    WAITING_FOR_GCODE = "waiting_for_gcode"
    ANALYZING_GCODE = "analyzing_gcode"
    GCODE_READY = "gcode_ready"
    SEARCHING_SLICER = "searching_slicer"
    READY = "ready"
    DEGRADED = "degraded"
    ERROR = "error"


class WorkflowController(QObject):
    """Coordinates progressive disclosure without owning domain operations."""

    stage_changed = Signal(str)

    def __init__(
        self,
        *,
        source_card: SectionCard,
        slicer_card: SectionCard,
        downstream_widgets: tuple[QWidget, ...],
        parent: QWidget,
        duration_ms: int = 0,
        first_success_duration_ms: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.source_card = source_card
        self.slicer_card = slicer_card
        self.downstream_widgets = downstream_widgets
        self.parent_widget = parent
        # Retained for constructor/API compatibility. All workflow transitions
        # are deliberately immediate.
        self.duration_ms = 0
        self.first_success_duration_ms = 0
        self.stage = WorkflowStage.WAITING_FOR_GCODE
        self._source_auto_collapsed = False
        self._slicer_auto_collapsed = False

    def reset(self) -> None:
        self._source_auto_collapsed = False
        self._slicer_auto_collapsed = False
        self.source_card.setCheckable(False)
        self.source_card.setChecked(True)
        self.source_card.set_summary("")
        self.source_card.set_summary_note(None)
        self.source_card.set_badge(None)
        self.source_card.set_state(SectionState.ACTIVE)
        self._set_source_prompt_icon(True)
        self.slicer_card.setCheckable(False)
        self.slicer_card.setChecked(True)
        self.slicer_card.set_summary("")
        self.slicer_card.set_summary_note(None)
        self.slicer_card.set_title_note(None)
        self.slicer_card.set_badge(None)
        self.slicer_card.set_state(SectionState.NEUTRAL)
        self.slicer_card.hide()
        for widget in self.downstream_widgets:
            widget.hide()
        self._set_stage(WorkflowStage.WAITING_FOR_GCODE)

    def begin_analysis(self) -> None:
        # Keep the upload arrow prominent from the empty prompt through the
        # whole analysis. The final result replaces it with a compact status
        # glyph after analysis has finished.
        self._set_source_prompt_icon(True)
        self.source_card.setCheckable(False)
        self.source_card.setChecked(True)
        self.source_card.set_summary("Analyse läuft")
        self.source_card.set_state(SectionState.ACTIVE)
        self.slicer_card.hide()
        for widget in self.downstream_widgets:
            widget.hide()
        self._set_stage(WorkflowStage.ANALYZING_GCODE)

    def analysis_failed(self) -> None:
        self._set_source_prompt_icon(False)
        self.source_card.setCheckable(False)
        self.source_card.setChecked(True)
        self.source_card.set_summary("Analyse fehlgeschlagen")
        self.source_card.set_state(SectionState.ERROR)
        self.slicer_card.hide()
        for widget in self.downstream_widgets:
            widget.hide()
        self._set_stage(WorkflowStage.ERROR)

    def analysis_succeeded(self, summary: str) -> None:
        self._set_source_prompt_icon(False)
        self.source_card.set_summary(summary)
        self.source_card.setCheckable(True)
        self.source_card.set_state(SectionState.SUCCESS)
        self._set_stage(WorkflowStage.GCODE_READY)

        if not self._source_auto_collapsed:
            self._source_auto_collapsed = True
            self.source_card.set_expanded(
                False,
                on_finished=lambda: self.slicer_card.show(),
            )
        else:
            self.slicer_card.show()

    def begin_slicer_search(self) -> None:
        self.slicer_card.setCheckable(False)
        self.slicer_card.setChecked(True)
        self.slicer_card.set_summary("Suche läuft")
        self.slicer_card.set_summary_note(None)
        self.slicer_card.set_title_note(None)
        self.slicer_card.set_state(SectionState.ACTIVE)
        if not self.slicer_card.isVisible() and not self._source_auto_collapsed:
            self.slicer_card.show()
        self._set_stage(WorkflowStage.SEARCHING_SLICER)

    def slicer_succeeded(self, summary: str) -> None:
        self.slicer_card.set_summary(summary)
        self.slicer_card.setCheckable(True)
        self.slicer_card.set_state(SectionState.SUCCESS)
        self._set_stage(WorkflowStage.READY)

        if not self._slicer_auto_collapsed:
            self._slicer_auto_collapsed = True
            self.slicer_card.set_expanded(
                False,
                on_finished=self._reveal_downstream,
            )
        else:
            self._reveal_downstream()

    def slicer_unavailable(self, summary: str) -> None:
        self.slicer_card.set_summary(summary)
        self.slicer_card.set_summary_note(None)
        self.slicer_card.set_title_note(None)
        self.slicer_card.set_state(SectionState.WARNING)
        self.slicer_card.setCheckable(True)
        self.slicer_card.setChecked(True)
        self._set_stage(WorkflowStage.DEGRADED)
        self._reveal_downstream()

    def update_slicer_summary(self, summary: str) -> None:
        if summary:
            self.slicer_card.set_summary(summary)

    def _reveal_downstream(self) -> None:
        for widget in self.downstream_widgets:
            widget.show()

    def _set_stage(self, stage: WorkflowStage) -> None:
        self.stage = stage
        self.stage_changed.emit(stage.value)

    def _set_source_prompt_icon(self, prominent: bool) -> None:
        icon = self.source_card.status_icon
        icon.setProperty("prominent", prominent)
        # The shift-arrow glyph contains more internal whitespace than the
        # later status glyphs.  Give the initial prompt enough real width so
        # the larger font is rendered completely instead of merely setting a
        # stylesheet property that remains optically unchanged.
        icon.setFixedWidth(28 if prominent else 18)
        style = icon.style()
        style.unpolish(icon)
        style.polish(icon)
