"""Read-only PrusaSlicer FFF profile inventory and inheritance handling."""
from __future__ import annotations

import configparser
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from cooling_tower.slicers.base import classify_profile_source
from cooling_tower.slicers.errors import SlicerProcessError
from cooling_tower.slicers.models import (
    ProfileKind,
    ProfileRecord,
    SlicerInstallation,
)
from cooling_tower.slicers.profile_models import stable_json_fingerprint


_MAXIMUM_PROFILE_FILE_BYTES = 32 * 1024 * 1024
_MAXIMUM_PROFILE_FILES = 2_000
_FLAT_SECTION = "__prusa_flat_profile__"
_SECTION_KINDS = {
    "printer": ProfileKind.MACHINE,
    "printer_model": ProfileKind.MACHINE,
    "print": ProfileKind.PROCESS,
    "filament": ProfileKind.FILAMENT,
}
_USER_DIRECTORY_KINDS = {
    "printer": ProfileKind.MACHINE,
    "print": ProfileKind.PROCESS,
    "filament": ProfileKind.FILAMENT,
}
_PROFILE_MARKERS = {
    ProfileKind.MACHINE: {
        "inherits",
        "printer_model",
        "printer_variant",
        "printer_technology",
        "nozzle_diameter",
        "bed_shape",
        "max_print_height",
        "gcode_flavor",
        "extruder_count",
    },
    ProfileKind.PROCESS: {
        "inherits",
        "layer_height",
        "first_layer_height",
        "perimeters",
        "fill_density",
        "fill_pattern",
        "support_material",
    },
    ProfileKind.FILAMENT: {
        "inherits",
        "filament_type",
        "filament_diameter",
        "filament_density",
        "temperature",
        "bed_temperature",
        "filament_vendor",
    },
}
_PROFILE_METADATA_KEYS = (
    "instantiation",
    "compatible_printers",
    "compatible_printers_condition",
    "printer_model",
    "printer_variant",
    "printer_technology",
    "nozzle_diameter",
    "gcode_flavor",
    "extruder_count",
    "printer_settings_id",
    "print_settings_id",
    "filament_settings_id",
    "setting_id",
    "setting_version",
)


@dataclass(frozen=True, slots=True)
class _IniDocument:
    modified_ns: int
    size_bytes: int
    sections: tuple[tuple[str, Mapping[str, str]], ...]
    flat_values: Mapping[str, str] | None


