from __future__ import annotations

import math
import struct
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from cooling_tower.write_policy import ensure_writable_output

from cooling_tower.tower.profile import StableTowerProfile
from cooling_tower.tower.hollow_profile import HollowTowerProfile
from cooling_tower.tower.solid_profile import SolidTowerProfile


Vector3 = tuple[float, float, float]
Triangle = tuple[int, int, int]

GEOMETRY_EPSILON = 1e-12
Z_EPSILON_MM = 1e-9


class MeshGenerationError(ValueError):
    """Raised when a valid tower mesh or STL cannot be generated."""


@dataclass(frozen=True, slots=True)
class TowerMeshConfig:
    segment_count: int = 32


def automatic_mesh_segments(profile: object) -> int:
    """Use 0.9 segments/mm per candidate to keep every STL ring watertight."""
    radii = [
        float(
            getattr(point, "outer_radius_mm", getattr(point, "radius_mm", math.nan))
        )
        for point in profile.points
    ]
    if not radii or any(not math.isfinite(radius) or radius <= 0 for radius in radii):
        raise MeshGenerationError("The tower profile needs finite positive radii.")
    return max(16, min(128, math.ceil(1.8 * max(radii))))


@dataclass(frozen=True, slots=True)
class TriangleMesh:
    vertices: tuple[Vector3, ...]
    faces: tuple[Triangle, ...]
    ring_count: int
    segment_count: int


@dataclass(frozen=True, slots=True)
class MeshValidation:
    vertex_count: int
    face_count: int

    invalid_index_face_count: int
    degenerate_face_count: int
    boundary_edge_count: int
    non_manifold_edge_count: int
    inconsistent_winding_edge_count: int

    surface_area_mm2: float
    signed_volume_mm3: float

    minimum_x_mm: float | None
    maximum_x_mm: float | None
    minimum_y_mm: float | None
    maximum_y_mm: float | None
    minimum_z_mm: float | None
    maximum_z_mm: float | None

    @property
    def is_watertight(self) -> bool:
        return (
            self.invalid_index_face_count == 0
            and self.degenerate_face_count == 0
            and self.boundary_edge_count == 0
            and self.non_manifold_edge_count == 0
        )

    @property
    def has_consistent_winding(self) -> bool:
        return self.inconsistent_winding_edge_count == 0

    @property
    def has_outward_orientation(self) -> bool:
        return self.signed_volume_mm3 > GEOMETRY_EPSILON

    @property
    def is_valid(self) -> bool:
        return (
            self.is_watertight
            and self.has_consistent_winding
            and self.has_outward_orientation
        )


@dataclass(frozen=True, slots=True)
class StlExportResult:
    output_path: Path
    file_size_bytes: int
    validation: MeshValidation


def validate_mesh_config(config: TowerMeshConfig) -> None:
    if isinstance(config.segment_count, bool):
        raise MeshGenerationError(
            "The mesh segment count must be an integer."
        )

    if not isinstance(config.segment_count, int):
        raise MeshGenerationError(
            "The mesh segment count must be an integer."
        )

    if config.segment_count < 3:
        raise MeshGenerationError(
            "The mesh segment count must be at least 3."
        )


def _validate_stable_profile(profile: StableTowerProfile) -> None:
    if len(profile.points) < 2:
        raise MeshGenerationError(
            "At least two stable profile points are required."
        )

    if abs(profile.points[0].z_mm) > Z_EPSILON_MM:
        raise MeshGenerationError(
            "The first stable profile point must be located at Z=0."
        )

    previous_z: float | None = None
    previous_radius: float | None = None

    for point in profile.points:
        if not math.isfinite(point.z_mm):
            raise MeshGenerationError(
                "All stable profile Z positions must be finite."
            )

        if point.z_mm < 0.0:
            raise MeshGenerationError(
                "Stable profile Z positions must not be negative."
            )

        if (
            previous_z is not None
            and point.z_mm <= previous_z + Z_EPSILON_MM
        ):
            inward_solid_step = (
                isinstance(profile, SolidTowerProfile)
                and profile.settings.simulate_full_tower_infill
                and point.z_mm == previous_z
                and previous_z > 0.0
                and previous_radius is not None
                and point.radius_mm < previous_radius - Z_EPSILON_MM
                and point.source == "inward_step"
            )
            if not inward_solid_step:
                raise MeshGenerationError(
                    "Profile heights must increase except at supported inward solid steps."
                )

        if (
            not math.isfinite(point.radius_mm)
            or point.radius_mm <= 0.0
        ):
            raise MeshGenerationError(
                "All stable profile radii must be finite and greater "
                "than zero."
            )

        previous_z = point.z_mm
        previous_radius = point.radius_mm


