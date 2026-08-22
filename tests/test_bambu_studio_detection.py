from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


from cooling_tower.models.gcode_metadata import SlicerFamily
from cooling_tower.models.source import SourceArtifact
from cooling_tower.slicers import (
    BambuStudioAdapter,
    ProfileInventoryService,
    ProfileKind,
    ProfileMatchingService,
    ProfileMatchingContext,
    ProfileSelectionReference,
    SlicerCapability,
    SlicerDiscoverySource,
    SlicerInstallation,
    SlicerSupportLevel,
    read_active_presets,
)


class BambuStudioDetectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.appdata = self.root / "appdata"
        self.install = self.root / "Bambu Studio"
        self.executable = self.install / "bambu-studio.exe"
        self.executable.parent.mkdir(parents=True)
        self.executable.write_bytes(b"MZ")
        self.resource_profiles = self.install / "resources" / "profiles"
        self.bbl_resources = self.resource_profiles / "BBL"
        self.anker_resources = self.resource_profiles / "Anker"
        self.bambu_data = self.appdata / "BambuStudio"
        self.user_root = self.bambu_data / "user"
        self.system_bbl = self.bambu_data / "system" / "BBL"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def write_json(path: Path, payload: dict[str, object]) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def adapter_and_installation(self):
        adapter = BambuStudioAdapter()
        with patch.dict(os.environ, {"APPDATA": str(self.appdata)}):
            roots = adapter.profile_roots_for(self.executable)
        installation = SlicerInstallation(
            adapter_id=adapter.adapter_id,
            product_name=adapter.product_name,
            version="02.08.02.61",
            executable_path=self.executable,
            verified=True,
            capabilities=frozenset({SlicerCapability.CLI_SLICE}),
            discovery_source=SlicerDiscoverySource.KNOWN_PATH,
            family=SlicerFamily.ORCA_BAMBU_ANYCUBIC,
            support_level=SlicerSupportLevel.FULL,
            profile_roots=roots,
        )
        return adapter, installation

    def create_realistic_catalog(self) -> dict[str, Path]:
        paths = {
            "machine_base": self.write_json(
                self.system_bbl / "machine" / "fdm_machine_common.json",
                {
                    "name": "fdm_machine_common",
                    "type": "machine",
                    "from": "system",
                    "instantiation": "false",
                    "printer_technology": "FFF",
                },
            ),
            "machine": self.write_json(
                self.system_bbl
                / "machine"
                / "Bambu Lab X2D 0.4 nozzle.json",
                {
                    "name": "Bambu Lab X2D 0.4 nozzle",
                    "type": "machine",
                    "inherits": "fdm_machine_common",
                    "from": "system",
                    "instantiation": "true",
                    "printer_model": "Bambu Lab X2D",
                    "printer_variant": "0.4",
                    "nozzle_diameter": ["0.4", "0.4"],
                    "extruder_count": 2,
                },
            ),
            "other_bambu_machine": self.write_json(
                self.system_bbl / "machine" / "Bambu Lab A1 0.4 nozzle.json",
                {
                    "name": "Bambu Lab A1 0.4 nozzle",
                    "type": "machine",
                    "inherits": "fdm_machine_common",
                    "from": "system",
                    "instantiation": "true",
                    "printer_model": "Bambu Lab A1",
                    "printer_variant": "0.4",
                    "nozzle_diameter": "0.4",
                },
            ),
            "process_base": self.write_json(
                self.system_bbl / "process" / "fdm_process_common.json",
                {
                    "name": "fdm_process_common",
                    "type": "process",
                    "from": "system",
                    "instantiation": "false",
                    "layer_height": "0.20",
                },
            ),
            "process": self.write_json(
                self.system_bbl
                / "process"
                / "0.20mm Standard @BBL X2D.json",
                {
                    "name": "0.20mm Standard @BBL X2D",
                    "type": "process",
                    "inherits": "fdm_process_common",
                    "from": "system",
                    "instantiation": "true",
                    "compatible_printers": "Bambu Lab X2D 0.4 nozzle",
                    "print_settings_id": "0.20mm Standard @BBL X2D",
                },
            ),
            "filament_base": self.write_json(
                self.system_bbl / "filament" / "Bambu PLA Basic @base.json",
                {
                    "name": "Bambu PLA Basic @base",
                    "type": "filament",
                    "from": "system",
                    "instantiation": "false",
                    "filament_type": "PLA",
                },
            ),
            "filament": self.write_json(
                self.system_bbl
                / "filament"
                / "Bambu PLA Basic @BBL X2D 0.4 nozzle.json",
                {
                    "name": "Bambu PLA Basic @BBL X2D 0.4 nozzle",
                    "type": "filament",
                    "inherits": "Bambu PLA Basic @base",
                    "from": "system",
                    "instantiation": "true",
                    "compatible_printers": "Bambu Lab X2D 0.4 nozzle",
                    "filament_settings_id": (
                        "Bambu PLA Basic @BBL X2D 0.4 nozzle"
                    ),
                },
            ),
            "user_process": self.write_json(
                self.user_root
                / "default"
                / "process"
                / "Test Prozessprofil (own).json",
                {
                    "name": "Test Prozessprofil (own)",
                    "inherits": "0.20mm Standard @BBL X2D",
                    "from": "User",
                    "print_settings_id": "Test Prozessprofil (own)",
                },
            ),
            "user_filament": self.write_json(
                self.user_root
                / "default"
                / "filament"
                / "Test PLA Filamentprofil (own).json",
                {
                    "name": "Test PLA Filamentprofil (own)",
                    "inherits": "Bambu PLA Basic @BBL X2D 0.4 nozzle",
                    "from": "User",
                    "filament_settings_id": "Test PLA Filamentprofil (own)",
                },
            ),
            "helper": self.write_json(
                self.system_bbl / "filament" / "filament_id_map.json",
                {"GM001": "not a preset"},
            ),
            "foreign_machine": self.write_json(
                self.anker_resources / "machine" / "Anker M5.json",
                {
                    "name": "Anker M5",
                    "type": "machine",
                    "instantiation": "true",
                },
            ),
        }
        self.bbl_resources.mkdir(parents=True, exist_ok=True)
        config_payload = {
            "header": "BambuStudio 02.08.02.61",
            "filaments": ["many available presets, not the active bundle"],
            "presets": {
                "machine": "Bambu Lab X2D 0.4 nozzle",
                "process": "0.20mm Standard @BBL X2D",
                "filaments": ["Test PLA Filamentprofil (own)"],
            },
        }
        config = self.bambu_data / "BambuStudio.conf"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(
            json.dumps(config_payload, ensure_ascii=False, indent=2)
            + "\n# MD5 checksum 0123456789ABCDEF\n",
            encoding="utf-8",
        )
        paths["config"] = config
        return paths

    def test_profile_roots_are_bambu_only_and_keep_anycubic_independent(self) -> None:
        self.create_realistic_catalog()
        _adapter, installation = self.adapter_and_installation()
        roots = {path.resolve() for path in installation.profile_roots}
        self.assertIn(self.user_root.resolve(), roots)
        self.assertIn(self.system_bbl.resolve(), roots)
        self.assertNotIn(self.resource_profiles.resolve(), roots)
        self.assertNotIn(self.anker_resources.resolve(), roots)
        self.assertNotIn(self.bbl_resources.resolve(), roots)

    def test_bundled_bbl_catalog_is_fallback_without_local_system_catalog(self) -> None:
        self.bbl_resources.mkdir(parents=True)
        adapter = BambuStudioAdapter()
        empty_appdata = self.root / "empty-appdata"
        with patch.dict(os.environ, {"APPDATA": str(empty_appdata)}):
            roots = adapter.profile_roots_for(self.executable)
        self.assertEqual(roots, (self.bbl_resources.resolve(),))

    def test_active_bambu_bundle_accepts_checksum_footer_and_plural_keys(self) -> None:
        paths = self.create_realistic_catalog()
        _adapter, installation = self.adapter_and_installation()
        before = paths["config"].read_bytes()

        active = read_active_presets(installation)

        self.assertEqual(active.printer_ids, ("Bambu Lab X2D 0.4 nozzle",))
        self.assertEqual(active.process_ids, ("0.20mm Standard @BBL X2D",))
        self.assertEqual(
            active.filament_ids,
            ("Test PLA Filamentprofil (own)",),
        )
        self.assertEqual(active.source_path, paths["config"].resolve())
        self.assertEqual(paths["config"].read_bytes(), before)

    def test_active_config_is_found_from_system_bbl_root_without_user_root(self) -> None:
        self.create_realistic_catalog()
        _adapter, installation = self.adapter_and_installation()
        system_only = SlicerInstallation(
            adapter_id=installation.adapter_id,
            product_name=installation.product_name,
            version=installation.version,
            executable_path=installation.executable_path,
            verified=True,
            capabilities=installation.capabilities,
            discovery_source=installation.discovery_source,
            family=installation.family,
            support_level=installation.support_level,
            profile_roots=(self.system_bbl,),
        )
        self.assertEqual(
            read_active_presets(system_only).printer_ids,
            ("Bambu Lab X2D 0.4 nozzle",),
        )

    def test_inventory_excludes_foreign_vendor_and_internal_helper_json(self) -> None:
        paths = self.create_realistic_catalog()
        adapter, installation = self.adapter_and_installation()
        before = {name: path.read_bytes() for name, path in paths.items()}

        records = adapter.discover_profiles(installation)

        names = {record.name for record in records}
        self.assertIn("Bambu Lab X2D 0.4 nozzle", names)
        self.assertIn("Test PLA Filamentprofil (own)", names)
        self.assertIn("Test Prozessprofil (own)", names)
        self.assertNotIn("Anker M5", names)
        self.assertNotIn("filament_id_map", names)
        self.assertTrue(all(record.kind is not ProfileKind.UNKNOWN for record in records))
        self.assertEqual(
            {name: path.read_bytes() for name, path in paths.items()},
            before,
        )

    def test_catalog_uses_active_x2d_and_offers_user_and_system_presets(self) -> None:
        paths = self.create_realistic_catalog()
        adapter, installation = self.adapter_and_installation()
        before = {name: path.read_bytes() for name, path in paths.items()}
        service = ProfileMatchingService(
            inventory_service=ProfileInventoryService()
        )

        catalog = service.catalog(installation, adapter)

        self.assertTrue(catalog.complete, catalog.blocking_message)
        self.assertIsNotNone(catalog.selected_machine)
        self.assertEqual(
            catalog.selected_machine.profile_id,
            "Bambu Lab X2D 0.4 nozzle",
        )
        machine_names = {item.name for item in catalog.machine_options}
        process_names = {item.name for item in catalog.process_options}
        filament_names = {item.name for item in catalog.filament_options}
        self.assertEqual(machine_names, {"Bambu Lab X2D 0.4 nozzle"})
        self.assertIn("0.20mm Standard @BBL X2D", process_names)
        self.assertIn("Test Prozessprofil (own)", process_names)
        self.assertIn(
            "Bambu PLA Basic @BBL X2D 0.4 nozzle", filament_names
        )
        self.assertIn("Test PLA Filamentprofil (own)", filament_names)
        self.assertNotIn("filament_id_map", filament_names)
        self.assertEqual(catalog.missing_roles, ())
        self.assertIsNone(catalog.blocking_message)
        incomplete = replace(catalog, process_options=())
        self.assertEqual(incomplete.missing_roles, ("Prozessprofile",))
        self.assertIn("Prozessprofile", incomplete.blocking_message)
        self.assertIn("Bestätigung nicht möglich", incomplete.blocking_message)
        self.assertEqual(
            {name: path.read_bytes() for name, path in paths.items()},
            before,
        )

    def test_stale_foreign_machine_falls_back_to_active_bambu_machine(self) -> None:
        paths = self.create_realistic_catalog()
        adapter, installation = self.adapter_and_installation()
        service = ProfileMatchingService(
            inventory_service=ProfileInventoryService()
        )
        before = {name: path.read_bytes() for name, path in paths.items()}

        catalog = service.catalog(
            installation,
            adapter,
            selected_machine=ProfileSelectionReference(
                "Anker M5",
                paths["foreign_machine"],
            ),
        )

        self.assertEqual(
            catalog.selected_machine.profile_id,
            "Bambu Lab X2D 0.4 nozzle",
        )
        self.assertEqual(
            {item.profile_id for item in catalog.machine_options},
            {"Bambu Lab X2D 0.4 nozzle"},
        )
        self.assertTrue(
            any(item.source == "system" for item in catalog.process_options)
        )
        self.assertTrue(
            any(item.source == "system" for item in catalog.filament_options)
        )
        self.assertEqual(
            {name: path.read_bytes() for name, path in paths.items()},
            before,
        )

    def test_rediscovery_prefers_active_machine_over_valid_old_choice(self) -> None:
        paths = self.create_realistic_catalog()
        adapter, installation = self.adapter_and_installation()
        service = ProfileMatchingService(
            inventory_service=ProfileInventoryService()
        )

        catalog = service.catalog(
            installation,
            adapter,
            selected_machine=ProfileSelectionReference(
                "Bambu Lab A1 0.4 nozzle",
                paths["other_bambu_machine"],
            ),
            prefer_active_presets=True,
        )

        self.assertEqual(
            catalog.selected_machine.profile_id,
            "Bambu Lab X2D 0.4 nozzle",
        )
        self.assertIn(
            "0.20mm Standard @BBL X2D",
            {item.profile_id for item in catalog.process_options},
        )
        self.assertIn(
            "Bambu PLA Basic @BBL X2D 0.4 nozzle",
            {item.profile_id for item in catalog.filament_options},
        )

    def test_stl_matching_proposes_the_active_complete_bambu_bundle(self) -> None:
        paths = self.create_realistic_catalog()
        adapter, installation = self.adapter_and_installation()
        model = self.root / "accepted-manifold.stl"
        model.write_text(
            "solid model\n"
            "facet normal 0 0 1\n"
            "outer loop\n"
            "vertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\n"
            "endloop\nendfacet\nendsolid model\n",
            encoding="ascii",
        )
        artifact = SourceArtifact.capture(model)
        service = ProfileMatchingService(
            inventory_service=ProfileInventoryService()
        )
        before = {name: path.read_bytes() for name, path in paths.items()}

        result = service.match(
            ProfileMatchingContext.from_stl(artifact),
            installation,
            adapter,
        )

        self.assertIsNotNone(result.selected, result.message)
        self.assertEqual(
            result.selected.machine.profile_id,
            "Bambu Lab X2D 0.4 nozzle",
        )
        self.assertEqual(
            result.selected.process.profile_id,
            "0.20mm Standard @BBL X2D",
        )
        self.assertEqual(
            result.selected.filament.profile_id,
            "Test PLA Filamentprofil (own)",
        )
        self.assertTrue(result.requires_confirmation)
        self.assertTrue(result.can_use_stl_mode)
        self.assertEqual(
            {name: path.read_bytes() for name, path in paths.items()},
            before,
        )


if __name__ == "__main__":
    unittest.main()
