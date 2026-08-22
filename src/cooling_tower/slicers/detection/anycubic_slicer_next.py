from __future__ import annotations

from pathlib import Path

from cooling_tower.slicers.base import existing_paths
from cooling_tower.slicers.detection.base import (
    ActivePresetSchema,
    SlicerDetectionModule,
)


class AnycubicSlicerNextDetectionModule(SlicerDetectionModule):
    """Behavior-preserving home of the proven Anycubic detection rules."""

    def __init__(self) -> None:
        super().__init__(
            adapter_id="anycubic_slicer_next",
            product_name="Anycubic Slicer Next",
            implemented=True,
            orca_derived=True,
            active_preset_schema=ActivePresetSchema(
                config_names=("AnycubicSlicerNext.conf",),
            ),
            executable_names=("AnycubicSlicerNext.exe",),
            product_markers=("AnycubicSlicerNext", "Anycubic Slicer Next"),
            installation_directories=("AnycubicSlicerNext",),
        )

    def profile_roots_for(
        self,
        executable: Path,
        *,
        appdata_root: Path | None,
    ) -> tuple[Path, ...]:
        # Keep the established Anycubic catalogue order and scope unchanged.
        resource_profiles = executable.parent / "resources" / "profiles"
        roots = [resource_profiles / "Anycubic", resource_profiles]
        if appdata_root is not None:
            base = appdata_root / "AnycubicSlicerNext"
            roots.extend((base / "user", base / "system", base / "profiles"))
        return existing_paths(roots)

    def usage_marker_paths(
        self,
        *,
        appdata_root: Path | None,
    ) -> tuple[Path, ...]:
        if appdata_root is None:
            return ()
        return (
            appdata_root
            / "AnycubicSlicerNext"
            / "AnycubicSlicerNext.conf",
        )


MODULE = AnycubicSlicerNextDetectionModule()
