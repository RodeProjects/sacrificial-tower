from __future__ import annotations

import json
from pathlib import Path

from cooling_tower.slicers.models import (
    SLICER_PREFERENCES_SCHEMA_VERSION,
    SlicerPreferences,
)


class SlicerPreferenceStore:
    """Persist only user-confirmed executables and the last selection."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> SlicerPreferences:
        if not self.path.is_file():
            return SlicerPreferences()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return SlicerPreferences()
            schema = int(payload.get("schema_version", 1))
            if schema > SLICER_PREFERENCES_SCHEMA_VERSION:
                return SlicerPreferences()
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
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SLICER_PREFERENCES_SCHEMA_VERSION,
            "confirmed_paths": [
                str(path.expanduser().resolve())
                for path in preferences.confirmed_paths
            ],
            "last_selected_key": preferences.last_selected_key,
        }
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)
        return self.path.resolve()
