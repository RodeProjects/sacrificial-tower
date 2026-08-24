from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from cooling_tower.models import LayerSliceTiming, SliceEvaluation
from cooling_tower.services.analysis_service import GCodeAnalysisService
from cooling_tower.slicers import EffectiveProfile, ProfileRecord, SliceResult
from cooling_tower.slicers.orca_profile_compatibility import (
    harmonize_temporary_orca_profile_compatibility,
)
from cooling_tower.slicers.profile_models import ResolvedProfile


COOLING_OVERRIDE_KEYS: Mapping[str, object] = {
    "slow_down_for_layer_cooling": False,
    "slow_down_layer_time": 0,
    "slowdown_below_layer_time": 0,
    "minimum_layer_time": 0,
    "cool_min_layer_time": 0,
    "fan_cooling_layer_time": 0,
}

FULL_INFILL_OVERRIDES_BY_ADAPTER: Mapping[
    str, tuple[tuple[str, object], ...]
] = {
    "anycubic_slicer_next": (("sparse_infill_density", "100%"),),
    "orca_slicer": (("sparse_infill_density", "100%"),),
    "bambu_studio": (
        ("sparse_infill_density", "100%"),
        ("sparse_infill_pattern", "zig-zag"),
    ),
    "prusa_slicer": (("fill_density", "100%"),),
    "cura": (("infill_sparse_density", 100),),
}


def build_calibration_profile(
    profile: EffectiveProfile,
    working_directory: Path,
    *,
    simulate_full_tower_infill: bool = False,
    resolved_profiles: Sequence[ResolvedProfile] | None = None,
) -> tuple[EffectiveProfile, Mapping[str, object]]:
    """Create a disposable effective profile for isolated tower test slices."""

    values = dict(profile.effective_values)
    orca_family = profile.installation.adapter_id in {
        "anycubic_slicer_next",
        "orca_slicer",
        "bambu_studio",
    }
    applied: dict[str, object] = {}
    for key, replacement in COOLING_OVERRIDE_KEYS.items():
        if key in values:
            serialized = _profile_override_value(
                replacement,
                values[key],
                orca_family=orca_family,
            )
            values[key] = serialized
            applied[key] = serialized
    # Orca-family process profiles can omit a key to inherit a non-zero
    # slowdown.  Write the canonical keys explicitly for calibration.
    for key in ("slow_down_for_layer_cooling", "slow_down_layer_time"):
        if key not in values:
            replacement = _profile_override_value(
                COOLING_OVERRIDE_KEYS[key],
                None,
                orca_family=orca_family,
            )
            values[key] = replacement
            applied[key] = replacement

    cooling_applied = dict(applied)
    if simulate_full_tower_infill:
        overrides = FULL_INFILL_OVERRIDES_BY_ADAPTER.get(
            profile.installation.adapter_id
        )
        if overrides is None:
            raise ValueError(
                "Für diesen Slicer ist keine sichere temporäre "
                "100-%-Füllungsüberschreibung definiert."
            )
        for key, replacement in overrides:
            serialized = _profile_override_value(
                replacement,
                values.get(key),
                orca_family=orca_family,
            )
            values[key] = serialized
            applied[key] = serialized

    if orca_family:
        working_directory.mkdir(parents=True, exist_ok=True)
        resolved_by_path = (
            {
                item.record.path: item
                for item in resolved_profiles
                if item.valid and item.effective_values
            }
            if resolved_profiles is not None
            else _resolve_orca_role_profiles(profile)
        )
        resolved_values = {
            path: dict(resolved.effective_values)
            for path, resolved in resolved_by_path.items()
        }
        machine_values = (
            resolved_values.get(profile.machine.path)
            if profile.machine is not None
            else None
        )
        dependent_values = tuple(
            resolved_values.get(record.path, {})
            for record in (
                *((profile.process,) if profile.process is not None else ()),
                *profile.filaments,
            )
        )
        machine_resolved = (
            resolved_by_path.get(profile.machine.path)
            if profile.machine is not None
            else None
        )
        machine_identity = harmonize_temporary_orca_profile_compatibility(
            profile.machine,
            machine_resolved.chain if machine_resolved is not None else (),
            machine_values,
            dependent_values,
        )
        machine = _materialize_orca_profile_copy(
            profile.machine,
            working_directory / "machine_01.json",
            overrides={},
            include_missing_overrides=False,
            resolved_values=(
                resolved_values.get(profile.machine.path)
                if profile.machine is not None
                else None
            ),
            compatible_machine_identity=machine_identity,
        )
        process = _materialize_orca_profile_copy(
            profile.process,
            working_directory / "process_01.json",
            overrides=applied,
            include_missing_overrides=True,
            resolved_values=(
                resolved_values.get(profile.process.path)
                if profile.process is not None
                else None
            ),
            compatible_machine_identity=machine_identity,
        )
        filaments = tuple(
            _materialize_orca_profile_copy(
                record,
                working_directory / f"filament_{index:02d}.json",
                overrides=cooling_applied,
                include_missing_overrides=True,
                resolved_values=resolved_values.get(record.path),
                compatible_machine_identity=machine_identity,
            )
            for index, record in enumerate(profile.filaments, start=1)
        )
    else:
        machine = profile.machine
        process = profile.process
        filaments = profile.filaments
    return (
        replace(
            profile,
            machine=machine,
            process=process,
            filaments=filaments,
            effective_values=values,
        ),
        applied,
    )


