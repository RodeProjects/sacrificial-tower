from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from cooling_tower.slicers.adapter import SlicerAdapter
from cooling_tower.slicers.models import (
    ProfileKind,
    ProfileRecord,
    SlicerInstallation,
)
from cooling_tower.slicers.profile_models import (
    PROFILE_INVENTORY_SCHEMA_VERSION,
    ProfileFileState,
    ProfileInventory,
    ProfileRole,
    ResolvedProfile,
    stable_json_fingerprint,
)


_PROFILE_SUFFIXES = {".json", ".ini", ".cfg"}


def profile_record_key(record: ProfileRecord) -> tuple[str, str]:
    section = str(record.metadata.get("section", ""))
    return str(record.path).casefold(), section.casefold()


def role_for_profile(
    record: ProfileRecord,
    values: Mapping[str, Any] | None = None,
) -> ProfileRole:
    if record.kind is ProfileKind.MACHINE:
        candidate = values or record.metadata
        variant = candidate.get("printer_variant")
        if variant not in (None, "", (), []):
            return ProfileRole.MACHINE_VARIANT
        return ProfileRole.MACHINE_MODEL
    if record.kind in {ProfileKind.PROCESS, ProfileKind.QUALITY}:
        return ProfileRole.PROCESS
    if record.kind is ProfileKind.FILAMENT:
        return ProfileRole.FILAMENT
    if record.source.casefold() in {"user", "project", "session"}:
        return ProfileRole.USER_OVERRIDE
    return ProfileRole.USER_OVERRIDE


