from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cooling_tower.gui.job_stress import SCENARIOS
from cooling_tower.slicers.process import _terminate_windows_process_tree
from cooling_tower.windows_process import windows_subprocess_creation_flags


class IsolatedProcessStressTests(unittest.TestCase):
    def test_each_native_qt_stress_scenario_runs_in_its_own_process(self) -> None:
        seed = int(os.environ.get("COOLING_TOWER_STRESS_SEED", "1729"))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = os.environ.copy()
            environment["QT_QPA_PLATFORM"] = "offscreen"
            environment["PYTHONUTF8"] = "1"
            environment["PYTHONPATH"] = os.pathsep.join(
                (
                    str(SRC_ROOT),
                    environment.get("PYTHONPATH", ""),
                )
            )
            for scenario in SCENARIOS:
                with self.subTest(scenario=scenario, seed=seed):
                    artifact_directory = root / scenario
                    command = (
                        sys.executable,
                        "-B",
                        "-m",
                        "cooling_tower.gui.job_stress",
                        "--scenario",
                        scenario,
                        "--artifact-directory",
                        str(artifact_directory),
                        "--seed",
                        str(seed),
                    )
                    process = subprocess.Popen(
                        command,
                        cwd=PROJECT_ROOT,
                        env=environment,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        creationflags=windows_subprocess_creation_flags(
                            getattr(subprocess, "CREATE_NO_WINDOW", 0)
                        ),
                    )
                    try:
                        stdout, stderr = process.communicate(timeout=90)
                    except subprocess.TimeoutExpired:
                        if os.name == "nt":
                            _terminate_windows_process_tree(process.pid)
                        else:
                            process.kill()
                        try:
                            stdout, stderr = process.communicate(timeout=5)
                        except subprocess.TimeoutExpired:
                            stdout = ""
                            stderr = "process tree did not close after timeout"
                        result_path = artifact_directory / "result.json"
                        result = (
                            result_path.read_text(
                                encoding="utf-8",
                                errors="replace",
                            )
                            if result_path.exists()
                            else "result.json missing"
                        )
                        native_log = artifact_directory / "native_crash.log"
                        native_details = (
                            native_log.read_text(
                                encoding="utf-8",
                                errors="replace",
                            )
                            if native_log.exists()
                            else "native_crash.log missing"
                        )
                        self.fail(
                            f"Scenario {scenario!r} timed out with seed {seed}.\n"
                            f"stdout:\n{stdout}\n"
                            f"stderr:\n{stderr}\n"
                            f"result:\n{result}\n"
                            f"native log:\n{native_details}"
                        )
                    completed = subprocess.CompletedProcess(
                        command,
                        process.returncode,
                        stdout,
                        stderr,
                    )
                    result_path = artifact_directory / "result.json"
                    result = (
                        json.loads(result_path.read_text(encoding="utf-8"))
                        if result_path.exists()
                        else {}
                    )
                    self.assertEqual(
                        completed.returncode,
                        0,
                        (
                            f"Scenario {scenario!r} failed with seed {seed}.\n"
                            f"stdout:\n{completed.stdout}\n"
                            f"stderr:\n{completed.stderr}\n"
                            f"result:\n{result}"
                        ),
                    )
                    self.assertTrue(result.get("complete_marker"), result)
                    self.assertEqual(result.get("active_job_count"), 0, result)
                    self.assertFalse(result.get("orphan_child_process"), result)
                    state = json.loads(
                        (artifact_directory / "session.json").read_text(
                            encoding="utf-8"
                        )
                    )
                    self.assertTrue(state["clean_shutdown"], state)
                    native_crash_log = (
                        artifact_directory / "native_crash.log"
                    ).read_text(encoding="utf-8", errors="replace")
                    self.assertIn("application session started", native_crash_log)
                    self.assertIn(
                        "stress process ended without native crash",
                        native_crash_log,
                    )
                    critical_messages = []
                    lifecycle_warnings = []
                    for path in artifact_directory.glob("diagnostics.jsonl*"):
                        for line in path.read_text(
                            encoding="utf-8",
                            errors="replace",
                        ).splitlines():
                            try:
                                entry = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            if (
                                entry.get("event") == "qt_message"
                                and entry.get("priority") == "critical"
                            ):
                                critical_messages.append(entry)
                            message = str(entry.get("message", ""))
                            if (
                                entry.get("event") == "qt_message"
                                and entry.get("priority") in {"warning", "critical"}
                                and any(
                                    marker in message
                                    for marker in (
                                        "QObject::",
                                        "QProcess:",
                                        "QSocketNotifier:",
                                        "QThread:",
                                        "Timers cannot",
                                    )
                                )
                            ):
                                lifecycle_warnings.append(entry)
                    self.assertEqual(critical_messages, [])
                    self.assertEqual(lifecycle_warnings, [])
                    if scenario == "shutdown_timeout":
                        self.assertTrue(result.get("timeout_observed"), result)


if __name__ == "__main__":
    unittest.main()
