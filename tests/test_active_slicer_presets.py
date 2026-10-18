from __future__ import annotations

import os
import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


from cooling_tower.models.gcode_metadata import SlicerFamily
from cooling_tower.slicers.active_presets import read_active_presets
from cooling_tower.slicers.models import (
    SlicerDiscoverySource,
    SlicerInstallation,
)


class ActiveSlicerPresetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.executable = self.root / "slicer.exe"
        self.executable.write_bytes(b"MZ")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def installation(
        self,
        adapter_id: str,
        profile_root: Path,
    ) -> SlicerInstallation:
        return SlicerInstallation(
            adapter_id=adapter_id,
            product_name=adapter_id,
            version="1.0",
            executable_path=self.executable,
            verified=True,
            capabilities=frozenset(),
            discovery_source=SlicerDiscoverySource.MANUAL,
            family=SlicerFamily.UNKNOWN,
            profile_roots=(profile_root,),
        )

    def test_orca_family_reads_persisted_preset_section(self) -> None:
        for adapter_id, config_name in (
            ("orca_slicer", "OrcaSlicer.conf"),
            ("bambu_studio", "BambuStudio.conf"),
            ("anycubic_slicer_next", "AnycubicSlicerNext.conf"),
        ):
            with self.subTest(adapter_id=adapter_id):
                root = self.root / adapter_id
                (root / "user").mkdir(parents=True)
                (root / config_name).write_text(
                    "[presets]\n"
                    "printer = Kobra 3 0.4 nozzle\n"
                    "print = 0.20 mm Quality\n"
                    "filament = [\"Generic PLA\", \"Support PLA\"]\n"
                    "nozzle_diameter = 0.4\n",
                    encoding="utf-8",
                )

                result = read_active_presets(
                    self.installation(adapter_id, root / "user")
                )

                self.assertEqual(result.printer_ids, ("Kobra 3 0.4 nozzle",))
                self.assertEqual(result.process_ids, ("0.20 mm Quality",))
                self.assertEqual(
                    result.filament_ids,
                    ("Generic PLA", "Support PLA"),
                )
                self.assertEqual(result.nozzle_diameters_mm, (0.4,))
                self.assertEqual(result.source_path, (root / config_name).resolve())

    def test_prusa_and_cura_active_machine_formats_are_supported(self) -> None:
        prusa_root = self.root / "PrusaSlicer"
        prusa_root.mkdir()
        (prusa_root / "PrusaSlicer.ini").write_text(
            "alert_when_supports_needed = 1\n"
            "[presets]\n"
            "printer = Original Prusa MK4S 0.4 nozzle\n"
            "print = 0.20mm STRUCTURAL\n"
            "filament = Prusament PETG\n",
            encoding="utf-8",
        )
        prusa = read_active_presets(
            self.installation("prusa_slicer", prusa_root)
        )
        self.assertEqual(
            prusa.printer_ids,
            ("Original Prusa MK4S 0.4 nozzle",),
        )
        self.assertEqual(prusa.process_ids, ("0.20mm STRUCTURAL",))

        cura_root = self.root / "cura"
        version_root = cura_root / "5.9"
        version_root.mkdir(parents=True)
        (version_root / "cura.cfg").write_text(
            "[cura]\n"
            "active_machine = anycubic_kobra_3\n"
            "quality = normal\n"
            "material = generic_pla\n",
            encoding="utf-8",
        )
        cura = read_active_presets(self.installation("cura", cura_root))
        self.assertEqual(cura.printer_ids, ("anycubic_kobra_3",))
        self.assertEqual(cura.process_ids, ("normal",))
        self.assertEqual(cura.filament_ids, ("generic_pla",))

    def test_nested_json_and_numbered_filaments_are_read_without_changes(self) -> None:
        root = self.root / "nested-json"
        user_root = root / "user"
        user_root.mkdir(parents=True)
        config = root / "AnycubicSlicerNext.conf"
        config.write_text(
            json.dumps(
                {
                    "presets": {
                        "printer": "Configured printer",
                        "print": "Configured process",
                        "filament_0": "Configured PLA",
                        "filament_1": "Configured support",
                        "filament_ams": "not a preset identifier",
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        before = config.read_bytes()

        result = read_active_presets(
            self.installation("anycubic_slicer_next", user_root)
        )

        self.assertEqual(result.printer_ids, ("Configured printer",))
        self.assertEqual(result.process_ids, ("Configured process",))
        self.assertEqual(
            result.filament_ids,
            ("Configured PLA", "Configured support"),
        )
        self.assertEqual(config.read_bytes(), before)

    def test_missing_malformed_and_oversized_configs_fail_closed(self) -> None:
        root = self.root / "invalid"
        root.mkdir()
        installation = self.installation("orca_slicer", root)
        self.assertFalse(read_active_presets(installation).has_printer_context)

        config = root / "OrcaSlicer.conf"
        config.write_text("not an ini or json", encoding="utf-8")
        self.assertFalse(read_active_presets(installation).has_printer_context)

        config.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
        os.utime(config, None)
        self.assertFalse(read_active_presets(installation).has_printer_context)


if __name__ == "__main__":
    unittest.main()