def generate_tower_mesh(
    profile: StableTowerProfile,
    config: TowerMeshConfig,
) -> TriangleMesh:
    """Generate a closed rotational mesh from all stable profile points."""
    validate_mesh_config(config)
    _validate_stable_profile(profile)

    segment_count = config.segment_count
    vertices: list[Vector3] = []

    for point in profile.points:
        for segment in range(segment_count):
            angle = math.tau * segment / segment_count
            vertices.append(
                (
                    point.radius_mm * math.cos(angle),
                    point.radius_mm * math.sin(angle),
                    point.z_mm,
                )
            )

    ring_count = len(profile.points)
    faces: list[Triangle] = []

    for ring in range(ring_count - 1):
        lower_start = ring * segment_count
        upper_start = (ring + 1) * segment_count

        for segment in range(segment_count):
            next_segment = (segment + 1) % segment_count

            lower_current = lower_start + segment
            lower_next = lower_start + next_segment
            upper_current = upper_start + segment
            upper_next = upper_start + next_segment

            faces.append(
                (
                    lower_current,
                    lower_next,
                    upper_next,
                )
            )
            faces.append(
                (
                    lower_current,
                    upper_next,
                    upper_current,
                )
            )

    bottom_center_index = len(vertices)
    vertices.append((0.0, 0.0, profile.points[0].z_mm))

    top_center_index = len(vertices)
    vertices.append((0.0, 0.0, profile.points[-1].z_mm))

    top_ring_start = (ring_count - 1) * segment_count

    for segment in range(segment_count):
        next_segment = (segment + 1) % segment_count

        faces.append(
            (
                bottom_center_index,
                next_segment,
                segment,
            )
        )
        faces.append(
            (
                top_center_index,
                top_ring_start + segment,
                top_ring_start + next_segment,
            )
        )

    return TriangleMesh(
        vertices=tuple(vertices),
        faces=tuple(faces),
        ring_count=ring_count,
        segment_count=segment_count,
    )


def generate_solid_tower_mesh(
    profile: SolidTowerProfile,
    config: TowerMeshConfig,
) -> TriangleMesh:
    """Generate the closed rotational mesh for a cavity-free tower."""

    return generate_tower_mesh(profile, config)  # type: ignore[arg-type]


