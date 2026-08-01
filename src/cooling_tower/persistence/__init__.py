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
from cooling_tower.persistence.analysis_cache import (
    DEFAULT_MAXIMUM_ANALYSIS_CACHE_BYTES,
    PERSISTENT_ANALYSIS_CACHE_SCHEMA_VERSION,
    InvalidPersistentAnalysisCacheError,
    PersistentAnalysisCacheError,
    PersistentGCodeAnalysisCache,
    UnsupportedPersistentAnalysisCacheError,
)
from cooling_tower.persistence.preslice_cache import (
    DEFAULT_MAXIMUM_PRESLICE_CACHE_ENTRIES,
    PRESLICE_CACHE_SCHEMA_VERSION,
    PreSliceCache,
    PreSliceCacheEntry,
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
    "DEFAULT_MAXIMUM_ANALYSIS_CACHE_BYTES",
    "PERSISTENT_ANALYSIS_CACHE_SCHEMA_VERSION",
    "InvalidPersistentAnalysisCacheError",
    "PersistentAnalysisCacheError",
    "PersistentGCodeAnalysisCache",
    "UnsupportedPersistentAnalysisCacheError",
    "DEFAULT_MAXIMUM_PRESLICE_CACHE_ENTRIES",
    "PRESLICE_CACHE_SCHEMA_VERSION",
    "PreSliceCache",
    "PreSliceCacheEntry",
]
