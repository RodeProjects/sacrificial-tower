"""Cooling-tower generator package."""

from cooling_tower.windows_process import configure_windows_process_policy


WINDOWS_PROCESS_POLICY = configure_windows_process_policy()

from cooling_tower.models import (
    GenerationResult,
    GenerationSettings,
    LayerData,
    TowerLayerProfile,
)
from cooling_tower.version import APP_VERSION

__version__ = APP_VERSION

__all__ = [
    "APP_VERSION",
    "GenerationResult",
    "GenerationSettings",
    "LayerData",
    "TowerLayerProfile",
    "WINDOWS_PROCESS_POLICY",
    "__version__",
]
