"""Fetch pinned upstream source archives and preserve their license evidence.

Downloads are build-time only. Archives are never executed or broadly extracted.
An upstream archive does not by itself prove correspondence with a binary wheel;
that remains part of the documented release review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import ssl
import tarfile
import urllib.request

import truststore

ROOT = Path(__file__).resolve().parents[1]


def prepare(destination: Path) -> None:
    registry = json.loads((ROOT / "config/qt_sources.json").read_text(encoding="utf-8"))
    destination.mkdir(parents=True, exist_ok=True)
    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    for entry in registry["archives"]:
        target = destination / entry["filename"]
        if not target.is_file():
            temporary = target.with_suffix(target.suffix + ".download")
            try:
                with urllib.request.urlopen(entry["url"], context=context, timeout=60) as response, temporary.open("wb") as stream:
                    shutil.copyfileobj(response, stream)
                with temporary.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                if digest != entry["sha256"]:
                    raise ValueError(f"Quellarchiv-Prüfsumme stimmt nicht: {entry['filename']}")
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        with target.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != entry["sha256"]:
                raise ValueError(f"Vorhandenes Quellarchiv ist verändert: {target}")
        print(f"Geprüft: {target.name}", flush=True)
        with tarfile.open(target, "r:xz") as archive:
            members = {member.name: member for member in archive if member.isfile()}
            selected = {name for name in members if PurePosixPath(name).name.lower().startswith(("license", "copying", "notice", "qt_attribution")) or "/LICENSES/" in name}
            for name in tuple(selected):
                if PurePosixPath(name).name != "qt_attribution.json":
                    continue
                with archive.extractfile(members[name]) as stream:
                    attribution = json.load(stream, strict=False)
                for item in attribution if isinstance(attribution, list) else [attribution]:
                    for field in ("LicenseFile", "CopyrightFile"):
                        value = item.get(field, "")
                        for filename in value if isinstance(value, list) else [value]:
                            if not filename:
                                continue
                            # Resolve only within the archive's own member names.
                            parts = list(PurePosixPath(name).parent.parts)
                            for part in PurePosixPath(filename).parts:
                                if part == "..":
                                    if parts:
                                        parts.pop()
                                elif part != ".":
                                    parts.append(part)
                            referenced = "/".join(parts)
                            if referenced in members:
                                selected.add(referenced)
            for name in sorted(selected):
                relative = PurePosixPath(name)
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError("Unsicherer Pfad im Quellarchiv")
                output = destination / "notices" / Path(*relative.parts)
                output.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(members[name]) as source, output.open("wb") as stream:
                    shutil.copyfileobj(source, stream)
    shutil.copy2(ROOT / "config/qt_sources.json", destination / "qt_sources.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "build/qt-sources")
    prepare(parser.parse_args().output)
