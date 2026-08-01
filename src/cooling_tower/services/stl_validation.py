from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
import heapq
import math
from pathlib import Path
import re
import struct

import numpy as np

from cooling_tower.models import SourceArtifact, SourceChangedError, SourceKind


StlProgressCallback = Callable[[int, str], None]
CancellationCallback = Callable[[], bool]

_NUMBER = re.compile(
    r"^[+-]?(?:(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|nan|inf(?:inity)?)$",
    re.IGNORECASE,
)


class StlFormat(str, Enum):
    ASCII = "ascii"
    BINARY = "binary"


class StlIssueCode(str, Enum):
    INVALID_FORMAT = "invalid_format"
    RESOURCE_LIMIT = "resource_limit"
    INVALID_VALUE = "invalid_value"
    DEGENERATE_FACE = "degenerate_face"
    DUPLICATE_FACE = "duplicate_face"
    BOUNDARY_EDGE = "boundary_edge"
    NON_MANIFOLD_EDGE = "non_manifold_edge"
    INCONSISTENT_WINDING = "inconsistent_winding"
    NON_POSITIVE_VOLUME = "non_positive_volume"
    SELF_INTERSECTION = "self_intersection"


class StlValidationCancelled(RuntimeError):
    pass


class StlValidationError(ValueError):
    pass


class StlResourceLimitError(StlValidationError):
    pass


@dataclass(frozen=True, slots=True)
class StlValidationLimits:
    maximum_file_size_bytes: int = 512 * 1024 * 1024
    maximum_triangle_count: int = 2_000_000
    vertex_merge_tolerance_mm: float = 1e-6
    maximum_coordinate_magnitude_mm: float = 1e9
    maximum_intersection_candidates: int = 2_000_000
    maximum_tolerable_self_intersection_pairs: int = 2_048
    maximum_tolerable_intersection_penetration_mm: float = 0.1
    maximum_tolerable_intersection_penetration_ratio: float = 0.001

    def __post_init__(self) -> None:
        if self.maximum_file_size_bytes < 84:
            raise ValueError("Das STL-Dateilimit ist zu klein.")
        if self.maximum_triangle_count < 1:
            raise ValueError("Das STL-Dreieckslimit muss positiv sein.")
        if not math.isfinite(self.vertex_merge_tolerance_mm) or not (
            self.vertex_merge_tolerance_mm > 0
        ):
            raise ValueError("Die STL-Vertex-Toleranz muss positiv und endlich sein.")
        if not math.isfinite(self.maximum_coordinate_magnitude_mm) or not (
            self.maximum_coordinate_magnitude_mm > 0
        ):
            raise ValueError("Das STL-Koordinatenlimit muss positiv und endlich sein.")
        if self.maximum_intersection_candidates < 1:
            raise ValueError("Das STL-Schnittkandidatenlimit muss positiv sein.")
        if self.maximum_tolerable_self_intersection_pairs < 0:
            raise ValueError(
                "Die tolerierbare Anzahl lokaler STL-Überschneidungen ist ungültig."
            )
        if not math.isfinite(
            self.maximum_tolerable_intersection_penetration_mm
        ) or self.maximum_tolerable_intersection_penetration_mm <= 0:
            raise ValueError(
                "Die absolute Eindringtoleranz lokaler STL-Überschneidungen "
                "ist ungültig."
            )
        if not math.isfinite(
            self.maximum_tolerable_intersection_penetration_ratio
        ) or not 0 < self.maximum_tolerable_intersection_penetration_ratio <= 0.1:
            raise ValueError(
                "Die relative Eindringtoleranz lokaler STL-Überschneidungen "
                "ist ungültig."
            )


@dataclass(frozen=True, slots=True)
class StlValidationIssue:
    code: StlIssueCode
    message: str
    count: int = 0
    technical_detail: str | None = None
    blocking: bool = True


@dataclass(frozen=True, slots=True)
class StlValidationResult:
    valid: bool
    source_artifact: SourceArtifact
    format: StlFormat | None
    vertex_count: int
    face_count: int
    component_count: int
    boundary_edge_count: int
    non_manifold_edge_count: int
    degenerate_face_count: int
    duplicate_face_count: int
    inconsistent_edge_count: int
    self_intersection_count: int
    winding_consistent: bool
    positive_volume: bool
    component_volumes_mm3: tuple[float, ...]
    issues: tuple[StlValidationIssue, ...]
    intersection_check_complete: bool = True

    @property
    def blocking_issues(self) -> tuple[StlValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.blocking)

    @property
    def warning_issues(self) -> tuple[StlValidationIssue, ...]:
        return tuple(issue for issue in self.issues if not issue.blocking)

    @property
    def technical_summary(self) -> str:
        rows = [
            f"Format: {self.format.value if self.format else 'unbekannt'}",
            f"Vertices (topologisch): {self.vertex_count}",
            f"Dreiecke: {self.face_count}",
            f"Komponenten: {self.component_count}",
            f"Offene Kanten: {self.boundary_edge_count}",
            f"Nicht-manifold Kanten: {self.non_manifold_edge_count}",
            f"Degenerierte Dreiecke: {self.degenerate_face_count}",
            f"Doppelte Flächen: {self.duplicate_face_count}",
            f"Inkonsistent ausgerichtete Kanten: {self.inconsistent_edge_count}",
            f"Erkannte Selbstüberschneidungen: {self.self_intersection_count}",
        ]
        rows.extend(
            f"{'Problem' if issue.blocking else 'Hinweis'} "
            f"[{issue.code.value}]: {issue.message}"
            for issue in self.issues
        )
        return "\n".join(rows)


