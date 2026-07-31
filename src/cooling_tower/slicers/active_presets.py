from __future__ import annotations

import configparser
import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from cooling_tower.slicers.models import SlicerInstallation


_MAXIMUM_CONFIG_BYTES = 2 * 1024 * 1024
_ORCA_FAMILY_ADAPTERS = {
    "anycubic_slicer_next",
    "bambu_studio",
    "orca_slicer",
}
_CONFIG_NAMES = {
    "anycubic_slicer_next": ("AnycubicSlicerNext.conf",),
    "bambu_studio": ("BambuStudio.conf",),
    "orca_slicer": ("OrcaSlicer.conf",),
    "prusa_slicer": ("PrusaSlicer.ini",),
    "cura": ("cura.cfg",),
}


@dataclass(frozen=True, slots=True)
class ActivePresetSelection:
    printer_ids: tuple[str, ...] = ()
    process_ids: tuple[str, ...] = ()
    filament_ids: tuple[str, ...] = ()
    nozzle_diameters_mm: tuple[float, ...] = ()
    source_path: Path | None = None

    @property
    def has_printer_context(self) -> bool:
        return bool(self.printer_ids or self.nozzle_diameters_mm)

    @property
    def fingerprint_sha256(self) -> str:
        payload = json.dumps(
            {
                "printer_ids": self.printer_ids,
                "process_ids": self.process_ids,
                "filament_ids": self.filament_ids,
                "nozzle_diameters_mm": self.nozzle_diameters_mm,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


def read_active_presets(
    installation: SlicerInstallation,
) -> ActivePresetSelection:
    """Read the most recently persisted preset selection without modifying it."""

    candidates = _candidate_config_paths(installation)
    for path in sorted(
        candidates,
        key=lambda item: (_safe_modified_ns(item), str(item).casefold()),
        reverse=True,
    ):
        selection = _read_config(path, installation.adapter_id)
        if selection is not None and selection.has_printer_context:
            return selection
    return ActivePresetSelection()


def _candidate_config_paths(
    installation: SlicerInstallation,
) -> tuple[Path, ...]:
    names = _CONFIG_NAMES.get(installation.adapter_id, ())
    if not names:
        return ()
    directories: set[Path] = set()
    for root in installation.profile_roots:
        resolved = Path(root).resolve()
        directories.add(resolved)
        if resolved.name.casefold() in {
            "user",
            "profiles",
            "system",
        }:
            directories.add(resolved.parent)

    result: set[Path] = set()
    for directory in directories:
        for name in names:
            direct = directory / name
            if direct.is_file():
                result.add(direct.resolve())
        if installation.adapter_id == "cura" and directory.is_dir():
            # Cura keeps one configuration per version. Limit discovery to
            # the immediate version directories to avoid a broad recursive
            # scan of the complete profile tree.
            for path in directory.glob("*/cura.cfg"):
                if path.is_file():
                    result.add(path.resolve())
    return tuple(result)


def _read_config(
    path: Path,
    adapter_id: str,
) -> ActivePresetSelection | None:
    try:
        if path.stat().st_size > _MAXIMUM_CONFIG_BYTES:
            return None
        payload = path.read_bytes()
    except OSError:
        return None
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = payload.decode("cp1252")
        except UnicodeDecodeError:
            return None

    values = _parse_ini_values(text, adapter_id)
    if values is None:
        values = _parse_json_values(text)
    if values is None:
        return None
    return ActivePresetSelection(
        printer_ids=_unique_strings(values.get("printer", ())),
        process_ids=_unique_strings(values.get("process", ())),
        filament_ids=_unique_strings(values.get("filament", ())),
        nozzle_diameters_mm=_finite_numbers(values.get("nozzle", ())),
        source_path=path.resolve(),
    )


def _parse_ini_values(
    text: str,
    adapter_id: str,
) -> dict[str, tuple[Any, ...]] | None:
    parser = configparser.ConfigParser(
        interpolation=None,
        strict=False,
    )
    parser.optionxform = str
    try:
        parser.read_string(text)
    except configparser.Error:
        return None

    sections = {
        section.casefold(): {
            key.casefold(): value
            for key, value in parser.items(section)
        }
        for section in parser.sections()
    }
    if adapter_id in _ORCA_FAMILY_ADAPTERS or adapter_id == "prusa_slicer":
        preferred = tuple(
            values
            for name, values in sections.items()
            if name in {"presets", "preset"}
        )
        if not preferred:
            return None
        merged = _merge_sections(preferred)
        filament_values = _split_config_value(
            merged.get("filament") or merged.get("filament_preset")
        )
        if not filament_values:
            filament_values = tuple(
                item
                for key, value in sorted(merged.items())
                if re.fullmatch(r"filament_(?:preset_)?\d+", key)
                for item in _split_config_value(value)
            )
        return {
            "printer": _split_config_value(
                merged.get("printer") or merged.get("printer_preset")
            ),
            "process": _split_config_value(
                merged.get("print")
                or merged.get("process")
                or merged.get("print_preset")
            ),
            "filament": filament_values,
            "nozzle": _split_config_value(merged.get("nozzle_diameter")),
        }

    if adapter_id == "cura":
        preferred = tuple(
            values
            for name, values in sections.items()
            if name in {"cura", "general", "metadata"}
        )
        if not preferred:
            return None
        merged = _merge_sections(preferred)
        return {
            "printer": _split_config_value(
                merged.get("active_machine")
                or merged.get("machine")
                or merged.get("printer")
            ),
            "process": _split_config_value(
                merged.get("quality") or merged.get("quality_type")
            ),
            "filament": _split_config_value(
                merged.get("material") or merged.get("material_profile")
            ),
            "nozzle": _split_config_value(merged.get("nozzle_diameter")),
        }
    return None


def _parse_json_values(text: str) -> dict[str, tuple[Any, ...]] | None:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, Mapping):
        return None
    normalized = {str(key).casefold(): value for key, value in payload.items()}
    nested_presets = normalized.get("presets")
    if isinstance(nested_presets, Mapping):
        normalized.update(
            {
                str(key).casefold(): value
                for key, value in nested_presets.items()
            }
        )
    filament_value = normalized.get("filament") or normalized.get(
        "filament_preset"
    )
    if filament_value is None:
        filament_value = tuple(
            item
            for key, value in sorted(normalized.items())
            if re.fullmatch(r"filament_(?:preset_)?\d+", key)
            for item in _as_values(value)
        )
    return {
        "printer": _as_values(
            normalized.get("printer")
            or normalized.get("printer_preset")
            or normalized.get("active_machine")
        ),
        "process": _as_values(
            normalized.get("print")
            or normalized.get("process")
            or normalized.get("print_preset")
        ),
        "filament": _as_values(filament_value),
        "nozzle": _as_values(normalized.get("nozzle_diameter")),
    }


def _merge_sections(
    sections: Iterable[Mapping[str, str]],
) -> dict[str, str]:
    result: dict[str, str] = {}
    for section in sections:
        result.update(section)
    return result


def _split_config_value(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    text = value.strip()
    if not text:
        return ()
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        decoded = None
    if isinstance(decoded, list):
        return tuple(str(item) for item in decoded)
    # Preset lists are commonly semicolon-separated; accept line breaks as a
    # defensive fallback but do not split commas inside ordinary preset names.
    return tuple(
        item.strip().strip('"')
        for item in re.split(r"[;\r\n]+", text)
        if item.strip().strip('"')
    )


def _as_values(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(value)
    return (value,)


def _unique_strings(values: Iterable[Any]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip().strip('"')
        folded = text.casefold()
        if not text or folded in seen or folded in {"default", "- default -"}:
            continue
        seen.add(folded)
        result.append(text)
    return tuple(result)


def _finite_numbers(values: Iterable[Any]) -> tuple[float, ...]:
    result: list[float] = []
    for value in values:
        for token in re.findall(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", str(value)):
            number = float(token)
            if math.isfinite(number) and number > 0 and number not in result:
                result.append(number)
    return tuple(result)


def _safe_modified_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return -1