def _materialize_orca_profile_copy(
    record: ProfileRecord | None,
    destination: Path,
    *,
    overrides: Mapping[str, object],
    include_missing_overrides: bool,
    resolved_values: Mapping[str, object] | None,
    compatible_machine_identity: str,
) -> ProfileRecord | None:
    """Create a CLI-compatible copy without ever writing the source profile."""

    if record is None:
        return None
    try:
        loaded = json.loads(record.path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(
            f"Das Slicerprofil kann nicht sicher kopiert werden: {record.path}"
        ) from error
    if not isinstance(loaded, Mapping):
        raise ValueError(
            f"Das Slicerprofil ist kein gültiges JSON-Objekt: {record.path}"
        )
    payload = dict(resolved_values) if resolved_values else dict(loaded)
    # Sparse Anycubic/Orca/Bambu user presets often omit ``type`` because the
    # GUI knows the containing directory.  Their CLI loader does not, so the
    # disposable copy must state the role explicitly.
    payload["name"] = str(payload.get("name") or record.name)
    payload["type"] = record.kind.value
    if compatible_machine_identity:
        if record.kind.value == "machine":
            payload["name"] = compatible_machine_identity
            payload["printer_settings_id"] = compatible_machine_identity
        elif record.kind.value in {"process", "filament"}:
            payload["compatible_printers"] = [compatible_machine_identity]
    # All flattened records form one synthetic, self-contained preset family.
    # Anycubic includes ``from`` in its compatibility model; mixing a system
    # machine with user process/filament copies can therefore intermittently
    # reject an otherwise probe-validated combination. This origin exists only
    # in our temporary workspace and never changes the slicer-owned sources.
    payload["from"] = "system"
    if resolved_values:
        # The temporary copy is self-contained. This is important when the
        # isolated slicer data directory intentionally contains no user
        # presets from the real slicer installation.
        payload["inherits"] = ""
    target = payload.get("setting")
    if isinstance(target, Mapping):
        patched = dict(target)
        patched.update(
            {
                key: value
                for key, value in overrides.items()
                if include_missing_overrides or key in patched
            }
        )
        payload["setting"] = patched
    else:
        payload.update(
            {
                key: value
                for key, value in overrides.items()
                if include_missing_overrides or key in payload
            }
        )
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return ProfileRecord(
        adapter_id=record.adapter_id,
        profile_id=f"cooling_tower_calibration_{record.kind.value}",
        name=payload["name"],
        kind=record.kind,
        path=destination,
        source="temporary",
        inherits=record.inherits,
        metadata={
            "temporary": True,
            "source_path": str(record.path),
        },
    )


def _profile_override_value(
    replacement: object,
    existing: object,
    *,
    orca_family: bool,
) -> object:
    if not orca_family:
        return replacement
    rendered = (
        "1"
        if replacement is True
        else "0"
        if replacement is False
        else str(replacement)
    )
    if isinstance(existing, (list, tuple)):
        return [rendered for _ in existing] or [rendered]
    return rendered


def _resolve_orca_role_profiles(
    profile: EffectiveProfile,
) -> dict[Path, ResolvedProfile]:
    """Resolve each role's inheritance read-only for self-contained copies."""

    try:
        from cooling_tower.slicers.adapters import default_adapters
        from cooling_tower.slicers.profile_inventory import (
            ProfileInheritanceResolver,
            ProfileInventoryService,
        )

        adapter = next(
            item
            for item in default_adapters()
            if item.adapter_id == profile.installation.adapter_id
        )
        inventory = ProfileInventoryService().load(
            adapter,
            profile.installation,
            force=True,
        )
        resolver = ProfileInheritanceResolver(inventory, adapter)
        result: dict[Path, ResolvedProfile] = {}
        records = (
            *((profile.machine,) if profile.machine is not None else ()),
            *((profile.process,) if profile.process is not None else ()),
            *profile.filaments,
        )
        for record in records:
            resolved = resolver.resolve(record)
            if resolved.valid and resolved.effective_values:
                result[record.path] = resolved
        return result
    except (OSError, StopIteration, ValueError, TypeError):
        # Sparse synthetic fixtures and manually supplied profiles may have no
        # inventory roots. They still receive a safe direct copy.
        return {}


def _extract_metadata_times(result: SliceResult) -> tuple[float, ...]:
    for path in result.metadata_paths:
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        try:
            payload: Any = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        candidates: list[Any] = []
        if isinstance(payload, Mapping):
            for key in ("layer_times", "layer_time", "layers"):
                if key in payload:
                    candidates.append(payload[key])
        for candidate in candidates:
            if isinstance(candidate, Sequence) and not isinstance(candidate, (str, bytes)):
                values: list[float] = []
                for item in candidate:
                    if isinstance(item, Mapping):
                        item = item.get("time", item.get("duration"))
                    try:
                        value = float(item)
                    except (TypeError, ValueError):
                        break
                    if not math.isfinite(value) or value < 0.0:
                        break
                    values.append(value)
                else:
                    if values:
                        return tuple(values)
    return ()


class SliceEvaluator:
    def __init__(self, analysis_service: GCodeAnalysisService | None = None) -> None:
        self.analysis_service = analysis_service or GCodeAnalysisService()

    def evaluate(
        self,
        result: SliceResult,
        source_layers: Sequence[object],
        *,
        approach_times_s: Mapping[int, tuple[float, float]] | None = None,
        metadata_tolerance_s: float = 0.75,
    ) -> SliceEvaluation:
        if not result.success or result.gcode_path is None:
            raise ValueError(
                result.failure_reason or "Der Slicer hat keinen G-Code erzeugt."
            )
        snapshot = self.analysis_service.analyze(result.gcode_path, force=True)
        tower_layers = snapshot.layers
        if not tower_layers:
            raise ValueError(
                "Der Slicer-G-Code enthält keine druckbaren Kühlturm-Layer."
            )
        metadata_times = _extract_metadata_times(result)
        diagnostics: list[str] = []
        if len(tower_layers) != len(source_layers):
            diagnostics.append(
                "Die Layeranzahl des Slicers weicht vom Kalibrierungsprofil ab; "
                "die Layer wurden über ihre Z-Höhe zugeordnet."
            )
        travels = approach_times_s or {}
        timings: list[LayerSliceTiming] = []
        differences: list[float] = []
        for source in source_layers:
            source_index = int(getattr(source, "index"))
            z = float(getattr(source, "z_mm", getattr(source, "z", 0.0)))
            tower = min(tower_layers, key=lambda layer: abs(layer.z_mm - z))
            approach, return_time = travels.get(source_index, (0.0, 0.0))
            computed = tower.total_time_s + approach + return_time
            reported = None
            difference = None
            metadata_position = tower.index - 1
            if metadata_position < len(metadata_times):
                reported = metadata_times[metadata_position]
                difference = abs(reported - tower.total_time_s)
                differences.append(difference)
            timings.append(
                LayerSliceTiming(
                    layer_index=source_index,
                    z_mm=z,
                    deposition_time_s=tower.deposition_time_s,
                    internal_travel_time_s=tower.travel_time_s,
                    retraction_time_s=(
                        tower.retraction_time_s + tower.unretraction_time_s
                    ),
                    approach_time_s=approach,
                    return_time_s=return_time,
                    total_added_time_s=computed,
                    slicer_reported_time_s=reported,
                    timing_difference_s=difference,
                )
            )
        maximum_difference = max(differences, default=None)
        if maximum_difference is not None and maximum_difference > metadata_tolerance_s:
            diagnostics.append(
                "Slicer-Metadaten und beschleunigungsabhängige G-Code-Zeit "
                f"weichen um bis zu {maximum_difference:.3f} s voneinander ab."
            )
        return SliceEvaluation(
            gcode_path=result.gcode_path.resolve(),
            layer_timings=tuple(timings),
            metadata_source=("slicer_and_gcode" if metadata_times else "gcode"),
            maximum_metadata_difference_s=maximum_difference,
            diagnostics=tuple(diagnostics),
        )
