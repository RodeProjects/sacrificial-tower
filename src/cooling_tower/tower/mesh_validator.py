"""Public mesh validation API."""

from cooling_tower.tower.mesh_generator import (
    MeshValidation,
    validate_triangle_mesh,
)

__all__ = ["MeshValidation", "validate_triangle_mesh"]
