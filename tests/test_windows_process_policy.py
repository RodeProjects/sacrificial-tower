from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import cooling_tower.windows_process as windows_process
from cooling_tower.windows_process import (
    CREATE_DEFAULT_ERROR_MODE,
    WER_FAULT_REPORTING_NO_UI,
    WINDOWS_DLL_INITIALIZATION_FAILED,
    WINDOWS_PROCESS_ERROR_MODE_FLAGS,
    configure_windows_process_policy,
    windows_process_status,
    windows_process_status_description,
    windows_subprocess_creation_flags,
)


def _fake_kernel32(
    *,
    process_mode: int = 0,
    wer_flags: int = 0,
) -> MagicMock:
    kernel32 = MagicMock()
    state = {
        "process_mode": int(process_mode),
        "wer_flags": int(wer_flags),
    }

    kernel32.GetErrorMode.side_effect = lambda: state["process_mode"]

    def set_error_mode(value: int) -> int:
        previous = state["process_mode"]
        state["process_mode"] = int(value)
        return previous

    kernel32.SetErrorMode.side_effect = set_error_mode
    kernel32.GetCurrentProcess.return_value = -1

    def get_wer_flags(_process, destination) -> int:
        destination._obj.value = state["wer_flags"]
        return 0

    kernel32.WerGetFlags.side_effect = get_wer_flags

    def set_wer_flags(value: int) -> int:
        state["wer_flags"] = int(value)
        return 0

    kernel32.WerSetFlags.side_effect = set_wer_flags
    kernel32._policy_state = state
    return kernel32


class WindowsProcessPolicyUnitTests(unittest.TestCase):
    def test_policy_preserves_existing_flags_and_is_idempotent(self) -> None:
        kernel32 = _fake_kernel32(process_mode=0x0004, wer_flags=0x0008)
        with (
            patch.object(windows_process.os, "name", "nt"),
            patch.object(windows_process, "_POLICY_STATE", None),
            patch.object(
                windows_process,
                "_load_kernel32",
                return_value=kernel32,
            ) as loader,
        ):
            first = configure_windows_process_policy()
            second = configure_windows_process_policy()

        self.assertTrue(first.active, first)
        self.assertIs(first, second)
        self.assertEqual(
            first.process_error_mode,
            0x0004 | WINDOWS_PROCESS_ERROR_MODE_FLAGS,
        )
        self.assertEqual(first.wer_flags, 0x0008 | WER_FAULT_REPORTING_NO_UI)
        self.assertEqual(first.errors, ())
        loader.assert_called_once_with()

    def test_incomplete_setup_is_reported_and_retried(self) -> None:
        failing = _fake_kernel32()
        failing.WerGetFlags.side_effect = lambda _process, _destination: -1
        working = _fake_kernel32()
        with (
            patch.object(windows_process.os, "name", "nt"),
            patch.object(windows_process, "_POLICY_STATE", None),
            patch.object(
                windows_process,
                "_load_kernel32",
                side_effect=(failing, working),
            ) as loader,
        ):
            first = configure_windows_process_policy()
            second = configure_windows_process_policy()

        self.assertFalse(first.active)
        self.assertIn("wer_get_flags_failed_0xFFFFFFFF", first.errors)
        self.assertTrue(second.active, second)
        self.assertEqual(loader.call_count, 2)

    def test_unconfigured_wer_state_is_initialized_and_verified(self) -> None:
        kernel32 = _fake_kernel32()
        normal_get_flags = kernel32.WerGetFlags.side_effect
        results = iter((0x80070490, 0))

        def get_flags(process, destination) -> int:
            result = next(results)
            if result == 0:
                normal_get_flags(process, destination)
            return result

        kernel32.WerGetFlags.side_effect = get_flags
        with (
            patch.object(windows_process.os, "name", "nt"),
            patch.object(windows_process, "_POLICY_STATE", None),
            patch.object(
                windows_process,
                "_load_kernel32",
                return_value=kernel32,
            ),
        ):
            state = configure_windows_process_policy()
        self.assertTrue(state.active, state)
        kernel32.WerSetFlags.assert_called_once_with(
            WER_FAULT_REPORTING_NO_UI
        )

    def test_non_windows_setup_is_a_noop(self) -> None:
        with (
            patch.object(windows_process.os, "name", "posix"),
            patch.object(windows_process, "_POLICY_STATE", None),
            patch.object(windows_process, "_load_kernel32") as loader,
        ):
            state = configure_windows_process_policy()
        self.assertFalse(state.is_windows)
        self.assertFalse(state.active)
        self.assertEqual(state.errors, ())
        loader.assert_not_called()

    def test_creation_flags_cannot_disable_policy_inheritance(self) -> None:
        with self.assertRaisesRegex(ValueError, "CREATE_DEFAULT_ERROR_MODE"):
            windows_subprocess_creation_flags(CREATE_DEFAULT_ERROR_MODE)

    def test_known_and_unknown_ntstatus_values_remain_visible(self) -> None:
        with patch.object(windows_process.os, "name", "nt"):
            self.assertEqual(
                windows_process_status(-1073741502),
                "0xC0000142",
            )
            self.assertEqual(
                windows_process_status_description(-1073741502),
                "DLL-Initialisierung fehlgeschlagen",
            )
            self.assertEqual(
                windows_process_status(WINDOWS_DLL_INITIALIZATION_FAILED),
                "0xC0000142",
            )
            self.assertIsNone(windows_process_status_description(0xC0000999))
            self.assertIsNone(windows_process_status(7))
            for code in (-1, -17, -50, -100, 0xFFFFFF9C):
                self.assertIsNone(windows_process_status(code))

    def test_all_product_subprocess_launchers_use_safe_creation_flags(self) -> None:
        managed_launchers = (
            PROJECT_ROOT / "start_gui.pyw",
            SRC_ROOT / "cooling_tower" / "update_installation.py",
            SRC_ROOT / "cooling_tower" / "slicers" / "discovery.py",
            SRC_ROOT / "cooling_tower" / "slicers" / "process.py",
        )
        for path in managed_launchers:
            with self.subTest(path=path):
                content = path.read_text(encoding="utf-8")
                self.assertIn("windows_subprocess_creation_flags", content)
                self.assertNotIn("CREATE_DEFAULT_ERROR_MODE", content)


