from __future__ import annotations

import itertools
import math
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from cooling_tower.models.analysis import GCodeAnalysisSnapshot
from cooling_tower.models.gcode_metadata import GCodeMetadata, SlicerFamily
from cooling_tower.slicers.adapter import SlicerAdapter
from cooling_tower.slicers.models import (
    EffectiveProfile,
    ProfileKind,
    ProfileRecord,
    SlicerInstallation,
)
from cooling_tower.slicers.profile_inventory import (
    ProfileInheritanceResolver,
    ProfileInventoryService,
)
from cooling_tower.slicers.profile_mappings import ProfileMappingStore
from cooling_tower.slicers.profile_models import (
    ProfileBundleMatch,
    ProfileExclusionCode,
    ProfileHardExclusion,
    ProfileMatchResult,
    ProfileMatchState,
    ProfileRole,
    ProfileValidationState,
    ProfileValueDifference,
    ResolvedProfile,
    profile_bundle_id,
    stable_json_fingerprint,
)


CRITICAL_PROFILE_KEYS: dict[str, tuple[str, ...]] = {
    "outer_wall_speed": ("outer_wall_speed", "external_perimeter_speed"),
    "inner_wall_speed": ("inner_wall_speed", "perimeter_speed"),
    "small_perimeter_speed": ("small_perimeter_speed", "small_feature_speed"),
    "overhang_speed": ("overhang_speed", "overhang_1_4_speed", "bridge_speed"),
    "default_acceleration": ("default_acceleration", "perimeter_acceleration"),
    "outer_wall_acceleration": ("outer_wall_acceleration", "external_perimeter_acceleration"),
    "travel_speed": ("travel_speed", "travel_speed_z"),
    "retraction_speed": ("retraction_speed", "retract_speed"),
    "deretraction_speed": ("deretraction_speed", "deretract_speed"),
    "retraction_length": ("retraction_length", "retract_length"),
    "line_width": ("line_width", "extrusion_width"),
    "outer_wall_line_width": ("outer_wall_line_width", "external_perimeter_extrusion_width"),
    "inner_wall_line_width": ("inner_wall_line_width", "perimeter_extrusion_width"),
    "layer_height": ("layer_height",),
    "wall_loops": ("wall_loops", "perimeters"),
    "max_volumetric_speed": ("filament_max_volumetric_speed", "max_volumetric_speed"),
    "min_print_speed": ("min_print_speed", "minimum_print_speed"),
    "slow_down_layer_time": ("slow_down_layer_time", "slowdown_below_layer_time"),
    "fan_min_speed": ("fan_min_speed", "min_fan_speed"),
    "fan_max_speed": ("fan_max_speed", "max_fan_speed"),
}

_IDENTIFIER_KEYS = {
    ProfileRole.MACHINE_MODEL: ("printer_settings_id",),
    ProfileRole.MACHINE_VARIANT: ("printer_settings_id",),
    ProfileRole.PROCESS: ("print_settings_id",),
    ProfileRole.FILAMENT: ("filament_settings_id",),
}


@dataclass(frozen=True, slots=True)
class GCodeProfileEvidence:
    absolute_xy_known: bool
    relative_xy_extrusion_seen: bool
    extrusion_mode_known: bool
    tool_indices: tuple[int, ...]
    special_procedure_seen: bool

    @property
    def active_tool_count(self) -> int:
        return max(self.tool_indices, default=0) + 1


@dataclass(frozen=True, slots=True)
class ProfileValidationOutcome:
    state: ProfileValidationState
    message: str


class ProfileBundleValidator(Protocol):
    def validate(
        self,
        adapter: SlicerAdapter,
        bundle: ProfileBundleMatch,
        source_values: Mapping[str, Any],
        *,
        reconstructed: bool,
    ) -> ProfileValidationOutcome: ...


class StructuralProfileValidator:
    def validate(
        self,
        adapter: SlicerAdapter,
        bundle: ProfileBundleMatch,
        source_values: Mapping[str, Any],
        *,
        reconstructed: bool,
    ) -> ProfileValidationOutcome:
        if bundle.exclusions:
            return ProfileValidationOutcome(
                ProfileValidationState.INVALID,
                "Profilkombination ist strukturell nicht kompatibel.",
            )
        return ProfileValidationOutcome(
            ProfileValidationState.STRUCTURALLY_VALID,
            "Profilkombination ist strukturell gültig; ein Probeslice wurde noch nicht ausgeführt.",
        )


