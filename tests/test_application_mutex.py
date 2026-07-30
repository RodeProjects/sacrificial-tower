from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cooling_tower.application_mutex import (
    APPLICATION_MUTEX_NAME,
    ERROR_ALREADY_EXISTS,
    SW_RESTORE,
    ApplicationAlreadyRunningError,
    activate_running_application_window,
    acquire_application_mutex,
    release_application_mutex,
)
from cooling_tower.application import run_application


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


class _FakeUser32:
    def __init__(self, *, window_handle=321, iconic=True) -> None:
        self.FindWindowW = _FakeFunction(window_handle)
        self.IsIconic = _FakeFunction(iconic)
        self.ShowWindow = _FakeFunction(True)
        self.BringWindowToTop = _FakeFunction(True)
        self.SetForegroundWindow = _FakeFunction(True)
        self.FlashWindow = _FakeFunction(True)


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
            patch(
                "cooling_tower.application_mutex.ctypes.get_last_error",
                return_value=0,
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

    @unittest.skipUnless(sys.platform == "win32", "benötigt Windows")
    def test_real_windows_kernel_rejects_a_second_named_mutex_owner(self) -> None:
        mutex_name = f"SacrificialTower-Test-{uuid.uuid4()}"
        first_handle = acquire_application_mutex(mutex_name)
        try:
            with self.assertRaises(ApplicationAlreadyRunningError):
                acquire_application_mutex(mutex_name)
        finally:
            release_application_mutex(first_handle)

    def test_existing_mutex_closes_duplicate_handle_and_stops_startup(self) -> None:
        kernel32 = _FakeKernel32(mutex_handle=456)
        with (
            patch("cooling_tower.application_mutex.os.name", "nt"),
            patch(
                "cooling_tower.application_mutex.ctypes.WinDLL",
                return_value=kernel32,
                create=True,
            ),
            patch(
                "cooling_tower.application_mutex.ctypes.get_last_error",
                return_value=ERROR_ALREADY_EXISTS,
            ),
        ):
            with self.assertRaises(ApplicationAlreadyRunningError):
                acquire_application_mutex()

        self.assertEqual(kernel32.CloseHandle.calls, [(456,)])

    def test_existing_minimized_window_is_restored_and_foregrounded(self) -> None:
        user32 = _FakeUser32(iconic=True)
        with (
            patch("cooling_tower.application_mutex.os.name", "nt"),
            patch(
                "cooling_tower.application_mutex.ctypes.WinDLL",
                return_value=user32,
                create=True,
            ),
        ):
            activated = activate_running_application_window(
                "Kühlturm-Generator",
                timeout_ms=0,
            )

        self.assertTrue(activated)
        self.assertEqual(
            user32.FindWindowW.calls,
            [(None, "Kühlturm-Generator")],
        )
        self.assertEqual(user32.ShowWindow.calls, [(321, SW_RESTORE)])
        self.assertEqual(user32.BringWindowToTop.calls, [(321,)])
        self.assertEqual(user32.SetForegroundWindow.calls, [(321,)])
        self.assertEqual(user32.FlashWindow.calls, [])

    def test_second_run_activates_existing_window_without_building_another(self) -> None:
        window_factory = Mock()
        with (
            patch(
                "cooling_tower.application.acquire_application_mutex",
                side_effect=ApplicationAlreadyRunningError,
            ),
            patch(
                "cooling_tower.application.activate_running_application_window"
            ) as activate,
        ):
            result = run_application(window_factory=window_factory)

        self.assertEqual(result, 0)
        activate.assert_called_once_with("Kühlturm-Generator")
        window_factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
