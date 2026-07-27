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

from PySide6.QtCore import QtMsgType, QTimer, qInstallMessageHandler
from PySide6.QtWidgets import QApplication, QMessageBox

from cooling_tower.application_mutex import (
    acquire_application_mutex,
    release_application_mutex,
)
from cooling_tower.gui import MainWindow
from cooling_tower.distribution import (
    DistributionChannel,
    detect_distribution_channel,
)
from cooling_tower.runtime_paths import IS_FROZEN, resolve_user_data_root
from cooling_tower.version import APP_VERSION


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


def install_qt_message_logging(
    log_path: str | Path = DEFAULT_RUNTIME_LOG,
):
    """Record Qt warnings and fatal messages before a native abort."""

    labels = {
        QtMsgType.QtDebugMsg: "qt-debug",
        QtMsgType.QtInfoMsg: "qt-info",
        QtMsgType.QtWarningMsg: "qt-warning",
        QtMsgType.QtCriticalMsg: "qt-critical",
        QtMsgType.QtFatalMsg: "qt-fatal",
    }

    def handle_qt_message(mode, context, message) -> None:
        location = ""
        if context is not None and context.file:
            location = f"{context.file}:{context.line}: "
        append_runtime_diagnostic(
            labels.get(mode, "qt-message"),
            f"{location}{message}",
            log_path,
        )

    return qInstallMessageHandler(handle_qt_message)


def show_startup_error(
    details: str,
    *,
    log_path: str | Path = DEFAULT_STARTUP_LOG,
) -> Path | None:
    written = write_application_error_log(details, log_path)
    location = str(written) if written is not None else "nicht verfügbar"
    QMessageBox.critical(
        None,
        "Kühlturm-Generator – Startfehler",
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
    native_crash_log = enable_native_crash_log()
    application_mutex = None
    previous_qt_message_handler = None
    qt_message_logging_installed = False
    try:
        if (
            IS_FROZEN
            and _DISTRIBUTION_CHANNEL is DistributionChannel.STANDALONE
        ):
            try:
                application_mutex = acquire_application_mutex()
            except OSError:
                append_runtime_diagnostic(
                    "application-mutex",
                    traceback.format_exc(),
                )
        application = QApplication.instance() or QApplication(sys.argv)
        application.setApplicationName("Kühlturm-Generator")
        application.setApplicationVersion(APP_VERSION)
        application.setQuitOnLastWindowClosed(True)
        install_exception_handler(log_path)
        previous_qt_message_handler = install_qt_message_logging()
        qt_message_logging_installed = True
        try:
            window = window_factory()
            window.show()
            automatic_close_ms = os.environ.get(
                "COOLING_TOWER_TEST_AUTOCLOSE_MS"
            )
            if automatic_close_ms:
                QTimer.singleShot(int(automatic_close_ms), window.close)
        except Exception:
            show_startup_error(traceback.format_exc(), log_path=log_path)
            return 1
        return application.exec()
    finally:
        if qt_message_logging_installed:
            qInstallMessageHandler(previous_qt_message_handler)
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
