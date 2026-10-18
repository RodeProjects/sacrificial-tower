"""Shared boundary between installation detection and runtime integration.

Experimental parsers and commands in legacy adapters do not authorize their
use while the detection registry still declares an unimplemented placeholder.
"""
from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from cooling_tower.slicers.errors import SlicerError, SlicerIntegrationUnavailableError
from cooling_tower.slicers.models import SlicerSupportLevel

if TYPE_CHECKING:
    from cooling_tower.slicers.adapter import SlicerAdapter
    from cooling_tower.slicers.models import SlicerInstallation


def integration_is_implemented(adapter_id: str) -> bool:
    # Detection modules reuse base path utilities during import. Resolve the
    # registry only when checking a concrete installation, after module setup.
    from cooling_tower.slicers.detection.registry import detection_module_for

    module = detection_module_for(adapter_id)
    # Legacy/custom adapters outside the registry declare their own support.
    # Registered placeholders, however, are always fail-closed.
    return module is None or module.implemented


def detected_installation(installation: SlicerInstallation) -> SlicerInstallation:
    if integration_is_implemented(installation.adapter_id):
        return installation
    return replace(
        installation,
        support_level=SlicerSupportLevel.DETECTION_ONLY,
        capabilities=frozenset(),
    )


def require_integration(installation: SlicerInstallation) -> None:
    if (
        not integration_is_implemented(installation.adapter_id)
        or installation.support_level is not SlicerSupportLevel.FULL
    ):
        raise SlicerIntegrationUnavailableError(
            f"{installation.product_name} wurde erkannt, wird aber noch nicht "
            "für die automatische Verarbeitung unterstützt. "
            "Bitte einen unterstützten Slicer auswählen."
        )


def require_profile_support(
    installation: SlicerInstallation,
    adapter: SlicerAdapter | None = None,
) -> None:
    require_integration(installation)
    if not installation.verified:
        raise SlicerIntegrationUnavailableError(
            "Für den ausgewählten Slicer ist keine bestätigte "
            "Profilverarbeitung verfügbar. Bitte einen unterstützten "
            "Slicer auswählen oder die Slicer-Erkennung erneut ausführen."
        )
    if adapter is not None and adapter.adapter_id != installation.adapter_id:
        raise SlicerIntegrationUnavailableError(
            "Die Slicer-Integration passt nicht zur ausgewählten Installation. "
            "Bitte die Slicer-Erkennung erneut ausführen."
        )


def slicer_failure_message(error: Exception) -> str:
    """Use confirmed domain causes; do not guess from arbitrary error text."""
    if isinstance(error, SlicerError) and str(error).strip():
        return str(error)
    if isinstance(error, PermissionError):
        return "Auf benötigte Slicer-Dateien konnte nicht zugegriffen werden."
    if isinstance(error, FileNotFoundError):
        return "Eine benötigte Slicer-Datei wurde nicht gefunden."
    if isinstance(error, TimeoutError):
        return "Die Slicer-Verarbeitung hat das Zeitlimit überschritten."
    return (
        "Die Slicer-Verarbeitung konnte wegen eines unerwarteten Fehlers "
        "nicht abgeschlossen werden. Bitte erneut versuchen oder einen "
        "anderen unterstützten Slicer auswählen."
    )
