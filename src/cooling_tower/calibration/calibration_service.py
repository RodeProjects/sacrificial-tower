from __future__ import annotations

import hashlib
import json
import math
import shutil
import tempfile
import time
from dataclasses import dataclass, replace
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
    OccupiedBounds,
    SliceEvaluation,
    SourceArtifact,
    SourceKind,
)
from cooling_tower.services.tower_need_service import assess_tower_need, layers_for_tower
from cooling_tower.slicers import (
    EffectiveProfile,
    SliceRequest,
    SliceResult,
    SlicerProcessError,
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


from cooling_tower.calibration.candidate_evaluation import (
    candidate_score,
    maximum_slicer_result_change,
    maximum_target_deviation,
    minimum_target_difference,
)
from cooling_tower.write_policy import ensure_writable_output

ProgressCallback = Callable[[int, str], None]


@dataclass(frozen=True, slots=True)
class _DeferredJointProjectExport:
    adapter: object
    request: SliceRequest
    source_model_path: Path
    occupied: OccupiedBounds
    placement: object
    tower_full_infill: bool


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
        precomputed_occupied_bounds: OccupiedBounds | None = None,
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
        occupied_bounds = (
            precomputed_occupied_bounds
            if precomputed_occupied_bounds is not None
            else determine_occupied_bounds(source)
        )
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
        best_deferred_project: _DeferredJointProjectExport | None = None
        best_iteration_number: int | None = None
        best_score: tuple[int, float, float, float, float, float] | None = None
        best_is_joint = False
        baseline_score: tuple[int, float, float, float, float, float] | None = None
        previous_added_times_s: dict[int, float] | None = None
        first_joint_round: int | None = None
        if joint_source_stl is not None and config.perform_joint_final_slice:
            joint_slice_budget = min(
                config.maximum_joint_slices,
                config.maximum_iterations,
            )
            if reuse_seed:
                # The preview already supplied the inexpensive calibration
                # rounds. Spend only the configured complete-object budget on
                # validating and, where needed, correcting that measured seed.
                first_joint_round = 1
                iteration_count = joint_slice_budget
            else:
                # Joint rounds are part of the configured total pass budget.
                # The GUI configures six isolated rounds followed by up to six
                # real object/tower rounds.
                iteration_count = config.maximum_iterations
                first_joint_round = (
                    iteration_count - joint_slice_budget + 1
                )
        else:
            iteration_count = config.maximum_iterations
        minimum_iteration_count = 1 if iteration_count == 1 else 2
        terminal_state = CalibrationState.LIMIT_REACHED
        warnings: list[str] = []
        if joint_source_stl is not None and config.perform_joint_final_slice:
            normal_slice_count = max(0, (first_joint_round or 1) - 1)
            warnings.append(
                (
                    f"Zuerst optimieren bis zu {normal_slice_count} getrennte "
                    "Slices die Turmgeometrie; bei stabiler Annäherung wird "
                    "früher zur vollständigen gemeinsamen Prüfung gewechselt. "
                    if normal_slice_count
                    else "Der vorhandene Turmkandidat wird wiederverwendet. "
                )
                + "Danach werden Objekt und Kühlturm mit festen Positionen "
                f"mindestens {config.minimum_joint_slices} und bis zu "
                f"{config.maximum_joint_slices} Mal gemeinsam geslicet. "
                "Sobald die Ziel-Layerzeit innerhalb der Toleranz bestätigt ist, "
                "endet die Generierung vorzeitig. Das exportierte 3MF reproduziert "
                "die ausgewählte geprüfte Anordnung."
            )
            if reuse_seed:
                warnings.append(
                    "Der bereits berechnete Vorschaukandidat wird direkt für "
                    "die gemeinsamen Slices wiederverwendet."
                )
        elif joint_source_stl is not None:
            warnings.append(
                "Der Kühlturm wird getrennt geslicet, weil für diese "
                "Slicer-Konfiguration kein gemeinsamer Lauf verfügbar ist."
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
            native_joint_template = work_root / "native_joint_template.3mf"
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
            if isolated_overrides:
                warnings.append(
                    "Für die 100-%-Turmfüllung temporär angepasste "
                    "Prozesswerte: "
                    + ", ".join(
                        f"{key}={value}"
                        for key, value in sorted(isolated_overrides.items())
                    )
                )
            measurement_history: dict[
                int, list[tuple[float, float]]
            ] = {}
            measurement_history_joint_phase: bool | None = None
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
                if (
                    joint_round
                    and first_joint_round is not None
                    and number - first_joint_round
                    >= config.maximum_joint_slices
                ):
                    break
                use_seed_this_round = reuse_seed and number == 1
                if joint_round:
                    round_status = "Gemeinsamer Slice wird vorbereitet …"
                elif first_joint_round is not None:
                    round_status = (
                        "Kühlturmgeometrie wird optimiert – getrennter Slice "
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
                deferred_project: _DeferredJointProjectExport | None = None
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
                    profile_for_slice = joint_profile
                    overrides_for_slice = joint_overrides
                    try:
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
                            native_project_template_path=(
                                native_joint_template
                            ),
                        )
                        lightweight_factory = getattr(
                            adapter,
                            "prepare_joint_slice_input",
                            None,
                        )
                        project_factory = getattr(
                            adapter, "create_joint_project", None
                        )
                        if callable(lightweight_factory):
                            slice_input = lightweight_factory(
                                project_request,
                                joint_source_stl,
                                candidate_stl,
                                iteration_root / "candidate.bambu-assemble.json",
                                occupied=occupied_bounds,
                                placement=placement,
                                tower_full_infill=(
                                    settings.simulate_full_tower_infill
                                ),
                            )
                            slice_model_path = Path(
                                getattr(slice_input, "slice_input_path")
                            ).resolve()
                            use_cli_assemble_list = True
                            deferred_project = _DeferredJointProjectExport(
                                adapter=adapter,
                                request=project_request,
                                source_model_path=joint_source_stl,
                                occupied=occupied_bounds,
                                placement=placement,
                                tower_full_infill=(
                                    settings.simulate_full_tower_infill
                                ),
                            )
                        elif callable(project_factory):
                            candidate_project = iteration_root / (
                                "object_with_cooling_tower.3mf"
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
                            candidate_project = iteration_root / (
                                "object_with_cooling_tower.3mf"
                            )
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
                    if candidate_project is not None and not use_cli_assemble_list:
                        slice_model_path = candidate_project
                signature = self._profile_signature(solid)
                repeated_signatures[signature] = repeated_signatures.get(signature, 0) + 1
                notify(
                    round((number - 0.5) / iteration_count * 90),
                    (
                        (
                            "Gemeinsamer Slice von Objekt und "
                            "Kühlturm wird ausgeführt …"
                            if number == first_joint_round
                            else "Weiterer gemeinsamer Slice zur gezielten "
                            "Korrekturprüfung wird ausgeführt …"
                        )
                        if joint_round
                        else f"Getrennter Kühlturm-Slice "
                        f"{number}/{first_joint_round - 1 if first_joint_round else iteration_count} "
                        "wird ausgeführt …"
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
                        if placement and not joint_round else None
                    ),
                    preserve_model_positions=joint_round,
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
                validate_full_infill = bool(
                    joint_round
                    and settings.simulate_full_tower_infill
                )
                try:
                    if validate_full_infill and slice_result.gcode_path is None:
                        raise JointProjectError(
                            "Der gemeinsame Slicer-Lauf lieferte keinen G-Code."
                        )
                    evaluation = self.evaluator.evaluate(
                        slice_result,
                        source_layers,
                        metadata_tolerance_s=config.slicer_metadata_tolerance_s,
                        validate_tower_full_infill=validate_full_infill,
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
                combined_path = None
                if joint_round:
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
                combined_times_s = (
                    evaluation.combined_time_by_layer if joint_round else {}
                )
                convergence = evaluate_convergence(
                    source_layers,
                    evaluation.added_time_by_layer,
                    target_time_s=settings.target_layer_time_s,
                    maximum_profile_change_mm=maximum_profile_change,
                    combined_times_s=combined_times_s,
                    config=config,
                )
                joint_target_deviation_s = (
                    self._maximum_target_deviation(
                        source_layers,
                        evaluation.added_time_by_layer,
                        target_time_s=settings.target_layer_time_s,
                        combined_times_s=combined_times_s,
                    )
                    if joint_round else None
                )
                minimum_target_difference_s = self._minimum_target_difference(
                    source_layers,
                    evaluation.added_time_by_layer,
                    target_time_s=settings.target_layer_time_s,
                    combined_times_s=combined_times_s,
                )
                minimum_target_reached = bool(
                    math.isfinite(minimum_target_difference_s)
                    and minimum_target_difference_s
                    >= -config.time_tolerance_s
                )
                target_time_confirmed = bool(
                    minimum_target_reached
                    and (
                        not joint_round
                        or minimum_target_difference_s
                        <= config.time_tolerance_s
                    )
                )
                joint_precision_confirmed = bool(
                    joint_round and target_time_confirmed
                )
                current_added_times_s = {
                    int(index): float(value)
                    for index, value in evaluation.added_time_by_layer.items()
                }
                if measurement_history_joint_phase is not joint_round:
                    measurement_history.clear()
                    measurement_history_joint_phase = joint_round
                realized_radii = {
                    int(layer.index): float(layer.outer_radius_mm)
                    for layer in solid.layers
                }
                for layer_index, observed_s in current_added_times_s.items():
                    radius = realized_radii.get(layer_index)
                    if radius is None:
                        continue
                    history = measurement_history.setdefault(layer_index, [])
                    history.append((radius, observed_s))
                    if len(history) > 8:
                        del history[:-8]
                maximum_slicer_result_change_s = (
                    self._maximum_slicer_result_change(
                        previous_added_times_s,
                        current_added_times_s,
                        source_layers,
                    )
                )
                minimum_iterations_reached = number >= minimum_iteration_count
                if joint_round:
                    # A joint result is direct timing evidence for the exported
                    # arrangement. Its measured deviation drives the next joint
                    # correction, so tower-only repetition stability must not
                    # veto an otherwise valid joint measurement.
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
                    (config.mode is CalibrationMode.GCODE or joint_round)
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
                    combined_times_s=combined_times_s,
                )
                if baseline_score is None:
                    baseline_score = candidate_score
                candidate_is_best = bool(
                    best_score is None
                    or (joint_round and not best_is_joint)
                    or (
                        joint_round == best_is_joint
                        and candidate_score < best_score
                    )
                )
                if not metadata_conflict and candidate_is_best:
                    best_score = candidate_score
                    best_is_joint = joint_round
                    best_profile = solid
                    best_stl = candidate_stl
                    best_gcode = combined_path
                    best_project = candidate_project
                    best_deferred_project = deferred_project
                    best_iteration_number = number
                if (
                    not joint_round
                    and joint_source_stl is not None
                    and config.perform_joint_final_slice
                    and first_joint_round is not None
                    and number + 1 < first_joint_round
                    and target_time_confirmed
                    and slicer_result_stable
                    and convergence.profile_stable
                    and not metadata_conflict
                    and not solid.feasibility_issues
                ):
                    # Isolated slices are only a fast search stage. Once two
                    # successive measurements and the profile itself are
                    # stable, unused search rounds cannot improve the final
                    # evidence; move directly to the mandatory full joint
                    # slices without weakening their count or tolerance.
                    first_joint_round = number + 1
                    record_diagnostic(
                        "calibration_joint_phase_advanced",
                        after_isolated_round=number,
                        saved_isolated_rounds=(
                            normal_slice_count - number
                        ),
                    )
                joint_candidate_accepted = bool(
                    joint_round
                    and target_time_confirmed
                    and first_joint_round is not None
                    and number - first_joint_round + 1
                    >= config.minimum_joint_slices
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
                        deferred_project=deferred_project,
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
                        measurement_history=measurement_history,
                        combined_layer_times_s=combined_times_s,
                        coupled_radius_scale=self._joint_coupled_radius_scale(
                            combined_times_s,
                            target_time_s=settings.target_layer_time_s,
                            config=config,
                        ),
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
                    measurement_history=measurement_history,
                    combined_layer_times_s=combined_times_s,
                    coupled_radius_scale=self._joint_coupled_radius_scale(
                        combined_times_s,
                        target_time_s=settings.target_layer_time_s,
                        config=config,
                    ),
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
                (
                    improved
                    or best_project is not None
                    or best_deferred_project is not None
                )
                and best_profile is not None
                and best_stl is not None
                and best_iteration_number is not None
            ):
                if best_project is not None or best_deferred_project is not None:
                    warnings.append(
                        "Die gemeinsamen Slices haben die "
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
                    deferred_project=best_deferred_project,
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

    _maximum_slicer_result_change = staticmethod(maximum_slicer_result_change)

    _maximum_target_deviation = staticmethod(maximum_target_deviation)

    _minimum_target_difference = staticmethod(minimum_target_difference)

    _candidate_score = staticmethod(candidate_score)

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
        deferred_project: _DeferredJointProjectExport | None,
        placement: object,
        failures: tuple[CalibrationFailure, ...] | list[CalibrationFailure],
        warnings: list[str],
        source: Path,
        source_hash: str,
        output_directory: Path,
        best_iteration_number: int,
        improved_over_initial_candidate: bool,
    ) -> CalibrationResult:
        if candidate_project is None and deferred_project is not None:
            project_factory = getattr(
                deferred_project.adapter,
                "create_joint_project",
                None,
            )
            if not callable(project_factory):
                error: BaseException = JointProjectError(
                    "Der finale Bambu-Projektbau ist nicht verfügbar."
                )
            else:
                try:
                    final_project = candidate_stl.with_name(
                        "selected_object_with_cooling_tower.3mf"
                    )
                    project_result = project_factory(
                        deferred_project.request,
                        deferred_project.source_model_path,
                        candidate_stl,
                        final_project,
                        occupied=deferred_project.occupied,
                        placement=deferred_project.placement,
                        tower_full_infill=(
                            deferred_project.tower_full_infill
                        ),
                    )
                    candidate_project = Path(
                        getattr(project_result, "path", final_project)
                    ).resolve()
                    if not candidate_project.is_file():
                        raise JointProjectError(
                            "Der finale Bambu-Projektbau lieferte kein 3MF."
                        )
                except (JointProjectError, OSError, SlicerProcessError) as caught:
                    error = caught
                else:
                    error = None
            if error is not None:
                return CalibrationResult(
                    state=CalibrationState.SLICER_FAILED,
                    mode=config.mode,
                    iterations=tuple(iterations),
                    profile=profile,
                    stl_path=None,
                    gcode_path=None,
                    placement=placement,
                    failures=(
                        *tuple(failures),
                        CalibrationFailure(
                            CalibrationFailureCode.SLICER_FAILURE,
                            "Das finale Bambu-3MF konnte nicht aus dem "
                            f"gewählten Kandidaten erzeugt werden: {error}",
                        ),
                    ),
                    warnings=tuple(warnings),
                    source_sha256=source_hash,
                    configured_iteration_count=config.maximum_iterations,
                    best_iteration_number=best_iteration_number,
                    improved_over_initial_candidate=False,
                )
        output_directory = ensure_writable_output(output_directory)
        output_directory.mkdir(parents=True, exist_ok=True)
        stl_destination = ensure_writable_output(output_directory / "cooling_tower_slicer_evaluated.stl", protected_files=(source,))
        shutil.copy2(candidate_stl, stl_destination)
        gcode_destination = None
        if candidate_gcode is not None:
            gcode_destination = output_directory / f"{source.stem}_cooling_tower.gcode"
            ensure_writable_output(gcode_destination, protected_files=(source,))
            shutil.copy2(candidate_gcode, gcode_destination)
        project_destination = None
        if candidate_project is not None:
            project_destination = output_directory / (
                f"{source.stem}_with_cooling_tower.3mf"
            )
            ensure_writable_output(project_destination, protected_files=(source,))
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
        report_path = ensure_writable_output(output_directory / "calibration_report.json", protected_files=(source,))
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
        # evidence. Preserve the joint time as direct plate evidence; only the
        # geometry feedback contribution remains clamped after subtracting the
        # standalone source time.
        values: list[LayerSliceTiming] = []
        timing_by_layer = {
            item.layer_index: item for item in isolated.layer_timings
        }
        for source in source_layers:
            index = int(getattr(source, "index"))
            source_time = float(getattr(source, "total_time_s"))
            original = timing_by_layer[index]
            direct_combined = original.total_added_time_s
            added = max(0.0, direct_combined - source_time)
            values.append(
                replace(
                    original,
                    total_added_time_s=added,
                    combined_layer_time_s=direct_combined,
                )
            )
        return replace(
            isolated,
            gcode_path=combined_path.resolve(),
            layer_timings=tuple(values),
            metadata_source="final_combined_gcode",
        )

    @staticmethod
    def _joint_coupled_radius_scale(
        combined_times_s: dict[int, float],
        *,
        target_time_s: float,
        config: CalibrationConfig,
    ) -> float:
        """Return a bounded plate-wide correction for coupled tower geometry."""

        finite_times = tuple(
            value
            for value in combined_times_s.values()
            if math.isfinite(value) and value > 1e-9
        )
        if not finite_times:
            return 1.0
        critical_time = min(finite_times)
        if abs(critical_time - target_time_s) <= config.time_tolerance_s:
            return 1.0
        correction_target_s = target_time_s
        if critical_time < target_time_s - config.time_tolerance_s:
            # Keep the actual acceptance threshold unchanged, but leave a
            # small bounded correction reserve. Complete-plate slicers can
            # move the minimum to a neighbouring layer after rebuilding their
            # cooling/speed plan; without the reserve that costs several full
            # feedback slices for fractions of a second.
            correction_target_s += min(
                1.0,
                max(config.time_tolerance_s, target_time_s * 0.05),
            )
        requested = math.sqrt(correction_target_s / critical_time)
        maximum_growth = math.sqrt(config.maximum_path_growth_factor)
        return min(maximum_growth, max(0.5, requested))

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
