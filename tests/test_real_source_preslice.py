from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
import struct
import sys
import tempfile
from threading import Event
import unittest

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cooling_tower.calibration import CalibrationService
from cooling_tower.models import CalibrationConfig, GenerationSettings, SlicerFamily
from cooling_tower.models.gcode_metadata import SlicerIdentity
from cooling_tower.persistence import PreSliceCache
from cooling_tower.services import (
    GCodeAnalysisService,
    SourcePreSliceCancelled,
    SourcePreSliceError,
    SourcePreSliceService,
    StlValidationService,
)
from cooling_tower.slicers import (
    AnycubicSlicerNextAdapter,
    ProfileBundleMatch,
    ProfileCandidate,
    ProfileConfirmation,
    ProfileInventoryService,
    ProfileKind,
    ProfileMatchingContext,
    ProfileMatchingService,
    ProfileMappingStore,
    ProfileMatchResult,
    ProfileMatchState,
    ProfileRecord,
    ProfileValidationState,
    SliceRequest,
    SlicerCandidate,
    SlicerDiscoverySource,
    protect_profile_sources,
)
from cooling_tower.slicers.profile_models import stable_json_fingerprint


REAL_TESTS_ENABLED = os.environ.get("COOLING_TOWER_RUN_REAL_SLICER_TESTS") == "1"


class CountingAdapter:
    def __init__(self, adapter) -> None:
        self.adapter = adapter
        self.adapter_id = adapter.adapter_id
        self.calls = 0

    def slice_model(self, request):
        self.calls += 1
        return self.adapter.slice_model(request)


