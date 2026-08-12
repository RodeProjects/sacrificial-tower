from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cooling_tower.calibration.slice_evaluator import build_calibration_profile
from cooling_tower.config import SETTINGS_SCHEMA_VERSION
from cooling_tower.gui.settings_store import UserSettingsStore
from cooling_tower.models import GenerationSettings
from cooling_tower.slicers import (
    EffectiveProfile,
    ProfileKind,
    ProfileRecord,
    SlicerCapability,
    SlicerDiscoverySource,
    SlicerInstallation,
    SlicerSupportLevel,
)
from cooling_tower.tower.mesh_generator import (
    TowerMeshConfig,
    generate_solid_tower_mesh,
    validate_triangle_mesh,
)
from cooling_tower.tower.profile import (
    LayerRadiusRecord,
    TowerProfileConfig,
    TowerRadiusProfile,
)
from cooling_tower.tower.solid_profile import build_solid_tower_profile


def radius_layer(
    *,
    index: int,
    z: float,
    calculated_radius: float,
    radius: float,
) -> LayerRadiusRecord:
    return LayerRadiusRecord(
        layer_index=index,
        z_mm=z,
        height_mm=0.2,
        layer_time_s=1.0,
        target_layer_time_s=10.0,
        time_deficit_s=9.0,
        seconds_per_deposition_mm=0.1,
        time_factor_source="local",
        reference_start_layer=index,
        reference_end_layer=index,
        additional_path_mm=calculated_radius * 6.283185307179586,
        safety_adjusted_path_mm=calculated_radius * 6.283185307179586,
        calculated_radius_mm=calculated_radius,
        radius_mm=radius,
        radius_limit="none",
        estimated_added_time_s=None,
        estimated_combined_layer_time_s=None,
    )


class SolidSettingsMigrationTests(unittest.TestCase):
    def test_public_settings_contain_only_diameter_and_solid_controls(self) -> None:
        settings = GenerationSettings()
        payload = settings.to_dict()
        self.assertEqual(payload["minimum_outer_diameter_mm"], 10.0)
        self.assertEqual(payload["maximum_outer_diameter_mm"], 40.0)
        self.assertFalse(payload["simulate_full_tower_infill"])
        for obsolete in (
            "minimum_outer_radius_mm",
            "maximum_outer_radius_mm",
            "minimum_wall_thickness_mm",
            "maximum_wall_thickness_mm",
            "wall_path_width_mm",
            "minimum_inner_radius_mm",
            "maximum_wall_change_per_mm_z",
        ):
            self.assertNotIn(obsolete, payload)

    def test_schema_5_radius_values_migrate_through_to_current_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            defaults = root / "defaults.json"
            defaults.write_text(
                json.dumps(
                    {
                        "settings_schema_version": SETTINGS_SCHEMA_VERSION,
                        **GenerationSettings().to_dict(),
                    }
                ),
                encoding="utf-8",
            )
            user = root / "user.json"
            user.write_text(
                json.dumps(
                    {
                        "settings_schema_version": 5,
                        "generation": {
                            "minimum_outer_radius_mm": 7.5,
                            "maximum_outer_radius_mm": 22.0,
                            "minimum_wall_thickness_mm": 0.8,
                            "maximum_wall_thickness_mm": 4.2,
                            "wall_path_width_mm": 0.42,
                            "minimum_inner_radius_mm": 2.0,
                            "maximum_wall_change_per_mm_z": 0.42,
                        },
                    }
                ),
                encoding="utf-8",
            )
            store = UserSettingsStore(user, defaults)
            settings, payload = store.load()
            self.assertEqual(settings.minimum_outer_diameter_mm, 15.0)
            self.assertEqual(settings.maximum_outer_diameter_mm, 44.0)
            self.assertEqual(
                payload["settings_schema_version"],
                SETTINGS_SCHEMA_VERSION,
            )
            self.assertEqual(payload["preview_iterations"], 3)
            self.assertIsNotNone(store.last_migration_backup)
            self.assertTrue(store.last_migration_backup.is_file())

    def test_schema_6_quality_preset_migrates_to_explicit_iterations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            defaults = root / "defaults.json"
            defaults.write_text(
                json.dumps(
                    {
                        "settings_schema_version": SETTINGS_SCHEMA_VERSION,
                        **GenerationSettings().to_dict(),
                    }
                ),
                encoding="utf-8",
            )
            user = root / "user.json"
            original = json.dumps(
                {
                    "settings_schema_version": 6,
                    "generation": GenerationSettings().to_dict(),
                    "preview_quality": "exact",
                }
            ).encode("utf-8")
            user.write_bytes(original)

            store = UserSettingsStore(user, defaults)
            _settings, payload = store.load()

            self.assertEqual(
                payload["settings_schema_version"],
                SETTINGS_SCHEMA_VERSION,
            )
            self.assertEqual(payload["preview_iterations"], 5)
            self.assertNotIn("preview_quality", payload)
            self.assertIsNotNone(store.last_migration_backup)
            self.assertEqual(store.last_migration_backup.read_bytes(), original)

    def test_schema_7_pass_count_is_clamped_to_new_eight_pass_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            defaults = root / "defaults.json"
            defaults.write_text(
                json.dumps(
                    {
                        "settings_schema_version": SETTINGS_SCHEMA_VERSION,
                        **GenerationSettings().to_dict(),
                    }
                ),
                encoding="utf-8",
            )
            user = root / "user.json"
            original = json.dumps(
                {
                    "settings_schema_version": 7,
                    "generation": GenerationSettings().to_dict(),
                    "preview_iterations": 12,
                }
            ).encode("utf-8")
            user.write_bytes(original)

            store = UserSettingsStore(user, defaults)
            _settings, payload = store.load()

            self.assertEqual(
                payload["settings_schema_version"],
                SETTINGS_SCHEMA_VERSION,
            )
            self.assertEqual(payload["preview_iterations"], 8)
            self.assertIsNotNone(store.last_migration_backup)
            self.assertEqual(store.last_migration_backup.read_bytes(), original)


