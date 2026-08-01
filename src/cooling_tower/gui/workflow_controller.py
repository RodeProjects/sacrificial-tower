from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QWidget
from cooling_tower.gui.widgets import SectionCard, SectionState


class WorkflowStage(str, Enum):
    WAITING_FOR_SOURCE = "waiting_for_source"
    VALIDATING_SOURCE = "validating_source"
    ANALYZING_GCODE = "analyzing_gcode"
    VALIDATING_STL = "validating_stl"
    SOURCE_INVALID = "source_invalid"
    DISCOVERING_SLICER = "discovering_slicer"
    MATCHING_PROFILES = "matching_profiles"
    WAITING_FOR_PROFILE_CONFIRMATION = "waiting_for_profile_confirmation"
    PRESLICING_MODEL = "preslicing_model"
    ANALYZING_PRESLICE = "analyzing_preslice"
    READY = "ready"
    DEGRADED = "degraded"
    ERROR = "error"

    # Compatibility aliases for callers from the former G-code-only UI.
    WAITING_FOR_GCODE = WAITING_FOR_SOURCE
    GCODE_READY = DISCOVERING_SLICER
    SEARCHING_SLICER = DISCOVERING_SLICER


_ALLOWED_TRANSITIONS: dict[WorkflowStage, frozenset[WorkflowStage]] = {
    WorkflowStage.WAITING_FOR_SOURCE: frozenset(
        {
            WorkflowStage.VALIDATING_SOURCE,
            WorkflowStage.ANALYZING_GCODE,
            WorkflowStage.VALIDATING_STL,
            # Restored sessions may already hold a completed analysis.
            WorkflowStage.DISCOVERING_SLICER,
            WorkflowStage.MATCHING_PROFILES,
            # Discovery results can be restored before a source card is
            # hydrated (session restore and deterministic UI tests).
            WorkflowStage.READY,
            WorkflowStage.DEGRADED,
            WorkflowStage.ERROR,
        }
    ),
    WorkflowStage.VALIDATING_SOURCE: frozenset(
        {
            WorkflowStage.ANALYZING_GCODE,
            WorkflowStage.VALIDATING_STL,
            WorkflowStage.SOURCE_INVALID,
            WorkflowStage.ERROR,
        }
    ),
    WorkflowStage.ANALYZING_GCODE: frozenset(
        {
            WorkflowStage.VALIDATING_SOURCE,
            WorkflowStage.VALIDATING_STL,
            WorkflowStage.DISCOVERING_SLICER,
            WorkflowStage.SOURCE_INVALID,
            WorkflowStage.ERROR,
        }
    ),
    WorkflowStage.VALIDATING_STL: frozenset(
        {
            WorkflowStage.VALIDATING_SOURCE,
            WorkflowStage.ANALYZING_GCODE,
            WorkflowStage.DISCOVERING_SLICER,
            WorkflowStage.SOURCE_INVALID,
            WorkflowStage.ERROR,
        }
    ),
    WorkflowStage.SOURCE_INVALID: frozenset(
        {
            WorkflowStage.VALIDATING_SOURCE,
            WorkflowStage.ANALYZING_GCODE,
            WorkflowStage.VALIDATING_STL,
            WorkflowStage.ERROR,
        }
    ),
    WorkflowStage.DISCOVERING_SLICER: frozenset(
        {
            # Selecting/reloading another direct G-code is permitted while
            # the slicer card is already visible.
            WorkflowStage.VALIDATING_SOURCE,
            WorkflowStage.ANALYZING_GCODE,
            WorkflowStage.VALIDATING_STL,
            WorkflowStage.DISCOVERING_SLICER,
            WorkflowStage.MATCHING_PROFILES,
            WorkflowStage.WAITING_FOR_PROFILE_CONFIRMATION,
            WorkflowStage.READY,
            WorkflowStage.DEGRADED,
            WorkflowStage.ERROR,
        }
    ),
    WorkflowStage.MATCHING_PROFILES: frozenset(
        {
            WorkflowStage.VALIDATING_SOURCE,
            WorkflowStage.ANALYZING_GCODE,
            WorkflowStage.VALIDATING_STL,
            WorkflowStage.DISCOVERING_SLICER,
            WorkflowStage.WAITING_FOR_PROFILE_CONFIRMATION,
            WorkflowStage.READY,
            WorkflowStage.DEGRADED,
            WorkflowStage.ERROR,
        }
    ),
    WorkflowStage.WAITING_FOR_PROFILE_CONFIRMATION: frozenset(
        {
            WorkflowStage.VALIDATING_SOURCE,
            WorkflowStage.ANALYZING_GCODE,
            WorkflowStage.VALIDATING_STL,
            WorkflowStage.PRESLICING_MODEL,
            WorkflowStage.READY,
            WorkflowStage.MATCHING_PROFILES,
            WorkflowStage.ERROR,
        }
    ),
    WorkflowStage.PRESLICING_MODEL: frozenset(
        {
            WorkflowStage.VALIDATING_SOURCE,
            WorkflowStage.ANALYZING_GCODE,
            WorkflowStage.VALIDATING_STL,
            WorkflowStage.ANALYZING_PRESLICE,
            WorkflowStage.MATCHING_PROFILES,
            WorkflowStage.ERROR,
        }
    ),
    WorkflowStage.ANALYZING_PRESLICE: frozenset(
        {
            WorkflowStage.VALIDATING_SOURCE,
            WorkflowStage.ANALYZING_GCODE,
            WorkflowStage.VALIDATING_STL,
            WorkflowStage.MATCHING_PROFILES,
            WorkflowStage.READY,
            WorkflowStage.ERROR,
        }
    ),
    WorkflowStage.READY: frozenset(
        {
            WorkflowStage.READY,
            WorkflowStage.VALIDATING_SOURCE,
            WorkflowStage.VALIDATING_STL,
            WorkflowStage.ANALYZING_GCODE,
            WorkflowStage.DISCOVERING_SLICER,
            WorkflowStage.MATCHING_PROFILES,
            WorkflowStage.DEGRADED,
            WorkflowStage.ERROR,
        }
    ),
    WorkflowStage.DEGRADED: frozenset(
        {
            WorkflowStage.DEGRADED,
            WorkflowStage.VALIDATING_SOURCE,
            WorkflowStage.VALIDATING_STL,
            WorkflowStage.ANALYZING_GCODE,
            WorkflowStage.DISCOVERING_SLICER,
            WorkflowStage.MATCHING_PROFILES,
            WorkflowStage.READY,
            WorkflowStage.ERROR,
        }
    ),
    WorkflowStage.ERROR: frozenset(
        {
            WorkflowStage.VALIDATING_SOURCE,
            WorkflowStage.ANALYZING_GCODE,
            WorkflowStage.VALIDATING_STL,
            WorkflowStage.DISCOVERING_SLICER,
            WorkflowStage.MATCHING_PROFILES,
            WorkflowStage.ERROR,
        }
    ),
}


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
        self.stage = WorkflowStage.WAITING_FOR_SOURCE
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
        self._set_stage(WorkflowStage.WAITING_FOR_SOURCE, force=True)

    def can_transition_to(self, stage: WorkflowStage) -> bool:
        return stage is self.stage or stage in _ALLOWED_TRANSITIONS[self.stage]

    def begin_source_validation(self, *, is_stl: bool = False) -> None:
        self._prepare_source_activity("Quelle wird geprüft")
        self._set_stage(
            WorkflowStage.VALIDATING_STL
            if is_stl
            else WorkflowStage.VALIDATING_SOURCE
        )

    def source_invalid(self, summary: str) -> None:
        self._set_source_prompt_icon(False)
        self.source_card.set_summary_note(None)
        self.source_card.setCheckable(False)
        self.source_card.setChecked(True)
        self.source_card.set_summary(summary)
        self.source_card.set_state(SectionState.ERROR)
        self.slicer_card.hide()
        for widget in self.downstream_widgets:
            widget.hide()
        self._set_stage(WorkflowStage.SOURCE_INVALID)

    def _prepare_source_activity(self, summary: str) -> None:
        self._set_source_prompt_icon(True)
        self.source_card.set_summary_note(None)
        self.source_card.setCheckable(False)
        self.source_card.setChecked(True)
        self.source_card.set_summary(summary)
        self.source_card.set_state(SectionState.ACTIVE)
        self.slicer_card.hide()
        for widget in self.downstream_widgets:
            widget.hide()

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

    def begin_preslice_analysis(self) -> None:
        self.source_card.setCheckable(False)
        self.source_card.setChecked(True)
        self.source_card.set_summary("Pre-Slice wird analysiert")
        self.source_card.set_state(SectionState.ACTIVE)
        self.slicer_card.show()
        self.slicer_card.set_summary("Slicer-Ausgabe wird geprüft")
        self.slicer_card.set_state(SectionState.ACTIVE)
        for widget in self.downstream_widgets:
            widget.hide()
        self._set_stage(WorkflowStage.ANALYZING_PRESLICE)

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
        self.source_validation_succeeded(summary)

    def source_validation_succeeded(self, summary: str) -> None:
        self._set_source_prompt_icon(False)
        self.source_card.set_summary(summary)
        self.source_card.setCheckable(True)
        self.source_card.set_state(SectionState.SUCCESS)
        self._set_stage(WorkflowStage.DISCOVERING_SLICER)

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
        self._set_stage(WorkflowStage.DISCOVERING_SLICER)

    def begin_profile_matching(self) -> None:
        self._set_stage(WorkflowStage.MATCHING_PROFILES)

    def wait_for_profile_confirmation(self) -> None:
        self._set_stage(WorkflowStage.WAITING_FOR_PROFILE_CONFIRMATION)

    def begin_preslice(self) -> None:
        self.slicer_card.show()
        self.slicer_card.setCheckable(False)
        self.slicer_card.setChecked(True)
        self.slicer_card.set_summary("Modell wird geslict")
        self.slicer_card.set_state(SectionState.ACTIVE)
        for widget in self.downstream_widgets:
            widget.hide()
        self._set_stage(WorkflowStage.PRESLICING_MODEL)

    def preslice_succeeded(
        self,
        source_summary: str,
        slicer_summary: str,
    ) -> None:
        self.source_card.set_summary(source_summary)
        self.source_card.setCheckable(True)
        self.source_card.set_state(SectionState.SUCCESS)
        self.source_card.set_expanded(False)
        self.slicer_card.show()
        self.slicer_card.set_summary(slicer_summary)
        self.slicer_card.setCheckable(True)
        self.slicer_card.set_state(SectionState.SUCCESS)
        self._set_stage(WorkflowStage.READY)
        self.slicer_card.set_expanded(False, on_finished=self._reveal_downstream)

    def preslice_failed(self, summary: str) -> None:
        self.source_card.setCheckable(True)
        self.source_card.setChecked(True)
        self.source_card.set_summary(summary)
        self.source_card.set_state(SectionState.ERROR)
        self.slicer_card.show()
        self.slicer_card.setCheckable(True)
        self.slicer_card.setChecked(True)
        self.slicer_card.set_state(SectionState.ERROR)
        for widget in self.downstream_widgets:
            widget.hide()
        self._set_stage(WorkflowStage.ERROR)

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

    def required_slicer_unavailable(self, summary: str) -> None:
        """Block STL processing when no verified CLI slicer is available."""

        self.slicer_card.set_summary(summary)
        self.slicer_card.set_summary_note(None)
        self.slicer_card.set_title_note(None)
        self.slicer_card.set_state(SectionState.ERROR)
        self.slicer_card.setCheckable(True)
        self.slicer_card.setChecked(True)
        for widget in self.downstream_widgets:
            widget.hide()
        self._set_stage(WorkflowStage.ERROR)

    def update_slicer_summary(self, summary: str) -> None:
        if summary:
            self.slicer_card.set_summary(summary)

    def _reveal_downstream(self) -> None:
        for widget in self.downstream_widgets:
            widget.show()

    def _set_stage(self, stage: WorkflowStage, *, force: bool = False) -> None:
        if not force and not self.can_transition_to(stage):
            raise ValueError(
                f"Ungültiger Workflowübergang: {self.stage.value} -> {stage.value}"
            )
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
