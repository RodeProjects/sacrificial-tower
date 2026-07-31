from __future__ import annotations

import json
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from cooling_tower.models.gcode_metadata import SlicerFamily
from cooling_tower.slicers.adapter import SlicerAdapter
from cooling_tower.slicers.models import (
    EffectiveProfile,
    ProfileKind,
    ProfileRecord,
    SliceRequest,
)
from cooling_tower.slicers.profile_matching import (
    ProfileBundleValidator,
    ProfileValidationOutcome,
)
from cooling_tower.slicers.profile_models import (
    ProfileBundleMatch,
    ProfileRole,
    ProfileValidationState,
    stable_json_fingerprint,
)
from cooling_tower.slicers.profile_safety import protect_profile_sources


class SlicerProfileProbeValidator(ProfileBundleValidator):
    """Validate a bundle by slicing a tiny model in an isolated workspace."""

    def __init__(
        self,
        *,
        diagnostics_root: str | Path | None = None,
        timeout_s: float = 120.0,
    ) -> None:
        self.diagnostics_root = (
            Path(diagnostics_root).resolve()
            if diagnostics_root is not None
            else Path(tempfile.gettempdir()) / "cooling_tower_profile_diagnostics"
        )
        self.timeout_s = timeout_s
        self._cache: dict[str, ProfileValidationOutcome] = {}

    def validate(
        self,
        adapter: SlicerAdapter,
        bundle: ProfileBundleMatch,
        source_values: Mapping[str, Any],
        *,
        reconstructed: bool,
    ) -> ProfileValidationOutcome:
        cache_key = stable_json_fingerprint(
            {
                "adapter": adapter.adapter_id,
                "bundle": bundle.bundle_id,
                "source": source_values if reconstructed else {},
                "reconstructed": reconstructed,
                "version": bundle.effective_profile.installation.version,
            }
        )
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            with (
                protect_profile_sources(bundle.effective_profile),
                tempfile.TemporaryDirectory(
                    prefix="cooling_tower_profile_probe_"
                ) as temporary_directory,
            ):
                root = Path(temporary_directory)
                model_path = root / "profile_probe_cube.stl"
                import trimesh

                trimesh.creation.box(extents=(8.0, 8.0, 4.0)).export(model_path)
                effective = (
                    self._materialize_reconstructed_profile(
                        bundle,
                        source_values if reconstructed else {},
                        root / "profiles",
                    )
                    if (
                        reconstructed
                        or bundle.effective_profile.installation.family
                        is SlicerFamily.ORCA_BAMBU_ANYCUBIC
                    )
                    else bundle.effective_profile
                )
                result = adapter.slice_model(
                    SliceRequest(
                        model_path=model_path,
                        profile=effective,
                        output_directory=root / "sliced",
                        diagnostics_root=(
                            self.diagnostics_root
                            / ("reconstructed" if reconstructed else "installed")
                        ),
                        timeout_s=self.timeout_s,
                    )
                )
                if not result.success:
                    diagnostic_hint = (
                        f" Diagnose: {result.diagnostic_path}."
                        if result.diagnostic_path is not None
                        else ""
                    )
                    outcome = ProfileValidationOutcome(
                        ProfileValidationState.INVALID,
                        "Probeslice fehlgeschlagen: "
                        f"{result.failure_reason or 'unbekannter Fehler'}."
                        f"{diagnostic_hint}",
                    )
                else:
                    layer_times = adapter.extract_layer_times(result)
                    if not layer_times or not all(value > 0 for value in layer_times):
                        outcome = ProfileValidationOutcome(
                            ProfileValidationState.INVALID,
                            "Probeslice erzeugte keine auswertbaren Layerzeiten.",
                        )
                    else:
                        outcome = ProfileValidationOutcome(
                            ProfileValidationState.PROBE_VALIDATED,
                            f"Probeslice erfolgreich ({len(layer_times)} Layer).",
                        )
        except Exception as error:
            outcome = ProfileValidationOutcome(
                ProfileValidationState.INVALID,
                f"Probeslice konnte nicht ausgeführt werden: {error}",
            )
        self._cache[cache_key] = outcome
        return outcome

    def _materialize_reconstructed_profile(
        self,
        bundle: ProfileBundleMatch,
        source_values: Mapping[str, Any],
        profile_root: Path,
    ) -> EffectiveProfile:
        profile = bundle.effective_profile
        if profile.installation.family is not SlicerFamily.ORCA_BAMBU_ANYCUBIC:
            # Prusa consumes the effective mapping through a temporary INI in
            # its adapter; other families remain installed-profile only.
            if profile.installation.family is SlicerFamily.PRUSA_SLIC3R:
                merged = dict(profile.effective_values)
                merged.update(source_values)
                return replace(profile, effective_values=merged)
            raise ValueError(
                "Für diese Slicerfamilie wird keine Profilrekonstruktion unterstützt."
            )
        profile_root.mkdir(parents=True, exist_ok=True)
        resolved_by_path = {
            item.record.path: dict(item.effective_values)
            for item in bundle.resolved_profiles
        }
        role_values: dict[str, dict[str, Any]] = {}
        records = (
            *((profile.machine,) if profile.machine else ()),
            *((profile.process,) if profile.process else ()),
            *profile.filaments,
        )
        for record in records:
            values = dict(resolved_by_path.get(record.path, {}))
            role_values[record.kind.value] = values

        for values in role_values.values():
            for key, value in source_values.items():
                if key in values:
                    values[key] = _profile_json_value(value, values[key])

        machine_name = _temporary_machine_identity(bundle)
        if machine_name:
            # Flattening a derived user machine removes its inheritance link.
            # Orca-family CLIs then compare process/filament compatibility
            # against the temporary machine preset name. Use the compatible
            # inherited identity while retaining every effective user setting.
            # Align only our isolated temporary copies; source profiles remain
            # untouched, and the bundle already passed app-side validation.
            for role in (ProfileKind.PROCESS.value, ProfileKind.FILAMENT.value):
                values = role_values.get(role)
                if values is not None:
                    values["compatible_printers"] = [machine_name]

        temporary_records: list[ProfileRecord] = []
        for record in records:
            values = role_values[record.kind.value]
            values["inherits"] = ""
            values.setdefault("type", record.kind.value)
            # The temporary machine intentionally carries the compatible
            # inherited system identity. Anycubic includes ``from`` in its CLI
            # preset-compatibility model, so the flattened process/filament
            # copies must use the same coherent origin. The files themselves
            # still live exclusively in our isolated temporary directory.
            values["from"] = "system"
            # Orca-family compatibility rules refer to the concrete preset
            # name. A synthetic display name would make an otherwise valid
            # process appear incompatible with its machine.
            is_machine = (
                profile.machine is not None
                and record.path == profile.machine.path
            )
            values["name"] = machine_name if is_machine else record.name
            if is_machine:
                # Anycubic's CLI uses the setting ID as well as the display
                # name when resolving compatible process presets.
                values["printer_settings_id"] = machine_name
            destination = profile_root / f"{record.kind.value}.json"
            destination.write_text(
                json.dumps(values, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary_records.append(
                ProfileRecord(
                    adapter_id=record.adapter_id,
                    profile_id=f"cooling_tower_reconstructed_{record.kind.value}",
                    name=values["name"],
                    kind=record.kind,
                    path=destination,
                    source="temporary",
                    metadata={
                        "temporary": True,
                        "source_path": str(record.path),
                    },
                )
            )
        machine = next(
            (item for item in temporary_records if item.kind is ProfileKind.MACHINE),
            None,
        )
        process = next(
            (item for item in temporary_records if item.kind is ProfileKind.PROCESS),
            None,
        )
        filaments = tuple(
            item for item in temporary_records if item.kind is ProfileKind.FILAMENT
        )
        merged = dict(profile.effective_values)
        merged.update(source_values)
        return EffectiveProfile(
            installation=profile.installation,
            machine=machine,
            process=process,
            filaments=filaments,
            effective_values=merged,
            resolution_notes=(
                *profile.resolution_notes,
                "Temporäre effektive Konfiguration aus dem Quell-G-Code.",
            ),
        )

def write_profile_match_report(
    result,
    path: str | Path,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(result.to_report_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination.resolve()


def _json_value(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


def _profile_json_value(value: Any, existing: Any) -> Any:
    converted = _json_value(value)
    if isinstance(existing, list):
        return converted if isinstance(converted, list) else [converted]
    if isinstance(existing, tuple):
        return converted if isinstance(converted, list) else [converted]
    if isinstance(converted, list) and len(converted) == 1:
        return converted[0]
    return converted


def _temporary_machine_identity(bundle: ProfileBundleMatch) -> str:
    """Choose the inherited machine alias accepted by flattened CLI presets."""

    profile = bundle.effective_profile
    machine_record = profile.machine
    if machine_record is None:
        return ""
    machine = next(
        (
            item
            for item in bundle.resolved_profiles
            if item.record.path == machine_record.path
            and item.role
            in {ProfileRole.MACHINE_MODEL, ProfileRole.MACHINE_VARIANT}
        ),
        None,
    )
    if machine is None:
        return machine_record.name

    compatible_targets: list[str] = []
    for item in bundle.resolved_profiles:
        if item is machine:
            continue
        value = item.effective_values.get("compatible_printers")
        values = value if isinstance(value, (list, tuple, set)) else (value,)
        compatible_targets.extend(
            str(candidate).strip().strip('"')
            for candidate in values
            if candidate is not None and str(candidate).strip().strip('"')
        )
    normalized_targets = {
        _normalized_profile_name(value): value
        for value in compatible_targets
    }
    for record in reversed(machine.chain):
        for identity in (record.profile_id, record.name):
            target = normalized_targets.get(_normalized_profile_name(identity))
            if target is not None:
                return target
    return machine_record.name


def _normalized_profile_name(value: Any) -> str:
    return " ".join(str(value).strip().strip('"').casefold().split())
