from __future__ import annotations

import math
import tempfile
from pathlib import Path
from threading import Event
from typing import Callable

from cooling_tower.diagnostic_context import record_diagnostic
from cooling_tower.calibration import CalibrationService
from cooling_tower.calibration.gcode_integration import (
    GCodeIntegrationError,
    determine_occupied_bounds,
    parse_bed_bounds,
    propose_tower_placement,
)
from cooling_tower.models import (
    BedBounds,
    CalibrationState,
    OccupiedBounds,
    TowerPlacement,
)
from cooling_tower.file_integrity import sha256_file
from cooling_tower.preview.models import (
    LineSegment3D,
    OutputMode,
    Point3D,
    PreviewRequest,
    PreviewResult,
    PreviewScene,
)
from cooling_tower.preview.toolpath import (
    PreviewCancelled,
    extract_deposition_toolpaths,
)
from cooling_tower.services.tower_need_service import (
    assess_tower_need,
    layers_for_tower,
)
from cooling_tower.tower.hollow_profile import build_hollow_tower_profile
from cooling_tower.tower.mesh_generator import (
    TowerMeshConfig,
    generate_hollow_tower_mesh,
    write_binary_stl,
)
from cooling_tower.tower.profile import (
    TowerProfileConfig,
    build_tower_radius_profile,
)


ProgressCallback = Callable[[int, str], None]


class PreviewBuildError(RuntimeError):
    pass


def _fallback_bed(occupied: OccupiedBounds, tower_radius: float) -> BedBounds:
    margin = max(15.0, tower_radius + 8.0)
    width = occupied.maximum_x_mm - occupied.minimum_x_mm
    depth = occupied.maximum_y_mm - occupied.minimum_y_mm
    return BedBounds(
        occupied.minimum_x_mm - margin,
        occupied.maximum_x_mm + margin + max(2.0 * tower_radius, width * 0.2),
        occupied.minimum_y_mm - margin,
        occupied.maximum_y_mm + margin + max(2.0 * tower_radius, depth * 0.1),
    )


def _suggest_placement(
    bed: BedBounds,
    occupied: OccupiedBounds,
    tower_radius: float,
    request: PreviewRequest,
) -> TowerPlacement:
    try:
        return propose_tower_placement(
            bed,
            occupied,
            tower_radius_mm=tower_radius,
            object_clearance_mm=request.calibration_config.object_clearance_mm,
            edge_clearance_mm=request.calibration_config.bed_edge_clearance_mm,
        )
    except GCodeIntegrationError:
        return TowerPlacement(
            bed.maximum_x_mm - tower_radius - 3.0,
            bed.minimum_y_mm + tower_radius + 3.0,
            tower_radius,
            bed,
            request.calibration_config.object_clearance_mm,
        )


