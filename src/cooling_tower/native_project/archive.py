"""Bounded OPC/3MF access without extracting paths or resolving external input."""
from __future__ import annotations

from dataclasses import dataclass
import posixpath
from pathlib import Path, PurePosixPath
import stat
import struct
import unicodedata
from xml.etree import ElementTree as ET
import zipfile
import zlib


_OPTIONAL_PREVIEW_RELATIONSHIPS = frozenset({
    "http://schemas.openxmlformats.org/package/2006/relationships/metadata/thumbnail",
    "http://schemas.bambulab.com/package/2021/cover-thumbnail-middle",
    "http://schemas.bambulab.com/package/2021/cover-thumbnail-small",
})


class ProjectArchiveError(ValueError):
    """A damaged or unsafe container, distinct from an incomplete project."""


@dataclass(frozen=True, slots=True)
class ArchiveLimits:
    container_bytes: int = 2 * 1024**3
    expanded_bytes: int = 4 * 1024**3
    member_bytes: int = 1024**3
    metadata_bytes: int = 32 * 1024**2
    members: int = 100_000
    directory_bytes: int = 32 * 1024**2


def _preflight_directory(path: Path, limits: ArchiveLimits) -> None:
    """Bound ZIP metadata *before* ZipFile creates a ZipInfo per entry."""
    size = path.stat().st_size
    if size > limits.container_bytes:
        raise ProjectArchiveError("Das Projekt überschreitet die zulässige Archivgröße.")
    with path.open("rb") as stream:
        stream.seek(max(0, size - 65557))
        tail = stream.read(65557)
        offset = tail.rfind(b"PK\x05\x06")
        if offset < 0 or len(tail) - offset < 22:
            raise ProjectArchiveError("Das Projektarchiv besitzt keinen gültigen ZIP-Abschluss.")
        _, disk, directory_disk, disk_count, count, directory_size, directory_offset, comment_size = struct.unpack_from("<4s4H2LH", tail, offset)
        if offset + 22 + comment_size != len(tail) or disk or directory_disk or disk_count != count:
            raise ProjectArchiveError("Das Projektarchiv besitzt eine ungültige oder mehrteilige ZIP-Struktur.")
        end_offset = size - len(tail) + offset
        if count == 0xffff or directory_size == 0xffffffff or directory_offset == 0xffffffff:
            if end_offset < 20:
                raise ProjectArchiveError("Die ZIP64-Verzeichnisangaben fehlen.")
            stream.seek(end_offset - 20)
            locator = stream.read(20)
            signature, disk, zip64_offset, disks = struct.unpack("<4sLQL", locator)
            if signature != b"PK\x06\x07" or disk or disks != 1 or zip64_offset + 56 > end_offset:
                raise ProjectArchiveError("Die ZIP64-Verzeichnisangaben sind ungültig.")
            stream.seek(zip64_offset)
            record = stream.read(56)
            if len(record) != 56:
                raise ProjectArchiveError("Der ZIP64-Abschluss ist beschädigt.")
            signature, record_size, _, _, disk, directory_disk, disk_count, count, directory_size, directory_offset = struct.unpack("<4sQ2H2L4Q", record)
            if signature != b"PK\x06\x06" or record_size < 44 or disk or directory_disk or disk_count != count:
                raise ProjectArchiveError("Der ZIP64-Abschluss ist ungültig.")
        if count > limits.members or directory_size > limits.directory_bytes:
            raise ProjectArchiveError("Das Projekt überschreitet die Archiv-Verzeichnisgrenze.")
        if directory_offset + directory_size > end_offset:
            raise ProjectArchiveError("Das ZIP-Verzeichnis verlässt das Projektarchiv.")
        stream.seek(directory_offset)
        directory = stream.read(directory_size)
        position = entries = 0
        while position < len(directory):
            if position + 46 > len(directory) or directory[position:position + 4] != b"PK\x01\x02":
                raise ProjectArchiveError("Das ZIP-Verzeichnis ist beschädigt.")
            name_size, extra_size, comment_size = struct.unpack_from("<3H", directory, position + 28)
            position += 46 + name_size + extra_size + comment_size
            entries += 1
            if position > len(directory) or entries > limits.members:
                raise ProjectArchiveError("Das ZIP-Verzeichnis besitzt ungültige Eintragsgrößen.")
        if entries != count:
            raise ProjectArchiveError("Die Eintragszahl des ZIP-Verzeichnisses stimmt nicht.")