def metadata_values(metadata: GCodeMetadata) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for item in metadata.typed_config:
        if item.valid:
            if item.separator is None:
                # Preserve lossless slicer syntax. In particular, converting
                # "80%" to numeric 80 would change its meaning on export.
                value: Any = item.raw_value
            else:
                value = tuple(
                    f"{part.value}{part.unit}" if part.unit else part.value
                    for part in item.items
                )
            values[item.key.strip().casefold()] = value
    return values


def critical_values(values: Mapping[str, Any]) -> dict[str, Any]:
    normalized = {str(key).casefold(): value for key, value in values.items()}
    result: dict[str, Any] = {}
    for canonical, aliases in CRITICAL_PROFILE_KEYS.items():
        for alias in aliases:
            if alias in normalized:
                result[canonical] = _normalise_value(normalized[alias])
                break
    return result


def scan_gcode_profile_evidence(path: Path) -> GCodeProfileEvidence:
    absolute_xy_known = False
    absolute_xy = True
    extrusion_mode_known = False
    relative_xy_extrusion_seen = False
    tool_indices: set[int] = {0}
    special = False
    with path.open("r", encoding="utf-8", errors="replace") as source:
        for raw_line in source:
            code = raw_line.split(";", 1)[0].strip().upper()
            if not code:
                continue
            command = code.split(None, 1)[0]
            if command == "G90":
                absolute_xy = True
                absolute_xy_known = True
            elif command == "G91":
                absolute_xy = False
                absolute_xy_known = True
            elif command in {"M82", "M83"}:
                extrusion_mode_known = True
            elif command in {"G0", "G1"} and "E" in code and not absolute_xy:
                relative_xy_extrusion_seen = True
            elif re.fullmatch(r"T\d+", command):
                tool_indices.add(int(command[1:]))
            elif command in {"M600", "M701", "M702"}:
                special = True
    return GCodeProfileEvidence(
        absolute_xy_known=absolute_xy_known,
        relative_xy_extrusion_seen=relative_xy_extrusion_seen,
        extrusion_mode_known=extrusion_mode_known,
        tool_indices=tuple(sorted(tool_indices)),
        special_procedure_seen=special,
    )


