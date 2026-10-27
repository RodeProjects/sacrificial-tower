from __future__ import annotations

import math
import random
import subprocess
import struct
import sys
import tempfile
import unittest
from collections import Counter
from dataclasses import replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from stl_generator import (
    MeshGenerationError,
    TowerMeshConfig,
    TriangleMesh,
    calculate_face_normal,
    generate_tower_mesh,
    validate_triangle_mesh,
    write_binary_stl,
)
from test_phase3 import make_phase2_profile
from tower_generator import (
    StabilityProfileConfig,
    build_stable_tower_profile,
)


def make_stable_profile(
    z_positions: tuple[float, ...] = (1.0, 10.0),
    radii: tuple[float, ...] = (5.0, 5.0),
    *,
    base_height_mm: float = 1.0,
    maximum_radius_change_per_mm_z: float = 100.0,
):
    phase2 = make_phase2_profile(
        z_positions,
        radii,
        minimum_radius_mm=min(radii),
    )

    return build_stable_tower_profile(
        phase2,
        StabilityProfileConfig(
            minimum_radius_height_factor=0.0,
            minimum_base_radius_mm=min(radii),
            base_height_factor=0.0,
            base_margin_mm=0.0,
            base_height_mm=base_height_mm,
            maximum_radius_change_per_mm_z=(
                maximum_radius_change_per_mm_z
            ),
        ),
    )


