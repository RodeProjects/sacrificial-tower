from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from cooling_tower.models.gcode_metadata import SlicerFamily, SlicerIdentity
from cooling_tower.models.source import SourceArtifact, SourceKind
from cooling_tower.slicers.models import (
    EffectiveProfile,
    ProfileRecord,
    ProfileSelectionReference,
    SlicerInstallation,
)
from cooling_tower.slicers.profile_safety import profile_paths_fingerprint


PROFILE_INVENTORY_SCHEMA_VERSION = 1
PROFILE_MAPPING_SCHEMA_VERSION = 1
PROFILE_REPORT_SCHEMA_VERSION = 1

_REPORT_CRITICAL_KEYS = {
    "outer_wall_speed",
    "inner_wall_speed",
    "small_perimeter_speed",
    "overhang_speed",
    "default_acceleration",
    "outer_wall_acceleration",
    "travel_speed",
    "retraction_speed",
    "deretraction_speed",
    "retraction_length",
    "line_width",
    "outer_wall_line_width",
    "inner_wall_line_width",
    "layer_height",
    "wall_loops",
    "max_volumetric_speed",
    "filament_max_volumetric_speed",
    "min_print_speed",
    "slow_down_layer_time",
    "fan_min_speed",
    "fan_max_speed",
}


class ProfileRole(str, Enum):
    MACHINE_MODEL = "machine_model"
    MACHINE_VARIANT = "machine_variant"
    PROCESS = "process"
    FILAMENT = "filament"
    USER_OVERRIDE = "user_override"
    TEMPORARY_EFFECTIVE_PROFILE = "temporary_effective_profile"


class ProfileOrigin(str, Enum):
    SYSTEM = "system"
    USER = "user"
    PROJECT = "project"
    SESSION = "session"
    GCODE_RECONSTRUCTION = "gcode_reconstruction"
    TEMPORARY = "temporary"
    UNKNOWN = "unknown"


class ProfileMatchState(str, Enum):
    RECONSTRUCTED = "reconstructed"
    MATCHED = "matched"
    COMPATIBLE = "compatible"
    AMBIGUOUS = "ambiguous"
    UNAVAILABLE = "unavailable"


class ProfileValidationState(str, Enum):
    INVALID = "invalid"
    STRUCTURALLY_VALID = "structurally_valid"
    PROBE_VALIDATED = "probe_validated"


class ProfileExclusionCode(str, Enum):
    WRONG_TECHNOLOGY = "wrong_technology"
    NOZZLE_MISMATCH = "nozzle_mismatch"
    EXTRUDER_COUNT_MISMATCH = "extruder_count_mismatch"
    GCODE_DIALECT_MISMATCH = "gcode_dialect_mismatch"
    BUILD_VOLUME_TOO_SMALL = "build_volume_too_small"
    UNSUPPORTED_TOOL_CHANGE = "unsupported_tool_change"
    UNRESOLVED_INHERITANCE = "unresolved_inheritance"
    INCOMPATIBLE_PROFILE_VERSION = "incompatible_profile_version"
    INCOMPATIBLE_PROFILE_COMBINATION = "incompatible_profile_combination"


@dataclass(frozen=True, slots=True)
class ProfileFileState:
    path: Path
    size_bytes: int
    modified_ns: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path).resolve())

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "size_bytes": self.size_bytes,
            "modified_ns": self.modified_ns,
        }


@dataclass(frozen=True, slots=True)
class ProfileInventory:
    installation: SlicerInstallation
    records: tuple[ProfileRecord, ...]
    file_states: tuple[ProfileFileState, ...]
    fingerprint_sha256: str
    created_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    schema_version: int = PROFILE_INVENTORY_SCHEMA_VERSION

    def records_for_ids(self, profile_ids: tuple[str, ...]) -> tuple[ProfileRecord, ...]:
        wanted = {value.casefold() for value in profile_ids}
        return tuple(
            record
            for record in self.records
            if record.profile_id.casefold() in wanted
            or record.name.casefold() in wanted
        )


@dataclass(frozen=True, slots=True)
class ProfileCatalog:
    """Source-independent, read-only profile choices for one installation."""

    execution_slicer: SlicerInstallation
    inventory_fingerprint: str
    machine_options: tuple[ProfileRecord, ...]
    process_options: tuple[ProfileRecord, ...]
    filament_options: tuple[ProfileRecord, ...]
    rejected_profile_count: int = 0
    profiles_filtered: bool = False
    profile_filter_summary: str = ""
    selected_machine: ProfileSelectionReference | None = None
    selected_process: ProfileSelectionReference | None = None
    selected_filament: ProfileSelectionReference | None = None

    @property
    def complete(self) -> bool:
        return bool(
            self.machine_options
            and self.process_options
            and self.filament_options
        )


