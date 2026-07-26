from __future__ import annotations

from collections.abc import Callable, MutableMapping

from PySide6.QtCore import QObject, QThread


BackgroundJob = tuple[QThread, QObject]
BackgroundJobs = MutableMapping[int, BackgroundJob]


def start_background_job(
    *,
    parent: QObject,
    request_id: int,
    worker: QObject,
    jobs: BackgroundJobs,
    on_thread_finished: Callable[[], None],
) -> QThread:
    """Start and retain one Qt worker until its native thread has stopped.

    Task-specific signals must be connected before calling this function.
    Keeping thread setup here ensures every background operation follows the
    same shutdown order and cannot lose its Python references prematurely.
    """

    if request_id in jobs:
        raise ValueError(f"Background request already exists: {request_id}")
    run = getattr(worker, "run", None)
    finished = getattr(worker, "finished", None)
    if not callable(run) or finished is None:
        raise TypeError("Background workers require run() and finished.")

    thread = QThread(parent)
    jobs[request_id] = (thread, worker)
    worker.moveToThread(thread)
    thread.started.connect(run)
    finished.connect(thread.quit)
    finished.connect(worker.deleteLater)
    thread.finished.connect(on_thread_finished)
    thread.finished.connect(thread.deleteLater)
    thread.start()
    return thread
