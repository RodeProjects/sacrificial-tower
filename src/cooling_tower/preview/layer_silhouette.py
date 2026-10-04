"""Complete STL cross sections for the layer tool, independent of 3D sampling."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import trimesh

from cooling_tower.models import SourceArtifact, SourceChangedError


MAXIMUM_SILHOUETTE_SEGMENTS = 2_000_000


@dataclass(frozen=True, slots=True)
class LayerSilhouette:
    segments_xy: tuple[np.ndarray, ...]
    center_xy: tuple[float, float]


def load_layer_silhouette(source: SourceArtifact, layers) -> LayerSilhouette:
    """Read the verified original without modifying it or any slicer files.

    Sweep triangle start/end heights so only intersecting faces are considered
    at each layer. Keep complete cross sections, including separate islands;
    their projection can then be rotated without rereading or resampling.
    """
    if not source.matches_current_file(verify_content=True):
        raise SourceChangedError("Die Original-STL wurde seit der Vorbereitung verändert.")
    mesh = trimesh.load(source.original_path, file_type="stl", force="mesh", process=False)
    triangles = np.asarray(mesh.triangles, dtype=np.float64)
    if not len(triangles) or not np.isfinite(triangles).all():
        raise ValueError("Die STL enthält keine gültige Vorschaugeometrie.")
    bounds = mesh.bounds
    center = tuple(float(value) for value in (bounds[0, :2] + bounds[1, :2]) / 2)
    minimum_z = float(bounds[0, 2])
    lower = triangles[:, :, 2].min(axis=1)
    upper = triangles[:, :, 2].max(axis=1)
    starts, ends = np.argsort(lower), np.argsort(upper)
    ordered_lower, ordered_upper = lower[starts], upper[ends]
    active = set()
    start_cursor = end_cursor = 0
    previous_z = 0.0
    sections = []
    segment_count = 0
    for layer in layers:
        # The interior of the printed layer avoids coplanar top/bottom faces.
        plane = minimum_z + (previous_z + layer.z_mm) / 2
        previous_z = layer.z_mm
        start_stop = np.searchsorted(ordered_lower, plane, side="right")
        end_stop = np.searchsorted(ordered_upper, plane, side="right")
        active.update(starts[start_cursor:start_stop])
        active.difference_update(ends[end_cursor:end_stop])
        start_cursor, end_cursor = start_stop, end_stop
        if segment_count + len(active) > MAXIMUM_SILHOUETTE_SEGMENTS:
            raise ValueError("Die STL-Schnittvorschau überschreitet das Speicherlimit. Bitte ein Modell mit geringerer Netzauflösung verwenden.")
        faces = triangles[np.asarray(sorted(active), dtype=np.intp)]
        points = np.empty((len(faces), 2, 2), dtype=np.float64)
        counts = np.zeros(len(faces), dtype=np.intp)
        for first, second in ((0, 1), (1, 2), (2, 0)):
            a, b = faces[:, first], faces[:, second]
            crosses = (a[:, 2] <= plane) != (b[:, 2] <= plane)
            indices = np.flatnonzero(crosses)
            ratio = (plane - a[indices, 2]) / (b[indices, 2] - a[indices, 2])
            points[indices, counts[indices]] = a[indices, :2] + ratio[:, None] * (b[indices, :2] - a[indices, :2])
            counts[indices] += 1
        points = points[counts == 2]
        segment_count += len(points)
        points.setflags(write=False)
        sections.append(points)
    if not source.matches_current_file(verify_content=True):
        raise SourceChangedError("Die Original-STL wurde beim Lesen verändert.")
    return LayerSilhouette(tuple(sections), center)