def generate_hollow_tower_mesh(
    profile: HollowTowerProfile,
    config: TowerMeshConfig,
) -> TriangleMesh:
    """Generate a closed shell with outer wall, inner wall and annular caps."""
    validate_mesh_config(config)
    if len(profile.points) < 2:
        raise MeshGenerationError(
            "A hollow mesh requires at least two profile points."
        )

    previous_z: float | None = None
    for point in profile.points:
        if not all(
            math.isfinite(value)
            for value in (
                point.z_mm,
                point.outer_radius_mm,
                point.inner_radius_mm,
                point.wall_thickness_mm,
            )
        ):
            raise MeshGenerationError(
                "Hollow profile coordinates must be finite."
            )
        if point.inner_radius_mm <= 0.0:
            raise MeshGenerationError(
                "Every hollow profile point needs a positive inner radius."
            )
        if point.outer_radius_mm <= point.inner_radius_mm:
            raise MeshGenerationError(
                "Outer radii must be greater than inner radii."
            )
        if previous_z is not None and point.z_mm <= previous_z + Z_EPSILON_MM:
            raise MeshGenerationError(
                "Hollow profile heights must be strictly increasing."
            )
        previous_z = point.z_mm

    segments = config.segment_count
    vertices: list[Vector3] = []
    for point in profile.points:
        for radius in (point.outer_radius_mm, point.inner_radius_mm):
            for segment in range(segments):
                angle = math.tau * segment / segments
                vertices.append(
                    (
                        radius * math.cos(angle),
                        radius * math.sin(angle),
                        point.z_mm,
                    )
                )

    faces: list[Triangle] = []
    stride = segments * 2
    for ring in range(len(profile.points) - 1):
        lower_outer = ring * stride
        lower_inner = lower_outer + segments
        upper_outer = (ring + 1) * stride
        upper_inner = upper_outer + segments
        for segment in range(segments):
            next_segment = (segment + 1) % segments
            # Outer surface: normals point away from the rotation axis.
            faces.extend(
                (
                    (
                        lower_outer + segment,
                        lower_outer + next_segment,
                        upper_outer + next_segment,
                    ),
                    (
                        lower_outer + segment,
                        upper_outer + next_segment,
                        upper_outer + segment,
                    ),
                )
            )
            # Inner surface: winding is reversed, so normals face the cavity.
            faces.extend(
                (
                    (
                        lower_inner + segment,
                        upper_inner + next_segment,
                        lower_inner + next_segment,
                    ),
                    (
                        lower_inner + segment,
                        upper_inner + segment,
                        upper_inner + next_segment,
                    ),
                )
            )

    bottom_outer = 0
    bottom_inner = segments
    top_outer = (len(profile.points) - 1) * stride
    top_inner = top_outer + segments
    for segment in range(segments):
        next_segment = (segment + 1) % segments
        # Bottom annulus points down.
        faces.extend(
            (
                (
                    bottom_outer + segment,
                    bottom_inner + next_segment,
                    bottom_outer + next_segment,
                ),
                (
                    bottom_outer + segment,
                    bottom_inner + segment,
                    bottom_inner + next_segment,
                ),
            )
        )
        # Top annulus points up.
        faces.extend(
            (
                (
                    top_outer + segment,
                    top_outer + next_segment,
                    top_inner + next_segment,
                ),
                (
                    top_outer + segment,
                    top_inner + next_segment,
                    top_inner + segment,
                ),
            )
        )

    mesh = TriangleMesh(
        vertices=tuple(vertices),
        faces=tuple(faces),
        ring_count=len(profile.points),
        segment_count=segments,
    )
    validation = validate_triangle_mesh(mesh)
    if not validation.is_valid:
        raise MeshGenerationError(
            "The generated hollow mesh is not watertight, consistently "
            "wound and outward oriented."
        )
    return mesh


def _subtract(first: Vector3, second: Vector3) -> Vector3:
    return (
        first[0] - second[0],
        first[1] - second[1],
        first[2] - second[2],
    )


def _cross(first: Vector3, second: Vector3) -> Vector3:
    return (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )


def _dot(first: Vector3, second: Vector3) -> float:
    return (
        first[0] * second[0]
        + first[1] * second[1]
        + first[2] * second[2]
    )


def _length(vector: Vector3) -> float:
    return math.sqrt(_dot(vector, vector))


def calculate_face_normal(
    first: Vector3,
    second: Vector3,
    third: Vector3,
) -> Vector3:
    """Return a normalized triangle normal following vertex winding."""
    first_edge = _subtract(second, first)
    second_edge = _subtract(third, first)
    normal = _cross(first_edge, second_edge)
    normal_length = _length(normal)

    if normal_length <= GEOMETRY_EPSILON:
        raise MeshGenerationError(
            "A triangle is degenerate and has no usable normal."
        )

    return (
        normal[0] / normal_length,
        normal[1] / normal_length,
        normal[2] / normal_length,
    )


