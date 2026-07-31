from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cooling_tower.models.gcode_metadata import SlicerFamily
from cooling_tower.calibration.gcode_integration import parse_bed_bounds
from cooling_tower.gcode.metadata_parser import parse_typed_config_value
from cooling_tower.gcode.parser import GCodeLine, parse_gcode_line
from cooling_tower.slicers.models import (
    ProfileKind,
    ProfileRecord,
    SlicerCapability,
    SlicerDiscoverySource,
    SlicerInstallation,
    SlicerSupportLevel,
)
from cooling_tower.slicers.profile_inventory import ProfileInventoryService
from cooling_tower.slicers.qprocess_backend import _BoundedProcessOutput


class _InventoryAdapter:
    adapter_id = "hardening-test"

    def __init__(self, profile_path: Path, barrier: threading.Barrier | None = None):
        self.profile_path = profile_path
        self.barrier = barrier
        self.discovery_count = 0

    def discover_profiles(
        self,
        _installation: SlicerInstallation,
    ) -> tuple[ProfileRecord, ...]:
        self.discovery_count += 1
        if self.barrier is not None:
            self.barrier.wait(timeout=5)
        return (
            ProfileRecord(
                adapter_id=self.adapter_id,
                profile_id=self.profile_path.stem,
                name=self.profile_path.stem,
                kind=ProfileKind.PROCESS,
                path=self.profile_path,
                source="user",
            ),
        )


def _installation(root: Path, executable_name: str) -> SlicerInstallation:
    executable = root / executable_name
    executable.write_bytes(b"test executable")
    return SlicerInstallation(
        adapter_id="hardening-test",
        product_name="Hardening Test Slicer",
        version="1.0",
        executable_path=executable,
        verified=True,
        capabilities=frozenset(
            {SlicerCapability.PROFILE_INVENTORY, SlicerCapability.CLI_SLICE}
        ),
        discovery_source=SlicerDiscoverySource.MANUAL,
        family=SlicerFamily.UNKNOWN,
        support_level=SlicerSupportLevel.FULL,
        profile_roots=(root,),
    )