class TowerMeshGenerationTests(unittest.TestCase):
    def test_cylinder_counts_bounds_topology_and_volume(self) -> None:
        profile = make_stable_profile()
        mesh = generate_tower_mesh(
            profile,
            TowerMeshConfig(segment_count=8),
        )
        validation = validate_triangle_mesh(mesh)

        expected_ring_count = len(profile.points)
        expected_vertices = expected_ring_count * 8 + 2
        expected_faces = (expected_ring_count - 1) * 8 * 2 + 16

        self.assertEqual(mesh.ring_count, expected_ring_count)
        self.assertEqual(len(mesh.vertices), expected_vertices)
        self.assertEqual(len(mesh.faces), expected_faces)
        self.assertTrue(validation.is_valid)
        self.assertTrue(validation.is_watertight)
        self.assertTrue(validation.has_consistent_winding)
        self.assertTrue(validation.has_outward_orientation)
        self.assertEqual(validation.boundary_edge_count, 0)
        self.assertEqual(validation.non_manifold_edge_count, 0)
        self.assertEqual(validation.degenerate_face_count, 0)

        polygon_area = (
            8 / 2.0 * 5.0**2 * math.sin(math.tau / 8)
        )
        self.assertAlmostEqual(
            validation.signed_volume_mm3,
            polygon_area * 10.0,
        )
        self.assertAlmostEqual(validation.minimum_x_mm, -5.0)
        self.assertAlmostEqual(validation.maximum_x_mm, 5.0)
        self.assertAlmostEqual(validation.minimum_y_mm, -5.0)
        self.assertAlmostEqual(validation.maximum_y_mm, 5.0)
        self.assertEqual(validation.minimum_z_mm, 0.0)
        self.assertEqual(validation.maximum_z_mm, 10.0)

    def test_ring_vertices_follow_every_profile_support_point(self) -> None:
        profile = make_stable_profile(
            (0.2, 1.0, 2.5, 7.0),
            (6.0, 8.0, 5.0, 10.0),
            base_height_mm=0.5,
            maximum_radius_change_per_mm_z=10.0,
        )
        segment_count = 12
        mesh = generate_tower_mesh(
            profile,
            TowerMeshConfig(segment_count=segment_count),
        )

        self.assertEqual(mesh.ring_count, len(profile.points))

        for ring_index, point in enumerate(profile.points):
            ring_start = ring_index * segment_count
            ring_vertices = mesh.vertices[
                ring_start:ring_start + segment_count
            ]

            self.assertTrue(
                all(vertex[2] == point.z_mm for vertex in ring_vertices)
            )
            self.assertTrue(
                all(
                    math.isclose(
                        math.hypot(vertex[0], vertex[1]),
                        point.radius_mm,
                        rel_tol=1e-12,
                        abs_tol=1e-12,
                    )
                    for vertex in ring_vertices
                )
            )

    def test_side_bottom_and_top_normals_point_outward(self) -> None:
        profile = make_stable_profile(
            (1.0, 5.0, 10.0),
            (8.0, 5.0, 10.0),
            base_height_mm=1.0,
            maximum_radius_change_per_mm_z=10.0,
        )
        segment_count = 16
        mesh = generate_tower_mesh(
            profile,
            TowerMeshConfig(segment_count=segment_count),
        )

        first_side_face = mesh.faces[0]
        side_vertices = tuple(
            mesh.vertices[index] for index in first_side_face
        )
        side_normal = calculate_face_normal(*side_vertices)
        side_centroid = (
            sum(vertex[0] for vertex in side_vertices) / 3.0,
            sum(vertex[1] for vertex in side_vertices) / 3.0,
        )

        self.assertGreater(
            side_normal[0] * side_centroid[0]
            + side_normal[1] * side_centroid[1],
            0.0,
        )

        side_face_count = (
            (mesh.ring_count - 1) * segment_count * 2
        )
        bottom_face = mesh.faces[side_face_count]
        top_face = mesh.faces[side_face_count + 1]

        bottom_normal = calculate_face_normal(
            *(mesh.vertices[index] for index in bottom_face)
        )
        top_normal = calculate_face_normal(
            *(mesh.vertices[index] for index in top_face)
        )

        self.assertAlmostEqual(bottom_normal[2], -1.0)
        self.assertAlmostEqual(top_normal[2], 1.0)

    def test_segment_configuration_is_validated(self) -> None:
        profile = make_stable_profile()

        for invalid_segment_count in (True, 2, 0, -1, 3.5):
            with self.subTest(segment_count=invalid_segment_count):
                with self.assertRaises(MeshGenerationError):
                    generate_tower_mesh(
                        profile,
                        TowerMeshConfig(
                            segment_count=invalid_segment_count
                        ),
                    )

        mesh = generate_tower_mesh(
            profile,
            TowerMeshConfig(segment_count=3),
        )
        self.assertTrue(validate_triangle_mesh(mesh).is_valid)

    def test_invalid_stable_profile_is_rejected(self) -> None:
        profile = make_stable_profile()

        no_bottom_profile = replace(
            profile,
            points=profile.points[1:],
        )
        duplicate_z_profile = replace(
            profile,
            points=(
                profile.points[0],
                replace(profile.points[1], z_mm=0.0),
                *profile.points[2:],
            ),
        )
        zero_radius_profile = replace(
            profile,
            points=(
                replace(profile.points[0], radius_mm=0.0),
                *profile.points[1:],
            ),
        )

        for invalid_profile in (
            no_bottom_profile,
            duplicate_z_profile,
            zero_radius_profile,
        ):
            with self.subTest(profile=invalid_profile):
                with self.assertRaises(MeshGenerationError):
                    generate_tower_mesh(
                        invalid_profile,
                        TowerMeshConfig(),
                    )

    def test_validator_detects_open_inconsistent_and_nonmanifold_meshes(
        self,
    ) -> None:
        mesh = generate_tower_mesh(
            make_stable_profile(),
            TowerMeshConfig(segment_count=8),
        )
        cap_face_count = 16

        open_mesh = replace(
            mesh,
            faces=mesh.faces[:-cap_face_count],
        )
        open_validation = validate_triangle_mesh(open_mesh)
        self.assertFalse(open_validation.is_watertight)
        self.assertGreater(open_validation.boundary_edge_count, 0)

        reversed_face = tuple(reversed(mesh.faces[0]))
        inconsistent_mesh = replace(
            mesh,
            faces=(reversed_face, *mesh.faces[1:]),
        )
        inconsistent_validation = validate_triangle_mesh(
            inconsistent_mesh
        )
        self.assertFalse(
            inconsistent_validation.has_consistent_winding
        )
        self.assertGreater(
            inconsistent_validation.inconsistent_winding_edge_count,
            0,
        )

        nonmanifold_mesh = replace(
            mesh,
            faces=(*mesh.faces, mesh.faces[0]),
        )
        nonmanifold_validation = validate_triangle_mesh(
            nonmanifold_mesh
        )
        self.assertFalse(nonmanifold_validation.is_watertight)
        self.assertGreater(
            nonmanifold_validation.non_manifold_edge_count,
            0,
        )

    def test_validator_detects_degenerate_triangle(self) -> None:
        mesh = generate_tower_mesh(
            make_stable_profile(),
            TowerMeshConfig(segment_count=8),
        )
        bottom_center_index = len(mesh.vertices) - 2
        degenerate_face = (bottom_center_index, 0, 4)
        invalid_mesh = replace(
            mesh,
            faces=(*mesh.faces, degenerate_face),
        )

        validation = validate_triangle_mesh(invalid_mesh)

        self.assertGreater(validation.degenerate_face_count, 0)
        self.assertFalse(validation.is_valid)

    def test_deterministic_random_profiles_always_form_valid_solids(
        self,
    ) -> None:
        random_source = random.Random(20260714)

        for profile_number in range(50):
            layer_count = random_source.randint(2, 25)
            current_z = 0.0
            z_positions: list[float] = []

            for _ in range(layer_count):
                current_z += random_source.uniform(0.05, 1.5)
                z_positions.append(current_z)

            radii = tuple(
                random_source.uniform(3.0, 30.0)
                for _ in range(layer_count)
            )
            profile = make_stable_profile(
                tuple(z_positions),
                radii,
                base_height_mm=random_source.uniform(0.1, 3.0),
                maximum_radius_change_per_mm_z=(
                    random_source.uniform(0.2, 5.0)
                ),
            )
            segment_count = random_source.choice((3, 8, 16, 32, 48))

            with self.subTest(profile_number=profile_number):
                mesh = generate_tower_mesh(
                    profile,
                    TowerMeshConfig(segment_count=segment_count),
                )
                validation = validate_triangle_mesh(mesh)

                self.assertTrue(validation.is_valid)
                self.assertEqual(
                    len(mesh.vertices),
                    len(profile.points) * segment_count + 2,
                )
                self.assertEqual(
                    len(mesh.faces),
                    (len(profile.points) - 1)
                    * segment_count
                    * 2
                    + segment_count
                    * 2,
                )


