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


def legal_profile(*, root: Path = RESOURCE_ROOT) -> dict[str, str]:
    profile = json.loads((root / "config" / "legal_profile.json").read_text(encoding="utf-8"))
    if not isinstance(profile, dict) or not all(isinstance(value, str) for value in profile.values()):
        raise ValueError("Ungültige Anbieterangaben")
    return profile


def render_legal_document(title: str, *, root: Path = RESOURCE_ROOT) -> str:
    filename = DOCUMENTS[title]
    profile = legal_profile(root=root)
    template = (root / "legal" / filename).read_text(encoding="utf-8")
    def substitute(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in profile or not isinstance(profile[key], str):
            raise ValueError(f"Fehlende Anbieterangabe: {key}")
        return profile[key]
    return re.sub(r"\{\{([a-z_]+)\}\}", substitute, template)
