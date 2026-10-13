"""Bounded, component-aware preview reduction using only owned NumPy arrays.

The slider is a quality preference, never a requested percentage of faces.
Unsafe components and singular neighborhoods stay exact. No repair or spatial
welding is performed.
"""
from collections import OrderedDict
from dataclasses import dataclass, field
import math
from threading import Lock

import numpy as np

from cooling_tower.preview.toolpath import PreviewCancelled


SMALL_MESH_FACES = 6000
MINIMUM_FACE_SAVING = .20
MAXIMUM_COMPONENTS_FOR_REDUCTION = 256


def check_cancel(event):
    if event is not None and event.is_set():
        raise PreviewCancelled()


def connected_labels(count, edges, event=None):
    """Vectorized union/find with pointer jumping; no optional graph library."""
    labels = np.arange(count)
    while len(edges):
        check_cancel(event)
        before = labels.copy()
        pairs = labels[edges]
        roots = pairs.min(axis=1)
        np.minimum.at(labels, pairs[:, 0], roots)
        np.minimum.at(labels, pairs[:, 1], roots)
        labels = labels[labels]
        if np.array_equal(labels, before):
            break
    return labels


@dataclass(frozen=True, slots=True)
class MeshTopology:
    source: np.ndarray = field(compare=False, repr=False)
    vertices: np.ndarray
    faces: np.ndarray
    normals: np.ndarray
    edges: np.ndarray
    first: np.ndarray
    last: np.ndarray
    counts: np.ndarray
    vertex_components: np.ndarray
    face_components: np.ndarray
    safe_components: np.ndarray
    contour_components: np.ndarray
    bounds: np.ndarray
    protected_vertices: np.ndarray
    singular_vertices: np.ndarray
    _cache: OrderedDict = field(default_factory=OrderedDict, compare=False, repr=False)
    _cache_lock: Lock = field(default_factory=Lock, compare=False, repr=False)

    @property
    def reliable_contours(self):
        # Pinched vertices do not invalidate the oriented boundary integral
        # used for a projected silhouette. Open/inconsistently wound edges do.
        return bool(len(self.contour_components) and self.contour_components.all())

    @property
    def manifold(self):
        return bool(len(self.safe_components) and self.safe_components.all())


