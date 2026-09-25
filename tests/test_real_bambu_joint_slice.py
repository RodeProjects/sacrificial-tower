from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import trimesh


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cooling_tower.calibration import (
    CalibrationService,
    build_calibration_profile,
    determine_occupied_bounds,
    parse_bed_geometry,
    propose_tower_placement,
)
from cooling_tower.models import (
    BedBounds,
    CalibrationConfig,
    GenerationSettings,
    OccupiedBounds,
    TowerPlacement,
)
from cooling_tower.calibration.joint_project import (
    build_joint_project,
    validate_tower_infill_adoption,
)
from cooling_tower.services import GCodeAnalysisService
from cooling_tower.services.source_preslice import SourcePreSliceService
from cooling_tower.services.stl_validation import StlValidationService
from cooling_tower.slicers import (
    BambuStudioAdapter,
    ProfileConfirmation,
    ProfileInventoryService,
    ProfileMappingStore,
    ProfileMatchingContext,
    ProfileMatchingService,
    ProfileRole,
    SliceRequest,
    SlicerCandidate,
    SlicerDiscoverySource,
    protect_profile_sources,
)


@unittest.skipUnless(
    os.environ.get("COOLING_TOWER_RUN_REAL_SLICER_TESTS") == "1",
    "Real slicer integration is opt-in.",
)
class RealBambuJointSliceTests(unittest.TestCase):
    def test_joint_slice_preserves_slowdowns_and_profile_sources(self) -> None:
        executable = Path(
            r"C:\Program Files\Bambu Studio\bambu-studio.exe"
        )
        source = PROJECT_ROOT / "input" / "Test-STL (manifold).stl"
        self.assertTrue(executable.is_file(), executable)
        self.assertTrue(source.is_file(), source)

        adapter = BambuStudioAdapter()
        installation = adapter.verify_installation(
            SlicerCandidate(
                executable,
                SlicerDiscoverySource.KNOWN_PATH,
                adapter_hint=adapter.adapter_id,
            )
        )
        validation = StlValidationService().validate(source)
        self.assertTrue(validation.valid, validation.technical_summary)

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
                force_inventory=True,
            )
            self.assertIsNotNone(match.selected, match.message)
            confirmation = ProfileConfirmation.from_result(
                match,
                validation.source_artifact,
            )
            confirmed = matching.confirm(match)
            assert confirmed.selected is not None
            selected = confirmed.selected
            profile = selected.effective_profile
            self.assertIsNotNone(selected.filament)
            assert selected.filament is not None
            filament_values = next(
                item.effective_values
                for item in selected.resolved_profiles
                if item.role is ProfileRole.FILAMENT
                and item.record.path == selected.filament.path
            )
            source_paths = profile.source_paths
            source_hashes = {
                path: hashlib.sha256(path.read_bytes()).digest()
                for path in source_paths
            }
            source_hash = hashlib.sha256(source.read_bytes()).digest()

            preslice = SourcePreSliceService(
                analysis_service=GCodeAnalysisService(),
                workspace_parent=root / "preslice_workspaces",
                diagnostics_root=root / "preslice_diagnostics",
                timeout_s=300.0,
            ).run(
                stl_validation=validation,
                profile_match=confirmed,
                confirmation=confirmation,
                adapter=adapter,
            )
            try:
                self.assertEqual(
                    preslice.slice_result.command.count("--load-filaments"),
                    1,
                )
                occupied = determine_occupied_bounds(
                    preslice.prepared_source.analysis_gcode_path
                )
            finally:
                preslice.cleanup()

            geometry = parse_bed_geometry(profile.effective_values)
            self.assertIsNotNone(geometry)
            assert geometry is not None
            placement = propose_tower_placement(
                geometry.bounds,
                occupied,
                tower_radius_mm=5.0,
                object_clearance_mm=25.0,
                edge_clearance_mm=3.0,
                bed_geometry=geometry,
            )
            tower = root / "cooling_tower.stl"
            trimesh.creation.cylinder(
                radius=5.0,
                height=10.0,
                sections=32,
            ).export(tower)
            joint_profile, joint_overrides = build_calibration_profile(
                profile,
                root / "joint_profile",
                simulate_full_tower_infill=False,
                resolved_profiles=selected.resolved_profiles,
            )
            self.assertEqual(joint_overrides, {})
            self.assertEqual(
                _cooling_values(joint_profile.effective_values),
                _cooling_values(profile.effective_values),
            )

            project = root / "object_with_cooling_tower.3mf"
            project_request = SliceRequest(
                model_path=source,
                profile=joint_profile,
                output_directory=root / "project_export",
                diagnostics_root=root / "project_diagnostics",
                timeout_s=300.0,
                temporary_overrides=joint_overrides,
                purpose="calibration",
            )
            with protect_profile_sources(profile):
                project_result = adapter.create_joint_project(
                    project_request,
                    source,
                    tower,
                    project,
                    occupied=occupied,
                    placement=placement,
                    tower_full_infill=True,
                )
                self.assertIsNotNone(project_result.slice_input_path)
                slice_result = adapter.slice_model(
                    SliceRequest(
                        model_path=project_result.slice_input_path,
                        profile=joint_profile,
                        output_directory=root / "joint_slice",
                        diagnostics_root=root / "joint_diagnostics",
                        timeout_s=300.0,
                        temporary_overrides=joint_overrides,
                        preserve_model_positions=True,
                        use_cli_assemble_list=True,
                        purpose="calibration",
                    )
                )
            self.assertTrue(
                slice_result.success,
                (
                    slice_result.failure_reason,
                    slice_result.stdout,
                    slice_result.stderr,
                    slice_result.command,
                ),
            )
            self.assertIsNotNone(slice_result.gcode_path)
            assert slice_result.gcode_path is not None
            validate_tower_infill_adoption(
                slice_result.gcode_path,
                tower_center_xy_mm=(
                    placement.center_x_mm,
                    placement.center_y_mm,
                ),
            )
            project_values = _project_settings(project)
            self.assertEqual(
                _normalise_setting(
                    project_values.get("long_retractions_when_ec")
                ),
                _normalise_setting(
                    filament_values.get("long_retractions_when_ec")
                ),
            )
            control_project = root / "control" / "object_with_cooling_tower.3mf"
            control_project.parent.mkdir()
            with protect_profile_sources(profile):
                # Build the native control with the same self-contained
                # temporary profile as the real calibration. Calling the
                # Orca-family implementation deliberately omits only Bambu's
                # post-export filament synchronization, which is the behaviour
                # this control is intended to isolate.
                super(BambuStudioAdapter, adapter).create_joint_project(
                    SliceRequest(
                        model_path=source,
                        profile=joint_profile,
                        output_directory=root / "control" / "project_export",
                        diagnostics_root=root / "control" / "diagnostics",
                        timeout_s=300.0,
                        purpose="calibration",
                    ),
                    source,
                    tower,
                    control_project,
                    occupied=occupied,
                    placement=placement,
                    tower_full_infill=True,
                )
            control_values = _project_settings(control_project)
            compared_filament_keys = set()
            exported_differences = {}
            control_differences = {}
            for key, expected in filament_values.items():
                if (
                    key in _PROFILE_METADATA_KEYS
                    or key not in project_values
                    or key not in control_values
                ):
                    continue
                compared_filament_keys.add(key)
                expected_value = _normalise_setting(expected)
                exported_value = _normalise_setting(project_values[key])
                control_value = _normalise_setting(control_values[key])
                if exported_value != expected_value:
                    exported_differences[key] = {
                        "expected": expected_value,
                        "exported": exported_value,
                    }
                if control_value != expected_value:
                    control_differences[key] = {
                        "expected": expected_value,
                        "control": control_value,
                    }
            self.assertGreater(len(compared_filament_keys), 20)
            unexpected_exported_differences = {
                key: difference
                for key, difference in exported_differences.items()
                if _normalise_setting(project_values[key])
                != _normalise_setting(control_values[key])
            }
            self.assertEqual(
                unexpected_exported_differences,
                {},
                json.dumps(
                    unexpected_exported_differences,
                    ensure_ascii=False,
                    indent=2,
                ),
            )
            self.assertTrue(control_differences)
            self.assertTrue(
                any(
                    _normalise_setting(project_values[key])
                    == _normalise_setting(filament_values[key])
                    for key in control_differences
                    if key in project_values
                )
            )
            for key, expected in _cooling_values(
                profile.effective_values
            ).items():
                self.assertEqual(
                    _normalise_setting(project_values.get(key)),
                    _normalise_setting(expected),
                    key,
                )

            self.assertEqual(
                {
                    path: hashlib.sha256(path.read_bytes()).digest()
                    for path in source_paths
                },
                source_hashes,
            )
            self.assertEqual(
                hashlib.sha256(source.read_bytes()).digest(),
                source_hash,
            )

    def test_real_full_joint_calibration_exports_latest_measured_mesh(
        self,
    ) -> None:
        """Regress the stale-native-project Bambu timing failure end to end."""

        executable = Path(r"C:\Program Files\Bambu Studio\bambu-studio.exe")
        source = PROJECT_ROOT / "input" / "Test-STL (manifold).stl"
        self.assertTrue(executable.is_file(), executable)
        self.assertTrue(source.is_file(), source)
        adapter = BambuStudioAdapter()
        installation = adapter.verify_installation(
            SlicerCandidate(
                executable,
                SlicerDiscoverySource.KNOWN_PATH,
                adapter_hint=adapter.adapter_id,
            )
        )
        validation = StlValidationService().validate(source)
        self.assertTrue(validation.valid, validation.technical_summary)
        source_hash = hashlib.sha256(source.read_bytes()).digest()

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
                force_inventory=True,
            )
            self.assertIsNotNone(match.selected, match.message)
            confirmation = ProfileConfirmation.from_result(
                match,
                validation.source_artifact,
            )
            confirmed = matching.confirm(match)
            assert confirmed.selected is not None
            profile_hashes = {
                path: hashlib.sha256(path.read_bytes()).digest()
                for path in confirmed.selected.effective_profile.source_paths
            }
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
                        minimum_outer_diameter_mm=3.0,
                        maximum_outer_diameter_mm=40.0,
                        minimum_object_tower_distance_mm=0.5,
                        simulate_full_tower_infill=True,
                        base_height_mm=1.0,
                        automatic_base_width=True,
                        maximum_expansion_angle_deg=50.0,
                        maximum_contraction_angle_deg=50.0,
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
                            f"real-bambu {percent:3d}% {status}"
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
                "real-bambu joint minima:",
                ", ".join(f"{value:.3f}" for value in joint_minima),
                "best:",
                result.best_iteration_number,
                "state:",
                result.state.value,
            )
            self.assertTrue(joint_iterations, result.failures)
            self.assertTrue(result.has_usable_improvement, result.failures)
            self.assertIsNotNone(result.project_path)
            assert result.project_path is not None
            self.assertTrue(result.project_path.is_file())
            self.assertIsNotNone(result.stl_path)
            assert result.stl_path is not None
            best_iteration = result.best_iteration
            self.assertIsNotNone(best_iteration)
            assert best_iteration is not None
            best_joint_times = best_iteration.evaluation.combined_time_by_layer
            self.assertTrue(best_joint_times)
            predicted_minimum = min(best_joint_times.values())

            # The Bambu CLI cannot reliably re-slice its finalized 3MF in
            # headless mode, so verify the durable artifact at the mesh level.
            # Before the regression fix this project embedded round one's
            # roughly seven-second tower while the sidecar-driven calibration
            # measured a later roughly 9.6-second STL.
            exported_meshes = _embedded_3mf_meshes(result.project_path)
            self.assertTrue(exported_meshes)
            candidate_mesh = trimesh.load(
                result.stl_path,
                file_type="stl",
                force="mesh",
                process=True,
            )
            self.assertIsInstance(candidate_mesh, trimesh.Trimesh)
            matching_meshes = tuple(
                mesh
                for mesh in exported_meshes
                if all(
                    abs(float(actual) - float(expected)) <= 0.01
                    for actual, expected in zip(
                        mesh.extents,
                        candidate_mesh.extents,
                    )
                )
                and abs(abs(float(mesh.volume)) - abs(float(candidate_mesh.volume)))
                <= max(0.1, abs(float(candidate_mesh.volume)) * 0.001)
            )
            print(
                "real-bambu exported mesh matches:",
                len(matching_meshes),
                "predicted minimum:",
                f"{predicted_minimum:.3f}",
            )
            self.assertTrue(matching_meshes)
            self.assertGreater(predicted_minimum, joint_minima[0] + 2.0)
            self.assertEqual(
                {
                    path: hashlib.sha256(path.read_bytes()).digest()
                    for path in profile_hashes
                },
                profile_hashes,
            )

        self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), source_hash)


