from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
from threading import Event
import time
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from cooling_tower.gui.main_window import MainWindow
from cooling_tower.gui.background_jobs import JobKind
from cooling_tower.gui.workflow_controller import WorkflowStage
from cooling_tower.models import SourceArtifact, SourceKind, SlicerFamily
from cooling_tower.services import (
    SourcePreSliceError,
    SourcePreSliceService,
    StlValidationService,
)
from cooling_tower.slicers import (
    AnycubicSlicerNextAdapter,
    ProfileConfirmation,
    ProfileInventoryService,
    ProfileMappingStore,
    ProfileMatchState,
    ProfileMatchingContext,
    ProfileMatchingService,
    ProfileSelectionReference,
    SlicerCapability,
    SlicerDiscoveryResult,
    SlicerDiscoverySource,
    SlicerGuiState,
    SlicerInstallation,
    SlicerSupportLevel,
    SliceResult,
)


FULL_CAPABILITIES = frozenset(
    {
        SlicerCapability.PROFILE_INVENTORY,
        SlicerCapability.CLI_SLICE,
        SlicerCapability.OUTPUT_DIRECTORY,
        SlicerCapability.PROCESS_CANCELLATION,
    }
)


class MustNotProbeBeforeConfirmation:
    def __init__(self) -> None:
        self.calls = 0

    def validate(self, *_args, **_kwargs):
        self.calls += 1
        raise AssertionError("STL matching must not execute a probe slice")


class StaticAdapterService:
    def __init__(self, adapter) -> None:
        self.adapter = adapter

    def adapter_for(self, _installation):
        return self.adapter

    def remember_selection(self, _identity_key) -> None:
        return None


class TestAnycubicSlicerNextAdapter(AnycubicSlicerNextAdapter):
    """Inventory-capable adapter with a deterministic in-process slice."""

    __test__ = False

    def __init__(self) -> None:
        super().__init__()
        self.block_until_cancel = False
        self.slice_started = Event()

    def slice_model(self, request):
        self.slice_started.set()
        if self.block_until_cancel:
            deadline = time.monotonic() + 5
            while (
                request.cancellation_event is not None
                and not request.cancellation_event.is_set()
                and time.monotonic() < deadline
            ):
                time.sleep(0.01)
            return SliceResult(
                success=False,
                return_code=None,
                command=("test-anycubic",),
                output_files=(),
                gcode_path=None,
                metadata_paths=(),
                stdout="",
                stderr="",
                duration_s=0.01,
                failure_reason="cancelled",
                cancelled=True,
            )
        output = request.output_directory / "prepared.gcode"
        output.write_text(
            "; deterministic STL GUI test\n"
            "G90\nM83\n"
            "G1 Z0.2 F600\nG1 X10 Y10 E0.4 F900\n"
            "G1 Z0.4 F600\nG1 X11 Y11 E0.4 F900\n",
            encoding="utf-8",
        )
        return SliceResult(
            success=True,
            return_code=0,
            command=("test-anycubic",),
            output_files=(output,),
            gcode_path=output,
            metadata_paths=(),
            stdout="",
            stderr="",
            duration_s=0.01,
        )


class StlProfileMatchingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.slicer_root = self.root / "slicer"
        self.profile_root = self.slicer_root / "profiles"
        self.slicer_root.mkdir()
        self.executable = self.slicer_root / "AnycubicSlicerNext.exe"
        self.executable.write_bytes(b"MZ")
        self.adapter = TestAnycubicSlicerNextAdapter()
        self.installation = SlicerInstallation(
            adapter_id=self.adapter.adapter_id,
            product_name=self.adapter.product_name,
            version="1.4.1.2",
            executable_path=self.executable,
            verified=True,
            capabilities=FULL_CAPABILITIES,
            discovery_source=SlicerDiscoverySource.MANUAL,
            family=SlicerFamily.ORCA_BAMBU_ANYCUBIC,
            support_level=SlicerSupportLevel.FULL,
            profile_roots=(self.profile_root,),
        )
        self._write_profiles()
        fixture = (
            PROJECT_ROOT
            / "tests"
            / "fixtures"
            / "stl"
            / "known_valid_tetrahedron_ascii.stl"
        )
        self.artifact = SourceArtifact.capture(fixture)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write(self, category: str, name: str, payload: dict) -> None:
        directory = self.profile_root / category
        directory.mkdir(parents=True, exist_ok=True)
        data = {"name": name, "type": category, "from": "system", **payload}
        (directory / f"{name}.json").write_text(
            json.dumps(data), encoding="utf-8"
        )

    def _write_profiles(self) -> None:
        self._write(
            "machine",
            "Testdrucker 0.4",
            {
                "printer_settings_id": "Testdrucker 0.4",
                "printer_model": "Testdrucker",
                "printer_technology": "FFF",
                "nozzle_diameter": ["0.4"],
                "printable_height": "250",
            },
        )
        self._write(
            "process",
            "Qualität 0.2",
            {
                "print_settings_id": "Qualität 0.2",
                "layer_height": "0.2",
                "line_width": "0.42",
                "compatible_printers": ["Testdrucker 0.4"],
            },
        )
        self._write(
            "filament",
            "Test PLA",
            {
                "filament_settings_id": "Test PLA",
                "filament_max_volumetric_speed": ["12"],
                "compatible_printers": ["Testdrucker 0.4"],
            },
        )
    def service(self, validator) -> ProfileMatchingService:
        return ProfileMatchingService(
            inventory_service=ProfileInventoryService(
                self.root / "inventory.json"
            ),
            mapping_store=ProfileMappingStore(self.root / "mappings.json"),
            validator=validator,
        )

    def test_stl_inventory_match_uses_no_artificial_gcode_snapshot(self) -> None:
        validator = MustNotProbeBeforeConfirmation()
        context = ProfileMatchingContext.from_stl(self.artifact)
        self.assertIsNone(context.gcode_snapshot)
        result = self.service(validator).match(
            context,
            self.installation,
            self.adapter,
        )
        self.assertEqual(validator.calls, 0)
        self.assertIs(result.source_kind, SourceKind.STL)
        self.assertTrue(result.requires_confirmation)
        self.assertFalse(result.user_confirmed)
        self.assertTrue(result.can_use_stl_mode)
        self.assertFalse(result.can_use_gcode_mode)
        self.assertIsNotNone(result.selected)
        self.assertEqual(result.selected.machine.name, "Testdrucker 0.4")
        self.assertEqual(result.selected.process.name, "Qualität 0.2")
        self.assertEqual(result.selected.filament.name, "Test PLA")
        self.assertTrue(result.effective_profile_fingerprint)
        self.assertEqual(result.source_slicer.family, SlicerFamily.UNKNOWN)

    def test_confirmation_is_bound_to_source_slicer_and_effective_values(self) -> None:
        service = self.service(MustNotProbeBeforeConfirmation())
        result = service.match(
            ProfileMatchingContext.from_stl(self.artifact),
            self.installation,
            self.adapter,
        )
        confirmed = service.confirm(result)
        binding = ProfileConfirmation.from_result(confirmed, self.artifact)
        self.assertTrue(confirmed.user_confirmed)
        self.assertFalse(confirmed.requires_confirmation)
        self.assertTrue(binding.matches_source(self.artifact))
        self.assertEqual(binding.slicer_identity_key, self.installation.identity_key)
        self.assertEqual(binding.machine_profile_id, "Testdrucker 0.4")
        self.assertEqual(binding.process_profile_id, "Qualität 0.2")
        self.assertEqual(binding.filament_profile_ids, ("Test PLA",))
        self.assertEqual(
            binding.effective_profile_fingerprint,
            result.effective_profile_fingerprint,
        )
        self.assertEqual(len(binding.profile_sources_fingerprint), 64)
        identical_copy = self.root / "identical-copy.stl"
        identical_copy.write_bytes(self.artifact.original_path.read_bytes())
        self.assertFalse(
            binding.matches_source(SourceArtifact.capture(identical_copy))
        )

    def test_initial_stl_match_uses_the_same_filtered_profiles_as_selectors(self) -> None:
        (self.slicer_root / "AnycubicSlicerNext.conf").write_text(
            "[presets]\nprinter = Testdrucker 0.4\n",
            encoding="utf-8",
        )
        for index in range(1, 7):
            self._write(
                "machine",
                f"AAA Fremddrucker {index}",
                {
                    "printer_settings_id": f"AAA Fremddrucker {index}",
                    "printer_model": f"Fremddrucker {index}",
                    "printer_technology": "FFF",
                    "nozzle_diameter": ["0.4"],
                    "printable_height": "250",
                },
            )
        for index in (3, 4):
            self._write(
                "process",
                f"AAA Fremdprozess {index}",
                {
                    "print_settings_id": f"AAA Fremdprozess {index}",
                    "layer_height": "0.2",
                    "compatible_printers": [f"AAA Fremddrucker {index}"],
                },
            )
        for index in (5, 6):
            self._write(
                "filament",
                f"AAA Fremdfilament {index}",
                {
                    "filament_settings_id": f"AAA Fremdfilament {index}",
                    "filament_max_volumetric_speed": ["12"],
                    "compatible_printers": [f"AAA Fremddrucker {index}"],
                },
            )

        service = ProfileMatchingService(
            inventory_service=ProfileInventoryService(
                self.root / "filtered-inventory.json"
            ),
            mapping_store=ProfileMappingStore(
                self.root / "filtered-mappings.json"
            ),
            validator=MustNotProbeBeforeConfirmation(),
            maximum_options_per_role=2,
        )
        result = service.match(
            ProfileMatchingContext.from_stl(self.artifact),
            self.installation,
            self.adapter,
        )

        self.assertEqual(result.profile_filter_source, "slicer")
        self.assertIsNot(result.state, ProfileMatchState.UNAVAILABLE)
        self.assertIsNotNone(result.selected)
        assert result.selected is not None
        self.assertEqual(result.selected.machine.name, "Testdrucker 0.4")
        self.assertTrue(result.selected.usable)
        self.assertTrue(result.requires_confirmation)
        self.assertIn(
            result.selected.machine.path,
            {record.path for record in result.machine_options},
        )
        self.assertIn(
            result.selected.process.path,
            {record.path for record in result.process_options},
        )
        self.assertIn(
            result.selected.filament.path,
            {record.path for record in result.filament_options},
        )

        # Bambu Studio shares the Orca-family profile model but has its own
        # adapter/config identity. The matching fix must remain generic and
        # the Anycubic mirror rule must not leak into this adapter.
        (self.slicer_root / "BambuStudio.conf").write_text(
            "[presets]\nprinter = Testdrucker 0.4\n",
            encoding="utf-8",
        )
        bambu_adapter = TestAnycubicSlicerNextAdapter()
        bambu_adapter.adapter_id = "bambu_studio"
        bambu_installation = replace(
            self.installation,
            adapter_id="bambu_studio",
            product_name="Bambu Studio",
        )
        bambu_result = ProfileMatchingService(
            inventory_service=ProfileInventoryService(
                self.root / "bambu-filtered-inventory.json"
            ),
            mapping_store=ProfileMappingStore(
                self.root / "bambu-filtered-mappings.json"
            ),
            validator=MustNotProbeBeforeConfirmation(),
            maximum_options_per_role=2,
        ).match(
            ProfileMatchingContext.from_stl(self.artifact),
            bambu_installation,
            bambu_adapter,
        )
        self.assertEqual(bambu_result.profile_filter_source, "slicer")
        self.assertIsNot(bambu_result.state, ProfileMatchState.UNAVAILABLE)
        self.assertIsNotNone(bambu_result.selected)
        assert bambu_result.selected is not None
        self.assertEqual(
            bambu_result.selected.machine.name,
            "Testdrucker 0.4",
        )

    def test_remembered_profiles_restore_per_role_with_safe_missing_fallback(
        self,
    ) -> None:
        (self.slicer_root / "AnycubicSlicerNext.conf").write_text(
            "[presets]\nprinter = Testdrucker 0.4\n",
            encoding="utf-8",
        )
        self._write(
            "machine",
            "Testdrucker Spezial 0.4",
            {
                "printer_settings_id": "Testdrucker Spezial 0.4",
                "printer_model": "Testdrucker",
                "printer_technology": "FFF",
                "nozzle_diameter": ["0.4"],
                "printable_height": "250",
            },
        )
        self._write(
            "filament",
            "Spezial PLA",
            {
                "filament_settings_id": "Spezial PLA",
                "filament_max_volumetric_speed": ["12"],
                "compatible_printers": ["Testdrucker Spezial 0.4"],
            },
        )
        self._write(
            "process",
            "Fallback Prozess 0.2",
            {
                "print_settings_id": "Fallback Prozess 0.2",
                "layer_height": "0.2",
                "line_width": "0.42",
                "compatible_printers": ["Testdrucker Spezial 0.4"],
            },
        )
        machine_path = (
            self.profile_root / "machine" / "Testdrucker Spezial 0.4.json"
        )
        remembered = {
            "machine": ProfileSelectionReference(
                "Testdrucker Spezial 0.4",
                machine_path,
            ),
            # This preset disappeared. Only this role must fall back to the
            # currently available/default process instead of rejecting all.
            "process": ProfileSelectionReference(
                "Entfernter Prozess",
                self.root / "old" / "Entfernter Prozess.json",
            ),
            # The path moved during a slicer update; the stable ID remains.
            "filament": ProfileSelectionReference(
                "Spezial PLA",
                self.root / "old" / "Spezial PLA.json",
            ),
        }

        result = self.service(MustNotProbeBeforeConfirmation()).match(
            ProfileMatchingContext.from_stl(self.artifact),
            self.installation,
            self.adapter,
            selected_profile_ids=remembered,
            force_inventory=True,
            include_all_profiles=True,
        )

        self.assertIsNot(result.state, ProfileMatchState.UNAVAILABLE)
        self.assertIsNotNone(result.selected)
        assert result.selected is not None
        self.assertEqual(result.selected.machine.name, "Testdrucker Spezial 0.4")
        self.assertEqual(result.selected.filament.name, "Spezial PLA")
        self.assertEqual(result.selected.process.name, "Fallback Prozess 0.2")

        incompatible = self.service(MustNotProbeBeforeConfirmation()).match(
            ProfileMatchingContext.from_stl(self.artifact),
            self.installation,
            self.adapter,
            selected_profile_ids={
                "machine": remembered["machine"],
                "process": ProfileSelectionReference(
                    "QualitÃ¤t 0.2",
                    self.profile_root / "process" / "QualitÃ¤t 0.2.json",
                ),
                "filament": ProfileSelectionReference(
                    "Test PLA",
                    self.profile_root / "filament" / "Test PLA.json",
                ),
            },
            force_inventory=True,
            include_all_profiles=True,
        )
        self.assertIsNot(incompatible.state, ProfileMatchState.UNAVAILABLE)
        self.assertIsNotNone(incompatible.selected)
        assert incompatible.selected is not None
        self.assertEqual(incompatible.selected.machine.name, "Testdrucker 0.4")
        self.assertNotEqual(
            incompatible.selected.process.name,
            "Fallback Prozess 0.2",
        )
        self.assertEqual(incompatible.selected.filament.name, "Test PLA")

    def test_inherited_profile_change_invalidates_confirmation_before_slice(self) -> None:
        base_path = self.profile_root / "machine" / "Basisdrucker.json"
        self._write(
            "machine",
            "Basisdrucker",
            {
                "printer_settings_id": "Basisdrucker",
                "printer_model": "Testdrucker",
                "printer_technology": "FFF",
                "nozzle_diameter": ["0.4"],
                "printable_height": "250",
            },
        )
        machine_path = self.profile_root / "machine" / "Testdrucker 0.4.json"
        machine_payload = json.loads(machine_path.read_text(encoding="utf-8"))
        machine_payload["inherits"] = "Basisdrucker"
        machine_path.write_text(json.dumps(machine_payload), encoding="utf-8")
        process_path = self.profile_root / "process" / "Qualität 0.2.json"
        filament_path = self.profile_root / "filament" / "Test PLA.json"
        matching = self.service(MustNotProbeBeforeConfirmation())
        result = matching.match(
            ProfileMatchingContext.from_stl(self.artifact),
            self.installation,
            self.adapter,
            selected_profile_ids={
                "machine": str(machine_path),
                "process": str(process_path),
                "filament": str(filament_path),
            },
            force_inventory=True,
            include_all_profiles=True,
        )
        self.assertIsNotNone(result.selected)
        assert result.selected is not None
        self.assertIn(base_path.resolve(), result.selected.source_paths)
        confirmation = ProfileConfirmation.from_result(result, self.artifact)
        confirmed = matching.confirm(result)
        validation = StlValidationService().validate(self.artifact.original_path)

        base_payload = json.loads(base_path.read_text(encoding="utf-8"))
        base_payload["printable_height"] = "249"
        base_path.write_text(json.dumps(base_payload), encoding="utf-8")
        self.adapter.slice_started.clear()
        preslice = SourcePreSliceService(
            workspace_parent=self.root / "preslice",
            diagnostics_root=self.root / "diagnostics",
        )
        with self.assertRaisesRegex(SourcePreSliceError, "Profildatei"):
            preslice.run(
                stl_validation=validation,
                profile_match=confirmed,
                confirmation=confirmation,
                adapter=self.adapter,
            )
        self.assertFalse(self.adapter.slice_started.is_set())

    def test_stl_slicer_selector_excludes_detection_only_installations(self) -> None:
        app = QApplication.instance() or QApplication([])
        detection_only = SlicerInstallation(
            adapter_id="detected",
            product_name="Nur erkannt",
            version="1.0",
            executable_path=self.root / "detected.exe",
            verified=True,
            capabilities=frozenset(),
            discovery_source=SlicerDiscoverySource.MANUAL,
            family=SlicerFamily.UNKNOWN,
            support_level=SlicerSupportLevel.DETECTION_ONLY,
        )
        result = SlicerDiscoveryResult(
            installations=(detection_only, self.installation),
            recommended_key=detection_only.identity_key,
            gui_state=SlicerGuiState.AVAILABLE,
            message="Slicer gefunden",
        )
        window = MainWindow(
            user_settings_path=self.root / "gui.json",
            enable_update_check=False,
        )
        try:
            window.current_source_kind = SourceKind.STL
            window._slicer_request_id = 1
            window._on_slicer_discovery_succeeded(1, result)
            self.assertEqual(window.slicer_combo.count(), 1)
            self.assertEqual(
                window.slicer_combo.currentData(),
                self.installation.identity_key,
            )
        finally:
            window.close()
            window.deleteLater()
            app.processEvents()

    def test_gui_blocks_confirmation_if_a_profile_source_disappeared(self) -> None:
        app = QApplication.instance() or QApplication([])
        matching = self.service(MustNotProbeBeforeConfirmation())
        result = matching.match(
            ProfileMatchingContext.from_stl(self.artifact),
            self.installation,
            self.adapter,
        )
        window = MainWindow(
            user_settings_path=self.root / "gui-missing-profile.json",
            profile_service=matching,
            enable_update_check=False,
            enable_startup_slicer_discovery=False,
        )
        try:
            validation = StlValidationService().validate(
                self.artifact.original_path
            )
            window.current_source_path = self.artifact.original_path
            window.current_source_kind = SourceKind.STL
            window.source_artifact = self.artifact
            window.stl_validation_result = validation
            window.profile_match_result = result
            assert result.selected is not None
            assert result.selected.process is not None
            result.selected.process.path.unlink()
            window.confirm_profile_selection()
            self.assertIsNone(window.confirmed_profile_context)
            self.assertIn(
                "Profilzuordnung konnte nicht gespeichert werden",
                window.profile_status_label.text(),
            )
            self.assertFalse((self.root / "mappings.json").exists())
        finally:
            window.close()
            window.deleteLater()
            app.processEvents()

    def test_gui_cancels_preslice_without_accepting_partial_results(self) -> None:
        app = QApplication.instance() or QApplication([])
        self.adapter.block_until_cancel = True
        matching = self.service(MustNotProbeBeforeConfirmation())
        window = MainWindow(
            user_settings_path=self.root / "gui-cancel.json",
            user_data_root=self.root / "appdata-cancel",
            profile_service=matching,
            enable_update_check=False,
            enable_startup_slicer_discovery=False,
        )
        window.slicer_service = StaticAdapterService(self.adapter)
        discovery = SlicerDiscoveryResult(
            installations=(self.installation,),
            recommended_key=self.installation.identity_key,
            gui_state=SlicerGuiState.AVAILABLE_AND_RECOMMENDED,
            message="Slicer gefunden",
        )
        try:
            self.assertTrue(window.drop_zone.set_file(self.artifact.original_path))
            deadline = time.monotonic() + 15
            while window.stl_validation_result is None and time.monotonic() < deadline:
                app.processEvents()
                QTest.qWait(10)
            self.assertIsNotNone(window.stl_validation_result)
            window.preparation_tabs.setCurrentIndex(1)
            window._slicer_request_id += 1
            window._on_slicer_discovery_succeeded(
                window._slicer_request_id,
                discovery,
            )
            deadline = time.monotonic() + 10
            while window.profile_catalog is None and time.monotonic() < deadline:
                app.processEvents()
                QTest.qWait(10)
            self.assertIsNotNone(window.profile_catalog)
            self.assertTrue(window.profile_confirm_button.isEnabled())
            window.confirm_profile_selection()
            deadline = time.monotonic() + 15
            while not self.adapter.slice_started.is_set() and time.monotonic() < deadline:
                app.processEvents()
                QTest.qWait(10)
            self.assertTrue(self.adapter.slice_started.is_set())
            self.assertFalse(window.preslice_cancel_button.isHidden())
            window.cancel_source_preslice()
            deadline = time.monotonic() + 5
            while (
                window.background_job_manager.has_active(JobKind.PRESLICE)
                and time.monotonic() < deadline
            ):
                app.processEvents()
                QTest.qWait(10)
            app.processEvents()
            self.assertFalse(
                window.background_job_manager.has_active(JobKind.PRESLICE)
            )
            self.assertIsNone(window.source_preslice_result)
            self.assertIsNone(window.prepared_analysis_source)
            self.assertIsNone(window.analysis_snapshot)
            self.assertIsNone(window.current_gcode_path)
            self.assertIs(
                window.workflow.stage,
                WorkflowStage.WAITING_FOR_PROFILE_CONFIRMATION,
            )
            self.assertTrue(window.profile_confirm_button.isEnabled())
            workspaces = tuple(
                (self.root / "appdata-cancel" / "temporary").glob(
                    "cooling_tower_source_preslice_*"
                )
            )
            self.assertEqual(workspaces, ())
        finally:
            window.close()
            window.deleteLater()
            app.processEvents()

    def test_gui_requires_explicit_confirmation_and_binds_it_to_stl(self) -> None:
        app = QApplication.instance() or QApplication([])
        matching = self.service(MustNotProbeBeforeConfirmation())
        window = MainWindow(
            user_settings_path=self.root / "gui-confirm.json",
            user_data_root=self.root / "appdata-confirm",
            profile_service=matching,
            enable_update_check=False,
            enable_startup_slicer_discovery=False,
        )
        window.slicer_service = StaticAdapterService(self.adapter)
        discovery = SlicerDiscoveryResult(
            installations=(self.installation,),
            recommended_key=self.installation.identity_key,
            gui_state=SlicerGuiState.AVAILABLE_AND_RECOMMENDED,
            message="Slicer gefunden",
        )
        try:
            self.assertTrue(window.drop_zone.set_file(self.artifact.original_path))
            deadline = time.monotonic() + 10
            while window.stl_validation_result is None and time.monotonic() < deadline:
                app.processEvents()
                QTest.qWait(10)
            self.assertIsNotNone(window.stl_validation_result)
            window.preparation_tabs.setCurrentIndex(1)
            window._slicer_request_id += 1
            window._on_slicer_discovery_succeeded(
                window._slicer_request_id,
                discovery,
            )
            deadline = time.monotonic() + 10
            while window.profile_catalog is None and time.monotonic() < deadline:
                app.processEvents()
                QTest.qWait(10)
            self.assertIsNotNone(window.profile_catalog)
            self.assertIs(
                window.workflow.stage,
                WorkflowStage.WAITING_FOR_PROFILE_CONFIRMATION,
            )
            self.assertTrue(window.profile_confirm_button.isEnabled())
            self.assertEqual(
                window.profile_confirm_button.text(),
                "Slicer und Profile bestätigen",
            )
            source_hash = self.artifact.original_sha256
            profile_hashes = {
                path: path.read_bytes()
                for path in (
                    self.profile_root / "machine" / "Testdrucker 0.4.json",
                    self.profile_root / "process" / "Qualität 0.2.json",
                    self.profile_root / "filament" / "Test PLA.json",
                )
            }
            window.confirm_profile_selection()
            deadline = time.monotonic() + 10
            while (
                window.confirmed_profile_context is None
                and time.monotonic() < deadline
            ):
                app.processEvents()
                QTest.qWait(10)
            self.assertIsNotNone(window.confirmed_profile_context)
            assert window.confirmed_profile_context is not None
            self.assertTrue(
                window.confirmed_profile_context.matches_source(self.artifact)
            )
            self.assertIn(
                "Düse: 0.4 mm",
                window.profile_diagnostics.toPlainText(),
            )
            self.assertIn(
                "Layerhöhe: 0.2 mm",
                window.profile_diagnostics.toPlainText(),
            )
            self.assertTrue(window.profile_effective_summary_label.isHidden())
            deadline = time.monotonic() + 10
            while (
                window.source_preslice_result is None
                and time.monotonic() < deadline
            ):
                app.processEvents()
                QTest.qWait(10)
            self.assertIsNotNone(window.source_preslice_result)
            self.assertIs(window.workflow.stage, WorkflowStage.READY)
            self.assertEqual(
                [
                    selector.progress_value
                    for selector in window.preparation_step_selectors
                ],
                [100, 100],
            )
            self.assertTrue(
                all(
                    icon.text() == "✓"
                    for icon, _label in (
                        window.preparation_requirement_rows.values()
                    )
                )
            )
            self.assertFalse(window.ready_grid.isHidden())
            self.assertTrue(window.workflow_group.isCheckable())
            self.assertFalse(window.workflow_group.isChecked())
            self.assertEqual(window.workflow_group.status_icon.text(), "✓")
            self.assertIsNotNone(window.analysis_snapshot)
            self.assertEqual(window.analysis_snapshot.layer_count, 2)
            self.assertIsNotNone(window.prepared_analysis_source)

            self.adapter.slice_started.clear()
            profile_stage_events: list[str] = []
            window.workflow.stage_changed.connect(profile_stage_events.append)
            window.show_all_profiles_checkbox.setChecked(
                not window.show_all_profiles_checkbox.isChecked()
            )
            deadline = time.monotonic() + 60
            while (
                (
                    window.workflow.stage is WorkflowStage.MATCHING_PROFILES
                    or window.background_job_manager.has_active(
                        JobKind.PROFILE_MATCH
                    )
                )
                and time.monotonic() < deadline
            ):
                app.processEvents()
                QTest.qWait(10)
            app.processEvents()
            self.assertIsNone(window._pending_profile_match)
            self.assertFalse(
                window.background_job_manager.has_active(JobKind.PROFILE_MATCH)
            )
            distinct_profile_stages = [
                stage
                for index, stage in enumerate(profile_stage_events)
                if index == 0 or stage != profile_stage_events[index - 1]
            ]
            self.assertEqual(
                distinct_profile_stages,
                [
                    WorkflowStage.MATCHING_PROFILES.value,
                    WorkflowStage.WAITING_FOR_PROFILE_CONFIRMATION.value,
                ],
            )
            self.assertFalse(self.adapter.slice_started.is_set())
            self.assertIsNone(window.confirmed_profile_context)
            self.assertIsNone(window.source_preslice_result)
            self.assertIs(
                window.workflow.stage,
                WorkflowStage.WAITING_FOR_PROFILE_CONFIRMATION,
            )
            self.assertTrue(window.ready_grid.isHidden())
            self.assertFalse(window.workflow_group.isCheckable())
            self.assertTrue(window.workflow_group.isChecked())
            self.assertTrue(window.profile_confirm_button.isEnabled())
            self.assertEqual(
                window.profile_confirm_button.text(),
                "Slicer und Profile bestätigen",
            )

            window.profile_confirm_button.click()
            app.processEvents()
            self.assertIsNotNone(window.confirmed_profile_context)
            self.assertIsNotNone(window.profile_match_result)
            assert window.profile_match_result is not None
            self.assertTrue(window.profile_match_result.user_confirmed)
            deadline = time.monotonic() + 15
            while (
                window.source_preslice_result is None
                and time.monotonic() < deadline
            ):
                app.processEvents()
                QTest.qWait(10)
            self.assertIsNotNone(window.source_preslice_result)
            self.assertIs(window.workflow.stage, WorkflowStage.READY)
            self.assertFalse(window.ready_grid.isHidden())
            self.assertTrue(window.workflow_group.isCheckable())
            self.assertFalse(window.workflow_group.isChecked())
            self.assertIn(
                "Höhe des automatisch geslicten Modells",
                window.automatic_base_width_label.text(),
            )
            self.assertFalse(window.preslice_cancel_button.isVisible())
            self.assertEqual(
                SourceArtifact.capture(self.artifact.original_path).original_sha256,
                source_hash,
            )
            for path, original in profile_hashes.items():
                self.assertEqual(path.read_bytes(), original)
            support_context = window._support_diagnostic_context()
            rendered_context = json.dumps(support_context, ensure_ascii=False)
            self.assertNotIn(str(self.artifact.original_path), rendered_context)
            self.assertNotIn(self.artifact.original_path.name, rendered_context)
            self.assertEqual(
                support_context["source"]["source_kind"],
                "stl",
            )
            self.assertTrue(
                support_context["source"]["analysis_gcode_available"]
            )
            result = window.source_preslice_result
            assert result is not None
            workspace = result.workspace_root
            self.assertTrue(workspace.is_dir())
            window.remove_source()
            deadline = time.monotonic() + 2
            while workspace.exists() and time.monotonic() < deadline:
                app.processEvents()
                QTest.qWait(10)
            self.assertFalse(workspace.exists())
            self.assertIsNone(window.source_preslice_result)
            self.assertIsNone(window.analysis_snapshot)
            self.assertIsNotNone(window.profile_catalog_confirmation)
            self.assertEqual(
                [
                    selector.progress_value
                    for selector in window.preparation_step_selectors
                ],
                [0, 0],
            )
            self.assertTrue(window.ready_grid.isHidden())
        finally:
            window.close()
            window.deleteLater()
            app.processEvents()


if __name__ == "__main__":
    unittest.main()
