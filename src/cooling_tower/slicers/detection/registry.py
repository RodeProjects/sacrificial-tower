from __future__ import annotations

from cooling_tower.slicers.detection.anycubic_slicer_next import (
    MODULE as ANYCUBIC_SLICER_NEXT,
)
from cooling_tower.slicers.detection.bambu_studio import MODULE as BAMBU_STUDIO
from cooling_tower.slicers.detection.base import SlicerDetectionModule
from cooling_tower.slicers.detection.creality_print import MODULE as CREALITY_PRINT
from cooling_tower.slicers.detection.cura import MODULE as CURA
from cooling_tower.slicers.detection.orca_slicer import MODULE as ORCA_SLICER
from cooling_tower.slicers.detection.prusa_slicer import MODULE as PRUSA_SLICER


_MODULES = (
    ANYCUBIC_SLICER_NEXT,
    BAMBU_STUDIO,
    CURA,
    PRUSA_SLICER,
    ORCA_SLICER,
    CREALITY_PRINT,
)
_BY_ADAPTER_ID = {module.adapter_id: module for module in _MODULES}


def detection_modules() -> tuple[SlicerDetectionModule, ...]:
    return _MODULES


def detection_module_for(
    adapter_id: str,
    *,
    implemented_only: bool = False,
) -> SlicerDetectionModule | None:
    module = _BY_ADAPTER_ID.get(str(adapter_id).casefold())
    if module is None or (implemented_only and not module.implemented):
        return None
    return module