class ProfileInventoryHardeningTests(unittest.TestCase):
    def test_inventory_rejects_foreign_adapter_and_foreign_root_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selected_root = root / "selected-slicer"
            foreign_root = root / "foreign-slicer"
            selected_root.mkdir()
            foreign_root.mkdir()
            valid = selected_root / "valid.json"
            wrong_adapter = selected_root / "wrong-adapter.json"
            wrong_root = foreign_root / "wrong-root.json"
            for path in (valid, wrong_adapter, wrong_root):
                path.write_text("{}", encoding="utf-8")

            class MixedAdapter(_InventoryAdapter):
                def discover_profiles(self, _installation):
                    return (
                        ProfileRecord(
                            adapter_id=self.adapter_id,
                            profile_id="valid",
                            name="valid",
                            kind=ProfileKind.PROCESS,
                            path=valid,
                            source="user",
                        ),
                        ProfileRecord(
                            adapter_id="foreign-adapter",
                            profile_id="wrong-adapter",
                            name="wrong-adapter",
                            kind=ProfileKind.PROCESS,
                            path=wrong_adapter,
                            source="user",
                        ),
                        ProfileRecord(
                            adapter_id=self.adapter_id,
                            profile_id="wrong-root",
                            name="wrong-root",
                            kind=ProfileKind.PROCESS,
                            path=wrong_root,
                            source="user",
                        ),
                    )

            inventory = ProfileInventoryService().load(
                MixedAdapter(valid),
                _installation(selected_root, "slicer.exe"),
            )

            self.assertEqual(
                [record.profile_id for record in inventory.records],
                ["valid"],
            )

    def test_cache_size_limit_rejects_boolean_and_non_integer_values(self) -> None:
        for invalid in (True, 1.5, "64"):
            with self.subTest(value=invalid):
                with self.assertRaisesRegex(ValueError, "positive integer"):
                    ProfileInventoryService(
                        "inventory-cache.json",
                        maximum_cache_bytes=invalid,  # type: ignore[arg-type]
                    )

    def test_malformed_installations_collection_is_rebuilt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = root / "profile.json"
            profile.write_text("{}", encoding="utf-8")
            cache = root / "inventory-cache.json"
            cache.write_text(
                json.dumps({"schema_version": 1, "installations": []}),
                encoding="utf-8",
            )
            adapter = _InventoryAdapter(profile)

            inventory = ProfileInventoryService(cache).load(
                adapter,
                _installation(root, "slicer.exe"),
            )

            self.assertEqual(adapter.discovery_count, 1)
            self.assertEqual(inventory.records[0].name, "profile")
            persisted = json.loads(cache.read_text(encoding="utf-8"))
            self.assertIsInstance(persisted["installations"], dict)

    def test_tampered_persisted_fingerprint_is_not_trusted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = root / "profile.json"
            profile.write_text("{}", encoding="utf-8")
            cache = root / "inventory-cache.json"
            installation = _installation(root, "slicer.exe")
            first_adapter = _InventoryAdapter(profile)
            ProfileInventoryService(cache).load(first_adapter, installation)
            payload = json.loads(cache.read_text(encoding="utf-8"))
            entry = payload["installations"][installation.identity_key]
            entry["records"][0]["name"] = "tampered"
            cache.write_text(json.dumps(payload), encoding="utf-8")
            second_adapter = _InventoryAdapter(profile)

            inventory = ProfileInventoryService(cache).load(
                second_adapter,
                installation,
            )

            self.assertEqual(second_adapter.discovery_count, 1)
            self.assertEqual(inventory.records[0].name, "profile")

    def test_parallel_services_preserve_both_cache_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_root = root / "first"
            second_root = root / "second"
            first_root.mkdir()
            second_root.mkdir()
            first_profile = first_root / "first.json"
            second_profile = second_root / "second.json"
            first_profile.write_text("{}", encoding="utf-8")
            second_profile.write_text("{}", encoding="utf-8")
            cache = root / "inventory-cache.json"
            barrier = threading.Barrier(2)
            first_installation = _installation(first_root, "first.exe")
            second_installation = _installation(second_root, "second.exe")
            failures: list[BaseException] = []

            def load(
                profile: Path,
                installation: SlicerInstallation,
            ) -> None:
                try:
                    ProfileInventoryService(cache).load(
                        _InventoryAdapter(profile, barrier),
                        installation,
                    )
                except BaseException as error:  # captured for the main test thread
                    failures.append(error)

            threads = (
                threading.Thread(
                    target=load,
                    args=(first_profile, first_installation),
                ),
                threading.Thread(
                    target=load,
                    args=(second_profile, second_installation),
                ),
            )
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)

            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(failures, [])
            payload = json.loads(cache.read_text(encoding="utf-8"))
            self.assertEqual(
                set(payload["installations"]),
                {
                    first_installation.identity_key,
                    second_installation.identity_key,
                },
            )


class RuntimeInvariantHardeningTests(unittest.TestCase):
    def test_diagnostics_write_requires_an_open_archive(self) -> None:
        output = _BoundedProcessOutput(128, None)
        with self.assertRaisesRegex(RuntimeError, "archive is not open"):
            output._write_archive_chunk("stdout", b"payload")


class NumericInputHardeningTests(unittest.TestCase):
    def test_non_finite_gcode_parameter_is_left_unparsed(self) -> None:
        parsed = parse_gcode_line(
            GCodeLine(number=1, text="G1 X1e999 Y10 E1")
        )

        self.assertEqual(parsed.parameters, {})
        self.assertEqual(parsed.unparsed_text, "X1e999 Y10 E1")

    def test_non_finite_metadata_number_is_marked_invalid(self) -> None:
        parsed = parse_typed_config_value(
            "machine_width",
            "1e999",
            source_line=1,
        )

        self.assertFalse(parsed.valid)
        self.assertEqual(parsed.value, "1e999")

    def test_non_finite_bed_dimensions_are_rejected(self) -> None:
        self.assertIsNone(
            parse_bed_bounds(
                {"machine_width": float("inf"), "machine_depth": 200.0}
            )
        )
        self.assertIsNone(
            parse_bed_bounds(
                {"machine_width": "9" * 400, "machine_depth": "200"}
            )
        )


if __name__ == "__main__":
    unittest.main()