def validate_triangle_mesh(mesh: TriangleMesh) -> MeshValidation:
    """Validate topology, winding, area, volume, and mesh bounds."""
    vertex_count = len(mesh.vertices)
    face_count = len(mesh.faces)

    invalid_index_face_count = 0
    degenerate_face_count = 0
    surface_area_mm2 = 0.0
    signed_volume_mm3 = 0.0

    edge_occurrences: dict[
        tuple[int, int],
        list[tuple[int, int]],
    ] = defaultdict(list)

    for face in mesh.faces:
        if (
            len(set(face)) != 3
            or any(index < 0 or index >= vertex_count for index in face)
        ):
            invalid_index_face_count += 1
            continue

        first = mesh.vertices[face[0]]
        second = mesh.vertices[face[1]]
        third = mesh.vertices[face[2]]

        first_edge = _subtract(second, first)
        second_edge = _subtract(third, first)
        cross_product = _cross(first_edge, second_edge)
        double_area = _length(cross_product)

        if double_area <= GEOMETRY_EPSILON:
            degenerate_face_count += 1
        else:
            surface_area_mm2 += double_area / 2.0

        signed_volume_mm3 += (
            _dot(first, _cross(second, third)) / 6.0
        )

        directed_edges = (
            (face[0], face[1]),
            (face[1], face[2]),
            (face[2], face[0]),
        )

        for directed_edge in directed_edges:
            undirected_edge = tuple(sorted(directed_edge))
            edge_occurrences[undirected_edge].append(
                directed_edge
            )

    boundary_edge_count = sum(
        len(occurrences) == 1
        for occurrences in edge_occurrences.values()
    )
    non_manifold_edge_count = sum(
        len(occurrences) > 2
        for occurrences in edge_occurrences.values()
    )
    inconsistent_winding_edge_count = 0

    for occurrences in edge_occurrences.values():
        if len(occurrences) != 2:
            continue

        first, second = occurrences

        if first != (second[1], second[0]):
            inconsistent_winding_edge_count += 1

    if mesh.vertices:
        x_values = [vertex[0] for vertex in mesh.vertices]
        y_values = [vertex[1] for vertex in mesh.vertices]
        z_values = [vertex[2] for vertex in mesh.vertices]

        minimum_x_mm: float | None = min(x_values)
        maximum_x_mm: float | None = max(x_values)
        minimum_y_mm: float | None = min(y_values)
        maximum_y_mm: float | None = max(y_values)
        minimum_z_mm: float | None = min(z_values)
        maximum_z_mm: float | None = max(z_values)
    else:
        minimum_x_mm = None
        maximum_x_mm = None
        minimum_y_mm = None
        maximum_y_mm = None
        minimum_z_mm = None
        maximum_z_mm = None

    return MeshValidation(
        vertex_count=vertex_count,
        face_count=face_count,

        invalid_index_face_count=invalid_index_face_count,
        degenerate_face_count=degenerate_face_count,
        boundary_edge_count=boundary_edge_count,
        non_manifold_edge_count=non_manifold_edge_count,
        inconsistent_winding_edge_count=(
            inconsistent_winding_edge_count
        ),

        surface_area_mm2=surface_area_mm2,
        signed_volume_mm3=signed_volume_mm3,

        minimum_x_mm=minimum_x_mm,
        maximum_x_mm=maximum_x_mm,
        minimum_y_mm=minimum_y_mm,
        maximum_y_mm=maximum_y_mm,
        minimum_z_mm=minimum_z_mm,
        maximum_z_mm=maximum_z_mm,
    )


def write_binary_stl(
    mesh: TriangleMesh,
    output_path: str | Path,
) -> StlExportResult:
    """Validate and write a binary STL with explicit face normals."""
    validation = validate_triangle_mesh(mesh)

    if not validation.is_valid:
        raise MeshGenerationError(
            "The mesh is not a valid, consistently oriented, watertight "
            "solid and cannot be exported."
        )

    path = ensure_writable_output(output_path)

    if path.exists() and path.is_dir():
        raise IsADirectoryError(
            f"The STL output path is a directory: {path}"
        )

    path.parent.mkdir(parents=True, exist_ok=True)

    header_text = (
        "Dynamic cooling tower generated by cooling_tower"
    )
    header = header_text.encode("ascii")[:80].ljust(80, b"\0")

    with path.open(mode="wb") as stl_file:
        stl_file.write(header)
        stl_file.write(struct.pack("<I", len(mesh.faces)))

        for face in mesh.faces:
            first = mesh.vertices[face[0]]
            second = mesh.vertices[face[1]]
            third = mesh.vertices[face[2]]
            normal = calculate_face_normal(first, second, third)

            stl_file.write(
                struct.pack(
                    "<12fH",
                    normal[0],
                    normal[1],
                    normal[2],
                    first[0],
                    first[1],
                    first[2],
                    second[0],
                    second[1],
                    second[2],
                    third[0],
                    third[1],
                    third[2],
                    0,
                )
            )

    resolved_path = path.resolve()

    return StlExportResult(
        output_path=resolved_path,
        file_size_bytes=resolved_path.stat().st_size,
        validation=validation,
    )
