"""Cross-cutting contracts that make later localized changes safer."""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from check_release_readiness import EXPECTED, checklist, missing_fields
from distribution_compliance import keep_qt_binary, copy_notice, binary_origins
from cooling_tower.cli import build_argument_parser
from cooling_tower.legal_documents import DOCUMENTS, render_legal_document
from cooling_tower.models import GenerationSettings
from cooling_tower.settings_defaults import GENERATION_DEFAULTS


class ProjectContractTests(unittest.TestCase):
    def test_current_domain_and_cli_defaults_agree(self):
        self.assertEqual(GenerationSettings().to_dict(), dict(GENERATION_DEFAULTS))
        args = build_argument_parser().parse_args(["--gcode", "example.gcode"])
        self.assertNotIn("base_height_mm", GENERATION_DEFAULTS)
        self.assertNotIn("--base-height ", build_argument_parser().format_help())
        self.assertEqual(args.minimum_diameter, GENERATION_DEFAULTS["minimum_outer_diameter_mm"])
        self.assertEqual(args.maximum_diameter, GENERATION_DEFAULTS["maximum_outer_diameter_mm"])
        self.assertIsNone(args.target_time)  # Deliberate CLI analysis-only default.

    def test_core_preview_can_import_without_loading_qt(self):
        code = "import cooling_tower.preview, sys; assert not any(n.startswith('PySide6') for n in sys.modules)"
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
        result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_domain_modules_do_not_import_gui(self):
        for folder in ("models", "tower", "gcode", "services", "calibration"):
            for path in (ROOT / "src/cooling_tower" / folder).rglob("*.py"):
                for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                    modules = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
                    for name in modules:
                        self.assertFalse(name.startswith(("PySide6", "cooling_tower.gui")), f"{path}: {name}")

    def test_qt_distribution_policy_rejects_unreviewed_modules(self):
        for path in ("PySide6/Qt6VirtualKeyboard.dll", "PySide6/Qt6Pdf.dll", "PySide6/Qt6Qml.dll", "PySide6/opengl32sw.dll", "PySide6/plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll"):
            self.assertFalse(keep_qt_binary(path), path)
        self.assertTrue(keep_qt_binary("PySide6/Qt6Widgets.dll"))
        self.assertTrue(keep_qt_binary("PySide6/plugins/platforms/qwindows.dll"))
        with self.assertRaises(ValueError):
            keep_qt_binary("PySide6/Qt6FutureModule.dll")
        with self.assertRaises(ValueError):
            keep_qt_binary("PySide6/QtVirtualKeyboard.pyd")

    def test_packaging_rejects_a_qt_dll_from_an_unrelated_program(self):
        with tempfile.TemporaryDirectory() as directory:
            foreign = Path(directory) / "Qt6Core.dll"
            foreign.write_bytes(b"unrelated DLL")
            with self.assertRaisesRegex(ValueError, "fixierten Wheel"):
                binary_origins([("PySide6/Qt6Core.dll", str(foreign), "BINARY")])

    def test_bootstrap_failure_log_stays_outside_the_installation(self):
        tree = ast.parse((ROOT / "start_gui.pyw").read_text(encoding="utf-8"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_fallback_startup_error")
        scope = {}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "bootstrap", "exec"), scope)
        fake_ctypes = SimpleNamespace(windll=SimpleNamespace(user32=SimpleNamespace(MessageBoxW=Mock())))
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, {"ctypes": fake_ctypes}):
            with patch.dict(os.environ, {"COOLING_TOWER_USER_DATA_ROOT": directory}):
                scope["_fallback_startup_error"]("controlled import failure")
            self.assertEqual((Path(directory) / "logs/application_startup.log").read_text(encoding="utf-8"), "controlled import failure")

    def test_license_paths_are_short_and_original_provenance_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first/LICENSE.txt"
            second = root / "second/LICENSE.txt"
            for path, data in ((first, b"first copyright"), (second, b"second copyright")):
                path.parent.mkdir()
                path.write_bytes(data)
            index = []
            origin = "upstream/" + "long-component/" * 25
            copy_notice(first, root / "output", component="Qt", origin=origin + "first/LICENSE.txt", index=index)
            copy_notice(second, root / "output", component="Qt", origin=origin + "second/LICENSE.txt", index=index)
            self.assertNotEqual(index[0]["file"], index[1]["file"])
            self.assertEqual(index[0]["origin"], origin + "first/LICENSE.txt")
            self.assertLess(len(index[0]["file"]), 100)
            self.assertEqual((root / "output" / index[1]["file"]).read_bytes(), b"second copyright")

    def test_wheel_registry_and_hashed_lock_are_identical(self):
        lock = (ROOT / "requirements-windows.lock").read_text(encoding="utf-8")
        entries = re.findall(r"^([\w.-]+)==([^\s]+)\s+--hash=sha256:([a-f0-9]{64})$", lock, re.M)
        canonical = lambda value: re.sub(r"[-_.]+", "-", value).lower()
        actual = {(canonical(name), version, digest) for name, version, digest in entries}
        registry = json.loads((ROOT / "config/dependency_artifacts.json").read_text(encoding="utf-8"))
        expected = {(canonical(item["name"]), item["version"], item["sha256"]) for item in registry["artifacts"]}
        self.assertEqual(actual, expected)

    def test_legal_documents_render_offline_from_one_profile(self):
        for title in DOCUMENTS:
            rendered = render_legal_document(title)
            self.assertNotIn("{{", rendered)
            self.assertGreater(len(rendered), 500)
        self.assertEqual((ROOT / "docs/missing_data.md").read_text(encoding="utf-8"), checklist())

    def test_release_gate_catches_missing_and_unregistered_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "legal").mkdir()
            profile = {key: "Ergänzte geprüfte Angabe" for key in EXPECTED}
            profile["provider_postal_address"] = "[[PROVIDER_POSTAL_ADDRESS]]"
            path = root / "config/legal_profile.json"
            path.write_text(json.dumps(profile), encoding="utf-8")
            self.assertEqual([key for key, _ in missing_fields(root)], ["provider_postal_address"])
            profile["provider_postal_address"] = "Beispielstraße 1, 12345 Beispielstadt, Deutschland"
            path.write_text(json.dumps(profile), encoding="utf-8")
            self.assertEqual(missing_fields(root), [])
            (root / "legal/terms.md").write_text("{{unknown_field}}", encoding="utf-8")
            self.assertTrue(missing_fields(root))


if __name__ == "__main__":
    unittest.main()
