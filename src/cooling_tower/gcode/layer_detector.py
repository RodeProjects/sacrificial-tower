from __future__ import annotations

from dataclasses import dataclass

from cooling_tower.gcode.parser import Dwell, Movement


Z_EPSILON_MM = 1e-4
EXTRUSION_EPSILON_MM = 1e-9

TimedEvent = Movement | Dwell


@dataclass(frozen=True, slots=True)
class LayerRecord:
    index: int

    z_mm: float
    height_mm: float

    start_line: int
    first_deposition_line: int
    end_line: int

    event_count: int
    movement_count: int
    deposition_count: int

    total_time_s: float
    deposition_time_s: float
    travel_time_s: float
    retraction_time_s: float
    unretraction_time_s: float
    dwell_time_s: float
    other_time_s: float

    deposition_path_mm: float
    deposition_e_mm: float

    untimed_event_count: int
    untimed_distance_mm: float


@dataclass(frozen=True, slots=True)
class LayerAnalysis:
    layers: tuple[LayerRecord, ...]

    confirmed_layer_changes: int
    rejected_z_candidates: int

    pre_layer_event_count: int
    pre_layer_time_s: float
    pre_layer_untimed_event_count: int


@dataclass(slots=True)
class _LayerAccumulator:
    index: int

    z_mm: float
    height_mm: float

    start_line: int
    first_deposition_line: int
    end_line: int

    event_count: int = 0
    movement_count: int = 0
    deposition_count: int = 0

    total_time_s: float = 0.0
    deposition_time_s: float = 0.0
    travel_time_s: float = 0.0
    retraction_time_s: float = 0.0
    unretraction_time_s: float = 0.0
    dwell_time_s: float = 0.0
    other_time_s: float = 0.0

    deposition_path_mm: float = 0.0
    deposition_e_mm: float = 0.0

    untimed_event_count: int = 0
    untimed_distance_mm: float = 0.0

    def to_record(self) -> LayerRecord:
        return LayerRecord(
            index=self.index,

            z_mm=self.z_mm,
            height_mm=self.height_mm,

            start_line=self.start_line,
            first_deposition_line=self.first_deposition_line,
            end_line=self.end_line,

            event_count=self.event_count,
            movement_count=self.movement_count,
            deposition_count=self.deposition_count,

            total_time_s=self.total_time_s,
            deposition_time_s=self.deposition_time_s,
            travel_time_s=self.travel_time_s,
            retraction_time_s=self.retraction_time_s,
            unretraction_time_s=self.unretraction_time_s,
            dwell_time_s=self.dwell_time_s,
            other_time_s=self.other_time_s,

            deposition_path_mm=self.deposition_path_mm,
            deposition_e_mm=self.deposition_e_mm,

            untimed_event_count=self.untimed_event_count,
            untimed_distance_mm=self.untimed_distance_mm,
        )


