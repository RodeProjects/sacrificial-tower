from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cooling_tower.version import APP_VERSION


_SENSITIVE_KEY = re.compile(
    r"(?:password|passwd|secret|private[_-]?key|access[_-]?token|"
    r"refresh[_-]?token|profile[_-]?(?:content|payload|values))",
    re.IGNORECASE,
)
_PATH_KEY = re.compile(r"(?:path|directory|root|file)$", re.IGNORECASE)
_COMMAND_KEY = re.compile(r"(?:command|arguments|argv)$", re.IGNORECASE)
_MAX_TEXT_LENGTH = 4096
_CURRENT_JOURNAL: DiagnosticJournal | None = None
_CURRENT_LOCK = threading.RLock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _redact_text(value: str) -> str:
    try:
        home = str(Path.home())
    except RuntimeError:
        home = ""
    redacted = value.replace(home, "<user-home>") if home else value
    if len(redacted) > _MAX_TEXT_LENGTH:
        return redacted[:2048] + " … <truncated> … " + redacted[-1024:]
    return redacted


def _sanitize(key: str, value: Any) -> Any:
    if _SENSITIVE_KEY.search(key):
        return "<redacted>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Path):
        value = str(value)
    if isinstance(value, str):
        if _PATH_KEY.search(key):
            path = Path(value)
            return f"<redacted-path>/{path.name}" if path.name else "<redacted-path>"
        return _redact_text(value)
    if isinstance(value, Mapping):
        return {
            str(child_key): _sanitize(str(child_key), child_value)
            for child_key, child_value in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if _COMMAND_KEY.search(key):
            executable = Path(str(value[0])).name if value else ""
            return {
                "executable": executable,
                "argument_count": max(0, len(value) - 1),
            }
        return [_sanitize(key, item) for item in value]
    return _redact_text(repr(value))


class DiagnosticJournal:
    """Thread-safe, rotating JSONL diagnostics with clean-session markers."""

    def __init__(
        self,
        log_path: str | Path,
        *,
        state_path: str | Path | None = None,
        app_version: str = APP_VERSION,
        maximum_bytes: int = 5 * 1024 * 1024,
        backup_count: int = 3,
    ) -> None:
        self.log_path = Path(log_path).expanduser().resolve()
        self.state_path = (
            Path(state_path).expanduser().resolve()
            if state_path is not None
            else self.log_path.with_name("diagnostic_session.json")
        )
        self.app_version = app_version
        self.maximum_bytes = max(64 * 1024, int(maximum_bytes))
        self.backup_count = max(1, int(backup_count))
        self.session_id = str(uuid.uuid4())
        self._started_monotonic = time.monotonic()
        self._event_sequence = 0
        self._lock = threading.RLock()
        self._started = False
        self._closed_cleanly = False
        self._active_jobs_provider: Callable[[], object] | None = None
        self.previous_unexpected_session: dict[str, Any] | None = None

    def set_active_jobs_provider(
        self,
        provider: Callable[[], object] | None,
    ) -> None:
        with self._lock:
            self._active_jobs_provider = provider

    def start_session(self) -> dict[str, Any] | None:
        with self._lock:
            if self._started:
                return self.previous_unexpected_session
            previous = self._read_state()
            if previous and not bool(previous.get("clean_shutdown", False)):
                self.previous_unexpected_session = dict(previous)
            self._started = True
            self._write_state(clean_shutdown=False)
            self.record(
                "session_started",
                previous_session_ended_unexpectedly=(
                    self.previous_unexpected_session is not None
                ),
                previous_unexpected_session=(
                    self.previous_unexpected_session.get("session_id")
                    if self.previous_unexpected_session
                    else None
                ),
            )
            return self.previous_unexpected_session

    def close_session(self) -> None:
        with self._lock:
            if not self._started or self._closed_cleanly:
                return
            self.record("session_finished", clean_shutdown=True)
            self._closed_cleanly = True
            self._write_state(clean_shutdown=True)

    def record(self, event: str, **details: Any) -> dict[str, Any]:
        with self._lock:
            self._event_sequence += 1
            entry: dict[str, Any] = {
                "session_id": self.session_id,
                "program_version": self.app_version,
                "event_sequence": self._event_sequence,
                "utc_time": _utc_now(),
                "monotonic_s": round(
                    max(0.0, time.monotonic() - self._started_monotonic),
                    6,
                ),
                "event": str(event),
                "python_thread_id": threading.get_ident(),
                "native_thread_id": threading.get_native_id(),
            }
            entry.update(
                {
                    str(key): _sanitize(str(key), value)
                    for key, value in details.items()
                }
            )
            payload = (
                json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n"
            ).encode("utf-8")
            try:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                self._rotate_if_needed(len(payload))
                with self.log_path.open("ab") as handle:
                    handle.write(payload)
                    handle.flush()
            except OSError:
                pass
            return entry

    def record_qt_message(
        self,
        *,
        message_type: str,
        message: str,
        location: str = "",
        critical: bool = False,
    ) -> None:
        try:
            active_jobs = (
                self._active_jobs_provider()
                if critical and self._active_jobs_provider is not None
                else ()
            )
            self.record(
                "qt_message",
                message_type=message_type,
                message=message,
                location=location,
                priority="critical" if critical else "normal",
                active_jobs=active_jobs,
            )
        except Exception:
            # A Qt message handler must never propagate into Qt.
            return

    def build_previous_crash_report(self) -> str:
        previous = self.previous_unexpected_session
        if previous is None:
            return "Es wurde kein unerwartet beendeter vorheriger Lauf erkannt."
        previous_id = str(previous.get("session_id", "unknown"))
        events: list[dict[str, Any]] = []
        for path in self._log_candidates():
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line in lines:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("session_id") == previous_id:
                    events.append(entry)
        report = {
            "report_type": "unexpected_previous_session",
            "detected_by_session_id": self.session_id,
            "previous_session": previous,
            "events": events[-250:],
        }
        return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)

    def discard_previous_crash_report(self) -> None:
        previous = self.previous_unexpected_session
        self.previous_unexpected_session = None
        self.record(
            "previous_crash_report_discarded",
            previous_session_id=(
                previous.get("session_id") if previous is not None else None
            ),
        )

    def _read_state(self) -> dict[str, Any] | None:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return dict(payload) if isinstance(payload, Mapping) else None

    def _write_state(self, *, clean_shutdown: bool) -> None:
        payload = {
            "session_id": self.session_id,
            "program_version": self.app_version,
            "process_id": os.getpid(),
            "started_utc": (
                _utc_now()
                if not self._closed_cleanly
                else None
            ),
            "updated_utc": _utc_now(),
            "clean_shutdown": bool(clean_shutdown),
            "diagnostic_log_path": str(self.log_path),
        }
        temporary = self.state_path.with_name(
            f".{self.state_path.name}.{os.getpid()}.tmp"
        )
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.state_path)
        except OSError:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _rotate_if_needed(self, incoming_bytes: int) -> None:
        try:
            current_size = self.log_path.stat().st_size
        except OSError:
            current_size = 0
        if current_size + incoming_bytes <= self.maximum_bytes:
            return
        for index in range(self.backup_count, 0, -1):
            source = (
                self.log_path
                if index == 1
                else self.log_path.with_suffix(
                    self.log_path.suffix + f".{index - 1}"
                )
            )
            destination = self.log_path.with_suffix(
                self.log_path.suffix + f".{index}"
            )
            try:
                if source.exists():
                    os.replace(source, destination)
            except OSError:
                continue

    def _log_candidates(self) -> tuple[Path, ...]:
        return (
            self.log_path,
            *(
                self.log_path.with_suffix(self.log_path.suffix + f".{index}")
                for index in range(1, self.backup_count + 1)
            ),
        )


def set_current_diagnostic_journal(
    journal: DiagnosticJournal | None,
) -> None:
    global _CURRENT_JOURNAL
    with _CURRENT_LOCK:
        _CURRENT_JOURNAL = journal


def current_diagnostic_journal() -> DiagnosticJournal | None:
    with _CURRENT_LOCK:
        return _CURRENT_JOURNAL
