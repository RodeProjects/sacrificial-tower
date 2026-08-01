from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
from typing import Any, Mapping
from uuid import uuid4

from cooling_tower.file_integrity import sha256_file
from cooling_tower.persistence.versioned_json import (
    InvalidVersionedDocumentError,
    VersionedDocumentError,
    VersionedJsonStore,
)


PRESLICE_CACHE_SCHEMA_VERSION = 1
DEFAULT_MAXIMUM_PRESLICE_CACHE_ENTRIES = 8
_SCHEMA_KEY = "preslice_cache_schema_version"
_KEY_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_ENTRY_KEYS = {
    "artifact_name",
    "gcode_sha256",
    "gcode_size_bytes",
    "created_at_utc",
    "preslice_duration_s",
}


@dataclass(frozen=True, slots=True)
class PreSliceCacheEntry:
    cache_key: str
    artifact_path: Path
    gcode_sha256: str
    gcode_size_bytes: int
    created_at_utc: str
    preslice_duration_s: float


class PreSliceCache:
    """Small, versioned cache for app-owned generated analysis G-code."""

    def __init__(
        self,
        root: str | Path,
        *,
        maximum_entries: int = DEFAULT_MAXIMUM_PRESLICE_CACHE_ENTRIES,
    ) -> None:
        if maximum_entries < 1 or maximum_entries > 100:
            raise ValueError("Die Anzahl der Pre-Slice-Cacheeinträge ist ungültig.")
        self.root = Path(root).expanduser().resolve()
        self.artifact_root = self.root / "artifacts"
        self.index_path = self.root / "index.json"
        self.maximum_entries = maximum_entries
        self._store = VersionedJsonStore(
            self.index_path,
            schema_key=_SCHEMA_KEY,
            current_version=PRESLICE_CACHE_SCHEMA_VERSION,
            normalizer=_normalize_document,
            document_name="Pre-Slice-Cacheindex",
            legacy_version=0,
        )

    def assert_safe_location(
        self,
        forbidden_roots: tuple[Path, ...],
        *,
        source_parent: Path | None = None,
    ) -> None:
        candidate = self.root
        forbidden = tuple(Path(path).expanduser().resolve() for path in forbidden_roots)
        if any(candidate == path or candidate.is_relative_to(path) for path in forbidden):
            raise ValueError(
                "Der Pre-Slice-Cache darf weder in einem Slicer-Verzeichnis "
                "noch neben der Benutzer-STL liegen."
            )
        if source_parent is not None:
            original_parent = Path(source_parent).expanduser().resolve()
            if candidate == original_parent or candidate.parent == original_parent:
                raise ValueError(
                    "Der Pre-Slice-Cache darf nicht direkt neben der Benutzer-STL liegen."
                )

    def get(self, cache_key: str) -> PreSliceCacheEntry | None:
        key = _cache_key(cache_key)
        document = self._load_document()
        if document is None:
            return None
        entries = document["entries"]
        raw = entries.get(key)
        if raw is None:
            return None
        entry = self._entry_from_payload(key, raw)
        try:
            stat = entry.artifact_path.stat()
            digest = sha256_file(entry.artifact_path)
        except OSError:
            return None
        if (
            not entry.artifact_path.is_file()
            or stat.st_size != entry.gcode_size_bytes
            or digest != entry.gcode_sha256
        ):
            return None
        return entry

    def put(
        self,
        *,
        cache_key: str,
        gcode_path: str | Path,
        created_at_utc: str,
        preslice_duration_s: float,
    ) -> PreSliceCacheEntry | None:
        key = _cache_key(cache_key)
        source = Path(gcode_path).expanduser().resolve(strict=True)
        if not source.is_file() or source.suffix.casefold() != ".gcode":
            raise ValueError("Nur ein lesbarer G-Code darf gespeichert werden.")
        created = _timestamp(created_at_utc)
        duration = _duration(preslice_duration_s)
        document = self._load_document()
        if document is None:
            # A malformed, future or externally changed index is deliberately
            # never replaced implicitly.
            return None
        digest = sha256_file(source)
        size = source.stat().st_size
        artifact_name = f"{key}.gcode"
        destination = self.artifact_root / artifact_name
        created_artifact = False
        if destination.exists():
            try:
                existing_matches = (
                    destination.is_file()
                    and destination.stat().st_size == size
                    and sha256_file(destination) == digest
                )
            except OSError:
                existing_matches = False
            if not existing_matches:
                return None
        else:
            self.artifact_root.mkdir(parents=True, exist_ok=True)
            temporary = self.artifact_root / f".{artifact_name}.{uuid4().hex}.tmp"
            try:
                with source.open("rb") as reader, temporary.open("xb") as writer:
                    shutil.copyfileobj(reader, writer, length=1024 * 1024)
                    writer.flush()
                    os.fsync(writer.fileno())
                if sha256_file(temporary) != digest:
                    raise OSError("Die Cachekopie stimmt nicht mit dem G-Code überein.")
                if destination.exists():
                    temporary.unlink(missing_ok=True)
                    return None
                os.replace(temporary, destination)
                created_artifact = True
            except Exception:
                temporary.unlink(missing_ok=True)
                raise

        payload = {
            "artifact_name": artifact_name,
            "gcode_sha256": digest,
            "gcode_size_bytes": size,
            "created_at_utc": created,
            "preslice_duration_s": duration,
        }
        entries = dict(document["entries"])
        entries[key] = payload
        retained = sorted(
            entries.items(),
            key=lambda item: item[1]["created_at_utc"],
            reverse=True,
        )[: self.maximum_entries]
        retained_entries = dict(retained)
        removed = set(entries) - set(retained_entries)
        try:
            self._store.save(
                {
                    _SCHEMA_KEY: PRESLICE_CACHE_SCHEMA_VERSION,
                    "payload_sha256": _entries_digest(retained_entries),
                    "entries": retained_entries,
                }
            )
        except (OSError, VersionedDocumentError):
            if created_artifact:
                destination.unlink(missing_ok=True)
            return None
        for removed_key in removed:
            removed_path = self.artifact_root / f"{removed_key}.gcode"
            if removed_path.parent == self.artifact_root:
                removed_path.unlink(missing_ok=True)
        return self._entry_from_payload(key, payload)

    def _load_document(self) -> dict[str, Any] | None:
        if not self.index_path.exists():
            return {
                _SCHEMA_KEY: PRESLICE_CACHE_SCHEMA_VERSION,
                "payload_sha256": _entries_digest({}),
                "entries": {},
            }
        try:
            return self._store.load().payload
        except (OSError, VersionedDocumentError):
            return None

    def _entry_from_payload(
        self,
        cache_key: str,
        payload: Mapping[str, Any],
    ) -> PreSliceCacheEntry:
        return PreSliceCacheEntry(
            cache_key=cache_key,
            artifact_path=(self.artifact_root / str(payload["artifact_name"])).resolve(),
            gcode_sha256=str(payload["gcode_sha256"]),
            gcode_size_bytes=int(payload["gcode_size_bytes"]),
            created_at_utc=str(payload["created_at_utc"]),
            preslice_duration_s=float(payload["preslice_duration_s"]),
        )


