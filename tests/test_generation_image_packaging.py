"""The generation artwork must work with the packaged Qt plugin policy."""
from __future__ import annotations

import ast
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from distribution_compliance import keep_qt_binary


class GenerationImagePackagingTests(unittest.TestCase):
    def test_packaged_artwork_renders_without_optional_image_plugins(self):
        """Stage the spec's actual asset source and emulate frozen module paths."""
        spec = ast.parse((ROOT / "SacrificialTower.spec").read_text(encoding="utf-8"))
        analysis = next(node for node in ast.walk(spec)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "Analysis")
        data = next(keyword.value for keyword in analysis.keywords if keyword.arg == "datas")
        asset_entry = next(entry for entry in data.elts
            if entry.elts[1].value == "cooling_tower/gui/assets")

        def source_path(node):
            if isinstance(node, ast.Name) and node.id == "source_root":
                return ROOT / "src"
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                return node.value
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                return source_path(node.left) / source_path(node.right)
            self.fail("Die Quelle der GUI-Assets muss als Paketpfad auflösbar sein.")

        asset_call = asset_entry.elts[0]
        self.assertIsInstance(asset_call, ast.Call)
        self.assertEqual(asset_call.func.id, "str")
        assets = source_path(asset_call.args[0])
        # The real distribution deliberately omits the optional WebP decoder.
        self.assertFalse(keep_qt_binary("PySide6/plugins/imageformats/qwebp.dll"))
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "_internal"
            staged_assets = bundle / asset_entry.elts[1].value
            shutil.copytree(assets, staged_assets)
            module_path = staged_assets.parent / "generation_progress_dialog.py"
            shutil.copy2(ROOT / "src/cooling_tower/gui/generation_progress_dialog.py", module_path)
            code = textwrap.dedent("""
                import importlib.util
                from pathlib import Path
                import sys
                from PySide6.QtCore import QCoreApplication
                from PySide6.QtGui import QImageReader
                from PySide6.QtWidgets import QApplication

                app = QApplication([])
                # Start a fresh decoder registry; no development image plugin
                # may make this packaging regression pass accidentally.
                QCoreApplication.setLibraryPaths([])
                assert b'webp' not in [bytes(f) for f in QImageReader.supportedImageFormats()]
                spec = importlib.util.spec_from_file_location('packaged_progress', sys.argv[1])
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                path = module.GENERATION_IMAGE_PATH
                assert path == Path(sys.argv[1]).parent / 'assets/tower_gen_finished.png'
                widget = module.TowerImageProgress(path)
                assert not widget._pixmap.isNull(), 'Das gebündelte Turmbild ist leer.'
                assert widget._pixmap.width() == 1035 and widget._pixmap.height() == 1215
                widget.show()
                widget.set_fill(0.0)
                empty = widget.grab().toImage()
                widget.set_fill(0.5)
                half = widget.grab().toImage()
                widget.set_fill(1.0)
                full = widget.grab().toImage()
                assert empty != half and half != full, 'Die Bildfüllung wird nicht gezeichnet.'
                widget.close()
            """)
            environment = dict(os.environ, QT_QPA_PLATFORM="offscreen")
            environment["PYTHONPATH"] = str(ROOT / "src")
            result = subprocess.run([sys.executable, "-c", code, str(module_path)],
                cwd=directory, env=environment, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
