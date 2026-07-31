from __future__ import annotations

import hashlib
import json
import math
import shutil
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import Callable

from cooling_tower.diagnostic_context import record_diagnostic
from cooling_tower.file_integrity import sha256_file
from cooling_tower.calibration.convergence import evaluate_convergence
from cooling_tower.calibration.gcode_integration import (
    GCodeIntegrationError,
    GCodeIntegrator,
    assess_gcode_support,
    determine_occupied_bounds,
    parse_bed_bounds,
    propose_tower_placement,
)
from cooling_tower.calibration.profile_adjuster import adjust_radius_profile
from cooling_tower.calibration.slice_evaluator import (
    SliceEvaluator,
    build_calibration_profile,
)
from cooling_tower.models import (
    CalibrationConfig,
    CalibrationFailure,
    CalibrationFailureCode,
    CalibrationIteration,
    CalibrationMode,
    CalibrationResult,
    CalibrationState,
    GenerationSettings,
    LayerSliceTiming,
    SliceEvaluation,
)
from cooling_tower.services.tower_need_service import assess_tower_need, layers_for_tower
from cooling_tower.slicers import (
    EffectiveProfile,
    SliceRequest,
    assert_profile_copies_are_isolated,
    protect_profile_sources,
)
from cooling_tower.tower.hollow_profile import build_hollow_tower_profile
from cooling_tower.tower.mesh_generator import (
    TowerMeshConfig,
    generate_hollow_tower_mesh,
    write_binary_stl,
)
from cooling_tower.tower.profile import TowerProfileConfig, build_tower_radius_profile


ProgressCallback = Callable[[int, str], None]


