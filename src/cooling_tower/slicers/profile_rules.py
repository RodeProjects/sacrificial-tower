"""Pure profile identity, normalization and compatibility rules.

No inventory I/O or matching orchestration lives here. Unknown slicer regex
conditions deliberately remain unknown instead of executing untrusted patterns.
"""
from __future__ import annotations
import math
import re
from pathlib import Path
from typing import Any, Mapping, Sequence
from cooling_tower.slicers.models import ProfileRecord, ProfileSelectionReference
from cooling_tower.slicers.profile_models import ResolvedProfile

def _profile_identifiers(resolved: ResolvedProfile) -> tuple[str, ...]:
    values = [resolved.record.profile_id, resolved.record.name]
    for key in (
        "setting_id",
        "printer_settings_id",
        "print_settings_id",
        "filament_settings_id",
    ):
        value = resolved.effective_values.get(key)
        values.extend(str(item) for item in _as_sequence(value) if str(item).strip())
    return tuple(dict.fromkeys(values))


def _machine_compatibility_identifiers(
    resolved: ResolvedProfile,
) -> tuple[str, ...]:
    """Return exact machine identities carried by the resolved preset chain."""

    values = list(_profile_identifiers(resolved))
    for record in resolved.chain:
        values.extend((record.profile_id, record.name))
    for key in ("printer_model", "printer_variant"):
        values.extend(
            str(value)
            for value in _as_sequence(resolved.effective_values.get(key))
            if str(value).strip()
        )
    return tuple(
        dict.fromkeys(value for value in values if str(value).strip())
    )


def _machine_scope_identifiers(
    resolved: ResolvedProfile,
) -> tuple[str, ...]:
    """Return stable preset identities suitable for ``preset @ machine``."""

    values = list(_profile_identifiers(resolved))
    for record in resolved.chain:
        values.extend((record.profile_id, record.name))
    return tuple(
        dict.fromkeys(value for value in values if str(value).strip())
    )


def _recognized_machine_scopes(
    profile: ResolvedProfile,
    known_machines: Sequence[ResolvedProfile],
) -> frozenset[str]:
    known = {
        _normalise_profile_identity(value)
        for machine in known_machines
        for value in _machine_scope_identifiers(machine)
    }
    scopes = {
        _normalise_profile_identity(scope)
        for identifier in _profile_identifiers(profile)
        for prefix, separator, scope in (str(identifier).rpartition("@"),)
        if separator and prefix.strip() and scope.strip()
    }
    # Some vendor catalogues contain stale machine-bound filament entries
    # whose referenced machine preset is no longer shipped. A conventional
    # ``<diameter> nozzle`` suffix is still unambiguous machine-scope evidence,
    # whereas abstract bases such as ``@acbase`` remain unrestricted.
    structured = {
        scope
        for scope in scopes
        if re.search(
            r"\b\d+(?:[.,]\d+)?\s*(?:mm\s*)?nozzle\b",
            scope,
        )
    }
    return frozenset(
        scope for scope in scopes if scope in known or scope in structured
    )


def _normalise_profile_identity(value: Any) -> str:
    return re.sub(
        r"\s+",
        " ",
        str(value).strip().strip('"'),
    ).casefold()


def _is_selectable_profile(resolved: ResolvedProfile) -> bool:
    """Mirror the slicer's hidden abstract-preset behaviour conservatively."""

    value = resolved.record.metadata.get("instantiation")
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _resolve_selected_profile_ids(
    selections: Mapping[str, str | ProfileSelectionReference],
    *,
    machine_options: Sequence[ProfileRecord],
    process_options: Sequence[ProfileRecord],
    filament_options: Sequence[ProfileRecord],
) -> dict[str, str]:
    """Resolve remembered references against this inventory, role by role.

    The concrete path wins when it still belongs to the inventory.  A stable
    profile ID is the fallback when a slicer update moved the preset.  Missing
    roles are deliberately omitted so normal matching can select its current
    safe default independently for each role.
    """

    options_by_role = {
        "machine": machine_options,
        "process": process_options,
        "filament": filament_options,
    }
    resolved: dict[str, str] = {}
    for role, selection in selections.items():
        options = options_by_role.get(role)
        if options is None:
            continue
        selected_record: ProfileRecord | None = None
        if isinstance(selection, ProfileSelectionReference):
            if selection.path is not None:
                selected_record = next(
                    (
                        record
                        for record in options
                        if _paths_refer_to_same_file(record.path, selection.path)
                    ),
                    None,
                )
            if selected_record is None:
                selected_record = next(
                    (
                        record
                        for record in options
                        if record.profile_id.casefold()
                        == selection.profile_id.casefold()
                    ),
                    None,
                )
        elif isinstance(selection, str) and selection.strip():
            selected_record = next(
                (
                    record
                    for record in options
                    if _record_matches_id(record, selection)
                ),
                None,
            )
        if selected_record is not None:
            resolved[role] = str(selected_record.path)
    return resolved


def _paths_refer_to_same_file(first: Path, second: Path) -> bool:
    if str(first).casefold() == str(second).casefold():
        return True
    try:
        return first.samefile(second)
    except (OSError, ValueError):
        return False


