from __future__ import annotations

import faulthandler
import os
import sys
import threading
import traceback
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import TextIO, Type

from PySide6.QtCore import QTimer, QUrl, QtMsgType, qInstallMessageHandler
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from cooling_tower.application_mutex import (
    ApplicationAlreadyRunningError,
    activate_running_application_window,
    acquire_application_mutex,
    release_application_mutex,
)
from cooling_tower.diagnostic_events import (
    DIAGNOSTIC_EVENT_SCHEMA_VERSION,
    exception_error_code,
)
from cooling_tower.diagnostics import (
    DiagnosticJournal,
    current_diagnostic_journal,
    set_current_diagnostic_journal,
)
from cooling_tower.gui import MainWindow
from cooling_tower.distribution import detect_distribution_channel
from cooling_tower.runtime_paths import IS_FROZEN, resolve_user_data_root
from cooling_tower.version import APP_NAME, APP_VERSION
from cooling_tower.windows_process import configure_windows_process_policy


_DISTRIBUTION_CHANNEL = detect_distribution_channel()
_APPLICATION_DATA_ROOT = resolve_user_data_root(
    instance_id=(
        _DISTRIBUTION_CHANNEL.value if IS_FROZEN else "development"
    )
)
_APPLICATION_LOG_ROOT = _APPLICATION_DATA_ROOT / "logs"
DEFAULT_STARTUP_LOG = _APPLICATION_LOG_ROOT / "application_startup.log"
DEFAULT_NATIVE_CRASH_LOG = _APPLICATION_LOG_ROOT / "native_crash.log"
DEFAULT_RUNTIME_LOG = _APPLICATION_LOG_ROOT / "application_runtime.log"
DEFAULT_JOB_DIAGNOSTIC_LOG = _APPLICATION_LOG_ROOT / "background_jobs.jsonl"
DEFAULT_DIAGNOSTIC_SESSION_STATE = (
    _APPLICATION_LOG_ROOT / "diagnostic_session.json"
)
APPLICATION_ICON_PATH = (
    Path(__file__).resolve().parent / "gui" / "assets" / "app.ico"
)

_CRITICAL_QT_MESSAGES = (
    "qobject::killtimer",
    "timers cannot be stopped from another thread",
    "qthread: destroyed while thread is still running",
    "qthreadstorage",
    "qobject::setparent",
)
MAIN_WINDOW_REVEAL_DELAY_MS = 40


def _reveal_main_window(window) -> None:  # type: ignore[no-untyped-def]
    if window.isVisible():
        window.setWindowOpacity(1.0)


def _show_main_window(window) -> None:  # type: ignore[no-untyped-def]
    """Hide Windows' provisional first frame until placement is complete."""

    if sys.platform != "win32":
        window.show()
        return
    window.setWindowOpacity(0.0)
    window.show()
    QTimer.singleShot(
        MAIN_WINDOW_REVEAL_DELAY_MS,
        lambda: _reveal_main_window(window),
    )


def enable_native_crash_log(
    log_path: str | Path = DEFAULT_NATIVE_CRASH_LOG,
) -> TextIO | None:
    """Keep Python thread stacks for otherwise silent native process aborts."""

    path = Path(log_path).expanduser()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a", encoding="utf-8", buffering=1)
        handle.write(
            "\n=== application session started "
            f"{datetime.now().astimezone().isoformat()} pid={os.getpid()} ===\n"
        )
        faulthandler.enable(file=handle, all_threads=True)
        return handle
    except (OSError, RuntimeError):
        return None


def write_application_error_log(
    details: str,
    log_path: str | Path = DEFAULT_STARTUP_LOG,
) -> Path | None:
    path = Path(log_path).expanduser()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(details, encoding="utf-8")
        return path.resolve()
    except OSError:
        return None


def append_runtime_diagnostic(
    source: str,
    details: str,
    log_path: str | Path = DEFAULT_RUNTIME_LOG,
) -> Path | None:
    """Persist diagnostics that would otherwise disappear with the GUI."""

    path = Path(log_path).expanduser()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                "\n=== "
                f"{datetime.now().astimezone().isoformat()} [{source}] ===\n"
            )
            handle.write(details.rstrip())
            handle.write("\n")
        return path.resolve()
    except OSError:
        return None


def _record_unhandled_exception(scope: str, exception: BaseException) -> None:
    journal = current_diagnostic_journal()
    if journal is None:
        return
    journal.record(
        "unhandled_python_exception",
        diagnostic_event_schema_version=DIAGNOSTIC_EVENT_SCHEMA_VERSION,
        outcome="failed",
        error_scope=scope,
        error_code=exception_error_code(scope, exception),
        error_type=type(exception).__name__,
    )


