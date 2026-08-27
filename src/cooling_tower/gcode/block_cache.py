from __future__ import annotations

import struct
from collections import OrderedDict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, fields, replace
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
        self._entries: OrderedDict[_CacheKey, _CacheEntry] = OrderedDict()
        self._bytes = 0
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._lock = RLock()

    def iter_events(
        self,
        parsed_lines: Iterable[ParsedGCodeLine],
        tracker: MachineStateTracker,
    ) -> Iterator[tuple[ParsedGCodeLine, TimedSourceEvent]]:
        for block in self._content_defined_blocks(parsed_lines):
            yield from self._events_for_block(block, tracker)

    def _content_defined_blocks(
        self,
        parsed_lines: Iterable[ParsedGCodeLine],
    ) -> Iterator[tuple[ParsedGCodeLine, ...]]:
        block: list[ParsedGCodeLine] = []
        fingerprint = 0
        boundary_mask = self.average_lines - 1
        for parsed_line in parsed_lines:
            block.append(parsed_line)
            # Python's string hash runs in native code and remains stable for
            # the process lifetime. Exact equality is established separately
            # by _CacheKey.source_lines, so this value only selects boundaries.
            fingerprint = (
                ((fingerprint << 1) & _MASK_64)
                ^ (hash(parsed_line.raw_text) & _MASK_64)
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
            return

        events = tuple(tracker.process_line(parsed) for parsed in block)
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

    def info(self) -> dict[str, int]:
        with self._lock:
            return {
                "hits": self._hits,
                "misses": self._misses,
                "entries": len(self._entries),
                "bytes": self._bytes,
                "evictions": self._evictions,
            }
