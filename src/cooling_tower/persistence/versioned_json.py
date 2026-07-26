from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4


JsonObject = dict[str, Any]
MigrationStep = Callable[[JsonObject], JsonObject]
DocumentNormalizer = Callable[[JsonObject], JsonObject]


class VersionedDocumentError(ValueError):
    """A versioned user document cannot be interpreted safely."""


class InvalidVersionedDocumentError(VersionedDocumentError):
    """A versioned user document is malformed or failed validation."""


class FutureSchemaVersionError(VersionedDocumentError):
    """A document was produced by a newer, unsupported application."""


class MissingMigrationError(VersionedDocumentError):
    """A required migration step has not been registered."""


class ConcurrentDocumentChangeError(VersionedDocumentError):
    """A document changed after it was read by this store."""


class VersionedDocumentWriteBlockedError(OSError):
    """Writing is blocked to protect a document that could not be loaded."""


@dataclass(frozen=True, slots=True)
class VersionedLoadResult:
    payload: JsonObject
    source_version: int
    target_version: int
    migrated: bool
    normalized: bool
    backup_path: Path | None = None

    @property
    def changed(self) -> bool:
        return self.migrated or self.normalized


class VersionedJsonStore:
    """Load, migrate, validate, and atomically save one JSON document.

    Migration functions are indexed by their source version. A function stored
    under ``2`` migrates schema 2 to schema 3. Every intermediate step is
    mandatory so that semantic changes cannot be skipped accidentally.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        schema_key: str,
        current_version: int,
        migrations: Mapping[int, MigrationStep] | None = None,
        normalizer: DocumentNormalizer | None = None,
        document_name: str = "JSON-Dokument",
        legacy_version: int = 0,
    ) -> None:
        if not schema_key.strip():
            raise ValueError("Der Schlüssel der Schema-Version darf nicht leer sein.")
        if current_version < 1:
            raise ValueError("Die aktuelle Schema-Version muss mindestens 1 sein.")
        if not 0 <= legacy_version <= current_version:
            raise ValueError("Die Legacy-Version liegt außerhalb des Schemas.")
        self.path = Path(path)
        self.schema_key = schema_key
        self.current_version = current_version
        self.migrations = dict(migrations or {})
        self.normalizer = normalizer
        self.document_name = document_name
        self.legacy_version = legacy_version
        self._write_blocked_reason: str | None = None
        self._loaded_successfully = False
        self._last_known_bytes: bytes | None = None

    @property
    def write_blocked_reason(self) -> str | None:
        return self._write_blocked_reason

    @property
    def write_blocked(self) -> bool:
        return self._write_blocked_reason is not None

    def load(self) -> VersionedLoadResult:
        try:
            original, original_bytes = self._read_payload()
            source_version = self._schema_version(original)
            migrated_payload = self._apply_migrations(original, source_version)
            normalized_payload = self._normalize(migrated_payload)
            migrated = source_version != self.current_version
            normalized = normalized_payload != migrated_payload
            backup_path = None
            if migrated or normalized:
                backup_path = self._create_backup(
                    source_version,
                    expected_bytes=original_bytes,
                )
                atomic_write_json(
                    self.path,
                    normalized_payload,
                    expected_original_bytes=original_bytes,
                )
        except (OSError, VersionedDocumentError) as error:
            self._write_blocked_reason = str(error)
            self._loaded_successfully = False
            raise

        try:
            self._last_known_bytes = self.path.read_bytes()
        except OSError as error:
            self._write_blocked_reason = str(error)
            self._loaded_successfully = False
            raise
        self._write_blocked_reason = None
        self._loaded_successfully = True
        return VersionedLoadResult(
            payload=normalized_payload,
            source_version=source_version,
            target_version=self.current_version,
            migrated=migrated,
            normalized=normalized,
            backup_path=backup_path,
        )

    def save(self, payload: Mapping[str, Any]) -> Path:
        if self.path.is_file() and not self._loaded_successfully:
            self._write_blocked_reason = (
                f"{self.document_name} muss vor dem Überschreiben erfolgreich "
                "geladen werden."
            )
        if self._write_blocked_reason is not None:
            raise VersionedDocumentWriteBlockedError(
                f"{self.document_name} wird nicht überschrieben, weil es zuvor "
                f"nicht sicher geladen werden konnte: {self._write_blocked_reason}"
            )
        normalized = self._prepare_current_payload(payload)
        try:
            atomic_write_json(
                self.path,
                normalized,
                expected_original_bytes=(
                    self._last_known_bytes
                    if self._loaded_successfully
                    else None
                ),
            )
        except (OSError, VersionedDocumentError) as error:
            self._write_blocked_reason = str(error)
            self._loaded_successfully = False
            raise
        try:
            self._last_known_bytes = self.path.read_bytes()
        except OSError as error:
            self._write_blocked_reason = str(error)
            self._loaded_successfully = False
            raise
        self._loaded_successfully = True
        return self.path.resolve()

    def replace_with_recovery(self, payload: Mapping[str, Any]) -> Path:
        """Explicitly replace a blocked document after preserving its bytes."""

        normalized = self._prepare_current_payload(payload)
        try:
            if self.path.is_file():
                self._create_backup("recovery")
            atomic_write_json(self.path, normalized)
            self._last_known_bytes = self.path.read_bytes()
        except (OSError, VersionedDocumentError) as error:
            self._write_blocked_reason = str(error)
            self._loaded_successfully = False
            raise
        self._write_blocked_reason = None
        self._loaded_successfully = True
        return self.path.resolve()

    def _read_payload(self) -> tuple[JsonObject, bytes]:
        try:
            raw = self.path.read_bytes()
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise InvalidVersionedDocumentError(
                f"{self.document_name} ist kein gültiges UTF-8-JSON-Objekt."
            ) from error
        if not isinstance(payload, dict):
            raise InvalidVersionedDocumentError(
                f"{self.document_name} muss ein JSON-Objekt enthalten."
            )
        return payload, raw

    def _schema_version(self, payload: JsonObject) -> int:
        if self.schema_key not in payload:
            return self.legacy_version
        version = payload[self.schema_key]
        if isinstance(version, bool) or not isinstance(version, int) or version < 0:
            raise InvalidVersionedDocumentError(
                f"{self.document_name} enthält keine gültige Schema-Version."
            )
        if version > self.current_version:
            raise FutureSchemaVersionError(
                f"{self.document_name} verwendet Schema {version}; diese "
                f"Programmversion unterstützt höchstens Schema "
                f"{self.current_version}."
            )
        return version

    def _apply_migrations(
        self,
        payload: JsonObject,
        source_version: int,
    ) -> JsonObject:
        migrated = deepcopy(payload)
        version = source_version
        while version < self.current_version:
            migration = self.migrations.get(version)
            if migration is None:
                raise MissingMigrationError(
                    f"Für {self.document_name} fehlt die Migration von Schema "
                    f"{version} auf Schema {version + 1}."
                )
            try:
                candidate = migration(deepcopy(migrated))
            except VersionedDocumentError:
                raise
            except Exception as error:
                raise InvalidVersionedDocumentError(
                    f"Die Migration von {self.document_name} von Schema "
                    f"{version} auf Schema {version + 1} ist fehlgeschlagen."
                ) from error
            if not isinstance(candidate, dict):
                raise InvalidVersionedDocumentError(
                    f"Die Migration von {self.document_name} auf Schema "
                    f"{version + 1} lieferte kein JSON-Objekt."
                )
            version += 1
            candidate[self.schema_key] = version
            migrated = candidate
        return migrated

    def _normalize(self, payload: JsonObject) -> JsonObject:
        normalized = deepcopy(payload)
        if self.normalizer is not None:
            try:
                normalized = self.normalizer(normalized)
            except VersionedDocumentError:
                raise
            except Exception as error:
                raise InvalidVersionedDocumentError(
                    f"{self.document_name} konnte nicht validiert werden."
                ) from error
        if not isinstance(normalized, dict):
            raise InvalidVersionedDocumentError(
                f"Die Validierung von {self.document_name} lieferte kein JSON-Objekt."
            )
        normalized[self.schema_key] = self.current_version
        return normalized

    def _prepare_current_payload(self, payload: Mapping[str, Any]) -> JsonObject:
        if not isinstance(payload, Mapping):
            raise InvalidVersionedDocumentError(
                f"{self.document_name} muss als Objekt gespeichert werden."
            )
        current = deepcopy(dict(payload))
        current[self.schema_key] = self.current_version
        return self._normalize(current)

    def _create_backup(
        self,
        source_version: int | str,
        *,
        expected_bytes: bytes | None = None,
    ) -> Path:
        label = str(source_version).replace(os.sep, "_")
        base = self.path.with_name(
            f"{self.path.name}.schema-{label}.backup"
        )
        candidate = base
        suffix = 1
        original_bytes = self.path.read_bytes()
        if expected_bytes is not None and original_bytes != expected_bytes:
            raise ConcurrentDocumentChangeError(
                f"{self.document_name} wurde nach dem Laden von einem anderen "
                "Prozess verändert und deshalb nicht überschrieben."
            )
        while candidate.exists():
            try:
                if candidate.read_bytes() == original_bytes:
                    return candidate.resolve()
            except OSError:
                pass
            candidate = base.with_name(f"{base.name}.{suffix}")
            suffix += 1
        candidate.parent.mkdir(parents=True, exist_ok=True)
        try:
            with candidate.open("xb") as handle:
                handle.write(original_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            shutil.copystat(self.path, candidate)
        except Exception:
            candidate.unlink(missing_ok=True)
            raise
        return candidate.resolve()


def atomic_write_json(
    path: str | Path,
    payload: Mapping[str, Any],
    *,
    expected_original_bytes: bytes | None = None,
) -> Path:
    """Write JSON beside its target and replace the target in one operation."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    serialized = json.dumps(
        dict(payload),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        if expected_original_bytes is not None:
            try:
                current_bytes = target.read_bytes()
            except FileNotFoundError as error:
                raise ConcurrentDocumentChangeError(
                    "Die Zieldatei wurde nach dem Laden entfernt und deshalb "
                    "nicht neu erstellt."
                ) from error
            if current_bytes != expected_original_bytes:
                raise ConcurrentDocumentChangeError(
                    "Die Zieldatei wurde nach dem Laden verändert und deshalb "
                    "nicht überschrieben."
                )
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target.resolve()
