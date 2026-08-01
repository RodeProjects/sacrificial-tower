from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from cooling_tower.persistence import VersionedDocumentError, VersionedJsonStore

from cooling_tower.slicers.models import (
    ProfileRecord,
    ProfileSelectionReference,
    SLICER_PREFERENCES_SCHEMA_VERSION,
    SlicerProfileSelections,
    SlicerPreferences,
)


_PROFILE_ROLES = ("machine", "process", "filament")
_MAX_REMEMBERED_SLICERS = 128
_MAX_IDENTITY_LENGTH = 4096
_MAX_PROFILE_ID_LENGTH = 1024
_MAX_PROFILE_PATH_LENGTH = 32767


def _migrate_preferences_0_to_1(payload: dict[str, Any]) -> dict[str, Any]:
    """Adopt preferences written before an explicit schema was required."""

    return dict(payload)


def _migrate_preferences_1_to_2(payload: dict[str, Any]) -> dict[str, Any]:
    """Add per-slicer profile choices without inferring historic selections."""

    migrated = dict(payload)
    migrated.setdefault("profile_selections", {})
    return migrated


def _normalize_profile_reference(value: Any) -> dict[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    profile_id = value.get("profile_id")
    if not isinstance(profile_id, str):
        return None
    profile_id = profile_id.strip()
    if not profile_id or len(profile_id) > _MAX_PROFILE_ID_LENGTH:
        return None
    result = {"profile_id": profile_id}
    path = value.get("path")
    if (
        isinstance(path, str)
        and path.strip()
        and len(path) <= _MAX_PROFILE_PATH_LENGTH
    ):
        result["path"] = path.strip()
    return result


def _normalize_profile_selections(
    value: Any,
) -> dict[str, dict[str, dict[str, str]]]:
    if not isinstance(value, Mapping):
        return {}
    normalized: dict[str, dict[str, dict[str, str]]] = {}
    for raw_identity, raw_roles in value.items():
        if len(normalized) >= _MAX_REMEMBERED_SLICERS:
            break
        if (
            not isinstance(raw_identity, str)
            or not raw_identity.strip()
            or len(raw_identity) > _MAX_IDENTITY_LENGTH
            or not isinstance(raw_roles, Mapping)
        ):
            continue
        roles: dict[str, dict[str, str]] = {}
        for role in _PROFILE_ROLES:
            reference = _normalize_profile_reference(raw_roles.get(role))
            if reference is not None:
                roles[role] = reference
        if roles:
            normalized[raw_identity.strip()] = roles
    return normalized


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
        "profile_selections": _normalize_profile_selections(
            payload.get("profile_selections")
        ),
    }


class SlicerPreferenceStore:
    """Persist user-confirmed slicers and explicit per-slicer profile choices."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.last_load_warning: str | None = None
        self.last_migration_backup: Path | None = None
        self._document = VersionedJsonStore(
            self.path,
            schema_key="schema_version",
            current_version=SLICER_PREFERENCES_SCHEMA_VERSION,
            migrations={
                0: _migrate_preferences_0_to_1,
                1: _migrate_preferences_1_to_2,
            },
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
            profile_selections = self._deserialize_profile_selections(
                payload.get("profile_selections")
            )
            return SlicerPreferences(
                schema_version=SLICER_PREFERENCES_SCHEMA_VERSION,
                confirmed_paths=paths,
                last_selected_key=(
                    str(selected) if selected is not None else None
                ),
                profile_selections=profile_selections,
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
            profile_selections=current.profile_selections,
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
            profile_selections=current.profile_selections,
        )
        self.save(updated)
        return updated

    def set_last_selected(self, identity_key: str | None) -> SlicerPreferences:
        current = self.load()
        updated = SlicerPreferences(
            confirmed_paths=current.confirmed_paths,
            last_selected_key=identity_key,
            profile_selections=current.profile_selections,
        )
        self.save(updated)
        return updated

    def set_profile_selection(
        self,
        identity_key: str,
        role: str,
        profile: ProfileRecord,
    ) -> SlicerPreferences:
        identity_key = str(identity_key).strip()
        normalized_role = str(role).casefold()
        if not identity_key or len(identity_key) > _MAX_IDENTITY_LENGTH:
            raise ValueError("A valid slicer identity is required.")
        if normalized_role not in _PROFILE_ROLES:
            raise ValueError(f"Unsupported profile role: {role}")

        current = self.load()
        selections = dict(current.profile_selections)
        existing = selections.get(identity_key, SlicerProfileSelections())
        values = existing.as_mapping()
        values[normalized_role] = ProfileSelectionReference(
            profile_id=profile.profile_id,
            path=profile.path,
        )
        selections[identity_key] = SlicerProfileSelections(
            machine=values.get("machine"),
            process=values.get("process"),
            filament=values.get("filament"),
        )
        updated = SlicerPreferences(
            confirmed_paths=current.confirmed_paths,
            last_selected_key=current.last_selected_key,
            profile_selections=selections,
        )
        self.save(updated)
        return updated

    def profile_selections_for(
        self,
        identity_key: str,
    ) -> dict[str, ProfileSelectionReference]:
        selections = self.load().profile_selections.get(identity_key)
        return selections.as_mapping() if selections is not None else {}

    def save(self, preferences: SlicerPreferences) -> Path:
        payload = {
            "schema_version": SLICER_PREFERENCES_SCHEMA_VERSION,
            "confirmed_paths": [
                str(path.expanduser().resolve())
                for path in preferences.confirmed_paths
            ],
            "last_selected_key": preferences.last_selected_key,
            "profile_selections": {
                identity_key: {
                    role: {
                        "profile_id": reference.profile_id,
                        **(
                            {"path": str(reference.path)}
                            if reference.path is not None
                            else {}
                        ),
                    }
                    for role, reference in selections.as_mapping().items()
                }
                for identity_key, selections in sorted(
                    preferences.profile_selections.items()
                )
                if selections.as_mapping()
            },
        }
        return self._document.save(payload)

    @staticmethod
    def _deserialize_profile_selections(
        value: Any,
    ) -> dict[str, SlicerProfileSelections]:
        normalized = _normalize_profile_selections(value)
        result: dict[str, SlicerProfileSelections] = {}
        for identity_key, roles in normalized.items():
            references = {
                role: ProfileSelectionReference(
                    profile_id=reference["profile_id"],
                    path=reference.get("path"),
                )
                for role, reference in roles.items()
            }
            result[identity_key] = SlicerProfileSelections(
                machine=references.get("machine"),
                process=references.get("process"),
                filament=references.get("filament"),
            )
        return result
