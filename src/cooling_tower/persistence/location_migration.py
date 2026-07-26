from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class LocationMigrationResult:
    source: Path
    target: Path
    copied: bool
    reason: str


def copy_legacy_file_if_absent(
    source: str | Path,
    target: str | Path,
) -> LocationMigrationResult:
    """Atomically copy legacy user data without deleting or overwriting it."""

    source_path = Path(source)
    target_path = Path(target)
    try:
        if source_path.resolve() == target_path.resolve():
            return LocationMigrationResult(
                source_path,
                target_path,
                False,
                "Quelle und Ziel sind identisch.",
            )
    except OSError:
        pass
    if target_path.exists():
        return LocationMigrationResult(
            source_path,
            target_path,
            False,
            "Das Ziel existiert bereits und bleibt unverändert.",
        )
    if not source_path.is_file():
        return LocationMigrationResult(
            source_path,
            target_path,
            False,
            "Es existiert keine zu migrierende Quelldatei.",
        )

    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = target_path.with_name(f".{target_path.name}.{uuid4().hex}.tmp")
    try:
        source_before = source_path.stat()
        with source_path.open("rb") as source_handle, temporary.open("xb") as target_handle:
            shutil.copyfileobj(source_handle, target_handle, length=1024 * 1024)
            target_handle.flush()
            os.fsync(target_handle.fileno())
        source_after = source_path.stat()
        if (
            source_before.st_size != source_after.st_size
            or source_before.st_mtime_ns != source_after.st_mtime_ns
        ):
            raise OSError(
                "Die Legacy-Datei wurde während der Migration verändert."
            )
        shutil.copystat(source_path, temporary)
        try:
            os.link(temporary, target_path)
        except FileExistsError:
            return LocationMigrationResult(
                source_path,
                target_path,
                False,
                "Das Ziel wurde zwischenzeitlich erstellt und bleibt unverändert.",
            )
    finally:
        temporary.unlink(missing_ok=True)
    return LocationMigrationResult(
        source_path.resolve(),
        target_path.resolve(),
        True,
        "Die Legacy-Datei wurde sicher kopiert; das Original bleibt erhalten.",
    )


def migrate_legacy_configuration(
    source_root: str | Path,
    target_root: str | Path,
    filenames: tuple[str, ...],
) -> tuple[LocationMigrationResult, ...]:
    source_directory = Path(source_root)
    target_directory = Path(target_root)
    return tuple(
        copy_legacy_file_if_absent(
            source_directory / filename,
            target_directory / filename,
        )
        for filename in filenames
    )