class ProfileMatchingService:
    def __init__(
        self,
        *,
        inventory_service: ProfileInventoryService | None = None,
        mapping_store: ProfileMappingStore | None = None,
        validator: ProfileBundleValidator | None = None,
        maximum_options_per_role: int = 10,
    ) -> None:
        self.inventory_service = inventory_service or ProfileInventoryService()
        self.mapping_store = mapping_store
        self.validator = validator or StructuralProfileValidator()
        self.maximum_options_per_role = max(2, maximum_options_per_role)
        self._gcode_evidence_cache: dict[
            tuple[Path, int, int], GCodeProfileEvidence
        ] = {}

    def match(
        self,
        snapshot: GCodeAnalysisSnapshot,
        installation: SlicerInstallation,
        adapter: SlicerAdapter,
        *,
        selected_profile_ids: Mapping[str, str] | None = None,
        force_inventory: bool = False,
    ) -> ProfileMatchResult:
        inventory = self.inventory_service.load(
            adapter,
            installation,
            force=force_inventory,
        )
        resolver = ProfileInheritanceResolver(inventory, adapter)
        resolved = resolver.resolve_all()
        source_values = metadata_values(snapshot.metadata)
        source_critical = critical_values(source_values)
        source_critical_fingerprint = stable_json_fingerprint(source_critical)
        source_profile_fingerprint = (
            snapshot.metadata.profile_fingerprint.digest_sha256
        )
        gcode_evidence = self._gcode_evidence(snapshot)
        selected_profile_ids = {
            str(key).casefold(): value
            for key, value in (selected_profile_ids or {}).items()
            if value
        }

        machine_options = self._selectable_options(
            resolved,
            (ProfileRole.MACHINE_VARIANT, ProfileRole.MACHINE_MODEL),
        )
        process_options = self._selectable_options(
            resolved,
            (ProfileRole.PROCESS,),
        )
        filament_options = self._selectable_options(
            resolved,
            (ProfileRole.FILAMENT,),
        )
        role_groups = self._role_groups(resolved)
        source_ids = self._source_identifiers(source_values)
        ranked_roles = {
            role: self._rank_role_records(
                role_groups.get(role, ()),
                role,
                source_values,
                source_critical,
                source_ids.get(role, ()),
                selected_profile_ids.get(role.value)
                or (
                    selected_profile_ids.get("machine")
                    if role
                    in {
                        ProfileRole.MACHINE_VARIANT,
                        ProfileRole.MACHINE_MODEL,
                    }
                    else None
                ),
            )
            for role in (
                ProfileRole.MACHINE_VARIANT,
                ProfileRole.MACHINE_MODEL,
                ProfileRole.PROCESS,
                ProfileRole.FILAMENT,
            )
        }
        machines = self._merge_machine_options(ranked_roles)
        processes = ranked_roles[ProfileRole.PROCESS]
        filaments = ranked_roles[ProfileRole.FILAMENT]

        rejected_resolution = tuple(
            item
            for item in resolved
            if not item.valid
        )
        candidates = self._build_candidates(
            installation,
            snapshot,
            source_values,
            source_critical,
            source_ids,
            gcode_evidence,
            machines,
            processes,
            filaments,
        )
        if not candidates and rejected_resolution:
            candidates = tuple(
                self._invalid_resolution_candidate(
                    installation,
                    item,
                )
                for item in rejected_resolution[:3]
            )

        usable = tuple(candidate for candidate in candidates if candidate.usable)
        if not usable:
            return ProfileMatchResult(
                state=ProfileMatchState.UNAVAILABLE,
                selected=None,
                candidates=candidates,
                machine_options=machine_options,
                process_options=process_options,
                filament_options=filament_options,
                requires_confirmation=False,
                user_confirmed=False,
                can_use_stl_mode=False,
                can_use_gcode_mode=False,
                message="Keine verwendbare Profilkombination gefunden.",
                source_slicer=snapshot.metadata.slicer,
                execution_slicer=installation,
                inventory_fingerprint=inventory.fingerprint_sha256,
                source_profile_fingerprint=source_profile_fingerprint,
                source_critical_fingerprint=source_critical_fingerprint,
                gcode_restrictions=("Keine gültige Profilkombination.",),
            )

        selected = usable[0]
        state = self._classify(
            usable,
            source_ids,
            snapshot.metadata.slicer.family,
            installation.family,
        )
        explicit_selection = bool(selected_profile_ids)
        user_confirmed = False

        if not explicit_selection and self._is_reconstructable(source_values, source_critical):
            outcome = self.validator.validate(
                adapter,
                selected,
                source_values,
                reconstructed=True,
            )
            if outcome.state is ProfileValidationState.PROBE_VALIDATED:
                selected = replace(
                    selected,
                    reconstructed=True,
                    temporary_overrides=dict(source_values),
                    validation_state=outcome.state,
                    validation_message=outcome.message,
                )
                state = ProfileMatchState.RECONSTRUCTED
        if state is not ProfileMatchState.RECONSTRUCTED:
            outcome = self.validator.validate(
                adapter,
                selected,
                source_values,
                reconstructed=False,
            )
            selected = replace(
                selected,
                validation_state=outcome.state,
                validation_message=outcome.message,
            )
            if outcome.state is ProfileValidationState.INVALID:
                state = ProfileMatchState.UNAVAILABLE

        mapping = (
            self.mapping_store.find(
                family=installation.family,
                version=installation.version,
                source_profile_fingerprint=source_profile_fingerprint,
                source_critical_fingerprint=source_critical_fingerprint,
            )
            if self.mapping_store is not None
            else None
        )
        if mapping is not None and state is not ProfileMatchState.RECONSTRUCTED:
            confirmed = next(
                (
                    candidate
                    for candidate in usable
                    if self.mapping_store.bundle_matches_mapping(candidate, mapping)
                ),
                None,
            )
            if confirmed is not None:
                selected = confirmed
                outcome = self.validator.validate(
                    adapter,
                    selected,
                    source_values,
                    reconstructed=False,
                )
                selected = replace(
                    selected,
                    validation_state=outcome.state,
                    validation_message=outcome.message,
                )
                user_confirmed = (
                    outcome.state is not ProfileValidationState.INVALID
                )
                if outcome.state is ProfileValidationState.INVALID:
                    state = ProfileMatchState.UNAVAILABLE

        requires_confirmation = (
            state in {ProfileMatchState.COMPATIBLE, ProfileMatchState.AMBIGUOUS}
            and not user_confirmed
        )
        restrictions = self._gcode_restrictions(
            snapshot,
            installation,
            selected,
            state,
            gcode_evidence,
        )
        can_use_gcode = not restrictions and not requires_confirmation
        can_use_stl = (
            state is not ProfileMatchState.UNAVAILABLE
            and selected.validation_state is not ProfileValidationState.INVALID
        )
        message = (
            selected.validation_message
            if selected.validation_state is ProfileValidationState.INVALID
            and selected.validation_message
            else self._state_message(state, requires_confirmation, user_confirmed)
        )
        return ProfileMatchResult(
            state=state,
            selected=selected,
            candidates=candidates,
            machine_options=machine_options,
            process_options=process_options,
            filament_options=filament_options,
            requires_confirmation=requires_confirmation,
            user_confirmed=user_confirmed,
            can_use_stl_mode=can_use_stl,
            can_use_gcode_mode=can_use_gcode,
            message=message,
            source_slicer=snapshot.metadata.slicer,
            execution_slicer=installation,
            inventory_fingerprint=inventory.fingerprint_sha256,
            source_profile_fingerprint=source_profile_fingerprint,
            source_critical_fingerprint=source_critical_fingerprint,
            gcode_restrictions=restrictions,
        )

    def confirm(self, result: ProfileMatchResult) -> ProfileMatchResult:
        if result.selected is None:
            raise ValueError("Es ist keine Profilkombination ausgewählt.")
        if self.mapping_store is None:
            raise ValueError("Es ist kein Speicher für Profilzuordnungen eingerichtet.")
        self.mapping_store.confirm(result)
        restrictions = tuple(
            item
            for item in result.gcode_restrictions
            if item != "Profilzuordnung wurde noch nicht bestätigt."
        )
        return replace(
            result,
            user_confirmed=True,
            requires_confirmation=False,
            can_use_gcode_mode=not restrictions,
            message="Profilkombination wurde bestätigt und sicher gespeichert.",
            gcode_restrictions=restrictions,
        )

    def inventory_is_stale(self, result: ProfileMatchResult) -> bool:
        inventory = self.inventory_service.cached_inventory(
            result.execution_slicer
        )
        return inventory is None or self.inventory_service.is_stale(inventory)

    def _gcode_evidence(
        self,
        snapshot: GCodeAnalysisSnapshot,
    ) -> GCodeProfileEvidence:
        key = (
            snapshot.gcode_path,
            snapshot.file_size_bytes,
            snapshot.file_modified_ns,
        )
        value = self._gcode_evidence_cache.get(key)
        if value is None:
            value = scan_gcode_profile_evidence(snapshot.gcode_path)
            self._gcode_evidence_cache = {key: value}
        return value

    @staticmethod
    def _role_groups(
        resolved: Sequence[ResolvedProfile],
    ) -> dict[ProfileRole, tuple[ResolvedProfile, ...]]:
        result: dict[ProfileRole, list[ResolvedProfile]] = {}
        seen: set[tuple[ProfileRole, str, str | None]] = set()
        for item in resolved:
            # Vendor resources, OTA mirrors and the local system cache often
            # expose the same effective preset at several paths.  This is one
            # candidate and must not create artificial ambiguity.
            key = (
                item.role,
                item.record.profile_id.casefold(),
                item.fingerprint_sha256,
            )
            if key in seen:
                continue
            seen.add(key)
            result.setdefault(item.role, []).append(item)
        return {key: tuple(value) for key, value in result.items()}

    @staticmethod
    def _selectable_options(
        resolved: Sequence[ResolvedProfile],
        roles: tuple[ProfileRole, ...],
    ) -> tuple[ProfileRecord, ...]:
        """Return each valid logical preset once, without ranking limits."""

        selected: dict[tuple[str, str], ResolvedProfile] = {}
        for item in resolved:
            if not item.valid or item.role not in roles:
                continue
            role_key = (
                "machine"
                if item.role
                in {
                    ProfileRole.MACHINE_VARIANT,
                    ProfileRole.MACHINE_MODEL,
                }
                else item.role.value
            )
            identifier = (
                item.record.profile_id.strip()
                or item.record.name.strip()
                or str(item.record.path)
            ).casefold()
            key = (role_key, identifier)
            existing = selected.get(key)
            if existing is None or ProfileMatchingService._option_preference(
                item
            ) < ProfileMatchingService._option_preference(existing):
                selected[key] = item
        records = [item.record for item in selected.values()]
        return tuple(
            sorted(
                records,
                key=lambda record: (
                    record.name.casefold(),
                    record.profile_id.casefold(),
                    str(record.path).casefold(),
                ),
            )
        )

    @staticmethod
    def _option_preference(item: ResolvedProfile) -> tuple[int, int, str]:
        source = item.record.source.casefold()
        source_rank = {
            "user": 0,
            "project": 1,
            "session": 2,
            "system": 3,
        }.get(source, 4)
        parts = {part.casefold() for part in item.record.path.parts}
        canonical_location_rank = (
            0
            if source == "user" and "user" in parts
            else 0
            if source == "system" and "resources" in parts
            else 1
        )
        return (
            source_rank,
            canonical_location_rank,
            str(item.record.path).casefold(),
        )

    @staticmethod
    def _source_identifiers(
        source_values: Mapping[str, Any],
    ) -> dict[ProfileRole, tuple[str, ...]]:
        result: dict[ProfileRole, tuple[str, ...]] = {}
        for role, keys in _IDENTIFIER_KEYS.items():
            values: list[str] = []
            for key in keys:
                if key not in source_values:
                    continue
                for value in _as_sequence(source_values[key]):
                    text = str(value).strip().strip('"')
                    if text and text.casefold() not in {item.casefold() for item in values}:
                        values.append(text)
            result[role] = tuple(values)
        return result

    def _rank_role_records(
        self,
        records: Sequence[ResolvedProfile],
        role: ProfileRole,
        source_values: Mapping[str, Any],
        source_critical: Mapping[str, Any],
        source_ids: tuple[str, ...],
        selected_id: str | None,
    ) -> tuple[tuple[ResolvedProfile, int, tuple[str, ...]], ...]:
        ranked: list[tuple[ResolvedProfile, int, tuple[str, ...]]] = []
        source_model = str(source_values.get("printer_model", "")).casefold()
        source_printer_ids = {
            str(value).strip().strip('"').casefold()
            for value in _as_sequence(source_values.get("printer_settings_id"))
            if str(value).strip().strip('"')
        }
        for resolved in records:
            if not resolved.valid:
                continue
            if selected_id and not _record_matches_id(resolved.record, selected_id):
                continue
            evidence: list[str] = []
            score = 0
            identifiers = _profile_identifiers(resolved)
            exact = {
                value.casefold() for value in source_ids
            }.intersection(value.casefold() for value in identifiers)
            if exact:
                score += 100
                evidence.append("Eindeutige Profil-/Setting-ID stimmt überein.")
            model = str(resolved.effective_values.get("printer_model", "")).casefold()
            if source_model and model == source_model:
                score += 70
                evidence.append("Explizites Druckermodell stimmt überein.")
            compatible_printers = {
                str(value).strip().strip('"').casefold()
                for value in _as_sequence(
                    resolved.effective_values.get("compatible_printers")
                )
                if str(value).strip().strip('"')
            }
            if compatible_printers.intersection(source_printer_ids):
                score += 60
                evidence.append("Kompatible Maschinen-ID stimmt überein.")
            elif source_model and any(
                source_model in value for value in compatible_printers
            ):
                score += 45
                evidence.append("Kompatibilitätsliste passt zum Druckermodell.")
            if any(
                resolved.record.name.casefold() == value.casefold()
                for value in source_ids
            ):
                score += 20
                evidence.append("Profilname stimmt als zusätzlicher Hinweis überein.")
            candidate_critical = critical_values(resolved.effective_values)
            matches = sum(
                _values_equal(value, candidate_critical[key])
                for key, value in source_critical.items()
                if key in candidate_critical
            )
            score += 2 * matches
            # A concrete derived preset is a better selectable candidate than
            # an otherwise identical abstract/common base preset.  Keep the
            # increment deliberately small so explicit IDs, model data and
            # critical values remain the decisive evidence.
            score += max(0, len(resolved.chain) - 1)
            ranked.append((resolved, score, tuple(evidence)))
        ranked.sort(
            key=lambda item: (
                -item[1],
                item[0].record.name.casefold(),
                str(item[0].record.path).casefold(),
            )
        )
        return tuple(ranked[: self.maximum_options_per_role])

    @staticmethod
    def _merge_machine_options(ranked_roles):
        values = (
            *ranked_roles[ProfileRole.MACHINE_VARIANT],
            *ranked_roles[ProfileRole.MACHINE_MODEL],
        )
        return tuple(
            sorted(values, key=lambda item: (-item[1], item[0].record.name.casefold()))
        )

    def _build_candidates(
        self,
        installation: SlicerInstallation,
        snapshot: GCodeAnalysisSnapshot,
        source_values: Mapping[str, Any],
        source_critical: Mapping[str, Any],
        source_ids: Mapping[ProfileRole, tuple[str, ...]],
        gcode_evidence: GCodeProfileEvidence,
        machines,
        processes,
        filaments,
    ) -> tuple[ProfileBundleMatch, ...]:
        if not machines or not processes or not filaments:
            return ()
        candidates: list[ProfileBundleMatch] = []
        for machine_entry, process_entry, filament_entry in itertools.product(
            machines,
            processes,
            filaments,
        ):
            machine, machine_score, machine_evidence = machine_entry
            process, process_score, process_evidence = process_entry
            filament, filament_score, filament_evidence = filament_entry
            effective_values: dict[str, Any] = {}
            for item in (machine, process, filament):
                effective_values.update(item.effective_values)
            profile = EffectiveProfile(
                installation=installation,
                machine=machine.record,
                process=process.record,
                filaments=(filament.record,),
                effective_values=effective_values,
                resolution_notes=tuple(
                    error
                    for item in (machine, process, filament)
                    for error in item.errors
                ),
            )
            exclusions = self._hard_exclusions(
                snapshot,
                source_values,
                installation,
                machine,
                process,
                filament,
                effective_values,
                gcode_evidence,
            )
            candidate_critical = critical_values(effective_values)
            differences: list[ProfileValueDifference] = []
            unknown: list[str] = []
            matches = 0
            for key, source_value in source_critical.items():
                if key not in candidate_critical:
                    unknown.append(key)
                elif _values_equal(source_value, candidate_critical[key]):
                    matches += 1
                else:
                    differences.append(
                        ProfileValueDifference(
                            key=key,
                            source_value=source_value,
                            candidate_value=candidate_critical[key],
                            critical=True,
                        )
                    )
            exact_identifiers = sum(
                bool(
                    {value.casefold() for value in source_ids.get(role, ())}
                    .intersection(
                        identifier.casefold()
                        for identifier in _profile_identifiers(resolved)
                    )
                )
                for role, resolved in (
                    (ProfileRole.MACHINE_VARIANT, machine),
                    (ProfileRole.PROCESS, process),
                    (ProfileRole.FILAMENT, filament),
                )
            )
            cross_slicer = (
                snapshot.metadata.slicer.family is not SlicerFamily.UNKNOWN
                and snapshot.metadata.slicer.family is not installation.family
            )
            evidence = tuple(
                dict.fromkeys(
                    (*machine_evidence, *process_evidence, *filament_evidence)
                )
            )
            rank = (
                machine_score
                + process_score
                + filament_score
                + exact_identifiers * 50
                + matches * 3
                - len(differences) * 8
                - len(unknown)
            )
            candidates.append(
                ProfileBundleMatch(
                    bundle_id=profile_bundle_id(profile),
                    effective_profile=profile,
                    resolved_profiles=(machine, process, filament),
                    evidence=evidence,
                    differences=tuple(differences),
                    unknown_keys=tuple(sorted(unknown)),
                    exclusions=exclusions,
                    rank=rank,
                    exact_identifier_count=exact_identifiers,
                    critical_match_count=matches,
                    critical_mismatch_count=len(differences),
                    validation_state=(
                        ProfileValidationState.STRUCTURALLY_VALID
                        if not exclusions
                        else ProfileValidationState.INVALID
                    ),
                    cross_slicer=cross_slicer,
                    temporary_overrides=candidate_critical,
                )
            )
        candidates.sort(
            key=lambda item: (
                bool(item.exclusions),
                -item.rank,
                -item.exact_identifier_count,
                item.critical_mismatch_count,
                item.bundle_id,
            )
        )
        return tuple(candidates)

    def _hard_exclusions(
        self,
        snapshot: GCodeAnalysisSnapshot,
        source_values: Mapping[str, Any],
        installation: SlicerInstallation,
        machine: ResolvedProfile,
        process: ResolvedProfile,
        filament: ResolvedProfile,
        effective: Mapping[str, Any],
        gcode_evidence: GCodeProfileEvidence,
    ) -> tuple[ProfileHardExclusion, ...]:
        issues: list[ProfileHardExclusion] = []
        self._exclude_value_mismatch(
            issues,
            ProfileExclusionCode.WRONG_TECHNOLOGY,
            "Drucktechnologie stimmt nicht überein.",
            source_values.get("printer_technology"),
            effective.get("printer_technology"),
            machine.record.profile_id,
        )
        self._exclude_value_mismatch(
            issues,
            ProfileExclusionCode.NOZZLE_MISMATCH,
            "Düsendurchmesser stimmt nicht überein.",
            source_values.get("nozzle_diameter"),
            effective.get("nozzle_diameter"),
            machine.record.profile_id,
        )
        self._exclude_value_mismatch(
            issues,
            ProfileExclusionCode.GCODE_DIALECT_MISMATCH,
            "G-Code-Dialekt ist inkompatibel.",
            source_values.get("gcode_flavor"),
            effective.get("gcode_flavor"),
            machine.record.profile_id,
        )
        printable_height = _to_float(effective.get("printable_height"))
        if (
            printable_height is not None
            and printable_height + 1e-6 < snapshot.maximum_print_z_mm
        ):
            issues.append(
                ProfileHardExclusion(
                    ProfileExclusionCode.BUILD_VOLUME_TOO_SMALL,
                    "Der Bauraum ist niedriger als das Quellobjekt.",
                    machine.record.profile_id,
                )
            )
        source_extruder_count = _explicit_extruder_count(source_values)
        candidate_extruder_count = _explicit_extruder_count(effective)
        if (
            source_extruder_count is not None
            and candidate_extruder_count is not None
            and source_extruder_count != candidate_extruder_count
        ):
            issues.append(
                ProfileHardExclusion(
                    ProfileExclusionCode.EXTRUDER_COUNT_MISMATCH,
                    "Die explizite Anzahl physischer Extruder stimmt nicht überein.",
                    machine.record.profile_id,
                )
            )
        if gcode_evidence.special_procedure_seen:
            issues.append(
                ProfileHardExclusion(
                    ProfileExclusionCode.UNSUPPORTED_TOOL_CHANGE,
                    "Nicht unterstütztes Filament-/Werkzeugwechselverfahren erkannt.",
                )
            )
        machine_names = {
            machine.record.name.casefold(),
            machine.record.profile_id.casefold(),
            str(effective.get("printer_settings_id", "")).casefold(),
        }
        for item in (process, filament):
            compatible = _as_sequence(item.effective_values.get("compatible_printers"))
            if compatible and not any(
                str(value).casefold() in machine_names for value in compatible
            ):
                issues.append(
                    ProfileHardExclusion(
                        ProfileExclusionCode.INCOMPATIBLE_PROFILE_COMBINATION,
                        f"Profil '{item.record.name}' ist nicht mit dem Maschinenprofil kompatibel.",
                        item.record.profile_id,
                    )
                )
        for item in (machine, process, filament):
            minimum = item.effective_values.get("minimum_slicer_version")
            maximum = item.effective_values.get("maximum_slicer_version")
            if not _version_in_range(installation.version, minimum, maximum):
                issues.append(
                    ProfileHardExclusion(
                        ProfileExclusionCode.INCOMPATIBLE_PROFILE_VERSION,
                        f"Profil '{item.record.name}' ist für diese Slicerversion ungültig.",
                        item.record.profile_id,
                    )
                )
        return tuple(issues)

    @staticmethod
    def _exclude_value_mismatch(
        issues: list[ProfileHardExclusion],
        code: ProfileExclusionCode,
        message: str,
        source_value: Any,
        candidate_value: Any,
        profile_id: str,
    ) -> None:
        if (
            source_value is not None
            and candidate_value is not None
            and not _values_equal(source_value, candidate_value)
        ):
            issues.append(ProfileHardExclusion(code, message, profile_id))

    @staticmethod
    def _classify(
        usable: tuple[ProfileBundleMatch, ...],
        source_ids: Mapping[ProfileRole, tuple[str, ...]],
        source_family: SlicerFamily,
        target_family: SlicerFamily,
    ) -> ProfileMatchState:
        first = usable[0]
        if source_family is not SlicerFamily.UNKNOWN and source_family is not target_family:
            return ProfileMatchState.COMPATIBLE
        if len(usable) > 1:
            second = usable[1]
            if (
                first.rank == second.rank
                and first.exact_identifier_count == second.exact_identifier_count
                and first.critical_mismatch_count == second.critical_mismatch_count
            ):
                return ProfileMatchState.AMBIGUOUS
        # MACHINE_MODEL and MACHINE_VARIANT use the same source setting ID and
        # therefore form one identifier category, not two independent pieces
        # of evidence.
        required_ids = (
            int(bool(
                source_ids.get(ProfileRole.MACHINE_VARIANT, ())
                or source_ids.get(ProfileRole.MACHINE_MODEL, ())
            ))
            + int(bool(source_ids.get(ProfileRole.PROCESS, ())))
            + int(bool(source_ids.get(ProfileRole.FILAMENT, ())))
        )
        if (
            required_ids >= 2
            and first.exact_identifier_count >= required_ids
            and first.critical_mismatch_count == 0
        ):
            return ProfileMatchState.MATCHED
        if required_ids and first.exact_identifier_count < required_ids:
            return ProfileMatchState.COMPATIBLE
        if first.critical_mismatch_count == 0 and first.critical_match_count >= 6:
            return ProfileMatchState.MATCHED
        return ProfileMatchState.COMPATIBLE

    @staticmethod
    def _is_reconstructable(
        source_values: Mapping[str, Any],
        source_critical: Mapping[str, Any],
    ) -> bool:
        required = {
            "printer_technology",
            "nozzle_diameter",
            "gcode_flavor",
            "printer_model",
            "layer_height",
            "line_width",
        }
        return (
            required.issubset(source_values)
            and len(source_values) >= 12
            and len(source_critical) >= 6
        )

    @staticmethod
    def _gcode_restrictions(
        snapshot: GCodeAnalysisSnapshot,
        installation: SlicerInstallation,
        selected: ProfileBundleMatch,
        state: ProfileMatchState,
        evidence: GCodeProfileEvidence,
    ) -> tuple[str, ...]:
        restrictions: list[str] = []
        source_family = snapshot.metadata.slicer.family
        if (
            source_family is SlicerFamily.UNKNOWN
            or source_family is not installation.family
        ):
            restrictions.append("Quell- und Ausführungs-Slicer gehören nicht derselben bestätigten Familie an.")
        if state not in {ProfileMatchState.RECONSTRUCTED, ProfileMatchState.MATCHED}:
            restrictions.append("Profilzuordnung ist nicht eindeutig genug für den G-Code-Modus.")
        if selected.validation_state is not ProfileValidationState.PROBE_VALIDATED:
            restrictions.append("Profilkombination wurde noch nicht durch einen Probeslice validiert.")
        if not evidence.absolute_xy_known or evidence.relative_xy_extrusion_seen:
            restrictions.append("Koordinatenmodus ist unbekannt oder nicht unterstützt.")
        if not evidence.extrusion_mode_known:
            restrictions.append("Extrusionsmodus ist im Quell-G-Code nicht eindeutig.")
        if evidence.active_tool_count > 1 or evidence.special_procedure_seen:
            restrictions.append("Mehrwerkzeug- oder Sonderdruckverfahren wird nicht unterstützt.")
        return tuple(dict.fromkeys(restrictions))

    @staticmethod
    def _state_message(
        state: ProfileMatchState,
        requires_confirmation: bool,
        user_confirmed: bool,
    ) -> str:
        if state is ProfileMatchState.RECONSTRUCTED:
            return "Effektive G-Code-Konfiguration wurde rekonstruiert und validiert."
        if state is ProfileMatchState.MATCHED:
            return "Installierte Profilkombination stimmt bei starken Identifikatoren und kritischen Werten überein."
        if user_confirmed:
            return "Bestätigte Profilzuordnung wurde sicher wiederverwendet."
        if state is ProfileMatchState.AMBIGUOUS:
            return "Mehrere Profilkombinationen sind gleichwertig; Auswahl muss bestätigt werden."
        if requires_confirmation:
            return "Kompatible Profilkombination gefunden; Auswahl muss bestätigt werden."
        return "Keine verwendbare Profilkombination gefunden."

    @staticmethod
    def _invalid_resolution_candidate(
        installation: SlicerInstallation,
        resolved: ResolvedProfile,
    ) -> ProfileBundleMatch:
        profile = EffectiveProfile(
            installation=installation,
            machine=(resolved.record if resolved.record.kind is ProfileKind.MACHINE else None),
            process=(resolved.record if resolved.record.kind is ProfileKind.PROCESS else None),
            filaments=((resolved.record,) if resolved.record.kind is ProfileKind.FILAMENT else ()),
        )
        return ProfileBundleMatch(
            bundle_id=profile_bundle_id(profile),
            effective_profile=profile,
            resolved_profiles=(resolved,),
            evidence=(),
            differences=(),
            unknown_keys=(),
            exclusions=(
                ProfileHardExclusion(
                    ProfileExclusionCode.UNRESOLVED_INHERITANCE,
                    " ".join(resolved.errors),
                    resolved.record.profile_id,
                ),
            ),
            rank=-10_000,
            exact_identifier_count=0,
            critical_match_count=0,
            critical_mismatch_count=0,
            validation_state=ProfileValidationState.INVALID,
        )


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


def _record_matches_id(record: ProfileRecord, selected_id: str) -> bool:
    normalized = selected_id.casefold()
    return (
        record.profile_id.casefold() == normalized
        or record.name.casefold() == normalized
        or str(record.path).casefold() == normalized
    )


def _as_sequence(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(value)
    return (value,)


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
