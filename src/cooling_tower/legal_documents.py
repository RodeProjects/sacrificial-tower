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


def render_legal_document(title: str, *, root: Path = RESOURCE_ROOT) -> str:
    filename = DOCUMENTS[title]
    profile = legal_profile(root=root)
    template = (root / "legal" / filename).read_text(encoding="utf-8")
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