class CalibrationService:
    """Run the bounded slicer/profile feedback loop from Phase 16."""

    def __init__(
        self,
        *,
        evaluator: SliceEvaluator | None = None,
        integrator: GCodeIntegrator | None = None,
    ) -> None:
        self.evaluator = evaluator or SliceEvaluator()
        self.integrator = integrator or GCodeIntegrator()

    def calibrate(
        self,
        snapshot: object,
        settings: GenerationSettings,
        *,
        adapter: object,
        profile: EffectiveProfile,
        output_directory: str | Path,
        config: CalibrationConfig | None = None,
        cancellation_event: Event | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> CalibrationResult:
        config = config or CalibrationConfig()
        notify = progress_callback or (lambda percent, status: None)
        started = time.monotonic()
        source = Path(getattr(snapshot, "gcode_path")).resolve()
        source_hash = sha256_file(source)
        assessment = assess_tower_need(snapshot, settings)
        if not assessment.tower_required:
            return CalibrationResult(
                state=CalibrationState.CONVERGED,
                mode=config.mode,
                iterations=(),
                profile=None,
                stl_path=None,
                gcode_path=None,
                placement=None,
                warnings=(
                    "Es wird kein Kühlturm benötigt; es wurde keine Ausgabedatei erstellt.",
                ),
                source_sha256=source_hash,
                configured_iteration_count=config.maximum_iterations,
            )
        source_layers = layers_for_tower(snapshot, assessment)
        if not source_layers:
            return self._failure(
                config, CalibrationState.INVALID_GEOMETRY, source_hash,
                CalibrationFailureCode.LAYER_MISMATCH,
                "Es wurden keine für den Kühlturm relevanten Quell-Layer gefunden.",
            )
        if config.maximum_iterations == 0:
            return CalibrationResult(
                state=CalibrationState.NOT_STARTED,
                mode=config.mode,
                iterations=(),
                profile=None,
                stl_path=None,
                gcode_path=None,
                placement=None,
                warnings=(
                    "Die Slicer-Kalibrierung wurde bewusst deaktiviert; es wird "
                    "der analytisch berechnete Kühlturm verwendet.",
                ),
                source_sha256=source_hash,
                configured_iteration_count=0,
            )
        if not profile.installation.can_slice:
            return self._failure(
                config, CalibrationState.UNSUPPORTED, source_hash,
                CalibrationFailureCode.PROFILE_INCOMPLETE,
                "Die ausgewählte Slicer-/Profilkombination kann nicht automatisch slicen.",
            )
        if config.mode is CalibrationMode.GCODE:
            support = assess_gcode_support(source)
            if not support.supported:
                return self._failure(
                    config, CalibrationState.UNSUPPORTED, source_hash,
                    CalibrationFailureCode.UNSUPPORTED_GCODE,
                    " ".join(support.reasons),
                )

        profile_config = TowerProfileConfig(
            target_layer_time_s=settings.target_layer_time_s,
            safety_factor=settings.safety_factor,
            minimum_radius_mm=settings.minimum_outer_radius_mm,
            maximum_radius_mm=settings.maximum_outer_radius_mm,
            local_time_factor_window=settings.local_reference_window,
        )
        radius_profile = build_tower_radius_profile(source_layers, profile_config)
        placement = None
        if config.mode is CalibrationMode.GCODE:
            bed = parse_bed_bounds(profile.effective_values)
            if bed is None:
                return self._failure(
                    config, CalibrationState.UNSUPPORTED, source_hash,
                    CalibrationFailureCode.PROFILE_INCOMPLETE,
                    "Das wirksame Maschinenprofil enthält keine verlässlichen "
                    "Druckbettgrenzen.",
                )
            try:
                placement = propose_tower_placement(
                    bed,
                    determine_occupied_bounds(source),
                    tower_radius_mm=max(
                        settings.maximum_outer_radius_mm,
                        settings.manual_base_width_mm / 2.0,
                    ),
                    object_clearance_mm=config.object_clearance_mm,
                    edge_clearance_mm=config.bed_edge_clearance_mm,
                )
            except GCodeIntegrationError as error:
                return self._failure(
                    config, CalibrationState.UNSUPPORTED, source_hash,
                    CalibrationFailureCode.NO_BED_SPACE, str(error),
                )

        iterations: list[CalibrationIteration] = []
        repeated_signatures: dict[str, int] = {}
        maximum_profile_change = math.inf
        final_profile = None
        best_profile = None
        best_stl: Path | None = None
        best_gcode: Path | None = None
        best_iteration_number: int | None = None
        best_score: tuple[int, float, float, float] | None = None
        baseline_score: tuple[int, float, float, float] | None = None
        previous_added_times_s: dict[int, float] | None = None
        minimum_iteration_count = (
            1 if config.maximum_iterations == 1 else 2
        )
        terminal_state = CalibrationState.LIMIT_REACHED
        warnings: list[str] = []
        if config.mode is CalibrationMode.STL:
            warnings.append(
                "Die kalibrierte STL-Datei ist eine Zeitprognose; spätere "
                "Sliceränderungen können die endgültige Layerzeit verändern. "
                "Bitte prüfen Sie das Ergebnis in der Layerzeitansicht des Slicers."
            )
        failures: list[CalibrationFailure] = []
        with (
            protect_profile_sources(profile),
            tempfile.TemporaryDirectory(
                prefix="cooling_tower_calibration_"
            ) as temporary,
        ):
            work_root = Path(temporary)
            calibration_profile, overrides = build_calibration_profile(
                profile, work_root / "profile"
            )
            if profile.installation.adapter_id in {
                "anycubic_slicer_next",
                "orca_slicer",
                "bambu_studio",
            }:
                assert_profile_copies_are_isolated(
                    profile,
                    calibration_profile,
                    work_root / "profile",
                )
            warnings.append(
                "Für die Kalibrierung temporär angepasste Kühlwerte: "
                + ", ".join(f"{key}={value}" for key, value in sorted(overrides.items()))
            )
            for number in range(1, config.maximum_iterations + 1):
                if cancellation_event is not None and cancellation_event.is_set():
                    return CalibrationResult(
                        CalibrationState.CANCELLED, config.mode, tuple(iterations),
                        final_profile, None, None, placement,
                        source_sha256=source_hash,
                        configured_iteration_count=config.maximum_iterations,
                        best_iteration_number=best_iteration_number,
                    )
                elapsed = time.monotonic() - started
                if elapsed > config.maximum_runtime_s:
                    failures.append(CalibrationFailure(
                        CalibrationFailureCode.RUNTIME_LIMIT,
                        "Das Zeitlimit der Kalibrierung wurde erreicht.",
                    ))
                    break
                notify(
                    round((number - 1) / config.maximum_iterations * 90),
                    f"Kühlturm wird kalibriert – Durchlauf "
                    f"{number}/{config.maximum_iterations}",
                )
                record_diagnostic(
                    "calibration_round_started",
                    calibration_round=number,
                    calibration_round_count=config.maximum_iterations,
                )
                hollow = build_hollow_tower_profile(
                    radius_profile,
                    settings,
                    tower_end_z_mm=assessment.tower_end_z_mm,
                    object_height_mm=getattr(snapshot, "maximum_print_z_mm"),
                )
                final_profile = hollow
                if hollow.feasibility_issues:
                    for issue in hollow.feasibility_issues:
                        failures.append(
                            CalibrationFailure(
                                self._failure_code_for_issue(issue.code),
                                issue.message,
                                issue.affected_layer_index,
                                issue.related_setting_names,
                            )
                        )
                iteration_root = work_root / f"iteration_{number:02d}"
                iteration_root.mkdir()
                candidate_stl = iteration_root / "candidate.stl"
                mesh = generate_hollow_tower_mesh(
                    hollow, TowerMeshConfig(settings.mesh_segments)
                )
                export = write_binary_stl(mesh, candidate_stl)
                if not export.validation.is_valid:
                    record_diagnostic(
                        "calibration_round_finished",
                        calibration_round=number,
                        success=False,
                        reason="invalid_geometry",
                    )
                    failures.append(CalibrationFailure(
                        CalibrationFailureCode.GEOMETRY_INVALID,
                        "Das erzeugte Kandidaten-Mesh ist nicht geschlossen und "
                        "konsistent ausgerichtet.",
                    ))
                    break
                signature = self._profile_signature(hollow)
                repeated_signatures[signature] = repeated_signatures.get(signature, 0) + 1
                notify(
                    round((number - 0.5) / config.maximum_iterations * 90),
                    f"Slicer-Auftrag {number}/{config.maximum_iterations} wird ausgeführt …",
                )
                slice_result = adapter.slice_model(
                    SliceRequest(
                        model_path=candidate_stl,
                        profile=calibration_profile,
                        output_directory=iteration_root / "slice",
                        diagnostics_root=iteration_root / "diagnostics",
                        timeout_s=config.timeout_per_slice_s,
                        cancellation_event=cancellation_event,
                        temporary_overrides=overrides,
                        expected_layer_heights_mm=tuple(
                            float(getattr(layer, "height_mm")) for layer in source_layers
                        ),
                        placement_xy_mm=(
                            (placement.center_x_mm, placement.center_y_mm)
                            if placement else None
                        ),
                        purpose="calibration",
                        calibration_round=number,
                    )
                )
                notify(
                    round(number / config.maximum_iterations * 90),
                    f"Slicer-Ergebnis {number}/{config.maximum_iterations} wird ausgewertet …",
                )
                if not slice_result.success:
                    record_diagnostic(
                        "calibration_round_finished",
                        calibration_round=number,
                        success=False,
                        reason="slicer_failure",
                    )
                    details = (slice_result.stderr or slice_result.stdout).strip()
                    if len(details) > 1000:
                        details = details[-1000:]
                    failures.append(CalibrationFailure(
                        CalibrationFailureCode.SLICER_FAILURE,
                        (slice_result.failure_reason or "Der Slicer ist fehlgeschlagen.")
                        + (f" Slicer-Ausgabe: {details}" if details else ""),
                    ))
                    terminal_state = CalibrationState.SLICER_FAILED
                    break
                evaluation = self.evaluator.evaluate(
                    slice_result,
                    source_layers,
                    metadata_tolerance_s=config.slicer_metadata_tolerance_s,
                )
                combined_path = None
                if config.mode is CalibrationMode.GCODE:
                    combined_path = iteration_root / "combined.gcode"
                    try:
                        if placement is None:
                            raise GCodeIntegrationError(
                                "Die berechnete Druckbettplatzierung fehlt; der "
                                "G-Code kann nicht sicher integriert werden."
                            )
                        self.integrator.integrate(
                            source,
                            evaluation.gcode_path,
                            combined_path,
                            placement=placement,
                            source_layers=source_layers,
                            target_layer_time_s=settings.target_layer_time_s,
                            travel_speed_mm_s=config.travel_speed_mm_s,
                            retraction_length_mm=config.retraction_length_mm,
                            retraction_speed_mm_s=config.retraction_speed_mm_s,
                        )
                    except GCodeIntegrationError as error:
                        record_diagnostic(
                            "calibration_round_finished",
                            calibration_round=number,
                            success=False,
                            reason="gcode_integration_failure",
                        )
                        failures.append(CalibrationFailure(
                            CalibrationFailureCode.UNSUPPORTED_GCODE, str(error)
                        ))
                        break
                    evaluation = self._combined_evaluation(
                        evaluation, combined_path, source_layers
                    )
                convergence = evaluate_convergence(
                    source_layers,
                    evaluation.added_time_by_layer,
                    target_time_s=settings.target_layer_time_s,
                    maximum_profile_change_mm=maximum_profile_change,
                    config=config,
                )
                current_added_times_s = {
                    int(index): float(value)
                    for index, value in evaluation.added_time_by_layer.items()
                }
                maximum_slicer_result_change_s = (
                    self._maximum_slicer_result_change(
                        previous_added_times_s,
                        current_added_times_s,
                        source_layers,
                    )
                )
                minimum_iterations_reached = number >= minimum_iteration_count
                if minimum_iteration_count == 1:
                    # "Schnell" deliberately accepts its single measurement.
                    slicer_result_stable = minimum_iterations_reached
                else:
                    slicer_result_stable = bool(
                        minimum_iterations_reached
                        and maximum_slicer_result_change_s is not None
                        and maximum_slicer_result_change_s
                        <= config.time_tolerance_s
                    )
                iteration = CalibrationIteration(
                    number=number,
                    candidate_signature=signature,
                    maximum_remaining_deficit_s=(
                        convergence.maximum_remaining_deficit_s
                    ),
                    deficient_layer_count=convergence.deficient_layer_count,
                    total_remaining_deficit_s=(
                        convergence.total_remaining_deficit_s
                    ),
                    maximum_profile_change_mm=maximum_profile_change,
                    elapsed_s=time.monotonic() - started,
                    evaluation=evaluation,
                    maximum_slicer_result_change_s=(
                        maximum_slicer_result_change_s
                    ),
                    slicer_result_stable=slicer_result_stable,
                    final_combined_gcode_path=combined_path,
                )
                iterations.append(iteration)
                previous_added_times_s = current_added_times_s
                record_diagnostic(
                    "calibration_round_finished",
                    calibration_round=number,
                    success=True,
                    deficient_layer_count=convergence.deficient_layer_count,
                    maximum_remaining_deficit_s=(
                        convergence.maximum_remaining_deficit_s
                    ),
                    maximum_slicer_result_change_s=(
                        maximum_slicer_result_change_s
                    ),
                    slicer_result_stable=slicer_result_stable,
                    minimum_iterations_reached=minimum_iterations_reached,
                )
                metadata_conflict = (
                    config.mode is CalibrationMode.GCODE
                    and evaluation.maximum_metadata_difference_s is not None
                    and evaluation.maximum_metadata_difference_s
                    > config.slicer_metadata_tolerance_s
                )
                candidate_score = self._candidate_score(convergence, hollow)
                if baseline_score is None:
                    baseline_score = candidate_score
                if not metadata_conflict and (
                    best_score is None or candidate_score < best_score
                ):
                    best_score = candidate_score
                    best_profile = hollow
                    best_stl = candidate_stl
                    best_gcode = combined_path
                    best_iteration_number = number
                if (
                    convergence.converged
                    and slicer_result_stable
                    and not metadata_conflict
                    and not hollow.feasibility_issues
                ):
                    result = self._export_candidate(
                        state=CalibrationState.CONVERGED,
                        config=config,
                        iterations=iterations,
                        profile=hollow,
                        candidate_stl=candidate_stl,
                        candidate_gcode=combined_path,
                        placement=placement,
                        failures=(),
                        warnings=warnings,
                        source=source,
                        source_hash=source_hash,
                        output_directory=Path(output_directory),
                        best_iteration_number=number,
                        improved_over_analytical=(
                            baseline_score is not None
                            and candidate_score < baseline_score
                        ),
                    )
                    notify(100, "Slicerbasierte Kalibrierung abgeschlossen")
                    return result

                if metadata_conflict:
                    failures.append(CalibrationFailure(
                        CalibrationFailureCode.SLICER_TIMING_MISMATCH,
                        "Slicer-Metadaten und berechnete G-Code-Zeit weichen stärker "
                        "als zulässig voneinander ab.",
                    ))
                    break
                if (
                    convergence.deficient_layer_count > 0
                    and repeated_signatures[signature]
                    > config.repeated_result_limit
                ):
                    failures.append(CalibrationFailure(
                        CalibrationFailureCode.STALLED,
                        "Wiederholt identische Kandidaten können die verbleibende "
                        "Zeitabweichung nicht ausgleichen.",
                    ))
                    break
                if convergence.deficient_layer_count == 0:
                    # Verify an unchanged candidate once more.  Material
                    # reduction belongs after a proven stable timing result;
                    # reducing here would reintroduce the just-closed deficit.
                    maximum_profile_change = 0.0
                    continue
                radius_profile, maximum_profile_change = adjust_radius_profile(
                    radius_profile,
                    source_layers,
                    evaluation.added_time_by_layer,
                    target_time_s=settings.target_layer_time_s,
                    minimum_wall_path_count=hollow.wall_bounds.minimum_path_count,
                    wall_path_width_mm=settings.wall_path_width_mm,
                    config=replace(config, material_reduction_factor=0.0),
                )
            if not failures:
                last_iteration = iterations[-1] if iterations else None
                if (
                    last_iteration is not None
                    and last_iteration.deficient_layer_count == 0
                    and not last_iteration.slicer_result_stable
                ):
                    result_change = (
                        last_iteration.maximum_slicer_result_change_s
                    )
                    rendered_change = (
                        f"{result_change:.3f} s"
                        if result_change is not None
                        and math.isfinite(result_change)
                        else "nicht belastbar"
                    )
                    failures.append(CalibrationFailure(
                        CalibrationFailureCode.STALLED,
                        "Die Zielzeit wurde erreicht, aber die aufeinanderfolgenden "
                        "Slicer-Ergebnisse blieben bis zum Durchlauflimit "
                        "instabil (größte Layerzeit-Abweichung zuletzt: "
                        f"{rendered_change}; zulässig: "
                        f"{config.time_tolerance_s:.3f} s).",
                    ))
                else:
                    failures.append(CalibrationFailure(
                        CalibrationFailureCode.ITERATION_LIMIT,
                        "Die maximale Anzahl der Kalibrierungsdurchläufe wurde erreicht.",
                    ))
            improved = bool(
                best_score is not None
                and baseline_score is not None
                and best_score < baseline_score
            )
            if (
                improved
                and best_profile is not None
                and best_stl is not None
                and best_iteration_number is not None
            ):
                warnings.append(
                    "Die Kalibrierung hat die Zielzeit nicht vollständig erreicht; "
                    "der beste gültige und vom Slicer gemessene Kandidat aus "
                    f"Durchlauf {best_iteration_number} wird verwendet."
                )
                notify(
                    100,
                    "Bester sliceroptimierter Zwischenstand wird verwendet",
                )
                return self._export_candidate(
                    state=terminal_state,
                    config=config,
                    iterations=iterations,
                    profile=best_profile,
                    candidate_stl=best_stl,
                    candidate_gcode=best_gcode,
                    placement=placement,
                    failures=failures,
                    warnings=warnings,
                    source=source,
                    source_hash=source_hash,
                    output_directory=Path(output_directory),
                    best_iteration_number=best_iteration_number,
                    improved_over_analytical=True,
                )
        return CalibrationResult(
            terminal_state,
            config.mode,
            tuple(iterations),
            final_profile,
            None,
            None,
            placement,
            tuple(failures),
            tuple(warnings),
            source_sha256=source_hash,
            configured_iteration_count=config.maximum_iterations,
            best_iteration_number=best_iteration_number,
            improved_over_analytical=False,
        )

    @staticmethod
    def _maximum_slicer_result_change(
        previous_added_times_s: dict[int, float] | None,
        current_added_times_s: dict[int, float],
        source_layers: tuple[object, ...],
    ) -> float | None:
        """Compare consecutive slicer timings for every relevant source layer."""

        if previous_added_times_s is None:
            return None
        expected_indices = tuple(
            int(getattr(layer, "index")) for layer in source_layers
        )
        if any(
            index not in previous_added_times_s
            or index not in current_added_times_s
            for index in expected_indices
        ):
            return math.inf
        changes = []
        for index in expected_indices:
            previous = previous_added_times_s[index]
            current = current_added_times_s[index]
            if not math.isfinite(previous) or not math.isfinite(current):
                return math.inf
            changes.append(abs(current - previous))
        return max(changes, default=0.0)

    @staticmethod
    def _candidate_score(
        convergence: object,
        profile: object,
    ) -> tuple[int, float, float, float]:
        """Rank timing first and material only as a deterministic tie-breaker."""

        material = sum(
            max(
                0.0,
                float(layer.outer_radius_mm) ** 2
                - float(layer.inner_radius_mm) ** 2,
            )
            for layer in getattr(profile, "layers")
        )
        return (
            int(getattr(convergence, "deficient_layer_count")),
            float(getattr(convergence, "maximum_remaining_deficit_s")),
            float(getattr(convergence, "total_remaining_deficit_s")),
            material,
        )

    @staticmethod
    def _export_candidate(
        *,
        state: CalibrationState,
        config: CalibrationConfig,
        iterations: list[CalibrationIteration],
        profile: object,
        candidate_stl: Path,
        candidate_gcode: Path | None,
        placement: object,
        failures: tuple[CalibrationFailure, ...] | list[CalibrationFailure],
        warnings: list[str],
        source: Path,
        source_hash: str,
        output_directory: Path,
        best_iteration_number: int,
        improved_over_analytical: bool,
    ) -> CalibrationResult:
        output_directory.mkdir(parents=True, exist_ok=True)
        stl_destination = output_directory / "cooling_tower_slicer_evaluated.stl"
        shutil.copy2(candidate_stl, stl_destination)
        gcode_destination = None
        if candidate_gcode is not None:
            gcode_destination = output_directory / f"{source.stem}_cooling_tower.gcode"
            shutil.copy2(candidate_gcode, gcode_destination)
        if config.mode is CalibrationMode.GCODE and gcode_destination is None:
            raise GCodeIntegrationError(
                "Für den ausgewählten besten Kandidaten liegt kein integrierter "
                "G-Code vor."
            )
        exported = (
            gcode_destination
            if config.mode is CalibrationMode.GCODE
            else stl_destination
        )
        if exported is None:
            raise GCodeIntegrationError(
                "Für den Kalibrierungskandidaten fehlt die erwartete Exportdatei."
            )
        result = CalibrationResult(
            state=state,
            mode=config.mode,
            iterations=tuple(iterations),
            profile=profile,
            stl_path=stl_destination.resolve(),
            gcode_path=(
                gcode_destination.resolve() if gcode_destination else None
            ),
            placement=placement,
            failures=tuple(failures),
            warnings=tuple(warnings),
            source_sha256=source_hash,
            output_sha256=sha256_file(exported),
            configured_iteration_count=config.maximum_iterations,
            best_iteration_number=best_iteration_number,
            improved_over_analytical=improved_over_analytical,
        )
        report_path = output_directory / "calibration_report.json"
        report_path.write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return replace(result, report_path=report_path.resolve())

    def _combined_evaluation(
        self,
        isolated: SliceEvaluation,
        combined_path: Path,
        source_layers: tuple[object, ...],
    ) -> SliceEvaluation:
        combined = self.evaluator.analysis_service.analyze(combined_path, force=True)
        values: list[LayerSliceTiming] = []
        for source in source_layers:
            index = int(getattr(source, "index"))
            z = float(getattr(source, "z_mm"))
            layer = min(combined.layers, key=lambda item: abs(item.z_mm - z))
            source_time = float(getattr(source, "total_time_s"))
            added = max(0.0, layer.total_time_s - source_time)
            original = next(
                item for item in isolated.layer_timings if item.layer_index == index
            )
            values.append(replace(original, total_added_time_s=added))
        return replace(
            isolated,
            gcode_path=combined_path.resolve(),
            layer_timings=tuple(values),
            metadata_source="final_combined_gcode",
        )

    @staticmethod
    def _profile_signature(profile: object) -> str:
        points = getattr(profile, "points")
        payload = "|".join(
            f"{point.z_mm:.5f},{point.outer_radius_mm:.5f},{point.wall_thickness_mm:.5f}"
            for point in points
        )
        return hashlib.sha256(payload.encode("ascii")).hexdigest()

    @staticmethod
    def _failure_code_for_issue(code: str) -> CalibrationFailureCode:
        folded = code.casefold()
        if "angle" in folded:
            return CalibrationFailureCode.TRANSITION_ANGLE
        if "wall" in folded:
            return CalibrationFailureCode.MAXIMUM_WALL_THICKNESS
        if "radius" in folded:
            return CalibrationFailureCode.MAXIMUM_RADIUS
        return CalibrationFailureCode.GEOMETRY_INVALID

    @staticmethod
    def _failure(
        config: CalibrationConfig,
        state: CalibrationState,
        source_hash: str,
        code: CalibrationFailureCode,
        message: str,
    ) -> CalibrationResult:
        return CalibrationResult(
            state, config.mode, (), None, None, None, None,
            (CalibrationFailure(code, message),),
            source_sha256=source_hash,
            configured_iteration_count=config.maximum_iterations,
        )