class BinaryStlExportTests(unittest.TestCase):
    def test_binary_stl_size_header_count_and_normals(self) -> None:
        mesh = generate_tower_mesh(
            make_stable_profile(),
            TowerMeshConfig(segment_count=8),
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "tower.stl"
            result = write_binary_stl(mesh, output_path)
            data = output_path.read_bytes()

        expected_size = 84 + len(mesh.faces) * 50

        self.assertEqual(result.file_size_bytes, expected_size)
        self.assertEqual(len(data), expected_size)
        self.assertTrue(
            data[:80].rstrip(b"\0").startswith(
                b"Dynamic cooling tower"
            )
        )
        self.assertEqual(struct.unpack("<I", data[80:84])[0], len(mesh.faces))
        first_normal = struct.unpack("<3f", data[84:96])
        self.assertGreater(math.sqrt(sum(value**2 for value in first_normal)), 0.999)
        self.assertTrue(result.validation.is_valid)

    def test_binary_stl_roundtrip_has_closed_edges_and_matching_normals(
        self,
    ) -> None:
        mesh = generate_tower_mesh(
            make_stable_profile(
                (0.5, 2.0, 5.0),
                (6.0, 10.0, 4.0),
                base_height_mm=0.5,
                maximum_radius_change_per_mm_z=10.0,
            ),
            TowerMeshConfig(segment_count=16),
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "roundtrip.stl"
            write_binary_stl(mesh, output_path)
            data = output_path.read_bytes()

        triangle_count = struct.unpack("<I", data[80:84])[0]
        edge_counts: Counter[
            tuple[tuple[float, float, float], tuple[float, float, float]]
        ] = Counter()
        signed_volume = 0.0

        for triangle_index in range(triangle_count):
            offset = 84 + triangle_index * 50
            unpacked = struct.unpack(
                "<12fH",
                data[offset:offset + 50],
            )
            stored_normal = unpacked[0:3]
            vertices = (
                unpacked[3:6],
                unpacked[6:9],
                unpacked[9:12],
            )
            calculated_normal = calculate_face_normal(*vertices)
            normal_alignment = sum(
                first * second
                for first, second in zip(
                    stored_normal,
                    calculated_normal,
                    strict=True,
                )
            )
            self.assertGreater(normal_alignment, 0.99999)

            for start, end in (
                (vertices[0], vertices[1]),
                (vertices[1], vertices[2]),
                (vertices[2], vertices[0]),
            ):
                edge_counts[tuple(sorted((start, end)))] += 1

            first, second, third = vertices
            cross = (
                second[1] * third[2] - second[2] * third[1],
                second[2] * third[0] - second[0] * third[2],
                second[0] * third[1] - second[1] * third[0],
            )
            signed_volume += sum(
                first[axis] * cross[axis]
                for axis in range(3)
            ) / 6.0

        self.assertEqual(triangle_count, len(mesh.faces))
        self.assertTrue(edge_counts)
        self.assertTrue(
            all(count == 2 for count in edge_counts.values())
        )
        self.assertGreater(signed_volume, 0.0)

    def test_export_creates_parent_directory(self) -> None:
        mesh = generate_tower_mesh(
            make_stable_profile(),
            TowerMeshConfig(segment_count=8),
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = (
                Path(temporary_directory)
                / "nested"
                / "tower.stl"
            )
            result = write_binary_stl(mesh, output_path)

            self.assertTrue(output_path.is_file())
            self.assertEqual(result.output_path, output_path.resolve())

    def test_export_refuses_invalid_mesh(self) -> None:
        mesh = generate_tower_mesh(
            make_stable_profile(),
            TowerMeshConfig(segment_count=8),
        )
        invalid_mesh = replace(mesh, faces=mesh.faces[:-16])

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "invalid.stl"

            with self.assertRaises(MeshGenerationError):
                write_binary_stl(invalid_mesh, output_path)

            self.assertFalse(output_path.exists())


class Phase4CliTests(unittest.TestCase):
    def test_cli_generates_valid_binary_stl_end_to_end(self) -> None:
        gcode = "\n".join(
            (
                "G90",
                "M83",
                "G1 Z0.2 F600",
                "G1 X10 E1 F600",
                "G1 Z1.0 F600",
                "G1 X20 E1 F600",
                "G1 Z2.0 F600",
                "G1 X30 E1 F600",
            )
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            gcode_path = temporary_path / "model.gcode"
            csv_path = temporary_path / "analysis.csv"
            stl_path = temporary_path / "tower.stl"
            gcode_path.write_text(gcode, encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(PROJECT_ROOT / "main.py"),
                    "--gcode",
                    str(gcode_path),
                    "--target-time",
                    "5",
                    "--minimum-radius",
                    "2",
                    "--maximum-radius",
                    "20",
                    "--base-height",
                    "0.5",
                    "--maximum-radius-change",
                    "2",
                    "--local-window",
                    "3",
                    "--output-stl",
                    str(stl_path),
                    "--preview",
                    "0",
                    "--csv",
                    str(csv_path),
                ],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Phase-4 mesh and STL export", result.stdout)
            self.assertIn("Watertight:                         yes", result.stdout)
            self.assertIn("Consistent winding:                 yes", result.stdout)
            self.assertIn("Outward orientation:                yes", result.stdout)
            self.assertTrue(stl_path.is_file())
            self.assertTrue(csv_path.is_file())

            data = stl_path.read_bytes()

        triangle_count = struct.unpack("<I", data[80:84])[0]
        self.assertGreater(triangle_count, 0)
        self.assertEqual(len(data), 84 + triangle_count * 50)

    def test_cli_requires_target_time_for_stl_export(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(PROJECT_ROOT / "main.py"),
                "--gcode",
                "unused.gcode",
                "--output-stl",
                "unused.stl",
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn(
            "--output-stl requires --target-time",
            result.stderr,
        )


if __name__ == "__main__":
    unittest.main()
