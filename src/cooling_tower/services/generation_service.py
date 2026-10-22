from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from dataclasses import replace
from cooling_tower.models.layer_ranges import excluded_layer_indices

from cooling_tower.models import (
    AnalysisDiagnosticReport,
    GCodeAnalysisSnapshot,
    GenerationResult,
    GenerationSettings,
    NoTowerRequiredResult,
)
from cooling_tower.services.analysis_service import GCodeAnalysisService
from cooling_tower.services.output_service import OutputService
from cooling_tower.services.tower_need_service import (
    assess_tower_need,
    layers_for_tower,
)
from cooling_tower.tower.solid_profile import (
    build_solid_tower_profile,
    validate_solid_settings,
)
from cooling_tower.tower.mesh_generator import (
    TowerMeshConfig,
    configured_mesh_segments,
    generate_solid_tower_mesh,
    validate_mesh_config,
    write_binary_stl,
)
from cooling_tower.tower.profile import (
    TowerProfileConfig,
    build_tower_radius_profile,
    validate_profile_config,
)
from cooling_tower.models import CalibrationConfig, CalibrationResult
from cooling_tower.slicers.models import EffectiveProfile


ProgressCallback = Callable[[int, str], None]
GenerationOutcome = GenerationResult | NoTowerRequiredResult


