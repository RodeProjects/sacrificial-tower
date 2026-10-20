from __future__ import annotations
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from cooling_tower.slicers import (
    OrcaSlicerAdapter, ProfileInventoryService, ProfileMatchingService,
    SliceRequest,
)
from slicer_acceptance_support import (
    require_profile_records,
    require_slicer_installation,
)

@unittest.skipUnless(
    os.environ.get("COOLING_TOWER_RUN_INSTALLED_ORCA_INTEGRATION_TEST") == "1",
    "Orca's real read-only inventory and isolated CLI slice are opt-in.",
)
class InstalledOrcaIntegrationTests(unittest.TestCase):
    def test_real_unselected_system_filament_can_be_expanded_confirmed_and_sliced(self):
        from cooling_tower.services import SourcePreSliceService, StlValidationService
        from cooling_tower.slicers import (
            ProfileCatalogConfirmation, ProfileConfirmation, ProfileMappingStore,
            ProfileMatchingContext, ProfileSelectionReference, SecureSlicerProcessRunner,
        )
        from cooling_tower.slicers.profile_safety import fingerprint_profile_paths
        from cooling_tower.slicers import read_active_presets

        adapter = OrcaSlicerAdapter(runner=SecureSlicerProcessRunner())
        installation = require_slicer_installation(adapter)
        paths = {p for root in installation.profile_roots for p in root.rglob("*") if p.is_file()}
        config_path = read_active_presets(installation).source_path
        self.assertIsNotNone(config_path)
        paths.add(config_path)
        before = fingerprint_profile_paths(paths)
        build_root = PROJECT_ROOT / "build"
        build_root.mkdir(exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(dir=build_root) as temporary:
                root = Path(temporary)
                matching = ProfileMatchingService(inventory_service=ProfileInventoryService(), mapping_store=ProfileMappingStore(root / "mappings.json"))
                selected = require_profile_records(
                    self,
                    test_key="orca_unselected_system_filament",
                    adapter=adapter,
                    installation=installation,
                    roles=("machine", "process", "filament"),
                    expected_sources={"filament": "system"},
                )
                machine = selected["machine"]
                process = selected["process"]
                filament = selected["filament"]
                reference = ProfileSelectionReference(machine.profile_id, machine.path)
                filtered = matching.catalog(installation, adapter, selected_machine=reference)
                self.assertNotIn(filament.path, {r.path for r in filtered.filament_options})
                expanded = matching.catalog(installation, adapter, selected_machine=reference, include_all_profiles=True)
                confirmation = ProfileCatalogConfirmation.from_catalog(
                    expanded, machine_path=machine.path, process_path=process.path,
                    filament_path=filament.path, machine_profile_id=machine.profile_id,
                    process_profile_id=process.profile_id, filament_profile_id=filament.profile_id,
                )
                source = root / "source" / "model.stl"
                source.parent.mkdir()
                source.write_text(_tiny_cube_ascii_stl(), encoding="ascii")
                validation = StlValidationService().validate(source)
                self.assertTrue(validation.accepted, validation.technical_summary)
                result = matching.match(ProfileMatchingContext.from_stl(validation.source_artifact), installation, adapter,
                                        selected_profile_ids=confirmation.selected_profile_ids(), include_all_profiles=True)
                self.assertIsNotNone(result.selected, result.message)
                self.assertEqual(result.selected.filament.path, filament.path)
                binding = ProfileConfirmation.from_result(result, validation.source_artifact)
                confirmed = matching.confirm(result)
                self.assertTrue(confirmed.can_use_stl_mode)
                sliced = SourcePreSliceService(workspace_parent=root / "preslice", timeout_s=180).run(
                    stl_validation=validation, profile_match=confirmed, confirmation=binding, adapter=adapter,
                )
                try:
                    self.assertTrue(sliced.metadata_verified)
                    self.assertGreater(sliced.analysis_snapshot.layer_count, 0)
                    self.assertIn(filament.name, sliced.slice_result.gcode_path.read_text(encoding="utf-8"))
                finally:
                    sliced.cleanup()
        finally:
            self.assertEqual(before, fingerprint_profile_paths(paths))
            after = {p for root in installation.profile_roots for p in root.rglob("*") if p.is_file()}
            after.add(config_path)
            self.assertEqual(paths, after)

    def test_real_orca_confirmation_preslice_and_calibration_preserve_slicer_files(
        self,
    ) -> None:
        from cooling_tower.services import (
            GCodeAnalysisService,
            SourcePreSliceService,
            StlValidationService,
        )
        from cooling_tower.calibration import CalibrationService
        from cooling_tower.manual.geometry import ManualSettings, initial_draft
        from cooling_tower.manual.service import ManualGenerationService, ManualRequest, ManualExportService
        from cooling_tower.models import CalibrationConfig, CalibrationMode, GenerationSettings
        from cooling_tower.preview import OutputMode, PreviewService, PreviewRequest, PreviewExportService
        from cooling_tower.slicers import (
            ProfileCatalogConfirmation,
            ProfileConfirmation,
            ProfileMappingStore,
            ProfileMatchingContext,
            ProfileSelectionReference,
            SecureSlicerProcessRunner,
        )
        adapter = OrcaSlicerAdapter(runner=SecureSlicerProcessRunner())
        installation = require_slicer_installation(adapter)
        executable = installation.executable_path
        build_root = PROJECT_ROOT / "build"
        build_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=build_root) as temporary:
            root = Path(temporary)
            selected_records = require_profile_records(
                self,
                test_key="orca_confirmation_preslice",
                adapter=adapter,
                installation=installation,
                roles=("machine", "process", "filament"),
                expected_sources={
                    "machine": "user",
                    "process": "user",
                    "filament": "user",
                },
            )
            references = {
                role: ProfileSelectionReference(record.profile_id, record.path)
                for role, record in selected_records.items()
            }
            original_paths = {executable}
            from cooling_tower.slicers import read_active_presets
            active = read_active_presets(installation)
            if active.source_path:
                original_paths.add(active.source_path)
            for profile_root in installation.profile_roots:
                if profile_root.is_dir():
                    original_paths.update(
                        path for path in profile_root.rglob("*") if path.is_file()
                    )
            before = {
                path: (path.stat().st_size, path.stat().st_mtime_ns, path.read_bytes())
                for path in original_paths
            }
            source_root = root / "source"
            source_root.mkdir()
            model_path = source_root / "tiny.stl"
            model_path.write_text(_tiny_cube_ascii_stl(), encoding="ascii")
            preslice_result = None
            manual_result = None
            try:
                validation = StlValidationService().validate(model_path)
                self.assertTrue(validation.accepted, validation.technical_summary)
                matching = ProfileMatchingService(
                    inventory_service=ProfileInventoryService(
                        root / "profile-inventory.json"
                    ),
                    mapping_store=ProfileMappingStore(root / "profile-mappings.json"),
                )
                catalog = matching.catalog(
                    installation,
                    adapter,
                    selected_machine=references["machine"],
                    selected_profile_ids=references,
                )
                # Orca's enabled library is separate from the active user
                # material. Its exact persisted choice backs the system group.
                from cooling_tower.slicers.active_presets import _load_json_with_checksum_footer
                self.assertIsNotNone(active.source_path)
                saved = _load_json_with_checksum_footer(active.source_path.read_text(encoding="utf-8-sig"))
                enabled = set(saved["filaments"])
                self.assertTrue(enabled, "This opt-in fixture expects enabled system materials.")
                self.assertEqual({r.name for r in catalog.filament_options if r.source == "system"}, enabled)
                self.assertIn(references["filament"].path, {r.path for r in catalog.filament_options if r.source == "user"})
                expanded = matching.catalog(installation, adapter, selected_machine=references["machine"], include_all_profiles=True)
                expanded_system = {r.name for r in expanded.filament_options if r.source == "system"}
                self.assertLess(enabled, expanded_system)
                catalog_confirmation = ProfileCatalogConfirmation.from_catalog(
                    catalog,
                    machine_path=references["machine"].path,
                    process_path=references["process"].path,
                    filament_path=references["filament"].path,
                    machine_profile_id=references["machine"].profile_id,
                    process_profile_id=references["process"].profile_id,
                    filament_profile_id=references["filament"].profile_id,
                )
                match = matching.match(
                    ProfileMatchingContext.from_stl(validation.source_artifact),
                    installation,
                    adapter,
                    selected_profile_ids=(
                        catalog_confirmation.selected_profile_ids()
                    ),
                )
                self.assertIsNotNone(match.selected)
                assert match.selected is not None
                self.assertEqual(
                    match.selected.effective_profile.machine.profile_id,
                    references["machine"].profile_id,
                )
                self.assertEqual(
                    match.selected.effective_profile.process.profile_id,
                    references["process"].profile_id,
                )
                self.assertEqual(
                    match.selected.effective_profile.filaments[0].profile_id,
                    references["filament"].profile_id,
                )
                source_confirmation = ProfileConfirmation.from_result(
                    match,
                    validation.source_artifact,
                )
                confirmed = matching.confirm(match)
                self.assertTrue(confirmed.user_confirmed)
                self.assertFalse(confirmed.requires_confirmation)
                effective = confirmed.selected.effective_profile

                preslice_result = SourcePreSliceService(
                    workspace_parent=root / "preslice-workspaces",
                    diagnostics_root=root / "preslice-diagnostics",
                    timeout_s=180,
                ).run(
                    stl_validation=validation,
                    profile_match=confirmed,
                    confirmation=source_confirmation,
                    adapter=adapter,
                )
                result = preslice_result.slice_result
                self.assertTrue(result.success, result.failure_reason or result.stderr)
                self.assertTrue(result.gcode_path and result.gcode_path.is_file())
                assert result.gcode_path is not None
                source_bytes = result.gcode_path.read_bytes()
                self.assertNotEqual(source_bytes[:4], b"GCDE")
                source_text = source_bytes.decode("utf-8", errors="replace")
                for key in ("printer_model", "layer_height", "filament_type"):
                    expected = effective.effective_values[key]
                    if isinstance(expected, (list, tuple)):
                        expected = ",".join(str(item) for item in expected)
                    actual = next((line.split(" = ", 1)[1] for line in source_text.splitlines()
                                   if line.startswith(f"; {key} = ")), None)
                    self.assertIsNotNone(actual, f"Missing emitted setting: {key}")
                    if key == "layer_height":
                        self.assertAlmostEqual(float(actual), float(expected))
                    else:
                        self.assertEqual(actual, expected, key)
                self.assertGreater(preslice_result.analysis_snapshot.layer_count, 0)
                self.assertTrue(preslice_result.metadata_verified)

                from cooling_tower.calibration.slice_evaluator import (
                    build_calibration_profile,
                )

                calibration_profile, calibration_overrides = (
                    build_calibration_profile(
                        effective,
                        root / "calibration-profile",
                        simulate_full_tower_infill=True,
                    )
                )
                self.assertEqual(calibration_overrides["sparse_infill_density"], "100%")
                calibration_result = adapter.slice_model(
                    SliceRequest(
                        model_path=model_path,
                        profile=calibration_profile,
                        output_directory=root / "calibration-output",
                        timeout_s=180,
                        retain_failure_diagnostics=False,
                        temporary_overrides=calibration_overrides,
                        purpose="calibration",
                    )
                )
                self.assertTrue(
                    calibration_result.success,
                    "\n".join(
                        item
                        for item in (
                            calibration_result.failure_reason,
                            calibration_result.stderr,
                            calibration_result.stdout,
                        )
                        if item
                    ),
                )
                self.assertIsNotNone(calibration_result.gcode_path)
                assert calibration_result.gcode_path is not None
                calibration_bytes = calibration_result.gcode_path.read_bytes()
                self.assertNotEqual(calibration_bytes[:4], b"GCDE")
                calibration_snapshot = GCodeAnalysisService().analyze(
                    calibration_result.gcode_path
                )
                self.assertGreater(calibration_snapshot.layer_count, 0)
                calibration_text = calibration_bytes.decode(
                    "utf-8", errors="replace"
                )
                self.assertTrue("; sparse_infill_density = 100%" in calibration_text)

                automatic_settings = GenerationSettings(
                    target_layer_time_s=(
                        preslice_result.analysis_snapshot.minimum_layer_time_s + 1.0
                    ),
                    simulate_full_tower_infill=True,
                )
                automatic_result = CalibrationService().calibrate(
                    preslice_result.analysis_snapshot,
                    automatic_settings,
                    adapter=adapter,
                    profile=effective,
                    output_directory=root / "automatic-output",
                    config=CalibrationConfig(
                        maximum_iterations=4,
                        maximum_runtime_s=180,
                        timeout_per_slice_s=180,
                    ),
                    source_artifact=validation.source_artifact,
                    force_tower=True,
                )
                self.assertTrue(
                    automatic_result.has_usable_improvement,
                    (
                        automatic_result.state,
                        automatic_result.failures,
                        automatic_result.warnings,
                        [(item.number, min(item.evaluation.combined_time_by_layer.values(), default=-1)) for item in automatic_result.iterations],
                    ),
                )
                self.assertTrue(automatic_result.iterations)
                # A deliberately small iteration budget can retain a measured
                # intermediate result. It must never hide a slicing failure.
                self.assertTrue(all(failure.code.value == "iteration_limit" for failure in automatic_result.failures))
                self.assertTrue(automatic_result.project_path and automatic_result.project_path.is_file())
                self.assertTrue(
                    automatic_result.stl_path
                    and automatic_result.stl_path.is_file()
                )

                manual_settings = GenerationSettings(
                    simulate_full_tower_infill=True,
                )
                manual_request = ManualRequest(
                    snapshot=preslice_result.analysis_snapshot,
                    settings=manual_settings,
                    output_mode=OutputMode.STL,
                    calibration_config=CalibrationConfig(maximum_iterations=1),
                    slicer_identity_key=installation.identity_key,
                    profile_fingerprint=confirmed.effective_profile_fingerprint,
                    effective_profile=effective,
                    adapter=adapter,
                    source_artifact=validation.source_artifact,
                    prepared_analysis_source=preslice_result.prepared_source,
                    prepared_source_data=preslice_result.preview_source_data,
                )
                manual_service = ManualGenerationService(
                    PreviewService(),
                    root / "manual-workspaces",
                    GCodeAnalysisService(),
                )
                manual_reference = manual_service.prepare_reference(manual_request)
                manual_draft = initial_draft(
                    ManualSettings(),
                    manual_request.snapshot.layers,
                    manual_reference.context.maximum_height_mm,
                    manual_reference.context.key,
                )
                manual_request = replace(
                    manual_request,
                    draft=manual_draft,
                    context=manual_reference.context,
                    profile_source_hashes=manual_reference.profile_source_hashes,
                )
                manual_result = manual_service.prepare(manual_request)
                self.assertTrue(manual_result.joint_sliced)
                self.assertTrue(manual_result.artifact_path.is_file())
                self.assertTrue(manual_result.manual_evaluation.layer_times)
                manual_gcode = manual_result.manual_evaluation.gcode_path.read_bytes()
                self.assertNotEqual(manual_gcode[:4], b"GCDE")
                manual_text = manual_gcode.decode("utf-8", errors="replace")
                from cooling_tower.calibration.joint_project import validate_joint_project, validate_tower_infill_adoption
                self.assertTrue(manual_result.project_path and manual_result.project_path.is_file())
                validate_joint_project(manual_result.project_path, tower_full_infill=True)
                validate_tower_infill_adoption(manual_result.manual_evaluation.gcode_path)
                # Source density remains its saved value. Full infill is
                # scoped to the tower object in the durable joint project.
                self.assertTrue(f"; sparse_infill_density = {effective.effective_values['sparse_infill_density']}" in manual_text)
                exported = ManualExportService().export(manual_result, manual_request, root / "manual-export")
                self.assertTrue(exported.output_path.is_file())
                self.assertTrue(exported.project_path and exported.project_path.is_file())
                self.assertTrue(exported.report_path.is_file())
                validate_joint_project(exported.project_path, tower_full_infill=True)
                backend_report = adapter.validate_process_backends(SliceRequest(
                    model_path=model_path, profile=effective,
                    output_directory=root / "backend-output", timeout_s=180,
                    retain_failure_diagnostics=False,
                ))
                self.assertTrue(backend_report.equivalent, backend_report.differences)
                self.assertTrue(backend_report.qprocess.success)
                reopened = adapter.slice_model(SliceRequest(
                    model_path=exported.project_path, profile=calibration_profile,
                    output_directory=root / "reopened-export", timeout_s=180,
                    retain_failure_diagnostics=False, purpose="calibration",
                    preserve_model_positions=True,
                ))
                self.assertTrue(reopened.success, reopened.failure_reason)
                validate_tower_infill_adoption(reopened.gcode_path)
                reopened_snapshot = GCodeAnalysisService().analyze(reopened.gcode_path)
                self.assertAlmostEqual(reopened_snapshot.minimum_layer_time_s,
                                       manual_result.manual_evaluation.minimum_time_s, places=6)
                from cooling_tower.preview.joint_source_toolpath import analyze_joint_source_toolpaths
                actual_source_paths = analyze_joint_source_toolpaths(
                    reopened.gcode_path,
                    tower_center_xy_mm=manual_result.scene.tower_center_xy_mm,
                    expected_layer_count=preslice_result.analysis_snapshot.layer_count,
                )
                bounds = actual_source_paths.occupied_bounds
                self.assertGreater(len(actual_source_paths.object_segments), 0)
                tx, ty = manual_result.scene.tower_center_xy_mm
                self.assertFalse(bounds.minimum_x_mm <= tx <= bounds.maximum_x_mm
                                 and bounds.minimum_y_mm <= ty <= bounds.maximum_y_mm)
                self.assertLess(bounds.maximum_x_mm - bounds.minimum_x_mm, 12)

                # Exercise the actual automatic preview/export orchestration
                # for both output modes, beyond the calibration service alone.
                preview_service = PreviewService()
                for mode in (OutputMode.STL, OutputMode.GCODE):
                    with self.subTest(automatic_output=mode.value):
                        preview_request = PreviewRequest(
                            snapshot=preslice_result.analysis_snapshot,
                            settings=(replace(automatic_settings, simulate_tower_without_supports=True,
                                              simulate_source_supports=True)
                                      if mode is OutputMode.GCODE else automatic_settings),
                            output_mode=mode,
                            calibration_config=CalibrationConfig(
                                mode=CalibrationMode(mode.value), maximum_iterations=4,
                                maximum_runtime_s=180, timeout_per_slice_s=180,
                            ),
                            slicer_identity_key=installation.identity_key,
                            profile_fingerprint=confirmed.effective_profile_fingerprint,
                            effective_profile=effective, adapter=adapter,
                            source_artifact=validation.source_artifact,
                            prepared_analysis_source=preslice_result.prepared_source,
                            prepared_source_data=preslice_result.preview_source_data,
                            force_tower=True,
                        )
                        preview = preview_service.prepare(preview_request)
                        try:
                            self.assertTrue(preview.joint_sliced)
                            self.assertTrue(preview.slicer_optimized)
                            automatic_export = PreviewExportService().export(
                                preview, preview_request, root / f"automatic-export-{mode.value}"
                            )
                            self.assertTrue(automatic_export.output_path.is_file())
                            self.assertTrue(automatic_export.project_path and automatic_export.project_path.is_file())
                            validate_joint_project(
                                automatic_export.project_path, tower_full_infill=True,
                                tower_supports_disabled=mode is OutputMode.GCODE,
                                source_supports_enabled=mode is OutputMode.GCODE,
                            )
                        finally:
                            preview.dispose()

                simulated_request = replace(manual_request, settings=GenerationSettings(
                    simulate_full_tower_infill=True,
                    simulate_source_supports=True,
                ))
                simulated = manual_service.prepare(simulated_request)
                try:
                    validate_joint_project(simulated.project_path, tower_full_infill=True,
                                           source_supports_enabled=True)
                    self.assertTrue(simulated.manual_evaluation.layer_times)
                finally:
                    simulated.dispose()

                # Exercise saved system presets as well as both user materials
                # and processes, including the saved support-enabled process.
                by_name = {record.name: record for record in inventory}
                combinations = (
                    ("Anker M5 0.4 nozzle", "0.20mm Standard @Anker", "Generic PLA @System"),
                    ("Anker M5 0.4 nozzle - Eigenes Maschinenprofil 1", "Eigenes Prozessprofil 1", "Eigenes Filamentprofil 1"),
                    ("Anker M5 0.4 nozzle", "Eigenes Prozessprofil 2 (ohne Stützen)", "Eigenes Filamentprofil 2"),
                )
                for index, names in enumerate(combinations):
                    with self.subTest(profiles=names):
                        choices = {role: ProfileSelectionReference(by_name[name].profile_id, by_name[name].path)
                                   for role, name in zip(("machine", "process", "filament"), names)}
                        combination = matching.match(
                            ProfileMatchingContext.from_stl(validation.source_artifact),
                            installation, adapter, selected_profile_ids=choices,
                        )
                        self.assertIsNotNone(combination.selected)
                        binding = ProfileConfirmation.from_result(combination, validation.source_artifact)
                        combination = matching.confirm(combination)
                        prepared = SourcePreSliceService(workspace_parent=root / f"combination-{index}", timeout_s=180).run(
                            stl_validation=validation, profile_match=combination,
                            confirmation=binding, adapter=adapter,
                        )
                        try:
                            self.assertTrue(prepared.metadata_verified)
                            self.assertGreater(prepared.analysis_snapshot.layer_count, 0)
                        finally:
                            prepared.cleanup()
                self.assertTrue(validation.source_artifact.matches_current_file(verify_content=True))
            finally:
                if manual_result is not None:
                    manual_result.dispose()
                if preslice_result is not None:
                    preslice_result.cleanup()
                after_paths = {executable}
                if active.source_path:
                    after_paths.add(active.source_path)
                for profile_root in installation.profile_roots:
                    after_paths.update(path for path in profile_root.rglob("*") if path.is_file())
                self.assertEqual(original_paths, after_paths)
                self.assertEqual(
                    before,
                    {
                        path: (
                            path.stat().st_size,
                            path.stat().st_mtime_ns,
                            path.read_bytes(),
                        )
                        for path in original_paths
                    },
                )


