from __future__ import annotations

import itertools
import math
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from cooling_tower.models.analysis import GCodeAnalysisSnapshot
from cooling_tower.models.gcode_metadata import (
    GCodeMetadata,
    SlicerFamily,
    SlicerIdentity,
)
from cooling_tower.models.source import SourceArtifact, SourceKind
from cooling_tower.slicers.adapter import SlicerAdapter
from cooling_tower.slicers.active_presets import read_active_presets
from cooling_tower.slicers.models import (
    EffectiveProfile,
    ProfileKind,
    ProfileRecord,
    ProfileSelectionReference,
    SlicerInstallation,
)
from cooling_tower.slicers.profile_inventory import (
    ProfileInheritanceResolver,
    ProfileInventoryService,
)
from cooling_tower.slicers.profile_mappings import ProfileMappingStore
from cooling_tower.slicers.profile_models import (
    ProfileCatalog,
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


from cooling_tower.slicers.profile_rules import (
    _profile_identifiers,
    _machine_compatibility_identifiers,
    _machine_scope_identifiers,
    _recognized_machine_scopes,
    _normalise_profile_identity,
    _is_selectable_profile,
    _resolve_selected_profile_ids,
    _paths_refer_to_same_file,
    _record_matches_id,
    _as_sequence,
    _text_values,
    _positive_finite_numbers,
    _profile_nozzle_diameters,
    _nozzle_values_compatible,
    _compatibility_values,
    _safe_printer_note_pattern_match,
    _normalise_value,
    _normalise_scalar,
    _values_equal,
    _to_float,
    _explicit_extruder_count,
    _version_tuple,
    _version_in_range,
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
class ProfileMatchingContext:
    """Neutral input for G-code evidence or an STL source inventory match."""

    source_kind: SourceKind | None
    source_artifact: SourceArtifact | None = None
    gcode_snapshot: GCodeAnalysisSnapshot | None = None

    def __post_init__(self) -> None:
        if self.source_kind is None and self.gcode_snapshot is None:
            raise ValueError("Für G-Code fehlt der Analyse-Snapshot.")
        if self.source_kind is SourceKind.STL and self.source_artifact is None:
            raise ValueError("Für STL fehlt die unveränderliche Quellenidentität.")
        if (
            self.source_artifact is not None
            and self.source_artifact.source_kind is not self.source_kind
        ):
            raise ValueError("Profilkontext und Quellenidentität widersprechen sich.")
        if self.source_kind is SourceKind.STL and self.gcode_snapshot is not None:
            raise ValueError("STL-Profilmatching darf keinen G-Code-Snapshot vortäuschen.")

    @classmethod
    def from_gcode(
        cls,
        snapshot: GCodeAnalysisSnapshot,
        source_artifact: SourceArtifact | None = None,
    ) -> "ProfileMatchingContext":
        return cls(None, source_artifact, snapshot)

    @classmethod
    def from_stl(
        cls,
        source_artifact: SourceArtifact,
    ) -> "ProfileMatchingContext":
        return cls(SourceKind.STL, source_artifact, None)


@dataclass(frozen=True, slots=True)
class ProfileFilterContext:
    source: str
    machine_ids: tuple[str, ...] = ()
    process_ids: tuple[str, ...] = ()
    filament_ids: tuple[str, ...] = ()
    printer_model: str | None = None
    nozzle_diameters_mm: tuple[float, ...] = ()
    source_path: Path | None = None
    active_preset_fingerprint: str | None = None

    @property
    def usable(self) -> bool:
        return bool(
            self.machine_ids
            or self.printer_model
            or self.nozzle_diameters_mm
        )


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

    def catalog(
        self,
        installation: SlicerInstallation,
        adapter: SlicerAdapter,
        *,
        force_inventory: bool = False,
        selected_machine: str | ProfileSelectionReference | None = None,
        selected_profile_ids: Mapping[
            str, str | ProfileSelectionReference
        ] | None = None,
        include_all_profiles: bool = False,
        prefer_active_presets: bool = False,
    ) -> ProfileCatalog:
        """Load selectable profiles without requiring or modifying a source.

        Inventory discovery is intentionally read-only. Compatibility and
        effective-value validation remain part of :meth:`match` once a real
        STL or G-code source is available.
        """

        inventory = self.inventory_service.load(
            adapter,
            installation,
            force=force_inventory,
        )
        resolved = ProfileInheritanceResolver(inventory, adapter).resolve_all()
        all_machine_options = self._selectable_options(
            resolved,
            (ProfileRole.MACHINE_VARIANT, ProfileRole.MACHINE_MODEL),
        )
        all_process_options = self._selectable_options(
            resolved,
            (ProfileRole.PROCESS,),
        )
        all_filament_options = self._selectable_options(
            resolved,
            (ProfileRole.FILAMENT,),
        )
        active = read_active_presets(installation)
        active_context = ProfileFilterContext(
            source="slicer",
            machine_ids=active.printer_ids,
            process_ids=active.process_ids,
            filament_ids=active.filament_ids,
            nozzle_diameters_mm=active.nozzle_diameters_mm,
            source_path=active.source_path,
            active_preset_fingerprint=active.fingerprint_sha256,
        )
        requested_selections = dict(selected_profile_ids or {})
        requested_machine = selected_machine or requested_selections.get(
            "machine"
        )
        if prefer_active_presets and active.has_printer_context:
            requested_selections.clear()
            requested_machine = None
        elif requested_machine is not None:
            # A removed or formerly cross-vendor preset must not suppress the
            # slicer's current machine context and later fall through to the
            # alphabetically first machine.  Resolve the reference before it
            # is allowed to become the filtering authority.
            resolved_requested_machine = _resolve_selected_profile_ids(
                {"machine": requested_machine},
                machine_options=all_machine_options,
                process_options=all_process_options,
                filament_options=all_filament_options,
            ).get("machine")
            if resolved_requested_machine is None:
                requested_selections.pop("machine", None)
                requested_machine = None
        automatic_machine_selection = False
        if requested_machine is None and active.has_printer_context:
            scored_active_machines = tuple(
                (item, self._machine_context_score(item, active_context))
                for item in resolved
                if item.valid
                and _is_selectable_profile(item)
                and item.role
                in {ProfileRole.MACHINE_VARIANT, ProfileRole.MACHINE_MODEL}
            )
            best_active_score = max(
                (score for _item, score in scored_active_machines),
                default=0,
            )
            active_machines = tuple(
                item
                for item, score in scored_active_machines
                if best_active_score > 0 and score == best_active_score
            )
            if active_machines:
                selected_active = min(
                    active_machines,
                    key=self._option_preference,
                ).record
                requested_machine = ProfileSelectionReference(
                    selected_active.profile_id,
                    selected_active.path,
                )
                automatic_machine_selection = True
                for role, identifiers in (
                    ("process", active.process_ids),
                    ("filament", active.filament_ids),
                ):
                    if role not in requested_selections and identifiers:
                        requested_selections[role] = identifiers[0]
        if requested_machine is None and len(all_machine_options) == 1:
            only_machine = all_machine_options[0]
            requested_machine = ProfileSelectionReference(
                only_machine.profile_id,
                only_machine.path,
            )
        if requested_machine is not None:
            requested_selections["machine"] = requested_machine
        selected_ids = _resolve_selected_profile_ids(
            requested_selections,
            machine_options=all_machine_options,
            process_options=all_process_options,
            filament_options=all_filament_options,
        )
        selected_machine_path = selected_ids.get("machine")
        machine_record = next(
            (
                item
                for item in all_machine_options
                if selected_machine_path is not None
                and _paths_refer_to_same_file(
                    item.path,
                    Path(selected_machine_path),
                )
            ),
            None,
        )
        machine_resolved = next(
            (
                item
                for item in resolved
                if machine_record is not None
                and item.record.path == machine_record.path
                and item.record.profile_id.casefold()
                == machine_record.profile_id.casefold()
            ),
            None,
        )
        if automatic_machine_selection:
            filter_context = replace(
                active_context,
                printer_model=(
                    str(
                        machine_resolved.effective_values.get(
                            "printer_model", ""
                        )
                    )
                    or None
                    if machine_resolved is not None
                    else None
                ),
                nozzle_diameters_mm=(
                    active.nozzle_diameters_mm
                    or (
                        _profile_nozzle_diameters(machine_resolved)
                        if machine_resolved is not None
                        else ()
                    )
                ),
            )
        else:
            filter_context = ProfileFilterContext(
                source="manual",
                machine_ids=(
                    (machine_record.profile_id,) if machine_record else ()
                ),
                printer_model=(
                    str(
                        machine_resolved.effective_values.get(
                            "printer_model", ""
                        )
                    )
                    or None
                    if machine_resolved is not None
                    else None
                ),
                nozzle_diameters_mm=(
                    _profile_nozzle_diameters(machine_resolved)
                    if machine_resolved is not None
                    else ()
                ),
            )
        (
            machine_options,
            process_options,
            filament_options,
            profiles_filtered,
            filter_summary,
        ) = self._filter_profile_options(
            resolved,
            filter_context,
            include_all_profiles=include_all_profiles,
            all_options=(
                all_machine_options,
                all_process_options,
                all_filament_options,
            ),
        )

        def selected_record(
            role: str,
            options: Sequence[ProfileRecord],
        ) -> ProfileRecord | None:
            selected_path = selected_ids.get(role)
            if selected_path is None:
                return None
            return next(
                (
                    item
                    for item in options
                    if _paths_refer_to_same_file(
                        item.path,
                        Path(selected_path),
                    )
                ),
                None,
            )

        selected_process_record = selected_record(
            "process", process_options
        )
        selected_filament_record = selected_record(
            "filament", filament_options
        )
        return ProfileCatalog(
            content_fingerprints={str(item.record.path): item.fingerprint_sha256
                                  for item in resolved if item.valid and item.fingerprint_sha256},
            execution_slicer=installation,
            inventory_fingerprint=inventory.fingerprint_sha256,
            machine_options=machine_options,
            process_options=process_options,
            filament_options=filament_options,
            rejected_profile_count=sum(not item.valid for item in resolved),
            profiles_filtered=profiles_filtered,
            profile_filter_summary=filter_summary,
            selected_machine=(
                ProfileSelectionReference(
                    machine_record.profile_id,
                    machine_record.path,
                )
                if machine_record is not None
                else None
            ),
            selected_process=(
                ProfileSelectionReference(
                    selected_process_record.profile_id,
                    selected_process_record.path,
                )
                if selected_process_record is not None
                else None
            ),
            selected_filament=(
                ProfileSelectionReference(
                    selected_filament_record.profile_id,
                    selected_filament_record.path,
                )
                if selected_filament_record is not None
                else None
            ),
        )

    def match(
        self,
        source: GCodeAnalysisSnapshot | ProfileMatchingContext,
        installation: SlicerInstallation,
        adapter: SlicerAdapter,
        *,
        selected_profile_ids: Mapping[
            str, str | ProfileSelectionReference
        ] | None = None,
        force_inventory: bool = False,
        include_all_profiles: bool = False,
    ) -> ProfileMatchResult:
        context = (
            source
            if isinstance(source, ProfileMatchingContext)
            else ProfileMatchingContext.from_gcode(source)
        )
        snapshot = context.gcode_snapshot
        inventory = self.inventory_service.load(
            adapter,
            installation,
            force=force_inventory,
        )
        resolver = ProfileInheritanceResolver(inventory, adapter)
        resolved = resolver.resolve_all()
        if snapshot is not None:
            source_values = metadata_values(snapshot.metadata)
            source_critical = critical_values(source_values)
            source_critical_fingerprint = stable_json_fingerprint(source_critical)
            source_profile_fingerprint = (
                snapshot.metadata.profile_fingerprint.digest_sha256
            )
            source_slicer = snapshot.metadata.slicer
            gcode_evidence = self._gcode_evidence(snapshot)
        else:
            artifact = context.source_artifact
            assert artifact is not None
            source_values = {}
            source_critical = {}
            source_critical_fingerprint = stable_json_fingerprint(
                {
                    "source_kind": context.source_kind.value,
                    "source_sha256": artifact.original_sha256,
                }
            )
            source_profile_fingerprint = f"stl:{artifact.original_sha256}"
            source_slicer = SlicerIdentity()
            gcode_evidence = GCodeProfileEvidence(
                absolute_xy_known=False,
                relative_xy_extrusion_seen=False,
                extrusion_mode_known=False,
                tool_indices=(),
                special_procedure_seen=False,
            )
        requested_profile_selections = {
            str(key).casefold(): value
            for key, value in (selected_profile_ids or {}).items()
            if value
        }
        remembered_selection_requested = any(
            isinstance(value, ProfileSelectionReference)
            for value in requested_profile_selections.values()
        )

        all_machine_options = self._selectable_options(
            resolved,
            (ProfileRole.MACHINE_VARIANT, ProfileRole.MACHINE_MODEL),
        )
        all_process_options = self._selectable_options(
            resolved,
            (ProfileRole.PROCESS,),
        )
        all_filament_options = self._selectable_options(
            resolved,
            (ProfileRole.FILAMENT,),
        )
        selected_profile_ids = _resolve_selected_profile_ids(
            requested_profile_selections,
            machine_options=all_machine_options,
            process_options=all_process_options,
            filament_options=all_filament_options,
        )
        filter_context = self._profile_filter_context(
            source_values,
            selected_profile_ids,
            installation,
            resolved,
        )
        ranked_profile_ids = dict(selected_profile_ids)
        if filter_context.source == "slicer":
            for role, identifiers in (
                ("machine", filter_context.machine_ids),
                ("process", filter_context.process_ids),
                ("filament", filter_context.filament_ids),
            ):
                if role not in ranked_profile_ids and identifiers:
                    ranked_profile_ids[role] = identifiers[0]
        (
            machine_options,
            process_options,
            filament_options,
            profiles_filtered,
            filter_summary,
        ) = self._filter_profile_options(
            resolved,
            filter_context,
            include_all_profiles=include_all_profiles,
            all_options=(
                all_machine_options,
                all_process_options,
                all_filament_options,
            ),
        )
        # Candidate generation must use the same contextual inventory that
        # backs the selectors.  Previously the UI displayed the filtered
        # 2/20/25 records while matching independently examined the first ten
        # records of every unfiltered role.  A valid combination could then be
        # displayed but reported as unavailable until any manual selection
        # happened to promote its three paths.
        candidate_options = (
            machine_options,
            process_options,
            filament_options,
        )
        if include_all_profiles:
            # "Alle Profile anzeigen" only expands the catalogue.  It must
            # not replace the safe automatic proposal with arbitrary machines
            # that are unrelated to the active/filter context.
            candidate_options = self._filter_profile_options(
                resolved,
                filter_context,
                include_all_profiles=False,
                all_options=(
                    all_machine_options,
                    all_process_options,
                    all_filament_options,
                ),
            )[:3]
        candidate_paths = {
            "machine": {
                Path(record.path).resolve()
                for record in candidate_options[0]
            },
            "process": {
                Path(record.path).resolve()
                for record in candidate_options[1]
            },
            "filament": {
                Path(record.path).resolve()
                for record in candidate_options[2]
            },
        }
        role_groups = self._role_groups(resolved)
        source_ids = self._source_identifiers(source_values)
        ranked_roles = {
            role: self._rank_role_records(
                tuple(
                    item
                    for item in role_groups.get(role, ())
                    if Path(item.record.path).resolve()
                    in candidate_paths[
                        "machine"
                        if role
                        in {
                            ProfileRole.MACHINE_VARIANT,
                            ProfileRole.MACHINE_MODEL,
                        }
                        else role.value
                    ]
                ),
                role,
                source_values,
                source_critical,
                source_ids.get(role, ()),
                ranked_profile_ids.get(role.value)
                or (
                    ranked_profile_ids.get("machine")
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
        known_machine_profiles = tuple(
            item
            for item in resolved
            if item.valid
            and item.role
            in {ProfileRole.MACHINE_VARIANT, ProfileRole.MACHINE_MODEL}
        )

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
            known_machine_profiles,
        )
        if not candidates:
            # Preserve hard-exclusion diagnostics (for example an explicitly
            # identified 0.6 mm source against a 0.4 mm inventory) when the
            # contextual filter intentionally leaves a selector empty. Never
            # promote a hidden usable bundle: this fallback is diagnostic
            # only and therefore accepted solely when every bundle is invalid.
            diagnostic_ranked_roles = {
                role: self._rank_role_records(
                    role_groups.get(role, ()),
                    role,
                    source_values,
                    source_critical,
                    source_ids.get(role, ()),
                    ranked_profile_ids.get(role.value)
                    or (
                        ranked_profile_ids.get("machine")
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
            diagnostic_candidates = self._build_candidates(
                installation,
                snapshot,
                source_values,
                source_critical,
                source_ids,
                gcode_evidence,
                self._merge_machine_options(diagnostic_ranked_roles),
                diagnostic_ranked_roles[ProfileRole.PROCESS],
                diagnostic_ranked_roles[ProfileRole.FILAMENT],
                known_machine_profiles,
            )
            if diagnostic_candidates and not any(
                candidate.usable for candidate in diagnostic_candidates
            ):
                candidates = diagnostic_candidates
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
            if remembered_selection_requested:
                # Slicer updates can leave individually existing presets
                # mutually incompatible. A persisted convenience preference
                # must never make an otherwise usable source unavailable.
                return self.match(
                    source,
                    installation,
                    adapter,
                    selected_profile_ids=None,
                    force_inventory=False,
                    include_all_profiles=include_all_profiles,
                )
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
                source_slicer=source_slicer,
                execution_slicer=installation,
                inventory_fingerprint=inventory.fingerprint_sha256,
                source_profile_fingerprint=source_profile_fingerprint,
                source_critical_fingerprint=source_critical_fingerprint,
                gcode_restrictions=("Keine gültige Profilkombination.",),
                profiles_filtered=profiles_filtered,
                profile_filter_source=(
                    filter_context.source if filter_context.usable else None
                ),
                profile_filter_summary=filter_summary,
                unfiltered_option_counts=(
                    len(all_machine_options),
                    len(all_process_options),
                    len(all_filament_options),
                ),
                visible_option_counts=(
                    len(machine_options),
                    len(process_options),
                    len(filament_options),
                ),
                active_preset_fingerprint=(
                    filter_context.active_preset_fingerprint
                ),
                source_kind=context.source_kind,
            )

        selected = usable[0]
        state = self._classify(
            usable,
            source_ids,
            source_slicer.family,
            installation.family,
        )
        explicit_selection = bool(selected_profile_ids)
        user_confirmed = False

        if (
            snapshot is not None
            and not explicit_selection
            and self._is_reconstructable(source_values, source_critical)
        ):
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
        if snapshot is not None and state is not ProfileMatchState.RECONSTRUCTED:
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
            if self.mapping_store is not None and snapshot is not None
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

        display_filter_context = filter_context
        if selected.machine is not None:
            # The actual selected machine is the authoritative context for
            # visible system process/filament presets. This second, cheap
            # filtering pass prevents a broader initial G-code or user-printer
            # context from mixing system presets for several machines.
            resolved_selected_machine = next(
                (
                    item
                    for item in selected.resolved_profiles
                    if item.role
                    in {
                        ProfileRole.MACHINE_VARIANT,
                        ProfileRole.MACHINE_MODEL,
                    }
                    and item.record.path == selected.machine.path
                ),
                None,
            )
            selected_model = (
                str(
                    resolved_selected_machine.effective_values.get(
                        "printer_model",
                        "",
                    )
                ).strip()
                if resolved_selected_machine is not None
                else ""
            )
            display_filter_context = replace(
                filter_context,
                machine_ids=(str(selected.machine.path),),
                printer_model=selected_model or None,
                nozzle_diameters_mm=(
                    _profile_nozzle_diameters(resolved_selected_machine)
                    if resolved_selected_machine is not None
                    else ()
                ),
            )
            (
                machine_options,
                process_options,
                filament_options,
                profiles_filtered,
                filter_summary,
            ) = self._filter_profile_options(
                resolved,
                display_filter_context,
                include_all_profiles=include_all_profiles,
                all_options=(
                    all_machine_options,
                    all_process_options,
                    all_filament_options,
                ),
            )

        requires_confirmation = (
            (
                context.source_kind is SourceKind.STL
                and state is not ProfileMatchState.UNAVAILABLE
            )
            or (
                state in {ProfileMatchState.COMPATIBLE, ProfileMatchState.AMBIGUOUS}
                and not user_confirmed
            )
        )
        restrictions = (
            self._gcode_restrictions(
                snapshot,
                installation,
                selected,
                state,
                gcode_evidence,
            )
            if snapshot is not None
            else ()
        )
        can_use_gcode = not restrictions and not requires_confirmation
        can_use_stl = (
            state is not ProfileMatchState.UNAVAILABLE
            and selected.validation_state is not ProfileValidationState.INVALID
            and installation.can_slice
        )
        effective_profile_fingerprint = stable_json_fingerprint(
            selected.effective_profile.effective_values
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
            source_slicer=source_slicer,
            execution_slicer=installation,
            inventory_fingerprint=inventory.fingerprint_sha256,
            source_profile_fingerprint=source_profile_fingerprint,
            source_critical_fingerprint=source_critical_fingerprint,
            gcode_restrictions=restrictions,
            profiles_filtered=profiles_filtered,
            profile_filter_source=(
                filter_context.source if filter_context.usable else None
            ),
            profile_filter_summary=filter_summary,
            unfiltered_option_counts=(
                len(all_machine_options),
                len(all_process_options),
                len(all_filament_options),
            ),
            visible_option_counts=(
                len(machine_options),
                len(process_options),
                len(filament_options),
            ),
            active_preset_fingerprint=(
                filter_context.active_preset_fingerprint
            ),
            source_kind=context.source_kind,
            effective_profile_fingerprint=effective_profile_fingerprint,
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
            can_use_stl_mode=(
                result.execution_slicer.can_slice
                and result.selected.validation_state
                is not ProfileValidationState.INVALID
            ),
            can_use_gcode_mode=not restrictions,
            message=(
                "STL-Profile wurden bestätigt; das Modell kann analysiert werden."
                if result.source_kind is SourceKind.STL
                else "Profilkombination wurde bestätigt und sicher gespeichert."
            ),
            gcode_restrictions=restrictions,
        )

    def inventory_is_stale(self, result: ProfileMatchResult) -> bool:
        inventory = self.inventory_service.cached_inventory(
            result.execution_slicer
        )
        if inventory is None or self.inventory_service.is_stale(inventory):
            return True
        if result.profile_filter_source == "slicer":
            current = read_active_presets(result.execution_slicer)
            return (
                current.fingerprint_sha256
                != result.active_preset_fingerprint
            )
        return False

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
        selected: dict[
            ProfileRole,
            dict[tuple[ProfileRole, str, str | None], ResolvedProfile],
        ] = {}
        for item in resolved:
            if not item.valid or not _is_selectable_profile(item):
                continue
            # Vendor resources, OTA mirrors and the local system cache often
            # expose the same effective preset at several paths.  This is one
            # candidate and must not create artificial ambiguity.
            key = (
                item.role,
                item.record.profile_id.casefold(),
                item.fingerprint_sha256,
            )
            current = selected.setdefault(item.role, {}).get(key)
            if current is None or ProfileMatchingService._option_preference(
                item
            ) < ProfileMatchingService._option_preference(current):
                selected[item.role][key] = item
        return {
            role: tuple(items.values())
            for role, items in selected.items()
        }

    @classmethod
    def _profile_filter_context(
        cls,
        source_values: Mapping[str, Any],
        selected_profile_ids: Mapping[str, str],
        installation: SlicerInstallation,
        resolved: Sequence[ResolvedProfile],
    ) -> ProfileFilterContext:
        gcode_machine_ids = _text_values(
            source_values.get("printer_settings_id")
        )
        gcode_process_ids = _text_values(
            source_values.get("print_settings_id")
        )
        gcode_filament_ids = _text_values(
            source_values.get("filament_settings_id")
        )
        printer_model_values = _text_values(source_values.get("printer_model"))
        printer_model = (
            printer_model_values[0] if printer_model_values else None
        )
        gcode_nozzles = _positive_finite_numbers(
            source_values.get("nozzle_diameter")
        )

        selected_machine = selected_profile_ids.get("machine")
        if selected_machine:
            resolved_machine = next(
                (
                    item
                    for item in resolved
                    if item.valid
                    and item.role
                    in {
                        ProfileRole.MACHINE_VARIANT,
                        ProfileRole.MACHINE_MODEL,
                    }
                    and _record_matches_id(item.record, selected_machine)
                ),
                None,
            )
            # The manually selected machine, including its inherited model
            # and nozzle metadata, is authoritative for filtering. Retaining
            # those values from the imported G-code would suppress the system
            # presets belonging to a deliberately selected machine variant.
            machine_id = (
                str(resolved_machine.record.path)
                if resolved_machine is not None
                else selected_machine
            )
            selected_model = (
                str(
                    resolved_machine.effective_values.get(
                        "printer_model",
                        "",
                    )
                ).strip()
                if resolved_machine is not None
                else ""
            )
            return ProfileFilterContext(
                source="manual",
                machine_ids=(machine_id,),
                process_ids=(
                    (selected_profile_ids["process"],)
                    if selected_profile_ids.get("process")
                    else ()
                ),
                filament_ids=(
                    (selected_profile_ids["filament"],)
                    if selected_profile_ids.get("filament")
                    else ()
                ),
                printer_model=selected_model or None,
                nozzle_diameters_mm=(
                    _profile_nozzle_diameters(resolved_machine)
                    if resolved_machine is not None
                    else ()
                ),
            )

        gcode_context = ProfileFilterContext(
            source="gcode",
            machine_ids=gcode_machine_ids,
            process_ids=gcode_process_ids,
            filament_ids=gcode_filament_ids,
            printer_model=printer_model,
            nozzle_diameters_mm=gcode_nozzles,
        )
        machine_profiles = tuple(
            item
            for item in resolved
            if item.valid
            and _is_selectable_profile(item)
            and item.role
            in {ProfileRole.MACHINE_VARIANT, ProfileRole.MACHINE_MODEL}
        )
        if (gcode_machine_ids or printer_model) and any(
            cls._machine_context_score(item, gcode_context) > 0
            for item in machine_profiles
        ):
            return gcode_context

        active = read_active_presets(installation)
        active_context = ProfileFilterContext(
            source="slicer",
            machine_ids=active.printer_ids,
            process_ids=active.process_ids,
            filament_ids=active.filament_ids,
            printer_model=None,
            nozzle_diameters_mm=(gcode_nozzles or active.nozzle_diameters_mm),
            source_path=active.source_path,
            active_preset_fingerprint=active.fingerprint_sha256,
        )
        active_machines = tuple(
            item
            for item in machine_profiles
            if cls._machine_context_score(item, active_context) > 0
        )
        if active.has_printer_context and active_machines:
            related_user_machines = cls._related_user_machine_profiles(
                active_machines,
                machine_profiles,
            )
            if related_user_machines:
                related_ids = tuple(
                    dict.fromkeys(
                        (
                            *active_context.machine_ids,
                            *(
                                item.record.profile_id
                                for item in related_user_machines
                            ),
                        )
                    )
                )
                return replace(active_context, machine_ids=related_ids)
            return active_context

        # A foreign project can leave the slicer's persisted active preset on
        # an unavailable project-only printer.  In that case, locally stored
        # user machine presets are stronger evidence of printers the user has
        # deliberately configured than that stale foreign identifier.
        user_machines = tuple(
            item
            for item in machine_profiles
            if item.record.source.casefold() == "user"
            and _nozzle_values_compatible(
                gcode_nozzles,
                _profile_nozzle_diameters(item),
            )
        )
        if user_machines:
            return ProfileFilterContext(
                source="user",
                machine_ids=tuple(
                    dict.fromkeys(
                        item.record.profile_id for item in user_machines
                    )
                ),
                nozzle_diameters_mm=gcode_nozzles,
                source_path=active.source_path,
                active_preset_fingerprint=active.fingerprint_sha256,
            )
        if gcode_nozzles:
            return ProfileFilterContext(
                source="gcode",
                machine_ids=(),
                process_ids=gcode_process_ids,
                filament_ids=gcode_filament_ids,
                printer_model=None,
                nozzle_diameters_mm=gcode_nozzles,
            )
        if gcode_context.usable:
            return gcode_context
        if active.has_printer_context:
            return active_context
        return ProfileFilterContext(source="none")

    @staticmethod
    def _related_user_machine_profiles(
        active_machines: Sequence[ResolvedProfile],
        machine_profiles: Sequence[ResolvedProfile],
    ) -> tuple[ResolvedProfile, ...]:
        active_identifiers = {
            value.casefold()
            for item in active_machines
            for value in _profile_identifiers(item)
        }
        active_models = {
            str(item.effective_values.get("printer_model", ""))
            .strip()
            .casefold()
            for item in active_machines
            if str(item.effective_values.get("printer_model", "")).strip()
        }
        active_nozzles = tuple(
            value
            for item in active_machines
            for value in _profile_nozzle_diameters(item)
        )
        result: list[ResolvedProfile] = []
        for item in machine_profiles:
            if item.record.source.casefold() != "user":
                continue
            own_identifiers = {
                value.casefold() for value in _profile_identifiers(item)
            }
            inherited_identifiers = {
                value.casefold()
                for record in item.chain[:-1]
                for value in (record.profile_id, record.name)
            }
            model = str(
                item.effective_values.get("printer_model", "")
            ).strip().casefold()
            same_identity = bool(own_identifiers & active_identifiers)
            inherits_active = bool(
                inherited_identifiers & active_identifiers
            )
            same_model = bool(model and model in active_models)
            nozzle_matches = _nozzle_values_compatible(
                active_nozzles,
                _profile_nozzle_diameters(item),
            )
            if nozzle_matches and (
                same_identity or inherits_active or same_model
            ):
                result.append(item)
        return tuple(result)

    @classmethod
    def _filter_profile_options(
        cls,
        resolved: Sequence[ResolvedProfile],
        context: ProfileFilterContext,
        *,
        include_all_profiles: bool,
        all_options: tuple[
            tuple[ProfileRecord, ...],
            tuple[ProfileRecord, ...],
            tuple[ProfileRecord, ...],
        ],
    ) -> tuple[
        tuple[ProfileRecord, ...],
        tuple[ProfileRecord, ...],
        tuple[ProfileRecord, ...],
        bool,
        str,
    ]:
        all_counts = tuple(len(items) for items in all_options)
        known_machine_profiles = tuple(
            item
            for item in resolved
            if item.valid
            and item.role
            in {ProfileRole.MACHINE_VARIANT, ProfileRole.MACHINE_MODEL}
        )
        machine_candidates = tuple(
            item
            for item in known_machine_profiles
            if _is_selectable_profile(item)
        )
        known_machine_scope_ids = frozenset(
            _normalise_profile_identity(value)
            for machine in known_machine_profiles
            for value in _machine_scope_identifiers(machine)
        )
        scored_machines = tuple(
            (item, cls._machine_context_score(item, context))
            for item in machine_candidates
        )
        best_machine_score = max(
            (score for _item, score in scored_machines),
            default=0,
        )
        machines = tuple(
            item
            for item, score in scored_machines
            if best_machine_score > 0 and score == best_machine_score
        )
        if (
            not machines
            and not context.usable
            and len(machine_candidates) == 1
        ):
            # A slicer installation with exactly one selectable machine has
            # an unambiguous local context even when it persists no active
            # preset file. Expose its compatible system process/filament
            # records instead of leaving both selectors empty.
            machines = machine_candidates
        user_machines = tuple(
            item
            for item in machine_candidates
            if item.record.source.casefold() == "user"
        )
        inherited_system_ids = {
            identifier.casefold()
            for item in machines
            if item.record.source.casefold() == "user"
            for identifier in item.record.inherits
        }
        inherited_system_machines = tuple(
            item
            for item in machine_candidates
            if item.record.source.casefold() != "user"
            and bool(
                inherited_system_ids.intersection(
                    {
                        item.record.profile_id.casefold(),
                        item.record.name.casefold(),
                    }
                )
            )
        )
        visible_machines = (
            machine_candidates
            if include_all_profiles
            else (
                *user_machines,
                *machines,
                *inherited_system_machines,
            )
        )
        if not visible_machines and not context.usable:
            # Without any user or active machine evidence the selector must
            # still offer a way to establish a context manually.
            visible_machines = machine_candidates
        machine_options = cls._selectable_options(
            visible_machines,
            (ProfileRole.MACHINE_VARIANT, ProfileRole.MACHINE_MODEL),
        )

        def role_is_visible(item: ResolvedProfile) -> bool:
            if include_all_profiles:
                return True
            if item.record.source.casefold() == "user":
                return True
            return bool(machines) and cls._profile_matches_machine_context(
                item,
                machines,
                context,
                known_machine_profiles,
                known_machine_scope_ids=known_machine_scope_ids,
            )

        process_resolved = tuple(
            item
            for item in resolved
            if item.valid
            and _is_selectable_profile(item)
            and item.role is ProfileRole.PROCESS
            and role_is_visible(item)
        )
        filament_resolved = tuple(
            item
            for item in resolved
            if item.valid
            and _is_selectable_profile(item)
            and item.role is ProfileRole.FILAMENT
            and role_is_visible(item)
        )
        process_options = cls._selectable_options(
            process_resolved,
            (ProfileRole.PROCESS,),
        )
        filament_options = cls._selectable_options(
            filament_resolved,
            (ProfileRole.FILAMENT,),
        )

        visible_counts = (
            len(machine_options),
            len(process_options),
            len(filament_options),
        )
        filtered = any(
            visible < total
            for visible, total in zip(visible_counts, all_counts)
        )
        source_label = {
            "gcode": "G-Code",
            "slicer": "zuletzt gespeicherte Slicer-Auswahl",
            "user": "lokale Benutzer-Druckerprofile",
            "manual": "manuelle Profilauswahl",
        }.get(context.source, context.source)
        identity = cls._filter_context_label(context)
        mode = (
            "alle Profile (Druckerfilter ausgesetzt)"
            if include_all_profiles
            else "aktive Maschinenprofile"
        )
        summary = (
            "Profilfilter\n"
            f"Quelle: {source_label}\n"
            f"Drucker: {identity}\n"
            f"Modus: {mode}\n"
            f"Sichtbar: Maschine {visible_counts[0]}/{all_counts[0]}  ·  "
            f"Filament {visible_counts[2]}/{all_counts[2]}  ·  "
            f"Prozess {visible_counts[1]}/{all_counts[1]}"
        )
        if not machines:
            summary += (
                "\nHinweis: Bis zur Auswahl eines Maschinenprofils werden "
                "nur User-Presets für Filament und Prozess angezeigt."
            )
        return (
            machine_options,
            process_options,
            filament_options,
            filtered,
            summary,
        )

    @staticmethod
    def _machine_context_score(
        item: ResolvedProfile,
        context: ProfileFilterContext,
    ) -> int:
        if not _nozzle_values_compatible(
            context.nozzle_diameters_mm,
            _profile_nozzle_diameters(item),
        ):
            return 0
        identifiers = {
            value.casefold() for value in _profile_identifiers(item)
        }
        requested_ids = {value.casefold() for value in context.machine_ids}
        if requested_ids:
            if identifiers.intersection(requested_ids) or any(
                _record_matches_id(item.record, value)
                for value in context.machine_ids
            ):
                return 300
            return 0
        model = str(item.effective_values.get("printer_model", "")).strip()
        if context.printer_model:
            if model.casefold() == context.printer_model.casefold():
                return 200 + int(bool(_profile_nozzle_diameters(item)))
            return 0
        if context.nozzle_diameters_mm:
            return 100 if _profile_nozzle_diameters(item) else 50
        return 0

    @classmethod
    def _profile_matches_machine_context(
        cls,
        item: ResolvedProfile,
        machines: Sequence[ResolvedProfile],
        context: ProfileFilterContext,
        known_machines: Sequence[ResolvedProfile],
        *,
        known_machine_scope_ids: frozenset[str] | None = None,
    ) -> bool:
        machine_names = {
            value.casefold()
            for machine in machines
            for value in _machine_compatibility_identifiers(machine)
        }
        compatible = {
            value.casefold()
            for value in _compatibility_values(
                item.effective_values.get("compatible_printers")
            )
        }
        if compatible and not machine_names.intersection(compatible):
            return False
        if not compatible:
            # A few Orca/Anycubic system catalogues omit compatibility fields
            # from otherwise explicitly machine-scoped presets. Their stable
            # naming convention is ``preset @ machine preset``. Treat the
            # suffix as a restriction only when it resolves to a real machine
            # in the same slicer inventory, so genuinely generic profiles and
            # unrelated uses of ``@`` remain visible.
            inferred_scopes = _recognized_machine_scopes(
                item,
                known_machines,
                known_machine_scope_ids=known_machine_scope_ids,
            )
            if inferred_scopes:
                selected_machine_scopes = {
                    _normalise_profile_identity(value)
                    for machine in machines
                    for value in _machine_scope_identifiers(machine)
                }
                if not inferred_scopes.issubset(selected_machine_scopes):
                    return False
        condition = str(
            item.effective_values.get("compatible_printers_condition", "")
            or ""
        ).strip()
        return cls._compatible_condition_matches(
            condition,
            machines,
            context,
        )

    @staticmethod
    def _compatible_condition_matches(
        condition: str,
        machines: Sequence[ResolvedProfile],
        context: ProfileFilterContext,
    ) -> bool:
        if not condition:
            return True
        if len(condition) > 4096:
            return True
        nozzle_requirements = tuple(
            float(value)
            for value in re.findall(
                r"nozzle_diameter(?:\[\d+\])?\s*==\s*([0-9]+(?:\.[0-9]+)?)",
                condition,
                flags=re.IGNORECASE,
            )
        )
        if (
            nozzle_requirements
            and context.nozzle_diameters_mm
            and not _nozzle_values_compatible(
                context.nozzle_diameters_mm,
                nozzle_requirements,
            )
        ):
            return False

        # Support the common Orca-family literal machine constraints without
        # evaluating arbitrary preset expressions. Multiple allowed values for
        # one key are treated as alternatives; different constrained keys all
        # have to match. Unsupported syntax remains unknown and is included.
        literal_keys = {
            value.casefold()
            for value in re.findall(
                r"\b(printer_model|printer_variant|printer_settings_id)\s*[!=]=",
                condition,
                flags=re.IGNORECASE,
            )
        }
        has_cross_key_or = bool(
            len(literal_keys) > 1
            and re.search(r"(?:\bor\b|\|\|)", condition, re.IGNORECASE)
        )
        for key in (() if has_cross_key_or else literal_keys):
            allowed = {
                match[2].casefold()
                for match in re.findall(
                    rf"\b({key})\s*==\s*([\"'])(.*?)\2",
                    condition,
                    flags=re.IGNORECASE,
                )
                if match[2]
            }
            forbidden = {
                match[2].casefold()
                for match in re.findall(
                    rf"\b({key})\s*!=\s*([\"'])(.*?)\2",
                    condition,
                    flags=re.IGNORECASE,
                )
                if match[2]
            }
            machine_values = {
                str(value).strip().strip('"').casefold()
                for machine in machines
                for value in (
                    _profile_identifiers(machine)
                    if key == "printer_settings_id"
                    else _as_sequence(machine.effective_values.get(key))
                )
                if str(value).strip().strip('"')
            }
            if allowed and not machine_values.intersection(allowed):
                return False
            if forbidden and machine_values.intersection(forbidden):
                return False

        printer_notes = "\n".join(
            str(machine.effective_values.get("printer_notes", ""))
            for machine in machines
        )
        positive_patterns = re.findall(
            r"printer_notes\s*=~\s*/(.+?)/",
            condition,
            flags=re.IGNORECASE,
        )
        negative_patterns = re.findall(
            r"printer_notes\s*!~\s*/(.+?)/",
            condition,
            flags=re.IGNORECASE,
        )
        positive_matches = tuple(
            _safe_printer_note_pattern_match(pattern, printer_notes)
            for pattern in positive_patterns[:16]
        )
        negative_matches = tuple(
            _safe_printer_note_pattern_match(pattern, printer_notes)
            for pattern in negative_patterns[:16]
        )
        if positive_matches:
            if any(value is True for value in positive_matches):
                pass
            elif any(value is None for value in positive_matches):
                # Unsupported expression syntax is not reliable evidence of
                # incompatibility.
                return True
            else:
                return False
        if any(value is True for value in negative_matches):
            return False
        return True

    @staticmethod
    def _filter_context_label(context: ProfileFilterContext) -> str:
        values: list[str] = []
        if context.machine_ids:
            identity = context.machine_ids[0]
            path = Path(identity)
            label = path.stem if path.is_absolute() else identity
            if len(context.machine_ids) > 1:
                label += f" (+{len(context.machine_ids) - 1} zugehörig)"
            values.append(label)
        elif context.printer_model:
            values.append(context.printer_model)
        if context.nozzle_diameters_mm:
            rendered = ", ".join(
                f"{value:g} mm" for value in context.nozzle_diameters_mm
            )
            values.append(f"Düse {rendered}")
        return " · ".join(values) or "aktiver Drucker"

    @staticmethod
    def _selectable_options(
        resolved: Sequence[ResolvedProfile],
        roles: tuple[ProfileRole, ...],
    ) -> tuple[ProfileRecord, ...]:
        """Return each valid logical preset once, without ranking limits."""

        selected: dict[tuple[str, str], ResolvedProfile] = {}
        for item in resolved:
            if (
                not item.valid
                or not _is_selectable_profile(item)
                or item.role not in roles
            ):
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
            if source == "system" and "system" in parts
            else 1
            if source == "system" and "resources" in parts
            else 2
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
        snapshot: GCodeAnalysisSnapshot | None,
        source_values: Mapping[str, Any],
        source_critical: Mapping[str, Any],
        source_ids: Mapping[ProfileRole, tuple[str, ...]],
        gcode_evidence: GCodeProfileEvidence,
        machines,
        processes,
        filaments,
        known_machines: Sequence[ResolvedProfile],
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
                known_machines,
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
                snapshot is not None
                and snapshot.metadata.slicer.family is not SlicerFamily.UNKNOWN
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
        snapshot: GCodeAnalysisSnapshot | None,
        source_values: Mapping[str, Any],
        installation: SlicerInstallation,
        machine: ResolvedProfile,
        process: ResolvedProfile,
        filament: ResolvedProfile,
        effective: Mapping[str, Any],
        gcode_evidence: GCodeProfileEvidence,
        known_machines: Sequence[ResolvedProfile],
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
            snapshot is not None
            and
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
        validation_context = ProfileFilterContext(
            source="validation",
            machine_ids=(str(machine.record.path),),
            printer_model=(
                str(machine.effective_values.get("printer_model", "")).strip()
                or None
            ),
            nozzle_diameters_mm=(
                _positive_finite_numbers(source_values.get("nozzle_diameter"))
                or _profile_nozzle_diameters(machine)
            ),
        )
        for item in (process, filament):
            incompatible = not self._profile_matches_machine_context(
                item,
                (machine,),
                validation_context,
                known_machines,
            )
            if incompatible:
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
            return (
                "Mehrere passende Profilkombinationen wurden gleich gut bewertet. "
                "Prüfe die vorausgewählte Kombination aus Maschinen-, Filament- "
                "und Prozessprofil und bestätige sie."
            )
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