def install_qt_message_logging(
    log_path: str | Path = DEFAULT_RUNTIME_LOG,
    *,
    diagnostic_journal: DiagnosticJournal | None = None,
    active_jobs_provider: Callable[[], object] | None = None,
):
    """Record Qt messages without throwing and preserve an existing handler."""

    labels = {
        QtMsgType.QtDebugMsg: "qt-debug",
        QtMsgType.QtInfoMsg: "qt-info",
        QtMsgType.QtWarningMsg: "qt-warning",
        QtMsgType.QtCriticalMsg: "qt-critical",
        QtMsgType.QtFatalMsg: "qt-fatal",
    }

    if diagnostic_journal is not None:
        diagnostic_journal.set_active_jobs_provider(active_jobs_provider)
    previous_holder: dict[str, object] = {}

    def handle_qt_message(mode, context, message) -> None:
        try:
            location = ""
            if context is not None and context.file:
                location = f"{context.file}:{context.line}"
            normalized = str(message).casefold()
            critical = any(
                marker in normalized for marker in _CRITICAL_QT_MESSAGES
            )
            if diagnostic_journal is not None:
                diagnostic_journal.record_qt_message(
                    message_type=labels.get(mode, "qt-message"),
                    message=str(message),
                    location=location,
                    critical=critical,
                )
            else:
                append_runtime_diagnostic(
                    labels.get(mode, "qt-message"),
                    f"{location + ': ' if location else ''}{message}",
                    log_path,
                )
        except Exception:
            pass
        previous = previous_holder.get("handler")
        if callable(previous):
            try:
                previous(mode, context, message)
            except Exception:
                pass

    previous = qInstallMessageHandler(handle_qt_message)
    previous_holder["handler"] = previous
    return previous


def offer_previous_crash_report(
    parent,
    journal: DiagnosticJournal,
) -> None:
    """Offer local-only recovery actions for an unclosed previous session."""

    if journal.previous_unexpected_session is None:
        return
    box = QMessageBox(parent)
    box.setWindowTitle("Vorheriger Programmabbruch erkannt")
    box.setIcon(QMessageBox.Icon.Warning)
    box.setText(
        "Die vorherige Sitzung wurde offenbar nicht sauber beendet. "
        "Der technische Bericht bleibt lokal und wird nicht automatisch "
        "übertragen."
    )
    show_button = box.addButton(
        "Technischen Bericht anzeigen",
        QMessageBox.ButtonRole.ActionRole,
    )
    copy_button = box.addButton(
        "In Zwischenablage kopieren",
        QMessageBox.ButtonRole.ActionRole,
    )
    folder_button = box.addButton(
        "Protokollordner öffnen",
        QMessageBox.ButtonRole.ActionRole,
    )
    discard_button = box.addButton(
        "Bericht verwerfen",
        QMessageBox.ButtonRole.DestructiveRole,
    )
    later_button = box.addButton(
        "Später",
        QMessageBox.ButtonRole.RejectRole,
    )
    box.setDefaultButton(later_button)
    box.exec()
    clicked = box.clickedButton()
    report = journal.build_previous_crash_report()
    if clicked is show_button:
        details = QMessageBox(parent)
        details.setWindowTitle("Technischer Diagnosebericht")
        details.setIcon(QMessageBox.Icon.Information)
        details.setText(
            "Diagnose der unerwartet beendeten vorherigen Sitzung"
        )
        details.setDetailedText(report)
        details.exec()
    elif clicked is copy_button:
        from cooling_tower.support_report import previous_crash_report_for_export
        QApplication.clipboard().setText(previous_crash_report_for_export(journal))
    elif clicked is folder_button:
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(journal.log_path.parent))
        )
    elif clicked is discard_button:
        journal.discard_previous_crash_report()


def show_startup_error(
    details: str,
    *,
    log_path: str | Path = DEFAULT_STARTUP_LOG,
) -> Path | None:
    written = write_application_error_log(details, log_path)
    location = str(written) if written is not None else "nicht verfügbar"
    QMessageBox.critical(
        None,
        f"{APP_NAME} – Startfehler",
        "Die Anwendung konnte nicht vollständig gestartet werden.\n\n"
        "Fehlerdetails wurden gespeichert unter:\n"
        f"{location}",
    )
    return written


