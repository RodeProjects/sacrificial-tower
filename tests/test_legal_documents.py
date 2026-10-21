"""Public and installer legal texts must match the application's offline view."""
from __future__ import annotations

import codecs
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from cooling_tower.legal_documents import DOCUMENTS, PROJECT_LEGAL_FILES, export_legal_documents, legal_profile, render_legal_document
from distribution_compliance import audit_bundle

# Full Apache text including its appendix, compared with apache.org on 2026-10-21.
# Whitespace is ignored so Git's line-ending conversion cannot alter this check.
APACHE_2_0_NORMALIZED_SHA256 = "0ffddef9e48f8a09aed5caf2d44f7ba1c1be2d9b8e0a6f693b1635b2d5566645"


class LegalDocumentExportTests(unittest.TestCase):
    def _prepare_synthetic_bundle(self, bundle: Path) -> Path:
        root = bundle / "_internal"
        shutil.copytree(ROOT / "legal", root / "legal")
        (root / "config").mkdir()
        shutil.copy2(ROOT / "config/legal_profile.json", root / "config/legal_profile.json")
        for filename in PROJECT_LEGAL_FILES:
            shutil.copy2(ROOT / filename, root / "legal" / filename)
        # No real DLL or source archive is needed for checks of legal texts.
        for relative in (
            "licenses/Qt/LGPL-3.0-only.txt", "licenses/Qt/GPL-3.0-only.txt",
            "licenses/Python-LICENSE.txt",
        ):
            path = root / "legal" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture")
        for filename in ("notice-index.json", "binary-origins.json"):
            (root / "legal" / filename).write_text("[]", encoding="utf-8")
        (bundle / "SacrificialTower.exe").write_bytes(b"fixture")
        export_legal_documents(root / "legal/published", root=root)
        return root

    def _audit_synthetic_bundle(self, bundle: Path) -> dict:
        # A complete audit can use empty dependency registries to isolate the
        # legal-text checks without downloading or inventing real Qt archives.
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            shutil.copytree(ROOT / "legal", source / "legal")
            (source / "config").mkdir()
            shutil.copy2(ROOT / "config/legal_profile.json", source / "config/legal_profile.json")
            for filename in PROJECT_LEGAL_FILES:
                shutil.copy2(ROOT / filename, source / filename)
            (source / "config/qt_sources.json").write_text('{"archives": []}', encoding="utf-8")
            (source / "config/dependency_artifacts.json").write_text('{"artifacts": []}', encoding="utf-8")
            with patch("distribution_compliance.ROOT", source):
                return audit_bundle(bundle)

    def test_project_license_is_the_unmodified_official_apache_2_0_text(self):
        text = (ROOT / "LICENSE.md").read_text(encoding="utf-8")
        digest = hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()
        self.assertEqual(digest, APACHE_2_0_NORMALIZED_SHA256)

    def test_bundle_audit_accepts_matching_legal_material(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory)
            self._prepare_synthetic_bundle(bundle)
            report = self._audit_synthetic_bundle(bundle)
            files = {entry["path"] for entry in report["files"]}
            self.assertIn("_internal/legal/NOTICE", files)
            self.assertIn("_internal/legal/published/LICENSE.md", files)

    def test_bundle_audit_rejects_outdated_templates_even_with_matching_exports(self):
        for filename in (*DOCUMENTS.values(), "source_build_notes.md"):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as directory:
                bundle = Path(directory)
                root = self._prepare_synthetic_bundle(bundle)
                template = root / "legal" / filename
                template.write_text(
                    template.read_text(encoding="utf-8") + "\nCommercial redistribution is prohibited.\n",
                    encoding="utf-8",
                )
                export_legal_documents(root / "legal/published", root=root)
                with self.assertRaisesRegex(ValueError, "im Paket fehlt oder weicht vom Quellstand ab"):
                    self._audit_synthetic_bundle(bundle)

    def test_bundle_audit_rejects_an_outdated_or_missing_provider_profile(self):
        for missing in (False, True):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as directory:
                bundle = Path(directory)
                root = self._prepare_synthetic_bundle(bundle)
                profile = root / "config/legal_profile.json"
                if missing:
                    profile.unlink()
                else:
                    values = json.loads(profile.read_text(encoding="utf-8"))
                    values["distribution_terms"] = "Commercial redistribution is prohibited."
                    profile.write_text(json.dumps(values), encoding="utf-8")
                    export_legal_documents(root / "legal/published", root=root)
                with self.assertRaisesRegex(ValueError, "config/legal_profile.json"):
                    self._audit_synthetic_bundle(bundle)

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
            for filename in PROJECT_LEGAL_FILES:
                original = (ROOT / filename).read_text(encoding="utf-8")
                self.assertEqual((destination / filename).read_text(encoding="utf-8"), original)
                self.assertEqual(terms.decode("utf-8-sig").count(original), 1)
            self.assertIn("Wolfgang Florian Rode", terms.decode("utf-8-sig"))
        for path, original in originals.items():
            self.assertEqual(path.read_bytes(), original)

    def test_bad_template_does_not_replace_existing_public_texts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "legal").mkdir()
            shutil.copy2(ROOT / "config/legal_profile.json", root / "config/legal_profile.json")
            for filename in PROJECT_LEGAL_FILES:
                shutil.copy2(ROOT / filename, root / filename)
            for filename in DOCUMENTS.values():
                (root / "legal" / filename).write_text("{{unknown_provider_value}}", encoding="utf-8")
            destination = root / "public"
            destination.mkdir()
            (destination / "terms.md").write_bytes(b"previous valid publication")
            with self.assertRaisesRegex(ValueError, "Fehlende Anbieterangabe"):
                export_legal_documents(destination, root=root)
            self.assertEqual((destination / "terms.md").read_bytes(), b"previous valid publication")
            self.assertEqual([path.name for path in destination.iterdir()], ["terms.md"])

    def test_support_terms_are_shared_by_app_installer_and_privacy(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            export_legal_documents(destination, root=ROOT)
            terms = (destination / "terms.txt").read_text(encoding="utf-8-sig")
            self.assertEqual(terms, render_legal_document("Lizenzbedingungen", root=ROOT))
            self.assertIn("## Freiwillige Unterstützung über PayPal", terms)
            self.assertIn("sind 3,50 €, 5 €, 10 €, 15 € und 20 €", terms)
            self.assertIn("von 2,50 € bis 50,00 € pro Zahlung", terms)
            self.assertIn("5 € sind beim erstmaligen Öffnen als unverbindlicher", terms)
            self.assertIn("unverbindlicher, frei änderbarer Vorschlag", terms)
            self.assertIn(legal_profile(root=ROOT)["provider_name"], terms)
            self.assertIn("keine steuerbegünstigte Spende", terms)
            self.assertIn("keine Zahlung aus", terms)
            privacy = (destination / "privacy.md").read_text(encoding="utf-8")
            self.assertIn("## Freiwillige Unterstützung und PayPal", privacy)
            self.assertIn("Art. 6 Abs. 1 lit. b DSGVO", privacy)
            self.assertIn("acht Jahre", privacy)

    def test_packaged_root_uses_its_own_profile_and_appends_license_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "legal", root / "legal")
            (root / "config").mkdir()
            shutil.copy2(ROOT / "config/legal_profile.json", root / "config/legal_profile.json")
            for filename in PROJECT_LEGAL_FILES:
                shutil.copy2(ROOT / filename, root / "legal" / filename)
            destination = root / "legal/published"
            export_legal_documents(destination, root=root)
            terms = render_legal_document("Lizenzbedingungen", root=root)
            for filename in PROJECT_LEGAL_FILES:
                original = (ROOT / filename).read_text(encoding="utf-8")
                self.assertEqual(terms.count(original), 1)
                self.assertEqual((destination / filename).read_text(encoding="utf-8"), original)
            self.assertEqual((destination / "terms.txt").read_text(encoding="utf-8-sig"), terms)

    def test_bundle_audit_rejects_an_outdated_installer_license(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory)
            root = self._prepare_synthetic_bundle(bundle)
            (root / "legal/published/terms.txt").write_text("old terms", encoding="utf-8-sig")
            with self.assertRaisesRegex(ValueError, "Installer-Lizenztext fehlt oder ist veraltet"):
                audit_bundle(bundle)

    def test_bundle_audit_requires_the_license_and_notice(self):
        for filename in PROJECT_LEGAL_FILES:
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as directory:
                bundle = Path(directory)
                root = self._prepare_synthetic_bundle(bundle)
                (root / "legal" / filename).unlink()
                with self.assertRaisesRegex(ValueError, "Erforderlicher Lizenztext fehlt"):
                    audit_bundle(bundle)

    def test_bundle_audit_rejects_a_consistently_outdated_packaged_license_or_notice(self):
        for filename in PROJECT_LEGAL_FILES:
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as directory:
                bundle = Path(directory)
                root = self._prepare_synthetic_bundle(bundle)
                (root / "legal" / filename).write_text("outdated source license", encoding="utf-8")
                export_legal_documents(root / "legal/published", root=root)
                with self.assertRaisesRegex(ValueError, "im Paket fehlt oder weicht vom Quellstand ab"):
                    audit_bundle(bundle)

    def test_bundle_audit_rejects_missing_or_stale_exported_license_and_notice(self):
        for filename in PROJECT_LEGAL_FILES:
            for missing in (False, True):
                with self.subTest(filename=filename, missing=missing), tempfile.TemporaryDirectory() as directory:
                    bundle = Path(directory)
                    root = self._prepare_synthetic_bundle(bundle)
                    path = root / "legal/published" / filename
                    if missing:
                        path.unlink()
                    else:
                        path.write_text("outdated legal text", encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "Lizenz-/Herkunftstext fehlt oder weicht vom Paket ab"):
                        audit_bundle(bundle)

    def test_missing_notice_does_not_replace_existing_public_texts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._prepare_synthetic_bundle(Path(directory))
            (root / "legal/NOTICE").unlink()
            destination = root / "legal/published"
            originals = {path: path.read_bytes() for path in destination.iterdir()}
            with self.assertRaises(FileNotFoundError):
                export_legal_documents(destination, root=root)
            self.assertEqual({path: path.read_bytes() for path in destination.iterdir()}, originals)


if __name__ == "__main__":
    unittest.main()
