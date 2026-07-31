from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from cooling_tower.models import OccupiedBounds
from cooling_tower.preview.models import LineSegment3D


PREVIEW_SOURCE_CACHE_SCHEMA_VERSION = 1
DEFAULT_PREVIEW_SOURCE_CACHE_ENTRIES = 2


def _is_sha256(value: str) -> bool:
    if len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


@dataclass(frozen=True, slots=True)
class PreviewSourceCacheKey:
    """Identify one exact source-file version and preview sampling contract."""

    source_path: Path
    file_size_bytes: int
    file_modified_ns: int
    content_sha256: str
    analysis_schema_version: int
    parser_version: int
    expected_layer_count: int
    maximum_segments: int
    cache_schema_version: int = PREVIEW_SOURCE_CACHE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_path",
            Path(self.source_path).expanduser().resolve(),
        )
        normalized_digest = str(self.content_sha256).casefold()
        if not _is_sha256(normalized_digest):
            raise ValueError("content_sha256 must be a hexadecimal SHA-256 digest")
        object.__setattr__(self, "content_sha256", normalized_digest)
        if self.file_size_bytes < 0:
            raise ValueError("file_size_bytes must not be negative")
        if self.file_modified_ns < 0:
            raise ValueError("file_modified_ns must not be negative")
        if self.analysis_schema_version < 1:
            raise ValueError("analysis_schema_version must be positive")
        if self.parser_version < 1:
            raise ValueError("parser_version must be positive")
        if self.expected_layer_count < 1:
            raise ValueError("expected_layer_count must be positive")
        if self.maximum_segments < 100:
            raise ValueError("maximum_segments must be at least 100")
        if self.cache_schema_version != PREVIEW_SOURCE_CACHE_SCHEMA_VERSION:
            raise ValueError("Unsupported preview source cache schema version")

    @property
    def source_version(self) -> tuple[Path, int, int, str, int, int, int]:
        return (
            self.source_path,
            self.file_size_bytes,
            self.file_modified_ns,
            self.content_sha256,
            self.analysis_schema_version,
            self.parser_version,
            self.cache_schema_version,
        )


@dataclass(frozen=True, slots=True)
class PreviewSourceData:
    """Immutable source-derived data reusable across preview settings."""

    key: PreviewSourceCacheKey
    object_segments: tuple[LineSegment3D, ...]
    source_segment_count: int
    occupied_bounds: OccupiedBounds

    def __post_init__(self) -> None:
        if not isinstance(self.object_segments, tuple):
            raise TypeError("object_segments must be an immutable tuple")
        if not self.object_segments:
            raise ValueError("object_segments must not be empty")
        if len(self.object_segments) > self.key.maximum_segments:
            raise ValueError("object_segments exceed the configured cache limit")
        if self.source_segment_count < len(self.object_segments):
            raise ValueError(
                "source_segment_count must cover every displayed segment"
            )


class PreviewSourceDataCache:
    """Small thread-safe LRU cache for versioned source preview data."""

    def __init__(
        self,
        maximum_entries: int = DEFAULT_PREVIEW_SOURCE_CACHE_ENTRIES,
    ) -> None:
        if maximum_entries < 1:
            raise ValueError("maximum_entries must be at least one")
        self.maximum_entries = int(maximum_entries)
        self._entries: OrderedDict[
            PreviewSourceCacheKey,
            PreviewSourceData,
        ] = OrderedDict()
        self._lock = RLock()

    def get(self, key: PreviewSourceCacheKey) -> PreviewSourceData | None:
        with self._lock:
            value = self._entries.get(key)
            if value is not None:
                self._entries.move_to_end(key)
            return value

    def put(self, value: PreviewSourceData) -> None:
        key = value.key
        with self._lock:
            # A changed file version must not leave stale variants of the same
            # path resident. Sampling variants of the current version may
            # coexist until normal LRU eviction.
            stale_keys = tuple(
                candidate
                for candidate in self._entries
                if candidate.source_path == key.source_path
                and candidate.source_version != key.source_version
            )
            for stale_key in stale_keys:
                self._entries.pop(stale_key, None)
            self._entries[key] = value
            self._entries.move_to_end(key)
            while len(self._entries) > self.maximum_entries:
                self._entries.popitem(last=False)

    def invalidate_path(self, source_path: str | Path) -> None:
        resolved = Path(source_path).expanduser().resolve()
        with self._lock:
            stale_keys = tuple(
                key for key in self._entries if key.source_path == resolved
            )
            for stale_key in stale_keys:
                self._entries.pop(stale_key, None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def keys(self) -> tuple[PreviewSourceCacheKey, ...]:
        """Return an oldest-to-newest snapshot for diagnostics and tests."""

        with self._lock:
            return tuple(self._entries)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