class PrusaProfileCatalog:
    """Parse each Prusa INI once and expose only actual FFF presets."""

    def __init__(self) -> None:
        self._documents: dict[Path, _IniDocument | None] = {}

    def discover_profiles(
        self,
        installation: SlicerInstallation,
    ) -> tuple[ProfileRecord, ...]:
        records: list[ProfileRecord] = []
        seen: set[Path] = set()
        files_seen = 0
        for root in installation.profile_roots:
            resolved_root = Path(root).resolve()
            if not resolved_root.is_dir():
                continue
            try:
                paths = resolved_root.rglob("*.ini")
                for candidate in paths:
                    if candidate.suffix.casefold() != ".ini":
                        continue
                    path = candidate.resolve()
                    if (
                        path in seen
                        or not path.is_file()
                        or not _is_within(path, resolved_root)
                    ):
                        continue
                    seen.add(path)
                    files_seen += 1
                    if files_seen > _MAXIMUM_PROFILE_FILES:
                        raise SlicerProcessError(
                            "Der PrusaSlicer-Profilkatalog enthält mehr als "
                            f"{_MAXIMUM_PROFILE_FILES} INI-Dateien und kann "
                            "nicht vollständig und sicher geladen werden."
                        )
                    document = self._document(path)
                    if document is None:
                        continue
                    records.extend(
                        self._records_for_document(installation, path, document)
                    )
            except OSError:
                # One unreadable optional catalogue must not hide profiles
                # already collected from the other supported roots.
                continue
        return tuple(
            sorted(
                records,
                key=lambda item: (
                    item.kind.value,
                    item.name.casefold(),
                    str(item.path).casefold(),
                    str(item.metadata.get("section", "")).casefold(),
                ),
            )
        )

    def profile_values(self, record: ProfileRecord) -> dict[str, str]:
        document = self._document(record.path)
        if document is None:
            return {}
        section = str(record.metadata.get("section", ""))
        if section:
            for name, values in document.sections:
                if name == section:
                    return dict(values)
            return {}
        if record.metadata.get("flat_profile") is True:
            return dict(document.flat_values or {})
        return {}

    def select_parent_records(
        self,
        candidates: Sequence[ProfileRecord],
        child: ProfileRecord,
    ) -> tuple[ProfileRecord, ...]:
        """Resolve vendor templates against their matching active catalogue."""

        selected = tuple(candidates)
        child_vendor = str(child.metadata.get("vendor", "")).casefold()
        if child_vendor:
            same_vendor = tuple(
                item
                for item in selected
                if str(item.metadata.get("vendor", "")).casefold()
                == child_vendor
            )
            if same_vendor:
                selected = same_vendor

        if child.source.casefold() == "user":
            current = tuple(
                item
                for item in selected
                if item.source.casefold() == "system"
                and item.metadata.get("catalog_origin") == "active_vendor"
            )
            if current:
                selected = current

        if len(selected) <= 1:
            return selected

        best_preference = min(_parent_preference(item) for item in selected)
        preferred = tuple(
            item
            for item in selected
            if _parent_preference(item) == best_preference
        )
        if len(preferred) <= 1:
            return preferred

        # Multiple repositories can ship the same template identifier. Only
        # collapse them when their parsed values are equivalent; conflicting
        # definitions remain invalid rather than inheriting arbitrary settings.
        fingerprints = {
            stable_json_fingerprint(self.profile_values(item))
            for item in preferred
        }
        if len(fingerprints) == 1:
            return (min(preferred, key=lambda item: str(item.path).casefold()),)
        return preferred

    def _document(self, path: Path) -> _IniDocument | None:
        try:
            statistics = path.stat()
        except OSError:
            return None
        resolved = path.resolve()
        cached = self._documents.get(resolved)
        if cached is not None and (
            cached.modified_ns == statistics.st_mtime_ns
            and cached.size_bytes == statistics.st_size
        ):
            return cached
        if statistics.st_size > _MAXIMUM_PROFILE_FILE_BYTES:
            self._documents[resolved] = None
            return None
        try:
            payload = path.read_bytes()
            if len(payload) > _MAXIMUM_PROFILE_FILE_BYTES:
                self._documents[resolved] = None
                return None
            text = _decode_profile(payload)
            if text is None:
                self._documents[resolved] = None
                return None
            parser = _new_parser()
            try:
                parser.read_string(text)
            except configparser.Error:
                parser = _new_parser()
                parser.read_string(f"[{_FLAT_SECTION}]\n{text}")
                sections: tuple[tuple[str, Mapping[str, str]], ...] = ()
                flat_values: Mapping[str, str] | None = dict(
                    parser.items(_FLAT_SECTION, raw=True)
                )
            else:
                sections = tuple(
                    (name, dict(parser.items(name, raw=True)))
                    for name in parser.sections()
                )
                flat_values = None
            document = _IniDocument(
                modified_ns=statistics.st_mtime_ns,
                size_bytes=statistics.st_size,
                sections=sections,
                flat_values=flat_values,
            )
            self._documents[resolved] = document
            return document
        except (OSError, UnicodeError, configparser.Error, ValueError):
            self._documents[resolved] = None
            return None

    def _records_for_document(
        self,
        installation: SlicerInstallation,
        path: Path,
        document: _IniDocument,
    ) -> tuple[ProfileRecord, ...]:
        result: list[ProfileRecord] = []
        source = classify_profile_source(installation, path)
        catalog_origin = _catalog_origin(path)
        vendor = path.stem if catalog_origin else ""
        for section, values in document.sections:
            prefix, separator, name = section.partition(":")
            kind = _SECTION_KINDS.get(prefix.casefold()) if separator else None
            if kind is None or not name.strip():
                continue
            result.append(
                self._make_record(
                    installation,
                    path,
                    name.strip(),
                    kind,
                    values,
                    source=source,
                    section=section,
                    vendor=vendor,
                    catalog_origin=catalog_origin,
                )
            )

        if document.sections or document.flat_values is None:
            return tuple(result)
        kind = _USER_DIRECTORY_KINDS.get(path.parent.name.casefold())
        if kind is None:
            return ()
        values = dict(document.flat_values)
        if not set(key.casefold() for key in values).intersection(
            _PROFILE_MARKERS[kind]
        ):
            return ()
        return (
            self._make_record(
                installation,
                path,
                path.stem,
                kind,
                values,
                source=source,
                section="",
                flat_profile=True,
            ),
        )

    @staticmethod
    def _make_record(
        installation: SlicerInstallation,
        path: Path,
        name: str,
        kind: ProfileKind,
        values: Mapping[str, str],
        *,
        source: str,
        section: str,
        vendor: str = "",
        catalog_origin: str = "",
        flat_profile: bool = False,
    ) -> ProfileRecord:
        normalized = {str(key).casefold(): value for key, value in values.items()}
        inherits = _split_inherits(normalized.get("inherits", ""))
        metadata = {
            "section": section,
            **{
                key: normalized[key]
                for key in _PROFILE_METADATA_KEYS
                if key in normalized
            },
        }
        if vendor:
            metadata["vendor"] = vendor
            metadata["catalog_origin"] = catalog_origin
        if flat_profile:
            metadata["flat_profile"] = True
        # Prusa hides wildcard sections such as [print:*common*] from the
        # selectable list while retaining them as inheritance parents.
        if _is_abstract_preset(name):
            metadata["instantiation"] = False
        return ProfileRecord(
            adapter_id=installation.adapter_id,
            profile_id=name,
            name=name,
            kind=kind,
            path=path,
            source=source,
            inherits=inherits,
            metadata=metadata,
        )


def _new_parser() -> configparser.ConfigParser:
    parser = configparser.ConfigParser(
        interpolation=None,
        strict=False,
        delimiters=("=",),
        comment_prefixes=("#", ";"),
    )
    parser.optionxform = str
    return parser


def _decode_profile(payload: bytes) -> str | None:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def _split_inherits(value: object) -> tuple[str, ...]:
    return tuple(
        item.strip().strip('"')
        for item in str(value or "").split(";")
        if item.strip().strip('"')
    )


def _catalog_origin(path: Path) -> str:
    appdata = os.environ.get("APPDATA")
    if appdata:
        active_vendor = (Path(appdata) / "PrusaSlicer" / "vendor").resolve()
        if _is_within(path, active_vendor):
            return "active_vendor"
    return "bundled" if "resources" in {part.casefold() for part in path.parts} else ""


def _parent_preference(record: ProfileRecord) -> tuple[int, int]:
    if record.source.casefold() == "user":
        source_rank = 0
    elif record.source.casefold() == "system":
        source_rank = 1
    else:
        source_rank = 2
    origin_rank = 0 if record.metadata.get("catalog_origin") == "active_vendor" else 1
    return source_rank, origin_rank


def _is_within(path: Path, root: Path) -> bool:
    try:
        return path == root or root in path.parents
    except (OSError, ValueError):
        return False


def _is_abstract_preset(name: str) -> bool:
    value = name.strip()
    return len(value) > 2 and value.startswith("*") and value.endswith("*")
