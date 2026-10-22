from __future__ import annotations

import json
import os
import platform
import re
import stat
import sys
import tempfile
import uuid
import zipfile
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from cooling_tower.diagnostics import DiagnosticJournal
from cooling_tower.version import APP_NAME, APP_VERSION
from cooling_tower.write_policy import ensure_writable_output
from cooling_tower.support_privacy import (
    CONTEXT_KEYS, SETTING_KEYS, SAFE_ERROR_TYPES, sanitize_technical,
)


SUPPORT_REPORT_DIRECTORY_NAME = "support_reports"
MAXIMUM_JOURNAL_BYTES = 8 * 1024 * 1024
MAXIMUM_AUXILIARY_LOG_BYTES = 512 * 1024
MAXIMUM_JOURNAL_LINE_BYTES = 256 * 1024
_TRACEBACK_FRAME_PATTERN = re.compile(r'^\s*File\s+"[^"]+",\s+line\s+(?P<line>\d{1,8}),\s+in\s+')
_ERROR_SUMMARY_PATTERN = re.compile(r"^\s*(?P<type>[A-Za-z_][\w.]*(?:Error|Exception|Warning|Fault))\s*:")
_FATAL_ERROR_PATTERN = re.compile(r"^\s*Fatal Python error:")

_JOURNAL_SAFE_KEYS = frozenset(
    {
        "active_jobs",
        "adapter",
        "adapter_id",
        "backend",
        "bundle_size_bytes",
        "cache_kind",
        "cache_hit",
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
        "current_version",
        "target_version",
        "update_stage",
        "expected_size_bytes",
        "winerror",
        "errno",
        "http_status",
        "installed_version_matches",
        "error_code",
        "error_message",
        "error_scope",
        "error_type",
        "event",
        "event_sequence",
        "exclusion_count",
        "failure_reason",
        "file_size_bytes",
        "face_count",
        "component_count",
        "issue_count",
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


def previous_crash_report_for_export(journal: DiagnosticJournal) -> str:
    """Use the same explicit vocabulary for clipboard reports as for ZIPs."""
    try:
        raw = json.loads(journal.build_previous_crash_report())
    except json.JSONDecodeError:
        raw = {}
    events = raw.get("events", [])
    report = {
        "report_type": "unexpected_previous_session",
        "previous_session": sanitize_technical(raw.get("previous_session", {}), allowed_keys=_JOURNAL_SAFE_KEYS),
        "events": [sanitize_technical(entry, allowed_keys=_JOURNAL_SAFE_KEYS)
                   for entry in events[-250:] if isinstance(entry, Mapping)],
    }
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)


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
        directory = ensure_writable_output(self.output_directory)
        if not directory.is_relative_to(self.user_data_root):
            raise ValueError("Der Diagnoseordner liegt außerhalb der eigenen Benutzerdaten.")
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def create_bundle(
        self,
        *,
        application_context: Mapping[str, Any] | None = None,
    ) -> SupportReportBundle:
        created_at = self._now_provider()
        if created_at.tzinfo is None:
            created_at = created_at.astimezone()
        report_id = (
            f"ST-{created_at:%Y%m%d-%H%M%S}-"
            f"{uuid.uuid4().hex[:6].upper()}"
        )
        directory = self.ensure_output_directory()
        journal = self.diagnostic_journal
        if journal is not None:
            journal.record("support_report_bundle_started", report_id=report_id)

        report_text = self._build_bundle_instructions(
            report_id=report_id,
            created_at=created_at,
        )
        diagnostic_text = self._build_diagnostic_log(
            report_id=report_id,
            created_at=created_at,
            application_context=application_context or {},
        )
        manifest = {
            "support_report_schema_version": 4,
            "report_id": report_id,
            "created_at": created_at.isoformat(),
            "program_name": APP_NAME,
            "program_version": APP_VERSION,
            "files": ["hinweise.txt", "diagnose.log", "manifest.json"],
            "privacy": {
                "raw_logs_included": False,
                "user_files_included": False,
                "structured_diagnostics_allowlisted": True,
                "user_text_included": False,
                "technical_strings_allowlisted": True,
                "unknown_fields_omitted": True,
                "review_before_upload_required": True,
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
        target: Path | None = None
        try:
            target = self._available_target_path(directory, created_at)
            with zipfile.ZipFile(
                temporary,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=6,
            ) as archive:
                archive.writestr("hinweise.txt", report_text)
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
            if target is not None:
                target.unlink(missing_ok=True)
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
            "SacrificialTower_Diagnosepaket_"
            f"{created_at:%Y-%m-%d_%H-%M-%S}"
        )
        target = directory / f"{base_name}.zip"
        suffix = 2
        while True:
            try:
                descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                target = directory / f"{base_name}_{suffix}.zip"
                suffix += 1
            else:
                os.close(descriptor)
                return target

    @staticmethod
    def _build_bundle_instructions(
        *,
        report_id: str,
        created_at: datetime,
    ) -> str:
        timezone_name = created_at.strftime("UTC%z")
        return (
            f"{APP_NAME} – Diagnosepaket\n"
            f"{'=' * 48}\n\n"
            f"Bericht-ID: {report_id}\n"
            f"Erstellt: {created_at:%d.%m.%Y um %H:%M:%S Uhr} "
            f"({timezone_name})\n"
            f"Programmversion: {APP_VERSION}\n\n"
            "Dieses Paket enthält technische Diagnosedaten, keine Problembeschreibung.\n"
            "Es wurde lokal erstellt und noch nicht gesendet.\n\n"
            "1. Dieses Diagnosepaket als ZIP öffnen und alle enthaltenen Dateien\n"
            "   vor der Weitergabe prüfen; nur bei Bedarf entpacken.\n"
            "2. In Support & Diagnose das Anliegen Fehler melden wählen und das\n"
            "   Fehlerformular auf GitHub öffnen.\n"
            "3. Das Problem direkt im GitHub-Formular beschreiben, die geprüfte ZIP\n"
            "   manuell anhängen und die Meldung absenden.\n\n"
            "GitHub-Meldungen und Anhänge sind öffentlich sichtbar. Keine persönlichen\n"
            "oder vertraulichen Inhalte veröffentlichen. Eine vollständig anonyme ZIP\n"
            "wird nicht garantiert. Für Fragen und Wünsche ist kein Diagnosepaket nötig.\n"
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
                        f"Betriebssystem: {self._system_summary()}",
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
        entries: deque[tuple[str | None, Mapping[str, Any]]] = deque(maxlen=20_000)
        for path in self._journal_candidates_oldest_first():
            try:
                payload_bytes, _truncated = self._read_log_tail(path, MAXIMUM_JOURNAL_BYTES)
                lines = payload_bytes.splitlines()
            except OSError:
                continue
            for line in lines:
                if len(line) > MAXIMUM_JOURNAL_LINE_BYTES:
                    continue
                try:
                    payload = json.loads(line)
                except (ValueError, UnicodeError, RecursionError):
                    continue
                session_id = (
                    str(payload.get("session_id"))
                    if isinstance(payload, Mapping)
                    and isinstance(payload.get("session_id"), str)
                    and len(payload["session_id"]) <= 128
                    else None
                )
                if isinstance(payload, Mapping):
                    entries.append((session_id, payload))

        if not entries:
            return "(kein Diagnosejournal vorhanden)"

        session_order = list(dict.fromkeys(session_id for session_id, _ in entries if session_id))
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

    def _read_log_tail(self, path: Path, limit: int) -> tuple[bytes, bool]:
        """Read only bounded, application-owned regular logs; never follow external links."""
        resolved = path.resolve()
        if not resolved.is_relative_to(self.log_root):
            raise OSError("Keine eigene Protokolldatei.")
        with resolved.open("rb") as handle:
            metadata = os.fstat(handle.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise OSError("Keine reguläre Protokolldatei.")
            truncated = metadata.st_size > limit
            handle.seek(max(0, metadata.st_size - limit))
            payload = handle.read(limit)
        if truncated:
            # The tail can start in the middle of a record. Never parse a fragment.
            payload = payload.partition(b"\n")[2]
        return payload, truncated

    @staticmethod
    def _system_summary() -> str:
        system = platform.system()
        system = system if system in {"Windows", "Linux", "Darwin"} else "Unbekannt"
        machine = platform.machine()
        machine = machine if machine in {"AMD64", "ARM64", "x86_64", "aarch64", "x86", "i386"} else "Unbekannt"
        release = platform.release()
        release = release if re.fullmatch(r"[0-9.]{1,24}", release) else "<Version ausgelassen>"
        return f"{system} {release} ({machine})"

    def _extract_error_summary(self, path: Path) -> str:
        try:
            payload, truncated = self._read_log_tail(path, MAXIMUM_AUXILIARY_LOG_BYTES)
        except OSError:
            return "(Datei nicht vorhanden oder nicht freigegeben)"
        safe_lines: list[str] = []
        for raw_line in payload.decode("utf-8", errors="replace").splitlines():
            frame = _TRACEBACK_FRAME_PATTERN.match(raw_line)
            if frame is not None:
                safe_lines.append(f"Traceback-Rahmen: Zeile {frame.group('line')}")
                continue
            error = _ERROR_SUMMARY_PATTERN.match(raw_line)
            if error is not None:
                kind = error.group("type")
                safe_lines.append(f"Ausnahmetyp: {kind if kind in SAFE_ERROR_TYPES else 'Exception'}")
                continue
            if _FATAL_ERROR_PATTERN.match(raw_line):
                safe_lines.append("Fataler Python-Fehler erkannt")
        if not safe_lines:
            return "(keine freigegebenen Fehlerangaben vorhanden)"
        prefix = "[älterer Dateiinhalt ausgelassen]\n" if truncated else ""
        return prefix + "\n".join(safe_lines[-200:])

    def _sanitize_journal_entry(self, payload: Mapping[str, Any], *, session_alias: str) -> dict[str, Any]:
        result = {"session": session_alias}
        result.update(sanitize_technical(payload, allowed_keys=_JOURNAL_SAFE_KEYS))
        return result

    def _sanitize_context_value(self, value: Any, *, depth: int = 0) -> Any:
        return sanitize_technical(
            value,
            allowed_keys=_JOURNAL_SAFE_KEYS | CONTEXT_KEYS | SETTING_KEYS,
            depth=depth,
        )
