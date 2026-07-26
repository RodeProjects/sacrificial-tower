from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class MigratedFile:
    source: str
    destination: str
    category: str


@dataclass(frozen=True, slots=True)
class MigrationResult:
    migrated_root: Path
    report_path: Path
    moved_files: tuple[MigratedFile, ...]


class MigrationService:
    """Moves legacy flat output files into collision-safe categories."""

    CATEGORIES = ("stl", "analysis", "profiles", "config", "logs")

    def __init__(self, output_root: str | Path = "output") -> None:
        self.output_root = Path(output_root).expanduser()

    def migrate_flat_output(self) -> MigrationResult:
        migrated_root = self.output_root / "migrated_legacy"
        for category in self.CATEGORIES:
            (migrated_root / category).mkdir(parents=True, exist_ok=True)

        moved: list[MigratedFile] = []
        if self.output_root.is_dir():
            candidates = sorted(
                path
                for path in self.output_root.iterdir()
                if path.is_file()
            )
            for source in candidates:
                category = self.classify_file(source)
                destination = self._unique_destination(
                    migrated_root / category / source.name
                )
                shutil.move(str(source), str(destination))
                moved.append(
                    MigratedFile(
                        source=str(source.resolve()),
                        destination=str(destination.resolve()),
                        category=category,
                    )
                )

        report_path = self._unique_destination(
            migrated_root
            / "logs"
            / f"migration_report_{datetime.now():%Y%m%d_%H%M%S}.json"
        )
        report = {
            "migrated_at": datetime.now().astimezone().isoformat(),
            "output_root": str(self.output_root.resolve()),
            "moved_file_count": len(moved),
            "moved_files": [asdict(item) for item in moved],
        }
        with report_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
        return MigrationResult(
            migrated_root=migrated_root.resolve(),
            report_path=report_path.resolve(),
            moved_files=tuple(moved),
        )

    @staticmethod
    def classify_file(path: Path) -> str:
        suffix = path.suffix.lower()
        lower_name = path.name.lower()
        if suffix == ".stl":
            return "stl"
        if "profile" in lower_name:
            return "profiles"
        if suffix in {".json", ".yaml", ".yml", ".ini", ".toml"}:
            return "config" if any(
                word in lower_name for word in ("setting", "config")
            ) else "analysis"
        if suffix in {".log", ".txt"}:
            return "logs"
        return "analysis"

    @staticmethod
    def _unique_destination(path: Path) -> Path:
        if not path.exists():
            return path
        suffix = 2
        while True:
            candidate = path.with_name(
                f"{path.stem}_{suffix}{path.suffix}"
            )
            if not candidate.exists():
                return candidate
            suffix += 1