class ProfileInventoryService:
    """Cache a profile inventory and invalidate it on any file-state change."""

    def __init__(self, cache_path: str | Path | None = None) -> None:
        self.cache_path = Path(cache_path) if cache_path is not None else None
        self._memory: dict[str, ProfileInventory] = {}

    def load(
        self,
        adapter: SlicerAdapter,
        installation: SlicerInstallation,
        *,
        force: bool = False,
    ) -> ProfileInventory:
        key = installation.identity_key
        current_states = self.snapshot_file_states(installation.profile_roots)
        if not force:
            memory = self._memory.get(key)
            if memory is not None and memory.file_states == current_states:
                return memory
            persisted = self._load_persisted(installation, current_states)
            if persisted is not None:
                self._memory[key] = persisted
                return persisted

        records = tuple(adapter.discover_profiles(installation))
        # Re-read after discovery so a concurrent change never creates a mixed
        # inventory/fingerprint pair.
        final_states = self.snapshot_file_states(installation.profile_roots)
        if current_states != final_states:
            records = tuple(adapter.discover_profiles(installation))
            final_states = self.snapshot_file_states(installation.profile_roots)
        fingerprint = self._fingerprint(installation, records, final_states)
        inventory = ProfileInventory(
            installation=installation,
            records=records,
            file_states=final_states,
            fingerprint_sha256=fingerprint,
        )
        self._memory[key] = inventory
        self._save_persisted(inventory)
        return inventory

    def is_stale(self, inventory: ProfileInventory) -> bool:
        return self.snapshot_file_states(
            inventory.installation.profile_roots
        ) != inventory.file_states

    def cached_inventory(
        self,
        installation: SlicerInstallation,
    ) -> ProfileInventory | None:
        return self._memory.get(installation.identity_key)

    def invalidate(self, installation: SlicerInstallation) -> None:
        self._memory.pop(installation.identity_key, None)

    @staticmethod
    def snapshot_file_states(
        roots: Iterable[Path],
    ) -> tuple[ProfileFileState, ...]:
        states: list[ProfileFileState] = []
        seen: set[Path] = set()
        for root in roots:
            root = Path(root)
            if not root.is_dir():
                continue
            try:
                paths = tuple(root.rglob("*"))
            except OSError:
                continue
            for path in paths:
                if path.suffix.casefold() not in _PROFILE_SUFFIXES:
                    continue
                try:
                    resolved = path.resolve()
                    statistics = resolved.stat()
                except OSError:
                    continue
                if resolved in seen or not resolved.is_file():
                    continue
                seen.add(resolved)
                states.append(
                    ProfileFileState(
                        path=resolved,
                        size_bytes=statistics.st_size,
                        modified_ns=statistics.st_mtime_ns,
                    )
                )
        return tuple(sorted(states, key=lambda item: str(item.path).casefold()))

    @staticmethod
    def _fingerprint(
        installation: SlicerInstallation,
        records: tuple[ProfileRecord, ...],
        states: tuple[ProfileFileState, ...],
    ) -> str:
        payload = {
            "adapter_id": installation.adapter_id,
            "executable_path": str(installation.executable_path),
            "version": installation.version,
            "files": [state.to_dict() for state in states],
            "records": [
                {
                    "profile_id": record.profile_id,
                    "name": record.name,
                    "kind": record.kind.value,
                    "path": str(record.path),
                    "source": record.source,
                    "inherits": list(record.inherits),
                    "metadata": _json_safe(record.metadata),
                }
                for record in records
            ],
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def _load_persisted(
        self,
        installation: SlicerInstallation,
        current_states: tuple[ProfileFileState, ...],
    ) -> ProfileInventory | None:
        if self.cache_path is None or not self.cache_path.is_file():
            return None
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if int(payload.get("schema_version", 0)) != PROFILE_INVENTORY_SCHEMA_VERSION:
                return None
            entry = payload.get("installations", {}).get(installation.identity_key)
            if not isinstance(entry, Mapping):
                return None
            if entry.get("version") != installation.version:
                return None
            raw_states = entry.get("file_states", ())
            states = tuple(
                ProfileFileState(
                    path=Path(item["path"]),
                    size_bytes=int(item["size_bytes"]),
                    modified_ns=int(item["modified_ns"]),
                )
                for item in raw_states
                if isinstance(item, Mapping)
            )
            if states != current_states:
                return None
            records = tuple(
                _record_from_dict(item, installation.adapter_id)
                for item in entry.get("records", ())
                if isinstance(item, Mapping)
            )
            if not records and current_states:
                return None
            return ProfileInventory(
                installation=installation,
                records=records,
                file_states=states,
                fingerprint_sha256=str(entry.get("fingerprint_sha256", "")),
                created_utc=str(entry.get("created_utc", "")),
            )
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None

    def _save_persisted(self, inventory: ProfileInventory) -> None:
        if self.cache_path is None:
            return
        payload: dict[str, Any] = {
            "schema_version": PROFILE_INVENTORY_SCHEMA_VERSION,
            "installations": {},
        }
        if self.cache_path.is_file():
            try:
                existing = json.loads(self.cache_path.read_text(encoding="utf-8"))
                if (
                    isinstance(existing, dict)
                    and existing.get("schema_version") == PROFILE_INVENTORY_SCHEMA_VERSION
                ):
                    payload = existing
            except (OSError, json.JSONDecodeError):
                pass
        installations = payload.setdefault("installations", {})
        installations[inventory.installation.identity_key] = {
            "version": inventory.installation.version,
            "created_utc": inventory.created_utc,
            "fingerprint_sha256": inventory.fingerprint_sha256,
            "file_states": [state.to_dict() for state in inventory.file_states],
            "records": [_record_to_dict(record) for record in inventory.records],
        }
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.cache_path.with_suffix(self.cache_path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.cache_path)
        except OSError:
            return


class ProfileInheritanceResolver:
    def __init__(
        self,
        inventory: ProfileInventory,
        adapter: SlicerAdapter,
    ) -> None:
        self.inventory = inventory
        self.adapter = adapter
        self._cache: dict[tuple[str, str], ResolvedProfile] = {}

    def resolve(self, record: ProfileRecord) -> ResolvedProfile:
        return self._resolve(record, ())

    def resolve_all(self) -> tuple[ResolvedProfile, ...]:
        return tuple(self.resolve(record) for record in self.inventory.records)

    def _resolve(
        self,
        record: ProfileRecord,
        stack: tuple[tuple[str, str], ...],
    ) -> ResolvedProfile:
        key = profile_record_key(record)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        if key in stack:
            cycle = " -> ".join(item[1] or item[0] for item in (*stack, key))
            return ResolvedProfile(
                record=record,
                role=role_for_profile(record),
                chain=(record,),
                effective_values={},
                fingerprint_sha256=None,
                valid=False,
                errors=(f"Zyklische Profilvererbung: {cycle}",),
            )

        values: dict[str, Any] = {}
        chain: list[ProfileRecord] = []
        errors: list[str] = []
        for parent_reference in record.inherits:
            parents = self._find_parents(parent_reference, record)
            if len(parents) != 1:
                if not parents:
                    errors.append(
                        f"Fehlendes Basisprofil '{parent_reference}' für "
                        f"'{record.name}'."
                    )
                else:
                    errors.append(
                        f"Mehrdeutiges Basisprofil '{parent_reference}' für "
                        f"'{record.name}'."
                    )
                continue
            parent = self._resolve(parents[0], (*stack, key))
            if not parent.valid:
                errors.extend(parent.errors)
                continue
            values.update(parent.effective_values)
            for item in parent.chain:
                if item not in chain:
                    chain.append(item)

        own_values = self.adapter.profile_values(record)
        if not own_values:
            errors.append(f"Profil '{record.name}' enthält keine lesbaren Werte.")
        values.update(own_values)
        chain.append(record)
        fingerprint = stable_json_fingerprint(values) if values else None
        resolved = ResolvedProfile(
            record=record,
            role=role_for_profile(record, values),
            chain=tuple(chain),
            effective_values=values,
            fingerprint_sha256=fingerprint,
            valid=not errors,
            errors=tuple(dict.fromkeys(errors)),
        )
        self._cache[key] = resolved
        return resolved

    def _find_parents(
        self,
        reference: str,
        child: ProfileRecord,
    ) -> tuple[ProfileRecord, ...]:
        normalized = reference.casefold().strip()
        exact_ids = tuple(
            record
            for record in self.inventory.records
            if record.profile_id.casefold() == normalized
            and self._compatible_profile_kinds(record.kind, child.kind)
        )
        if exact_ids:
            return self._select_parent_mirror(exact_ids, child)
        named = tuple(
            record
            for record in self.inventory.records
            if record.name.casefold() == normalized
            and self._compatible_profile_kinds(record.kind, child.kind)
        )
        return self._select_parent_mirror(named, child)

    def _select_parent_mirror(
        self,
        candidates: tuple[ProfileRecord, ...],
        child: ProfileRecord,
    ) -> tuple[ProfileRecord, ...]:
        if len(candidates) <= 1:
            return candidates

        child_parts = tuple(part.casefold() for part in child.path.parts)
        child_mirror = _profile_mirror(child_parts)

        def location_score(record: ProfileRecord) -> tuple[int, int]:
            parent_parts = tuple(part.casefold() for part in record.path.parts)
            parent_mirror = _profile_mirror(parent_parts)
            mirror_score = 0
            if child_mirror == parent_mirror:
                mirror_score = 100
            elif child_mirror == "user" and parent_mirror == "system":
                # Orca-family user presets inherit from the active system
                # catalogue, not from a parallel OTA or installation mirror.
                mirror_score = 80
            shared = 0
            for left, right in zip(child_parts, parent_parts):
                if left != right:
                    break
                shared += 1
            return mirror_score, shared

        scores = {profile_record_key(item): location_score(item) for item in candidates}
        best = max(scores.values())
        local = tuple(
            item for item in candidates if scores[profile_record_key(item)] == best
        )
        if len(local) <= 1:
            return local

        # Multiple paths in the same mirror can still refer to the same base
        # preset. Collapse only byte-equivalent effective raw values; genuine
        # conflicts intentionally remain ambiguous and invalidate the child.
        fingerprints = {
            stable_json_fingerprint(self.adapter.profile_values(item))
            for item in local
        }
        if len(fingerprints) == 1:
            return (sorted(local, key=lambda item: str(item.path).casefold())[0],)
        return local

    @staticmethod
    def _compatible_profile_kinds(
        first: ProfileKind,
        second: ProfileKind,
    ) -> bool:
        machine = {ProfileKind.MACHINE, ProfileKind.DEFINITION}
        process = {ProfileKind.PROCESS, ProfileKind.QUALITY}
        if first in machine and second in machine:
            return True
        if first in process and second in process:
            return True
        return first is second


def _record_to_dict(record: ProfileRecord) -> dict[str, Any]:
    return {
        "profile_id": record.profile_id,
        "name": record.name,
        "kind": record.kind.value,
        "path": str(record.path),
        "source": record.source,
        "inherits": list(record.inherits),
        "metadata": _json_safe(record.metadata),
    }


def _record_from_dict(
    payload: Mapping[str, Any],
    adapter_id: str,
) -> ProfileRecord:
    try:
        kind = ProfileKind(str(payload.get("kind", ProfileKind.UNKNOWN.value)))
    except ValueError:
        kind = ProfileKind.UNKNOWN
    metadata = payload.get("metadata", {})
    return ProfileRecord(
        adapter_id=adapter_id,
        profile_id=str(payload.get("profile_id", "")),
        name=str(payload.get("name", "")),
        kind=kind,
        path=Path(str(payload.get("path", ""))),
        source=str(payload.get("source", "unknown")),
        inherits=tuple(str(item) for item in payload.get("inherits", ())),
        metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _profile_mirror(parts: tuple[str, ...]) -> str:
    for marker in ("user", "system", "ota", "resources"):
        if marker in parts:
            return marker
    return "other"