def build_mesh_topology(triangles, event=None):
    check_cancel(event)
    vertices, inverse = np.unique(np.asarray(triangles).reshape(-1, 3), axis=0, return_inverse=True)
    faces = inverse.reshape(-1, 3)
    normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    directed = faces[:, (0, 1, 1, 2, 2, 0)].reshape(-1, 2)
    edges, groups, counts = np.unique(np.sort(directed, axis=1), axis=0,
                                     return_inverse=True, return_counts=True)
    order = np.argsort(groups, kind="stable")
    starts = np.cumsum(counts) - counts
    first, last = order[starts], order[starts + counts - 1]
    labels = connected_labels(len(vertices), edges, event)
    _, components = np.unique(labels, return_inverse=True)
    face_components = components[faces[:, 0]]
    component_count = int(components.max()) + 1 if len(components) else 0
    safe = np.ones(component_count, dtype=bool)
    opposed = np.all(directed[first] == directed[last, ::-1], axis=1)
    bad_edges = (counts != 2) | ~opposed
    safe[components[edges[bad_edges, 0]]] = False
    lengths = np.linalg.norm(normals, axis=1)
    bad_faces = ~np.isfinite(triangles).all(axis=(1, 2)) | (lengths <= 1e-15)
    safe[face_components[bad_faces]] = False
    contour_safe = safe.copy()

    # A closed edge-manifold can still have a pinched, non-manifold vertex.
    # Connect face corners across paired edges; each vertex must have one fan.
    paired = (counts == 2) & opposed
    a, b = first[paired], last[paired]
    corner_pairs = np.concatenate((
        np.column_stack((a, b // 3 * 3 + (b % 3 + 1) % 3)),
        np.column_stack((a // 3 * 3 + (a % 3 + 1) % 3, b))))
    fans = connected_labels(faces.size, corner_pairs, event)
    lower = np.full(len(vertices), faces.size, dtype=np.int64)
    upper = np.full(len(vertices), -1, dtype=np.int64)
    np.minimum.at(lower, faces.ravel(), fans)
    np.maximum.at(upper, faces.ravel(), fans)
    singular = lower != upper
    safe[components[singular]] = False

    bounds = np.empty((component_count, 2, 3))
    bounds[:, 0] = np.inf
    bounds[:, 1] = -np.inf
    np.minimum.at(bounds[:, 0], components, vertices)
    np.maximum.at(bounds[:, 1], components, vertices)
    protected = np.zeros(len(vertices), dtype=bool)
    unit = np.divide(normals, lengths[:, None], out=np.zeros_like(normals), where=lengths[:, None] > 0)
    sharp = np.einsum("ij,ij->i", unit[first // 3], unit[last // 3]) < math.cos(math.radians(35))
    protected[edges[sharp | bad_edges].ravel()] = True
    # Keep the entire one-ring of a pinched vertex exact. The remainder of a
    # large surface can still simplify without modifying the singularity.
    protected[singular] = True
    protected[edges[np.any(singular[edges], axis=1)].ravel()] = True
    arrays = (vertices, faces, normals, edges, first, last, counts, components,
              face_components, safe, contour_safe, bounds, protected, singular)
    for array in arrays:
        array.setflags(write=False)
    check_cancel(event)
    return MeshTopology(triangles, *arrays)


def _component_gap(bounds, index):
    """AABB separation is a conservative lower bound on surface distance.

    Overlapping boxes remain unreduced, including nested shells. This avoids
    an expensive nearest-triangle search and never invents object membership.
    """
    if len(bounds) == 1:
        return math.inf
    separation = np.maximum(np.maximum(bounds[index, 0] - bounds[:, 1],
                                        bounds[:, 0] - bounds[index, 1]), 0)
    distance = np.linalg.norm(separation, axis=1)
    distance[index] = math.inf
    return float(distance.min())


def _reduce_component(source, preference, gap, event, topology=None):
    if topology is None:
        topology = build_mesh_topology(source, event)
    vertices, faces = topology.vertices, topology.faces
    if not topology.reliable_contours:
        return source
    extent = np.ptp(vertices, axis=0)
    diagonal = float(np.linalg.norm(extent))
    quality = preference / 100
    # Dense sources have an absolute display budget rather than a percentage
    # of their original faces. Small sources bypass this entirely.
    error = min(diagonal * (.020 - .013 * quality), float(extent.min()) * .06, gap * .20)
    if not error > 0:
        return source
    target = round(4000 + 12000 * quality)
    if len(source) <= target / (1 - MINIMUM_FACE_SAVING):
        return source
    area = np.linalg.norm(topology.normals, axis=1).sum() / 2
    size = min(math.sqrt(area / target), error * 2 / math.sqrt(3))
    source_euler = len(vertices) - len(topology.edges) + len(faces)
    protected = topology.protected_vertices.copy()
    original_singular = vertices[topology.singular_vertices]
    original_area = area
    for _ in range(16):
        check_cancel(event)
        cells = np.floor((vertices - vertices.min(axis=0)) / size).astype(np.int64)
        _, groups = np.unique(cells, axis=0, return_inverse=True)
        # Sharp features stay exact. Only originally connected vertices may
        # share a cluster, so nearby opposite walls cannot be welded together.
        groups[protected] = groups.max() + 1 + np.arange(protected.sum())
        inside = topology.edges[groups[topology.edges[:, 0]] == groups[topology.edges[:, 1]]]
        roots = connected_labels(len(vertices), inside, event)
        _, groups = np.unique(roots, return_inverse=True)
        counts = np.bincount(groups)
        reduced = np.column_stack([np.bincount(groups, weights=vertices[:, axis]) / counts for axis in range(3)])
        mapped = groups[faces]
        valid = (mapped[:, 0] != mapped[:, 1]) & (mapped[:, 1] != mapped[:, 2]) & (mapped[:, 2] != mapped[:, 0])
        candidate = reduced[mapped[valid]]
        if len(candidate) > len(source) * (1 - MINIMUM_FACE_SAVING):
            if np.array_equal(protected, topology.protected_vertices):
                return source
            # A coarse grid can force too many local locks. Restart finer
            # rather than carrying those locks into an unchanged full mesh.
            protected = topology.protected_vertices.copy()
            size *= .7
            continue
        displacement = np.linalg.norm(reduced[groups] - vertices, axis=1)
        bad_groups = np.zeros(len(reduced), dtype=bool)
        bad_groups[groups[displacement > error]] = True
        if len(candidate):
            candidate_normals = np.cross(candidate[:, 1] - candidate[:, 0], candidate[:, 2] - candidate[:, 0])
            old_normals = topology.normals[valid]
            products = np.linalg.norm(old_normals, axis=1) * np.linalg.norm(candidate_normals, axis=1)
            dot = np.einsum("ij,ij->i", old_normals, candidate_normals)
            # Sub-error facets carry fine surface texture, not a hard shape
            # constraint. Their normals may vary more, but never invert.
            fine = np.linalg.norm(old_normals, axis=1) < error * error
            aligned = (products > 1e-15) & (dot > 0) & (
                fine | (dot >= products * math.cos(math.radians(35))))
            bad_groups[mapped[valid][~aligned].ravel()] = True
            new_area = np.linalg.norm(candidate_normals, axis=1).sum() / 2
            if not bad_groups.any() and .95 * original_area <= new_area <= 1.05 * original_area:
                checked = build_mesh_topology(candidate, event)
                euler = len(checked.vertices) - len(checked.edges) + len(checked.faces)
                same_singular = np.array_equal(checked.vertices[checked.singular_vertices], original_singular)
                if checked.reliable_contours and len(checked.safe_components) == 1 and euler == source_euler and same_singular:
                    candidate.setflags(write=False)
                    return candidate
                # Refine only newly unsafe neighborhoods, not the entire mesh.
                unsafe = checked.singular_vertices.copy()
                if len(original_singular):
                    _, singular_ids = np.unique(np.concatenate((checked.vertices, original_singular)),
                                                axis=0, return_inverse=True)
                    unsafe &= ~np.isin(singular_ids[:len(checked.vertices)], singular_ids[len(checked.vertices):])
                unsafe[checked.edges[checked.counts != 2].ravel()] = True
                if unsafe.any():
                    coordinates = checked.vertices[unsafe]
                    _, indices = np.unique(np.concatenate((reduced, coordinates)), axis=0, return_inverse=True)
                    bad_groups = np.isin(indices[:len(reduced)], indices[len(reduced):])
        newly_protected = bad_groups[groups] & ~protected
        if newly_protected.any():
            protected |= newly_protected
        else:
            protected = topology.protected_vertices.copy()
            size *= .7
    return source


def simplify_display_mesh(triangles, percent, event=None, *, topology=None):
    """Choose a useful reduction within hard geometric and topology bounds."""
    check_cancel(event)
    if percent <= 0 or len(triangles) <= SMALL_MESH_FACES:
        return triangles
    if topology is None or topology.source is not triangles:
        topology = build_mesh_topology(triangles, event)
    with topology._cache_lock:
        cached = topology._cache.get(percent)
        if cached is not None:
            topology._cache.move_to_end(percent)
            return cached
    result = triangles
    component_count = len(topology.safe_components)
    if component_count <= MAXIMUM_COMPONENTS_FOR_REDUCTION:
        order = np.argsort(topology.face_components, kind="stable")
        counts = np.bincount(topology.face_components, minlength=component_count)
        pieces = []
        changed = False
        offset = 0
        for index, count in enumerate(counts):
            check_cancel(event)
            indices = order[offset:offset + count]
            offset += count
            source = triangles if component_count == 1 else triangles[indices]
            candidate = source
            if count > SMALL_MESH_FACES and topology.contour_components[index]:
                candidate = _reduce_component(source, percent, _component_gap(topology.bounds, index), event,
                                              topology if component_count == 1 else None)
            pieces.append(candidate)
            changed |= candidate is not source
        if changed:
            result = np.concatenate(pieces)
            result.setflags(write=False)
    check_cancel(event)
    with topology._cache_lock:
        topology._cache[percent] = result
        while len(topology._cache) > 8:
            topology._cache.popitem(last=False)
    return result
