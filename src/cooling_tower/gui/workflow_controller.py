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
            WorkflowStage.WAITING_FOR_PROFILE_CONFIRMATION,
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
            # A source-independent profile confirmation can carry directly
            # into an STL pre-slice after the exact bundle was validated.
            WorkflowStage.PRESLICING_MODEL,
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
            # Before a source exists, confirming the loaded catalogue marks
            # the Slicer side complete while the workflow still awaits input.
            WorkflowStage.DISCOVERING_SLICER,
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
        workflow_card: SectionCard | None = None,
        downstream_widgets: tuple[QWidget, ...],
        parent: QWidget,
        duration_ms: int = 0,
        first_success_duration_ms: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.source_card = source_card
        self.slicer_card = slicer_card
        self.workflow_card = workflow_card
        self.downstream_widgets = downstream_widgets
        self.parent_widget = parent
        # Retained for constructor/API compatibility. All workflow transitions
        # are deliberately immediate.
        self.duration_ms = 0
        self.first_success_duration_ms = 0
        self.stage = WorkflowStage.WAITING_FOR_SOURCE
        self._source_auto_collapsed = False
        self._slicer_auto_collapsed = False
        self._workflow_auto_collapsed = False
        self._source_complete = False
        self._slicer_complete = False

    def reset(self) -> None:
        self._source_auto_collapsed = False
        self._slicer_auto_collapsed = False
        self._workflow_auto_collapsed = False
        self._source_complete = False
        self._slicer_complete = False
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
        if self.workflow_card is None:
            self.slicer_card.hide()
        else:
            self.source_card.show()
            self.slicer_card.show()
            self.workflow_card.setCheckable(True)
            self.workflow_card.setChecked(True)
            self.workflow_card.set_summary("Datei und Slicer abschließen")
            self.workflow_card.set_summary_note(None)
            self.workflow_card.set_badge(None)
            self.workflow_card.set_state(SectionState.ACTIVE)
        self._hide_downstream()
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
        self._source_complete = False
        self._slicer_complete = False
        self._set_source_prompt_icon(False)
        self.source_card.set_summary_note(None)
        self.source_card.setCheckable(False)
        self.source_card.setChecked(True)
        self.source_card.set_summary(summary)
        self.source_card.set_state(SectionState.ERROR)
        if self.workflow_card is None:
            self.slicer_card.hide()
        else:
            self.slicer_card.show()
            self._set_workflow_incomplete(
                "Datei prüfen und Fehler beheben",
                SectionState.ERROR,
            )
        self._hide_downstream()
        self._set_stage(WorkflowStage.SOURCE_INVALID)

    def _prepare_source_activity(self, summary: str) -> None:
        self._source_complete = False
        self._slicer_complete = False
        self._workflow_auto_collapsed = False
        self._set_source_prompt_icon(True)
        self.source_card.set_summary_note(None)
        self.source_card.setCheckable(False)
        self.source_card.setChecked(True)
        self.source_card.set_summary(summary)
        self.source_card.set_state(SectionState.ACTIVE)
        if self.workflow_card is None:
            self.slicer_card.hide()
        else:
            self.slicer_card.show()
            self.slicer_card.set_state(SectionState.NEUTRAL)
            self._set_workflow_incomplete(
                "Datei wird geprüft",
                SectionState.ACTIVE,
            )
        self._hide_downstream()

    def begin_analysis(self) -> None:
        # Keep the upload arrow prominent from the empty prompt through the
        # whole analysis. The final result replaces it with a compact status
        # glyph after analysis has finished.
        self._prepare_source_activity("Analyse läuft")
        self._set_stage(WorkflowStage.ANALYZING_GCODE)

    def begin_preslice_analysis(self) -> None:
        self.source_card.setCheckable(False)
        self.source_card.setChecked(True)
        self.source_card.set_summary("Pre-Slice wird analysiert")
        self.source_card.set_state(SectionState.ACTIVE)
        self.slicer_card.show()
        self.slicer_card.set_summary("Slicer-Ausgabe wird geprüft")
        self.slicer_card.set_state(SectionState.ACTIVE)
        self._source_complete = False
        self._slicer_complete = False
        if self.workflow_card is not None:
            self._set_workflow_incomplete(
                "Erzeugter G-Code wird analysiert",
                SectionState.ACTIVE,
            )
        self._hide_downstream()
        self._set_stage(WorkflowStage.ANALYZING_PRESLICE)

    def analysis_failed(self) -> None:
        self._source_complete = False
        self._slicer_complete = False
        self._set_source_prompt_icon(False)
        self.source_card.setCheckable(False)
        self.source_card.setChecked(True)
        self.source_card.set_summary("Analyse fehlgeschlagen")
        self.source_card.set_state(SectionState.ERROR)
        if self.workflow_card is None:
            self.slicer_card.hide()
        else:
            self.slicer_card.show()
            self._set_workflow_incomplete(
                "Dateianalyse fehlgeschlagen",
                SectionState.ERROR,
            )
        self._hide_downstream()
        self._set_stage(WorkflowStage.ERROR)

    def analysis_succeeded(self, summary: str) -> None:
        self.source_validation_succeeded(summary, analysis_complete=True)

    def source_validation_succeeded(
        self,
        summary: str,
        *,
        analysis_complete: bool = True,
    ) -> None:
        # A valid STL is only an intermediate result. It becomes a completed
        # source prerequisite after the generated Pre-Slice G-code has also
        # been analysed and bound to the current file/profile context.
        self._source_complete = bool(analysis_complete)
        self._set_source_prompt_icon(False)
        self.source_card.set_summary(summary)
        self.source_card.setCheckable(self.workflow_card is None)
        self.source_card.set_state(
            SectionState.SUCCESS if analysis_complete else SectionState.ACTIVE
        )
        self._set_stage(WorkflowStage.DISCOVERING_SLICER)

        if self.workflow_card is not None:
            self.slicer_card.show()
            self._set_workflow_incomplete(
                "Datei analysiert · Slicer bestätigen",
                SectionState.ACTIVE,
            )
        elif not self._source_auto_collapsed:
            self._source_auto_collapsed = True
            self.source_card.set_expanded(
                False,
                on_finished=lambda: self.slicer_card.show(),
            )
        else:
            self.slicer_card.show()

    def begin_slicer_search(self) -> None:
        self._slicer_complete = False
        self.slicer_card.setCheckable(False)
        self.slicer_card.setChecked(True)
        self.slicer_card.set_summary("Suche läuft")
        self.slicer_card.set_summary_note(None)
        self.slicer_card.set_title_note(None)
        self.slicer_card.set_state(SectionState.ACTIVE)
        if not self.slicer_card.isVisible() and not self._source_auto_collapsed:
            self.slicer_card.show()
        if self.workflow_card is not None:
            self._set_workflow_incomplete(
                "Slicer werden erkannt und geprüft",
                SectionState.ACTIVE,
            )
            self._hide_downstream()
        self._set_stage(WorkflowStage.DISCOVERING_SLICER)

    def begin_profile_matching(self) -> None:
        self._slicer_complete = False
        if self.workflow_card is not None:
            self._set_workflow_incomplete(
                "Slicer-Profile werden geprüft",
                SectionState.ACTIVE,
            )
            self._hide_downstream()
        self._set_stage(WorkflowStage.MATCHING_PROFILES)

    def wait_for_profile_confirmation(self) -> None:
        self._slicer_complete = False
        if self.workflow_card is not None:
            self._set_workflow_incomplete(
                "Slicer und Profile bestätigen",
                SectionState.ACTIVE,
            )
            self._hide_downstream()
        self._set_stage(WorkflowStage.WAITING_FOR_PROFILE_CONFIRMATION)

    def begin_preslice(self) -> None:
        self._source_complete = False
        self._slicer_complete = False
        self.slicer_card.show()
        self.slicer_card.setCheckable(False)
        self.slicer_card.setChecked(True)
        self.slicer_card.set_summary("Modell wird geslict")
        self.slicer_card.set_state(SectionState.ACTIVE)
        if self.workflow_card is not None:
            self._set_workflow_incomplete(
                "STL wird geslict und anschließend analysiert",
                SectionState.ACTIVE,
            )
        self._hide_downstream()
        self._set_stage(WorkflowStage.PRESLICING_MODEL)

    def preslice_succeeded(
        self,
        source_summary: str,
        slicer_summary: str,
    ) -> None:
        self.source_card.set_summary(source_summary)
        self.source_card.setCheckable(self.workflow_card is None)
        self.source_card.set_state(SectionState.SUCCESS)
        if self.workflow_card is None:
            self.source_card.set_expanded(False)
        self.slicer_card.show()
        self.slicer_card.set_summary(slicer_summary)
        self.slicer_card.setCheckable(self.workflow_card is None)
        self.slicer_card.set_state(SectionState.SUCCESS)
        self._source_complete = True
        self._slicer_complete = True
        if self.workflow_card is not None:
            self._finish_combined_workflow()
        else:
            self._set_stage(WorkflowStage.READY)
            self.slicer_card.set_expanded(
                False,
                on_finished=self._reveal_downstream,
            )

    def preslice_failed(self, summary: str) -> None:
        self._source_complete = False
        self._slicer_complete = False
        self.source_card.setCheckable(self.workflow_card is None)
        self.source_card.setChecked(True)
        self.source_card.set_summary(summary)
        self.source_card.set_state(SectionState.ERROR)
        self.slicer_card.show()
        self.slicer_card.setCheckable(self.workflow_card is None)
        self.slicer_card.setChecked(True)
        self.slicer_card.set_state(SectionState.ERROR)
        if self.workflow_card is not None:
            self._set_workflow_incomplete(
                "STL-Verarbeitung fehlgeschlagen",
                SectionState.ERROR,
            )
        self._hide_downstream()
        self._set_stage(WorkflowStage.ERROR)

    def slicer_succeeded(self, summary: str) -> None:
        self._slicer_complete = True
        self.slicer_card.set_summary(summary)
        self.slicer_card.setCheckable(self.workflow_card is None)
        self.slicer_card.set_state(SectionState.SUCCESS)
        if self.workflow_card is not None:
            if self._source_complete:
                self._finish_combined_workflow()
            else:
                self._set_workflow_incomplete(
                    "Dateianalyse noch nicht abgeschlossen",
                    SectionState.ACTIVE,
                )
                self._hide_downstream()
                self._set_stage(WorkflowStage.DISCOVERING_SLICER)
            return
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
        self._slicer_complete = False
        self.slicer_card.set_summary(summary)
        self.slicer_card.set_summary_note(None)
        self.slicer_card.set_title_note(None)
        self.slicer_card.set_state(SectionState.WARNING)
        self.slicer_card.setCheckable(self.workflow_card is None)
        self.slicer_card.setChecked(True)
        self._set_stage(WorkflowStage.DEGRADED)
        if self.workflow_card is None:
            self._reveal_downstream()
        else:
            self._set_workflow_incomplete(
                "Slicer-Erkennung oder Bestätigung erforderlich",
                SectionState.WARNING,
            )
            self._hide_downstream()

    def required_slicer_unavailable(self, summary: str) -> None:
        """Block STL processing when no verified CLI slicer is available."""

        self._slicer_complete = False
        self.slicer_card.set_summary(summary)
        self.slicer_card.set_summary_note(None)
        self.slicer_card.set_title_note(None)
        self.slicer_card.set_state(SectionState.ERROR)
        self.slicer_card.setCheckable(self.workflow_card is None)
        self.slicer_card.setChecked(True)
        if self.workflow_card is not None:
            self._set_workflow_incomplete(
                "Kein verwendbarer Slicer bestätigt",
                SectionState.ERROR,
            )
        self._hide_downstream()
        self._set_stage(WorkflowStage.ERROR)

    def update_slicer_summary(self, summary: str) -> None:
        if summary:
            self.slicer_card.set_summary(summary)

    def _set_workflow_incomplete(
        self,
        summary: str,
        state: SectionState,
    ) -> None:
        card = self.workflow_card
        if card is None:
            return
        self._workflow_auto_collapsed = False
        card.setCheckable(True)
        card.set_summary(summary)
        card.set_summary_note(None)
        card.set_badge(None)
        card.set_state(state)
        card.set_expanded(True)

    def _finish_combined_workflow(self) -> None:
        """Close and unlock only after both current prerequisites succeeded."""

        card = self.workflow_card
        if card is None or not (self._source_complete and self._slicer_complete):
            self._hide_downstream()
            return
        self.source_card.setCheckable(False)
        self.source_card.set_state(SectionState.SUCCESS)
        self.slicer_card.setCheckable(False)
        self.slicer_card.set_state(SectionState.SUCCESS)
        card.setCheckable(True)
        card.set_summary("Vorbereitung abgeschlossen")
        card.set_summary_note(None)
        card.set_badge(None)
        card.set_state(SectionState.SUCCESS)

        def reveal_ready_state() -> None:
            self._set_stage(WorkflowStage.READY)
            self._reveal_downstream()

        if not self._workflow_auto_collapsed:
            self._workflow_auto_collapsed = True
            card.set_expanded(False, on_finished=reveal_ready_state)
        else:
            reveal_ready_state()

    def _hide_downstream(self) -> None:
        for widget in self.downstream_widgets:
            widget.hide()

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
