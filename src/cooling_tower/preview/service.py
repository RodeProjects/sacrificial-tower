from __future__ import annotations

import math
import os
import tempfile
from hmac import compare_digest
from pathlib import Path
from threading import Event
from typing import Callable

from cooling_tower.diagnostic_context import record_diagnostic
from cooling_tower.calibration import CalibrationService
from cooling_tower.calibration.gcode_integration import (
    GCodeIntegrationError,
    parse_bed_geometry,
    propose_tower_placement,
)
from cooling_tower.models import (
    BedBounds,
    CalibrationState,
    OccupiedBounds,
    TowerPlacement,
)
from cooling_tower.file_integrity import sha256_file
from cooling_tower.calibration.candidate_evaluation import minimum_combined_layer_time
from cooling_tower.tower.mesh_generator import automatic_mesh_segments
from cooling_tower.preview.models import (
    LineSegment3D,
    OutputMode,
    Point3D,
    PreviewRequest,
    PreviewResult,
    PreviewScene,
)
from cooling_tower.preview.source_cache import (
    PreviewSourceCacheKey,
    PreviewSourceData,
    PreviewSourceDataCache,
)
from cooling_tower.preview.toolpath import (
    PreviewCancelled,
    analyze_deposition_toolpaths,
)


ProgressCallback = Callable[[int, str], None]


class PreviewBuildError(RuntimeError):
    pass


def _fallback_bed(
    occupied: OccupiedBounds,
    tower_radius: float,
    *,
    object_clearance: float,
    edge_clearance: float,
) -> BedBounds:
    margin = max(
        15.0,
        object_clearance + 2.0 * tower_radius + edge_clearance + 5.0,
    )
    return BedBounds(
        occupied.minimum_x_mm - margin,
        occupied.maximum_x_mm + margin,
        occupied.minimum_y_mm - margin,
        occupied.maximum_y_mm + margin,
    )


def _suggest_placement(
    bed: BedBounds,
    occupied: OccupiedBounds,
    tower_radius: float,
    request: PreviewRequest,
    bed_geometry: object | None = None,
) -> TowerPlacement:
    return propose_tower_placement(
        bed,
        occupied,
        tower_radius_mm=tower_radius,
        object_clearance_mm=request.calibration_config.object_clearance_mm,
        edge_clearance_mm=request.calibration_config.bed_edge_clearance_mm,
        bed_geometry=bed_geometry,
    )


def _tower_wireframe(profile: object, placement: TowerPlacement) -> tuple[LineSegment3D, ...]:
    points = tuple(getattr(profile, "points"))
    if not points:
        return ()
    segment_count = automatic_mesh_segments(profile)
    rings: list[tuple[Point3D, ...]] = []
    for profile_point in points:
        radius = float(getattr(profile_point, "outer_radius_mm"))
        z = float(getattr(profile_point, "z_mm"))
        rings.append(
            tuple(
                Point3D(
                    placement.center_x_mm + radius * math.cos(2.0 * math.pi * index / segment_count),
                    placement.center_y_mm + radius * math.sin(2.0 * math.pi * index / segment_count),
                    z,
                )
                for index in range(segment_count)
            )
        )
    lines: list[LineSegment3D] = []
    for ring in rings:
        lines.extend(
            LineSegment3D(ring[index], ring[(index + 1) % segment_count])
            for index in range(segment_count)
        )
    for lower, upper in zip(rings, rings[1:]):
        lines.extend(
            LineSegment3D(lower[index], upper[index])
            for index in range(0, segment_count, 4)
        )
    return tuple(lines)