def _tower_wireframe(profile: object, placement: TowerPlacement) -> tuple[LineSegment3D, ...]:
    points = tuple(getattr(profile, "points"))
    if not points:
        return ()
    segment_count = 32
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
    def __init__(self, calibration_service: CalibrationService | None = None) -> None:
        self.calibration_service = calibration_service or CalibrationService()

    def prepare(
        self,
        request: PreviewRequest,
        *,
        cancellation_event: Event | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> PreviewResult:
        notify = progress_callback or (lambda _percent, _status: None)
        signature = request.signature()
        source = request.source_path
        if not source.is_file() or not bool(request.snapshot.matches_file()):
            raise PreviewBuildError(
                "Der Quell-G-Code wurde seit der Analyse verändert und muss neu geladen werden."
            )
        owner = tempfile.TemporaryDirectory(prefix="cooling_tower_preview_")
        root = Path(owner.name)
        try:
            notify(5, "Objekt-Werkzeugpfade werden aufbereitet …")
            object_segments, source_segment_count = extract_deposition_toolpaths(
                source,
                expected_layer_count=int(getattr(request.snapshot, "layer_count")),
                maximum_segments=request.maximum_object_segments,
                cancellation_event=cancellation_event,
                progress_callback=lambda _percent, status: notify(10, status),
            )
            if not object_segments:
                raise PreviewBuildError(
                    "Im G-Code wurden keine darstellbaren Extrusionspfade gefunden."
                )
            if cancellation_event is not None and cancellation_event.is_set():
                raise PreviewCancelled()
            notify(20, "Objekt-Werkzeugpfade sind vorbereitet")

            profile = None
            calibration = None
            calibrated = False
            slicer_optimized = False
            warnings: list[str] = []
            artifact: Path | None = None
            placement: TowerPlacement | None = None
            generation_kind = "analytischer STL-Fallback"
            if request.calibration_config.maximum_iterations == 0:
                generation_kind = "analytisch erzeugt (Slicer-Durchläufe deaktiviert)"
                warnings.append(
                    "Slicer-Durchläufe wurden auf 0 gesetzt; der Kühlturm wurde "
                    "ausschließlich analytisch berechnet."
                )
            elif request.adapter is not None and request.effective_profile is not None:
                notify(25, "Slicer und Profil werden für die Kalibrierung vorbereitet …")
                calibration = self.calibration_service.calibrate(
                    request.snapshot,
                    request.settings,
                    adapter=request.adapter,
                    profile=request.effective_profile,
                    output_directory=root / "calibrated",
                    config=request.calibration_config,
                    cancellation_event=cancellation_event,
                    progress_callback=lambda percent, status: notify(
                        25 + round(max(0, min(100, percent)) * 0.6),
                        status,
                    ),
                )
                if calibration.state is CalibrationState.CANCELLED:
                    raise PreviewCancelled()
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
                    slicer_optimized = True
                    generation_kind = (
                        "slicerbasiert kalibriert"
                        if calibration.success
                        else "sliceroptimierter bester Zwischenstand"
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
                            "exportiert wird der gegenüber dem analytischen Ausgang "
                            "messbar bessere Slicer-Zwischenstand."
                        )
                elif request.output_mode is OutputMode.GCODE:
                    detail = " ".join(item.message for item in calibration.failures)
                    raise PreviewBuildError(
                        "Der G-Code-Modus konnte nicht sicher kalibriert werden. "
                        + detail
                    )
                else:
                    warnings.append(
                        "Slicerbasierte Kalibrierung war nicht erfolgreich; "
                        "der Export verwendet den analytischen STL-Fallback."
                    )

            if profile is None:
                if request.output_mode is OutputMode.GCODE:
                    raise PreviewBuildError(
                        "G-Code-Ausgabe benötigt eine bestätigte, slicerfähige Profilkombination."
                    )
                notify(35, "Analytische Kühlturmgeometrie wird berechnet …")
                assessment = assess_tower_need(request.snapshot, request.settings)
                source_layers = layers_for_tower(request.snapshot, assessment)
                radius = build_tower_radius_profile(
                    source_layers,
                    TowerProfileConfig(
                        target_layer_time_s=request.settings.target_layer_time_s,
                        safety_factor=request.settings.safety_factor,
                        minimum_radius_mm=request.settings.minimum_outer_radius_mm,
                        maximum_radius_mm=request.settings.maximum_outer_radius_mm,
                        local_time_factor_window=request.settings.local_reference_window,
                    ),
                )
                profile = build_hollow_tower_profile(
                    radius,
                    request.settings,
                    tower_end_z_mm=assessment.tower_end_z_mm,
                    object_height_mm=request.snapshot.maximum_print_z_mm,
                )
                mesh = generate_hollow_tower_mesh(
                    profile,
                    TowerMeshConfig(request.settings.mesh_segments),
                )
                artifact = root / "cooling_tower_analytic.stl"
                write_binary_stl(mesh, artifact)
                notify(80, "Analytische Kühlturmgeometrie ist erstellt")

            if artifact is None or not artifact.is_file():
                raise PreviewBuildError("Die Vorschau besitzt keine exportierbare Ausgabedatei.")

            occupied = determine_occupied_bounds(source)
            bed = None
            if request.effective_profile is not None:
                bed = parse_bed_bounds(request.effective_profile.effective_values)
            tower_radius = max(
                float(getattr(point, "outer_radius_mm"))
                for point in getattr(profile, "points")
            )
            bed = bed or _fallback_bed(occupied, tower_radius)
            placement = placement or _suggest_placement(
                bed, occupied, tower_radius, request
            )
            notify(90, "Vorschau wird aufgebaut …")
            tower_segments = _tower_wireframe(profile, placement)
            tower_height = max(
                float(getattr(point, "z_mm"))
                for point in getattr(profile, "points")
            )
            minimum_time = self._minimum_verified_time(request, calibration)
            result = PreviewResult(
                request_signature=signature,
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
                ),
                artifact_path=artifact.resolve(),
                source_sha256=sha256_file(source),
                artifact_sha256=sha256_file(artifact),
                calibrated=calibrated,
                generation_kind=generation_kind,
                slicer_optimized=slicer_optimized,
                calibration=calibration,
                minimum_verified_layer_time_s=minimum_time,
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
        added = iteration.evaluation.added_time_by_layer
        values = [
            float(layer.total_time_s) + float(added[layer.index])
            for layer in request.snapshot.layers
            if layer.index in added
        ]
        return min(values) if values else None
