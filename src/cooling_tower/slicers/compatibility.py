from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SlicerCompatibility:
    adapter_id: str
    product_name: str
    executables: tuple[str, ...]
    argument_contract: str
    working_directory: str
    profile_contract: str
    expected_outputs: tuple[str, ...]
    known_return_codes: str
    output_notes: str
    running_gui_behavior: str
    subprocess_notes: str
    slicing_supported: bool = True


SLICER_COMPATIBILITY_MATRIX: tuple[SlicerCompatibility, ...] = (
    SlicerCompatibility(
        "anycubic_slicer_next",
        "Anycubic Slicer Next",
        ("AnycubicSlicerNext.exe",),
        "--datadir, --load-settings, optional --load-filaments, --arrange, --ensure-on-bed, --slice, --outputdir, model",
        "isolated per-job root",
        "temporary machine/process/filament copies; isolated --datadir",
        (".gcode", ".gcode.metadata", ".metadata"),
        "0 success; every non-zero value and CrashExit are failures",
        "stdout and stderr are independent and UTF-8 decoded with replacement",
        "CLI job remains isolated from an already running GUI instance",
        "may create helpers; Windows Job Object owns the concrete process tree",
    ),
    SlicerCompatibility(
        "orca_slicer",
        "OrcaSlicer",
        ("orca-slicer.exe", "OrcaSlicer.exe"),
        "--datadir, --load-settings, optional --load-filaments, --arrange, --ensure-on-bed, --slice, --outputdir, model",
        "isolated per-job root",
        "temporary machine/process/filament copies; isolated --datadir",
        (".gcode", ".gcode.metadata", ".metadata"),
        "0 success; every non-zero value and CrashExit are failures",
        "stdout and stderr are independent and UTF-8 decoded with replacement",
        "CLI job remains isolated from an already running GUI instance",
        "may create helpers; Windows Job Object owns the concrete process tree",
    ),
    SlicerCompatibility(
        "bambu_studio",
        "Bambu Studio",
        ("bambu-studio.exe", "BambuStudio.exe"),
        "--datadir, --load-settings, optional --load-filaments, --arrange, --ensure-on-bed, --slice, --outputdir, model",
        "isolated per-job root",
        "temporary machine/process/filament copies; isolated --datadir",
        (".gcode", ".gcode.metadata", ".metadata"),
        "0 success; every non-zero value and CrashExit are failures",
        "stdout and stderr are independent and UTF-8 decoded with replacement",
        "CLI job remains isolated from an already running GUI instance",
        "may create helpers; Windows Job Object owns the concrete process tree",
    ),
    SlicerCompatibility(
        "prusa_slicer",
        "PrusaSlicer",
        ("prusa-slicer.exe", "PrusaSlicer.exe"),
        "--load temporary-effective-profile.ini, --export-gcode, --output target.gcode, model",
        "isolated per-job root",
        "effective profile is serialized to a temporary INI file",
        (".gcode",),
        "0 success; every non-zero value and CrashExit are failures",
        "stdout and stderr are independent and UTF-8 decoded with replacement",
        "CLI job uses distinct paths and does not target the GUI process",
        "helpers are confined to the Windows Job Object when present",
    ),
    SlicerCompatibility(
        "cura",
        "UltiMaker Cura / CuraEngine",
        ("CuraEngine.exe",),
        "slice, repeated -j definitions, repeated -s key=value, -l model, -o target.gcode",
        "isolated per-job root",
        "definition files plus scalar effective settings",
        (".gcode",),
        "0 success; every non-zero value and CrashExit are failures",
        "engine diagnostics may use either stream; both remain separate",
        "CuraEngine invocation is independent of an open Cura GUI",
        "engine helpers are confined to the Windows Job Object when present",
    ),
    SlicerCompatibility(
        "ideamaker",
        "ideaMaker",
        ("ideaMaker.exe",),
        "detection only",
        "not applicable",
        "profile inventory only",
        (),
        "not applicable",
        "not applicable",
        "detection never terminates an existing GUI",
        "not applicable",
        slicing_supported=False,
    ),
    SlicerCompatibility(
        "simplify3d",
        "Simplify3D",
        ("Simplify3D.exe",),
        "detection only",
        "not applicable",
        "profile inventory only",
        (),
        "not applicable",
        "not applicable",
        "detection never terminates an existing GUI",
        "not applicable",
        slicing_supported=False,
    ),
)


def compatibility_for(adapter_id: str) -> SlicerCompatibility:
    normalized = adapter_id.strip().casefold()
    for item in SLICER_COMPATIBILITY_MATRIX:
        if item.adapter_id.casefold() == normalized:
            return item
    raise KeyError(adapter_id)
