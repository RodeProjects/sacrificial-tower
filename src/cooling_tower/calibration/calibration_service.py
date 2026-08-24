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
    parse_bed_geometry,
    propose_tower_placement,
)
from cooling_tower.calibration.joint_project import (
    JointProjectError,
    build_joint_project,
    validate_tower_infill_adoption,
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
    SourceArtifact,
    SourceKind,
)
from cooling_tower.services.tower_need_service import assess_tower_need, layers_for_tower
from cooling_tower.slicers import (
    EffectiveProfile,
    SliceRequest,
    SliceResult,
    assert_profile_copies_are_isolated,
    protect_profile_sources,
)
from cooling_tower.tower.solid_profile import build_solid_tower_profile
from cooling_tower.tower.mesh_generator import (
    TowerMeshConfig,
    generate_solid_tower_mesh,
    write_binary_stl,
)
from cooling_tower.tower.profile import TowerProfileConfig, build_tower_radius_profile
from cooling_tower.tower.base_calculator import calculate_phase10_base_outer_radius


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
        source_artifact: SourceArtifact | None = None,
        seed_profile: object | None = None,
        seed_stl_path: str | Path | None = None,
    ) -> CalibrationResult:
        config = config or CalibrationConfig()
        notify = progress_callback or (lambda percent, status: None)
        started = time.monotonic()
        source = Path(getattr(snapshot, "gcode_path")).resolve()
        source_hash = sha256_file(source)
        if source_artifact is not None and not source_artifact.matches_current_file(
            verify_content=True
        ):
            return self._failure(
                config,
                CalibrationState.INVALID_GEOMETRY,
                source_hash,
                CalibrationFailureCode.GEOMETRY_INVALID,
                "Die ursprüngliche Quelldatei wurde seit ihrer Prüfung verändert.",
            )
        joint_source_stl = (
            source_artifact.original_path
            if source_artifact is not None
            and source_artifact.source_kind is SourceKind.STL
            and profile.installation.adapter_id in {
                "anycubic_slicer_next", "orca_slicer", "bambu_studio"
            }
            else None
        )
        seed_stl = (
            Path(seed_stl_path).resolve()
            if seed_stl_path is not None else None
        )
        reuse_seed = bool(
            joint_source_stl is not None
            and config.perform_joint_final_slice
            and seed_profile is not None
            and seed_stl is not None
            and seed_stl.is_file()
        )
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
        if not profile.installation.can_slice:
            return self._failure(
                config, CalibrationState.UNSUPPORTED, source_hash,
                CalibrationFailureCode.PROFILE_INCOMPLETE,
                "Die ausgewählte Slicer-/Profilkombination kann nicht automatisch slicen.",
            )
        if config.mode is CalibrationMode.GCODE and joint_source_stl is None:
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
        if reuse_seed:
            radius_profile = self._radius_profile_from_seed(
                radius_profile,
                seed_profile,
            )
        placement = None
        occupied_bounds = determine_occupied_bounds(source)
        calculated_base_radius = calculate_phase10_base_outer_radius(
            object_height_mm=float(getattr(snapshot, "maximum_print_z_mm")),
            automatic_base_width=settings.automatic_base_width,
            manual_base_width_mm=settings.manual_base_width_mm,
        )
        brim_type = str(
            profile.effective_values.get("brim_type", "")
        ).casefold()
        brim_width = (
            self._profile_nonnegative_number(
                profile.effective_values.get("brim_width")
            )
            if brim_type not in {"", "none", "no_brim", "disabled"}
            else 0.0
        )
        reserved_tower_radius = max(
            settings.maximum_outer_radius_mm,
            calculated_base_radius,
        ) + brim_width
        if (
            config.mode is CalibrationMode.GCODE
            or joint_source_stl is not None
        ):
            bed_geometry = parse_bed_geometry(profile.effective_values)
            if bed_geometry is None:
                return self._failure(
                    config, CalibrationState.UNSUPPORTED, source_hash,
                    CalibrationFailureCode.PROFILE_INCOMPLETE,
                    "Das wirksame Maschinenprofil enthält keine verlässlichen "
                    "Druckbettgrenzen.",
                )
            try:
                placement = propose_tower_placement(
                    bed_geometry.bounds,
                    occupied_bounds,
                    tower_radius_mm=reserved_tower_radius,
                    object_clearance_mm=config.object_clearance_mm,
                    edge_clearance_mm=config.bed_edge_clearance_mm,
                    bed_geometry=bed_geometry,
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
        best_project: Path | None = None
        best_iteration_number: int | None = None
        best_score: tuple[int, float, float, float, float, float] | None = None
        baseline_score: tuple[int, float, float, float, float, float] | None = None
        previous_added_times_s: dict[int, float] | None = None
        first_joint_round: int | None = None
        if joint_source_stl is not None and config.perform_joint_final_slice:
            first_joint_round = 1 if reuse_seed else config.maximum_iterations
            correction_rounds = 1 if config.maximum_iterations > 1 else 0
            iteration_count = first_joint_round + correction_rounds
        else:
            iteration_count = config.maximum_iterations
        minimum_iteration_count = 1 if iteration_count == 1 else 2
        terminal_state = CalibrationState.LIMIT_REACHED
        warnings: list[str] = []
        if joint_source_stl is not None and config.perform_joint_final_slice:
            warnings.append(
                "Die schnellen Kalibrierungsrunden slicen nur den Kühlturm. "
                "Der Präzisionslauf slicet Objekt und Kühlturm gemeinsam mit "
                "festen Positionen. Nur bei einer relevanten Abweichung folgt "
                "höchstens eine gemeinsame Korrekturprüfung; das exportierte "
                "3MF reproduziert die geprüfte Anordnung."
            )
            if reuse_seed:
                warnings.append(
                    "Der bereits berechnete Vorschaukandidat wird direkt für "
                    "den gemeinsamen Präzisionsslice wiederverwendet."
                )
        elif joint_source_stl is not None:
            warnings.append(
                "Die Vorschau verwendet schnelle, separat geslicte "
                "Kühlturm-Kandidaten. Beim Export wird der aktuelle Kandidat "
                "einmal gemeinsam mit dem Objekt präzisionsgeprüft."
            )
        elif config.mode is CalibrationMode.GCODE:
            warnings.append(
                "Die Quelle ist bereits G-Code und kann nicht gemeinsam neu "
                "geslicet werden. Der separat geslicte Kühlturm wird deshalb "
                "schichtweise integriert; die resultierende Zeit ist eine "
                "geprüfte Näherung, keine echte gemeinsame Neu-Slicung."
            )
        elif config.mode is CalibrationMode.STL:
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
            joint_only = reuse_seed
            initial_profile_root = work_root / (
                "profile_joint" if joint_only else "profile_isolated"
            )
            isolated_profile, isolated_overrides = build_calibration_profile(
                profile,
                initial_profile_root,
                simulate_full_tower_infill=(
                    settings.simulate_full_tower_infill and not joint_only
                ),
            )
            joint_profile = isolated_profile
            joint_overrides = isolated_overrides
            if (
                not joint_only
                and joint_source_stl is not None
                and config.perform_joint_final_slice
                and settings.simulate_full_tower_infill
            ):
                joint_profile, joint_overrides = build_calibration_profile(
                    profile,
                    work_root / "profile_joint",
                    simulate_full_tower_infill=False,
                )
            if profile.installation.adapter_id in {
                "anycubic_slicer_next",
                "orca_slicer",
                "bambu_studio",
            }:
                assert_profile_copies_are_isolated(
                    profile,
                    isolated_profile,
                    initial_profile_root,
                )
                if joint_profile is not isolated_profile:
                    assert_profile_copies_are_isolated(
                        profile,
                        joint_profile,
                        work_root / "profile_joint",
                    )
            warnings.append(
                "Für die Kalibrierung temporär angepasste Prozesswerte: "
                + ", ".join(
                    f"{key}={value}"
                    for key, value in sorted(isolated_overrides.items())
                )
            )
            for number in range(1, iteration_count + 1):
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
                joint_round = bool(
                    first_joint_round is not None
                    and number >= first_joint_round
                )
                use_seed_this_round = reuse_seed and number == 1
                if joint_round:
                    round_status = "Gemeinsamer Präzisionsslice wird vorbereitet …"
                elif first_joint_round is not None:
                    round_status = (
                        "Kühlturm wird schnell kalibriert – Abgleich "
                        f"{number}/{first_joint_round - 1}"
                    )
                else:
                    round_status = (
                        f"Kühlturm wird kalibriert – Durchlauf "
                        f"{number}/{iteration_count}"
                    )
                notify(
                    round((number - 1) / iteration_count * 90),
                    round_status,
                )
                record_diagnostic(
                    "calibration_round_started",
                    calibration_round=number,
                    calibration_round_count=iteration_count,
                )
                solid = (
                    seed_profile
                    if use_seed_this_round
                    else build_solid_tower_profile(
                        radius_profile,
                        settings,
                        tower_end_z_mm=assessment.tower_end_z_mm,
                        object_height_mm=getattr(snapshot, "maximum_print_z_mm"),
                    )
                )
                final_profile = solid
                if solid.feasibility_issues:
                    for issue in solid.feasibility_issues:
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
                if use_seed_this_round:
                    assert seed_stl is not None
                    shutil.copy2(seed_stl, candidate_stl)
                    geometry_is_valid = candidate_stl.stat().st_size > 84
                else:
                    mesh = generate_solid_tower_mesh(
                        solid, TowerMeshConfig(settings.mesh_segments)
                    )
                    export = write_binary_stl(mesh, candidate_stl)
                    geometry_is_valid = export.validation.is_valid
                if not geometry_is_valid:
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
                candidate_project: Path | None = None
                slice_model_path = candidate_stl
                use_cli_assemble_list = False
                profile_for_slice = isolated_profile
                overrides_for_slice = isolated_overrides
                if joint_round:
                    if placement is None:
                        failures.append(CalibrationFailure(
                            CalibrationFailureCode.NO_BED_SPACE,
                            "Die feste Platzierung für das gemeinsame 3MF fehlt.",
                        ))
                        break
                    candidate_project = iteration_root / "object_with_cooling_tower.3mf"
                    profile_for_slice = joint_profile
                    overrides_for_slice = joint_overrides
                    try:
                        project_factory = getattr(
                            adapter, "create_joint_project", None
                        )
                        if callable(project_factory):
                            project_request = SliceRequest(
                                model_path=joint_source_stl,
                                profile=profile_for_slice,
                                output_directory=(
                                    iteration_root / "project_export"
                                ),
                                diagnostics_root=(
                                    iteration_root / "project_diagnostics"
                                ),
                                timeout_s=config.timeout_per_slice_s,
                                cancellation_event=cancellation_event,
                                temporary_overrides=overrides_for_slice,
                                purpose="calibration",
                                calibration_round=number,
                            )
                            project_result = project_factory(
                                project_request,
                                joint_source_stl,
                                candidate_stl,
                                candidate_project,
                                occupied=occupied_bounds,
                                placement=placement,
                                tower_full_infill=(
                                    settings.simulate_full_tower_infill
                                ),
                            )
                            native_slice_input = getattr(
                                project_result, "slice_input_path", None
                            )
                            if native_slice_input is not None:
                                slice_model_path = Path(native_slice_input).resolve()
                                use_cli_assemble_list = True
                        else:
                            build_joint_project(
                                joint_source_stl,
                                candidate_stl,
                                candidate_project,
                                occupied=occupied_bounds,
                                placement=placement,
                                tower_full_infill=(
                                    settings.simulate_full_tower_infill
                                ),
                            )
                    except JointProjectError as error:
                        failures.append(CalibrationFailure(
                            CalibrationFailureCode.GEOMETRY_INVALID,
                            str(error),
                        ))
                        terminal_state = CalibrationState.INVALID_GEOMETRY
                        break
                    if not use_cli_assemble_list:
                        slice_model_path = candidate_project
                signature = self._profile_signature(solid)
                repeated_signatures[signature] = repeated_signatures.get(signature, 0) + 1
                notify(
                    round((number - 0.5) / iteration_count * 90),
                    (
                        (
                            "Gemeinsamer Präzisionsslice von Objekt und "
                            "Kühlturm wird ausgeführt …"
                            if number == first_joint_round
                            else "Gemeinsamer Präzisionsslice zur gezielten "
                            "Korrekturprüfung wird ausgeführt …"
                        )
                        if joint_round
                        else f"Schneller Kühlturm-Abgleich "
                        f"{number}/{iteration_count} wird ausgeführt …"
                    ),
                )
                slice_request = SliceRequest(
                    model_path=slice_model_path,
                    profile=profile_for_slice,
                    output_directory=iteration_root / "slice",
                    diagnostics_root=iteration_root / "diagnostics",
                    timeout_s=config.timeout_per_slice_s,
                    cancellation_event=cancellation_event,
                    temporary_overrides=overrides_for_slice,
                    expected_layer_heights_mm=tuple(
                        float(getattr(layer, "height_mm")) for layer in source_layers
                    ),
                    placement_xy_mm=(
                        (placement.center_x_mm, placement.center_y_mm)
                        if placement and candidate_project is None else None
                    ),
                    preserve_model_positions=(candidate_project is not None),
                    use_cli_assemble_list=use_cli_assemble_list,
                    purpose="calibration",
                    calibration_round=number,
                )
                slice_result = adapter.slice_model(slice_request)
                if (
                    (cancellation_event is None or not cancellation_event.is_set())
                    and self._should_retry_anycubic_profile_load(
                        adapter,
                        slice_result,
                    )
                ):
                    retry_percent = round(
                        (number - 0.25) / iteration_count * 90
                    )
                    notify(
                        retry_percent,
                        "Anycubic-Profilpaket wird einmalig neu synchronisiert …",
                    )
                    record_diagnostic(
                        "calibration_slicer_retry",
                        calibration_round=number,
                        reason="anycubic_profile_compatibility",
                        first_return_code=slice_result.return_code,
                    )
                    slice_result = adapter.slice_model(slice_request)
                notify(
                    round(number / iteration_count * 90),
                    f"Slicer-Ergebnis {number}/{iteration_count} wird ausgewertet …",
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
                if (
                    candidate_project is not None
                    and settings.simulate_full_tower_infill
                ):
                    try:
                        if slice_result.gcode_path is None:
                            raise JointProjectError(
                                "Der gemeinsame Slicer-Lauf lieferte keinen G-Code."
                            )
                        validate_tower_infill_adoption(
                            slice_result.gcode_path,
                            tower_center_xy_mm=(
                                (placement.center_x_mm, placement.center_y_mm)
                                if placement is not None else None
                            ),
                        )
                    except JointProjectError as error:
                        failures.append(CalibrationFailure(
                            CalibrationFailureCode.OBJECT_OVERRIDE_REJECTED,
                            str(error),
                        ))
                        terminal_state = CalibrationState.SLICER_FAILED
                        break
                evaluation = self.evaluator.evaluate(
                    slice_result,
                    source_layers,
                    metadata_tolerance_s=config.slicer_metadata_tolerance_s,
                )
                combined_path = None
                if candidate_project is not None:
                    combined_path = evaluation.gcode_path
                    evaluation = self._combined_evaluation(
                        evaluation,
                        combined_path,
                        source_layers,
                    )
                elif config.mode is CalibrationMode.GCODE:
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
                joint_target_deviation_s = (
                    self._maximum_target_deviation(
                        source_layers,
                        evaluation.added_time_by_layer,
                        target_time_s=settings.target_layer_time_s,
                    )
                    if joint_round else None
                )
                minimum_target_difference_s = self._minimum_target_difference(
                    source_layers,
                    evaluation.added_time_by_layer,
                    target_time_s=settings.target_layer_time_s,
                )
                target_time_confirmed = bool(
                    math.isfinite(minimum_target_difference_s)
                    and minimum_target_difference_s
                    >= -config.time_tolerance_s
                )
                joint_precision_confirmed = bool(
                    joint_round and target_time_confirmed
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
                if joint_round:
                    # The expensive joint slice is deliberately performed once.
                    # Stability of the fast tower-only refinement is not a reason
                    # to repeat the complete object slice.
                    slicer_result_stable = True
                elif minimum_iteration_count == 1:
                    # A single requested pass deliberately accepts its only
                    # measurement without claiming repetition stability.
                    slicer_result_stable = minimum_iterations_reached
                else:
                    slicer_result_stable = bool(
                        minimum_iterations_reached
                        and maximum_slicer_result_change_s is not None
                        and maximum_slicer_result_change_s
                        <= config.slicer_result_change_tolerance_s
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
                    joint_slice=joint_round,
                    maximum_target_deviation_s=joint_target_deviation_s,
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
                    joint_target_deviation_s=joint_target_deviation_s,
                    joint_precision_confirmed=joint_precision_confirmed,
                    minimum_target_difference_s=(
                        minimum_target_difference_s
                    ),
                    target_time_confirmed=target_time_confirmed,
                )
                metadata_conflict = (
                    (config.mode is CalibrationMode.GCODE or candidate_project is not None)
                    and evaluation.maximum_metadata_difference_s is not None
                    and evaluation.maximum_metadata_difference_s
                    > config.slicer_metadata_tolerance_s
                )
                candidate_score = self._candidate_score(
                    convergence,
                    solid,
                    source_layers=source_layers,
                    added_times_s=evaluation.added_time_by_layer,
                    target_time_s=settings.target_layer_time_s,
                )
                if baseline_score is None:
                    baseline_score = candidate_score
                if not metadata_conflict and (
                    joint_round
                    or best_score is None
                    or candidate_score < best_score
                ):
                    best_score = candidate_score
                    best_profile = solid
                    best_stl = candidate_stl
                    best_gcode = combined_path
                    best_project = candidate_project
                    best_iteration_number = number
                joint_candidate_accepted = bool(
                    joint_round and target_time_confirmed
                )
                isolated_candidate_accepted = bool(
                    not joint_round
                    and target_time_confirmed
                    and number >= iteration_count
                )
                if (
                    (joint_candidate_accepted or isolated_candidate_accepted)
                    and not metadata_conflict
                    and not solid.feasibility_issues
                ):
                    result = self._export_candidate(
                        state=CalibrationState.CONVERGED,
                        config=config,
                        iterations=iterations,
                        profile=solid,
                        candidate_stl=candidate_stl,
                        candidate_gcode=combined_path,
                        candidate_project=candidate_project,
                        placement=placement,
                        failures=(),
                        warnings=warnings,
                        source=source,
                        source_hash=source_hash,
                        output_directory=Path(output_directory),
                        best_iteration_number=number,
                        improved_over_initial_candidate=(
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
                    and number >= iteration_count
                ):
                    deficient_layers = {
                        layer_index
                        for layer_index, deficit in (
                            convergence.remaining_deficits_s.items()
                        )
                        if deficit > config.time_tolerance_s
                    }
                    maximum_limited = next(
                        (
                            layer
                            for layer in solid.layers
                            if layer.index in deficient_layers
                            and math.isclose(
                                layer.outer_diameter_mm,
                                settings.maximum_outer_diameter_mm,
                                abs_tol=1e-6,
                            )
                        ),
                        None,
                    )
                    if maximum_limited is not None:
                        failures.append(CalibrationFailure(
                            CalibrationFailureCode.MAXIMUM_RADIUS,
                            "Der größte Außendurchmesser reicht auch unter "
                            "Einbeziehung der tatsächlichen Wände und Füllung "
                            "nicht für die Ziel-Layerzeit aus.",
                            maximum_limited.index,
                            ("maximum_outer_diameter_mm",),
                        ))
                    else:
                        angle_limited = next(
                            (
                                issue
                                for issue in solid.initial_geometry_limitations
                                if issue.code == "EXPANSION_ANGLE_TOO_SMALL"
                                and (
                                    issue.affected_layer_index is None
                                    or issue.affected_layer_index
                                    in deficient_layers
                                )
                            ),
                            None,
                        )
                        if angle_limited is not None:
                            failures.append(CalibrationFailure(
                                CalibrationFailureCode.TRANSITION_ANGLE,
                                "Der Aufweitungswinkel verhindert, dass der "
                                "Turm an den betroffenen Layern rechtzeitig "
                                "breit genug wird.",
                                angle_limited.affected_layer_index,
                                ("maximum_expansion_angle_deg",),
                            ))
                        else:
                            failures.append(CalibrationFailure(
                                CalibrationFailureCode.STALLED,
                                "Wiederholt identische Kandidaten können die "
                                "verbleibende Zeitabweichung nicht ausgleichen.",
                            ))
                    break
                if convergence.deficient_layer_count == 0:
                    # A solid body can gain substantial time from process-
                    # profile walls and infill. Feed that measured surplus
                    # back into the diameter demand before accepting a wider
                    # candidate than necessary.
                    radius_profile, maximum_profile_change = adjust_radius_profile(
                        radius_profile,
                        source_layers,
                        evaluation.added_time_by_layer,
                        target_time_s=settings.target_layer_time_s,
                        realized_outer_radii_mm={
                            layer.index: layer.outer_radius_mm
                            for layer in solid.layers
                        },
                        config=config,
                    )
                    continue
                radius_profile, maximum_profile_change = adjust_radius_profile(
                    radius_profile,
                    source_layers,
                    evaluation.added_time_by_layer,
                    target_time_s=settings.target_layer_time_s,
                    realized_outer_radii_mm={
                        layer.index: layer.outer_radius_mm
                        for layer in solid.layers
                    },
                    config=config,
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
                        f"{config.slicer_result_change_tolerance_s:.3f} s).",
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
                (improved or best_project is not None)
                and best_profile is not None
                and best_stl is not None
                and best_iteration_number is not None
            ):
                if best_project is not None:
                    warnings.append(
                        "Der einmalige gemeinsame Präzisionsslice hat die "
                        "Zielzeit nicht vollständig bestätigt. Der gemeinsam "
                        "geslicte Kandidat und sein reproduzierbares 3MF werden "
                        "als sicher prüfbarer Zwischenstand verwendet."
                    )
                else:
                    warnings.append(
                        "Die Kalibrierung hat die Zielzeit nicht vollständig "
                        "erreicht; der beste gültige und vom Slicer gemessene "
                        f"Kandidat aus Durchlauf {best_iteration_number} wird "
                        "verwendet."
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
                    candidate_project=best_project,
                    placement=placement,
                    failures=failures,
                    warnings=warnings,
                    source=source,
                    source_hash=source_hash,
                    output_directory=Path(output_directory),
                    best_iteration_number=best_iteration_number,
                    improved_over_initial_candidate=improved,
                )
        return CalibrationResult(
            state=terminal_state,
            mode=config.mode,
            iterations=tuple(iterations),
            profile=final_profile,
            stl_path=None,
            gcode_path=None,
            placement=placement,
            failures=tuple(failures),
            warnings=tuple(warnings),
            source_sha256=source_hash,
            configured_iteration_count=config.maximum_iterations,
            best_iteration_number=best_iteration_number,
            improved_over_initial_candidate=False,
        )

    @staticmethod
    def _radius_profile_from_seed(
        radius_profile: object,
        seed_profile: object,
    ) -> object:
        """Use the preview's realized radii as the exact-check correction base."""

        seed_by_index = {
            int(getattr(layer, "index")): float(
                getattr(layer, "outer_radius_mm")
            )
            for layer in getattr(seed_profile, "layers", ())
        }
        adjusted_layers = []
        for layer in getattr(radius_profile, "layers"):
            radius = seed_by_index.get(int(getattr(layer, "layer_index")))
            if radius is None or not math.isfinite(radius) or radius <= 0.0:
                adjusted_layers.append(layer)
                continue
            path = math.tau * radius
            factor = getattr(layer, "seconds_per_deposition_mm")
            estimated_added = path * factor if factor is not None else None
            adjusted_layers.append(
                replace(
                    layer,
                    calculated_radius_mm=radius,
                    radius_mm=radius,
                    additional_path_mm=(
                        path / radius_profile.config.safety_factor
                    ),
                    safety_adjusted_path_mm=path,
                    estimated_added_time_s=estimated_added,
                )
            )
        return replace(radius_profile, layers=tuple(adjusted_layers))

    @staticmethod
    def _profile_nonnegative_number(value: object) -> float:
        if isinstance(value, (list, tuple)):
            value = value[0] if value else 0.0
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return 0.0
        return number if math.isfinite(number) and number >= 0.0 else 0.0

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
    def _maximum_target_deviation(
        source_layers: tuple[object, ...],
        added_times_s: dict[int, float],
        *,
        target_time_s: float,
    ) -> float:
        """Measure over- and undershoot only where the object needs a tower."""

        deviations = []
        for layer in source_layers:
            index = int(getattr(layer, "index"))
            required_added = max(
                0.0,
                target_time_s - float(getattr(layer, "total_time_s")),
            )
            if required_added <= 0.0:
                continue
            observed_added = max(0.0, float(added_times_s.get(index, 0.0)))
            deviations.append(abs(observed_added - required_added))
        return max(deviations, default=0.0)

    @staticmethod
    def _minimum_target_difference(
        source_layers: tuple[object, ...],
        added_times_s: dict[int, float],
        *,
        target_time_s: float,
    ) -> float:
        """Return the signed deviation of the critical minimum layer time."""

        combined_times = [
            float(getattr(layer, "total_time_s"))
            + max(
                0.0,
                float(
                    added_times_s.get(
                        int(getattr(layer, "index")),
                        0.0,
                    )
                ),
            )
            for layer in source_layers
        ]
        if not combined_times or not all(
            math.isfinite(value) for value in combined_times
        ):
            return math.inf
        return min(combined_times) - target_time_s

    @staticmethod
    def _candidate_score(
        convergence: object,
        profile: object,
        *,
        source_layers: tuple[object, ...],
        added_times_s: dict[int, float],
        target_time_s: float,
    ) -> tuple[int, float, float, float, float, float]:
        """Rank target compliance, tower-time excess, then material."""

        material = sum(
            max(
                0.0,
                float(layer.outer_radius_mm) ** 2,
            )
            for layer in getattr(profile, "layers")
        )
        required_by_index = {
            int(getattr(layer, "index")): max(
                0.0,
                target_time_s - float(getattr(layer, "total_time_s")),
            )
            for layer in source_layers
        }
        avoidable_excesses = tuple(
            max(
                0.0,
                float(added_times_s.get(index, 0.0)) - required_added,
            )
            for index, required_added in required_by_index.items()
        )
        deficient_layer_count = int(
            getattr(convergence, "deficient_layer_count")
        )
        return (
            deficient_layer_count,
            (
                float(getattr(convergence, "maximum_remaining_deficit_s"))
                if deficient_layer_count > 0
                else 0.0
            ),
            float(getattr(convergence, "total_remaining_deficit_s")),
            sum(avoidable_excesses),
            max(avoidable_excesses, default=0.0),
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
        candidate_project: Path | None,
        placement: object,
        failures: tuple[CalibrationFailure, ...] | list[CalibrationFailure],
        warnings: list[str],
        source: Path,
        source_hash: str,
        output_directory: Path,
        best_iteration_number: int,
        improved_over_initial_candidate: bool,
    ) -> CalibrationResult:
        output_directory.mkdir(parents=True, exist_ok=True)
        stl_destination = output_directory / "cooling_tower_slicer_evaluated.stl"
        shutil.copy2(candidate_stl, stl_destination)
        gcode_destination = None
        if candidate_gcode is not None:
            gcode_destination = output_directory / f"{source.stem}_cooling_tower.gcode"
            shutil.copy2(candidate_gcode, gcode_destination)
        project_destination = None
        if candidate_project is not None:
            project_destination = output_directory / (
                f"{source.stem}_with_cooling_tower.3mf"
            )
            shutil.copy2(candidate_project, project_destination)
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
            project_path=(
                project_destination.resolve() if project_destination else None
            ),
            failures=tuple(failures),
            warnings=tuple(warnings),
            source_sha256=source_hash,
            output_sha256=sha256_file(exported),
            configured_iteration_count=config.maximum_iterations,
            best_iteration_number=best_iteration_number,
            improved_over_initial_candidate=improved_over_initial_candidate,
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
        # ``SliceEvaluator.evaluate`` has already parsed the complete joint
        # G-code and stored each matched joint layer's total time in
        # ``total_added_time_s``. Re-parsing the same multi-million-line file
        # here used to double the dominant analysis cost without adding any
        # evidence. The source pre-slice is unchanged, so its known layer time
        # can be subtracted directly from that first joint measurement.
        values: list[LayerSliceTiming] = []
        for source in source_layers:
            index = int(getattr(source, "index"))
            source_time = float(getattr(source, "total_time_s"))
            original = next(
                item for item in isolated.layer_timings if item.layer_index == index
            )
            added = max(0.0, original.total_added_time_s - source_time)
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
            f"{point.z_mm:.5f},{point.outer_radius_mm:.5f}"
            for point in points
        )
        return hashlib.sha256(payload.encode("ascii")).hexdigest()

    @staticmethod
    def _should_retry_anycubic_profile_load(
        adapter: object,
        result: SliceResult,
    ) -> bool:
        if result.success or getattr(adapter, "adapter_id", "") != (
            "anycubic_slicer_next"
        ):
            return False
        output = f"{result.stdout}\n{result.stderr}".casefold()
        return (
            "process not compatible with printer" in output
            or (
                result.return_code == -17
                and "compatible" in output
                and "printer" in output
            )
        )

    @staticmethod
    def _failure_code_for_issue(code: str) -> CalibrationFailureCode:
        folded = code.casefold()
        if "angle" in folded:
            return CalibrationFailureCode.TRANSITION_ANGLE
        if "diameter" in folded or "radius" in folded:
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
            state=state,
            mode=config.mode,
            iterations=(),
            profile=None,
            stl_path=None,
            gcode_path=None,
            placement=None,
            failures=(CalibrationFailure(code, message),),
            source_sha256=source_hash,
            configured_iteration_count=config.maximum_iterations,
        )