def _normalize_document(payload: dict[str, Any]) -> dict[str, Any]:
    if set(payload) != {_SCHEMA_KEY, "payload_sha256", "entries"}:
        raise InvalidVersionedDocumentError(
            "Der Pre-Slice-Cacheindex enthält unerwartete Felder."
        )
    entries = payload.get("entries")
    if not isinstance(entries, dict) or len(entries) > 100:
        raise InvalidVersionedDocumentError(
            "Der Pre-Slice-Cacheindex enthält ungültige Einträge."
        )
    canonical: dict[str, dict[str, Any]] = {}
    for raw_key, raw_entry in entries.items():
        key = _cache_key(raw_key)
        if not isinstance(raw_entry, Mapping) or set(raw_entry) != _ENTRY_KEYS:
            raise InvalidVersionedDocumentError(
                "Ein Pre-Slice-Cacheeintrag ist unvollständig."
            )
        artifact_name = raw_entry["artifact_name"]
        if artifact_name != f"{key}.gcode":
            raise InvalidVersionedDocumentError(
                "Ein Pre-Slice-Cacheeintrag enthält einen unsicheren Dateinamen."
            )
        size = raw_entry["gcode_size_bytes"]
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise InvalidVersionedDocumentError(
                "Ein Pre-Slice-Cacheeintrag enthält eine ungültige Dateigröße."
            )
        canonical[key] = {
            "artifact_name": artifact_name,
            "gcode_sha256": _cache_key(raw_entry["gcode_sha256"]),
            "gcode_size_bytes": size,
            "created_at_utc": _timestamp(raw_entry["created_at_utc"]),
            "preslice_duration_s": _duration(raw_entry["preslice_duration_s"]),
        }
    expected_digest = _entries_digest(canonical)
    if payload["payload_sha256"] != expected_digest:
        raise InvalidVersionedDocumentError(
            "Die Prüfsumme des Pre-Slice-Cacheindex stimmt nicht."
        )
    return {
        _SCHEMA_KEY: PRESLICE_CACHE_SCHEMA_VERSION,
        "payload_sha256": expected_digest,
        "entries": canonical,
    }


def _entries_digest(entries: Mapping[str, Any]) -> str:
    try:
        payload = json.dumps(
            dict(entries),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise InvalidVersionedDocumentError(
            "Der Pre-Slice-Cacheindex ist nicht kanonisch serialisierbar."
        ) from error
    return hashlib.sha256(payload).hexdigest()


def _cache_key(value: object) -> str:
    if not isinstance(value, str) or _KEY_PATTERN.fullmatch(value) is None:
        raise InvalidVersionedDocumentError("Ein Cache-Schlüssel ist ungültig.")
    return value


def _timestamp(value: object) -> str:
    if not isinstance(value, str) or len(value) > 64:
        raise InvalidVersionedDocumentError("Ein Cache-Zeitpunkt ist ungültig.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise InvalidVersionedDocumentError(
            "Ein Cache-Zeitpunkt ist ungültig."
        ) from error
    if parsed.tzinfo is None:
        raise InvalidVersionedDocumentError(
            "Ein Cache-Zeitpunkt benötigt eine Zeitzone."
        )
    return parsed.astimezone(timezone.utc).isoformat()


def _duration(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidVersionedDocumentError("Eine Pre-Slice-Dauer ist ungültig.")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise InvalidVersionedDocumentError("Eine Pre-Slice-Dauer ist ungültig.")
    return result
