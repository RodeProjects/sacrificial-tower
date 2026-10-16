"""Public and installer legal texts must match the application's offline view."""
from __future__ import annotations

import codecs
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from cooling_tower.legal_documents import DOCUMENTS, export_legal_documents, render_legal_document
from distribution_compliance import audit_bundle


class LegalDocumentExportTests(unittest.TestCase):
    def test_export_resolves_provider_values_without_changing_templates(self):
        originals = {path: path.read_bytes() for path in (ROOT / "legal").glob("*.md")}
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            export_legal_documents(destination, root=ROOT)
            for title, filename in DOCUMENTS.items():
                content = (destination / filename).read_text(encoding="utf-8")
                self.assertEqual(content, render_legal_document(title, root=ROOT))
                self.assertNotIn("{{", content)
                self.assertNotIn("[[", content)
            terms = (destination / "terms.txt").read_bytes()
            self.assertTrue(terms.startswith(codecs.BOM_UTF8))
            self.assertEqual(
                terms.decode("utf-8-sig"),
                (destination / "terms.md").read_text(encoding="utf-8"),
            )
            self.assertEqual(terms.decode("utf-8-sig").count("# Sacrificial Tower – Projektlizenz"), 1)
            self.assertIn("Wolfgang Florian Rode", terms.decode("utf-8-sig"))
        for path, original in originals.items():
            self.assertEqual(path.read_bytes(), original)

    def test_bad_template_does_not_replace_existing_public_texts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "legal").mkdir()
            shutil.copy2(ROOT / "config/legal_profile.json", root / "config/legal_profile.json")
            shutil.copy2(ROOT / "LICENSE.md", root / "LICENSE.md")
            for filename in DOCUMENTS.values():
                (root / "legal" / filename).write_text("{{unknown_provider_value}}", encoding="utf-8")
            destination = root / "public"
            destination.mkdir()
            (destination / "terms.md").write_bytes(b"previous valid publication")
            with self.assertRaisesRegex(ValueError, "Fehlende Anbieterangabe"):
                export_legal_documents(destination, root=root)
            self.assertEqual((destination / "terms.md").read_bytes(), b"previous valid publication")
            self.assertEqual([path.name for path in destination.iterdir()], ["terms.md"])

    def test_packaged_root_uses_its_own_profile_and_appends_license_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "legal", root / "legal")
            (root / "config").mkdir()
            shutil.copy2(ROOT / "config/legal_profile.json", root / "config/legal_profile.json")
            shutil.copy2(ROOT / "LICENSE.md", root / "legal/LICENSE.md")
            destination = root / "legal/published"
            export_legal_documents(destination, root=root)
            terms = render_legal_document("Lizenzbedingungen", root=root)
            self.assertEqual(terms.count("# Sacrificial Tower – Projektlizenz"), 1)
            self.assertEqual((destination / "terms.txt").read_text(encoding="utf-8-sig"), terms)

    def test_bundle_audit_rejects_an_outdated_installer_license(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory)
            root = bundle / "_internal"
            shutil.copytree(ROOT / "legal", root / "legal")
            (root / "config").mkdir()
            shutil.copy2(ROOT / "config/legal_profile.json", root / "config/legal_profile.json")
            shutil.copy2(ROOT / "LICENSE.md", root / "legal/LICENSE.md")
            # The synthetic bundle only needs the required files checked before
            # the changed installer text; no real DLL or source archive is used.
            for relative in (
                "notice-index.json", "binary-origins.json",
                "licenses/Qt/LGPL-3.0-only.txt", "licenses/Qt/GPL-3.0-only.txt",
                "licenses/Python-LICENSE.txt",
            ):
                path = root / "legal" / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"fixture")
            (bundle / "SacrificialTower.exe").write_bytes(b"fixture")
            export_legal_documents(root / "legal/published", root=root)
            (root / "legal/published/terms.txt").write_text("old terms", encoding="utf-8-sig")
            with self.assertRaisesRegex(ValueError, "Installer-Lizenztext fehlt oder ist veraltet"):
                audit_bundle(bundle)


if __name__ == "__main__":
    unittest.main()
