from __future__ import annotations

import ast
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


from cooling_tower.slicers.detection import (
    SlicerDetectionModule,
    detection_module_for,
    detection_modules,
)
from cooling_tower.slicers import AnycubicSlicerNextAdapter


class SlicerDetectionModuleRegistryTests(unittest.TestCase):
    def test_detection_package_has_no_external_runtime_dependency(self) -> None:
        package_root = (
            SRC_ROOT / "cooling_tower" / "slicers" / "detection"
        )
        allowed = set(sys.stdlib_module_names) | {
            "__future__",
            "cooling_tower",
        }
        imported_roots: set[str] = set()
        for path in package_root.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported_roots.update(
                        alias.name.split(".", 1)[0] for alias in node.names
                    )
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported_roots.add(node.module.split(".", 1)[0])
        self.assertEqual(imported_roots - allowed, set())

    def test_every_requested_slicer_has_exactly_one_module(self) -> None:
        modules = detection_modules()
        ids = tuple(module.adapter_id for module in modules)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(
            set(ids),
            {
                "anycubic_slicer_next",
                "bambu_studio",
                "cura",
                "prusa_slicer",
                "orca_slicer",
                "creality_print",
            },
        )

    def test_prusa_is_operational_while_other_placeholders_remain_closed(self) -> None:
        implemented = {
            module.adapter_id
            for module in detection_modules()
            if module.implemented
        }
        self.assertEqual(
            implemented,
            {"anycubic_slicer_next", "bambu_studio", "prusa_slicer"},
        )
        for adapter_id in (
            "cura",
            "orca_slicer",
            "creality_print",
        ):
            with self.subTest(adapter_id=adapter_id):
                self.assertIsNotNone(detection_module_for(adapter_id))
                self.assertIsNone(
                    detection_module_for(adapter_id, implemented_only=True)
                )

    def test_orca_lineage_is_declared_without_implementing_placeholders(self) -> None:
        self.assertTrue(
            detection_module_for("anycubic_slicer_next").orca_derived
        )
        self.assertTrue(detection_module_for("bambu_studio").orca_derived)
        self.assertTrue(detection_module_for("orca_slicer").orca_derived)
        self.assertTrue(detection_module_for("creality_print").orca_derived)

    def test_usage_detection_stats_only_each_modules_exact_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            appdata = Path(temporary)
            expected = {
                "anycubic_slicer_next": (
                    appdata
                    / "AnycubicSlicerNext"
                    / "AnycubicSlicerNext.conf"
                ),
                "bambu_studio": (
                    appdata / "BambuStudio" / "BambuStudio.conf"
                ),
            }
            for adapter_id, marker in expected.items():
                with self.subTest(adapter_id=adapter_id):
                    marker.parent.mkdir(parents=True, exist_ok=True)
                    marker.write_bytes(b"private local configuration")
                    before = marker.read_bytes()
                    module = detection_module_for(adapter_id)
                    self.assertEqual(
                        module.usage_marker_paths(appdata_root=appdata),
                        (marker,),
                    )
                    self.assertEqual(
                        module.latest_usage_timestamp_ns(
                            appdata_root=appdata
                        ),
                        marker.stat().st_mtime_ns,
                    )
                    self.assertEqual(marker.read_bytes(), before)

    def test_adapter_accepts_a_contract_compatible_replacement_module(self) -> None:
        class ReplacementModule(SlicerDetectionModule):
            def profile_roots_for(self, executable, *, appdata_root):
                return (executable.parent / "replacement-profiles",)

        module = ReplacementModule(
            adapter_id="anycubic_slicer_next",
            product_name="Test replacement",
            implemented=True,
            orca_derived=True,
        )
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "slicer.exe"
            adapter = AnycubicSlicerNextAdapter(detection_module=module)
            self.assertEqual(
                adapter.profile_roots_for(executable),
                (executable.parent / "replacement-profiles",),
            )

    def test_adapter_rejects_cross_slicer_or_placeholder_replacement(self) -> None:
        with self.assertRaisesRegex(ValueError, "different slicer"):
            AnycubicSlicerNextAdapter(
                detection_module=SlicerDetectionModule(
                    adapter_id="bambu_studio",
                    product_name="Wrong module",
                    implemented=True,
                )
            )
        with self.assertRaisesRegex(ValueError, "placeholder"):
            AnycubicSlicerNextAdapter(
                detection_module=SlicerDetectionModule(
                    adapter_id="anycubic_slicer_next",
                    product_name="Placeholder",
                    implemented=False,
                )
            )


if __name__ == "__main__":
    unittest.main()