class PreviewService:
    def __init__(
        self,
        calibration_service: CalibrationService | None = None,
        source_data_cache: PreviewSourceDataCache | None = None,
    ) -> None:
        self.calibration_service = calibration_service or CalibrationService()
        self.source_data_cache = (
            source_data_cache
            if source_data_cache is not None
            else PreviewSourceDataCache()
        )

    def _source_identity(self, source: Path) -> tuple[os.stat_result, str]:
        """Read one stable file identity or fail without retaining stale data."""

        try:
            before = source.stat()
            content_sha256 = sha256_file(source)
            after = source.stat()
        except OSError as error:
            self.source_data_cache.invalidate_path(source)
            raise PreviewBuildError(
                "Der Quell-G-Code konnte während der Vorschauerstellung nicht "
                "mehr vollständig gelesen werden und muss neu geladen werden."
            ) from error
        if (
            after.st_size != before.st_size
            or after.st_mtime_ns != before.st_mtime_ns
        ):
            self.source_data_cache.invalidate_path(source)
            raise PreviewBuildError(
                "Der Quell-G-Code wurde während der Vorschauerstellung "
                "verändert und muss neu geladen werden."
            )
        return after, content_sha256

    def _source_data(
        self,
        request: PreviewRequest,
        *,
        cancellation_event: Event | None,
        notify: ProgressCallback,
    ) -> PreviewSourceData:
        source = request.source_path
        snapshot = request.snapshot
        if not source.is_file() or not bool(snapshot.matches_file(source)):
            self.source_data_cache.invalidate_path(source)
            raise PreviewBuildError(
                "Der Quell-G-Code wurde seit der Analyse verändert und muss "
                "neu geladen werden."
            )
        before, source_sha256 = self._source_identity(source)
        if not bool(snapshot.matches_file(source)):
            self.source_data_cache.invalidate_path(source)
            raise PreviewBuildError(
                "Der Quell-G-Code wurde während der Vorschauerstellung "
                "verändert und muss neu geladen werden."
            )
        expected_sha256 = getattr(snapshot, "content_sha256", None)
        if expected_sha256 is not None and not compare_digest(
            source_sha256,
            str(expected_sha256).casefold(),
        ):
            self.source_data_cache.invalidate_path(source)
            raise PreviewBuildError(
                "Der Inhalt des Quell-G-Codes stimmt nicht mehr mit der "
                "Analyse überein und muss neu geladen werden."
            )
        key = PreviewSourceCacheKey(
            source_path=source,
            file_size_bytes=before.st_size,
            file_modified_ns=before.st_mtime_ns,
            content_sha256=source_sha256,
            analysis_schema_version=int(
                getattr(snapshot, "analysis_schema_version", 1)
            ),
            parser_version=int(getattr(snapshot, "parser_version", 1)),
            expected_layer_count=int(getattr(snapshot, "layer_count")),
            maximum_segments=request.maximum_object_segments,
        )
        cached = self.source_data_cache.get(key)
        if cached is not None:
            record_diagnostic(
                "preview_source_cache_hit",
                displayed_segment_count=len(cached.object_segments),
                source_segment_count=cached.source_segment_count,
            )
            notify(20, "Zwischengespeicherte Objekt-Werkzeugpfade werden verwendet")
            return cached

        prepared_source_data = request.prepared_source_data
        if (
            isinstance(prepared_source_data, PreviewSourceData)
            and prepared_source_data.key == key
        ):
            self.source_data_cache.put(prepared_source_data)
            record_diagnostic(
                "preview_source_combined_analysis_used",
                displayed_segment_count=len(
                    prepared_source_data.object_segments
                ),
                source_segment_count=prepared_source_data.source_segment_count,
            )
            notify(
                20,
                "Gemeinsam analysierte Objekt-Werkzeugpfade werden verwendet",
            )
            return prepared_source_data

        record_diagnostic("preview_source_cache_miss")
        notify(5, "Objekt-Werkzeugpfade werden aufbereitet …")
        source_analysis = analyze_deposition_toolpaths(
            source,
            expected_layer_count=key.expected_layer_count,
            maximum_segments=key.maximum_segments,
            cancellation_event=cancellation_event,
            progress_callback=lambda _percent, status: notify(10, status),
        )
        object_segments = source_analysis.object_segments
        source_segment_count = source_analysis.source_segment_count
        if not object_segments:
            raise PreviewBuildError(
                "Im G-Code wurden keine darstellbaren Extrusionspfade gefunden."
            )
        if cancellation_event is not None and cancellation_event.is_set():
            raise PreviewCancelled()
        occupied_bounds = source_analysis.occupied_bounds
        if occupied_bounds is None:
            raise PreviewBuildError(
                "Im G-Code konnte keine belegte Druckbettfläche bestimmt werden."
            )
        notify(15, "Druckbettbelegung ist bestimmt")
        if cancellation_event is not None and cancellation_event.is_set():
            raise PreviewCancelled()

        after, after_sha256 = self._source_identity(source)
        if (
            after.st_size != before.st_size
            or after.st_mtime_ns != before.st_mtime_ns
            or not compare_digest(after_sha256, source_sha256)
            or not bool(snapshot.matches_file(source))
        ):
            self.source_data_cache.invalidate_path(source)
            raise PreviewBuildError(
                "Der Quell-G-Code wurde während der Vorschauerstellung "
                "verändert und muss neu geladen werden."
            )
        value = PreviewSourceData(
            key=key,
            object_segments=object_segments,
            source_segment_count=source_segment_count,
            occupied_bounds=occupied_bounds,
        )
        self.source_data_cache.put(value)
        record_diagnostic(
            "preview_source_cache_stored",
            displayed_segment_count=len(value.object_segments),
            source_segment_count=value.source_segment_count,
            cache_entry_count=len(self.source_data_cache),
        )
        notify(20, "Objekt-Werkzeugpfade sind vorbereitet")
        return value

    def prepare(
        self,
        request: PreviewRequest,
        *,
        cancellation_event: Event | None = None,
        accept_best_event: Event | None = None,
        progress_callback: ProgressCallback | None = None,
        joint_progress_callback: Callable[[object], None] | None = None,
        joint_scene_callback: Callable[[PreviewScene], None] | None = None,
        seed_preview: PreviewResult | None = None,
    ) -> PreviewResult:
        notify = progress_callback or (lambda _percent, _status: None)
        signature = request.signature()
        source = request.source_path
        seed_profile = None
        seed_stl_path = None
        if seed_preview is not None:
            expected_seed_signature = request.refinement_seed_signature()
            seed_calibration = getattr(seed_preview, "calibration", None)
            if (
                request.output_mode is not OutputMode.STL
                or not request.calibration_config.perform_joint_final_slice
                or request.source_artifact is None
                or request.source_artifact.source_kind.value != "stl"
                or seed_preview.refinement_seed_signature
                != expected_seed_signature
                or seed_preview.output_mode is not request.output_mode
                or seed_calibration is None
                or getattr(seed_calibration, "profile", None) is None
                or not seed_preview.artifact_path.is_file()
                or sha256_file(seed_preview.artifact_path)
                != seed_preview.artifact_sha256
            ):
                raise PreviewBuildError(
                    "Der vorhandene Geometriekandidat kann für die fortgesetzte "
                    "Kalibrierung nicht sicher wiederverwendet werden."
                )
            seed_profile = (
                getattr(seed_calibration, "continuation_profile", None)
                or seed_calibration.profile
            )
            seed_stl_path = seed_preview.artifact_path
        if not request.original_source_is_current():
            raise PreviewBuildError(
                "Die ursprüngliche Quelldatei wurde seit ihrer Prüfung verändert."
            )
        prepared = request.prepared_analysis_source
        if prepared is not None and not prepared.matches_analysis_gcode():
            raise PreviewBuildError(
                "Der vorbereitete Analyse-G-Code wurde seit seiner Prüfung verändert."
            )
        owner = tempfile.TemporaryDirectory(prefix="cooling_tower_preview_")
        root = Path(owner.name)
        try:
            source_data = self._source_data(
                request,
                cancellation_event=cancellation_event,
                notify=notify,
            )
            object_segments = source_data.object_segments
            source_segment_count = source_data.source_segment_count

            def report_joint_progress(progress: object) -> None:
                if joint_scene_callback is not None:
                    candidate_profile = (
                        getattr(progress, "best_profile", None)
                        or getattr(progress, "current_profile", None)
                    )
                    candidate_placement = getattr(progress, "placement", None)
                    if candidate_profile is not None and candidate_placement is not None:
                        points = tuple(getattr(candidate_profile, "points", ()))
                        if points:
                            joint_scene_callback(PreviewScene(
                                object_segments=object_segments,
                                tower_segments=_tower_wireframe(
                                    candidate_profile, candidate_placement
                                ),
                                bed_bounds=candidate_placement.bed_bounds,
                                tower_center_xy_mm=(
                                    candidate_placement.center_x_mm,
                                    candidate_placement.center_y_mm,
                                ),
                                source_segment_count=source_segment_count,
                                displayed_segment_count=len(object_segments),
                                tower_height_mm=max(float(point.z_mm) for point in points),
                                object_height_mm=float(request.snapshot.maximum_print_z_mm),
                                object_layer_count=int(request.snapshot.layer_count),
                                tower_layer_count=int(getattr(
                                    candidate_profile,
                                    "printable_layer_count",
                                    len(tuple(getattr(candidate_profile, "layers", ()))),
                                )),
                                tower_circle_segments=automatic_mesh_segments(
                                    candidate_profile
                                ),
                            ))
                if joint_progress_callback is not None:
                    joint_progress_callback(progress)

            if (
                request.calibration_config.maximum_iterations < 1
                or request.adapter is None
                or request.effective_profile is None
            ):
                raise PreviewBuildError(
                    "Für die präzise Kühlturmerzeugung sind ein bestätigter "
                    "Slicer, vollständige Profile und mindestens ein "
                    "Slicer-Durchlauf erforderlich."
                )

            profile = None
            calibration = None
            calibrated = False
            joint_sliced = False
            slicer_optimized = False
            warnings: list[str] = []
            artifact: Path | None = None
            placement: TowerPlacement | None = None
            generation_kind = "slicerbasierte Kalibrierung"
            if request.adapter is not None and request.effective_profile is not None:
                notify(25, "Slicer und Profil werden für die Kalibrierung vorbereitet …")
                calibration = self.calibration_service.calibrate(
                    request.snapshot,
                    request.settings,
                    force_tower=request.force_tower,
                    adapter=request.adapter,
                    profile=request.effective_profile,
                    output_directory=root / "calibrated",
                    config=request.calibration_config,
                    cancellation_event=cancellation_event,
                    accept_best_event=accept_best_event,
                    progress_callback=lambda percent, status: notify(
                        25 + round(max(0, min(100, percent)) * 0.6),
                        status,
                    ),
                    joint_progress_callback=(
                        report_joint_progress
                        if joint_progress_callback is not None
                        or joint_scene_callback is not None
                        else None
                    ),
                    source_artifact=request.source_artifact,
                    precomputed_occupied_bounds=source_data.occupied_bounds,
                    seed_profile=seed_profile,
                    seed_stl_path=seed_stl_path,
                )
                if calibration.state is CalibrationState.CANCELLED:
                    raise PreviewCancelled()
                joint_critical_failures = tuple(
                    failure
                    for failure in getattr(calibration, "failures", ())
                    if getattr(getattr(failure, "code", None), "value", "")
                    in {
                        "no_bed_space",
                        "object_override_rejected",
                        "slicer_failure",
                        "geometry_invalid",
                    }
                )
                if (
                    request.source_artifact is not None
                    and request.source_artifact.source_kind.value == "stl"
                    and request.calibration_config.perform_joint_final_slice
                    and joint_critical_failures
                ):
                    detail = " ".join(
                        item.message for item in joint_critical_failures
                    )
                    raise PreviewBuildError(
                        "Das gemeinsame Objekt-/Turm-Projekt konnte nicht "
                        "sicher geslicet werden. " + detail
                    )
                has_usable_improvement = bool(
                    getattr(
                        calibration,
                        "has_usable_improvement",
                        getattr(calibration, "success", False),
                    )
                )
                if has_usable_improvement:
                    profile = calibration.profile
                    placement = calibration.placement
                    calibrated = calibration.success
                    joint_sliced = getattr(calibration, "project_path", None) is not None
                    slicer_optimized = True
                    if joint_sliced:
                        generation_kind = (
                            "gemeinsam slicerbasiert kalibriert"
                            if calibration.success
                            else "gemeinsam gesliceter, prüfbarer Zwischenstand"
                        )
                    else:
                        generation_kind = (
                            "getrennt slicerbasiert kalibriert"
                            if calibration.success
                            else "getrennt optimierter Slicer-Zwischenstand"
                        )
                    warnings.extend(calibration.warnings)
                    artifact = (
                        calibration.gcode_path
                        if request.output_mode is OutputMode.GCODE
                        else calibration.stl_path
                    )
                    if not calibration.success:
                        warnings.append(
                            "Die Ziel-Layerzeit wurde nicht vollständig erreicht; "
                            + (
                                "verwendet wird der gemeinsam geslicte, "
                                "prüfbare Zwischenstand."
                                if joint_sliced
                                else "verwendet wird der messbar beste "
                                "Slicer-Zwischenstand."
                            )
                        )
                elif request.output_mode is OutputMode.GCODE:
                    detail = " ".join(item.message for item in calibration.failures)
                    raise PreviewBuildError(
                        "Der G-Code-Modus konnte nicht sicher kalibriert werden. "
                        + detail
                    )
                else:
                    detail = " ".join(
                        item.message for item in calibration.failures
                    )
                    raise PreviewBuildError(
                        "Die slicerbasierte Kalibrierung lieferte kein "
                        "verwendbares Ergebnis. " + detail
                    )

            if profile is None:
                raise PreviewBuildError(
                    "Der Slicer lieferte kein verwendbares Kühlturmprofil."
                )

            if artifact is None or not artifact.is_file():
                raise PreviewBuildError("Die Vorschau besitzt keine exportierbare Ausgabedatei.")

            occupied = source_data.occupied_bounds
            bed = None
            bed_geometry = None
            if request.effective_profile is not None:
                bed_geometry = parse_bed_geometry(
                    request.effective_profile.effective_values
                )
                bed = bed_geometry.bounds if bed_geometry is not None else None
            actual_tower_radius = max(
                float(getattr(point, "outer_radius_mm"))
                for point in getattr(profile, "points")
            )
            maximum_tower_radius = request.settings.maximum_outer_radius_mm
            if actual_tower_radius > maximum_tower_radius + 1e-9:
                raise PreviewBuildError(
                    "Der Kühlturm überschreitet den maximalen Turmdurchmesser."
                )
            tower_radius = maximum_tower_radius
            bed = bed or _fallback_bed(
                occupied,
                tower_radius,
                object_clearance=(
                    request.calibration_config.object_clearance_mm
                ),
                edge_clearance=(
                    request.calibration_config.bed_edge_clearance_mm
                ),
            )
            if placement is None:
                try:
                    placement = _suggest_placement(
                        bed,
                        occupied,
                        tower_radius,
                        request,
                        bed_geometry,
                    )
                except GCodeIntegrationError as error:
                    raise PreviewBuildError(str(error)) from error
            notify(90, "Vorschau wird aufgebaut …")
            tower_segments = _tower_wireframe(profile, placement)
            tower_height = max(
                float(getattr(point, "z_mm"))
                for point in getattr(profile, "points")
            )
            minimum_time = self._minimum_verified_time(request, calibration)
            final_state, final_sha256 = self._source_identity(source)
            if (
                final_state.st_size != source_data.key.file_size_bytes
                or final_state.st_mtime_ns != source_data.key.file_modified_ns
                or not compare_digest(
                    final_sha256,
                    source_data.key.content_sha256,
                )
                or not bool(request.snapshot.matches_file(source))
            ):
                self.source_data_cache.invalidate_path(source)
                raise PreviewBuildError(
                    "Der Quell-G-Code wurde während der Vorschauerstellung "
                    "verändert und muss neu geladen werden."
                )
            result = PreviewResult(
                request_signature=signature,
                refinement_seed_signature=(
                    request.refinement_seed_signature()
                ),
                output_mode=request.output_mode,
                scene=PreviewScene(
                    object_segments=object_segments,
                    tower_segments=tower_segments,
                    bed_bounds=bed,
                    tower_center_xy_mm=(
                        placement.center_x_mm,
                        placement.center_y_mm,
                    ),
                    source_segment_count=source_segment_count,
                    displayed_segment_count=len(object_segments),
                    tower_height_mm=tower_height,
                    notes=tuple(warnings),
                    object_height_mm=float(
                        getattr(request.snapshot, "maximum_print_z_mm")
                    ),
                    object_layer_count=int(
                        getattr(request.snapshot, "layer_count")
                    ),
                    tower_layer_count=int(getattr(
                        profile, "printable_layer_count",
                        len(tuple(getattr(profile, "layers", ()))),
                    )),
                    tower_circle_segments=automatic_mesh_segments(profile),
                ),
                artifact_path=artifact.resolve(),
                source_sha256=final_sha256,
                artifact_sha256=sha256_file(artifact),
                project_path=(
                    getattr(calibration, "project_path", None)
                    if calibration is not None else None
                ),
                project_sha256=(
                    sha256_file(getattr(calibration, "project_path"))
                    if calibration is not None
                    and getattr(calibration, "project_path", None) is not None
                    else None
                ),
                joint_sliced=joint_sliced,
                completed_joint_slice_count=(
                    sum(
                        1
                        for item in getattr(calibration, "iterations", ())
                        if bool(getattr(item, "joint_slice", False))
                    )
                    if calibration is not None
                    else 0
                ),
                configured_joint_slice_count=(
                    request.calibration_config.maximum_joint_slices
                    if joint_sliced
                    else 0
                ),
                calibrated=calibrated,
                generation_kind=generation_kind,
                slicer_optimized=slicer_optimized,
                calibration=calibration,
                minimum_verified_layer_time_s=minimum_time,
                target_layer_time_s=request.settings.target_layer_time_s,
                calibration_time_tolerance_s=(
                    request.calibration_config.time_tolerance_s
                ),
                calibration_slicer_result_tolerance_s=(
                    request.calibration_config
                    .slicer_result_change_tolerance_s
                ),
                calibration_profile_tolerance_mm=(
                    request.calibration_config.profile_change_tolerance_mm
                ),
                calibration_metadata_tolerance_s=(
                    request.calibration_config.slicer_metadata_tolerance_s
                ),
                warnings=tuple(warnings),
                _temporary_owner=owner,
            )
            owner = None
            notify(100, "Vorschau ist aktuell")
            return result
        finally:
            if owner is not None:
                owner.cleanup()
                record_diagnostic(
                    "temporary_data_cleaned",
                    temporary_kind="preview_directory",
                )

    @staticmethod
    def _minimum_verified_time(
        request: PreviewRequest,
        calibration: object | None,
    ) -> float | None:
        iterations = tuple(getattr(calibration, "iterations", ()))
        if not iterations:
            return None
        best = getattr(calibration, "best_iteration", None)
        iteration = best if best is not None else iterations[-1]
        minimum = minimum_combined_layer_time(iteration.evaluation)
        if minimum is not None:
            return minimum
        added = iteration.evaluation.added_time_by_layer
        values = [
            float(layer.total_time_s) + float(added.get(layer.index, 0.0))
            for layer in request.snapshot.layers
        ]
        return min(values) if values else None
