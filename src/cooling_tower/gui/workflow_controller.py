from __future__ import annotations

from enum import Enum

from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QParallelAnimationGroup,
    QPropertyAnimation,
    Signal,
)
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget
from cooling_tower.gui.widgets import SectionCard, SectionState


class WorkflowStage(str, Enum):
    WAITING_FOR_SOURCE = "waiting_for_source"
    VALIDATING_SOURCE = "validating_source"
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

    SEARCHING_SLICER = DISCOVERING_SLICER


_ALLOWED_TRANSITIONS: dict[WorkflowStage, frozenset[WorkflowStage]] = {
    WorkflowStage.WAITING_FOR_SOURCE: frozenset(
        {
            WorkflowStage.VALIDATING_SOURCE,
            WorkflowStage.VALIDATING_STL,
            WorkflowStage.DISCOVERING_SLICER,
            WorkflowStage.MATCHING_PROFILES,
            WorkflowStage.WAITING_FOR_PROFILE_CONFIRMATION,
            WorkflowStage.READY,
            WorkflowStage.DEGRADED,
            WorkflowStage.ERROR,
        }
    ),
    WorkflowStage.VALIDATING_SOURCE: frozenset(
        {
            WorkflowStage.VALIDATING_STL,
            WorkflowStage.DISCOVERING_SLICER,
            WorkflowStage.SOURCE_INVALID,
            WorkflowStage.ERROR,
        }
    ),
    WorkflowStage.VALIDATING_STL: frozenset(
        {
            WorkflowStage.VALIDATING_SOURCE,
            WorkflowStage.DISCOVERING_SLICER,
            WorkflowStage.SOURCE_INVALID,
            WorkflowStage.ERROR,
        }
    ),
    WorkflowStage.SOURCE_INVALID: frozenset(
        {
            WorkflowStage.VALIDATING_SOURCE,
            WorkflowStage.VALIDATING_STL,
            WorkflowStage.ERROR,
        }
    ),
    WorkflowStage.DISCOVERING_SLICER: frozenset(
        {
            WorkflowStage.VALIDATING_SOURCE,
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
            WorkflowStage.VALIDATING_STL,
            WorkflowStage.ANALYZING_PRESLICE,
            WorkflowStage.MATCHING_PROFILES,
            WorkflowStage.ERROR,
        }
    ),
    WorkflowStage.ANALYZING_PRESLICE: frozenset(
        {
            WorkflowStage.VALIDATING_SOURCE,
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
            WorkflowStage.DISCOVERING_SLICER,
            WorkflowStage.MATCHING_PROFILES,
            WorkflowStage.READY,
            WorkflowStage.ERROR,
        }
    ),
    WorkflowStage.ERROR: frozenset(
        {
            WorkflowStage.VALIDATING_SOURCE,
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
        self.duration_ms = max(0, int(duration_ms))
        self.first_success_duration_ms = max(
            0,
            int(
                duration_ms
                if first_success_duration_ms is None
                else first_success_duration_ms
            ),
        )
        self.stage = WorkflowStage.WAITING_FOR_SOURCE
        self._source_auto_collapsed = False
        self._slicer_auto_collapsed = False
        self._workflow_auto_collapsed = False
        self._source_complete = False
        self._slicer_complete = False
        self._slicer_step_visible = workflow_card is None
        self._deferred_slicer_feedback: tuple[str, tuple[object, ...]] | None = None
        self._reveal_animation: QParallelAnimationGroup | None = None

    def reset(self) -> None:
        self._source_auto_collapsed = False
        self._slicer_auto_collapsed = False
        self._workflow_auto_collapsed = False
        self._source_complete = False
        self._slicer_complete = False
        self._slicer_step_visible = self.workflow_card is None
        self._deferred_slicer_feedback = None
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
            self.workflow_card.setCheckable(False)
            self.workflow_card.setChecked(True)
            self.workflow_card.set_summary("Bitte Vorbereitungen abschließen")
            self.workflow_card.set_summary_note(None)
            self.workflow_card.set_badge(None)
            self.workflow_card.set_state(SectionState.ACTIVE, icon="⇧")
        self._hide_downstream()
        self._set_stage(WorkflowStage.WAITING_FOR_SOURCE, force=True)

    def set_slicer_step_visible(self, visible: bool) -> None:
        """Publish deferred Slicer feedback only after step 2 is opened."""

        self._slicer_step_visible = bool(visible)
        if not self._slicer_step_visible:
            self._show_source_step_summary()
            return
        if self._deferred_slicer_feedback is None:
            self._show_slicer_step_summary()
            return
        method_name, arguments = self._deferred_slicer_feedback
        self._deferred_slicer_feedback = None
        getattr(self, method_name)(*arguments)

    def _show_source_step_summary(self) -> None:
        """Keep Slicer-only feedback out of the file-transfer step."""

        if self.workflow_card is None or self.stage is WorkflowStage.READY:
            return
        source_state = self.source_card.state()
        if source_state is SectionState.ERROR:
            self._set_workflow_incomplete(
                "Datei prüfen und Fehler beheben",
                SectionState.ERROR,
            )
        elif source_state is SectionState.SUCCESS:
            self._set_workflow_incomplete(
                "Dateiübergabe abgeschlossen · weiter mit Schritt 2",
                SectionState.ACTIVE,
            )
        else:
            self._set_workflow_incomplete(
                "Datei auswählen und prüfen",
                SectionState.ACTIVE,
            )

    def _show_slicer_step_summary(self) -> None:
        """Restore the current Slicer result when step 2 is revisited."""

        if self.workflow_card is None or self.stage is WorkflowStage.READY:
            return
        slicer_state = self.slicer_card.state()
        if slicer_state is SectionState.ERROR:
            self._set_workflow_incomplete(
                "Slicer-Einstellungen prüfen",
                SectionState.ERROR,
            )
        elif slicer_state is SectionState.WARNING:
            self._set_workflow_incomplete(
                "Slicer-Erkennung oder Bestätigung erforderlich",
                SectionState.WARNING,
            )
        else:
            self._set_workflow_incomplete(
                "Slicer und Profile festlegen",
                SectionState.ACTIVE,
            )

    def _defer_slicer_feedback(
        self,
        method_name: str,
        *arguments: object,
    ) -> bool:
        if self._slicer_step_visible:
            return False
        self._deferred_slicer_feedback = (method_name, arguments)
        return True

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

    def begin_preslice_analysis(self) -> None:
        self.slicer_card.show()
        self.slicer_card.set_summary("Modell wird mit Slicer-Ausgabe geprüft")
        self.slicer_card.set_state(SectionState.ACTIVE)
        self._source_complete = False
        self._slicer_complete = False
        if self.workflow_card is not None:
            self._set_workflow_incomplete(
                "Slicer-Ausgabe wird analysiert",
                SectionState.ACTIVE,
            )
        self._hide_downstream()
        self._set_stage(WorkflowStage.ANALYZING_PRESLICE)

    def source_validation_succeeded(
        self,
        summary: str,
        *,
        analysis_complete: bool = True,
    ) -> None:
        # The file-transfer step is complete as soon as the STL itself is
        # valid. The internal Pre-Slice remains a prerequisite of step 2.
        self._source_complete = bool(analysis_complete)
        self._set_source_prompt_icon(False)
        self.source_card.set_summary(summary)
        self.source_card.setCheckable(self.workflow_card is None)
        self.source_card.set_state(SectionState.SUCCESS)
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
        if self._defer_slicer_feedback("begin_slicer_search"):
            return
        if self.workflow_card is not None:
            self._set_workflow_incomplete(
                "Slicer werden erkannt und geprüft",
                SectionState.ACTIVE,
            )
            self._hide_downstream()
        self._set_stage(WorkflowStage.DISCOVERING_SLICER)

    def begin_profile_matching(self) -> None:
        self._slicer_complete = False
        if self._defer_slicer_feedback("begin_profile_matching"):
            return
        if self.workflow_card is not None:
            self._set_workflow_incomplete(
                "Slicer-Profile werden geprüft",
                SectionState.ACTIVE,
            )
            self._hide_downstream()
        self._set_stage(WorkflowStage.MATCHING_PROFILES)

    def wait_for_profile_confirmation(self) -> None:
        self._slicer_complete = False
        if self._defer_slicer_feedback("wait_for_profile_confirmation"):
            return
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
        if self._defer_slicer_feedback("begin_preslice"):
            return
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
        self.slicer_card.show()
        self.slicer_card.setCheckable(self.workflow_card is None)
        self.slicer_card.setChecked(True)
        self.slicer_card.set_summary(summary)
        self.slicer_card.set_state(SectionState.ERROR)
        if self._defer_slicer_feedback("preslice_failed", summary):
            return
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
        if self._defer_slicer_feedback("slicer_succeeded", summary):
            return
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
        if self._defer_slicer_feedback("slicer_unavailable", summary):
            return
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
        if self._defer_slicer_feedback(
            "required_slicer_unavailable",
            summary,
        ):
            return
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
        card.setCheckable(False)
        card.set_summary(summary)
        card.set_summary_note(None)
        card.set_badge(None)
        card.set_state(state, icon="⇧")
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
        card.set_state(SectionState.SUCCESS, icon="⇧")

        def reveal_ready_state() -> None:
            self._set_stage(WorkflowStage.READY)
            self._reveal_downstream()

        if not self._workflow_auto_collapsed:
            self._workflow_auto_collapsed = True
            card.set_expanded(False)
            reveal_ready_state()
        else:
            reveal_ready_state()

    def _hide_downstream(self) -> None:
        if self._reveal_animation is not None:
            self._reveal_animation.stop()
            self._reveal_animation = None
        for widget in self.downstream_widgets:
            widget.setGraphicsEffect(None)
            widget.hide()

    def _reveal_downstream(self) -> None:
        if self.duration_ms <= 0 or not self.parent_widget.isVisible():
            for widget in self.downstream_widgets:
                widget.setGraphicsEffect(None)
                widget.show()
            return
        group = QParallelAnimationGroup(self)
        self._reveal_animation = group
        for widget in self.downstream_widgets:
            effect = QGraphicsOpacityEffect(widget)
            effect.setOpacity(0.0)
            widget.setGraphicsEffect(effect)
            widget.show()
            animation = QPropertyAnimation(effect, b"opacity", group)
            animation.setStartValue(0.0)
            animation.setEndValue(1.0)
            animation.setDuration(self.duration_ms)
            animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
            group.addAnimation(animation)

        def finish() -> None:
            for widget in self.downstream_widgets:
                widget.setGraphicsEffect(None)
            self._reveal_animation = None

        group.finished.connect(finish)
        group.start()

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
