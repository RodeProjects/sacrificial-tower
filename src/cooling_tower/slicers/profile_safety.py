from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from cooling_tower.file_integrity import sha256_file
from cooling_tower.slicers.errors import SlicerSourceMutationError
from cooling_tower.slicers.models import EffectiveProfile


@dataclass(frozen=True, slots=True)
class ProfileSourceFingerprint:
    """Immutable evidence for one slicer-owned source profile."""

    path: Path
    size: int
    modified_ns: int
    sha256: str


def fingerprint_profile_sources(
    profile: EffectiveProfile,
) -> tuple[ProfileSourceFingerprint, ...]:
    """Hash every source profile without opening it for writing."""

    fingerprints: list[ProfileSourceFingerprint] = []
    for path in dict.fromkeys(item.resolve() for item in profile.source_paths):
        try:
            stat = path.stat()
            digest = sha256_file(path)
        except OSError as error:
            raise SlicerSourceMutationError(
                f"Slicer-Quellprofil konnte nicht sicher gelesen werden: {path}"
            ) from error
        fingerprints.append(
            ProfileSourceFingerprint(
                path=path,
                size=stat.st_size,
                modified_ns=stat.st_mtime_ns,
                sha256=digest,
            )
        )
    return tuple(fingerprints)


def assert_profile_sources_unchanged(
    fingerprints: tuple[ProfileSourceFingerprint, ...],
) -> None:
    """Fail closed if a slicer-owned profile changed during an operation."""

    changed: list[Path] = []
    for expected in fingerprints:
        try:
            stat = expected.path.stat()
            digest = sha256_file(expected.path)
        except OSError:
            changed.append(expected.path)
            continue
        if (
            stat.st_size != expected.size
            or stat.st_mtime_ns != expected.modified_ns
            or digest != expected.sha256
        ):
            changed.append(expected.path)
    if changed:
        rendered = ", ".join(str(path) for path in changed)
        raise SlicerSourceMutationError(
            "Kritischer Sicherheitsabbruch: Mindestens ein originales "
            f"Slicer-Profil wurde waehrend des Vorgangs veraendert: {rendered}"
        )


@contextmanager
def protect_profile_sources(profile: EffectiveProfile) -> Iterator[None]:
    """Guard original slicer profiles across an external slicer invocation."""

    fingerprints = fingerprint_profile_sources(profile)
    try:
        yield
    finally:
        assert_profile_sources_unchanged(fingerprints)


def assert_profile_copies_are_isolated(
    source_profile: EffectiveProfile,
    temporary_profile: EffectiveProfile,
    working_directory: Path,
) -> None:
    """Ensure calibration passes only app-owned temporary profile copies."""

    root = working_directory.resolve()
    source_paths = {path.resolve() for path in source_profile.source_paths}
    copied_records = (
        *((temporary_profile.machine,) if temporary_profile.machine else ()),
        *((temporary_profile.process,) if temporary_profile.process else ()),
        *temporary_profile.filaments,
    )
    for record in copied_records:
        path = record.path.resolve()
        if path in source_paths or not path.is_relative_to(root):
            raise SlicerSourceMutationError(
                "Kalibrierungsprofile muessen isolierte temporaere Kopien sein: "
                f"{path}"
            )
        if not record.metadata.get("temporary"):
            raise SlicerSourceMutationError(
                f"Temporaere Profileigenschaft fehlt fuer: {path}"
            )
