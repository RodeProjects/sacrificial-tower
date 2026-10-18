from __future__ import annotations

import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from cooling_tower.slicers import (
    EffectiveProfile,
    ProfileCandidate,
    ProfileInventoryService,
    ProfileKind,
    ProfileMatchingService,
    ProcessOutcome,
    PrusaSlicerAdapter,
    SliceRequest,
    SlicerCapability,
    SlicerDiscoverySource,
    SlicerInstallation,
    SlicerSupportLevel,
)
from cooling_tower.slicers.detection.prusa_slicer import (
    PrusaSlicerDetectionModule,
)
from cooling_tower.slicers.prusa_profile_catalog import PrusaProfileCatalog


class PrusaSlicerIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.appdata = self.root / "AppData" / "Roaming"
        self.user_root = self.appdata / "PrusaSlicer"
        self.executable = self.root / "install" / "prusa-slicer.exe"
        self.resource_profiles = self.executable.parent / "resources" / "profiles"
        for directory in (
            self.user_root / "printer",
            self.user_root / "print",
            self.user_root / "filament",
            self.user_root / "vendor",
            self.user_root / "cache" / "vendor",
            self.user_root / "physical_printer",
            self.resource_profiles,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        self.executable.write_bytes(b"test executable placeholder")
        self.installation = SlicerInstallation(
            adapter_id="prusa_slicer",
            product_name="PrusaSlicer",
            version="2.9.0",
            executable_path=self.executable,
            verified=True,
            capabilities=frozenset(
                {
                    SlicerCapability.PROFILE_INVENTORY,
                    SlicerCapability.CLI_SLICE,
                }
            ),
            discovery_source=SlicerDiscoverySource.KNOWN_PATH,
            support_level=SlicerSupportLevel.FULL,
            profile_roots=(
                self.user_root / "printer",
                self.user_root / "print",
                self.user_root / "filament",
                self.user_root / "vendor",
                self.resource_profiles,
            ),
        )
        self.adapter = PrusaSlicerAdapter(runner=Mock())

    def _write(self, path: Path, content: str) -> Path:
        path.write_text(content, encoding="utf-8")
        return path

    def _create_profile_fixtures(self) -> dict[str, Path]:
        paths = {
            "machine": self._write(
                self.user_root
                / "printer"
                / "MK4S HF0.4 - Eigenes Maschinenprofil.ini",
                "inherits = Original Prusa MK4S HF0.4 nozzle\n"
                "printer_model = MK4S\n"
                "printer_variant = HF0.4\n"
                "nozzle_diameter = 0.4\n"
                "max_print_height = 250\n",
            ),
            "process": self._write(
                self.user_root / "print" / "Eigenes Prozessprofil.ini",
                "inherits = 0.20mm SPEED @MK4S HF0.4\n"
                "layer_height = 0.18\n"
                "perimeters = 4\n",
            ),
            "ambiguous_process": self._write(
                self.user_root / "print" / "Eigenes Prozessprofil mehrdeutig.ini",
                "inherits = *common*\nlayer_height = 0.1\n",
            ),
            "filament": self._write(
                self.user_root / "filament" / "Eigenes Filament.ini",
                "inherits = Generic PLA @MK4S HF0.4\n"
                "filament_type = PLA\n"
                "temperature = 218\n",
            ),
            "active_vendor": self._write(
                self.user_root / "vendor" / "PrusaResearch.ini",
                "[printer:Original Prusa MK4S HF0.4 nozzle]\n"
                "printer_model = MK4S\nprinter_variant = HF0.4\n"
                "nozzle_diameter = 0.4\nmax_print_height = 250\n"
                "[print:0.20mm SPEED @MK4S HF0.4]\n"
                "layer_height = 0.20\nperimeters = 3\n"
                "[print:*common*]\nperimeters = 2\n"
                "[filament:Generic PLA @MK4S HF0.4]\n"
                "filament_type = PLA\ntemperature = 215\n",
            ),
            "other_vendor": self._write(
                self.user_root / "vendor" / "OtherVendor.ini",
                "[print:*common*]\nperimeters = 9\n"
                "[print:Other Vendor Quality]\n"
                "inherits = *common*\nlayer_height = 0.3\n",
            ),
            "bundled": self._write(
                self.resource_profiles / "PrusaResearch.ini",
                "[printer:Original Prusa MK4S HF0.4 nozzle]\n"
                "printer_model = stale\nprinter_variant = stale\n"
                "nozzle_diameter = 0.6\nmax_print_height = 10\n"
                "[print:0.20mm SPEED @MK4S HF0.4]\n"
                "layer_height = 0.20\nperimeters = 7\n"
                "[print:*common*]\nperimeters = 7\n"
                "[filament:Generic PLA @MK4S HF0.4]\n"
                "filament_type = PLA\ntemperature = 250\n",
            ),
        }
        self._write(
            self.user_root / "cache" / "vendor" / "Stale.ini",
            "[print:Must not load]\nlayer_height = 9\n",
        )
        self._write(
            self.user_root / "physical_printer" / "Connection.ini",
            "[printer:Connection data]\nprinter_model = secret\n",
        )
        self._write(
            self.user_root / "PrusaSlicer.ini",
            "[presets]\n"
            "printer = MK4S HF0.4 - Eigenes Maschinenprofil\n"
            "print = Eigenes Prozessprofil\n"
            "filament = Eigenes Filament\n",
        )
        return paths

    def test_module_roots_cover_active_user_and_system_catalogues_only(self) -> None:
        module = PrusaSlicerDetectionModule()
        roots = module.profile_roots_for(
            self.executable,
            appdata_root=self.appdata,
        )
        normalized = {path.resolve() for path in roots}
        self.assertIn((self.user_root / "printer").resolve(), normalized)
        self.assertIn((self.user_root / "print").resolve(), normalized)
        self.assertIn((self.user_root / "filament").resolve(), normalized)
        self.assertIn((self.user_root / "vendor").resolve(), normalized)
        self.assertIn(self.resource_profiles.resolve(), normalized)
        self.assertFalse(any("cache" in path.parts for path in normalized))
        self.assertFalse(
            any(path.name.casefold() == "physical_printer" for path in normalized)
        )
        self.assertEqual(
            module.usage_marker_paths(appdata_root=self.appdata),
            (self.user_root / "PrusaSlicer.ini",),
        )

    def test_flat_user_ini_and_sectioned_vendor_profiles_are_typed_and_filtered(self) -> None:
        self._create_profile_fixtures()
        with patch.dict(os.environ, {"APPDATA": str(self.appdata)}):
            records = self.adapter.discover_profiles(self.installation)

        own = {record.name: record for record in records if record.source == "user"}
        self.assertEqual(
            own["MK4S HF0.4 - Eigenes Maschinenprofil"].kind,
            ProfileKind.MACHINE,
        )
        self.assertEqual(
            own["Eigenes Prozessprofil"].kind,
            ProfileKind.PROCESS,
        )
        self.assertEqual(own["Eigenes Filament"].kind, ProfileKind.FILAMENT)
        self.assertEqual(
            own["Eigenes Prozessprofil"].inherits,
            ("0.20mm SPEED @MK4S HF0.4",),
        )
        self.assertNotIn("Must not load", {record.name for record in records})
        self.assertNotIn("Connection data", {record.name for record in records})
        abstract = [record for record in records if record.name == "*common*"]
        self.assertEqual(
            {record.metadata.get("vendor") for record in abstract},
            {"PrusaResearch", "OtherVendor"},
        )
        visible_machine = [
            record
            for record in records
            if record.name == "Original Prusa MK4S HF0.4 nozzle"
        ]
        self.assertEqual(len(visible_machine), 1)
        self.assertEqual(
            visible_machine[0].metadata.get("catalog_origin"),
            "active_vendor",
        )

    def test_inheritance_uses_active_vendor_mirror_and_scopes_abstract_parent_by_vendor(self) -> None:
        from cooling_tower.slicers.profile_inventory import ProfileInheritanceResolver
        from cooling_tower.slicers.profile_models import ProfileInventory

        paths = self._create_profile_fixtures()
        with patch.dict(os.environ, {"APPDATA": str(self.appdata)}):
            records = self.adapter.discover_profiles(self.installation)
            by_name = {record.name: record for record in records if record.source == "user"}
            effective = self.adapter.resolve_profile_bundle(
                ProfileCandidate(
                    installation=self.installation,
                    machine=by_name["MK4S HF0.4 - Eigenes Maschinenprofil"],
                    process=by_name["Eigenes Prozessprofil"],
                    filaments=(by_name["Eigenes Filament"],),
                )
            )
            other_vendor_quality = next(
                record
                for record in records
                if record.name == "Other Vendor Quality"
            )
            other_vendor_effective = ProfileInheritanceResolver(
                ProfileInventory(self.installation, tuple(records), (), ""),
                self.adapter,
            ).resolve(other_vendor_quality)
            ambiguous_effective = ProfileInheritanceResolver(
                ProfileInventory(self.installation, tuple(records), (), ""),
                self.adapter,
            ).resolve(by_name["Eigenes Prozessprofil mehrdeutig"])

        self.assertEqual(effective.effective_values["max_print_height"], "250")
        self.assertEqual(effective.effective_values["layer_height"], "0.18")
        self.assertEqual(effective.effective_values["temperature"], "218")
        self.assertTrue(other_vendor_effective.valid, other_vendor_effective.errors)
        self.assertEqual(other_vendor_effective.effective_values["perimeters"], "9")
        self.assertFalse(ambiguous_effective.valid)
        self.assertTrue(
            any("Mehrdeutiges Basisprofil '*common*'" in item for item in ambiguous_effective.errors),
            ambiguous_effective.errors,
        )
        for path in paths.values():
            self.assertTrue(path.is_file())
        self.assertEqual(paths["bundled"].read_text(encoding="utf-8").count("stale"), 2)

    def test_profile_matching_returns_filtered_role_options_with_user_and_system_sources(self) -> None:
        self._create_profile_fixtures()
        with patch.dict(os.environ, {"APPDATA": str(self.appdata)}):
            catalog = ProfileMatchingService(
                inventory_service=ProfileInventoryService()
            ).catalog(
                self.installation,
                self.adapter,
                include_all_profiles=True,
                prefer_active_presets=True,
            )

        self.assertTrue(catalog.complete, catalog.missing_roles)
        self.assertTrue(any(item.source == "user" for item in catalog.machine_options))
        self.assertTrue(any(item.source == "system" for item in catalog.machine_options))
        self.assertIn(
            "Eigenes Prozessprofil",
            {item.name for item in catalog.process_options if item.source == "user"},
        )
        self.assertIn(
            "Eigenes Filament",
            {item.name for item in catalog.filament_options if item.source == "user"},
        )
        self.assertFalse(
            any(item.name == "*common*" for item in catalog.process_options)
        )

    def test_slice_command_uses_only_a_temporary_effective_ini_and_gcode_export(self) -> None:
        paths = self._create_profile_fixtures()
        with patch.dict(os.environ, {"APPDATA": str(self.appdata)}):
            records = self.adapter.discover_profiles(self.installation)
        by_name = {record.name: record for record in records if record.source == "user"}
        profile = EffectiveProfile(
            installation=self.installation,
            machine=by_name["MK4S HF0.4 - Eigenes Maschinenprofil"],
            process=by_name["Eigenes Prozessprofil"],
            filaments=(by_name["Eigenes Filament"],),
            effective_values={
                "inherits": "must-not-be-forwarded",
                "instantiation": False,
                "printer_settings_id": "must-not-be-forwarded",
                "layer_height": "0.18",
                "temperature": 218,
                "binary_gcode": object(),
                "custom_gcode": "first line\nsecond line",
            },
        )
        request = SliceRequest(
            model_path=self.root / "model.stl",
            profile=profile,
            output_directory=self.root / "result",
            temporary_overrides={
                "layer_height": "0.12",
                "fill_density": "100%",
                # The adapter owns the analysis transport format even if a
                # caller accidentally requests binary Prusa G-code.
                "binary_gcode": True,
            },
        )
        working = self.root / "working"
        output = self.root / "output"
        working.mkdir()
        output.mkdir()
        executable, arguments = self.adapter.build_slice_command(
            request,
            request.model_path,
            output,
            working,
        )
        temporary_config = Path(arguments[1])
        serialized = temporary_config.read_text(encoding="utf-8")
        self.assertTrue(
            executable.samefile(self.executable),
            "The adapter must use the configured PrusaSlicer executable.",
        )
        self.assertEqual(
            arguments,
            (
                "--load",
                str(temporary_config),
                "--export-gcode",
                "--output",
                str(output / "model.gcode"),
                str(request.model_path),
            ),
        )
        self.assertIn("layer_height = 0.12", serialized)
        self.assertIn("fill_density = 100%", serialized)
        self.assertIn("temperature = 218", serialized)
        self.assertIn("custom_gcode = first line\\nsecond line", serialized)
        self.assertNotIn("must-not-be-forwarded", serialized)
        self.assertIn("binary_gcode = 0", serialized)
        self.assertTrue(all(path.is_file() for path in paths.values()))

    def test_binary_prusa_output_is_rejected_with_a_specific_user_message(self) -> None:
        paths = self._create_profile_fixtures()
        with patch.dict(os.environ, {"APPDATA": str(self.appdata)}):
            records = self.adapter.discover_profiles(self.installation)
        by_name = {record.name: record for record in records if record.source == "user"}
        effective = self.adapter.resolve_profile_bundle(
            ProfileCandidate(
                installation=self.installation,
                machine=by_name["MK4S HF0.4 - Eigenes Maschinenprofil"],
                process=by_name["Eigenes Prozessprofil"],
                filaments=(by_name["Eigenes Filament"],),
            )
        )
        model = self.root / "model.stl"
        model.write_text(_tiny_cube_ascii_stl(), encoding="ascii")

        def run(_executable, arguments, **_kwargs):
            arguments = tuple(str(item) for item in arguments)
            output = Path(arguments[arguments.index("--output") + 1])
            output.write_bytes(b"GCDE\x01\x00\x00\x00binary")
            return ProcessOutcome(
                command=(str(self.executable), *arguments),
                return_code=0,
                stdout="",
                stderr="",
                duration_s=0.01,
            )

        adapter = PrusaSlicerAdapter(runner=Mock(run=run))
        result = adapter.slice_model(
            SliceRequest(
                model_path=model,
                profile=effective,
                output_directory=self.root / "binary-result",
            )
        )
        self.assertFalse(result.success)
        self.assertIsNone(result.gcode_path)
        self.assertIn("binären G-Code", result.failure_reason or "")
        self.assertTrue(all(path.is_file() for path in paths.values()))


@unittest.skipUnless(
    os.environ.get("COOLING_TOWER_RUN_INSTALLED_PRUSA_INTEGRATION_TEST") == "1",
    "Prusa's real read-only inventory and isolated CLI slice are opt-in.",
)
class InstalledPrusaIntegrationTests(unittest.TestCase):
    def test_real_prusa_confirmation_preslice_and_calibration_preserve_slicer_files(
        self,
    ) -> None:
        from cooling_tower.services import (
            GCodeAnalysisService,
            SourcePreSliceService,
            StlValidationService,
        )
        from cooling_tower.calibration import CalibrationService
        from cooling_tower.manual.geometry import ManualSettings, initial_draft
        from cooling_tower.manual.service import ManualGenerationService, ManualRequest
        from cooling_tower.models import CalibrationConfig, GenerationSettings
        from cooling_tower.preview import OutputMode, PreviewService
        from cooling_tower.slicers import (
            ProfileCatalogConfirmation,
            ProfileConfirmation,
            ProfileMappingStore,
            ProfileMatchingContext,
            ProfileSelectionReference,
            SecureSlicerProcessRunner,
        )
        from cooling_tower.slicers.prusa_profile_catalog import PrusaProfileCatalog

        executable = Path(
            r"C:\Program Files\Prusa3D\PrusaSlicer\prusa-slicer.exe"
        )
        self.assertTrue(executable.is_file())
        adapter = PrusaSlicerAdapter(runner=SecureSlicerProcessRunner())
        installation = adapter.verify_installation(executable)
        build_root = PROJECT_ROOT / "build"
        build_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=build_root) as temporary:
            root = Path(temporary)
            adapter._profile_catalog = PrusaProfileCatalog()
            inventory = adapter.discover_profiles(installation)
            user_records = [item for item in inventory if item.source == "user"]
            names = {item.name for item in user_records}
            self.assertIn(
                "Original Prusa MK4S HF0.4 nozzle - Eigenes Maschinenprofil",
                names,
            )
            self.assertIn("Eigenes Prozessprofil 1", names)
            self.assertIn("Eigenes Filament 2", names)
            selected = {item.name: item for item in user_records}
            selected_records = {
                "machine": selected[
                    "Original Prusa MK4S HF0.4 nozzle - Eigenes Maschinenprofil"
                ],
                "process": selected["Eigenes Prozessprofil 1"],
                "filament": selected["Eigenes Filament 2"],
            }
            references = {
                role: ProfileSelectionReference(record.profile_id, record.path)
                for role, record in selected_records.items()
            }
            original_paths = {executable}
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
                    self.assertIn(f"; {key} = {expected}", source_text)
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
                self.assertEqual(calibration_overrides["fill_density"], "100%")
                self.assertEqual(
                    calibration_overrides["fill_pattern"], "rectilinear"
                )
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
                self.assertIn("; fill_density = 100%", calibration_text)
                self.assertIn("; fill_pattern = rectilinear", calibration_text)

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
                    automatic_result.success,
                    (
                        automatic_result.state,
                        automatic_result.failures,
                        automatic_result.warnings,
                    ),
                )
                self.assertTrue(automatic_result.iterations)
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
                self.assertFalse(manual_result.joint_sliced)
                self.assertTrue(manual_result.artifact_path.is_file())
                self.assertTrue(manual_result.manual_evaluation.layer_times)
                manual_gcode = manual_result.manual_evaluation.gcode_path.read_bytes()
                self.assertNotEqual(manual_gcode[:4], b"GCDE")
                manual_text = manual_gcode.decode("utf-8", errors="replace")
                self.assertIn("; fill_density = 100%", manual_text)
                self.assertIn("; fill_pattern = rectilinear", manual_text)
            finally:
                if manual_result is not None:
                    manual_result.dispose()
                if preslice_result is not None:
                    preslice_result.cleanup()
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
