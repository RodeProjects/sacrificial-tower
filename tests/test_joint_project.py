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
    MODEL_SETTINGS_PATH,
    TOWER_INFILL_KEY,
    build_joint_project,
    finalize_slicer_project,
    JointProjectError,
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

        self.assertEqual(SETTINGS_SCHEMA_VERSION, 9)
        self.assertEqual(settings.minimum_object_tower_distance_mm, 25.0)
        self.assertEqual(
            payload["generation"]["minimum_object_tower_distance_mm"],
            25.0,
        )
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


if __name__ == "__main__":
    unittest.main()
