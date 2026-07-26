from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Sequence

from cooling_tower.models.gcode_metadata import SlicerIdentity
from cooling_tower.slicers.adapter import SlicerAdapter
from cooling_tower.slicers.adapters import default_adapters
from cooling_tower.slicers.discovery import (
    CandidateDiscovery,
    WindowsSlicerDiscovery,
    deduplicate_candidates,
)
from cooling_tower.slicers.errors import SlicerError, UnsupportedSlicerExecutableError
from cooling_tower.slicers.models import (
    SlicerCandidate,
    SlicerDiscoveryResult,
    SlicerDiscoverySource,
    SlicerGuiState,
    SlicerInstallation,
    SlicerSupportLevel,
)
from cooling_tower.slicers.preferences import SlicerPreferenceStore


_VERSION_COMPONENT = re.compile(r"\d+")


def _version_tuple(value: str | None) -> tuple[int, ...]:
    if not value:
        return ()
    return tuple(int(item) for item in _VERSION_COMPONENT.findall(value))


def _normalised_product(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").casefold())


class SlicerDiscoveryService:
    def __init__(
        self,
        *,
        adapters: Sequence[SlicerAdapter] | None = None,
        discovery: CandidateDiscovery | None = None,
        preference_store: SlicerPreferenceStore | None = None,
    ) -> None:
        self.adapters = tuple(adapters or default_adapters())
        self.discovery = discovery or WindowsSlicerDiscovery()
        self.preference_store = preference_store
        self._installations: tuple[SlicerInstallation, ...] | None = None
        self._diagnostics: tuple[str, ...] = ()

    def discover_installations(
        self,
        source_slicer: SlicerIdentity | None = None,
        *,
        force: bool = False,
    ) -> SlicerDiscoveryResult:
        if force or self._installations is None:
            self._installations, self._diagnostics = self._perform_discovery()
        return self._build_result(
            self._installations,
            source_slicer,
            self._diagnostics,
        )

    def _perform_discovery(
        self,
    ) -> tuple[tuple[SlicerInstallation, ...], tuple[str, ...]]:
        candidates = list(self.discovery.discover(self.adapters))
        preferences = self.preference_store.load() if self.preference_store else None
        if preferences is not None:
            candidates.extend(
                SlicerCandidate(
                    path,
                    SlicerDiscoverySource.SAVED_PATH,
                )
                for path in preferences.confirmed_paths
            )

        installations: list[SlicerInstallation] = []
        diagnostics: list[str] = []
        stale_saved_paths: set[Path] = set()
        for candidate in deduplicate_candidates(candidates):
            if not candidate.executable_path.expanduser().is_file():
                if candidate.discovery_source is SlicerDiscoverySource.SAVED_PATH:
                    stale_saved_paths.add(candidate.executable_path)
                    diagnostics.append(
                        f"Gespeicherter Slicerpfad existiert nicht mehr: "
                        f"{candidate.executable_path}"
                    )
                continue
            adapters = self._adapters_for_candidate(candidate)
            if not adapters:
                diagnostics.append(
                    f"Kein Adapter passt zu {candidate.executable_path.name}."
                )
                continue
            errors: list[str] = []
            for adapter in adapters:
                try:
                    installation = adapter.verify_installation(candidate)
                except (OSError, SlicerError, ValueError) as error:
                    errors.append(f"{adapter.adapter_id}: {error}")
                    continue
                installations.append(installation)
                break
            else:
                diagnostics.append(
                    f"{candidate.executable_path}: " + " | ".join(errors)
                )
        if stale_saved_paths and self.preference_store is not None:
            self.preference_store.remove_paths(stale_saved_paths)
        return self._deduplicate_installations(installations), tuple(diagnostics)

    def add_manual_installation(
        self,
        executable_path: str | Path,
        source_slicer: SlicerIdentity | None = None,
    ) -> SlicerDiscoveryResult:
        path = Path(executable_path).expanduser().resolve()
        candidate = SlicerCandidate(path, SlicerDiscoverySource.MANUAL)
        adapters = self._adapters_for_candidate(candidate, try_all=True)
        errors: list[str] = []
        for adapter in adapters:
            try:
                installation = adapter.verify_installation(candidate)
            except (OSError, SlicerError, ValueError) as error:
                errors.append(str(error))
                continue
            current = list(self._installations or ())
            current.append(installation)
            self._installations = self._deduplicate_installations(current)
            if self.preference_store is not None:
                self.preference_store.confirm_path(path)
            return self._build_result(
                self._installations,
                source_slicer,
                self._diagnostics,
            )
        message = (
            "Die ausgewählte Datei ist kein unterstützter Slicer."
            if not errors
            else "Die ausgewählte Datei konnte nicht bestätigt werden: "
            + " | ".join(errors)
        )
        raise UnsupportedSlicerExecutableError(message)

    def remember_selection(self, identity_key: str | None) -> None:
        if self.preference_store is not None:
            self.preference_store.set_last_selected(identity_key)

    def adapter_for(self, installation: SlicerInstallation) -> SlicerAdapter:
        for adapter in self.adapters:
            if adapter.adapter_id == installation.adapter_id:
                return adapter
        raise KeyError(f"Unknown slicer adapter: {installation.adapter_id}")

    def _adapters_for_candidate(
        self,
        candidate: SlicerCandidate,
        *,
        try_all: bool = False,
    ) -> tuple[SlicerAdapter, ...]:
        preferred = tuple(
            adapter
            for adapter in self.adapters
            if adapter.matches_candidate(candidate)
        )
        if preferred or not try_all:
            return preferred
        return self.adapters

    @staticmethod
    def _deduplicate_installations(
        installations: Iterable[SlicerInstallation],
    ) -> tuple[SlicerInstallation, ...]:
        unique: dict[str, SlicerInstallation] = {}
        for installation in installations:
            current = unique.get(installation.identity_key)
            if current is None or (
                current.discovery_source is SlicerDiscoverySource.KNOWN_PATH
                and installation.discovery_source
                in {
                    SlicerDiscoverySource.REGISTRY_SYSTEM,
                    SlicerDiscoverySource.REGISTRY_USER,
                    SlicerDiscoverySource.MANUAL,
                }
            ):
                unique[installation.identity_key] = installation
        return tuple(
            sorted(
                unique.values(),
                key=lambda item: (
                    item.product_name.casefold(),
                    tuple(-value for value in _version_tuple(item.version)),
                    str(item.executable_path).casefold(),
                ),
            )
        )

    def _build_result(
        self,
        installations: tuple[SlicerInstallation, ...],
        source_slicer: SlicerIdentity | None,
        diagnostics: tuple[str, ...],
    ) -> SlicerDiscoveryResult:
        preferences = self.preference_store.load() if self.preference_store else None
        last_selected = preferences.last_selected_key if preferences else None
        recommended = self._recommend(
            installations,
            source_slicer,
            last_selected,
        )
        state, message = self._gui_state(
            installations,
            recommended,
            source_slicer,
        )
        return SlicerDiscoveryResult(
            installations=installations,
            recommended_key=(
                recommended.identity_key if recommended is not None else None
            ),
            gui_state=state,
            message=message,
            source_slicer=source_slicer,
            diagnostics=diagnostics,
        )

    @staticmethod
    def _recommend(
        installations: tuple[SlicerInstallation, ...],
        source: SlicerIdentity | None,
        last_selected_key: str | None,
    ) -> SlicerInstallation | None:
        if not installations:
            return None

        source_product = _normalised_product(
            source.product_name if source is not None else None
        )
        source_version = _version_tuple(source.version if source else None)

        def score(item: SlicerInstallation) -> tuple[int, tuple[int, ...]]:
            value = 0
            if source is not None:
                if source.adapter_id and item.adapter_id == source.adapter_id:
                    value += 1000
                elif (
                    source_product
                    and _normalised_product(item.product_name) == source_product
                ):
                    value += 950
                elif source.family is item.family:
                    value += 700
                item_version = _version_tuple(item.version)
                if source_version and item_version:
                    if item_version == source_version:
                        value += 150
                    elif item_version > source_version:
                        value += 100
                    else:
                        value += 40
            if item.support_level is SlicerSupportLevel.FULL:
                value += 50
            if item.identity_key == last_selected_key:
                value += 30
            return value, _version_tuple(item.version)

        return max(installations, key=score)

    @staticmethod
    def _gui_state(
        installations: tuple[SlicerInstallation, ...],
        recommended: SlicerInstallation | None,
        source: SlicerIdentity | None,
    ) -> tuple[SlicerGuiState, str]:
        if not installations:
            if source is not None and source.product_name:
                return (
                    SlicerGuiState.NEEDS_MANUAL_PATH,
                    "Passender Slicer nicht automatisch gefunden – ausführbare "
                    "Datei kann einmalig ausgewählt werden.",
                )
            return (
                SlicerGuiState.NOT_FOUND,
                "Kein unterstützter Slicer automatisch gefunden.",
            )
        if not any(item.can_slice for item in installations):
            return (
                SlicerGuiState.UNSUPPORTED,
                "Installierter Slicer erkannt; für die automatische Verarbeitung "
                "ist derzeit nur STL-Export verfügbar.",
            )
        source_match = False
        if recommended is not None and source is not None:
            source_match = bool(
                (source.adapter_id and source.adapter_id == recommended.adapter_id)
                or (
                    source.product_name
                    and _normalised_product(source.product_name)
                    == _normalised_product(recommended.product_name)
                )
                or source.family is recommended.family
            )
        if source_match:
            return (
                SlicerGuiState.AVAILABLE_AND_RECOMMENDED,
                "Automatische Slicer-Verarbeitung verfügbar; passendster "
                "erkannter Slicer ist vorausgewählt.",
            )
        if len(installations) > 1:
            return (
                SlicerGuiState.AVAILABLE,
                "Mehrere Slicer verfügbar – Auswahl kann geändert werden.",
            )
        return (
            SlicerGuiState.AVAILABLE,
            "Automatische Slicer-Verarbeitung verfügbar.",
        )