class _SafeTreeBuilder(ET.TreeBuilder):
    def __init__(self):
        super().__init__()
        self._nodes = self._depth = 0

    def start(self, tag, attrs):
        self._nodes += 1
        self._depth += 1
        if self._nodes > 250_000 or self._depth > 128:
            raise ProjectArchiveError('Die XML-Projektbeschreibung überschreitet die Strukturgrenze.')
        return super().start(tag, attrs)

    def end(self, tag):
        value = super().end(tag)
        self._depth -= 1
        return value

    def doctype(self, *_: object) -> None:
        raise ProjectArchiveError("XML-Dokumenttypen und externe Entitäten sind nicht zulässig.")


def parse_xml(data: bytes) -> ET.Element:
    try:
        return ET.fromstring(data, parser=ET.XMLParser(target=_SafeTreeBuilder()))
    except ET.ParseError as error:
        raise ProjectArchiveError("Eine XML-Projektdatei ist beschädigt.") from error


def _member_name(name: str) -> str:
    if not name or "\x00" in name or "\\" in name or ":" in name:
        raise ProjectArchiveError("Das Projektarchiv enthält einen unsicheren Dateipfad.")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {".", ".."} for part in name.rstrip("/").split("/")):
        raise ProjectArchiveError("Das Projektarchiv enthält einen Pfadausbruch.")
    if any(not part or part.endswith((".", " ")) for part in name.rstrip("/").split("/")):
        raise ProjectArchiveError("Das Projektarchiv enthält einen mehrdeutigen Dateipfad.")
    for part in path.parts:
        stem = part.split(".", 1)[0].upper()
        if stem in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
            raise ProjectArchiveError("Das Projektarchiv enthält einen Windows-Gerätepfad.")
    return name


