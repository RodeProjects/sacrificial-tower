from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RunPaths:
    run_directory: Path
    stl_directory: Path
    analysis_directory: Path
    profiles_directory: Path
    config_directory: Path
    logs_directory: Path

    stl_path: Path
    analysis_path: Path
    metadata_path: Path
    summary_path: Path
    profile_path: Path
    settings_path: Path
    log_path: Path

    @classmethod
    def for_directory(cls, run_directory: str | Path) -> "RunPaths":
        run = Path(run_directory)
        stl = run / "stl"
        analysis = run / "analysis"
        profiles = run / "profiles"
        config = run / "config"
        logs = run / "logs"
        return cls(
            run_directory=run,
            stl_directory=stl,
            analysis_directory=analysis,
            profiles_directory=profiles,
            config_directory=config,
            logs_directory=logs,
            stl_path=stl / "cooling_tower.stl",
            analysis_path=analysis / "layer_analysis.csv",
            metadata_path=analysis / "gcode_metadata.json",
            summary_path=analysis / "analysis_summary.json",
            profile_path=profiles / "tower_profile.csv",
            settings_path=config / "generation_settings.json",
            log_path=logs / "generation.log",
        )

    @property
    def directories(self) -> tuple[Path, ...]:
        return (
            self.run_directory,
            self.stl_directory,
            self.analysis_directory,
            self.profiles_directory,
            self.config_directory,
            self.logs_directory,
        )