@dataclass(frozen=True, slots=True)
class ProfileCatalogConfirmation:
    """Session confirmation of exact profile files before a source is loaded."""

    slicer_identity_key: str
    inventory_fingerprint: str
    machine_profile_id: str
    machine_path: Path
    process_profile_id: str
    process_path: Path
    filament_profile_id: str
    filament_path: Path

    def __post_init__(self) -> None:
        for field_name in (
            "machine_profile_id",
            "process_profile_id",
            "filament_profile_id",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError("Die Profilbestätigung benötigt stabile IDs.")
            object.__setattr__(self, field_name, value)
        for field_name in (
            "machine_path",
            "process_path",
            "filament_path",
        ):
            object.__setattr__(
                self,
                field_name,
                Path(getattr(self, field_name)).resolve(),
            )

    @classmethod
    def from_catalog(
        cls,
        catalog: "ProfileCatalog",
        *,
        machine_path: str | Path,
        process_path: str | Path,
        filament_path: str | Path,
        machine_profile_id: str | None = None,
        process_profile_id: str | None = None,
        filament_profile_id: str | None = None,
    ) -> "ProfileCatalogConfirmation":
        selections = {
            "machine": Path(machine_path).resolve(),
            "process": Path(process_path).resolve(),
            "filament": Path(filament_path).resolve(),
        }
        requested_ids = {
            "machine": machine_profile_id,
            "process": process_profile_id,
            "filament": filament_profile_id,
        }
        options = {
            "machine": catalog.machine_options,
            "process": catalog.process_options,
            "filament": catalog.filament_options,
        }
        selected_records: dict[str, ProfileRecord] = {}
        for role, path in selections.items():
            candidates = tuple(
                item
                for item in options[role]
                if item.path.resolve() == path
                and (
                    requested_ids[role] is None
                    or item.profile_id.casefold()
                    == str(requested_ids[role]).strip().casefold()
                )
            )
            if len(candidates) != 1:
                raise ValueError(
                    "Die Profilauswahl ist im aktuellen Profilkatalog "
                    f"nicht mehr eindeutig: {role}."
                )
            if not candidates[0].path.is_file():
                raise ValueError(
                    f"Die ausgewählte Profildatei fehlt: {role}."
                )
            selected_records[role] = candidates[0]
        return cls(
            slicer_identity_key=catalog.execution_slicer.identity_key,
            inventory_fingerprint=catalog.inventory_fingerprint,
            machine_profile_id=selected_records["machine"].profile_id,
            machine_path=selections["machine"],
            process_profile_id=selected_records["process"].profile_id,
            process_path=selections["process"],
            filament_profile_id=selected_records["filament"].profile_id,
            filament_path=selections["filament"],
        )

    def matches_catalog(self, catalog: "ProfileCatalog") -> bool:
        return (
            self.slicer_identity_key == catalog.execution_slicer.identity_key
            and self.inventory_fingerprint == catalog.inventory_fingerprint
        )

    def selected_profile_ids(
        self,
    ) -> dict[str, ProfileSelectionReference]:
        return {
            "machine": ProfileSelectionReference(
                self.machine_profile_id,
                self.machine_path,
            ),
            "process": ProfileSelectionReference(
                self.process_profile_id,
                self.process_path,
            ),
            "filament": ProfileSelectionReference(
                self.filament_profile_id,
                self.filament_path,
            ),
        }


@dataclass(frozen=True, slots=True)
class ResolvedProfile:
    record: ProfileRecord
    role: ProfileRole
    chain: tuple[ProfileRecord, ...]
    effective_values: Mapping[str, Any]
    fingerprint_sha256: str | None
    valid: bool
    errors: tuple[str, ...] = ()

    @property
    def origin(self) -> ProfileOrigin:
        value = self.record.source.casefold()
        try:
            return ProfileOrigin(value)
        except ValueError:
            return ProfileOrigin.UNKNOWN


@dataclass(frozen=True, slots=True)
class ProfileHardExclusion:
    code: ProfileExclusionCode
    message: str
    profile_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "profile_id": self.profile_id,
        }


@dataclass(frozen=True, slots=True)
class ProfileValueDifference:
    key: str
    source_value: Any
    candidate_value: Any
    critical: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "source_value": self.source_value,
            "candidate_value": self.candidate_value,
            "critical": self.critical,
        }


