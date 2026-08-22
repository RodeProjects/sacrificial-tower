"""Slicer-specific, read-only discovery modules.

Only modules marked as implemented participate in profile and active-preset
detection.  Placeholder modules make the intended extension points explicit
without pretending that an unverified slicer format is already supported.
"""

from cooling_tower.slicers.detection.base import (
    ActivePresetSchema,
    SlicerDetectionModule,
)
from cooling_tower.slicers.detection.registry import (
    detection_module_for,
    detection_modules,
)

__all__ = [
    "ActivePresetSchema",
    "SlicerDetectionModule",
    "detection_module_for",
    "detection_modules",
]