def _tiny_cube_ascii_stl() -> str:
    vertices = (
        ((0, 0, 0), (10, 0, 0), (10, 10, 0)),
        ((0, 0, 0), (10, 10, 0), (0, 10, 0)),
        ((0, 0, 10), (10, 10, 10), (10, 0, 10)),
        ((0, 0, 10), (0, 10, 10), (10, 10, 10)),
        ((0, 0, 0), (0, 0, 10), (10, 0, 10)),
        ((0, 0, 0), (10, 0, 10), (10, 0, 0)),
        ((10, 0, 0), (10, 0, 10), (10, 10, 10)),
        ((10, 0, 0), (10, 10, 10), (10, 10, 0)),
        ((10, 10, 0), (10, 10, 10), (0, 10, 10)),
        ((10, 10, 0), (0, 10, 10), (0, 10, 0)),
        ((0, 10, 0), (0, 10, 10), (0, 0, 10)),
        ((0, 10, 0), (0, 0, 10), (0, 0, 0)),
    )
    lines = ["solid test_cube"]
    for triangle in vertices:
        # The coordinates above use the convenient face order from the
        # outside looking in.  STL needs the opposite winding so the closed
        # mesh has a positive signed volume during strict validation.
        triangle = (triangle[0], triangle[2], triangle[1])
        lines.append("  facet normal 0 0 0")
        lines.append("    outer loop")
        lines.extend(
            "      vertex " + " ".join(map(str, point))
            for point in triangle
        )
        lines.extend(("    endloop", "  endfacet"))
    lines.append("endsolid test_cube")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    unittest.main()
