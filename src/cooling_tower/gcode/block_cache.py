from __future__ import annotations

import math
import struct
import time
import zlib
from collections import OrderedDict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, fields, replace
from enum import Enum
from threading import RLock

from cooling_tower.gcode.parser import (
    Dwell,
    MachineState,
    MachineStateTracker,
    Movement,
    ParsedGCodeLine,
)


TimedSourceEvent = Movement | Dwell | None
_CACHE_FORMAT_VERSION = 1
_MASK_64 = (1 << 64) - 1
_STATE_FIELDS = tuple(field.name for field in fields(MachineState))


class BlockCachePolicy(str, Enum):
    """Runtime policy for the exact Python event cache."""

    AUTO = "auto"
    ENABLED = "enabled"
    BYPASSED = "bypassed"


@dataclass(frozen=True, slots=True)
class BlockCacheAnalysisStats:
    """Per-analysis counters; values from separate scans never overlap."""

    configured_policy: BlockCachePolicy
    effective_policy: BlockCachePolicy
    bypass_reason: str | None
    workload_bytes: int
    processed_lines: int
    processed_blocks: int
    hits: int
    misses: int
    evictions: int
    occupied_bytes_before: int
    occupied_bytes_after: int
    attempted_insert_bytes: int
    avoided_insertions: int
    estimated_avoided_bytes: int
    cache_time_s: float
    analysis_time_s: float | None = None


def _exact_state_atom(value: object) -> object:
    if isinstance(value, float):
        return struct.pack("!d", value)
    return value


def _state_signature(state: MachineState) -> tuple[object, ...]:
    return tuple(
        _exact_state_atom(getattr(state, field_name))
        for field_name in _STATE_FIELDS
    )


@dataclass(frozen=True, slots=True)
class _CacheKey:
    format_version: int
    bambu_compatible: bool
    incoming_state: tuple[object, ...]
    source_lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _CacheEntry:
    ending_state: MachineState
    events: tuple[TimedSourceEvent, ...]
    estimated_bytes: int


