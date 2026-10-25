"""Stable export destinations shared by settings, controllers and dialogs."""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path


EXPORT_METHOD_LABELS = {
    "automatic": "Automatisch",
    "manual": "Manuell",
    "preprocessor": "Präprozessor",
}


def default_export_roots(base: str | Path) -> dict[str, str]:
    return {method: str(Path(base) / method) for method in EXPORT_METHOD_LABELS}


def normalize_export_roots(values: object) -> dict[str, str]:
    if not isinstance(values, Mapping):
        return {}
    return {
        method: value.strip()
        for method in EXPORT_METHOD_LABELS
        if isinstance(value := values.get(method), str)
        and value.strip() and not any(ord(char) < 32 for char in value)
    }
