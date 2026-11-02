from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
import re
import weakref

from cooling_tower.file_integrity import sha256_file
from cooling_tower.models.gcode_metadata import SlicerIdentity
from cooling_tower.protected_io import InputSnapshot, OwnedWorkspace


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class SourceKind(str, Enum):
    """User-supplied source formats accepted by the application."""

    STL = "stl"
    NATIVE_3MF = "3mf"

    @classmethod
    def from_path(cls, path: str | Path) -> "SourceKind":
        suffix = Path(path).suffix.casefold()
        if suffix == ".stl":
            return cls.STL
        if suffix == ".3mf":
            return cls.NATIVE_3MF
        raise ValueError("Unterstützt werden STL-Dateien und native 3MF-Projekte.")


class GCodeOrigin(str, Enum):
    GENERATED_PRESLICE = "generated_preslice"


class SourceChangedError(RuntimeError):
    """Raised when a file changes while its immutable identity is captured."""


@dataclass(frozen=True, slots=True, weakref_slot=True)
class _CapturedSource:
    workspace: OwnedWorkspace
    snapshot: InputSnapshot

    def __post_init__(self):
        # Artifact copies share this lifetime object; dataclasses.replace must
        # not let the first discarded artifact remove another job's snapshot.
        weakref.finalize(self, self.workspace.close)


@dataclass(frozen=True, slots=True)
class SourceArtifact:
    """Immutable identity of the original user-selected source file."""

    source_kind: SourceKind
    original_path: Path
    original_size: int
    original_mtime_ns: int
    original_sha256: str
    _captured: _CapturedSource | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        path = Path(self.original_path)
        if not path.is_absolute():
            raise ValueError("Der Pfad der Originalquelle muss absolut sein.")
        if self.original_size < 0 or self.original_mtime_ns < 0:
            raise ValueError("Dateigröße und Änderungszeit sind ungültig.")
        digest = self.original_sha256.casefold()
        if _SHA256_PATTERN.fullmatch(digest) is None:
            raise ValueError("Der SHA-256-Wert der Originalquelle ist ungültig.")
        object.__setattr__(self, "original_path", path)
        object.__setattr__(self, "original_sha256", digest)

    @classmethod
    def capture(
        cls,
        path: str | Path,
        *,
        source_kind: SourceKind | None = None,
    ) -> "SourceArtifact":
        candidate = Path(path).expanduser().resolve(strict=True)
        if not candidate.is_file():
            raise ValueError("Die ausgewählte Quelle ist keine reguläre Datei.")
        kind = source_kind or SourceKind.from_path(candidate)
        if SourceKind.from_path(candidate) is not kind:
            raise ValueError("Dateiendung und angegebener Quellentyp stimmen nicht überein.")
        workspace = OwnedWorkspace(prefix='source_')
        try:
            snapshot = workspace.capture(candidate, name='input' + candidate.suffix.casefold())
            return cls(source_kind=kind, original_path=candidate, original_size=snapshot.size,
                original_mtime_ns=snapshot.mtime_ns, original_sha256=snapshot.sha256,
                _captured=_CapturedSource(workspace, snapshot))
        except BaseException:
            workspace.close()
            raise

    @property
    def processing_path(self) -> Path:
        return self._captured.snapshot.path if self._captured else self.original_path

    def verify_processing_snapshot(self) -> None:
        if self._captured:
            self._captured.snapshot.verify()
        elif not self.matches_current_file(verify_content=True):
            raise SourceChangedError('Die Quelle wurde seit ihrer Identifizierung verändert.')

    def matches_current_file(self, *, verify_content: bool = False) -> bool:
        try:
            current = self.original_path.stat()
        except OSError:
            return False
        if (
            not self.original_path.is_file()
            or current.st_size != self.original_size
            or current.st_mtime_ns != self.original_mtime_ns
        ):
            return False
        return (
            not verify_content
            or sha256_file(self.original_path) == self.original_sha256
        )


