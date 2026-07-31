from __future__ import annotations

import json
import os
import platform
import re
import sys
import tempfile
import uuid
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from cooling_tower.diagnostics import DiagnosticJournal
from cooling_tower.version import APP_NAME, APP_VERSION


SUPPORT_REPORT_DIRECTORY_NAME = "support_reports"
MAXIMUM_JOURNAL_BYTES = 8 * 1024 * 1024
MAXIMUM_AUXILIARY_LOG_BYTES = 512 * 1024
MAXIMUM_EXPORTED_TEXT_LENGTH = 2048
MAXIMUM_EXPORTED_COLLECTION_ITEMS = 100
_EMAIL_PATTERN = re.compile(
    r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])"
)
_WINDOWS_PATH_PATTERN = re.compile(
    r"(?i)(?<![\w])(?:[A-Z]:\\|\\\\)[^\r\n\"<>|]*"
)
_UNIX_PATH_PATTERN = re.compile(
    r"(?<![\w:])/(?:[^/\s\"'<>|]+/)+[^\s\"'<>|]*"
)
_URL_PATTERN = re.compile(
    r"(?i)\b(?:https?|ftp|file|smb)://[^\s<>\"']+"
)
_IPV4_PATTERN = re.compile(
    r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])"
)
_IPV6_PATTERN = re.compile(
    r"(?i)(?<![\w:])(?:[0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}(?![\w:])"
)
_MAC_PATTERN = re.compile(
    r"(?i)(?<![0-9a-f])(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}(?![0-9a-f])"
)
_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(password|passwd|secret|api[_-]?key|private[_-]?key|"
    r"access[_-]?token|refresh[_-]?token|authorization)\b"
    r"(\s*[:=]\s*)(?:bearer\s+)?[^\s,;]+"
)
_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_JWT_PATTERN = re.compile(
    r"(?<![\w.-])[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\."
    r"[A-Za-z0-9_-]{12,}(?![\w.-])"
)
_KNOWN_TOKEN_PATTERN = re.compile(
    r"(?i)(?<![\w])(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"
)
_LONG_IDENTIFIER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])[A-Fa-f0-9]{32,}(?![A-Za-z0-9])|"
    r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{48,}(?![A-Za-z0-9_-])"
)
_PERSONAL_NUMBER_PATTERN = re.compile(
    r"(?<!\d)\+?\d(?:[\s()./-]*\d){7,}(?!\d)"
)
_SENSITIVE_FILENAME_PATTERN = re.compile(
    r"(?i)(?<![\w.-])[^\\/:*?\"<>|\r\n]{1,120}?\."
    r"(?:gcode|bgcode|stl|3mf|obj|amf|step|stp|ply|ini|cfg|conf|json|yaml|"
    r"yml|log|txt|zip)(?![\w.-])"
)
_TRACEBACK_FRAME_PATTERN = re.compile(
    r'^\s*File\s+"(?P<path>[^"]+)",\s+line\s+(?P<line>\d+),\s+in\s+'
    r"(?P<function>[A-Za-z_][\w<>]*)\s*$"
)
_ERROR_SUMMARY_PATTERN = re.compile(
    r"^\s*(?P<type>[A-Za-z_][\w.]*(?:Error|Exception|Warning|Fault))"
    r"\s*:\s*(?P<message>.*)$"
)
_FATAL_ERROR_PATTERN = re.compile(r"^\s*Fatal Python error:\s*(?P<message>.*)$")
_BLOCKED_CONTEXT_KEY_PATTERN = re.compile(
    r"(?i)(?:^|_)(?:path|paths|directory|directories|root|roots|filename|"
    r"file_name|command|arguments|argv|password|passwd|secret|private_key|"
    r"api_key|access_token|refresh_token|authorization|fingerprint|digest|"
    r"content|payload|profile_values|hostname|username|email|session_id|"
    r"report_id|job_id|request_id|parent_operation_id|process_id|thread_id|"
    r"native_thread_id|python_thread_id|external_process_id)(?:$|_)"
)