class SolidGeometryTests(unittest.TestCase):
    def test_profile_and_mesh_have_no_inner_contour(self) -> None:
        radius_profile = TowerRadiusProfile(
            config=TowerProfileConfig(10.0, 1.0, 5.0, 20.0, 3),
            global_seconds_per_deposition_mm=0.1,
            layers=(
                radius_layer(index=1, z=0.2, calculated_radius=5.0, radius=5.0),
                radius_layer(index=2, z=1.0, calculated_radius=8.0, radius=8.0),
            ),
        )
        settings = GenerationSettings(
            minimum_outer_diameter_mm=10.0,
            maximum_outer_diameter_mm=40.0,
            base_height_mm=0.0,
            mesh_segments=16,
        )
        profile = build_solid_tower_profile(
            radius_profile,
            settings,
            object_height_mm=10.0,
        )
        self.assertTrue(all(layer.inner_radius_mm == 0.0 for layer in profile.layers))
        self.assertTrue(
            all(
                settings.minimum_outer_diameter_mm
                <= layer.outer_diameter_mm
                <= settings.maximum_outer_diameter_mm
                for layer in profile.layers
            )
        )
        mesh = generate_solid_tower_mesh(profile, TowerMeshConfig(16))
        validation = validate_triangle_mesh(mesh)
        self.assertTrue(validation.is_valid)
        self.assertEqual(len(mesh.vertices), len(profile.points) * 16 + 2)

    def test_analytical_limit_does_not_block_infill_aware_test_slice(self) -> None:
        radius_profile = TowerRadiusProfile(
            config=TowerProfileConfig(10.0, 1.0, 5.0, 20.0, 3),
            global_seconds_per_deposition_mm=0.1,
            layers=(
                radius_layer(index=1, z=1.0, calculated_radius=80.0, radius=20.0),
            ),
        )
        profile = build_solid_tower_profile(
            radius_profile,
            GenerationSettings(base_height_mm=0.0),
            object_height_mm=10.0,
        )
        limitations = {
            issue.code: issue for issue in profile.analytical_limitations
        }
        self.assertFalse(profile.feasibility_issues)
        self.assertIn("MAXIMUM_OUTER_DIAMETER_REACHED", limitations)
        self.assertFalse(
            any("WALL" in code or "INNER" in code for code in limitations)
        )
        self.assertEqual(
            limitations[
                "MAXIMUM_OUTER_DIAMETER_REACHED"
            ].related_setting_names,
            ("maximum_outer_diameter_mm",),
        )


class FullInfillProfileTests(unittest.TestCase):
    def _profile(self, root: Path, adapter_id: str) -> EffectiveProfile:
        executable = root / "slicer.exe"
        executable.write_bytes(b"MZ")
        process_path = root / "process.json"
        process_path.write_text(
            json.dumps(
                {
                    "name": "process",
                    "type": "process",
                    "sparse_infill_density": "12%",
                }
            ),
            encoding="utf-8",
        )
        machine_path = root / "machine.json"
        machine_path.write_text(
            json.dumps({"name": "machine", "type": "machine"}),
            encoding="utf-8",
        )
        installation = SlicerInstallation(
            adapter_id=adapter_id,
            product_name="Synthetic",
            version="1",
            executable_path=executable,
            verified=True,
            capabilities=frozenset({SlicerCapability.CLI_SLICE}),
            discovery_source=SlicerDiscoverySource.MANUAL,
            support_level=SlicerSupportLevel.FULL,
        )
        machine = ProfileRecord(
            adapter_id,
            "machine",
            "machine",
            ProfileKind.MACHINE,
            machine_path,
            "system",
        )
        process = ProfileRecord(
            adapter_id,
            "process",
            "process",
            ProfileKind.PROCESS,
            process_path,
            "user",
        )
        return EffectiveProfile(
            installation,
            machine,
            process,
            (),
            effective_values={"sparse_infill_density": "12%"},
        )

    def test_orca_full_infill_uses_only_temporary_profile_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = self._profile(root, "orca_slicer")
            source_before = profile.process.path.read_bytes()
            temporary_profile, overrides = build_calibration_profile(
                profile,
                root / "temporary",
                simulate_full_tower_infill=True,
            )
            self.assertEqual(overrides["sparse_infill_density"], "100%")
            self.assertEqual(profile.process.path.read_bytes(), source_before)
            self.assertNotEqual(temporary_profile.process.path, profile.process.path)
            copied = json.loads(
                temporary_profile.process.path.read_text(encoding="utf-8")
            )
            self.assertEqual(copied["sparse_infill_density"], "100%")

    def test_non_orca_adapters_receive_their_effective_override(self) -> None:
        expected = {
            "prusa_slicer": ("fill_density", "100%"),
            "cura": ("infill_sparse_density", 100),
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = self._profile(root, "orca_slicer")
            for adapter_id, (key, value) in expected.items():
                with self.subTest(adapter_id=adapter_id):
                    installation = replace(
                        base.installation,
                        adapter_id=adapter_id,
                    )
                    profile = replace(base, installation=installation)
                    temporary_profile, overrides = build_calibration_profile(
                        profile,
                        root / adapter_id,
                        simulate_full_tower_infill=True,
                    )
                    self.assertEqual(overrides[key], value)
                    self.assertEqual(temporary_profile.effective_values[key], value)


if __name__ == "__main__":
    unittest.main()
