"""Build-time inventory and explicit Qt distribution policy (standard library only)."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cooling_tower.legal_documents import DOCUMENTS, PROJECT_LEGAL_FILES, export_legal_documents, render_legal_document

QT_LIBRARIES = frozenset({"qt6core.dll", "qt6gui.dll", "qt6widgets.dll", "qt6network.dll", "qt6svg.dll", "qt6opengl.dll"})
QT_PLUGINS = frozenset({
    "qwindows.dll", "qoffscreen.dll", "qminimal.dll", "qmodernwindowsstyle.dll",
    "qsvgicon.dll", "qsvg.dll", "qgif.dll", "qico.dll", "qjpeg.dll",
    "qschannelbackend.dll", "qcertonlybackend.dll", "qnetworklistmanager.dll",
})
UNUSED_QT_PREFIXES = ("qt6qml", "qt6quick", "qt6virtualkeyboard", "qt6pdf")


def isolate_binary_search_path() -> None:
    """Do not resolve DLLs from unrelated applications inherited through PATH."""
    windows = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    roots = [Path(sys.prefix), Path(sys.prefix) / "Scripts", Path(sys.base_prefix),
             Path(sys.base_prefix) / "DLLs", windows / "System32", windows]
    for package, folder in (("PySide6_Essentials", "PySide6"), ("shiboken6", "shiboken6"), ("numpy", "numpy.libs")):
        roots.append(Path(metadata.distribution(package).locate_file(folder)))
    os.environ["PATH"] = os.pathsep.join(str(path.resolve()) for path in roots if path.is_dir())


def binary_origins(binaries: list) -> list[dict]:
    """Reject host-tool DLLs and record provenance without personal absolute paths."""
    qt_root = Path(metadata.distribution("PySide6_Essentials").locate_file("PySide6")).resolve()
    allowed = [("python-environment", Path(sys.prefix).resolve()),
               ("python-runtime", Path(sys.base_prefix).resolve()),
               ("project", (ROOT / "src").resolve()),
               ("windows", Path(os.environ.get("SystemRoot", r"C:\Windows")).resolve())]
    records = []
    for destination, origin, kind in binaries:
        source = Path(origin).resolve()
        normalized = destination.replace("\\", "/").lower()
        if (source.name.lower().startswith("qt6") or "pyside6/" in normalized) and not source.is_relative_to(qt_root):
            raise ValueError(f"Qt-Binärdatei stammt nicht aus dem fixierten Wheel: {destination}: {source}")
        owner = next(((label, root) for label, root in allowed if source.is_relative_to(root)), None)
        if owner is None:
            raise ValueError(f"Fremde Binärdatei aus nicht freigegebenem Suchpfad: {destination}: {source}")
        with source.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        label, root = owner
        records.append({"file": destination.replace("\\", "/"), "kind": kind,
                        "origin": label + "/" + source.relative_to(root).as_posix(), "sha256": digest})
    return records


def copy_notice(source: Path, destination: Path, *, component: str, origin: str, index: list) -> None:
    """Keep Windows installer paths short while retaining original provenance."""
    identifier = hashlib.sha256(origin.encode("utf-8")).hexdigest()[:16]
    target = destination / "licenses" / component / (identifier + "-" + source.name[-72:])
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    index.append({"component": component, "origin": origin,
                  "file": target.relative_to(destination).as_posix(),
                  "sha256": hashlib.sha256(source.read_bytes()).hexdigest()})


def keep_qt_binary(destination: str) -> bool:
    name = destination.replace("\\", "/").lower()
    basename = name.rsplit("/", 1)[-1]
    if "pyside6/plugins/" in name:
        return basename in QT_PLUGINS
    if basename.startswith(UNUSED_QT_PREFIXES) or basename == "opengl32sw.dll":
        return False
    if "pyside6/" in name and basename.endswith(".pyd") and basename.startswith("qt"):
        if basename not in {library.replace("qt6", "qt", 1).replace(".dll", ".pyd") for library in QT_LIBRARIES}:
            raise ValueError(f"Nicht freigegebenes Qt-Python-Modul: {destination}")
    if basename.startswith("qt6") and basename.endswith(".dll") and basename not in QT_LIBRARIES:
        raise ValueError(f"Nicht lizenzrechtlich freigegebenes Qt-Modul: {destination}")
    return True


def prepare_legal_material(destination: Path) -> None:
    destination = destination.resolve()
    if destination != (ROOT / "build/legal").resolve():
        raise ValueError("Lizenz-Staging ist ausschließlich unter build/legal zulässig.")
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / "legal", destination, dirs_exist_ok=True)
    for filename in PROJECT_LEGAL_FILES:
        shutil.copy2(ROOT / filename, destination / filename)
    export_legal_documents(destination / "published", root=ROOT)
    notice_index = []
    source_registry = json.loads((ROOT / "config/qt_sources.json").read_text(encoding="utf-8"))
    source_root = ROOT / "build/qt-sources"
    for entry in source_registry["archives"]:
        archive = source_root / entry["filename"]
        if not archive.is_file():
            raise ValueError("Qt-Quellmaterial fehlt: zuerst scripts/prepare_qt_sources.py ausführen.")
        with archive.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != entry["sha256"]:
                raise ValueError(f"Verändertes Qt-Quellarchiv: {archive.name}")
        (destination / "sources").mkdir(exist_ok=True)
        shutil.copy2(archive, destination / "sources" / archive.name)
    for source in sorted((source_root / "notices").rglob("*")):
        if source.is_file():
            copy_notice(source, destination, component="Qt-source-notices",
                        origin=source.relative_to(source_root / "notices").as_posix(), index=notice_index)
    shutil.copy2(ROOT / "config/qt_sources.json", destination / "sources/qt_sources.json")
    artifacts = json.loads((ROOT / "config/dependency_artifacts.json").read_text(encoding="utf-8"))["artifacts"]
    for artifact in artifacts:
        package = metadata.distribution(artifact["name"])
        if package.version != artifact["version"]:
            raise ValueError(f"Abweichende Build-Abhängigkeit: {artifact['name']} {package.version}")
        for file in package.files or ():
            parts = file.parts
            if file.suffix.lower() in {".py", ".pyc", ".pyd"}:
                continue
            if any(part.lower() in {"licenses", "license"} for part in parts) or file.name.lower().startswith(("license", "copying", "notice")):
                source = Path(package.locate_file(file))
                if source.is_file():
                    copy_notice(source, destination, component=artifact["name"],
                                origin=str(file), index=notice_index)
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise ValueError("Lizenztext der gebündelten Python-Laufzeit fehlt.")
    shutil.copy2(python_license, destination / "licenses/Python-LICENSE.txt")
    (destination / "notice-index.json").write_text(json.dumps(notice_index, indent=2) + "\n", encoding="utf-8")
    (destination / "dependency-artifacts.json").write_text(json.dumps(artifacts, indent=2) + "\n", encoding="utf-8")


def audit_bundle(root: Path) -> dict:
    if not root.is_dir() or not (root / "SacrificialTower.exe").is_file():
        raise ValueError("Kein vollständiges Anwendungspaket vorhanden.")
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if not keep_qt_binary(relative):
            raise ValueError(f"Nicht erlaubter Qt-Lieferumfang: {relative}")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        files.append({"path": relative, "bytes": path.stat().st_size, "sha256": digest})
    for required in (*PROJECT_LEGAL_FILES, "terms.md", "privacy.md", "third_party.md", "source_build_notes.md", "notice-index.json", "binary-origins.json", "licenses/Qt/LGPL-3.0-only.txt", "licenses/Qt/GPL-3.0-only.txt", "licenses/Python-LICENSE.txt"):
        if not (root / "_internal/legal" / required).is_file():
            raise ValueError(f"Erforderlicher Lizenztext fehlt: {required}")
    resource_root = root / "_internal"
    source_files = {
        Path("legal") / filename: ROOT / filename
        for filename in PROJECT_LEGAL_FILES
    }
    source_files.update({
        Path("legal") / filename: ROOT / "legal" / filename
        for filename in (*DOCUMENTS.values(), "source_build_notes.md")
    })
    source_files[Path("config/legal_profile.json")] = ROOT / "config/legal_profile.json"
    for relative, source in source_files.items():
        packaged = resource_root / relative
        if (
            not packaged.is_file()
            or packaged.read_text(encoding="utf-8") != source.read_text(encoding="utf-8")
        ):
            raise ValueError(f"Rechtstext/Anbieterprofil im Paket fehlt oder weicht vom Quellstand ab: {relative.as_posix()}")
    published = resource_root / "legal/published"
    for title, filename in DOCUMENTS.items():
        expected = render_legal_document(title, root=resource_root)
        path = published / filename
        if not path.is_file() or path.read_text(encoding="utf-8") != expected:
            raise ValueError(f"Aufgelöster Rechtstext fehlt oder ist veraltet: {filename}")
    terms_path = published / "terms.txt"
    if (
        not terms_path.is_file()
        or terms_path.read_text(encoding="utf-8-sig")
        != render_legal_document("Lizenzbedingungen", root=resource_root)
    ):
        raise ValueError("Installer-Lizenztext fehlt oder ist veraltet.")
    for filename in PROJECT_LEGAL_FILES:
        path = published / filename
        if (
            not path.is_file()
            or path.read_text(encoding="utf-8")
            != (resource_root / "legal" / filename).read_text(encoding="utf-8")
        ):
            raise ValueError(f"Veröffentlichter Lizenz-/Herkunftstext fehlt oder weicht vom Paket ab: {filename}")
    for entry in json.loads((ROOT / "config/qt_sources.json").read_text(encoding="utf-8"))["archives"]:
        expected = "_internal/legal/sources/" + entry["filename"]
        if not any(item["path"] == expected and item["sha256"] == entry["sha256"] for item in files):
            raise ValueError(f"Qt-Quellmaterial fehlt oder wurde verändert: {expected}")
    for entry in json.loads((root / "_internal/legal/notice-index.json").read_text(encoding="utf-8")):
        expected = "_internal/legal/" + entry["file"]
        if not any(item["path"] == expected and item["sha256"] == entry["sha256"] for item in files):
            raise ValueError(f"Lizenznachweis fehlt oder wurde verändert: {entry['origin']}")
    for entry in json.loads((root / "_internal/legal/binary-origins.json").read_text(encoding="utf-8")):
        expected = "_internal/" + entry["file"]
        if not any(item["path"] == expected and item["sha256"] == entry["sha256"] for item in files):
            raise ValueError(f"Binärdatei weicht vom Buildnachweis ab: {expected}")
    return {"schema_version": 1, "python": sys.version, "files": files,
            "dependency_artifacts": json.loads((ROOT / "config/dependency_artifacts.json").read_text(encoding="utf-8")),
            "legal_release_approval": "separate check_release_readiness.py required"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit_bundle(args.bundle)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Lieferumfang geprüft: {len(report['files'])} Dateien.")
