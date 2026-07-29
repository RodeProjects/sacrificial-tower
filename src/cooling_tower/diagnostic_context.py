from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from threading import local
from typing import Any


DiagnosticCallback = Callable[[str], None]
_CONTEXT = local()


@contextmanager
def diagnostic_scope(
    callback: Callable[..., None] | None,
) -> Iterator[None]:
    """Bind one job's diagnostic sink to the current worker thread."""

    previous = getattr(_CONTEXT, "callback", None)
    _CONTEXT.callback = callback
    try:
        yield
    finally:
        _CONTEXT.callback = previous


def record_diagnostic(event: str, **details: Any) -> None:
    """Record a domain event when the current operation has a job context."""

    callback = getattr(_CONTEXT, "callback", None)
    if callback is not None:
        callback(event, **details)
