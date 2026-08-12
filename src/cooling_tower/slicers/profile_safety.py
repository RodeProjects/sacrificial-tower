from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Iterable, Iterator

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

    return fingerprint_profile_paths(profile.source_paths)


def fingerprint_profile_paths(
    paths: Iterable[Path],
) -> tuple[ProfileSourceFingerprint, ...]:
    """Hash a complete resolved preset chain without changing any source."""

    fingerprints: list[ProfileSourceFingerprint] = []
    for path in dict.fromkeys(Path(item).resolve() for item in paths):
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


def profile_sources_fingerprint(profile: EffectiveProfile) -> str:
    """Return one stable digest binding every slicer-owned profile source."""

    return profile_paths_fingerprint(profile.source_paths)


def profile_paths_fingerprint(paths: Iterable[Path]) -> str:
    """Return one digest for all selected and inherited profile sources."""

    payload = [
        {
            "path": str(item.path).casefold(),
            "size": item.size,
            "modified_ns": item.modified_ns,
            "sha256": item.sha256,
        }
        for item in fingerprint_profile_paths(paths)
    ]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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

    with protect_profile_paths(profile.source_paths):
        yield


@contextmanager
def protect_profile_paths(
    paths: Iterable[Path],
    *,
    expected_initial_fingerprint: str | None = None,
) -> Iterator[None]:
    """Guard selected presets and every inherited source as one unit."""

    retained_paths = tuple(paths)
    fingerprints = (
        None
        if expected_initial_fingerprint is not None
        else fingerprint_profile_paths(retained_paths)
    )
    try:
        yield
    finally:
        if fingerprints is not None:
            assert_profile_sources_unchanged(fingerprints)
        elif (
            profile_paths_fingerprint(retained_paths)
            != expected_initial_fingerprint
        ):
            raise SlicerSourceMutationError(
                "Kritischer Sicherheitsabbruch: Mindestens ein originales "
                "Slicer-Profil wurde waehrend des Vorgangs veraendert."
            )


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