@unittest.skipUnless(REAL_TESTS_ENABLED, "Real slicer integration is opt-in.")
class RealSourcePreSliceAnycubicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.executable = Path(
            r"C:\Program Files\AnycubicSlicerNext\AnycubicSlicerNext.exe"
        )
        cls.profile_root = (
            cls.executable.parent / "resources" / "profiles" / "Anycubic"
        )
        cls.machine_path = (
            cls.profile_root
            / "machine"
            / "Anycubic Kobra 3 V2 0.4 nozzle.json"
        )
        cls.process_path = (
            cls.profile_root
            / "process"
            / "0.20mm Standard @Anycubic Kobra 3 V2 0.4 nozzle.json"
        )
        cls.filament_path = (
            cls.profile_root
            / "filament"
            / "Anycubic PLA @Anycubic Kobra 3 V2 0.4 nozzle.json"
        )
    @staticmethod
    def _hash(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _write_known_valid_cube(path: Path) -> None:
        vertices = np.asarray(
            (
                (-1, -1, -1), (-1, -1, 1), (-1, 1, -1), (-1, 1, 1),
                (1, -1, -1), (1, -1, 1), (1, 1, -1), (1, 1, 1),
            ),
            dtype=np.float32,
        )
        faces = np.asarray(
            (
                (1, 3, 0), (4, 1, 0), (0, 3, 2), (2, 4, 0),
                (1, 7, 3), (5, 1, 4), (5, 7, 1), (3, 7, 2),
                (6, 4, 2), (2, 7, 6), (6, 5, 4), (7, 5, 6),
            ),
            dtype=np.int64,
        )
        triangles = vertices[faces]
        with path.open("wb") as handle:
            handle.write(b"known-valid-real-slicer-cube".ljust(80, b"\0"))
            handle.write(struct.pack("<I", len(triangles)))
            for triangle in triangles:
                normal = np.cross(
                    triangle[1] - triangle[0],
                    triangle[2] - triangle[0],
                )
                normal /= np.linalg.norm(normal)
                handle.write(struct.pack("<3f", *normal))
                handle.write(struct.pack("<9f", *triangle.reshape(-1)))
                handle.write(struct.pack("<H", 0))

    def _context(self):
        for path in (
            self.executable,
            self.machine_path,
            self.process_path,
            self.filament_path,
            self.source,
        ):
            self.assertTrue(path.is_file(), path)
        adapter = AnycubicSlicerNextAdapter()
        installation = adapter.verify_installation(
            SlicerCandidate(
                self.executable,
                SlicerDiscoverySource.KNOWN_PATH,
                adapter_hint=adapter.adapter_id,
            )
        )

        def record(path: Path, kind: ProfileKind) -> ProfileRecord:
            return ProfileRecord(
                adapter_id=adapter.adapter_id,
                profile_id=path.stem,
                name=path.stem,
                kind=kind,
                path=path,
                source="system",
            )

        effective = adapter.resolve_profile_bundle(
            ProfileCandidate(
                installation=installation,
                machine=record(self.machine_path, ProfileKind.MACHINE),
                process=record(self.process_path, ProfileKind.PROCESS),
                filaments=(record(self.filament_path, ProfileKind.FILAMENT),),
            )
        )
        bundle = ProfileBundleMatch(
            bundle_id="real-anycubic-source-preslice",
            effective_profile=effective,
            resolved_profiles=(),
            evidence=("Realer Anycubic-Referenzlauf",),
            differences=(),
            unknown_keys=(),
            exclusions=(),
            rank=1,
            exact_identifier_count=3,
            critical_match_count=1,
            critical_mismatch_count=0,
            validation_state=ProfileValidationState.STRUCTURALLY_VALID,
        )
        fingerprint = stable_json_fingerprint(effective.effective_values)
        match = ProfileMatchResult(
            state=ProfileMatchState.MATCHED,
            selected=bundle,
            candidates=(bundle,),
            machine_options=(effective.machine,),
            process_options=(effective.process,),
            filament_options=effective.filaments,
            requires_confirmation=False,
            user_confirmed=True,
            can_use_stl_mode=True,
            can_use_gcode_mode=False,
            message="Reale Profile bestätigt",
            source_slicer=SlicerIdentity(family=SlicerFamily.UNKNOWN),
            execution_slicer=installation,
            inventory_fingerprint=stable_json_fingerprint(
                {
                    str(path): self._hash(path)
                    for path in (
                        self.machine_path,
                        self.process_path,
                        self.filament_path,
                    )
                }
            ),
            source_profile_fingerprint=None,
            source_critical_fingerprint=None,
            source_kind=self.validation.source_artifact.source_kind,
            effective_profile_fingerprint=fingerprint,
        )
        confirmation = ProfileConfirmation.from_result(
            match,
            self.validation.source_artifact,
        )
        return adapter, match, confirmation

    def setUp(self) -> None:
        self.source_directory = tempfile.TemporaryDirectory()
        self.source = Path(self.source_directory.name) / "known_valid_cube.stl"
        self._write_known_valid_cube(self.source)
        self.validation = StlValidationService().validate(self.source)
        self.assertTrue(self.validation.valid, self.validation.technical_summary)

    def tearDown(self) -> None:
        self.source_directory.cleanup()

    def test_real_preslice_matches_controlled_run_and_preserves_all_sources(self) -> None:
        adapter, match, confirmation = self._context()
        original_hash = self._hash(self.source)
        profile_states = {
            path: (self._hash(path), path.stat().st_mtime_ns)
            for path in (
                self.machine_path,
                self.process_path,
                self.filament_path,
            )
        }
        profile_tree_before = {
            str(path.relative_to(self.profile_root)): (
                path.stat().st_size,
                path.stat().st_mtime_ns,
            )
            for path in self.profile_root.rglob("*")
            if path.is_file()
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            counting = CountingAdapter(adapter)
            service = SourcePreSliceService(
                analysis_service=GCodeAnalysisService(),
                workspace_parent=root / "app" / "temporary",
                diagnostics_root=root / "app" / "diagnostics",
                cache=PreSliceCache(root / "app" / "cache"),
                timeout_s=240,
            )
            try:
                result = service.run(
                    stl_validation=self.validation,
                    profile_match=match,
                    confirmation=confirmation,
                    adapter=counting,
                )
            except SourcePreSliceError as error:
                self.fail(
                    f"{error}\n{getattr(error, 'technical_details', '')}"
                )
            try:
                self.assertFalse(result.cache_hit)
                self.assertEqual(counting.calls, 1)
                self.assertGreater(result.analysis_snapshot.layer_count, 0)
                self.assertTrue(result.prepared_source.matches_analysis_gcode())
                self.assertTrue(
                    result.prepared_source.analysis_gcode_path.is_relative_to(
                        result.workspace_root
                    )
                )

                with protect_profile_sources(match.selected.effective_profile):
                    reference = adapter.slice_model(
                        SliceRequest(
                            model_path=self.source,
                            profile=match.selected.effective_profile,
                            output_directory=root / "controlled" / "output",
                            diagnostics_root=root / "controlled" / "diagnostics",
                            timeout_s=240,
                            purpose="source_preslice_reference",
                        )
                    )
                self.assertTrue(reference.success, reference.failure_reason)
                reference_snapshot = GCodeAnalysisService().analyze(
                    reference.gcode_path,
                    force=True,
                )
                self.assertEqual(
                    result.analysis_snapshot.layer_count,
                    reference_snapshot.layer_count,
                )
                self.assertTrue(
                    math.isclose(
                        result.analysis_snapshot.maximum_print_z_mm,
                        reference_snapshot.maximum_print_z_mm,
                        abs_tol=1e-6,
                    )
                )
            finally:
                first_workspace = result.workspace_root
                result.cleanup()
                self.assertFalse(first_workspace.exists())

            cached = service.run(
                stl_validation=self.validation,
                profile_match=match,
                confirmation=confirmation,
                adapter=counting,
            )
            try:
                self.assertTrue(cached.cache_hit)
                self.assertEqual(counting.calls, 1)
            finally:
                cached_workspace = cached.workspace_root
                cached.cleanup()
                self.assertFalse(cached_workspace.exists())

        self.assertEqual(self._hash(self.source), original_hash)
        self.assertEqual(
            {
                path: (self._hash(path), path.stat().st_mtime_ns)
                for path in profile_states
            },
            profile_states,
        )
        profile_tree_after = {
            str(path.relative_to(self.profile_root)): (
                path.stat().st_size,
                path.stat().st_mtime_ns,
            )
            for path in self.profile_root.rglob("*")
            if path.is_file()
        }
        self.assertEqual(profile_tree_after, profile_tree_before)

    def test_real_cli_slices_supplied_manifold_stl_with_gui_user_presets(self) -> None:
        appdata = Path(os.environ["APPDATA"])
        user_roots = tuple(
            (appdata / "AnycubicSlicerNext" / "user").glob("*")
        )
        relative_paths = (
            Path("machine")
            / "Anycubic Kobra 3 V2 0.4 nozzle - (Settings v2).json",
            Path("process") / "PLA - Tecbears - Schwarz (matt).json",
            Path("filament") / "PLA - Tecbears - Schwarz (matt).json",
        )
        profile_paths = next(
            (
                tuple(root / relative for relative in relative_paths)
                for root in user_roots
                if all((root / relative).is_file() for relative in relative_paths)
            ),
            None,
        )
        if profile_paths is None:
            self.skipTest("Die referenzierten Anycubic-Benutzerprofile fehlen.")

        adapter = AnycubicSlicerNextAdapter()
        installation = adapter.verify_installation(
            SlicerCandidate(
                self.executable,
                SlicerDiscoverySource.KNOWN_PATH,
                adapter_hint=adapter.adapter_id,
            )
        )
        model = (
            PROJECT_ROOT
            / "tests"
            / "fixtures"
            / "stl"
            / "test_model_manifold.stl"
        )
        validation = StlValidationService().validate(model)
        self.assertTrue(validation.valid, validation.technical_summary)
        source_hash = self._hash(model)
        profile_hashes = {
            path: self._hash(path)
            for path in profile_paths
        }

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            matching = ProfileMatchingService(
                inventory_service=ProfileInventoryService(
                    root / "profile_inventory.json"
                ),
                mapping_store=ProfileMappingStore(
                    root / "profile_mappings.json"
                ),
            )
            match = matching.match(
                ProfileMatchingContext.from_stl(validation.source_artifact),
                installation,
                adapter,
                selected_profile_ids={
                    "machine": str(profile_paths[0]),
                    "process": str(profile_paths[1]),
                    "filament": str(profile_paths[2]),
                },
                force_inventory=True,
                include_all_profiles=True,
            )
            self.assertIsNotNone(match.selected)
            assert match.selected is not None
            self.assertEqual(match.selected.machine.path, profile_paths[0].resolve())
            self.assertEqual(match.selected.process.path, profile_paths[1].resolve())
            self.assertEqual(match.selected.filament.path, profile_paths[2].resolve())
            confirmation = ProfileConfirmation.from_result(
                match,
                validation.source_artifact,
            )
            confirmed = matching.confirm(match)
            service = SourcePreSliceService(
                analysis_service=GCodeAnalysisService(),
                workspace_parent=root / "application" / "temporary",
                diagnostics_root=root / "application" / "diagnostics",
                timeout_s=240,
            )
            result = service.run(
                stl_validation=validation,
                profile_match=confirmed,
                confirmation=confirmation,
                adapter=adapter,
            )
            try:
                self.assertIsNotNone(result.slice_result.gcode_path)
                assert result.slice_result.gcode_path is not None
                self.assertGreater(result.slice_result.gcode_path.stat().st_size, 1000)
                self.assertGreater(result.analysis_snapshot.layer_count, 0)
                self.assertTrue(result.metadata_verified)
                command = result.slice_result.command
                settings_value = command[command.index("--load-settings") + 1]
                filament_value = command[command.index("--load-filaments") + 1]
                copied_profiles = tuple(
                    Path(value)
                    for value in (
                        *settings_value.split(";"),
                        *filament_value.split(";"),
                    )
                )
                self.assertTrue(
                    all("effective_profiles" in path.parts for path in copied_profiles)
                )
                self.assertTrue(all(not path.exists() for path in copied_profiles))
                self.assertFalse(
                    any(str(path) in command for path in profile_paths)
                )
            finally:
                result.cleanup()

        self.assertEqual(self._hash(model), source_hash)
        self.assertEqual(
            {path: self._hash(path) for path in profile_paths},
            profile_hashes,
        )

    def test_real_preslice_process_can_be_cancelled_without_partial_result(self) -> None:
        adapter, match, confirmation = self._context()
        cancellation = Event()
        original_hash = self._hash(self.source)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = SourcePreSliceService(
                workspace_parent=root / "app" / "temporary",
                diagnostics_root=root / "app" / "diagnostics",
                timeout_s=240,
            )

            def cancel_when_slicing(_percent: int, _status: str, busy: bool) -> None:
                if busy:
                    cancellation.set()

            with self.assertRaises(SourcePreSliceCancelled):
                service.run(
                    stl_validation=self.validation,
                    profile_match=match,
                    confirmation=confirmation,
                    adapter=adapter,
                    cancellation_event=cancellation,
                    progress_callback=cancel_when_slicing,
                )
            self.assertEqual(
                tuple((root / "app" / "temporary").glob(
                    "cooling_tower_source_preslice_*"
                )),
                (),
            )
        self.assertEqual(self._hash(self.source), original_hash)

    def test_real_full_joint_calibration_reaches_target_with_gui_user_presets(
        self,
    ) -> None:
        """Regress the complete Anycubic scenario reported from the GUI."""

        appdata = Path(os.environ["APPDATA"])
        relative_paths = (
            Path("machine")
            / "Anycubic Kobra 3 V2 0.4 nozzle - (Settings v2).json",
            Path("process") / "PLA - Tecbears - Schwarz (matt).json",
            Path("filament") / "PLA - Tecbears - Schwarz (matt).json",
        )
        profile_paths = next(
            (
                tuple(root / relative for relative in relative_paths)
                for root in (appdata / "AnycubicSlicerNext" / "user").glob("*")
                if all((root / relative).is_file() for relative in relative_paths)
            ),
            None,
        )
        if profile_paths is None:
            self.skipTest("Die referenzierten Anycubic-Benutzerprofile fehlen.")

        adapter = AnycubicSlicerNextAdapter()
        installation = adapter.verify_installation(
            SlicerCandidate(
                self.executable,
                SlicerDiscoverySource.KNOWN_PATH,
                adapter_hint=adapter.adapter_id,
            )
        )
        source = PROJECT_ROOT / "input" / "Test-STL (manifold).stl"
        validation = StlValidationService().validate(source)
        self.assertTrue(validation.valid, validation.technical_summary)
        source_hash = self._hash(source)
        profile_hashes = {path: self._hash(path) for path in profile_paths}

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            matching = ProfileMatchingService(
                inventory_service=ProfileInventoryService(
                    root / "profile_inventory.json"
                ),
                mapping_store=ProfileMappingStore(root / "profile_mappings.json"),
            )
            match = matching.match(
                ProfileMatchingContext.from_stl(validation.source_artifact),
                installation,
                adapter,
                selected_profile_ids={
                    "machine": str(profile_paths[0]),
                    "process": str(profile_paths[1]),
                    "filament": str(profile_paths[2]),
                },
                force_inventory=True,
                include_all_profiles=True,
            )
            self.assertIsNotNone(match.selected, match.message)
            confirmation = ProfileConfirmation.from_result(
                match,
                validation.source_artifact,
            )
            confirmed = matching.confirm(match)
            assert confirmed.selected is not None
            preslice = SourcePreSliceService(
                analysis_service=GCodeAnalysisService(),
                workspace_parent=root / "application" / "temporary",
                diagnostics_root=root / "application" / "diagnostics",
                timeout_s=300.0,
            ).run(
                stl_validation=validation,
                profile_match=confirmed,
                confirmation=confirmation,
                adapter=adapter,
            )
            try:
                result = CalibrationService().calibrate(
                    preslice.analysis_snapshot,
                    GenerationSettings(
                        target_layer_time_s=10.0,
                        safety_factor=1.0,
                        minimum_outer_diameter_mm=3.0,
                        maximum_outer_diameter_mm=40.0,
                        minimum_object_tower_distance_mm=0.5,
                        simulate_full_tower_infill=True,
                        base_height_mm=1.0,
                        automatic_base_width=True,
                        maximum_expansion_angle_deg=50.0,
                        maximum_contraction_angle_deg=50.0,
                        mesh_segments=32,
                    ),
                    adapter=adapter,
                    profile=confirmed.selected.effective_profile,
                    output_directory=root / "calibration",
                    config=CalibrationConfig(
                        maximum_iterations=12,
                        maximum_runtime_s=1200.0,
                        time_tolerance_s=0.2,
                        timeout_per_slice_s=300.0,
                        object_clearance_mm=0.5,
                        maximum_joint_slices=6,
                        minimum_joint_slices=2,
                    ),
                    source_artifact=validation.source_artifact,
                    progress_callback=(
                        lambda percent, status: print(
                            f"real-anycubic {percent:3d}% {status}"
                        )
                    ),
                )
            finally:
                preslice.cleanup()

            joint_iterations = tuple(
                item for item in result.iterations if item.joint_slice
            )
            joint_minima = tuple(
                min(item.evaluation.combined_time_by_layer.values())
                for item in joint_iterations
                if item.evaluation.combined_time_by_layer
            )
            print(
                "real-anycubic joint minima:",
                ", ".join(f"{value:.3f}" for value in joint_minima),
                "best:",
                result.best_iteration_number,
                "state:",
                result.state.value,
            )
            self.assertTrue(joint_iterations, result.failures)
            self.assertTrue(result.success, (result.failures, joint_minima))
            self.assertIsNotNone(result.project_path)
            assert result.project_path is not None
            self.assertTrue(result.project_path.is_file())
            best_joint_iteration = next(
                item for item in joint_iterations
                if item.number == result.best_iteration_number
            )
            best_minimum = min(
                best_joint_iteration.evaluation.combined_time_by_layer.values()
            )
            self.assertLessEqual(abs(best_minimum - 10.0), 0.2)

        self.assertEqual(self._hash(source), source_hash)
        self.assertEqual(
            {path: self._hash(path) for path in profile_paths},
            profile_hashes,
        )


if __name__ == "__main__":
    unittest.main()
