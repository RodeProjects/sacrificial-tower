from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from cooling_tower.models.gcode_metadata import SlicerFamily
from cooling_tower.slicers.models import (
    EffectiveProfile,
    ProfileCandidate,
    ProfileRecord,
    SliceRequest,
    SliceResult,
    SlicerCandidate,
    SlicerInstallation,
    SlicerSupportLevel,
)


@runtime_checkable
class SlicerAdapter(Protocol):
    adapter_id: str
    product_name: str
    family: SlicerFamily
    support_level: SlicerSupportLevel
    executable_names: tuple[str, ...]

    def known_candidates(self) -> tuple[SlicerCandidate, ...]: ...

    def matches_candidate(self, candidate: SlicerCandidate) -> bool: ...

    def verify_installation(
        self,
        candidate: SlicerCandidate | Path,
    ) -> SlicerInstallation: ...

    def discover_profiles(
        self,
        installation: SlicerInstallation,
    ) -> list[ProfileRecord]: ...

    def profile_values(self, record: ProfileRecord) -> dict[str, object]: ...

    def resolve_profile_bundle(
        self,
        candidate: ProfileCandidate,
    ) -> EffectiveProfile: ...

    def slice_model(self, request: SliceRequest) -> SliceResult: ...

    def extract_layer_times(self, result: SliceResult) -> tuple[float, ...]: ...