_JOURNAL_SAFE_KEYS = frozenset(
    {
        "active_jobs",
        "adapter",
        "adapter_id",
        "backend",
        "bundle_size_bytes",
        "cache_kind",
        "calibrated",
        "calibration_failure_codes",
        "calibration_iteration_count",
        "calibration_mode",
        "calibration_round",
        "calibration_state",
        "cancellation_phase",
        "cancel_reason",
        "cancel_requested",
        "cancelled",
        "candidate_count",
        "can_slice",
        "can_use_gcode_mode",
        "can_use_stl_mode",
        "clean_shutdown",
        "completion_info",
        "configured_iteration_count",
        "crashed",
        "diagnostic_count",
        "diagnostic_event_schema_version",
        "discovery_source",
        "displayed_segment_count",
        "duration_s",
        "effective_profile_available",
        "elapsed_s",
        "error_code",
        "error_message",
        "error_scope",
        "error_type",
        "event",
        "event_sequence",
        "exclusion_count",
        "failure_reason",
        "file_size_bytes",
        "filament_profile_count",
        "filament_profile_status",
        "finished_utc",
        "forced_inventory",
        "forced_refresh",
        "generation_kind",
        "gui_state",
        "include_all_profiles",
        "installation_count",
        "job_kind",
        "job_state",
        "layer_count",
        "machine_profile_count",
        "machine_profile_status",
        "manual_selection",
        "message",
        "message_type",
        "metadata_value_count",
        "monotonic_s",
        "new_state",
        "outcome",
        "output_file_count",
        "output_mode",
        "previous_state",
        "previous_session_ended_unexpectedly",
        "priority",
        "process_error",
        "process_profile_count",
        "process_profile_status",
        "process_state",
        "product_name",
        "profile_exclusion_codes",
        "profile_state",
        "profiles_filtered",
        "program_version",
        "purpose",
        "reason",
        "recommendation_available",
        "requires_confirmation",
        "result_code",
        "return_code",
        "selected_profile_role_count",
        "selected_profile_cross_slicer",
        "selected_profile_reconstructed",
        "selected_profile_validation_state",
        "selection_available",
        "slice_capable_installation_count",
        "slicer_available",
        "slicer_optimized",
        "source_event",
        "source_file_available",
        "source_segment_count",
        "source_slicer_available",
        "stale_check",
        "started_utc",
        "state",
        "stderr_truncated",
        "stdout_truncated",
        "success",
        "support_level",
        "timed_out",
        "timing_confidence",
        "timeout_ms",
        "typed_config_value_count",
        "utc_time",
        "user_confirmed",
        "verified",
        "verified_installation_count",
        "version",
        "warning_count",
        "worker_class",
    }
)


@dataclass(frozen=True, slots=True)
class SupportReportBundle:
    report_id: str
    path: Path
    created_at: datetime


