"""Stable export destinations shared by settings, controllers and dialogs."""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from cooling_tower.legacy_method_ids import LEGACY_POSTPROCESSOR_ID


EXPORT_METHOD_LABELS = {
    "automatic": "Iterativ",
    "manual": "Manuell",
    "postprocessor": "Postprozessor",
}
EXPORT_FOLDER_NAMES = {
    "automatic": "exports_automatic_mode",
    "manual": "exports_manual_mode",
    "postprocessor": "exports_postprocessor",
}
LEGACY_EXPORT_FOLDER_NAMES = {
    "automatic": ("automatic",),
    "manual": ("manual",),
    "postprocessor": ("postprocessor", LEGACY_POSTPROCESSOR_ID),
}


def default_export_roots(base: str | Path) -> dict[str, str]:
    return {method: str(Path(base) / name) for method, name in EXPORT_FOLDER_NAMES.items()}


def legacy_export_roots(root: str | Path, method: str) -> tuple[Path, ...]:
    """Read earlier standard exports without moving or merging user files."""
    path = Path(root)
    names = (EXPORT_FOLDER_NAMES[method], *LEGACY_EXPORT_FOLDER_NAMES[method])
    if path.name.casefold() not in names:
        return ()
    return tuple(
        path.with_name(name) for name in names
        if name.casefold() != path.name.casefold()
    )


def migrate_standard_export_roots(
    values: object, *, default_base: Path | None = None,
) -> dict[str, str]:
    """Recognize the shared standard layout without rewriting custom targets."""
    roots = normalize_export_roots(values)
    result = dict(roots)
    for method, value in roots.items():
        path = Path(value)
        if path.name.casefold() not in LEGACY_EXPORT_FOLDER_NAMES[method]:
            continue
        known_default = default_base is not None and path.parent == default_base
        shared_layout = any(
            other != method and Path(candidate).parent == path.parent
            and Path(candidate).name.casefold() in (
                EXPORT_FOLDER_NAMES[other], *LEGACY_EXPORT_FOLDER_NAMES[other],
            )
            for other, candidate in roots.items()
        )
        if known_default or shared_layout:
            result[method] = str(path.with_name(EXPORT_FOLDER_NAMES[method]))
    return result


def normalize_export_roots(values: object) -> dict[str, str]:
    if not isinstance(values, Mapping):
        return {}
    if "postprocessor" not in values and LEGACY_POSTPROCESSOR_ID in values:
        values = {**values, "postprocessor": values[LEGACY_POSTPROCESSOR_ID]}
    return {
        method: value.strip()
        for method in EXPORT_METHOD_LABELS
        if isinstance(value := values.get(method), str)
        and value.strip() and not any(ord(char) < 32 for char in value)
    }