@unittest.skipUnless(os.name == "nt", "Windows process policy")
class WindowsProcessPolicyIntegrationTests(unittest.TestCase):
    def test_live_process_policy_is_fully_active(self) -> None:
        state = configure_windows_process_policy()
        self.assertTrue(state.active, state)
        self.assertEqual(
            int(state.process_error_mode) & WINDOWS_PROCESS_ERROR_MODE_FLAGS,
            WINDOWS_PROCESS_ERROR_MODE_FLAGS,
        )
        self.assertEqual(
            int(state.wer_flags) & WER_FAULT_REPORTING_NO_UI,
            WER_FAULT_REPORTING_NO_UI,
        )

    def test_direct_python_child_inherits_process_error_mode(self) -> None:
        code = (
            "import ctypes; "
            "print(int(ctypes.windll.kernel32.GetErrorMode()))"
        )
        completed = subprocess.run(
            [sys.executable, "-B", "-c", code],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            creationflags=windows_subprocess_creation_flags(
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
            ),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        child_mode = int(completed.stdout.strip())
        self.assertEqual(
            child_mode & WINDOWS_PROCESS_ERROR_MODE_FLAGS,
            WINDOWS_PROCESS_ERROR_MODE_FLAGS,
        )

    def test_direct_python_ntstatus_is_returned_without_blocking_ui(self) -> None:
        code = "\n".join(
            (
                "import ctypes",
                "exit_process = ctypes.windll.kernel32.ExitProcess",
                "exit_process.argtypes = (ctypes.c_uint32,)",
                "exit_process(0xC0000142)",
            )
        )
        completed = subprocess.run(
            [sys.executable, "-B", "-c", code],
            cwd=PROJECT_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
            creationflags=windows_subprocess_creation_flags(
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
            ),
        )
        self.assertEqual(
            windows_process_status(completed.returncode),
            "0xC0000142",
        )

    def test_sitecustomize_reapplies_policy_before_test_discovery(self) -> None:
        code = "\n".join(
            (
                "import ctypes",
                "import importlib",
                "import sitecustomize",
                "kernel32 = ctypes.windll.kernel32",
                "kernel32.SetErrorMode(0)",
                "importlib.reload(sitecustomize)",
                "print(int(kernel32.GetErrorMode()))",
            )
        )
        completed = subprocess.run(
            [sys.executable, "-B", "-c", code],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            creationflags=windows_subprocess_creation_flags(
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
            ),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        reapplied_mode = int(completed.stdout.strip())
        self.assertEqual(
            reapplied_mode & WINDOWS_PROCESS_ERROR_MODE_FLAGS,
            WINDOWS_PROCESS_ERROR_MODE_FLAGS,
        )


if __name__ == "__main__":
    unittest.main()