class GenerationService:
    """Single orchestration entry point shared by all front ends."""

    def __init__(
        self,
        output_root: str | Path = "output",
        *,
        analysis_service: GCodeAnalysisService | None = None,
    ) -> None:
        self.output_service = OutputService(output_root)
        self.analysis_service = analysis_service or GCodeAnalysisService()

    def analyze(
        self,
        gcode_path: str | Path,
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> GCodeAnalysisSnapshot:
        return self.analysis_service.analyze(
            gcode_path,
            progress_callback=progress_callback,
        )

    def generate(
        self,
        gcode_path: str | Path,
        settings: GenerationSettings,
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> GenerationOutcome:
        notify = progress_callback or (lambda percent, status: None)
        snapshot = self.analysis_service.analyze(
            gcode_path,
            progress_callback=lambda percent, status: notify(
                min(35, round(percent * 0.35)), status
            ),
        )
        return self.generate_from_analysis(
            snapshot,
            settings,
            progress_callback=notify,
        )

    def calibrate(
        self,
        snapshot: GCodeAnalysisSnapshot,
        settings: GenerationSettings,
        *,
        adapter: object,
        profile: EffectiveProfile,
        config: CalibrationConfig | None = None,
        output_directory: str | Path | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> CalibrationResult:
        """Run Phase-16 slicer calibration without changing legacy export."""

        from cooling_tower.calibration.calibration_service import CalibrationService

        destination = (
            Path(output_directory)
            if output_directory is not None
            else self.output_service.output_root / "calibrated" / snapshot.gcode_path.stem
        )
        return CalibrationService().calibrate(
            snapshot,
            settings,
            adapter=adapter,
            profile=profile,
            output_directory=destination,
            config=config,
            progress_callback=progress_callback,
        )

    def generate_from_analysis(
        self,
        snapshot: GCodeAnalysisSnapshot,
        settings: GenerationSettings,
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> GenerationOutcome:
        notify = progress_callback or (lambda percent, status: None)
        profile_config, mesh_config = self._validated_configs(settings)

        if not snapshot.matches_file():
            notify(0, "Geänderter G-Code wird erneut analysiert")
            snapshot = self.analysis_service.analyze(
                snapshot.gcode_path,
                force=True,
                progress_callback=lambda percent, status: notify(
                    min(35, round(percent * 0.35)), status
                ),
            )

        assessment = assess_tower_need(snapshot, settings)
        if not assessment.tower_required:
            notify(100, "Kein Kühlturm erforderlich")
            return NoTowerRequiredResult(
                source_gcode_path=snapshot.gcode_path,
                layer_count=snapshot.layer_count,
                assessment=assessment,
                analysis_snapshot=snapshot,
                settings=settings,
            )

        source = snapshot.gcode_path
        tower_layers = layers_for_tower(snapshot, assessment)
        if not tower_layers:
            raise RuntimeError(
                "A required cooling tower unexpectedly has no layers."
            )

        paths = self.output_service.create_run_directories(source)
        self.output_service.write_settings(paths, settings)
        diagnostic_report = AnalysisDiagnosticReport.from_snapshot(snapshot)
        self.output_service.write_analysis_diagnostic(
            paths,
            diagnostic_report,
        )
        notify(40, "Turmrelevante Layer werden ausgewählt")

        profile_config = replace(
            profile_config,
            excluded_layer_indices=excluded_layer_indices(snapshot.layers, settings.excluded_layer_ranges),
        )
        radius_profile = build_tower_radius_profile(
            layers=tower_layers,
            config=profile_config,
        )
        solid_profile = build_solid_tower_profile(
            phase2_profile=radius_profile,
            settings=settings,
            tower_end_z_mm=assessment.tower_end_z_mm,
            object_height_mm=snapshot.maximum_print_z_mm,
        )
        notify(60, "Verkürztes Turmprofil wird berechnet")

        mesh = generate_solid_tower_mesh(
            solid_profile, TowerMeshConfig(configured_mesh_segments(solid_profile, settings))
        )
        export = write_binary_stl(mesh, paths.stl_path)
        notify(80, "STL und Berichte werden gespeichert")

        deficits = {
            layer.index: deficit
            for layer, deficit in zip(
                snapshot.layers,
                assessment.layer_time_deficits_s,
                strict=True,
            )
        }
        self.output_service.write_layer_analysis(
            paths,
            snapshot.layers,
            deficits=deficits,
        )
        self.output_service.write_tower_profile(
            paths,
            solid_profile.layers,
        )

        profile_layers = solid_profile.layers
        warnings = list(solid_profile.warnings)
        unresolved_layer_count = sum(
            not layer.target_reached for layer in profile_layers
        )
        summary = {
            "analysis_report_schema_version": (
                diagnostic_report.schema_version
            ),
            "source_gcode": str(source.resolve()),
            "tower_required": True,
            "layer_count": snapshot.layer_count,
            "layers_below_target": assessment.deficit_layer_count,
            "first_deficit_layer_index": (
                assessment.first_deficit_layer_index
            ),
            "last_deficit_layer_index": (
                assessment.last_deficit_layer_index
            ),
            "tower_end_layer_index": assessment.tower_end_layer_index,
            "tower_end_z_mm": assessment.tower_end_z_mm,
            "original_model_height_mm": (
                assessment.original_model_height_mm
            ),
            "saved_tower_height_mm": assessment.saved_tower_height_mm,
            "synthetic_final_layer_used": (
                assessment.synthetic_final_layer_used
            ),
            "maximum_time_deficit_s": (
                assessment.maximum_time_deficit_s
            ),
            "base_width_mm": 2.0 * solid_profile.base_outer_radius_mm,
            "automatic_base_width": settings.automatic_base_width,
            "maximum_expansion_angle_deg": (
                90.0-settings.maximum_expansion_angle_deg
            ),
            "maximum_contraction_angle_deg": (
                90.0-settings.maximum_contraction_angle_deg
            ),
            "angle_reference": "horizontal",
            "spline_support_point_count": (
                solid_profile.support_point_count
            ),
            "spline_mesh_ring_count": len(solid_profile.points),
            "maximum_spline_error_mm": (
                solid_profile.maximum_spline_error_mm
            ),
            "minimum_outer_diameter_mm": min(
                point.outer_diameter_mm for point in solid_profile.points
            ),
            "maximum_outer_diameter_mm": max(
                point.outer_diameter_mm for point in solid_profile.points
            ),
            "solid_geometry": True,
            "simulate_full_tower_infill": settings.simulate_full_tower_infill,
            "unresolved_layer_count": unresolved_layer_count,
            "gcode_metadata": {
                "schema_version": snapshot.metadata.schema_version,
                "slicer": snapshot.metadata.slicer.to_dict(),
                "profile_fingerprint": (
                    snapshot.metadata.profile_fingerprint.to_dict()
                ),
                "timing_evidence": snapshot.timing_evidence.to_dict(),
            },
            "feasibility_issues": [
                {
                    "code": issue.code,
                    "message": issue.message,
                    "affected_layer_index": issue.affected_layer_index,
                    "affected_z_mm": issue.affected_z_mm,
                    "related_setting_names": list(
                        issue.related_setting_names
                    ),
                    "required_value": (90.0-issue.required_value
                        if issue.code == "EXPANSION_ANGLE_TOO_SMALL" and issue.required_value is not None
                        else issue.required_value),
                    "achievable_value": (90.0-issue.achievable_value
                        if issue.code == "EXPANSION_ANGLE_TOO_SMALL" and issue.achievable_value is not None
                        else issue.achievable_value),
                }
                for issue in solid_profile.feasibility_issues
            ],
            "mesh": {
                "vertices": export.validation.vertex_count,
                "triangles": export.validation.face_count,
                "watertight": export.validation.is_watertight,
                "consistent_winding": (
                    export.validation.has_consistent_winding
                ),
                "outward_orientation": (
                    export.validation.has_outward_orientation
                ),
            },
            "warnings": warnings,
        }
        self.output_service.write_summary(paths, summary)
        self.output_service.write_log(
            paths,
            (
                f"G-code: {source.resolve()}",
                f"Detected layers: {snapshot.layer_count}",
                "Reported source slicer: "
                f"{snapshot.metadata.slicer.product_name or 'unknown'}",
                "Profile fingerprint: "
                f"{snapshot.metadata.profile_fingerprint.digest_sha256 or 'unavailable'}",
                "Timing evidence: "
                f"{snapshot.timing_evidence.confidence_state.value}",
                "Layers below target: "
                f"{assessment.deficit_layer_count}",
                "Last deficit layer: "
                f"{assessment.last_deficit_layer_index}",
                f"Tower end Z: {assessment.tower_end_z_mm:.6f} mm",
                f"Generated triangles: {export.validation.face_count}",
                f"STL: {paths.stl_path.resolve()}",
                *(f"Warning: {warning}" for warning in warnings),
                "Generation completed successfully.",
            ),
        )
        notify(100, "Generierung abgeschlossen")

        return GenerationResult(
            run_directory=paths.run_directory.resolve(),
            stl_path=paths.stl_path.resolve(),
            analysis_path=paths.analysis_path.resolve(),
            profile_path=paths.profile_path.resolve(),
            settings_path=paths.settings_path.resolve(),
            log_path=paths.log_path.resolve(),
            summary_path=paths.summary_path.resolve(),
            metadata_path=paths.metadata_path.resolve(),
            layer_count=snapshot.layer_count,
            layers_below_target=assessment.deficit_layer_count,
            maximum_outer_diameter_mm=summary["maximum_outer_diameter_mm"],
            warnings=warnings,
            analysis=snapshot.analysis,
            profile=tuple(profile_layers),
            mesh_validation=export.validation,
            source_gcode_path=source.resolve(),
            settings=settings,
            assessment=assessment,
            analysis_snapshot=snapshot,
            feasibility_issues=solid_profile.feasibility_issues,
        )

    @staticmethod
    def _validated_configs(
        settings: GenerationSettings,
    ) -> tuple[TowerProfileConfig, TowerMeshConfig]:
        profile_config = TowerProfileConfig(
            target_layer_time_s=settings.target_layer_time_s,
            minimum_radius_mm=settings.minimum_outer_radius_mm,
            maximum_radius_mm=settings.maximum_outer_radius_mm,
            local_time_factor_window=settings.local_reference_window,
        )
        mesh_config = TowerMeshConfig()
        validate_profile_config(profile_config)
        validate_solid_settings(settings)
        validate_mesh_config(mesh_config)
        return profile_config, mesh_config
