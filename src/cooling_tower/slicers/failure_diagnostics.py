"""Bounded local evidence for failed slicer calls, outside disposable jobs.

These are raw local diagnostics, including model/profile copies. They are never
an automatic part of a support export.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
import uuid
from pathlib import Path
from threading import RLock
from typing import Iterable

from cooling_tower.diagnostic_context import record_diagnostic
from cooling_tower.diagnostics import current_diagnostic_journal
from cooling_tower.version import APP_VERSION
from cooling_tower.write_policy import ensure_writable_output


DEFAULT_MAXIMUM_CASES = 10
DEFAULT_MAXIMUM_BYTES = 128 * 1024 * 1024
DEFAULT_MAXIMUM_CASE_BYTES = 32 * 1024 * 1024
DEFAULT_MAXIMUM_AGE_S = 14 * 24 * 60 * 60
_CASE_NAME = re.compile(r"slice-[0-9a-f]{32}\Z")
_LOCK = RLock()


class SlicerFailureArchive:
    def __init__(
        self, root: str | Path, *, maximum_cases: int = DEFAULT_MAXIMUM_CASES,
        maximum_bytes: int = DEFAULT_MAXIMUM_BYTES,
        maximum_case_bytes: int = DEFAULT_MAXIMUM_CASE_BYTES,
        maximum_age_s: float = DEFAULT_MAXIMUM_AGE_S,
    ) -> None:
        if (
            maximum_cases < 1 or maximum_case_bytes < 4096
            or maximum_bytes < maximum_case_bytes or maximum_age_s <= 0
        ):
            raise ValueError("Invalid slicer diagnostic retention limits.")
        self.root = Path(root).expanduser().resolve()
        self.maximum_cases = maximum_cases
        self.maximum_bytes = maximum_bytes
        self.maximum_case_bytes = maximum_case_bytes
        self.maximum_age_s = maximum_age_s

    def retain(self, payload: dict, files: Iterable[tuple[Path, str]]) -> Path | None:
        """Copy bounded evidence before the caller cleans up its working tree."""
        with _LOCK:
            try:
                ensure_writable_output(self.root)
                self.root.mkdir(parents=True, exist_ok=True)
                self.prune()
                case = self.root / f"slice-{uuid.uuid4().hex}"
                case.mkdir()
                manifest_budget = min(1024 * 1024, self.maximum_case_bytes // 2)
                remaining = self.maximum_case_bytes - manifest_budget
                manifest = dict(
                    payload, archive_schema_version=1, program_version=APP_VERSION, files=[],
                )
                for index, (source, name) in enumerate(files):
                    if index >= 128:
                        manifest["file_list_truncated"] = True
                        break
                    source = Path(source)
                    relative = Path(name)
                    if relative.is_absolute() or relative.drive or ".." in relative.parts:
                        raise ValueError("Diagnostic file names must stay inside their case.")
                    entry = {"original_path": str(source), "path": relative.as_posix()}
                    manifest["files"].append(entry)
                    try:
                        if source.is_symlink() or source.is_junction() or not source.is_file():
                            entry["omitted"] = "not_regular_file"
                            continue
                        size = source.stat().st_size
                        entry["size_bytes"] = size
                        if size > remaining:
                            entry["omitted"] = "size_limit"
                            continue
                        destination = case / relative
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        # A source growing during the copy must not bypass the quota.
                        with source.open("rb") as reader, destination.open("xb") as writer:
                            copied = 0
                            digest = hashlib.sha256()
                            while chunk := reader.read(min(1024 * 1024, remaining - copied + 1)):
                                copied += len(chunk)
                                if copied > remaining:
                                    raise OverflowError("Diagnostic source exceeded its size allowance.")
                                writer.write(chunk)
                                digest.update(chunk)
                        remaining -= copied
                        entry["retained_bytes"] = copied
                        entry["sha256"] = digest.hexdigest()
                    except (OSError, OverflowError) as error:
                        entry["omitted"] = "size_limit" if isinstance(error, OverflowError) else "read_error"
                        target = case / relative
                        target.unlink(missing_ok=True)
                # Raw output is bounded independently of an oversized spool file.
                tail_limit = manifest_budget // 16
                for key in ("stdout", "stderr"):
                    raw = str(manifest.get(key, "")).encode("utf-8", errors="replace")
                    manifest[key] = raw[-tail_limit:].decode("utf-8", errors="replace")
                    if len(raw) > tail_limit:
                        manifest[f"{key}_archive_truncated"] = True
                encoded = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
                if len(encoded) > manifest_budget:
                    raise ValueError("Diagnostic metadata exceeded its size allowance.")
                path = case / "slicer_failure.json"
                path.write_bytes(encoded)
                self.prune()
                if path.is_file():
                    record_diagnostic("slicer_failure_retained", diagnostic_path=path)
                    return path
            except (OSError, ValueError) as error:
                if "case" in locals():
                    try:
                        self._remove_case(case)
                    except (OSError, ValueError):
                        pass
                record_diagnostic("slicer_failure_retention_failed", error_type=type(error).__name__)
            return None

    def prune(self) -> None:
        """Prune only our own direct children, never unknown folders or links."""
        with _LOCK:
            ensure_writable_output(self.root)
            if not self.root.is_dir():
                return
            cases = []
            now = time.time()
            for case in self.root.iterdir():
                if not self._is_case(case):
                    continue
                try:
                    modified = case.stat().st_mtime
                    if now - modified > self.maximum_age_s:
                        self._remove_case(case)
                        continue
                    size = sum(
                        p.stat().st_size for p in case.rglob("*")
                        if p.is_file() and not p.is_symlink()
                    )
                    cases.append((modified, case.name, case, size))
                except OSError:
                    continue
            retained = 0
            occupied = 0
            for _, _, case, size in sorted(cases, reverse=True):
                if retained >= self.maximum_cases or occupied + size > self.maximum_bytes:
                    self._remove_case(case)
                else:
                    retained += 1
                    occupied += size

    def _is_case(self, path: Path) -> bool:
        return bool(
            _CASE_NAME.fullmatch(path.name) and path.is_dir()
            and not path.is_symlink() and not path.is_junction()
            and path.resolve().parent == self.root
        )

    def _remove_case(self, path: Path) -> None:
        if self._is_case(path):
            # Windows: resolve and verify the concrete target before recursive deletion.
            ensure_writable_output(path)
            shutil.rmtree(path, ignore_errors=True)


def session_failure_archive() -> SlicerFailureArchive | None:
    journal = current_diagnostic_journal()
    if journal is None:
        # Headless callers without a session keep their explicit diagnostics_root.
        return None
    return SlicerFailureArchive(journal.log_path.parent / "slicer_failures")


def prune_session_failure_archive() -> None:
    archive = session_failure_archive()
    if archive is not None:
        try:
            archive.prune()
        except (OSError, ValueError) as error:
            record_diagnostic("slicer_failure_retention_failed", error_type=type(error).__name__)


def retain_slicer_failure(request, outcome, failure_reason: str, *, working_root: Path,
                          extra_files: Iterable[tuple[Path, str]] = ()) -> Path | None:
    try:
        return _retain_slicer_failure(request, outcome, failure_reason,
                                      working_root=working_root, extra_files=extra_files)
    except (OSError, ValueError) as error:
        record_diagnostic("slicer_failure_retention_failed", error_type=type(error).__name__)
        return None


def _retain_slicer_failure(request, outcome, failure_reason: str, *, working_root: Path,
                           extra_files: Iterable[tuple[Path, str]]) -> Path | None:
    archive = session_failure_archive()
    if archive is None or not request.retain_failure_diagnostics:
        return None
    protected = request.profile.installation
    ensure_writable_output(archive.root, protected_roots=(protected.executable_path.parent, *protected.profile_roots),
                           protected_files=request.profile.source_paths)
    files = []
    model = working_root / "input" / request.model_path.name
    if model.is_file():
        files.append((model, f"input/{model.name}"))
        if request.use_cli_assemble_list and model.stat().st_size <= 1024 * 1024:
            try:
                assembly = json.loads(model.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                assembly = {}
            plates = assembly.get("plates", []) if isinstance(assembly, dict) else []
            if not isinstance(plates, list):
                plates = []
            for plate in plates[:128]:
                objects = plate.get("objects", []) if isinstance(plate, dict) else []
                if not isinstance(objects, list):
                    continue
                for item in objects[:128]:
                    path = item.get("path") if isinstance(item, dict) else None
                    if not isinstance(path, str):
                        continue
                    source = Path(path)
                    if source.suffix.casefold() in {".stl", ".3mf"}:
                        files.append((source, f"assembly_inputs/{len(files):03d}{source.suffix.casefold()}"))
    for directory in ("input", "effective_profiles"):
        root = working_root / directory
        if root.is_dir() and not root.is_symlink() and not root.is_junction():
            files.extend((p, p.relative_to(working_root).as_posix()) for p in sorted(root.rglob("*"))
                         if p.is_file() and p != model and p.resolve().is_relative_to(working_root.resolve()))
    files.extend((p, p.name) for p in sorted(working_root.glob("*.ini")) if p.is_file())
    files.extend(extra_files)
    if outcome.output_diagnostic_path is not None:
        files.append((outcome.output_diagnostic_path, "process_output.binlog"))
    return archive.retain({
        "success": False, "failure_reason": failure_reason,
        "adapter": protected.adapter_id, "slicer_version": protected.version,
        "purpose": request.purpose, "calibration_round": request.calibration_round,
        "session_id": current_diagnostic_journal().session_id,
        "return_code": outcome.return_code, "process_id": outcome.process_id,
        "timed_out": outcome.timed_out, "cancelled": outcome.cancelled,
        "crashed": outcome.crashed, "process_backend": outcome.backend,
        "duration_s": outcome.duration_s, "command": list(outcome.command),
        "stdout": outcome.stdout, "stderr": outcome.stderr,
        "stdout_truncated": outcome.stdout_truncated, "stderr_truncated": outcome.stderr_truncated,
    }, files)