@dataclass(frozen=True, slots=True)
class ProfileBundleMatch:
    bundle_id: str
    effective_profile: EffectiveProfile
    resolved_profiles: tuple[ResolvedProfile, ...]
    evidence: tuple[str, ...]
    differences: tuple[ProfileValueDifference, ...]
    unknown_keys: tuple[str, ...]
    exclusions: tuple[ProfileHardExclusion, ...]
    rank: int
    exact_identifier_count: int
    critical_match_count: int
    critical_mismatch_count: int
    validation_state: ProfileValidationState
    cross_slicer: bool = False
    reconstructed: bool = False
    temporary_overrides: Mapping[str, Any] = field(default_factory=dict)
    validation_message: str | None = None

    @property
    def usable(self) -> bool:
        return not self.exclusions and self.validation_state is not ProfileValidationState.INVALID

    @property
    def machine(self) -> ProfileRecord | None:
        return self.effective_profile.machine

    @property
    def process(self) -> ProfileRecord | None:
        return self.effective_profile.process

    @property
    def filament(self) -> ProfileRecord | None:
        return (
            self.effective_profile.filaments[0]
            if self.effective_profile.filaments
            else None
        )

    @property
    def source_paths(self) -> tuple[Path, ...]:
        """All selected and inherited profile files used by this bundle."""

        paths = list(self.effective_profile.source_paths)
        paths.extend(
            record.path
            for resolved in self.resolved_profiles
            for record in resolved.chain
        )
        # ProfileRecord normalizes every path when it is constructed. Avoid
        # repeating Windows realpath calls in cancellable worker operations.
        return tuple(dict.fromkeys(paths))

    def to_report_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "machine_profile_id": self.machine.profile_id if self.machine else None,
            "process_profile_id": self.process.profile_id if self.process else None,
            "filament_profile_ids": [
                item.profile_id for item in self.effective_profile.filaments
            ],
            "source_paths": [str(path) for path in self.effective_profile.source_paths],
            "profile_origins": {
                "machine": self.machine.source if self.machine else None,
                "process": self.process.source if self.process else None,
                "filaments": [item.source for item in self.effective_profile.filaments],
            },
            "resolution_chains": [
                [
                    {
                        "profile_id": record.profile_id,
                        "source": record.source,
                        "path": str(record.path),
                    }
                    for record in resolved.chain
                ]
                for resolved in self.resolved_profiles
            ],
            "evidence": list(self.evidence),
            "differences": [item.to_dict() for item in self.differences],
            "unknown_keys": list(self.unknown_keys),
            "exclusions": [item.to_dict() for item in self.exclusions],
            "validation_state": self.validation_state.value,
            "validation_message": self.validation_message,
            "cross_slicer": self.cross_slicer,
            "reconstructed": self.reconstructed,
            "critical_values": {
                key: _json_safe(value)
                for key, value in sorted(self.temporary_overrides.items())
                if key in _REPORT_CRITICAL_KEYS
            },
            "temporary_override_count": (
                len(self.temporary_overrides) if self.reconstructed else 0
            ),
        }


