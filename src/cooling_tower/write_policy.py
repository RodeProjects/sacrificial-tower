"""Central boundary for application-owned outputs; never writes during discovery."""
from __future__ import annotations

import os
from pathlib import Path
from threading import RLock
from typing import Iterable


class ProtectedWritePathError(ValueError):
    """A requested output overlaps a slicer's installation or data directory."""


_lock = RLock()
_registered_roots: set[Path] = set()
_VENDOR_DIRECTORIES = (
    "AnycubicSlicerNext", "BambuStudio", "Bambu Studio", "OrcaSlicer",
    "Orca Slicer", "PrusaSlicer", "UltiMaker Cura", "Ultimaker Cura",
    "cura", "Creality Print", "CrealityPrint", "ideaMaker", "Simplify3D",
)


def register_slicer_roots(roots: Iterable[str | Path]) -> None:
    """Remember verified portable installations as well as discovered catalogs."""
    resolved = {Path(root).expanduser().resolve() for root in roots}
    with _lock:
        _registered_roots.update(resolved)


def protected_slicer_roots() -> tuple[Path, ...]:
    roots: set[Path] = set()
    for variable in ("APPDATA", "LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
        value = os.environ.get(variable)
        if value:
            base = Path(value)
            roots.update(base / name for name in _VENDOR_DIRECTORIES)
            if variable == "LOCALAPPDATA":
                roots.update(base / "Programs" / name for name in _VENDOR_DIRECTORIES)
    # Avoid resolving every ancestor of dozens of absent vendor folders.
    # Existing junction roots must still be resolved on every check.
    roots = {root.resolve() if root.is_dir() else root.absolute() for root in roots}
    with _lock:
        roots.update(_registered_roots)
    return tuple(roots)


def ensure_writable_output(
    path: str | Path,
    *,
    protected_roots: Iterable[str | Path] = (),
    protected_files: Iterable[str | Path] = (),
) -> Path:
    """Resolve junctions/symlinks and reject protected destinations before I/O.

    Discovery registers nonstandard portable roots. Callers with a profile also
    supply its roots and original files, so headless adapters use the same rule.
    This is a destination policy, not an OS sandbox for third-party executables.
    """
    target = Path(path).expanduser().resolve()
    roots = (*protected_slicer_roots(), *(Path(p).resolve() for p in protected_roots))
    if any(target == root or target.is_relative_to(root) for root in roots):
        raise ProtectedWritePathError(
            "Der Ausgabeort liegt in einem geschützten Slicer-Verzeichnis. "
            "Bitte einen eigenen Export- oder Arbeitsordner auswählen."
        )
    if target in {Path(p).resolve() for p in protected_files}:
        raise ProtectedWritePathError("Eine originale Slicer-Datei darf nicht überschrieben werden.")
    return target