def install_exception_handler(
    log_path: str | Path = DEFAULT_STARTUP_LOG,
    runtime_log_path: str | Path = DEFAULT_RUNTIME_LOG,
) -> Callable[[Type[BaseException], BaseException, TracebackType | None], None]:
    def handle_exception(
        exception_type: Type[BaseException],
        exception: BaseException,
        exception_traceback: TracebackType | None,
    ) -> None:
        _record_unhandled_exception("main_thread_exception", exception)
        details = "".join(
            traceback.format_exception(
                exception_type,
                exception,
                exception_traceback,
            )
        )
        append_runtime_diagnostic(
            "unhandled-main-thread-exception",
            details,
            runtime_log_path,
        )
        show_startup_error(details, log_path=log_path)

    def handle_thread_exception(arguments) -> None:
        _record_unhandled_exception(
            "python_thread_exception",
            arguments.exc_value,
        )
        details = "".join(
            traceback.format_exception(
                arguments.exc_type,
                arguments.exc_value,
                arguments.exc_traceback,
            )
        )
        append_runtime_diagnostic(
            f"unhandled-python-thread:{arguments.thread.name}",
            details,
            runtime_log_path,
        )

    def handle_unraisable(arguments) -> None:
        _record_unhandled_exception(
            "unraisable_exception",
            arguments.exc_value,
        )
        details = "".join(
            traceback.format_exception(
                type(arguments.exc_value),
                arguments.exc_value,
                arguments.exc_traceback,
            )
        )
        append_runtime_diagnostic(
            "unraisable-exception",
            f"{arguments.err_msg or ''}\n{details}",
            runtime_log_path,
        )

    sys.excepthook = handle_exception
    threading.excepthook = handle_thread_exception
    sys.unraisablehook = handle_unraisable
    return handle_exception


def run_application(
    *,
    window_factory=MainWindow,
    log_path: str | Path = DEFAULT_STARTUP_LOG,
) -> int:
    application_mutex = None
    try:
        application_mutex = acquire_application_mutex()
    except ApplicationAlreadyRunningError:
        try:
            activate_running_application_window(APP_NAME)
        except OSError:
            append_runtime_diagnostic(
                "application-activation",
                traceback.format_exc(),
            )
        return 0
    except OSError:
        append_runtime_diagnostic(
            "application-mutex",
            traceback.format_exc(),
        )
        return 1

    native_crash_log = enable_native_crash_log()
    previous_qt_message_handler = None
    qt_message_logging_installed = False
    application_returned = False
    diagnostic_journal = DiagnosticJournal(
        DEFAULT_JOB_DIAGNOSTIC_LOG,
        state_path=DEFAULT_DIAGNOSTIC_SESSION_STATE,
    )
    diagnostic_journal.start_session()
    set_current_diagnostic_journal(diagnostic_journal)
    process_policy = configure_windows_process_policy()
    diagnostic_journal.record(
        "windows_process_policy",
        active=process_policy.active,
        process_error_mode=(
            f"0x{process_policy.process_error_mode:08X}"
            if process_policy.process_error_mode is not None
            else None
        ),
        wer_flags=(
            f"0x{process_policy.wer_flags:08X}"
            if process_policy.wer_flags is not None
            else None
        ),
        configuration_errors=process_policy.errors,
    )
    try:
        application = QApplication.instance() or QApplication(sys.argv)
        application.setApplicationName(APP_NAME)
        application.setApplicationVersion(APP_VERSION)
        application.setWindowIcon(QIcon(str(APPLICATION_ICON_PATH)))
        application.setQuitOnLastWindowClosed(True)
        install_exception_handler(log_path)
        previous_qt_message_handler = install_qt_message_logging(
            diagnostic_journal=diagnostic_journal,
        )
        qt_message_logging_installed = True
        try:
            window = window_factory()
            manager = getattr(window, "background_job_manager", None)
            provider = getattr(manager, "diagnostic_snapshot", None)
            if callable(provider):
                diagnostic_journal.set_active_jobs_provider(provider)
            _show_main_window(window)
            if diagnostic_journal.previous_unexpected_session is not None:
                QTimer.singleShot(
                    (
                        MAIN_WINDOW_REVEAL_DELAY_MS + 1
                        if sys.platform == "win32"
                        else 0
                    ),
                    lambda: offer_previous_crash_report(
                        window,
                        diagnostic_journal,
                    ),
                )
            automatic_close_ms = os.environ.get(
                "COOLING_TOWER_TEST_AUTOCLOSE_MS"
            )
            if automatic_close_ms:
                QTimer.singleShot(int(automatic_close_ms), window.close)
        except Exception as error:
            diagnostic_journal.record(
                "application_startup_failed",
                diagnostic_event_schema_version=(
                    DIAGNOSTIC_EVENT_SCHEMA_VERSION
                ),
                outcome="failed",
                error_scope="application_startup",
                error_code=exception_error_code(
                    "application_startup",
                    error,
                ),
                error_type=type(error).__name__,
            )
            show_startup_error(traceback.format_exc(), log_path=log_path)
            application_returned = True
            return 1
        result = application.exec()
        application_returned = True
        return result
    finally:
        if qt_message_logging_installed:
            qInstallMessageHandler(previous_qt_message_handler)
        if application_returned:
            diagnostic_journal.close_session()
        set_current_diagnostic_journal(None)
        if native_crash_log is not None:
            try:
                faulthandler.disable()
                native_crash_log.write("=== application session ended cleanly ===\n")
                native_crash_log.close()
            except (OSError, RuntimeError):
                pass
        try:
            release_application_mutex(application_mutex)
        except OSError:
            append_runtime_diagnostic(
                "application-mutex-release",
                traceback.format_exc(),
            )


if __name__ == "__main__":
    raise SystemExit(run_application())
