from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import struct

from cooling_tower.models import SourceKind


SOURCE_SNIFF_LIMIT_BYTES = 1024 * 1024

_ASCII_STL_FACET = re.compile(rb"(?im)^\s*facet\s+normal\s+")
_ASCII_STL_VERTEX = re.compile(rb"(?im)^\s*vertex\s+")


class SourceRecognitionError(ValueError):
    """A selected file is unsupported or contradicts its extension."""


@dataclass(frozen=True, slots=True)
class SourceRecognitionResult:
    path: Path
    source_kind: SourceKind
    size_bytes: int
    format_description: str


def recognize_source(path: str | Path) -> SourceRecognitionResult:
    """Recognize one supported source using extension and bounded content.

    This is intentionally a fast routing check. Strict STL topology
    validation remains a separate background operation.
    """

    candidate = Path(path).expanduser().resolve(strict=True)
    if not candidate.is_file():
        raise SourceRecognitionError("Die ausgewählte Quelle ist keine Datei.")
    try:
        kind = SourceKind.from_path(candidate)
    except ValueError as error:
        raise SourceRecognitionError(str(error)) from error
    size = candidate.stat().st_size
    if size == 0:
        raise SourceRecognitionError("Die ausgewählte Datei ist leer.")
    with candidate.open("rb") as handle:
        prefix = handle.read(SOURCE_SNIFF_LIMIT_BYTES)

    description = _recognize_stl_container(prefix, size)
    return SourceRecognitionResult(candidate, kind, size, description)


def _recognize_stl_container(prefix: bytes, total_size: int) -> str:
    if _looks_like_ascii_stl(prefix):
        return "ASCII-STL"
    if total_size >= 84 and len(prefix) >= 84:
        triangle_count = struct.unpack_from("<I", prefix, 80)[0]
        expected_size = 84 + triangle_count * 50
        if expected_size == total_size and triangle_count > 0:
            return "Binär-STL"
    raise SourceRecognitionError(
        "Die .stl-Datei besitzt weder ein gültiges ASCII- noch Binär-STL-Format."
    )


def _looks_like_ascii_stl(prefix: bytes) -> bool:
    stripped = prefix.lstrip(b"\xef\xbb\xbf\x00\t\r\n ")
    return (
        stripped[:5].lower() == b"solid"
        and _ASCII_STL_FACET.search(prefix) is not None
        and len(_ASCII_STL_VERTEX.findall(prefix)) >= 3
    )
