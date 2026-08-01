from __future__ import annotations

from collections.abc import Iterable, Mapping, MutableMapping, Sequence
from typing import Any

from cooling_tower.slicers.models import ProfileRecord


def harmonize_temporary_orca_profile_compatibility(
    machine_record: ProfileRecord | None,
    machine_chain: Sequence[ProfileRecord],
    machine_values: MutableMapping[str, Any] | None,
    dependent_values: Iterable[MutableMapping[str, Any]],
) -> str:
    """Align flattened Orca-family presets to one accepted machine identity.

    Derived user machine presets lose their inheritance context when they are
    flattened into the application's isolated CLI workspace. Process and
    filament presets can still name the inherited system preset in
    ``compatible_printers``. Orca-family CLIs then reject that otherwise valid
    combination. Only the app-owned mappings passed here are changed.
    """

    dependents = tuple(dependent_values)
    identity = temporary_orca_machine_identity(
        machine_record,
        machine_chain,
        dependents,
    )
    if not identity:
        return ""
    if machine_values is not None:
        machine_values["name"] = identity
        machine_values["printer_settings_id"] = identity
    for values in dependents:
        values["compatible_printers"] = [identity]
    return identity


def temporary_orca_machine_identity(
    machine_record: ProfileRecord | None,
    machine_chain: Sequence[ProfileRecord],
    dependent_values: Iterable[Mapping[str, Any]],
) -> str:
    """Choose the inherited machine alias accepted by flattened CLI presets."""

    if machine_record is None:
        return ""
    compatible_targets: list[str] = []
    for values in dependent_values:
        raw = values.get("compatible_printers")
        candidates = raw if isinstance(raw, (list, tuple, set)) else (raw,)
        compatible_targets.extend(
            str(candidate).strip().strip('"')
            for candidate in candidates
            if candidate is not None and str(candidate).strip().strip('"')
        )
    normalized_targets = {
        _normalized_profile_name(value): value for value in compatible_targets
    }
    chain = tuple(machine_chain) or (machine_record,)
    for record in reversed(chain):
        for identity in (record.profile_id, record.name):
            target = normalized_targets.get(_normalized_profile_name(identity))
            if target is not None:
                return target
    return machine_record.name


def _normalized_profile_name(value: Any) -> str:
    return " ".join(str(value).strip().strip('"').casefold().split())