def _record_matches_id(record: ProfileRecord, selected_id: str) -> bool:
    normalized = selected_id.casefold()
    if (
        record.profile_id.casefold() == normalized
        or record.name.casefold() == normalized
        or str(record.path).casefold() == normalized
    ):
        return True

    selected_path = Path(selected_id).expanduser()
    if not selected_path.is_absolute():
        return False
    return _paths_refer_to_same_file(record.path, selected_path)


def _as_sequence(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(value)
    return (value,)


def _text_values(value: Any) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for item in _as_sequence(value):
        text = str(item).strip().strip('"')
        folded = text.casefold()
        if text and folded not in seen:
            seen.add(folded)
            result.append(text)
    return tuple(result)


def _positive_finite_numbers(value: Any) -> tuple[float, ...]:
    result: list[float] = []
    for item in _as_sequence(value):
        for token in re.findall(
            r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)",
            str(item),
        ):
            number = float(token)
            if math.isfinite(number) and number > 0 and not any(
                math.isclose(number, existing, abs_tol=1e-6)
                for existing in result
            ):
                result.append(number)
    return tuple(result)


def _profile_nozzle_diameters(
    resolved: ResolvedProfile,
) -> tuple[float, ...]:
    values = _positive_finite_numbers(
        resolved.effective_values.get("nozzle_diameter")
    )
    if values:
        return values
    values = _positive_finite_numbers(
        resolved.effective_values.get("printer_variant")
    )
    if values:
        return values
    return _positive_finite_numbers(resolved.record.metadata.get("nozzle_diameter"))


def _nozzle_values_compatible(
    requested: Sequence[float],
    candidate: Sequence[float],
) -> bool:
    if not requested or not candidate:
        return True
    return any(
        math.isclose(left, right, rel_tol=1e-5, abs_tol=1e-4)
        for left in requested
        for right in candidate
    )


def _compatibility_values(value: Any) -> tuple[str, ...]:
    values: list[str] = []
    for item in _as_sequence(value):
        values.extend(
            part.strip().strip('"')
            for part in re.split(r"[;\r\n]+", str(item))
            if part.strip().strip('"')
        )
    return tuple(dict.fromkeys(values))


def _safe_printer_note_pattern_match(
    pattern: str,
    printer_notes: str,
) -> bool | None:
    """Evaluate the common ``.*literal.*`` form without executing profile regex."""

    value = pattern.strip()
    if not value or len(value) > 256:
        return None
    if value.startswith("^"):
        value = value[1:]
    if value.endswith("$") and not value.endswith(r"\$"):
        value = value[:-1]
    while value.startswith(".*"):
        value = value[2:]
    while value.endswith(".*"):
        value = value[:-2]
    # Conditions shipped by the supported slicers predominantly wrap a
    # literal marker in ``.*``. Anything more expressive remains unknown and
    # is included conservatively instead of running untrusted regex syntax.
    if re.search(r"[\[\]{}()+?*|]", value):
        return None
    literal = re.sub(r"\\([.^$\\/])", r"\1", value).strip()
    if not literal:
        return None
    return literal.casefold() in printer_notes.casefold()


def _normalise_value(value: Any) -> Any:
    values = tuple(_normalise_scalar(item) for item in _as_sequence(value))
    unique: list[Any] = []
    for item in values:
        if item not in unique:
            unique.append(item)
    if len(unique) == 1:
        return unique[0]
    return tuple(unique)


def _normalise_scalar(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().strip('"')
    if text.casefold() in {"true", "yes", "on"}:
        return True
    if text.casefold() in {"false", "no", "off"}:
        return False
    if text.endswith("%"):
        number = _to_float(text[:-1])
        return ("percent", number) if number is not None else text.casefold()
    number = _to_float(text)
    return number if number is not None else text.casefold()


def _values_equal(first: Any, second: Any) -> bool:
    left = _normalise_value(first)
    right = _normalise_value(second)
    if isinstance(left, float) and isinstance(right, float):
        return math.isclose(left, right, rel_tol=1e-5, abs_tol=1e-6)
    return left == right


def _to_float(value: Any) -> float | None:
    try:
        result = float(str(value).strip())
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _explicit_extruder_count(values: Mapping[str, Any]) -> int | None:
    for key in (
        "extruder_count",
        "num_extruders",
        "number_of_extruders",
    ):
        number = _to_float(values.get(key))
        if number is not None and number >= 1 and float(number).is_integer():
            return int(number)
    nozzles = _as_sequence(values.get("nozzle_diameter"))
    # One physical nozzle can still expose several virtual material tools.
    # Several explicit nozzle diameters, by contrast, are physical evidence.
    return len(nozzles) if len(nozzles) > 1 else None


def _version_tuple(value: Any) -> tuple[int, ...]:
    return tuple(int(item) for item in re.findall(r"\d+", str(value or "")))


def _version_in_range(
    version: str | None,
    minimum: Any,
    maximum: Any,
) -> bool:
    current = _version_tuple(version)
    if not current:
        return minimum in (None, "") and maximum in (None, "")
    lower = _version_tuple(minimum)
    upper = _version_tuple(maximum)
    return (not lower or current >= lower) and (not upper or current <= upper)