@dataclass(frozen=True, slots=True)
class _ParsedStl:
    format: StlFormat
    normals: np.ndarray
    triangles: np.ndarray


class StlValidationService:
    """Strict, read-only validation for untrusted user STL files."""

    def __init__(self, limits: StlValidationLimits | None = None) -> None:
        self.limits = limits or StlValidationLimits()

    def validate(
        self,
        path: str | Path,
        *,
        progress_callback: StlProgressCallback | None = None,
        cancellation_callback: CancellationCallback | None = None,
    ) -> StlValidationResult:
        notify = progress_callback or (lambda _percent, _status: None)
        cancelled = cancellation_callback or (lambda: False)
        source = Path(path).expanduser().resolve(strict=True)
        if source.suffix.casefold() != ".stl" or not source.is_file():
            raise StlValidationError("Bitte eine vorhandene .stl-Datei auswählen.")
        size = source.stat().st_size
        if size > self.limits.maximum_file_size_bytes:
            artifact = SourceArtifact.capture(source, source_kind=SourceKind.STL)
            return self._format_failure(
                artifact,
                StlIssueCode.RESOURCE_LIMIT,
                "Die STL ist für die sichere Verarbeitung zu groß.",
                f"Dateigröße {size}, Limit {self.limits.maximum_file_size_bytes}",
            )
        self._check_cancelled(cancelled)
        notify(5, "STL-Datei wird vollständig gelesen")
        artifact = SourceArtifact.capture(source, source_kind=SourceKind.STL)
        try:
            parsed = self._parse(source, cancelled)
        except StlValidationCancelled:
            raise
        except StlResourceLimitError as error:
            return self._format_failure(
                artifact,
                StlIssueCode.RESOURCE_LIMIT,
                "Die STL überschreitet ein sicheres Verarbeitungslimit.",
                str(error),
            )
        except (OSError, UnicodeError, StlValidationError, ValueError) as error:
            return self._format_failure(
                artifact,
                StlIssueCode.INVALID_FORMAT,
                "Die STL-Datei ist beschädigt oder unvollständig.",
                str(error),
            )
        self._check_cancelled(cancelled)
        notify(25, "Koordinaten und Dreiecke werden geprüft")
        result = self._validate_geometry(artifact, parsed, notify, cancelled)
        self._check_cancelled(cancelled)
        if not artifact.matches_current_file(verify_content=True):
            raise SourceChangedError(
                "Die STL-Datei wurde während der Prüfung verändert."
            )
        notify(100, "STL-Prüfung abgeschlossen")
        return result

    def _parse(
        self,
        path: Path,
        cancelled: CancellationCallback,
    ) -> _ParsedStl:
        size = path.stat().st_size
        if size < 6:
            raise StlValidationError("Die STL-Datei ist zu kurz.")
        with path.open("rb") as handle:
            prefix = handle.read(512)
        binary_count: int | None = None
        if size >= 84:
            binary_count = struct.unpack_from("<I", prefix, 80)[0]
            if 84 + binary_count * 50 == size:
                return self._parse_binary(path, binary_count, cancelled)
        stripped = prefix.lstrip(b"\xef\xbb\xbf\t\r\n ")
        if stripped[:5].lower() == b"solid" and b"facet" in prefix.lower():
            return self._parse_ascii(path, cancelled)
        if binary_count is not None:
            raise StlValidationError(
                "Deklarierte und tatsächliche Binär-STL-Größe stimmen nicht überein."
            )
        raise StlValidationError("STL-Containerformat nicht erkannt.")

    def _parse_binary(
        self,
        path: Path,
        triangle_count: int,
        cancelled: CancellationCallback,
    ) -> _ParsedStl:
        if triangle_count < 1:
            raise StlValidationError("Die STL enthält keine Dreiecke.")
        if triangle_count > self.limits.maximum_triangle_count:
            raise StlResourceLimitError(
                "Die deklarierte Dreiecksanzahl überschreitet das Sicherheitslimit."
            )
        self._check_cancelled(cancelled)
        dtype = np.dtype(
            [
                ("normal", "<f4", (3,)),
                ("vertices", "<f4", (3, 3)),
                ("attribute", "<u2"),
            ]
        )
        records = np.fromfile(path, dtype=dtype, count=triangle_count, offset=84)
        if len(records) != triangle_count:
            raise StlValidationError("Die Binär-STL endet vorzeitig.")
        return _ParsedStl(
            StlFormat.BINARY,
            np.asarray(records["normal"], dtype=np.float64),
            np.asarray(records["vertices"], dtype=np.float64),
        )

    def _parse_ascii(
        self,
        path: Path,
        cancelled: CancellationCallback,
    ) -> _ParsedStl:
        facet_count = 0
        with path.open("r", encoding="utf-8-sig", errors="strict") as handle:
            for line_number, line in enumerate(handle, 1):
                if line.lstrip().casefold().startswith("facet normal"):
                    facet_count += 1
                    if facet_count > self.limits.maximum_triangle_count:
                        raise StlResourceLimitError(
                            "Die ASCII-STL überschreitet das Dreieckslimit."
                        )
                if line_number % 4096 == 0:
                    self._check_cancelled(cancelled)
        if facet_count < 1:
            raise StlValidationError("Die ASCII-STL enthält keine Facetten.")
        normals = np.empty((facet_count, 3), dtype=np.float64)
        triangles = np.empty((facet_count, 3, 3), dtype=np.float64)
        facet_index = -1
        vertex_index = 0
        in_facet = False
        saw_endsolid = False
        with path.open("r", encoding="utf-8-sig", errors="strict") as handle:
            for line_number, line in enumerate(handle, 1):
                stripped = line.strip()
                if not stripped:
                    continue
                parts = stripped.split()
                keyword = parts[0].casefold()
                if keyword == "solid" or keyword == "outer" or keyword == "endloop":
                    continue
                if keyword == "endsolid":
                    saw_endsolid = True
                    continue
                if keyword == "facet":
                    if in_facet or len(parts) != 5 or parts[1].casefold() != "normal":
                        raise StlValidationError(
                            f"Ungültige Facette in Zeile {line_number}."
                        )
                    facet_index += 1
                    normals[facet_index] = self._parse_vector(parts[2:], line_number)
                    vertex_index = 0
                    in_facet = True
                elif keyword == "vertex":
                    if not in_facet or len(parts) != 4 or vertex_index >= 3:
                        raise StlValidationError(
                            f"Ungültiger Vertex in Zeile {line_number}."
                        )
                    triangles[facet_index, vertex_index] = self._parse_vector(
                        parts[1:], line_number
                    )
                    vertex_index += 1
                elif keyword == "endfacet":
                    if not in_facet or vertex_index != 3:
                        raise StlValidationError(
                            f"Unvollständige Facette in Zeile {line_number}."
                        )
                    in_facet = False
                else:
                    raise StlValidationError(
                        f"Unbekanntes ASCII-STL-Element in Zeile {line_number}."
                    )
                if line_number % 4096 == 0:
                    self._check_cancelled(cancelled)
        if in_facet or facet_index + 1 != facet_count or not saw_endsolid:
            raise StlValidationError("Die ASCII-STL ist unvollständig.")
        return _ParsedStl(StlFormat.ASCII, normals, triangles)

    @staticmethod
    def _parse_vector(parts: list[str], line_number: int) -> tuple[float, float, float]:
        if len(parts) != 3 or any(_NUMBER.fullmatch(item) is None for item in parts):
            raise StlValidationError(
                f"Ungültiger Zahlenvektor in Zeile {line_number}."
            )
        return tuple(float(item) for item in parts)  # type: ignore[return-value]

    def _validate_geometry(
        self,
        artifact: SourceArtifact,
        parsed: _ParsedStl,
        notify: StlProgressCallback,
        cancelled: CancellationCallback,
    ) -> StlValidationResult:
        triangles = parsed.triangles
        face_count = int(len(triangles))
        issues: list[StlValidationIssue] = []
        invalid_values = int(
            np.count_nonzero(~np.isfinite(triangles))
            + np.count_nonzero(~np.isfinite(parsed.normals))
        )
        finite_vertices = bool(np.isfinite(triangles).all())
        if finite_vertices and np.max(np.abs(triangles), initial=0.0) > (
            self.limits.maximum_coordinate_magnitude_mm
        ):
            invalid_values += 1
        if invalid_values:
            issues.append(
                StlValidationIssue(
                    StlIssueCode.INVALID_VALUE,
                    "Die STL enthält ungültige oder nicht endliche Koordinaten.",
                    invalid_values,
                )
            )
            return self._geometry_failure(
                artifact, parsed.format, face_count, issues
            )

        cross = np.cross(
            triangles[:, 1] - triangles[:, 0],
            triangles[:, 2] - triangles[:, 0],
        )
        twice_area = np.linalg.norm(cross, axis=1)
        area_threshold = self.limits.vertex_merge_tolerance_mm**2
        raw_degenerate = twice_area <= area_threshold

        vertices = triangles.reshape((-1, 3))
        scale = 1.0 / self.limits.vertex_merge_tolerance_mm
        quantized = np.rint(vertices * scale).astype(np.int64)
        unique_quantized, first_indices, inverse = np.unique(
            quantized,
            axis=0,
            return_index=True,
            return_inverse=True,
        )
        welded_vertices = vertices[first_indices]
        faces = inverse.reshape((-1, 3))
        collapsed = (
            (faces[:, 0] == faces[:, 1])
            | (faces[:, 1] == faces[:, 2])
            | (faces[:, 2] == faces[:, 0])
        )
        degenerate = raw_degenerate | collapsed
        degenerate_count = int(np.count_nonzero(degenerate))
        if degenerate_count:
            issues.append(
                StlValidationIssue(
                    StlIssueCode.DEGENERATE_FACE,
                    "Die STL enthält degenerierte Dreiecke.",
                    degenerate_count,
                )
            )

        notify(45, "Topologie und Kanten werden geprüft")
        self._check_cancelled(cancelled)
        canonical_faces = np.sort(faces, axis=1)
        _face_keys, face_key_counts = np.unique(
            canonical_faces, axis=0, return_counts=True
        )
        duplicate_count = int(np.sum(np.maximum(face_key_counts - 1, 0)))
        if duplicate_count:
            issues.append(
                StlValidationIssue(
                    StlIssueCode.DUPLICATE_FACE,
                    "Die STL enthält doppelte oder widersprüchliche Flächen.",
                    duplicate_count,
                )
            )

        oriented_edges = np.concatenate(
            (faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]),
            axis=0,
        )
        edge_faces = np.tile(np.arange(face_count, dtype=np.int64), 3)
        canonical_edges = np.sort(oriented_edges, axis=1)
        _edge_keys, edge_inverse, edge_counts = np.unique(
            canonical_edges,
            axis=0,
            return_inverse=True,
            return_counts=True,
        )
        boundary_count = int(np.count_nonzero(edge_counts == 1))
        non_manifold_count = int(np.count_nonzero(edge_counts > 2))
        directions = np.where(
            oriented_edges[:, 0] < oriented_edges[:, 1], 1, -1
        )
        direction_sums = np.bincount(
            edge_inverse,
            weights=directions,
            minlength=len(edge_counts),
        )
        inconsistent_count = int(
            np.count_nonzero((edge_counts == 2) & (direction_sums != 0))
        )
        if boundary_count:
            issues.append(
                StlValidationIssue(
                    StlIssueCode.BOUNDARY_EDGE,
                    "Das Modell besitzt offene Kanten und ist non-manifold "
                    "(nicht vollständig geschlossen).",
                    boundary_count,
                )
            )
        if non_manifold_count:
            issues.append(
                StlValidationIssue(
                    StlIssueCode.NON_MANIFOLD_EDGE,
                    "Kanten mit mehr als zwei angrenzenden Flächen wurden erkannt.",
                    non_manifold_count,
                )
            )
        if inconsistent_count:
            issues.append(
                StlValidationIssue(
                    StlIssueCode.INCONSISTENT_WINDING,
                    "Benachbarte Flächen sind nicht konsistent ausgerichtet.",
                    inconsistent_count,
                )
            )

        notify(65, "Geschlossene Komponenten und Volumen werden geprüft")
        labels, component_count = _face_components(
            face_count,
            edge_inverse,
            edge_counts,
            edge_faces,
            cancelled,
        )
        origin = np.mean(welded_vertices, axis=0)
        shifted = triangles - origin
        signed_face_volumes = np.einsum(
            "ij,ij->i",
            shifted[:, 0],
            np.cross(shifted[:, 1], shifted[:, 2]),
        ) / 6.0
        component_volumes = np.bincount(
            labels,
            weights=signed_face_volumes,
            minlength=component_count,
        )
        volume_threshold = self.limits.vertex_merge_tolerance_mm**3
        positive_volume = bool(
            component_count > 0
            and np.isfinite(component_volumes).all()
            and np.all(component_volumes > volume_threshold)
        )
        if not positive_volume:
            issues.append(
                StlValidationIssue(
                    StlIssueCode.NON_POSITIVE_VOLUME,
                    "Mindestens eine Komponente besitzt kein gültiges positives Volumen.",
                    int(np.count_nonzero(component_volumes <= volume_threshold)),
                )
            )

        self_intersections = 0
        blocking_self_intersection = False
        intersection_complete = True
        topology_clean = not (
            boundary_count
            or non_manifold_count
            or inconsistent_count
            or degenerate_count
            or duplicate_count
        )
        if topology_clean:
            notify(82, "Problematische Flächenüberschneidungen werden gesucht")
            (
                self_intersections,
                intersection_complete,
                blocking_self_intersection,
            ) = _count_intersections(
                triangles,
                faces,
                labels,
                self.limits,
                cancelled,
            )
            if self_intersections:
                if blocking_self_intersection:
                    issues.append(
                        StlValidationIssue(
                            StlIssueCode.SELF_INTERSECTION,
                            "Das Modell enthält eine sicherheitskritische "
                            "Flächenüberschneidung.",
                            self_intersections,
                        )
                    )
                else:
                    issues.append(
                        StlValidationIssue(
                            StlIssueCode.SELF_INTERSECTION,
                            "Geringfügige lokale Flächenüberschneidungen wurden "
                            "erkannt. Die geschlossene Topologie und das positive "
                            "Volumen bleiben eindeutig; die Verarbeitung wird mit "
                            "Hinweis fortgesetzt.",
                            self_intersections,
                            technical_detail=(
                                "warning_only=true; "
                                "maximum_tolerable_self_intersection_pairs="
                                f"{self.limits.maximum_tolerable_self_intersection_pairs}; "
                                "maximum_tolerable_intersection_penetration_mm="
                                f"{self.limits.maximum_tolerable_intersection_penetration_mm}; "
                                "maximum_tolerable_intersection_penetration_ratio="
                                f"{self.limits.maximum_tolerable_intersection_penetration_ratio}"
                            ),
                            blocking=False,
                        )
                    )
            if not intersection_complete:
                issues.append(
                    StlValidationIssue(
                        StlIssueCode.RESOURCE_LIMIT,
                        "Die Überschneidungsprüfung überschritt das sichere Arbeitslimit.",
                        technical_detail=(
                            "maximum_intersection_candidates="
                            f"{self.limits.maximum_intersection_candidates}"
                        ),
                    )
                )
        notify(95, "STL-Prüfergebnis wird abgesichert")
        return StlValidationResult(
            valid=not any(issue.blocking for issue in issues),
            source_artifact=artifact,
            format=parsed.format,
            vertex_count=int(len(unique_quantized)),
            face_count=face_count,
            component_count=component_count,
            boundary_edge_count=boundary_count,
            non_manifold_edge_count=non_manifold_count,
            degenerate_face_count=degenerate_count,
            duplicate_face_count=duplicate_count,
            inconsistent_edge_count=inconsistent_count,
            self_intersection_count=self_intersections,
            winding_consistent=inconsistent_count == 0,
            positive_volume=positive_volume,
            component_volumes_mm3=tuple(float(value) for value in component_volumes),
            issues=tuple(issues),
            intersection_check_complete=intersection_complete,
        )

    @staticmethod
    def _geometry_failure(
        artifact: SourceArtifact,
        stl_format: StlFormat,
        face_count: int,
        issues: list[StlValidationIssue],
    ) -> StlValidationResult:
        return StlValidationResult(
            valid=False,
            source_artifact=artifact,
            format=stl_format,
            vertex_count=0,
            face_count=face_count,
            component_count=0,
            boundary_edge_count=0,
            non_manifold_edge_count=0,
            degenerate_face_count=0,
            duplicate_face_count=0,
            inconsistent_edge_count=0,
            self_intersection_count=0,
            winding_consistent=False,
            positive_volume=False,
            component_volumes_mm3=(),
            issues=tuple(issues),
            intersection_check_complete=False,
        )

    @staticmethod
    def _format_failure(
        artifact: SourceArtifact,
        code: StlIssueCode,
        message: str,
        detail: str,
    ) -> StlValidationResult:
        return StlValidationResult(
            valid=False,
            source_artifact=artifact,
            format=None,
            vertex_count=0,
            face_count=0,
            component_count=0,
            boundary_edge_count=0,
            non_manifold_edge_count=0,
            degenerate_face_count=0,
            duplicate_face_count=0,
            inconsistent_edge_count=0,
            self_intersection_count=0,
            winding_consistent=False,
            positive_volume=False,
            component_volumes_mm3=(),
            issues=(StlValidationIssue(code, message, technical_detail=detail),),
            intersection_check_complete=False,
        )

    @staticmethod
    def _check_cancelled(cancelled: CancellationCallback) -> None:
        if cancelled():
            raise StlValidationCancelled("STL-Prüfung wurde abgebrochen.")