@dataclass(frozen=True, slots=True)
class ProfileMatchResult:
    state: ProfileMatchState
    selected: ProfileBundleMatch | None
    candidates: tuple[ProfileBundleMatch, ...]
    machine_options: tuple[ProfileRecord, ...]
    process_options: tuple[ProfileRecord, ...]
    filament_options: tuple[ProfileRecord, ...]
    requires_confirmation: bool
    user_confirmed: bool
    can_use_stl_mode: bool
    can_use_gcode_mode: bool
    message: str
    source_slicer: SlicerIdentity
    execution_slicer: SlicerInstallation
    inventory_fingerprint: str
    source_profile_fingerprint: str | None
    source_critical_fingerprint: str | None
    gcode_restrictions: tuple[str, ...] = ()
    profiles_filtered: bool = False
    profile_filter_source: str | None = None
    profile_filter_summary: str = ""
    unfiltered_option_counts: tuple[int, int, int] = (0, 0, 0)
    visible_option_counts: tuple[int, int, int] = (0, 0, 0)
    active_preset_fingerprint: str | None = None
    source_kind: SourceKind | None = None
    effective_profile_fingerprint: str | None = None

    def to_report_dict(self) -> dict[str, Any]:
        return {
            "profile_report_schema_version": PROFILE_REPORT_SCHEMA_VERSION,
            "state": self.state.value,
            "message": self.message,
            "source_kind": (
                self.source_kind.value if self.source_kind is not None else "internal_gcode"
            ),
            "execution_slicer": {
                "adapter_id": self.execution_slicer.adapter_id,
                "product_name": self.execution_slicer.product_name,
                "version": self.execution_slicer.version,
                "path": str(self.execution_slicer.executable_path),
            },
            "source_slicer": self.source_slicer.to_dict(),
            "selected": (
                self.selected.to_report_dict() if self.selected else None
            ),
            "candidate_count": len(self.candidates),
            "requires_confirmation": self.requires_confirmation,
            "user_confirmed": self.user_confirmed,
            "can_use_stl_mode": self.can_use_stl_mode,
            "can_use_gcode_mode": self.can_use_gcode_mode,
            "gcode_restrictions": list(self.gcode_restrictions),
            "profile_filter": {
                "filtered": self.profiles_filtered,
                "source": self.profile_filter_source,
                "summary": self.profile_filter_summary,
                "unfiltered_option_counts": list(
                    self.unfiltered_option_counts
                ),
                "visible_option_counts": list(self.visible_option_counts),
                "active_preset_fingerprint": self.active_preset_fingerprint,
            },
            "inventory_fingerprint": self.inventory_fingerprint,
            "source_profile_fingerprint": self.source_profile_fingerprint,
            "source_critical_fingerprint": self.source_critical_fingerprint,
            "effective_profile_fingerprint": self.effective_profile_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class ProfileConfirmation:
    """One explicit profile confirmation bound to an immutable source."""

    source_kind: SourceKind
    source_path: Path
    source_sha256: str
    source_size_bytes: int
    source_modified_ns: int
    slicer_identity_key: str
    slicer_path: Path
    slicer_version: str | None
    machine_profile_id: str
    process_profile_id: str
    filament_profile_ids: tuple[str, ...]
    effective_profile_fingerprint: str
    profile_sources_fingerprint: str
    confirmed_utc: str

    @classmethod
    def from_result(
        cls,
        result: ProfileMatchResult,
        source: SourceArtifact,
    ) -> "ProfileConfirmation":
        selected = result.selected
        if selected is None or selected.machine is None or selected.process is None:
            raise ValueError("Die Profilbestätigung ist unvollständig.")
        if not selected.effective_profile.filaments:
            raise ValueError("Für die Profilbestätigung fehlt das Filament.")
        fingerprint = result.effective_profile_fingerprint or stable_json_fingerprint(
            selected.effective_profile.effective_values
        )
        return cls(
            source_kind=source.source_kind,
            source_path=source.original_path,
            source_sha256=source.original_sha256,
            source_size_bytes=source.original_size,
            source_modified_ns=source.original_mtime_ns,
            slicer_identity_key=result.execution_slicer.identity_key,
            slicer_path=result.execution_slicer.executable_path,
            slicer_version=result.execution_slicer.version,
            machine_profile_id=selected.machine.profile_id,
            process_profile_id=selected.process.profile_id,
            filament_profile_ids=tuple(
                item.profile_id for item in selected.effective_profile.filaments
            ),
            effective_profile_fingerprint=fingerprint,
            profile_sources_fingerprint=profile_paths_fingerprint(
                selected.source_paths
            ),
            confirmed_utc=datetime.now(timezone.utc).isoformat(),
        )

    def matches_source(self, source: SourceArtifact) -> bool:
        return (
            self.source_kind is source.source_kind
            and self.source_path == source.original_path
            and self.source_sha256 == source.original_sha256
            and self.source_size_bytes == source.original_size
            and self.source_modified_ns == source.original_mtime_ns
        )


@dataclass(frozen=True, slots=True)
class ConfirmedProfileMapping:
    mapping_key: str
    slicer_family: SlicerFamily
    version_compatibility: str
    source_profile_fingerprint: str | None
    source_critical_fingerprint: str
    machine_profile_id: str | None
    process_profile_id: str | None
    filament_profile_ids: tuple[str, ...]
    confirmed_utc: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "mapping_key": self.mapping_key,
            "slicer_family": self.slicer_family.value,
            "version_compatibility": self.version_compatibility,
            "source_profile_fingerprint": self.source_profile_fingerprint,
            "source_critical_fingerprint": self.source_critical_fingerprint,
            "machine_profile_id": self.machine_profile_id,
            "process_profile_id": self.process_profile_id,
            "filament_profile_ids": list(self.filament_profile_ids),
            "confirmed_utc": self.confirmed_utc,
        }


def stable_json_fingerprint(values: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        {key: _json_safe(value) for key, value in sorted(values.items())},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def profile_bundle_id(profile: EffectiveProfile) -> str:
    values = {
        "adapter": profile.installation.adapter_id,
        "machine": profile.machine.profile_id if profile.machine else None,
        "process": profile.process.profile_id if profile.process else None,
        "filaments": [item.profile_id for item in profile.filaments],
        "definitions": [item.profile_id for item in profile.definitions],
    }
    return stable_json_fingerprint(values)[:24]


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