class ExactGCodeBlockCache:
    """Bounded, collision-safe in-memory cache for unchanged G-code blocks.

    Content-defined boundaries re-synchronise after insertions, so unchanged
    source-object regions can hit even when a preceding tower region has a
    different number of lines. Every hit compares all original line strings
    and the bit-exact incoming machine state. Nothing is persisted between app
    sessions and the complete new G-code file is still read and parsed.
    """

    def __init__(
        self,
        *,
        maximum_bytes: int = 256 * 1024 * 1024,
        minimum_lines: int = 64,
        average_lines: int = 128,
        maximum_lines: int = 256,
        policy: BlockCachePolicy | str = BlockCachePolicy.AUTO,
    ) -> None:
        if maximum_bytes < 1024 * 1024:
            raise ValueError("maximum_bytes must be at least 1 MiB.")
        if not 1 <= minimum_lines <= average_lines <= maximum_lines:
            raise ValueError("Invalid content-defined block sizes.")
        if average_lines & (average_lines - 1):
            raise ValueError("average_lines must be a power of two.")
        self.maximum_bytes = maximum_bytes
        self.minimum_lines = minimum_lines
        self.average_lines = average_lines
        self.maximum_lines = maximum_lines
        self.policy = BlockCachePolicy(policy)
        self._entries: OrderedDict[_CacheKey, _CacheEntry] = OrderedDict()
        self._bytes = 0
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._auto_bypass_minimum_bytes: dict[bool, int] = {}
        self._last_analysis: BlockCacheAnalysisStats | None = None
        self._lock = RLock()

    def iter_events(
        self,
        parsed_lines: Iterable[ParsedGCodeLine],
        tracker: MachineStateTracker,
        *,
        workload_bytes: int = 0,
    ) -> Iterator[tuple[ParsedGCodeLine, TimedSourceEvent]]:
        if workload_bytes < 0:
            raise ValueError("workload_bytes must not be negative")
        with self._lock:
            # A cancelled scan must never expose the previous scan's per-run
            # counters as if they belonged to the aborted operation.
            self._last_analysis = None
            hits_before = self._hits
            misses_before = self._misses
            evictions_before = self._evictions
            occupied_before = self._bytes
            learned_threshold = self._auto_bypass_minimum_bytes.get(
                tracker.bambu_compatible
            )
        bypass_reason: str | None = None
        bypassed = self.policy is BlockCachePolicy.BYPASSED
        if bypassed:
            bypass_reason = "forced"
        elif (
            self.policy is BlockCachePolicy.AUTO
            and learned_threshold is not None
            and workload_bytes >= learned_threshold
        ):
            bypassed = True
            bypass_reason = "previous_comparable_scan_thrashed"

        processed_lines = 0
        processed_blocks = 0
        attempted_insert_bytes = 0
        avoided_insertions = 0
        estimated_avoided_bytes = 0
        cache_time_s = 0.0

        if bypassed:
            for parsed_line in parsed_lines:
                processed_lines += 1
                event = tracker.process_line(parsed_line)
                if event is not None:
                    estimated_avoided_bytes += 1_536
                estimated_avoided_bytes += 64 + len(parsed_line.raw_text) * 2
                yield parsed_line, event
            avoided_insertions = (
                math.ceil(processed_lines / self.average_lines)
                if processed_lines else 0
            )
        else:
            store_entries = True
            for block in self._content_defined_blocks(parsed_lines):
                processed_blocks += 1
                processed_lines += len(block)
                if store_entries:
                    (
                        _hit,
                        attempted_bytes,
                        block_cache_time_s,
                    ) = yield from self._events_for_block(block, tracker)
                    attempted_insert_bytes += attempted_bytes
                    cache_time_s += block_cache_time_s
                else:
                    events = tuple(tracker.process_line(parsed) for parsed in block)
                    avoided_insertions += 1
                    estimated_avoided_bytes += self._estimate_entry_bytes_from_block(
                        block,
                        events,
                    )
                    yield from zip(block, events)

                if (
                    store_entries
                    and self.policy is BlockCachePolicy.AUTO
                    and workload_bytes >= 1024 * 1024
                ):
                    with self._lock:
                        analysis_hits = self._hits - hits_before
                        analysis_misses = self._misses - misses_before
                        analysis_evictions = self._evictions - evictions_before
                    practically_no_hits = analysis_hits <= max(
                        1,
                        (analysis_hits + analysis_misses) // 100,
                    )
                    if (
                        analysis_misses >= 64
                        and analysis_evictions >= 8
                        and attempted_insert_bytes
                        >= round(self.maximum_bytes * 1.05)
                        and practically_no_hits
                    ):
                        store_entries = False
                        bypassed = True
                        bypass_reason = "sequential_scan_thrash"
                        with self._lock:
                            previous = self._auto_bypass_minimum_bytes.get(
                                tracker.bambu_compatible
                            )
                            threshold = max(1024 * 1024, workload_bytes // 2)
                            self._auto_bypass_minimum_bytes[
                                tracker.bambu_compatible
                            ] = (
                                threshold
                                if previous is None
                                else min(previous, threshold)
                            )
                            # Thrashing entries have no demonstrated reuse value
                            # and otherwise retain the complete memory penalty.
                            self._entries.clear()
                            self._bytes = 0

        with self._lock:
            self._last_analysis = BlockCacheAnalysisStats(
                configured_policy=self.policy,
                effective_policy=(
                    BlockCachePolicy.BYPASSED
                    if bypassed else BlockCachePolicy.ENABLED
                ),
                bypass_reason=bypass_reason,
                workload_bytes=workload_bytes,
                processed_lines=processed_lines,
                processed_blocks=processed_blocks,
                hits=self._hits - hits_before,
                misses=self._misses - misses_before,
                evictions=self._evictions - evictions_before,
                occupied_bytes_before=occupied_before,
                occupied_bytes_after=self._bytes,
                attempted_insert_bytes=attempted_insert_bytes,
                avoided_insertions=avoided_insertions,
                estimated_avoided_bytes=estimated_avoided_bytes,
                cache_time_s=cache_time_s,
            )

    def _content_defined_blocks(
        self,
        parsed_lines: Iterable[ParsedGCodeLine],
    ) -> Iterator[tuple[ParsedGCodeLine, ...]]:
        block: list[ParsedGCodeLine] = []
        fingerprint = 0
        boundary_mask = self.average_lines - 1
        for parsed_line in parsed_lines:
            block.append(parsed_line)
            # Stable boundaries must not depend on Python's process-randomized
            # string hash. Exact equality is established separately by
            # _CacheKey.source_lines, so CRC32 only selects boundaries.
            fingerprint = (
                ((fingerprint << 1) & _MASK_64)
                ^ zlib.crc32(parsed_line.raw_text.encode("utf-8"))
            )
            count = len(block)
            if count < self.minimum_lines:
                continue
            if (fingerprint & boundary_mask) != 0 and count < self.maximum_lines:
                continue
            yield tuple(block)
            block.clear()
            fingerprint = 0
        if block:
            yield tuple(block)

    def _events_for_block(
        self,
        block: tuple[ParsedGCodeLine, ...],
        tracker: MachineStateTracker,
    ) -> Iterator[tuple[ParsedGCodeLine, TimedSourceEvent]]:
        cache_started = time.perf_counter()
        key = _CacheKey(
            format_version=_CACHE_FORMAT_VERSION,
            bambu_compatible=tracker.bambu_compatible,
            incoming_state=_state_signature(tracker.state),
            source_lines=tuple(parsed.raw_text for parsed in block),
        )
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                self._entries.move_to_end(key)
                self._hits += 1
        lookup_time_s = time.perf_counter() - cache_started
        if entry is not None:
            tracker.state = replace(entry.ending_state)
            for parsed_line, event in zip(block, entry.events):
                if (
                    event is not None
                    and event.line_number != parsed_line.number
                ):
                    # Cache entries are private to this serialized analysis
                    # service. Rebinding this presentation-only source index
                    # avoids reconstructing the large immutable movement for
                    # every hit after a changed tower shifted later lines.
                    # No timing, geometry, or machine-state field is changed.
                    object.__setattr__(
                        event,
                        "line_number",
                        parsed_line.number,
                    )
                yield parsed_line, event
            return True, 0, lookup_time_s

        events = tuple(tracker.process_line(parsed) for parsed in block)
        insertion_started = time.perf_counter()
        entry = _CacheEntry(
            ending_state=replace(tracker.state),
            events=events,
            estimated_bytes=self._estimate_entry_bytes(key, events),
        )
        with self._lock:
            self._misses += 1
            if entry.estimated_bytes <= self.maximum_bytes:
                existing = self._entries.pop(key, None)
                if existing is not None:
                    self._bytes -= existing.estimated_bytes
                self._entries[key] = entry
                self._bytes += entry.estimated_bytes
                self._evict_if_needed()
        yield from zip(block, events)
        return (
            False,
            entry.estimated_bytes,
            lookup_time_s + time.perf_counter() - insertion_started,
        )

    @staticmethod
    def _estimate_entry_bytes(
        key: _CacheKey,
        events: tuple[TimedSourceEvent, ...],
    ) -> int:
        # Deliberately conservative accounting keeps the cache bounded without
        # recursively walking immutable object graphs on the analysis hot path.
        text_bytes = sum(64 + len(line) * 2 for line in key.source_lines)
        event_bytes = sum(1_536 for event in events if event is not None)
        return 1024 + text_bytes + event_bytes

    @staticmethod
    def _estimate_entry_bytes_from_block(
        block: tuple[ParsedGCodeLine, ...],
        events: tuple[TimedSourceEvent, ...],
    ) -> int:
        text_bytes = sum(64 + len(item.raw_text) * 2 for item in block)
        event_bytes = sum(1_536 for event in events if event is not None)
        return 1024 + text_bytes + event_bytes

    def _evict_if_needed(self) -> None:
        while self._bytes > self.maximum_bytes and self._entries:
            _key, entry = self._entries.popitem(last=False)
            self._bytes -= entry.estimated_bytes
            self._evictions += 1

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._bytes = 0
            self._hits = 0
            self._misses = 0
            self._evictions = 0
            self._auto_bypass_minimum_bytes.clear()
            self._last_analysis = None

    def record_analysis_time(self, duration_s: float) -> None:
        """Attach the complete analysis duration to the latest cache scan."""

        with self._lock:
            if self._last_analysis is not None:
                self._last_analysis = replace(
                    self._last_analysis,
                    analysis_time_s=max(0.0, float(duration_s)),
                )

    def last_analysis_stats(self) -> BlockCacheAnalysisStats | None:
        with self._lock:
            return self._last_analysis

    def info(self) -> dict[str, int | float | str | None]:
        with self._lock:
            result: dict[str, int | float | str | None] = {
                "hits": self._hits,
                "misses": self._misses,
                "entries": len(self._entries),
                "bytes": self._bytes,
                "evictions": self._evictions,
                "configured_policy": self.policy.value,
            }
            if self._last_analysis is not None:
                result.update(
                    {
                        "last_effective_policy": (
                            self._last_analysis.effective_policy.value
                        ),
                        "last_bypass_reason": self._last_analysis.bypass_reason,
                        "last_avoided_insertions": (
                            self._last_analysis.avoided_insertions
                        ),
                        "last_estimated_avoided_bytes": (
                            self._last_analysis.estimated_avoided_bytes
                        ),
                        "last_cache_time_s": self._last_analysis.cache_time_s,
                        "last_analysis_time_s": (
                            self._last_analysis.analysis_time_s
                        ),
                    }
                )
            return result