class Embedded3mfMeshReaderTests(unittest.TestCase):
    def test_reads_meshes_without_optional_trimesh_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.stl"
            tower = root / "tower.stl"
            project = root / "joint.3mf"
            trimesh.creation.box(extents=(10.0, 12.0, 8.0)).export(source)
            trimesh.creation.cylinder(
                radius=4.0,
                height=15.0,
                sections=32,
            ).export(tower)
            build_joint_project(
                source,
                tower,
                project,
                occupied=OccupiedBounds(40.0, 50.0, 40.0, 50.0),
                placement=TowerPlacement(
                    80.0,
                    80.0,
                    4.0,
                    BedBounds(0.0, 200.0, 0.0, 200.0),
                    25.0,
                ),
                tower_full_infill=True,
            )

            meshes = _embedded_3mf_meshes(project)

            self.assertEqual(len(meshes), 2)
            self.assertTrue(
                any(
                    all(
                        abs(float(actual) - float(expected)) <= 0.01
                        for actual, expected in zip(
                            mesh.extents,
                            (8.0, 8.0, 15.0),
                        )
                    )
                    for mesh in meshes
                )
            )


def _cooling_values(values: object) -> dict[str, object]:
    if not isinstance(values, dict):
        values = dict(values)
    return {
        str(key): value
        for key, value in values.items()
        if any(
            marker in str(key).casefold()
            for marker in (
                "slow_down",
                "slowdown",
                "minimum_layer_time",
                "cool_min_layer_time",
                "fan_cooling_layer_time",
            )
        )
    }


