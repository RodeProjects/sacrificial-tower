from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cooling_tower.application_mutex import (
    APPLICATION_MUTEX_NAME,
    acquire_application_mutex,
    release_application_mutex,
)


class _FakeFunction:
    def __init__(self, result) -> None:
        self.result = result
        self.calls = []
        self.argtypes = None
        self.restype = None

    def __call__(self, *arguments):
        self.calls.append(arguments)
        return self.result


class _FakeKernel32:
    def __init__(self, *, mutex_handle=123, close_result=True) -> None:
        self.CreateMutexW = _FakeFunction(mutex_handle)
        self.CloseHandle = _FakeFunction(close_result)


class ApplicationMutexTests(unittest.TestCase):
    def test_non_windows_platform_does_not_create_a_mutex(self) -> None:
        with (
            patch("cooling_tower.application_mutex.os.name", "posix"),
            patch("cooling_tower.application_mutex.ctypes.WinDLL") as win_dll,
        ):
            self.assertIsNone(acquire_application_mutex())
            release_application_mutex(None)
        win_dll.assert_not_called()

    def test_windows_mutex_uses_the_installer_name_and_releases_handle(self) -> None:
        kernel32 = _FakeKernel32()
        with (
            patch("cooling_tower.application_mutex.os.name", "nt"),
            patch(
                "cooling_tower.application_mutex.ctypes.WinDLL",
                return_value=kernel32,
                create=True,
            ),
        ):
            handle = acquire_application_mutex()
            release_application_mutex(handle)

        self.assertEqual(handle, 123)
        self.assertEqual(
            kernel32.CreateMutexW.calls,
            [(None, False, APPLICATION_MUTEX_NAME)],
        )
        self.assertEqual(kernel32.CloseHandle.calls, [(123,)])

    def test_windows_api_failures_are_reported(self) -> None:
        kernel32 = _FakeKernel32(mutex_handle=None)
        with (
            patch("cooling_tower.application_mutex.os.name", "nt"),
            patch(
                "cooling_tower.application_mutex.ctypes.WinDLL",
                return_value=kernel32,
                create=True,
            ),
            patch(
                "cooling_tower.application_mutex.ctypes.get_last_error",
                return_value=5,
            ),
        ):
            with self.assertRaises(OSError):
                acquire_application_mutex()


if __name__ == "__main__":
    unittest.main()
