from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


NO_EXPORT_FOLDER = "Kein Exportordner gefunden."
NO_VALID_EXPORT_FOLDER = "Kein gültiger Exportordner gefunden."
AMBIGUOUS_LATEST_EXPORT = (
    "Letzter Exportordner nicht eindeutig bestimmbar."
)
OUTPUT_FOLDER_UNAVAILABLE = "Der Ausgabeordner ist nicht verfügbar."
EXPORT_FOLDERS_UNREADABLE = "Exportordner konnten nicht geprüft werden."
MAXIMUM_REPORT_SIZE_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class LatestExportResolution:
    directory: Path | None
    unavailable_reason: str | None


@dataclass(frozen=True, slots=True)
class _ExportCandidate:
    directory: Path
    created_at: datetime
    report_modified_ns: int

    @property
    def order_key(self) -> tuple[datetime, int]:
        return self.created_at, self.report_modified_ns


def resolve_latest_export_directory(
    output_root: str | Path,
    *,
    preferred_directory: Path | None = None,
) -> LatestExportResolution:
    """Resolve the latest complete export without guessing on exact ties."""

    raw_root = str(output_root).strip()
    if not raw_root:
        return LatestExportResolution(None, OUTPUT_FOLDER_UNAVAILABLE)
    try:
        root = Path(raw_root).expanduser().resolve()
    except OSError:
        return LatestExportResolution(None, OUTPUT_FOLDER_UNAVAILABLE)
    if not root.is_dir():
        return LatestExportResolution(None, NO_EXPORT_FOLDER)

    try:
        child_directories = tuple(
            child for child in root.iterdir() if child.is_dir()
        )
    except OSError:
        return LatestExportResolution(None, EXPORT_FOLDERS_UNREADABLE)

    candidates = tuple(
        candidate
        for child in child_directories
        if (candidate := _read_export_candidate(root, child)) is not None
    )
    if not candidates:
        reason = (
            NO_VALID_EXPORT_FOLDER
            if child_directories
            else NO_EXPORT_FOLDER
        )
        return LatestExportResolution(None, reason)

    latest_key = max(candidate.order_key for candidate in candidates)
    latest_candidates = tuple(
        candidate
        for candidate in candidates
        if candidate.order_key == latest_key
    )
    if len(latest_candidates) == 1:
        return LatestExportResolution(latest_candidates[0].directory, None)

    preferred = _resolved_path(preferred_directory)
    preferred_matches = tuple(
        candidate
        for candidate in latest_candidates
        if candidate.directory == preferred
    )
    if len(preferred_matches) == 1:
        return LatestExportResolution(preferred_matches[0].directory, None)
    return LatestExportResolution(None, AMBIGUOUS_LATEST_EXPORT)


def _read_export_candidate(
    root: Path,
    directory: Path,
) -> _ExportCandidate | None:
    resolved_directory = _resolved_path(directory)
    if resolved_directory is None or resolved_directory.parent != root:
        return None
    report_path = resolved_directory / "export_report.json"
    summary_path = resolved_directory / "export_summary.txt"
    try:
        report_stat = report_path.stat()
        if (
            not report_path.is_file()
            or not summary_path.is_file()
            or report_stat.st_size > MAXIMUM_REPORT_SIZE_BYTES
        ):
            return None
        payload: Any = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("report_type") != "cooling_tower_export_diagnostics":
        return None
    summary = payload.get("summary")
    if not isinstance(summary, dict) or summary.get("export_succeeded") is not True:
        return None

    created_at = _parse_created_at(payload.get("created_at"))
    output = payload.get("output")
    if created_at is None or not isinstance(output, dict):
        return None
    raw_output_path = output.get("path")
    if not isinstance(raw_output_path, str) or not raw_output_path.strip():
        return None
    artifact_name = Path(raw_output_path).name
    if not artifact_name or Path(artifact_name).suffix.casefold() not in {
        ".gcode",
        ".stl",
    }:
        return None
    if not (resolved_directory / artifact_name).is_file():
        return None
    return _ExportCandidate(
        directory=resolved_directory,
        created_at=created_at,
        report_modified_ns=report_stat.st_mtime_ns,
    )


def _parse_created_at(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _resolved_path(path: Path | None) -> Path | None:
    if path is None:
        return None
    try:
        return path.expanduser().resolve()
    except OSError:
        return None
