from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from threading import Event
from typing import Any, Mapping

from cooling_tower.models.gcode_metadata import SlicerFamily, SlicerIdentity


SLICER_PREFERENCES_SCHEMA_VERSION = 2


class SlicerCapability(str, Enum):
    PROFILE_INVENTORY = "profile_inventory"
    CLI_SLICE = "cli_slice"
    CUSTOM_PROFILES = "custom_profiles"
    OUTPUT_DIRECTORY = "output_directory"
    AUTO_ARRANGE = "auto_arrange"
    GCODE_METADATA = "gcode_metadata"
    PROCESS_CANCELLATION = "process_cancellation"


class SlicerSupportLevel(str, Enum):
    DETECTION_ONLY = "detection_only"
    FULL = "full"


class SlicerDiscoverySource(str, Enum):
    REGISTRY_SYSTEM = "registry_system"
    REGISTRY_USER = "registry_user"
    APP_PATHS = "app_paths"
    KNOWN_PATH = "known_path"
    START_MENU = "start_menu"
    SAVED_PATH = "saved_path"
    MANUAL = "manual"


class SlicerGuiState(str, Enum):
    AVAILABLE_AND_RECOMMENDED = "available_and_recommended"
    AVAILABLE = "available"
    NEEDS_MANUAL_PATH = "needs_manual_path"
    UNSUPPORTED = "unsupported"
    NOT_FOUND = "not_found"


class ProfileKind(str, Enum):
    MACHINE = "machine"
    PROCESS = "process"
    FILAMENT = "filament"
    QUALITY = "quality"
    DEFINITION = "definition"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SlicerInstallation:
    adapter_id: str
    product_name: str
    version: str | None
    executable_path: Path
    verified: bool
    capabilities: frozenset[SlicerCapability]
    discovery_source: SlicerDiscoverySource
    family: SlicerFamily = SlicerFamily.UNKNOWN
    support_level: SlicerSupportLevel = SlicerSupportLevel.DETECTION_ONLY
    profile_roots: tuple[Path, ...] = ()
    engine_path: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "executable_path",
            Path(self.executable_path).expanduser().resolve(),
        )
        object.__setattr__(
            self,
            "profile_roots",
            tuple(Path(path).expanduser().resolve() for path in self.profile_roots),
        )
        if self.engine_path is not None:
            object.__setattr__(
                self,
                "engine_path",
                Path(self.engine_path).expanduser().resolve(),
            )

    @property
    def identity_key(self) -> str:
        return f"{self.adapter_id}|{str(self.executable_path).casefold()}"

    @property
    def can_slice(self) -> bool:
        return (
            self.verified
            and self.support_level is SlicerSupportLevel.FULL
            and SlicerCapability.CLI_SLICE in self.capabilities
        )

    @property
    def automatically_discovered(self) -> bool:
        """Whether this installation was found without a user-owned choice."""

        return self.discovery_source in {
            SlicerDiscoverySource.REGISTRY_SYSTEM,
            SlicerDiscoverySource.REGISTRY_USER,
            SlicerDiscoverySource.APP_PATHS,
            SlicerDiscoverySource.KNOWN_PATH,
            SlicerDiscoverySource.START_MENU,
        }

    @property
    def display_name(self) -> str:
        version = f" {self.version}" if self.version else ""
        suffix = (
            ""
            if self.support_level is SlicerSupportLevel.FULL
            else " (nur erkannt)"
        )
        return f"{self.product_name}{version}{suffix}"


@dataclass(frozen=True, slots=True)
class SlicerCandidate:
    executable_path: Path
    discovery_source: SlicerDiscoverySource
    adapter_hint: str | None = None
    product_hint: str | None = None
    version_hint: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "executable_path",
            Path(self.executable_path).expanduser(),
        )


@dataclass(frozen=True, slots=True)
class ProfileRecord:
    adapter_id: str
    profile_id: str
    name: str
    kind: ProfileKind
    path: Path
    source: str
    inherits: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path).resolve())


