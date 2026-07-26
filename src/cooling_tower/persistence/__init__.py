"""Safe persistence primitives for application-owned user data."""

from cooling_tower.persistence.versioned_json import (
    ConcurrentDocumentChangeError,
    FutureSchemaVersionError,
    InvalidVersionedDocumentError,
    MissingMigrationError,
    VersionedDocumentError,
    VersionedDocumentWriteBlockedError,
    VersionedJsonStore,
    VersionedLoadResult,
    atomic_write_json,
)
from cooling_tower.persistence.location_migration import (
    LocationMigrationResult,
    copy_legacy_file_if_absent,
    migrate_legacy_configuration,
)

__all__ = [
    "ConcurrentDocumentChangeError",
    "FutureSchemaVersionError",
    "InvalidVersionedDocumentError",
    "MissingMigrationError",
    "VersionedDocumentError",
    "VersionedDocumentWriteBlockedError",
    "VersionedJsonStore",
    "VersionedLoadResult",
    "atomic_write_json",
    "LocationMigrationResult",
    "copy_legacy_file_if_absent",
    "migrate_legacy_configuration",
]