class ProjectArchive:
    def __init__(self, path: str | Path, *, limits: ArchiveLimits | None = None) -> None:
        self.path = Path(path)
        self.limits = limits or ArchiveLimits()
        self._archive: zipfile.ZipFile | None = None
        self._entries: dict[str, zipfile.ZipInfo] = {}
        self._read_bytes = 0
        self._verified: set[str] = set()

    def __enter__(self) -> ProjectArchive:
        try:
            _preflight_directory(self.path, self.limits)
            self._archive = zipfile.ZipFile(self.path)
            infos = self._archive.infolist()
            if len(infos) > self.limits.members:
                raise ProjectArchiveError("Das Projekt enthält zu viele Archiveinträge.")
            expanded = 0
            aliases: set[str] = set()
            for info in infos:
                # ZipInfo normalizes the host separator and truncates at NUL;
                # validate its original central-directory spelling as well.
                _member_name(info.orig_filename)
                name = _member_name(info.filename)
                alias = unicodedata.normalize("NFC", name.rstrip("/")).casefold()
                if alias in aliases:
                    raise ProjectArchiveError("Das Projekt enthält doppelte oder mehrdeutige Archiveinträge.")
                aliases.add(alias)
                if stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1:
                    raise ProjectArchiveError("Verknüpfte oder verschlüsselte Archiveinträge sind nicht zulässig.")
                if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                    raise ProjectArchiveError("Das Projekt verwendet eine nicht unterstützte ZIP-Kompression.")
                expanded += info.file_size
                if info.file_size > self.limits.member_bytes or expanded > self.limits.expanded_bytes:
                    raise ProjectArchiveError("Das entpackte Projekt überschreitet die Ressourcengrenze.")
                self._entries[name] = info
            file_names = {n.casefold() for n, i in self._entries.items() if not i.is_dir()}
            if any(any(str(parent).casefold() in file_names for parent in PurePosixPath(n).parents if str(parent) != ".")
                   for n in self._entries):
                raise ProjectArchiveError("Ein Archiveintrag wird zugleich als Datei und Verzeichnis verwendet.")
            return self
        except (OSError, UnicodeError, struct.error, zipfile.BadZipFile, NotImplementedError) as error:
            self.close()
            raise ProjectArchiveError("Die 3MF-Datei ist kein lesbares ZIP-Projektarchiv.") from error
        except BaseException:
            self.close()
            raise

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._entries)

    def iter_bytes(self, name: str):
        """Stream a model with bounded memory and CRC verification."""
        if self._archive is None:
            raise RuntimeError("ProjectArchive is not open.")
        try:
            info = self._entries[name]
            read_size = 0
            with self._archive.open(info) as stream:
                while block := stream.read(1024 * 1024):
                    read_size += len(block)
                    self._read_bytes += len(block)
                    if read_size > self.limits.member_bytes or self._read_bytes > self.limits.expanded_bytes:
                        raise ProjectArchiveError("Die Projektverarbeitung überschreitet die Ressourcengrenze.")
                    yield block
            if read_size != info.file_size:
                raise ProjectArchiveError("Die entpackte Modellgröße stimmt nicht.")
            self._verified.add(name)
        except (KeyError, OSError, zipfile.BadZipFile, zlib.error, EOFError) as error:
            raise ProjectArchiveError("Eine native Modelldatei fehlt oder ist beschädigt.") from error

    def read(self, name: str, *, metadata: bool = False) -> bytes:
        if self._archive is None:
            raise RuntimeError("ProjectArchive is not open.")
        try:
            info = self._entries[name]
        except KeyError as error:
            raise ProjectArchiveError("Eine referenzierte interne Projektdatei fehlt.") from error
        bound = self.limits.metadata_bytes if metadata else self.limits.member_bytes
        if info.file_size > bound:
            raise ProjectArchiveError("Eine Projektdatei überschreitet die Ressourcengrenze.")
        try:
            with self._archive.open(info) as stream:
                data = stream.read(bound + 1)
            if len(data) != info.file_size or len(data) > bound:
                raise ProjectArchiveError("Eine Projektdatei besitzt eine ungültige entpackte Größe.")
            self._read_bytes += len(data)
            if self._read_bytes > self.limits.expanded_bytes:
                raise ProjectArchiveError("Die Projektverarbeitung überschreitet die Ressourcengrenze.")
            self._verified.add(name)
            return data
        except (OSError, zipfile.BadZipFile, zlib.error, RuntimeError, EOFError) as error:
            raise ProjectArchiveError("Eine Projektdatei ist beschädigt oder ihre Prüfsumme stimmt nicht.") from error

    def xml(self, name: str, *, metadata: bool = True) -> ET.Element:
        return parse_xml(self.read(name, metadata=metadata))

    def relationship_target(self, relationship_file: str, target: str, *, require_exists: bool = True) -> str:
        """Resolve an OPC target in the archive namespace, never on the host."""
        if not target or "\\" in target or ":" in target or "\x00" in target or "?" in target or "#" in target:
            raise ProjectArchiveError("Externe oder mehrdeutige Projektverweise sind nicht zulässig.")
        # OPC targets may use percent-encoded Unicode and spaces. Decode before
        # path validation so an encoded traversal cannot bypass this boundary.
        from urllib.parse import unquote
        try:
            decoded = unquote(target, encoding="utf-8", errors="strict")
        except UnicodeError as error:
            raise ProjectArchiveError('Der Projektverweis enthält ungültiges UTF-8.') from error
        if ":" in decoded or "\\" in decoded:
            raise ProjectArchiveError("Der Projektverweis verlässt das Archiv.")
        if decoded.startswith("/"):
            resolved = decoded[1:]
        else:
            rel = PurePosixPath(relationship_file)
            base = rel.parent.parent if rel.parent.name == "_rels" else rel.parent
            resolved = posixpath.normpath(posixpath.join(str(base), decoded))
        _member_name(resolved)
        if require_exists and resolved not in self._entries:
            raise ProjectArchiveError("Eine referenzierte interne Projektdatei fehlt.")
        return resolved

    def check_relationships(self) -> None:
        for name in self.names:
            if not name.endswith(".rels"):
                continue
            for relation in self.xml(name):
                if relation.get("TargetMode", "Internal").casefold() != "internal":
                    raise ProjectArchiveError("Das Projekt verweist auf eine externe Datei oder Adresse.")
                # The installed native exporter may retain preview relationships
                # when thumbnails were not rendered. Geometry relationships are
                # still mandatory; absent optional images are never loaded.
                self.relationship_target(name, relation.get("Target", ""),
                    require_exists=relation.get("Type") not in _OPTIONAL_PREVIEW_RELATIONSHIPS)

    def verify_remaining_members(self) -> None:
        """Check CRCs of auxiliary parts too, streaming without extracting."""
        for name in self.names:
            if name not in self._verified:
                for _ in self.iter_bytes(name):
                    pass

    def close(self) -> None:
        if self._archive is not None:
            self._archive.close()
            self._archive = None

    def __exit__(self, *_: object) -> None:
        self.close()