_PROFILE_METADATA_KEYS = {
    "name",
    "type",
    "from",
    "inherits",
    "compatible_printers",
    "compatible_printers_condition",
    "version",
}


def _project_settings(project: Path) -> dict[str, object]:
    with zipfile.ZipFile(project) as archive:
        payload = json.loads(
            archive.read("Metadata/project_settings.config").decode("utf-8-sig")
        )
    if not isinstance(payload, dict):
        raise AssertionError("Bambu project settings are not a JSON object")
    return payload


def _normalise_setting(value: object) -> tuple[str, ...]:
    values = value if isinstance(value, (list, tuple)) else (value,)
    normalised = tuple(_normalise_atom(item) for item in values)
    if normalised and len(set(normalised)) == 1:
        return (normalised[0],)
    return normalised


def _normalise_atom(value: object) -> str:
    rendered = str(value).strip().casefold()
    if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", rendered):
        return f"{float(rendered):g}"
    return rendered


def _embedded_3mf_meshes(project: Path) -> tuple[trimesh.Trimesh, ...]:
    """Read embedded 3MF meshes without trimesh's optional networkx loader."""

    namespace = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
    meshes: list[trimesh.Trimesh] = []
    with zipfile.ZipFile(project) as archive:
        model_paths = tuple(
            name
            for name in archive.namelist()
            if name.casefold().endswith(".model")
        )
        for model_path in model_paths:
            root = ElementTree.fromstring(archive.read(model_path))
            for mesh_element in root.findall(".//m:object/m:mesh", namespace):
                vertices_element = mesh_element.find("m:vertices", namespace)
                triangles_element = mesh_element.find("m:triangles", namespace)
                if vertices_element is None or triangles_element is None:
                    continue
                vertices = tuple(
                    (
                        float(vertex.get("x", "nan")),
                        float(vertex.get("y", "nan")),
                        float(vertex.get("z", "nan")),
                    )
                    for vertex in vertices_element.findall("m:vertex", namespace)
                )
                faces = tuple(
                    (
                        int(triangle.get("v1", "-1")),
                        int(triangle.get("v2", "-1")),
                        int(triangle.get("v3", "-1")),
                    )
                    for triangle in triangles_element.findall(
                        "m:triangle",
                        namespace,
                    )
                )
                if vertices and faces:
                    meshes.append(
                        trimesh.Trimesh(
                            vertices=vertices,
                            faces=faces,
                            process=True,
                        )
                    )
    return tuple(meshes)


if __name__ == "__main__":
    unittest.main()