class LayerDetector:
    """
    Detect printed layers by confirming increased Z positions through
    positive spatial extrusion.

    Temporary Z increases are buffered until they are either confirmed as a
    new layer or rejected as a Z-hop.
    """

    def __init__(self) -> None:
        self._completed_layers: list[LayerRecord] = []
        self._current_layer: _LayerAccumulator | None = None
        self._candidate_events: list[TimedEvent] = []

        self._confirmed_layer_changes = 0
        self._rejected_z_candidates = 0

        self._pre_layer_event_count = 0
        self._pre_layer_time_s = 0.0
        self._pre_layer_untimed_event_count = 0

    def process_event(self, event: TimedEvent) -> None:
        """
        Process one movement or dwell event.
        """
        if self._current_layer is None:
            self._process_before_first_layer(event)
            return

        if self._candidate_events:
            self._candidate_events.append(event)
            self._evaluate_candidate_event(event)
            return

        if (
            isinstance(event, Movement)
            and event.end_z > self._current_layer.z_mm + Z_EPSILON_MM
        ):
            self._candidate_events.append(event)
            self._evaluate_candidate_event(event)
            return

        self._add_event_to_layer(
            layer=self._current_layer,
            event=event,
        )

    def finish(self) -> LayerAnalysis:
        """
        Finalize layer detection at the end of the G-code file.
        """
        if self._candidate_events:
            self._reject_candidate()

        if self._current_layer is not None:
            self._completed_layers.append(
                self._current_layer.to_record()
            )
            self._current_layer = None

        return LayerAnalysis(
            layers=tuple(self._completed_layers),

            confirmed_layer_changes=self._confirmed_layer_changes,
            rejected_z_candidates=self._rejected_z_candidates,

            pre_layer_event_count=self._pre_layer_event_count,
            pre_layer_time_s=self._pre_layer_time_s,
            pre_layer_untimed_event_count=(
                self._pre_layer_untimed_event_count
            ),
        )

    def _process_before_first_layer(
        self,
        event: TimedEvent,
    ) -> None:
        if (
            isinstance(event, Movement)
            and self._is_positive_deposition(event)
        ):
            first_layer_z = event.end_z

            self._current_layer = _LayerAccumulator(
                index=1,

                z_mm=first_layer_z,
                height_mm=max(0.0, first_layer_z),

                start_line=event.line_number,
                first_deposition_line=event.line_number,
                end_line=event.line_number,
            )

            self._add_event_to_layer(
                layer=self._current_layer,
                event=event,
            )
            return

        self._pre_layer_event_count += 1

        duration_s = event.duration_s

        if duration_s is None:
            self._pre_layer_untimed_event_count += 1
        else:
            self._pre_layer_time_s += duration_s

    def _evaluate_candidate_event(
        self,
        event: TimedEvent,
    ) -> None:
        if not isinstance(event, Movement):
            return

        if self._current_layer is None:
            return

        if (
            self._is_positive_deposition(event)
            and event.end_z > self._current_layer.z_mm + Z_EPSILON_MM
        ):
            self._confirm_candidate(
                new_layer_z=event.end_z,
                first_deposition_line=event.line_number,
            )
            return

        if event.end_z <= self._current_layer.z_mm + Z_EPSILON_MM:
            self._reject_candidate()

    def _confirm_candidate(
        self,
        *,
        new_layer_z: float,
        first_deposition_line: int,
    ) -> None:
        if self._current_layer is None:
            raise RuntimeError(
                "Cannot confirm a new layer without a current layer."
            )

        if not self._candidate_events:
            raise RuntimeError(
                "Cannot confirm a new layer without candidate events."
            )

        previous_layer = self._current_layer

        self._completed_layers.append(
            previous_layer.to_record()
        )

        start_line = self._candidate_events[0].line_number
        layer_height = new_layer_z - previous_layer.z_mm

        new_layer = _LayerAccumulator(
            index=previous_layer.index + 1,

            z_mm=new_layer_z,
            height_mm=layer_height,

            start_line=start_line,
            first_deposition_line=first_deposition_line,
            end_line=first_deposition_line,
        )

        for buffered_event in self._candidate_events:
            self._add_event_to_layer(
                layer=new_layer,
                event=buffered_event,
            )

        self._candidate_events.clear()
        self._current_layer = new_layer
        self._confirmed_layer_changes += 1

    def _reject_candidate(self) -> None:
        if self._current_layer is None:
            self._candidate_events.clear()
            return

        for buffered_event in self._candidate_events:
            self._add_event_to_layer(
                layer=self._current_layer,
                event=buffered_event,
            )

        self._candidate_events.clear()
        self._rejected_z_candidates += 1

    @staticmethod
    def _is_positive_deposition(
        movement: Movement,
    ) -> bool:
        return (
            movement.category == "deposition"
            and movement.delta_e > EXTRUSION_EPSILON_MM
        )

    @staticmethod
    def _add_event_to_layer(
        *,
        layer: _LayerAccumulator,
        event: TimedEvent,
    ) -> None:
        layer.event_count += 1
        layer.end_line = max(
            layer.end_line,
            event.line_number,
        )

        if isinstance(event, Dwell):
            if event.duration_s is None:
                layer.untimed_event_count += 1
            else:
                layer.total_time_s += event.duration_s
                layer.dwell_time_s += event.duration_s

            return

        movement = event
        layer.movement_count += 1

        if movement.category == "deposition":
            layer.deposition_count += 1

            if movement.path_length_mm is not None:
                layer.deposition_path_mm += movement.path_length_mm

            if movement.delta_e > 0.0:
                layer.deposition_e_mm += movement.delta_e

        if movement.duration_s is None:
            layer.untimed_event_count += 1

            if movement.timing_distance_mm is not None:
                layer.untimed_distance_mm += (
                    movement.timing_distance_mm
                )

            return

        duration_s = movement.duration_s
        layer.total_time_s += duration_s

        if movement.category == "deposition":
            layer.deposition_time_s += duration_s

        elif movement.category in {
            "travel",
            "travel_with_retraction",
        }:
            layer.travel_time_s += duration_s

        elif movement.category == "retraction":
            layer.retraction_time_s += duration_s

        elif movement.category == "unretraction":
            layer.unretraction_time_s += duration_s

        else:
            layer.other_time_s += duration_s
