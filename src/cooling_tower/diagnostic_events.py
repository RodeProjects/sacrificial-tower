from __future__ import annotations


DIAGNOSTIC_EVENT_SCHEMA_VERSION = 1


def exception_error_code(operation: str, error: BaseException) -> str:
    """Return a stable, non-sensitive error code for support diagnostics."""

    normalized_operation = str(operation).strip().casefold().replace("-", "_")
    if isinstance(error, FileNotFoundError):
        suffix = "file_not_found"
    elif isinstance(error, PermissionError):
        suffix = "access_denied"
    elif isinstance(error, TimeoutError):
        suffix = "timeout"
    elif isinstance(error, UnicodeError):
        suffix = "encoding_error"
    elif isinstance(error, OSError):
        suffix = "io_error"
    elif isinstance(error, ValueError):
        suffix = "invalid_data"
    elif isinstance(error, RuntimeError):
        suffix = "runtime_error"
    else:
        suffix = "unexpected_error"
    return f"{normalized_operation}_{suffix}"
