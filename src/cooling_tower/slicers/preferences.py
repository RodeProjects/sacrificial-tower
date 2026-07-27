from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from cooling_tower.persistence import VersionedDocumentError, VersionedJsonStore

from cooling_tower.slicers.models import (
    SLICER_PREFERENCES_SCHEMA_VERSION,
    SlicerPreferences,
)


def _migrate_preferences_0_to_1(payload: dict[str, Any]) -> dict[str, Any]:
    """Adopt preferences written before an explicit schema was required."""

    return dict(payload)


def _normalize_preferences(payload: dict[str, Any]) -> dict[str, Any]:
    raw_paths = payload.get("confirmed_paths", ())
    if not isinstance(raw_paths, (list, tuple)):
        raw_paths = ()
    confirmed_paths = [
        value
        for value in raw_paths
        if isinstance(value, str) and value.strip()
    ]
    selected = payload.get("last_selected_key")
    return {
        "confirmed_paths": confirmed_paths,
        "last_selected_key": (
            selected if isinstance(selected, str) and selected else None
        ),
    }


class SlicerPreferenceStore:
    """Persist only user-confirmed executables and the last selection."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.last_load_warning: str | None = None
        self.last_migration_backup: Path | None = None
        self._document = VersionedJsonStore(
            self.path,
            schema_key="schema_version",
            current_version=SLICER_PREFERENCES_SCHEMA_VERSION,
            migrations={0: _migrate_preferences_0_to_1},
            normalizer=_normalize_preferences,
            document_name="Die gespeicherten Slicer-Einstellungen",
        )

    def load(self) -> SlicerPreferences:
        self.last_load_warning = None
        self.last_migration_backup = None
        if not self.path.is_file():
            return SlicerPreferences()
        try:
            result = self._document.load()
            payload = result.payload
            self.last_migration_backup = result.backup_path
            raw_paths = payload.get("confirmed_paths", ())
            paths = tuple(
                Path(value).expanduser()
                for value in raw_paths
                if isinstance(value, str) and value.strip()
            )
            selected = payload.get("last_selected_key")
            return SlicerPreferences(
                schema_version=SLICER_PREFERENCES_SCHEMA_VERSION,
                confirmed_paths=paths,
                last_selected_key=(
                    str(selected) if selected is not None else None
                ),
            )
        except (OSError, ValueError, TypeError, VersionedDocumentError) as error:
            self.last_load_warning = (
                "Die gespeicherten Slicer-Einstellungen konnten nicht sicher "
                f"geladen werden: {error} Die Originaldatei bleibt unverändert."
            )
            return SlicerPreferences()

    def confirm_path(self, path: str | Path) -> SlicerPreferences:
        current = self.load()
        resolved = Path(path).expanduser().resolve()
        paths = list(current.confirmed_paths)
        if not any(
            str(existing.resolve()).casefold() == str(resolved).casefold()
            for existing in paths
        ):
            paths.append(resolved)
        updated = SlicerPreferences(
            confirmed_paths=tuple(paths),
            last_selected_key=current.last_selected_key,
        )
        self.save(updated)
        return updated

    def remove_paths(self, paths: set[Path]) -> SlicerPreferences:
        current = self.load()
        rejected = {str(path.expanduser().resolve()).casefold() for path in paths}
        retained = tuple(
            path
            for path in current.confirmed_paths
            if str(path.expanduser().resolve()).casefold() not in rejected
        )
        updated = SlicerPreferences(
            confirmed_paths=retained,
            last_selected_key=current.last_selected_key,
        )
        self.save(updated)
        return updated

    def set_last_selected(self, identity_key: str | None) -> SlicerPreferences:
        current = self.load()
        updated = SlicerPreferences(
            confirmed_paths=current.confirmed_paths,
            last_selected_key=identity_key,
        )
        self.save(updated)
        return updated

    def save(self, preferences: SlicerPreferences) -> Path:
        payload = {
            "schema_version": SLICER_PREFERENCES_SCHEMA_VERSION,
            "confirmed_paths": [
                str(path.expanduser().resolve())
                for path in preferences.confirmed_paths
            ],
            "last_selected_key": preferences.last_selected_key,
        }
        return self._document.save(payload)