class SupportReportService:
    """Create a local, privacy-reduced support bundle atomically."""

    def __init__(
        self,
        user_data_root: str | Path,
        *,
        diagnostic_journal: DiagnosticJournal | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.user_data_root = Path(user_data_root).expanduser().resolve()
        self.log_root = self.user_data_root / "logs"
        self.output_directory = (
            self.user_data_root / "output" / SUPPORT_REPORT_DIRECTORY_NAME
        )
        self.diagnostic_journal = diagnostic_journal
        self._now_provider = now_provider or (lambda: datetime.now().astimezone())

    def ensure_output_directory(self) -> Path:
        self.output_directory.mkdir(parents=True, exist_ok=True)
        return self.output_directory.resolve()

    def create_bundle(
        self,
        *,
        title: str,
        description: str,
        application_context: Mapping[str, Any] | None = None,
    ) -> SupportReportBundle:
        normalized_title = " ".join(str(title).split())
        normalized_description = str(description).strip()
        if not normalized_title:
            raise ValueError("Eine kurze Zusammenfassung ist erforderlich.")
        if not normalized_description:
            raise ValueError("Eine Problembeschreibung ist erforderlich.")

        created_at = self._now_provider()
        if created_at.tzinfo is None:
            created_at = created_at.astimezone()
        report_id = (
            f"ST-{created_at:%Y%m%d-%H%M%S}-"
            f"{uuid.uuid4().hex[:6].upper()}"
        )
        directory = self.ensure_output_directory()
        target = self._available_target_path(directory, created_at)
        journal = self.diagnostic_journal
        if journal is not None:
            journal.record("support_report_bundle_started", report_id=report_id)

        report_text = self._build_user_report(
            report_id=report_id,
            created_at=created_at,
            title=normalized_title,
            description=normalized_description,
        )
        diagnostic_text = self._build_diagnostic_log(
            report_id=report_id,
            created_at=created_at,
            application_context=application_context or {},
        )
        manifest = {
            "support_report_schema_version": 2,
            "report_id": report_id,
            "created_at": created_at.isoformat(),
            "program_name": APP_NAME,
            "program_version": APP_VERSION,
            "files": ["problembericht.txt", "diagnose.log", "manifest.json"],
            "privacy": {
                "raw_logs_included": False,
                "user_files_included": False,
                "structured_diagnostics_allowlisted": True,
                "user_text_stored_verbatim": True,
            },
            "transmitted": False,
        }

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".support_report_",
            suffix=".tmp",
            dir=directory,
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            with zipfile.ZipFile(
                temporary,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=6,
            ) as archive:
                archive.writestr("problembericht.txt", report_text)
                archive.writestr("diagnose.log", diagnostic_text)
                archive.writestr(
                    "manifest.json",
                    json.dumps(
                        manifest,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                )
            os.replace(temporary, target)
        except Exception:
            temporary.unlink(missing_ok=True)
            if journal is not None:
                journal.record(
                    "support_report_bundle_failed",
                    report_id=report_id,
                )
            raise

        resolved = target.resolve()
        if journal is not None:
            journal.record(
                "support_report_bundle_created",
                report_id=report_id,
                bundle_path=resolved,
                bundle_size_bytes=resolved.stat().st_size,
            )
        return SupportReportBundle(report_id, resolved, created_at)

    @staticmethod
    def _available_target_path(directory: Path, created_at: datetime) -> Path:
        base_name = (
            "SacrificialTower_Problembericht_"
            f"{created_at:%Y-%m-%d_%H-%M-%S}"
        )
        target = directory / f"{base_name}.zip"
        suffix = 2
        while target.exists():
            target = directory / f"{base_name}_{suffix}.zip"
            suffix += 1
        return target

    @staticmethod
    def _build_user_report(
        *,
        report_id: str,
        created_at: datetime,
        title: str,
        description: str,
    ) -> str:
        timezone_name = created_at.tzname() or "lokale Zeit"
        return (
            f"{APP_NAME} – Problembericht\n"
            f"{'=' * 48}\n\n"
            f"Bericht-ID: {report_id}\n"
            f"Erstellt: {created_at:%d.%m.%Y um %H:%M:%S Uhr} "
            f"({timezone_name})\n"
            f"Programmversion: {APP_VERSION}\n\n"
            f"Zusammenfassung\n"
            f"---------------\n"
            f"{title}\n\n"
            f"Problembeschreibung\n"
            f"-------------------\n"
            f"{description}\n"
        )

    def _build_diagnostic_log(
        self,
        *,
        report_id: str,
        created_at: datetime,
        application_context: Mapping[str, Any],
    ) -> str:
        sections = [
            (
                "Diagnoseübersicht",
                "\n".join(
                    (
                        f"Bericht-ID: {report_id}",
                        f"Erstellt: {created_at.isoformat()}",
                        f"Programm: {APP_NAME} {APP_VERSION}",
                        f"Betriebssystem: {platform.system()} "
                        f"{platform.release()} ({platform.machine()})",
                        f"Python: {platform.python_version()}",
                        f"Eingefrorene Anwendung: "
                        f"{'ja' if getattr(sys, 'frozen', False) else 'nein'}",
                    )
                ),
            ),
            (
                "Aktueller Programmzustand",
                json.dumps(
                    self._sanitize_context_value(application_context),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                    default=str,
                ),
            ),
            (
                "Strukturiertes Diagnosejournal",
                self._collect_journal_entries(),
            ),
        ]
        auxiliary_logs = (
            ("Laufzeitfehler", self.log_root / "application_runtime.log"),
            ("Letzter Startfehler", self.log_root / "application_startup.log"),
            ("Native Absturzdiagnose", self.log_root / "native_crash.log"),
        )
        sections.extend(
            (heading, self._extract_error_summary(path))
            for heading, path in auxiliary_logs
        )
        return "\n\n".join(
            f"=== {heading} ===\n{content or '(keine Daten vorhanden)'}"
            for heading, content in sections
        ).rstrip() + "\n"

    def _collect_journal_entries(self) -> str:
        entries: list[tuple[str | None, Mapping[str, Any]]] = []
        for path in self._journal_candidates_oldest_first():
            try:
                lines = path.read_text(
                    encoding="utf-8",
                    errors="replace",
                ).splitlines()
            except OSError:
                continue
            for line in lines:
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                session_id = (
                    str(payload.get("session_id"))
                    if isinstance(payload, Mapping)
                    and payload.get("session_id") is not None
                    else None
                )
                if isinstance(payload, Mapping):
                    entries.append((session_id, payload))

        if not entries:
            return "(kein Diagnosejournal vorhanden)"

        session_order: list[str] = []
        for session_id, _line in entries:
            if session_id and session_id not in session_order:
                session_order.append(session_id)
        selected_sessions = set(session_order[-2:])
        current_session = (
            self.diagnostic_journal.session_id
            if self.diagnostic_journal is not None
            else None
        )
        if current_session:
            selected_sessions.add(current_session)
        session_aliases = {
            session_id: f"Sitzung-{index}"
            for index, session_id in enumerate(session_order[-2:], start=1)
        }
        selected_lines = []
        for session_id, payload in entries:
            if selected_sessions and session_id not in selected_sessions:
                continue
            safe_entry = self._sanitize_journal_entry(
                payload,
                session_alias=session_aliases.get(session_id, "Sitzung"),
            )
            selected_lines.append(
                json.dumps(
                    safe_entry,
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        return self._bounded_newest_lines(selected_lines)

    def _journal_candidates_oldest_first(self) -> tuple[Path, ...]:
        journal = self.diagnostic_journal
        if journal is not None:
            active = journal.log_path
            backup_count = journal.backup_count
        else:
            active = self.log_root / "background_jobs.jsonl"
            backup_count = 3
        return (
            *(
                active.with_suffix(active.suffix + f".{index}")
                for index in range(backup_count, 0, -1)
            ),
            active,
        )

    @staticmethod
    def _bounded_newest_lines(lines: list[str]) -> str:
        selected: list[str] = []
        size = 0
        truncated = False
        for line in reversed(lines):
            encoded_size = len(line.encode("utf-8", errors="replace")) + 1
            if size + encoded_size > MAXIMUM_JOURNAL_BYTES:
                truncated = True
                break
            selected.append(line)
            size += encoded_size
        selected.reverse()
        prefix = (
            "[ältere Journaleinträge wegen Größenbegrenzung ausgelassen]\n"
            if truncated
            else ""
        )
        return prefix + "\n".join(selected)

    def _extract_error_summary(self, path: Path) -> str:
        try:
            payload = path.read_bytes()
        except OSError:
            return "(Datei nicht vorhanden)"
        truncated = len(payload) > MAXIMUM_AUXILIARY_LOG_BYTES
        if truncated:
            payload = payload[-MAXIMUM_AUXILIARY_LOG_BYTES:]
        safe_lines: list[str] = []
        for raw_line in payload.decode("utf-8", errors="replace").splitlines():
            frame = _TRACEBACK_FRAME_PATTERN.match(raw_line)
            if frame is not None:
                safe_lines.append(
                    "Traceback-Rahmen: Zeile "
                    f"{frame.group('line')}, Funktion "
                    f"{frame.group('function')}"
                )
                continue
            error = _ERROR_SUMMARY_PATTERN.match(raw_line)
            if error is not None:
                safe_lines.append(f"Ausnahmetyp: {error.group('type')}")
                continue
            fatal = _FATAL_ERROR_PATTERN.match(raw_line)
            if fatal is not None:
                safe_lines.append("Fataler Python-Fehler erkannt")

        if not safe_lines:
            return "(keine freigegebenen Fehlerangaben vorhanden)"
        safe_lines = safe_lines[-200:]
        prefix = (
            "[älterer Dateiinhalt wurde vor der Auswertung ausgelassen]\n"
            if truncated
            else ""
        )
        return prefix + "\n".join(safe_lines)

    def _sanitize_journal_entry(
        self,
        payload: Mapping[str, Any],
        *,
        session_alias: str,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {"session": session_alias}
        for raw_key, value in payload.items():
            key = str(raw_key)
            if key not in _JOURNAL_SAFE_KEYS:
                continue
            if key in {"utc_time", "started_utc", "finished_utc"}:
                timestamp = str(value)
                try:
                    datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                except ValueError:
                    continue
                result[key] = timestamp
                continue
            result[key] = self._sanitize_context_value(value, depth=1)
        return result

    def _sanitize_context_value(self, value: Any, *, depth: int = 0) -> Any:
        if depth > 8:
            return "<ausgelassen: Verschachtelungstiefe>"
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, (str, Path)):
            return self._sanitize_free_text(str(value))
        if isinstance(value, Mapping):
            result: dict[str, Any] = {}
            for raw_key, child_value in value.items():
                key = str(raw_key)
                if _BLOCKED_CONTEXT_KEY_PATTERN.search(key):
                    continue
                result[key] = self._sanitize_context_value(
                    child_value,
                    depth=depth + 1,
                )
            return result
        if isinstance(value, (list, tuple, set, frozenset)):
            items = list(value)[:MAXIMUM_EXPORTED_COLLECTION_ITEMS]
            sanitized = [
                self._sanitize_context_value(item, depth=depth + 1)
                for item in items
            ]
            if len(value) > MAXIMUM_EXPORTED_COLLECTION_ITEMS:
                sanitized.append("<weitere Einträge ausgelassen>")
            return sanitized
        return self._sanitize_free_text(type(value).__name__)

    def _sanitize_free_text(self, value: str) -> str:
        sanitized = str(value).replace("\x00", "")
        sanitized = _URL_PATTERN.sub("<entfernte-url>", sanitized)
        sanitized = _WINDOWS_PATH_PATTERN.sub("<entfernter-pfad>", sanitized)
        sanitized = _UNIX_PATH_PATTERN.sub("<entfernter-pfad>", sanitized)
        for environment_key in ("USERNAME", "USERDOMAIN", "COMPUTERNAME"):
            identifier = os.environ.get(environment_key, "").strip()
            if len(identifier) >= 3:
                sanitized = re.sub(
                    rf"(?<![A-Za-z0-9]){re.escape(identifier)}"
                    r"(?![A-Za-z0-9])",
                    "<entfernte-kennung>",
                    sanitized,
                    flags=re.IGNORECASE,
                )

        sanitized = _EMAIL_PATTERN.sub("<entfernte-e-mail>", sanitized)
        sanitized = _MAC_PATTERN.sub("<entfernte-netzwerkadresse>", sanitized)
        sanitized = _IPV4_PATTERN.sub("<entfernte-netzwerkadresse>", sanitized)
        sanitized = _IPV6_PATTERN.sub("<entfernte-netzwerkadresse>", sanitized)
        sanitized = _SECRET_ASSIGNMENT_PATTERN.sub(
            lambda match: (
                f"{match.group(1)}{match.group(2)}<entferntes-geheimnis>"
            ),
            sanitized,
        )
        sanitized = _BEARER_PATTERN.sub("Bearer <entferntes-geheimnis>", sanitized)
        sanitized = _JWT_PATTERN.sub("<entferntes-geheimnis>", sanitized)
        sanitized = _KNOWN_TOKEN_PATTERN.sub("<entferntes-geheimnis>", sanitized)
        sanitized = _SENSITIVE_FILENAME_PATTERN.sub(
            "<entfernter-dateiname>",
            sanitized,
        )
        sanitized = _PERSONAL_NUMBER_PATTERN.sub(
            "<entfernte-nummer>",
            sanitized,
        )
        sanitized = _LONG_IDENTIFIER_PATTERN.sub(
            "<entfernte-kennung>",
            sanitized,
        )
        if len(sanitized) > MAXIMUM_EXPORTED_TEXT_LENGTH:
            sanitized = (
                sanitized[:1536]
                + " … <gekürzt> … "
                + sanitized[-384:]
            )
        return sanitized
