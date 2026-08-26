from __future__ import annotations

import hashlib
import json
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

from cooling_tower.calibration.gcode_integration import (
    parse_bed_geometry,
    propose_tower_placement,
)
from cooling_tower.calibration.joint_project import (
    BAMBU_STUDIO_NAMESPACE,
    MODEL_SETTINGS_PATH,
    TOWER_FULL_INFILL_PATTERN,
    TOWER_INFILL_KEY,
    TOWER_INFILL_PATTERN_KEY,
    build_joint_project,
    finalize_slicer_project,
    JointProjectError,
    synchronize_bambu_project_filament_settings,
    validate_tower_infill_adoption,
    validate_joint_project,
)
from cooling_tower.config import SETTINGS_SCHEMA_VERSION
from cooling_tower.gui.settings_store import UserSettingsStore
from cooling_tower.models import (
    BedBounds,
    GenerationSettings,
    OccupiedBounds,
    TowerPlacement,
)
from cooling_tower.settings_compatibility import (
    SETTING_COMPATIBILITY_CATALOG,
    merge_compatible_setting_changes,
)


class PlacementAndProjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_schema_8_migrates_distance_with_backup_and_catalog(self) -> None:
        defaults = self.root / "defaults.json"
        defaults.write_text(
            json.dumps(
                {
                    "settings_schema_version": SETTINGS_SCHEMA_VERSION,
                    **GenerationSettings().to_dict(),
                }
            ),
            encoding="utf-8",
        )
        user = self.root / "settings.json"
        old_generation = GenerationSettings().to_dict()
        old_generation.pop("minimum_object_tower_distance_mm")
        original = json.dumps(
            {
                "settings_schema_version": 8,
                "generation": old_generation,
                "preview_iterations": 3,
            }
        ).encode("utf-8")
        user.write_bytes(original)

        store = UserSettingsStore(user, defaults)
        settings, payload = store.load()

        self.assertEqual(SETTINGS_SCHEMA_VERSION, 10)
        self.assertEqual(settings.minimum_object_tower_distance_mm, 25.0)
        self.assertEqual(
            payload["generation"]["minimum_object_tower_distance_mm"],
            25.0,
        )
        self.assertEqual(payload["preview_iterations"], 4)
        self.assertEqual(
            payload["setting_compatibility"]
            ["generation.minimum_object_tower_distance_mm"],
            "object-tower-edge-distance-mm-v1",
        )
        self.assertIsNotNone(store.last_migration_backup)
        self.assertEqual(store.last_migration_backup.read_bytes(), original)

    def test_downgrade_merge_rejects_invalid_distance_without_clamping(self) -> None:
        current = {
            "settings_schema_version": SETTINGS_SCHEMA_VERSION,
            "generation": GenerationSettings().to_dict(),
            "setting_compatibility": dict(SETTING_COMPATIBILITY_CATALOG),
        }
        result = merge_compatible_setting_changes(
            current,
            {
                "generation.minimum_object_tower_distance_mm": {
                    "token": "object-tower-edge-distance-mm-v1",
                    "value": -1.0,
                }
            },
        )
        self.assertEqual(result.accepted_ids, ())
        self.assertEqual(result.rejected_ids, (
            "generation.minimum_object_tower_distance_mm",
        ))
        self.assertEqual(
            result.payload["generation"]["minimum_object_tower_distance_mm"],
            25.0,
        )

    def test_exclusion_area_is_parsed_and_avoided(self) -> None:
        geometry = parse_bed_geometry(
            {
                "printable_area": "0x0,100x0,100x100,0x100",
                "bed_exclude_area": "0x0,35x0,35x100,0x100",
            }
        )
        self.assertIsNotNone(geometry)
        self.assertEqual(len(geometry.excluded_polygons), 1)
        placement = propose_tower_placement(
            geometry.bounds,
            OccupiedBounds(45, 70, 40, 60),
            tower_radius_mm=5.0,
            object_clearance_mm=5.0,
            edge_clearance_mm=3.0,
            bed_geometry=geometry,
        )
        self.assertGreaterEqual(placement.center_x_mm, 43.0)

    def test_placement_uses_edge_to_edge_distance(self) -> None:
        occupied = OccupiedBounds(80, 120, 80, 120)
        placement = propose_tower_placement(
            BedBounds(0, 200, 0, 200),
            occupied,
            tower_radius_mm=10.0,
            object_clearance_mm=25.0,
            edge_clearance_mm=3.0,
        )
        closest_x = min(
            max(placement.center_x_mm, occupied.minimum_x_mm),
            occupied.maximum_x_mm,
        )
        closest_y = min(
            max(placement.center_y_mm, occupied.minimum_y_mm),
            occupied.maximum_y_mm,
        )
        center_distance = (
            (placement.center_x_mm - closest_x) ** 2
            + (placement.center_y_mm - closest_y) ** 2
        ) ** 0.5
        self.assertGreaterEqual(center_distance - placement.radius_mm, 25.0)

    def test_joint_project_keeps_sources_and_scopes_full_infill_to_tower(self) -> None:
        source = self.root / "source.stl"
        tower = self.root / "tower.stl"
        trimesh.creation.box(extents=(20, 10, 8)).export(source)
        trimesh.creation.cylinder(radius=5, height=12, sections=16).export(tower)
        before = {
            path: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (source, tower)
        }
        destination = self.root / "joint.3mf"
        placement = TowerPlacement(
            150.0,
            100.0,
            5.0,
            BedBounds(0.0, 200.0, 0.0, 200.0),
            25.0,
        )

        result = build_joint_project(
            source,
            tower,
            destination,
            occupied=OccupiedBounds(80.0, 100.0, 70.0, 80.0),
            placement=placement,
            tower_full_infill=True,
        )

        self.assertEqual(validate_joint_project(destination, tower_full_infill=True), (2, 4))
        self.assertEqual(result.source_object_id, 2)
        self.assertEqual(result.tower_object_id, 4)
        self.assertAlmostEqual(result.tower_translation_mm[0], 150.0)
        self.assertEqual(
            before,
            {
                path: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in (source, tower)
            },
        )
        with zipfile.ZipFile(destination) as archive:
            config = ElementTree.fromstring(archive.read(MODEL_SETTINGS_PATH))
        values = {
            int(str(item.get("id"))): {
                str(meta.get("key")): str(meta.get("value"))
                for meta in item.findall("metadata")
            }
            for item in config.findall("object")
        }
        self.assertNotIn(TOWER_INFILL_KEY, values[2])
        self.assertEqual(values[4][TOWER_INFILL_KEY], "100%")
        self.assertEqual(
            values[4][TOWER_INFILL_PATTERN_KEY],
            TOWER_FULL_INFILL_PATTERN,
        )

    def test_slicer_project_finalization_reassigns_positions_by_role(self) -> None:
        source = self.root / "source.stl"
        tower = self.root / "tower.stl"
        trimesh.creation.box(extents=(10, 10, 5)).export(source)
        trimesh.creation.cylinder(radius=4, height=5, sections=16).export(tower)
        first = self.root / "template.3mf"
        initial = TowerPlacement(
            80.0, 80.0, 4.0, BedBounds(0, 200, 0, 200), 25.0
        )
        build_joint_project(
            source,
            tower,
            first,
            occupied=OccupiedBounds(40, 50, 40, 50),
            placement=initial,
            tower_full_infill=True,
        )
        final = self.root / "final.3mf"
        updated = TowerPlacement(
            150.0, 110.0, 4.0, BedBounds(0, 200, 0, 200), 25.0
        )

        result = finalize_slicer_project(
            first,
            source,
            tower,
            final,
            occupied=OccupiedBounds(90, 100, 70, 80),
            placement=updated,
            tower_full_infill=False,
        )

        self.assertEqual(result.source_object_id, 2)
        self.assertEqual(result.tower_object_id, 4)
        self.assertAlmostEqual(result.tower_translation_mm[0], 150.0)
        self.assertEqual(
            validate_joint_project(final, tower_full_infill=False),
            (2, 4),
        )
        with zipfile.ZipFile(final) as archive:
            config = ElementTree.fromstring(archive.read(MODEL_SETTINGS_PATH))
        tower_values = {
            str(metadata.get("key")): str(metadata.get("value"))
            for item in config.findall("object")
            if int(str(item.get("id"))) == result.tower_object_id
            for metadata in item.findall("metadata")
        }
        self.assertNotIn(TOWER_INFILL_PATTERN_KEY, tower_values)

    def test_slicer_project_finalization_preserves_bambu_namespace(self) -> None:
        source = self.root / "source.stl"
        tower = self.root / "tower.stl"
        trimesh.creation.box(extents=(10, 10, 5)).export(source)
        trimesh.creation.cylinder(radius=4, height=5, sections=16).export(tower)
        template = self.root / "bambu_template.3mf"
        placement = TowerPlacement(
            80.0, 80.0, 4.0, BedBounds(0, 200, 0, 200), 25.0
        )
        build_joint_project(
            source,
            tower,
            template,
            occupied=OccupiedBounds(40, 50, 40, 50),
            placement=placement,
            tower_full_infill=True,
        )
        with zipfile.ZipFile(template, "r") as archive:
            entries = {
                item.filename: (item, archive.read(item.filename))
                for item in archive.infolist()
            }
        model_name = "3D/3dmodel.model"
        item, model_xml = entries[model_name]
        model_xml = model_xml.replace(
            b"<model ",
            (
                b'<model xmlns:BambuStudio="'
                + BAMBU_STUDIO_NAMESPACE.encode("ascii")
                + b'" '
            ),
            1,
        )
        entries[model_name] = (item, model_xml)
        with zipfile.ZipFile(template, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, (entry, data) in entries.items():
                archive.writestr(entry, data)

        finalized = self.root / "bambu_finalized.3mf"
        finalize_slicer_project(
            template,
            source,
            tower,
            finalized,
            occupied=OccupiedBounds(40, 50, 40, 50),
            placement=placement,
            tower_full_infill=True,
        )

        with zipfile.ZipFile(finalized) as archive:
            finalized_model = archive.read(model_name)
        self.assertIn(
            b'xmlns:BambuStudio="'
            + BAMBU_STUDIO_NAMESPACE.encode("ascii")
            + b'"',
            finalized_model,
        )

    def test_bambu_export_restores_only_semantically_changed_filament_values(self) -> None:
        source = self.root / "source.stl"
        tower = self.root / "tower.stl"
        trimesh.creation.box(extents=(10, 10, 5)).export(source)
        trimesh.creation.cylinder(radius=4, height=5, sections=16).export(tower)
        project = self.root / "bambu_project.3mf"
        placement = TowerPlacement(
            80.0, 80.0, 4.0, BedBounds(0, 200, 0, 200), 25.0
        )
        build_joint_project(
            source,
            tower,
            project,
            occupied=OccupiedBounds(40, 50, 40, 50),
            placement=placement,
            tower_full_infill=True,
        )
        with zipfile.ZipFile(project, "a", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "Metadata/project_settings.config",
                json.dumps(
                    {
                        "filament_dev_ams_drying_ams_limitations": ["1"],
                        "slow_down_layer_time": ["12", "12", "12"],
                    }
                ),
            )
        filament = self.root / "temporary_filament.json"
        filament.write_text(
            json.dumps(
                {
                    "name": "Temporary filament",
                    "type": "filament",
                    "filament_dev_ams_drying_ams_limitations": ["1", "0"],
                    "slow_down_layer_time": "12.0",
                }
            ),
            encoding="utf-8",
        )
        before = filament.read_bytes()

        digest = synchronize_bambu_project_filament_settings(
            project,
            (filament,),
        )

        with zipfile.ZipFile(project) as archive:
            values = json.loads(
                archive.read("Metadata/project_settings.config")
            )
        self.assertEqual(
            values["filament_dev_ams_drying_ams_limitations"],
            ["1", "0"],
        )
        self.assertEqual(
            values["slow_down_layer_time"],
            ["12", "12", "12"],
        )
        self.assertEqual(filament.read_bytes(), before)
        self.assertEqual(digest, hashlib.sha256(project.read_bytes()).hexdigest())

    def test_tower_infill_validation_accepts_solid_and_rejects_sparse(self) -> None:
        solid = self.root / "solid.gcode"
        solid.write_text(
            "EXCLUDE_OBJECT_START NAME=Cooling_tower_id_1_copy_0\n"
            ";TYPE:Internal solid infill\n"
            "G1 X1 Y1 E1\n"
            "EXCLUDE_OBJECT_END NAME=Cooling_tower_id_1_copy_0\n"
            "EXCLUDE_OBJECT_START NAME=Source_object_id_0_copy_0\n"
            ";TYPE:Sparse infill\n"
            "EXCLUDE_OBJECT_END NAME=Source_object_id_0_copy_0\n",
            encoding="utf-8",
        )
        validate_tower_infill_adoption(solid)

        sparse = self.root / "sparse.gcode"
        sparse.write_text(
            "EXCLUDE_OBJECT_START NAME=Cooling_tower_id_1_copy_0\n"
            ";TYPE:Sparse infill\n"
            "EXCLUDE_OBJECT_END NAME=Cooling_tower_id_1_copy_0\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(JointProjectError, "Sparse Infill"):
            validate_tower_infill_adoption(sparse)

        bambu = self.root / "bambu_solid.gcode"
        bambu.write_text(
            "; start printing object, unique label id: 58\n"
            "; printing object Cooling_tower_id_0_copy_0\n"
            "; FEATURE: Sparse infill\n"
            "; LINE_WIDTH: 0.45\n"
            "G1 X1 Y1 E1\n"
            "; stop printing object, unique label id: 58\n",
            encoding="utf-8",
        )
        validate_tower_infill_adoption(bambu)

    def test_bambu_numeric_object_label_is_matched_to_tower_position(self) -> None:
        positioned = self.root / "bambu_positioned.gcode"
        positioned.write_text(
            "; start printing object, unique label id: 45\n"
            "G1 X120 Y120 E1\n"
            "G1 X130 Y130 E1\n"
            "; stop printing object, unique label id: 45\n"
            "; start printing object, unique label id: 46\n"
            "G1 X89.5 Y149.5 E1\n"
            "; FEATURE: Sparse infill\n"
            "G1 X90.5 Y150.5 E1\n"
            "; stop printing object, unique label id: 46\n",
            encoding="utf-8",
        )

        validate_tower_infill_adoption(
            positioned,
            tower_center_xy_mm=(90.0, 150.0),
        )

        rejected = self.root / "bambu_positioned_sparse.gcode"
        rejected.write_text(
            positioned.read_text(encoding="utf-8").replace(
                "; FEATURE: Sparse infill", ";TYPE:Sparse infill"
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(JointProjectError, "Sparse Infill"):
            validate_tower_infill_adoption(
                rejected,
                tower_center_xy_mm=(90.0, 150.0),
            )


if __name__ == "__main__":
    unittest.main()