def _face_components(
    face_count: int,
    edge_inverse: np.ndarray,
    edge_counts: np.ndarray,
    edge_faces: np.ndarray,
    cancelled: CancellationCallback,
) -> tuple[np.ndarray, int]:
    parent = np.arange(face_count, dtype=np.int64)

    def find(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = int(parent[value])
        return value

    def union(first: int, second: int) -> None:
        root_a = find(first)
        root_b = find(second)
        if root_a != root_b:
            parent[root_b] = root_a

    order = np.argsort(edge_inverse, kind="stable")
    offsets = np.concatenate(([0], np.cumsum(edge_counts)))
    for edge_id in np.flatnonzero(edge_counts >= 2):
        start, end = int(offsets[edge_id]), int(offsets[edge_id + 1])
        group = edge_faces[order[start:end]]
        base = int(group[0])
        for other in group[1:]:
            union(base, int(other))
        if edge_id % 8192 == 0 and cancelled():
            raise StlValidationCancelled("STL-Prüfung wurde abgebrochen.")
    roots = np.fromiter((find(index) for index in range(face_count)), dtype=np.int64)
    _unique, labels = np.unique(roots, return_inverse=True)
    return labels, int(len(_unique))


def _count_intersections(
    triangles: np.ndarray,
    welded_faces: np.ndarray,
    component_labels: np.ndarray,
    limits: StlValidationLimits,
    cancelled: CancellationCallback,
) -> tuple[int, bool, bool]:
    """Classify proper intersections using a bounded, batched sweep.

    Intersections between distinct closed components are always blocking.
    Within one otherwise clean component, a bounded number of intersections
    between very small local facets is retained as a warning. This mirrors the
    robust behaviour of production slicers without accepting gross folded or
    overlapping volumes.
    """

    minima = triangles.min(axis=1)
    maxima = triangles.max(axis=1)
    order = np.argsort(minima[:, 0], kind="stable")
    active: set[int] = set()
    expiry: list[tuple[float, int]] = []
    checked = 0
    intersections = 0
    epsilon = 1e-8
    pending: list[tuple[int, int]] = []
    model_diagonal = float(
        np.linalg.norm(
            triangles.reshape((-1, 3)).max(axis=0)
            - triangles.reshape((-1, 3)).min(axis=0)
        )
    )
    penetration_limit = min(
        limits.maximum_tolerable_intersection_penetration_mm,
        max(
            limits.vertex_merge_tolerance_mm * 100.0,
            model_diagonal
            * limits.maximum_tolerable_intersection_penetration_ratio,
        ),
    )

    def evaluate_pending() -> bool:
        """Return true as soon as one blocking intersection is established."""

        nonlocal intersections
        if not pending:
            return False
        pairs = np.asarray(pending, dtype=np.int64)
        pending.clear()
        hits, penetration_depths = _triangle_pairs_intersection_metrics(
            triangles,
            pairs,
            epsilon,
        )
        for pair_index_value in np.flatnonzero(hits):
            pair_index = int(pair_index_value)
            pair = pairs[pair_index]
            first, second = int(pair[0]), int(pair[1])
            intersections += 1
            if component_labels[first] != component_labels[second]:
                return True
            if penetration_depths[pair_index] > penetration_limit:
                return True
            if (
                intersections
                > limits.maximum_tolerable_self_intersection_pairs
            ):
                return True
        return False

    for position, current_value in enumerate(order):
        current = int(current_value)
        min_x = minima[current, 0]
        while expiry and expiry[0][0] + epsilon < min_x:
            _maximum_x, expired = heapq.heappop(expiry)
            active.discard(expired)
        limit_reached = False
        if active:
            active_indices = np.fromiter(active, dtype=np.int64)
            overlaps = (
                (maxima[active_indices, 1] + epsilon >= minima[current, 1])
                & (maxima[current, 1] + epsilon >= minima[active_indices, 1])
                & (maxima[active_indices, 2] + epsilon >= minima[current, 2])
                & (maxima[current, 2] + epsilon >= minima[active_indices, 2])
            )
            candidates = active_indices[overlaps]
            if len(candidates):
                candidate_faces = welded_faces[candidates]
                current_face = welded_faces[current]
                shares_vertex = np.any(
                    candidate_faces[:, :, None]
                    == current_face[None, None, :],
                    axis=(1, 2),
                )
                candidates = candidates[~shares_vertex]
            remaining = limits.maximum_intersection_candidates - checked
            if len(candidates) > remaining:
                candidates = candidates[: max(0, remaining)]
                limit_reached = True
            checked += len(candidates)
            pending.extend((current, int(other)) for other in candidates)
            if len(pending) >= 4096 and evaluate_pending():
                return intersections, True, True
        active.add(current)
        heapq.heappush(expiry, (float(maxima[current, 0]), current))
        if limit_reached:
            if evaluate_pending():
                return intersections, True, True
            return intersections, False, False
        if position % 2048 == 0 and cancelled():
            raise StlValidationCancelled("STL-Prüfung wurde abgebrochen.")
    if evaluate_pending():
        return intersections, True, True
    return intersections, True, False


def _triangle_pairs_intersection_metrics(
    triangles: np.ndarray,
    pairs: np.ndarray,
    epsilon: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Return intersection flags and conservative penetration depths."""

    if len(pairs) == 0:
        empty = np.zeros(0, dtype=bool)
        return empty, np.zeros(0, dtype=np.float64)
    first = triangles[pairs[:, 0]]
    second = triangles[pairs[:, 1]]
    hits = np.zeros(len(pairs), dtype=bool)
    penetration_depths = np.zeros(len(pairs), dtype=np.float64)
    for source, target in ((first, second), (second, first)):
        edge_one = target[:, 1] - target[:, 0]
        edge_two = target[:, 2] - target[:, 0]
        target_maximum_edge = np.maximum.reduce(
            (
                np.linalg.norm(target[:, 1] - target[:, 0], axis=1),
                np.linalg.norm(target[:, 2] - target[:, 1], axis=1),
                np.linalg.norm(target[:, 0] - target[:, 2], axis=1),
            )
        )
        target_scale = np.linalg.norm(edge_one, axis=1) * np.linalg.norm(
            edge_two, axis=1
        )
        for start_index, end_index in ((0, 1), (1, 2), (2, 0)):
            start = source[:, start_index]
            direction = source[:, end_index] - start
            pvec = np.cross(direction, edge_two)
            determinant = np.einsum("ij,ij->i", edge_one, pvec)
            determinant_scale = np.linalg.norm(direction, axis=1) * target_scale
            valid = (determinant_scale > 0) & (
                np.abs(determinant) > epsilon * determinant_scale
            )
            inverse = np.zeros_like(determinant)
            inverse[valid] = 1.0 / determinant[valid]
            tvec = start - target[:, 0]
            u = np.einsum("ij,ij->i", tvec, pvec) * inverse
            qvec = np.cross(tvec, edge_one)
            v = np.einsum("ij,ij->i", direction, qvec) * inverse
            distance = np.einsum("ij,ij->i", edge_two, qvec) * inverse
            current_hits = (
                valid
                & (u > epsilon)
                & (u < 1.0 - epsilon)
                & (v > epsilon)
                & (u + v < 1.0 - epsilon)
                & (distance > epsilon)
                & (distance < 1.0 - epsilon)
            )
            barycentric_margin = np.minimum.reduce((u, v, 1.0 - u - v))
            penetration_depths = np.maximum(
                penetration_depths,
                np.where(
                    current_hits,
                    np.maximum(0.0, barycentric_margin)
                    * target_maximum_edge,
                    0.0,
                ),
            )
            hits |= current_hits

    remaining = np.flatnonzero(~hits)
    if not len(remaining):
        return hits, penetration_depths
    first_remaining = first[remaining]
    second_remaining = second[remaining]
    first_normals = np.cross(
        first_remaining[:, 1] - first_remaining[:, 0],
        first_remaining[:, 2] - first_remaining[:, 0],
    )
    second_normals = np.cross(
        second_remaining[:, 1] - second_remaining[:, 0],
        second_remaining[:, 2] - second_remaining[:, 0],
    )
    first_lengths = np.linalg.norm(first_normals, axis=1)
    second_lengths = np.linalg.norm(second_normals, axis=1)
    parallel = np.linalg.norm(
        np.cross(first_normals, second_normals), axis=1
    ) <= epsilon * first_lengths * second_lengths
    for local_index in np.flatnonzero(parallel):
        pair_index = int(remaining[local_index])
        if _coplanar_triangles_overlap(
            first[pair_index],
            second[pair_index],
            epsilon,
        ):
            hits[pair_index] = True
            # Coplanar facets have no penetration depth. Their smaller local
            # feature size is a conservative proxy: tiny overlapping slivers
            # may be tolerated inside one clean shell, while broad coplanar
            # overlaps remain blocking.
            first_maximum_edge = max(
                float(np.linalg.norm(first[pair_index, 1] - first[pair_index, 0])),
                float(np.linalg.norm(first[pair_index, 2] - first[pair_index, 1])),
                float(np.linalg.norm(first[pair_index, 0] - first[pair_index, 2])),
            )
            second_maximum_edge = max(
                float(np.linalg.norm(second[pair_index, 1] - second[pair_index, 0])),
                float(np.linalg.norm(second[pair_index, 2] - second[pair_index, 1])),
                float(np.linalg.norm(second[pair_index, 0] - second[pair_index, 2])),
            )
            penetration_depths[pair_index] = min(
                first_maximum_edge,
                second_maximum_edge,
            )
    return hits, penetration_depths


def _triangles_properly_intersect(
    first: np.ndarray,
    second: np.ndarray,
    epsilon: float,
) -> bool:
    for triangle, target in ((first, second), (second, first)):
        for start, end in (
            (triangle[0], triangle[1]),
            (triangle[1], triangle[2]),
            (triangle[2], triangle[0]),
        ):
            if _segment_triangle_intersection(start, end, target, epsilon):
                return True
    return _coplanar_triangles_overlap(first, second, epsilon)


def _coplanar_triangles_overlap(
    first: np.ndarray,
    second: np.ndarray,
    epsilon: float,
) -> bool:
    """Return true for a positive-area overlap of two coplanar triangles."""

    first_normal = np.cross(first[1] - first[0], first[2] - first[0])
    second_normal = np.cross(second[1] - second[0], second[2] - second[0])
    first_length = float(np.linalg.norm(first_normal))
    second_length = float(np.linalg.norm(second_normal))
    if first_length <= 0 or second_length <= 0:
        return False
    if float(np.linalg.norm(np.cross(first_normal, second_normal))) > (
        epsilon * first_length * second_length
    ):
        return False
    unit_normal = first_normal / first_length
    coordinate_scale = max(
        float(np.ptp(first, axis=0).max(initial=0.0)),
        float(np.ptp(second, axis=0).max(initial=0.0)),
        1.0,
    )
    if np.max(np.abs((second - first[0]) @ unit_normal), initial=0.0) > (
        epsilon * coordinate_scale
    ):
        return False

    projection_axis = int(np.argmax(np.abs(unit_normal)))
    first_2d = np.delete(first, projection_axis, axis=1)
    second_2d = np.delete(second, projection_axis, axis=1)
    projected_scale = max(
        float(np.ptp(first_2d, axis=0).max(initial=0.0)),
        float(np.ptp(second_2d, axis=0).max(initial=0.0)),
        1e-6,
    )
    tolerance = epsilon * projected_scale * projected_scale
    for start_a, end_a in _triangle_edges_2d(first_2d):
        for start_b, end_b in _triangle_edges_2d(second_2d):
            if _segments_cross_strictly_2d(
                start_a,
                end_a,
                start_b,
                end_b,
                tolerance,
            ):
                return True
    return any(
        _point_strictly_inside_triangle_2d(point, target, tolerance)
        for point, target in (
            *((point, second_2d) for point in first_2d),
            *((point, first_2d) for point in second_2d),
        )
    )


def _triangle_edges_2d(
    triangle: np.ndarray,
) -> tuple[tuple[np.ndarray, np.ndarray], ...]:
    return (
        (triangle[0], triangle[1]),
        (triangle[1], triangle[2]),
        (triangle[2], triangle[0]),
    )


def _orientation_2d(first: np.ndarray, second: np.ndarray, point: np.ndarray) -> float:
    return float(
        (second[0] - first[0]) * (point[1] - first[1])
        - (second[1] - first[1]) * (point[0] - first[0])
    )


def _segments_cross_strictly_2d(
    start_a: np.ndarray,
    end_a: np.ndarray,
    start_b: np.ndarray,
    end_b: np.ndarray,
    tolerance: float,
) -> bool:
    a_to_b_start = _orientation_2d(start_a, end_a, start_b)
    a_to_b_end = _orientation_2d(start_a, end_a, end_b)
    b_to_a_start = _orientation_2d(start_b, end_b, start_a)
    b_to_a_end = _orientation_2d(start_b, end_b, end_a)
    return (
        (
            a_to_b_start > tolerance and a_to_b_end < -tolerance
        )
        or (
            a_to_b_start < -tolerance and a_to_b_end > tolerance
        )
    ) and (
        (
            b_to_a_start > tolerance and b_to_a_end < -tolerance
        )
        or (
            b_to_a_start < -tolerance and b_to_a_end > tolerance
        )
    )


def _point_strictly_inside_triangle_2d(
    point: np.ndarray,
    triangle: np.ndarray,
    tolerance: float,
) -> bool:
    orientations = tuple(
        _orientation_2d(start, end, point)
        for start, end in _triangle_edges_2d(triangle)
    )
    return all(value > tolerance for value in orientations) or all(
        value < -tolerance for value in orientations
    )


def _segment_triangle_intersection(
    start: np.ndarray,
    end: np.ndarray,
    triangle: np.ndarray,
    epsilon: float,
) -> bool:
    direction = end - start
    edge_one = triangle[1] - triangle[0]
    edge_two = triangle[2] - triangle[0]
    pvec = np.cross(direction, edge_two)
    determinant = float(np.dot(edge_one, pvec))
    determinant_scale = (
        float(np.linalg.norm(direction))
        * float(np.linalg.norm(edge_one))
        * float(np.linalg.norm(edge_two))
    )
    if determinant_scale <= 0 or abs(determinant) <= epsilon * determinant_scale:
        return False
    inverse = 1.0 / determinant
    tvec = start - triangle[0]
    u = float(np.dot(tvec, pvec)) * inverse
    if u <= epsilon or u >= 1.0 - epsilon:
        return False
    qvec = np.cross(tvec, edge_one)
    v = float(np.dot(direction, qvec)) * inverse
    if v <= epsilon or u + v >= 1.0 - epsilon:
        return False
    distance = float(np.dot(edge_two, qvec)) * inverse
    return epsilon < distance < 1.0 - epsilon
