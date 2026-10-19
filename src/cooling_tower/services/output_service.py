from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path
from cooling_tower.write_policy import ensure_writable_output
from typing import Any, Iterable, Mapping, Sequence

from cooling_tower.config import save_generation_settings
from cooling_tower.models import GenerationSettings, TowerLayerProfile
from cooling_tower.paths import RunPaths


_INVALID_WINDOWS_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WHITESPACE = re.compile(r"\s+")
_RESERVED_WINDOWS_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def sanitize_filename_component(value: str) -> str:
    """Return a readable component that is safe on Windows filesystems."""
    result = _INVALID_WINDOWS_NAME.sub("_", value)
    result = _WHITESPACE.sub("_", result).strip(" ._")
    result = re.sub(r"_+", "_", result)
    if not result:
        result = "gcode"
    if result.upper() in _RESERVED_WINDOWS_NAMES:
        result = f"_{result}"
    return result[:100].rstrip(" .") or "gcode"


class OutputService:
    """Creates run directories and writes every generated artifact."""

    def __init__(self, output_root: str | Path = "output") -> None:
        self.output_root = Path(output_root).expanduser()

    @property
    def runs_root(self) -> Path:
        # The current GUI exposes the actual run directory as its output
        # destination.  Keep older callers that pass the parent ``output``
        # directory compatible without ever creating ``runs/runs``.
        if self.output_root.name.casefold() == "runs":
            return self.output_root
        return self.output_root / "runs"

    def create_run_directories(
        self,
        source_gcode_path: str | Path,
        *,
        timestamp: datetime | None = None,
    ) -> RunPaths:
        source = Path(source_gcode_path)
        moment = timestamp or datetime.now()
        stem = sanitize_filename_component(source.stem)
        base_name = f"{moment:%Y%m%d_%H%M%S}_{stem}"
        ensure_writable_output(self.runs_root)
        self.runs_root.mkdir(parents=True, exist_ok=True)

        suffix = 1
        while True:
            name = base_name if suffix == 1 else f"{base_name}_{suffix}"
            paths = RunPaths.for_directory(self.runs_root / name)
            try:
                paths.run_directory.mkdir(parents=False, exist_ok=False)
            except FileExistsError:
                suffix += 1
                continue
            break

        for directory in paths.directories[1:]:
            directory.mkdir(parents=False, exist_ok=False)
        return paths

    def write_settings(
        self,
        paths: RunPaths,
        settings: GenerationSettings,
    ) -> Path:
        return save_generation_settings(settings, paths.settings_path)

    def write_layer_analysis(
        self,
        paths: RunPaths,
        layers: Sequence[object],
        *,
        deficits: Mapping[int, float] | None = None,
    ) -> Path:
        deficit_by_index = deficits or {}
        fieldnames = (
            "layer_index",
            "z_mm",
            "height_mm",
            "total_time_s",
            "deposition_time_s",
            "travel_time_s",
            "retraction_time_s",
            "unretraction_time_s",
            "dwell_time_s",
            "deposition_path_mm",
            "deposition_e_mm",
            "time_deficit_s",
            "start_line",
            "end_line",
            "untimed_event_count",
        )
        with paths.analysis_path.open(
            "w", encoding="utf-8-sig", newline=""
        ) as handle:
            writer = csv.DictWriter(
                handle, fieldnames=fieldnames, delimiter=";"
            )
            writer.writeheader()
            for layer in layers:
                index = int(getattr(layer, "index"))
                writer.writerow(
                    {
                        "layer_index": index,
                        "z_mm": _format_float(getattr(layer, "z_mm")),
                        "height_mm": _format_float(
                            getattr(layer, "height_mm")
                        ),
                        "total_time_s": _format_float(
                            getattr(layer, "total_time_s")
                        ),
                        "deposition_time_s": _format_float(
                            getattr(layer, "deposition_time_s")
                        ),
                        "travel_time_s": _format_float(
                            getattr(layer, "travel_time_s")
                        ),
                        "retraction_time_s": _format_float(
                            getattr(layer, "retraction_time_s")
                        ),
                        "unretraction_time_s": _format_float(
                            getattr(layer, "unretraction_time_s")
                        ),
                        "dwell_time_s": _format_float(
                            getattr(layer, "dwell_time_s")
                        ),
                        "deposition_path_mm": _format_float(
                            getattr(layer, "deposition_path_mm")
                        ),
                        "deposition_e_mm": _format_float(
                            getattr(layer, "deposition_e_mm")
                        ),
                        "time_deficit_s": _format_float(
                            deficit_by_index.get(index, 0.0)
                        ),
                        "start_line": getattr(layer, "start_line"),
                        "end_line": getattr(layer, "end_line"),
                        "untimed_event_count": getattr(
                            layer, "untimed_event_count"
                        ),
                    }
                )
        return paths.analysis_path.resolve()

    def write_tower_profile(
        self,
        paths: RunPaths,
        profile_layers: Iterable[TowerLayerProfile],
    ) -> Path:
        fieldnames = (
            "layer_index",
            "z_mm",
            "layer_time_s",
            "time_deficit_s",
            "required_path_mm",
            "available_path_mm",
            "outer_diameter_raw_mm",
            "outer_diameter_spline_mm",
            "outer_diameter_mm",
            "expansion_angle_deg",
            "contraction_angle_deg",
            "angle_reference",
            "estimated_added_time_s",
            "target_reached",
            "profile_region",
        )
        with paths.profile_path.open(
            "w", encoding="utf-8-sig", newline=""
        ) as handle:
            writer = csv.DictWriter(
                handle, fieldnames=fieldnames, delimiter=";"
            )
            writer.writeheader()
            for layer in profile_layers:
                writer.writerow(
                    {
                        "layer_index": layer.index,
                        "z_mm": _format_float(layer.z),
                        "layer_time_s": _format_float(layer.layer_time_s),
                        "time_deficit_s": _format_float(layer.time_deficit_s),
                        "required_path_mm": _format_float(
                            layer.required_path_mm
                        ),
                        "available_path_mm": _format_float(
                            layer.available_path_mm
                        ),
                        "outer_diameter_raw_mm": _format_float(
                            layer.raw_outer_diameter_mm
                        ),
                        "outer_diameter_spline_mm": _format_float(
                            layer.outer_diameter_mm
                        ),
                        "outer_diameter_mm": _format_float(
                            layer.outer_diameter_mm
                        ),
                        "expansion_angle_deg": _format_float(
                            90.0-layer.expansion_angle_deg
                        ),
                        "contraction_angle_deg": _format_float(
                            90.0-layer.contraction_angle_deg
                        ),
                        "angle_reference": "horizontal",
                        "estimated_added_time_s": (
                            ""
                            if layer.estimated_added_time_s is None
                            else _format_float(layer.estimated_added_time_s)
                        ),
                        "target_reached": int(layer.target_reached),
                        "profile_region": layer.profile_region,
                    }
                )
        return paths.profile_path.resolve()

    def write_summary(
        self,
        paths: RunPaths,
        summary: Mapping[str, Any],
    ) -> Path:
        with paths.summary_path.open(
            "w", encoding="utf-8", newline="\n"
        ) as handle:
            json.dump(dict(summary), handle, indent=2, sort_keys=True)
            handle.write("\n")
        return paths.summary_path.resolve()

    def write_analysis_diagnostic(
        self,
        paths: RunPaths,
        report: object,
    ) -> Path:
        payload = (
            report.to_dict()
            if hasattr(report, "to_dict")
            else dict(report)  # type: ignore[arg-type]
        )
        with paths.metadata_path.open(
            "w", encoding="utf-8", newline="\n"
        ) as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        return paths.metadata_path.resolve()

    def write_log(self, paths: RunPaths, lines: Iterable[str]) -> Path:
        with paths.log_path.open(
            "w", encoding="utf-8", newline="\n"
        ) as handle:
            for line in lines:
                handle.write(str(line).rstrip("\r\n") + "\n")
        return paths.log_path.resolve()


def _format_float(value: object) -> str:
    return f"{float(value):.6f}"