@dataclass(frozen=True, slots=True)
class PreSliceProvenance:
    created_at_utc: str
    duration_s: float
    cache_key: str
    adapter_version: int
    cache_hit: bool = False

    def __post_init__(self) -> None:
        if self.duration_s < 0 or not _SHA256_PATTERN.fullmatch(
            self.cache_key.casefold()
        ):
            raise ValueError("Die Pre-Slice-Provenienz ist ungültig.")
        if self.adapter_version < 1:
            raise ValueError("Die Adapterversion muss positiv sein.")
        try:
            parsed = datetime.fromisoformat(
                self.created_at_utc.replace("Z", "+00:00")
            )
        except ValueError as error:
            raise ValueError("Der Pre-Slice-Zeitpunkt ist ungültig.") from error
        if parsed.tzinfo is None:
            raise ValueError("Der Pre-Slice-Zeitpunkt benötigt eine Zeitzone.")

    @classmethod
    def now(
        cls,
        *,
        duration_s: float,
        cache_key: str,
        adapter_version: int,
        cache_hit: bool = False,
    ) -> "PreSliceProvenance":
        return cls(
            created_at_utc=datetime.now(timezone.utc).isoformat(),
            duration_s=duration_s,
            cache_key=cache_key,
            adapter_version=adapter_version,
            cache_hit=cache_hit,
        )


@dataclass(frozen=True, slots=True)
class PreparedAnalysisSource:
    """A validated G-code source plus the provenance of its preparation."""

    source_artifact: SourceArtifact
    analysis_gcode_path: Path
    gcode_origin: GCodeOrigin
    gcode_sha256: str
    slicer_identity: SlicerIdentity | None = None
    slicer_version: str | None = None
    effective_profile_fingerprint: str | None = None
    preslice_provenance: PreSliceProvenance | None = None

    def __post_init__(self) -> None:
        path = Path(self.analysis_gcode_path)
        if not path.is_absolute():
            raise ValueError("Der Analyse-G-Code-Pfad muss absolut sein.")
        digest = self.gcode_sha256.casefold()
        if _SHA256_PATTERN.fullmatch(digest) is None:
            raise ValueError("Der SHA-256-Wert des Analyse-G-Codes ist ungültig.")
        if (
            self.gcode_origin is GCodeOrigin.GENERATED_PRESLICE
            and self.source_artifact.source_kind is not SourceKind.STL
        ):
            raise ValueError("Ein Pre-Slice muss aus einer STL-Quelle stammen.")
        if (
            self.gcode_origin is GCodeOrigin.GENERATED_PRESLICE
            and self.preslice_provenance is None
        ):
            raise ValueError("Bei einem Pre-Slice fehlt die Provenienz.")
        object.__setattr__(self, "analysis_gcode_path", path)
        object.__setattr__(self, "gcode_sha256", digest)

    @classmethod
    def capture(
        cls,
        *,
        source_artifact: SourceArtifact,
        analysis_gcode_path: str | Path,
        gcode_origin: GCodeOrigin,
        slicer_identity: SlicerIdentity | None = None,
        slicer_version: str | None = None,
        effective_profile_fingerprint: str | None = None,
        preslice_provenance: PreSliceProvenance | None = None,
    ) -> "PreparedAnalysisSource":
        path = Path(analysis_gcode_path).expanduser().resolve(strict=True)
        if not path.is_file() or path.suffix.casefold() != ".gcode":
            raise ValueError("Die Analysequelle ist keine lesbare G-Code-Datei.")
        before = path.stat()
        digest = sha256_file(path)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (
            after.st_size,
            after.st_mtime_ns,
        ):
            raise SourceChangedError(
                "Der Analyse-G-Code wurde während der Prüfung verändert."
            )
        return cls(
            source_artifact=source_artifact,
            analysis_gcode_path=path,
            gcode_origin=gcode_origin,
            gcode_sha256=digest,
            slicer_identity=slicer_identity,
            slicer_version=slicer_version,
            effective_profile_fingerprint=effective_profile_fingerprint,
            preslice_provenance=preslice_provenance,
        )

    def matches_analysis_gcode(self) -> bool:
        try:
            return (
                self.analysis_gcode_path.is_file()
                and sha256_file(self.analysis_gcode_path) == self.gcode_sha256
            )
        except OSError:
            return False
