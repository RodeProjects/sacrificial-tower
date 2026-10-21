"""Render shipped legal templates from one provider record; no network access."""
from __future__ import annotations

import json
import re
from pathlib import Path
from cooling_tower.runtime_paths import RESOURCE_ROOT

DOCUMENTS = {
    "Lizenzbedingungen": "terms.md",
    "Datenschutzerklärung": "privacy.md",
    "Drittanbieter-Lizenzen": "third_party.md",
}
PROJECT_LEGAL_FILES = ("LICENSE.md", "NOTICE")

DEVELOPMENT_PLACEHOLDER_TEXT = {
    "provider_postal_address": (
        "Anschrift für diese Entwicklungsversion noch nicht hinterlegt"
    ),
    "provider_additional_details": (
        "für diese Entwicklungsversion noch nicht abschließend hinterlegt"
    ),
    "support_retention_policy": (
        "für diese Entwicklungsversion noch nicht abschließend festgelegt; "
        "vor dem regulären Vertrieb nachzutragen"
    ),
}


def _is_unresolved_placeholder(value: str) -> bool:
    return bool(re.search(r"\[\[.*?\]\]", value))


def legal_profile(*, root: Path = RESOURCE_ROOT) -> dict[str, str]:
    profile = json.loads((root / "config" / "legal_profile.json").read_text(encoding="utf-8"))
    if not isinstance(profile, dict) or not all(isinstance(value, str) for value in profile.values()):
        raise ValueError("Ungültige Anbieterangaben")
    return profile


def _project_legal_text(root: Path, filename: str) -> str:
    path = root / filename
    if not path.is_file():
        path = root / "legal" / filename
    return path.read_text(encoding="utf-8")


def render_legal_document(title: str, *, root: Path = RESOURCE_ROOT) -> str:
    filename = DOCUMENTS[title]
    profile = legal_profile(root=root)
    template = (root / "legal" / filename).read_text(encoding="utf-8")
    if title == "Lizenzbedingungen":
        template += "\n\n---\n\n" + _project_legal_text(root, "LICENSE.md")
        template += "\n\n---\n\n## Urheber- und Herkunftshinweise (NOTICE)\n\n"
        template += _project_legal_text(root, "NOTICE")
    def substitute(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in profile or not isinstance(profile[key], str):
            raise ValueError(f"Fehlende Anbieterangabe: {key}")
        value = profile[key]
        if _is_unresolved_placeholder(value):
            if key not in DEVELOPMENT_PLACEHOLDER_TEXT:
                raise ValueError(f"Fehlende Anbieterangabe: {key}")
            return DEVELOPMENT_PLACEHOLDER_TEXT[key]
        return value
    return re.sub(r"\{\{([a-z_]+)\}\}", substitute, template)


def export_legal_documents(destination: Path, *, root: Path = RESOURCE_ROOT) -> None:
    """Write resolved copies for publication and the installer's license page.

    Keep the runtime templates separate: rendering an exported terms document
    again would otherwise append the project license twice.
    """
    documents = {
        filename: render_legal_document(title, root=root)
        for title, filename in DOCUMENTS.items()
    }
    documents.update({
        filename: _project_legal_text(root, filename)
        for filename in PROJECT_LEGAL_FILES
    })
    # Resolve everything before writing, so unknown or missing provider keys
    # cannot leave a partly updated set of public documents.
    destination.mkdir(parents=True, exist_ok=True)
    for filename, content in documents.items():
        (destination / filename).write_text(content, encoding="utf-8", newline="\n")
    # The BOM lets Inno Setup reliably recognize German UTF-8 text.
    (destination / "terms.txt").write_text(
        documents["terms.md"], encoding="utf-8-sig", newline="\n"
    )
