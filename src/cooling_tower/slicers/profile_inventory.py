from __future__ import annotations

import hashlib
import json
from hmac import compare_digest
from pathlib import Path
from threading import RLock
from typing import Any, Iterable, Mapping

from cooling_tower.persistence.versioned_json import atomic_write_json
from cooling_tower.slicers.adapter import SlicerAdapter
from cooling_tower.slicers.support import require_profile_support
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


_PROFILE_SUFFIXES = {".json", ".ini", ".cfg", ".info"}
DEFAULT_MAXIMUM_PROFILE_INVENTORY_CACHE_BYTES = 64 * 1024 * 1024

_CACHE_LOCKS_GUARD = RLock()
_CACHE_LOCKS: dict[Path, RLock] = {}


def _lock_for_cache_path(path: Path) -> RLock:
    with _CACHE_LOCKS_GUARD:
        lock = _CACHE_LOCKS.get(path)
        if lock is None:
            lock = RLock()
            _CACHE_LOCKS[path] = lock
        return lock


def profile_record_key(record: ProfileRecord) -> tuple[str, str]:
    section = str(record.metadata.get("section", ""))
    return str(record.path).casefold(), section.casefold()


def _records_owned_by_installation(
    records: Iterable[ProfileRecord],
    installation: SlicerInstallation,
) -> tuple[ProfileRecord, ...]:
    """Reject records crossing the selected slicer's adapter or root boundary."""

    roots: list[Path] = []
    for root in installation.profile_roots:
        try:
            roots.append(Path(root).resolve())
        except OSError:
            continue
    accepted: list[ProfileRecord] = []
    resolved_paths: dict[Path, Path] = {}
    for record in records:
        if record.adapter_id != installation.adapter_id:
            continue
        path = resolved_paths.get(record.path)
        if path is None:
            try:
                path = Path(record.path).resolve()
            except OSError:
                continue
            resolved_paths[record.path] = path
        if any(path == root or root in path.parents for root in roots):
            accepted.append(record)
    return tuple(accepted)


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

    def __init__(
        self,
        cache_path: str | Path | None = None,
        *,
        maximum_cache_bytes: int = DEFAULT_MAXIMUM_PROFILE_INVENTORY_CACHE_BYTES,
    ) -> None:
        self.cache_path = (
            Path(cache_path).expanduser().resolve()
            if cache_path is not None
            else None
        )
        if (
            isinstance(maximum_cache_bytes, bool)
            or not isinstance(maximum_cache_bytes, int)
            or maximum_cache_bytes <= 0
        ):
            raise ValueError("maximum_cache_bytes must be a positive integer.")
        self.maximum_cache_bytes = maximum_cache_bytes
        self._memory: dict[str, ProfileInventory] = {}
        self._lock = RLock()
        self._cache_lock = (
            _lock_for_cache_path(self.cache_path)
            if self.cache_path is not None
            else RLock()
        )

    def load(
        self,
        adapter: SlicerAdapter,
        installation: SlicerInstallation,
        *,
        force: bool = False,
    ) -> ProfileInventory:
        require_profile_support(installation, adapter)
        with self._lock:
            return self._load_locked(adapter, installation, force=force)

    def _load_locked(
        self,
        adapter: SlicerAdapter,
        installation: SlicerInstallation,
        *,
        force: bool,
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

        records = _records_owned_by_installation(
            adapter.discover_profiles(installation),
            installation,
        )
        # Re-read after discovery so a concurrent change never creates a mixed
        # inventory/fingerprint pair.
        final_states = self.snapshot_file_states(installation.profile_roots)
        if current_states != final_states:
            records = _records_owned_by_installation(
                adapter.discover_profiles(installation),
                installation,
            )
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
        with self._lock:
            return self._memory.get(installation.identity_key)

    def invalidate(self, installation: SlicerInstallation) -> None:
        with self._lock:
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
            for suffix in _PROFILE_SUFFIXES:
                try:
                    paths = root.rglob(f"*{suffix}")
                    for path in paths:
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
                except OSError:
                    continue
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
        cache_path = self.cache_path
        if cache_path is None:
            return None
        try:
            with self._cache_lock:
                if not cache_path.is_file():
                    return None
                with cache_path.open("rb") as handle:
                    raw = handle.read(self.maximum_cache_bytes + 1)
                if len(raw) > self.maximum_cache_bytes:
                    return None
                payload = json.loads(raw.decode("utf-8"))
                if not isinstance(payload, Mapping):
                    return None
                if (
                    payload.get("schema_version")
                    != PROFILE_INVENTORY_SCHEMA_VERSION
                ):
                    return None
                installations = payload.get("installations")
                if not isinstance(installations, Mapping):
                    return None
                entry = installations.get(installation.identity_key)
                if not isinstance(entry, Mapping):
                    return None
                if entry.get("version") != installation.version:
                    return None
                raw_states = entry.get("file_states")
                if not isinstance(raw_states, list) or not all(
                    _valid_file_state_payload(item) for item in raw_states
                ):
                    return None
                states = tuple(
                    ProfileFileState(
                        path=Path(item["path"]),
                        size_bytes=item["size_bytes"],
                        modified_ns=item["modified_ns"],
                    )
                    for item in raw_states
                )
                if states != current_states:
                    return None
                raw_records = entry.get("records")
                if not isinstance(raw_records, list) or not all(
                    _valid_record_payload(item) for item in raw_records
                ):
                    return None
                records = tuple(
                    _record_from_dict(item, installation.adapter_id)
                    for item in raw_records
                )
                if records != _records_owned_by_installation(
                    records,
                    installation,
                ):
                    return None
                if not records and current_states:
                    return None
                stored_fingerprint = entry.get("fingerprint_sha256")
                if not isinstance(stored_fingerprint, str):
                    return None
                calculated_fingerprint = self._fingerprint(
                    installation,
                    records,
                    states,
                )
                if not compare_digest(
                    stored_fingerprint.casefold(),
                    calculated_fingerprint,
                ):
                    return None
                created_utc = entry.get("created_utc")
                if not isinstance(created_utc, str):
                    return None
                return ProfileInventory(
                    installation=installation,
                    records=records,
                    file_states=states,
                    fingerprint_sha256=calculated_fingerprint,
                    created_utc=created_utc,
                )
        except (
            OSError,
            UnicodeError,
            ValueError,
            TypeError,
            KeyError,
            json.JSONDecodeError,
        ):
            return None

    def _save_persisted(self, inventory: ProfileInventory) -> None:
        cache_path = self.cache_path
        if cache_path is None:
            return
        with self._cache_lock:
            payload: dict[str, Any] = {
                "schema_version": PROFILE_INVENTORY_SCHEMA_VERSION,
                "installations": {},
            }
            if cache_path.is_file():
                try:
                    with cache_path.open("rb") as handle:
                        raw = handle.read(self.maximum_cache_bytes + 1)
                    if len(raw) <= self.maximum_cache_bytes:
                        existing = json.loads(raw.decode("utf-8"))
                        existing_installations = (
                            existing.get("installations")
                            if isinstance(existing, Mapping)
                            and existing.get("schema_version")
                            == PROFILE_INVENTORY_SCHEMA_VERSION
                            else None
                        )
                        if isinstance(existing_installations, Mapping):
                            payload["installations"] = dict(existing_installations)
                except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
                    pass
            installations = payload["installations"]
            installations[inventory.installation.identity_key] = {
                "version": inventory.installation.version,
                "created_utc": inventory.created_utc,
                "fingerprint_sha256": inventory.fingerprint_sha256,
                "file_states": [state.to_dict() for state in inventory.file_states],
                "records": [_record_to_dict(record) for record in inventory.records],
            }
            try:
                serialized = json.dumps(
                    payload,
                    ensure_ascii=False,
                    allow_nan=False,
                    indent=2,
                    sort_keys=True,
                ).encode("utf-8")
                if len(serialized) + 1 > self.maximum_cache_bytes:
                    return
                atomic_write_json(cache_path, payload)
            except (OSError, TypeError, ValueError):
                return


def _profile_include_references(value: object) -> tuple[str, ...]:
    """Return normalized Orca/Bambu template references."""

    if isinstance(value, str):
        candidate = value.strip()
        return (candidate,) if candidate else ()
    if isinstance(value, (list, tuple)):
        return tuple(
            candidate
            for item in value
            if isinstance(item, str)
            and (candidate := item.strip())
        )
    return ()


class ProfileInheritanceResolver:
    def __init__(
        self,
        inventory: ProfileInventory,
        adapter: SlicerAdapter,
    ) -> None:
        self.inventory = inventory
        self.adapter = adapter
        self._cache: dict[tuple[str, str], ResolvedProfile] = {}
        # Vendor catalogues such as PrusaSlicer's contain thousands of
        # presets.  Building these indexes once keeps inheritance lookup
        # linear in the number of actual matches instead of rescanning the
        # entire inventory for every profile.  Tuple order stays identical to
        # ``inventory.records``, preserving the existing selection policy.
        records_by_id: dict[str, list[ProfileRecord]] = {}
        records_by_name: dict[str, list[ProfileRecord]] = {}
        for record in inventory.records:
            records_by_id.setdefault(record.profile_id.casefold(), []).append(record)
            records_by_name.setdefault(record.name.casefold(), []).append(record)
        self._records_by_id = {
            key: tuple(records) for key, records in records_by_id.items()
        }
        self._records_by_name = {
            key: tuple(records) for key, records in records_by_name.items()
        }

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

        # Orca-family catalogues use ``include`` for template fragments which
        # are applied after the normal inheritance chain but before the
        # profile's own values.  Treating the key merely as payload made a
        # flattened Bambu profile promote older base defaults to explicit
        # overrides.  Variant-specific values from templates (for example the
        # X2D extruder-change retraction setting) were then lost in exported
        # projects even though no filament override had been requested.
        include_references = _profile_include_references(
            own_values.get("include")
        )
        for include_reference in include_references:
            includes = self._find_parents(include_reference, record)
            if len(includes) != 1:
                if not includes:
                    errors.append(
                        f"Fehlende Profilvorlage '{include_reference}' für "
                        f"'{record.name}'."
                    )
                else:
                    errors.append(
                        f"Mehrdeutige Profilvorlage '{include_reference}' "
                        f"für '{record.name}'."
                    )
                continue
            included = self._resolve(includes[0], (*stack, key))
            if not included.valid:
                errors.extend(included.errors)
                continue
            values.update(included.effective_values)
            for item in included.chain:
                if item not in chain:
                    chain.append(item)

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
            for record in self._records_by_id.get(normalized, ())
            if self._compatible_profile_kinds(record.kind, child.kind)
        )
        if exact_ids:
            return self._select_parent_records(exact_ids, child)
        named = tuple(
            record
            for record in self._records_by_name.get(normalized, ())
            if self._compatible_profile_kinds(record.kind, child.kind)
        )
        return self._select_parent_records(named, child)

    def _select_parent_records(
        self,
        candidates: tuple[ProfileRecord, ...],
        child: ProfileRecord,
    ) -> tuple[ProfileRecord, ...]:
        adapter_selector = getattr(
            self.adapter,
            "select_profile_parents",
            None,
        )
        if callable(adapter_selector):
            selected = adapter_selector(candidates, child)
            if isinstance(selected, tuple) and all(
                isinstance(item, ProfileRecord) for item in selected
            ):
                return selected
        return self._select_parent_mirror(candidates, child)

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


def _valid_file_state_payload(payload: object) -> bool:
    if not isinstance(payload, Mapping):
        return False
    path = payload.get("path")
    size_bytes = payload.get("size_bytes")
    modified_ns = payload.get("modified_ns")
    return (
        isinstance(path, str)
        and bool(path.strip())
        and isinstance(size_bytes, int)
        and not isinstance(size_bytes, bool)
        and size_bytes >= 0
        and isinstance(modified_ns, int)
        and not isinstance(modified_ns, bool)
        and modified_ns >= 0
    )


def _valid_record_payload(payload: object) -> bool:
    if not isinstance(payload, Mapping):
        return False
    required_strings = ("profile_id", "name", "kind", "path", "source")
    if any(
        not isinstance(payload.get(key), str) or not payload[key].strip()
        for key in required_strings
    ):
        return False
    try:
        ProfileKind(payload["kind"])
    except ValueError:
        return False
    inherits = payload.get("inherits")
    metadata = payload.get("metadata")
    return (
        isinstance(inherits, list)
        and all(isinstance(item, str) for item in inherits)
        and isinstance(metadata, Mapping)
    )


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