@dataclass(frozen=True, slots=True)
class ProfileCandidate:
    installation: SlicerInstallation
    machine: ProfileRecord | None = None
    process: ProfileRecord | None = None
    filaments: tuple[ProfileRecord, ...] = ()
    definitions: tuple[ProfileRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class EffectiveProfile:
    installation: SlicerInstallation
    machine: ProfileRecord | None
    process: ProfileRecord | None
    filaments: tuple[ProfileRecord, ...]
    definitions: tuple[ProfileRecord, ...] = ()
    effective_values: Mapping[str, Any] = field(default_factory=dict)
    resolution_notes: tuple[str, ...] = ()

    @property
    def source_paths(self) -> tuple[Path, ...]:
        records = (
            *((self.machine,) if self.machine is not None else ()),
            *((self.process,) if self.process is not None else ()),
            *self.filaments,
            *self.definitions,
        )
        return tuple(record.path for record in records)


@dataclass(frozen=True, slots=True)
class SliceRequest:
    model_path: Path
    profile: EffectiveProfile
    output_directory: Path
    timeout_s: float = 300.0
    diagnostics_root: Path | None = None
    retain_failure_diagnostics: bool = True
    temporary_overrides: Mapping[str, Any] = field(default_factory=dict)
    expected_layer_heights_mm: tuple[float, ...] = ()
    placement_xy_mm: tuple[float, float] | None = None
    preserve_model_positions: bool = False
    use_cli_assemble_list: bool = False
    purpose: str = "normal"
    calibration_round: int | None = None
    cancellation_event: Event | None = field(
        default=None,
        compare=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "model_path", Path(self.model_path).resolve())
        object.__setattr__(
            self,
            "output_directory",
            Path(self.output_directory).resolve(),
        )
        if self.diagnostics_root is not None:
            object.__setattr__(
                self,
                "diagnostics_root",
                Path(self.diagnostics_root).resolve(),
            )
        if self.timeout_s <= 0:
            raise ValueError("Slicer timeout must be greater than zero.")


@dataclass(frozen=True, slots=True)
class SliceResult:
    success: bool
    return_code: int | None
    command: tuple[str, ...]
    output_files: tuple[Path, ...]
    gcode_path: Path | None
    metadata_paths: tuple[Path, ...]
    stdout: str
    stderr: str
    duration_s: float
    diagnostic_path: Path | None = None
    failure_reason: str | None = None
    timed_out: bool = False
    cancelled: bool = False
    crashed: bool = False
    process_backend: str = "legacy"
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    process_output_diagnostic_path: Path | None = None


@dataclass(frozen=True, slots=True)
class SlicerDiscoveryResult:
    installations: tuple[SlicerInstallation, ...]
    recommended_key: str | None
    gui_state: SlicerGuiState
    message: str
    source_slicer: SlicerIdentity | None = None
    diagnostics: tuple[str, ...] = ()
    last_used_key: str | None = None

    @property
    def recommended(self) -> SlicerInstallation | None:
        if self.recommended_key is None:
            return None
        return next(
            (
                installation
                for installation in self.installations
                if installation.identity_key == self.recommended_key
            ),
            None,
        )

    @property
    def last_used(self) -> SlicerInstallation | None:
        if self.last_used_key is None:
            return None
        return next(
            (
                installation
                for installation in self.installations
                if installation.identity_key == self.last_used_key
            ),
            None,
        )


@dataclass(frozen=True, slots=True)
class SlicerPreferences:
    schema_version: int = SLICER_PREFERENCES_SCHEMA_VERSION
    confirmed_paths: tuple[Path, ...] = ()
    last_selected_key: str | None = None
    profile_selections: Mapping[str, SlicerProfileSelections] = field(
        default_factory=dict
    )


@dataclass(frozen=True, slots=True)
class ProfileSelectionReference:
    """Stable and path-specific identity of one user-selected preset."""

    profile_id: str
    path: Path | None = None

    def __post_init__(self) -> None:
        profile_id = str(self.profile_id).strip()
        if not profile_id:
            raise ValueError("A remembered profile requires a stable ID.")
        object.__setattr__(self, "profile_id", profile_id)
        if self.path is not None:
            object.__setattr__(
                self,
                "path",
                Path(self.path).expanduser().resolve(),
            )


@dataclass(frozen=True, slots=True)
class SlicerProfileSelections:
    """Last explicit machine, process and filament choices for one slicer."""

    machine: ProfileSelectionReference | None = None
    process: ProfileSelectionReference | None = None
    filament: ProfileSelectionReference | None = None

    def as_mapping(self) -> dict[str, ProfileSelectionReference]:
        return {
            role: reference
            for role, reference in (
                ("machine", self.machine),
                ("process", self.process),
                ("filament", self.filament),
            )
            if reference is not None
        }
